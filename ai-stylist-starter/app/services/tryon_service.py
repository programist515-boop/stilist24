"""Try-on orchestration service.

Pipeline (single-item, synchronous):

1. Load the user photo by id and verify ownership.
2. Load the wardrobe item by id and verify ownership.
3. Resolve usable image URLs for both assets (prefer ``image_url``,
   fall back to a URL projected from ``image_key`` via the storage
   service).
4. Persist a ``pending`` ``TryOnJob`` row so failures still leave a trace.
5. Call the FASHN adapter (provider logic is fully isolated).
6. Receive a ``FashnResult`` with the generated image bytes.
7. Store the bytes through the storage service under a deterministic key
   tied to the DB job id.
8. Mark the job as ``succeeded`` and return a structured response.

Errors are typed so the route layer can map them to HTTP status codes
without doing any business logic.

The service follows the same dependency-injection seam pattern as
``TodayService`` and ``InsightsService``: every collaborator (loaders,
repository, storage, adapter) can be replaced with a stub for tests, and
SQLAlchemy is only imported under :data:`TYPE_CHECKING` so the module is
importable in environments without it.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from app.core.storage import (
    StorageError,
    StorageService,
    StorageValidationError,
)
from app.services.fashn_adapter import (
    FashnAdapter,
    FashnAdapterError,
    FashnResult,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from app.models.tryon_job import TryOnJob
    from app.models.user_photo import UserPhoto
    from app.models.wardrobe_item import WardrobeItem
    from app.repositories.tryon_repository import TryOnRepository


# ---------------------------------------------------------------- constants


TRY_ON_DISCLAIMER = (
    "Visual simulation only — not an exact fit prediction."
)
PROVIDER_FASHN = "fashn"


# ---------------------------------------------------------------- errors


class TryOnError(Exception):
    """Base class for try-on service errors."""


class TryOnNotFoundError(TryOnError):
    """A referenced asset (wardrobe item or user photo) does not exist."""


class TryOnAssetError(TryOnError):
    """A referenced asset exists but is missing the data we need."""


class TryOnProviderError(TryOnError):
    """The FASHN provider failed."""


class TryOnStorageError(TryOnError):
    """Storage of the generated result image failed."""


class TryOnPersistenceError(TryOnError):
    """Persisting the success transition failed."""


# ---------------------------------------------------------------- service


WardrobeLoader = Callable[[uuid.UUID], "WardrobeItem | None"]
PhotoLoader = Callable[[uuid.UUID], "UserPhoto | None"]
AdapterCall = Callable[..., Awaitable[FashnResult]]


class TryOnService:
    def __init__(
        self,
        db: "Session | None" = None,
        *,
        wardrobe_loader: WardrobeLoader | None = None,
        photo_loader: PhotoLoader | None = None,
        tryon_repo: "TryOnRepository | None" = None,
        storage: StorageService | None = None,
        adapter: FashnAdapter | None = None,
        provider: str = PROVIDER_FASHN,
    ) -> None:
        self.db = db
        self._wardrobe_loader = wardrobe_loader
        self._photo_loader = photo_loader
        self._tryon_repo = tryon_repo
        self._storage = storage
        self._adapter = adapter
        self._provider = provider

    # ----- collaborators (lazy defaults) ---------------------------------

    def _load_wardrobe(self, item_id: uuid.UUID) -> "WardrobeItem | None":
        if self._wardrobe_loader is not None:
            return self._wardrobe_loader(item_id)
        from app.repositories.wardrobe_repository import WardrobeRepository  # lazy

        return WardrobeRepository(self.db).get_by_id(item_id)

    def _load_photo(self, photo_id: uuid.UUID) -> "UserPhoto | None":
        if self._photo_loader is not None:
            return self._photo_loader(photo_id)
        from app.repositories.user_photo_repository import UserPhotoRepository  # lazy

        return UserPhotoRepository(self.db).get_by_id(photo_id)

    def _get_tryon_repo(self) -> "TryOnRepository":
        if self._tryon_repo is not None:
            return self._tryon_repo
        from app.repositories.tryon_repository import TryOnRepository  # lazy

        repo = TryOnRepository(self.db)
        self._tryon_repo = repo
        return repo

    def _get_storage(self) -> StorageService:
        if self._storage is not None:
            return self._storage
        return StorageService()

    def _get_adapter(self) -> FashnAdapter:
        if self._adapter is not None:
            return self._adapter
        return FashnAdapter()

    # ----- pure helpers --------------------------------------------------

    @staticmethod
    def _resolve_url(asset: Any, storage: StorageService) -> str | None:
        """Pick a usable URL for an asset (wardrobe item or user photo).

        Prefers the stored ``image_url`` because it has already been built by
        the storage layer at upload time. Falls back to a freshly projected
        URL from ``image_key`` for cases where the URL was never persisted
        (e.g. legacy rows).
        """
        url = getattr(asset, "image_url", None)
        if url:
            return url
        key = getattr(asset, "image_key", None)
        if key:
            try:
                return storage.public_url(key)
            except Exception:
                return None
        return None

    # ----- public API ----------------------------------------------------

    async def generate(
        self,
        *,
        user_id: uuid.UUID,
        item_id: uuid.UUID,
        user_photo_id: uuid.UUID,
    ) -> dict:
        repo = self._get_tryon_repo()
        storage = self._get_storage()
        adapter = self._get_adapter()

        # 1. Load user photo + ownership check.
        photo = self._load_photo(user_photo_id)
        if photo is None or getattr(photo, "user_id", None) != user_id:
            raise TryOnNotFoundError("user photo not found")

        # 2. Load wardrobe item + ownership check.
        item = self._load_wardrobe(item_id)
        if item is None or getattr(item, "user_id", None) != user_id:
            raise TryOnNotFoundError("wardrobe item not found")

        # 3. Resolve usable image URLs.
        person_url = self._resolve_url(photo, storage)
        if not person_url:
            raise TryOnAssetError("user photo image is missing")
        garment_url = self._resolve_url(item, storage)
        if not garment_url:
            raise TryOnAssetError("wardrobe image is missing")

        # 4. Persist a pending job row up front so failures are observable.
        job_id = uuid.uuid4()
        job = repo.create_pending(
            user_id=user_id,
            item_id=item_id,
            user_photo_id=user_photo_id,
            provider=self._provider,
            job_id=job_id,
        )
        # Trust the value the repository echoed back so tests that hand us a
        # fake repo can override the id without needing to honour the kwarg.
        job_id = getattr(job, "id", job_id)

        # 5. Call the provider.
        try:
            result: FashnResult = await adapter.generate_tryon(
                person_image_url=person_url,
                garment_image_url=garment_url,
                garment_category=getattr(item, "category", None),
            )
        except FashnAdapterError as exc:
            self._safe_mark_failed(repo, job_id, f"provider error: {exc}")
            raise TryOnProviderError(str(exc)) from exc

        # 6/7. Store the generated bytes through the storage service.
        try:
            asset = storage.upload_tryon_result(
                user_id,
                job_id,
                data=result.image_bytes,
                content_type=result.content_type,
            )
        except (StorageError, StorageValidationError) as exc:
            self._safe_mark_failed(repo, job_id, f"storage error: {exc}")
            raise TryOnStorageError(str(exc)) from exc

        # 8. Persist the success transition.
        try:
            updated = repo.mark_succeeded(
                job_id,
                result_image_key=asset.key,
                result_image_url=asset.url,
                metadata=self._safe_metadata(result),
                provider_job_id=result.provider_job_id,
            )
        except Exception as exc:
            self._safe_mark_failed(repo, job_id, f"persistence error: {exc}")
            raise TryOnPersistenceError(str(exc)) from exc

        return self._build_response(updated or job, asset, result)

    # ----- response builder ----------------------------------------------

    def _build_response(
        self,
        job: Any,
        asset: Any,
        result: FashnResult,
    ) -> dict:
        return {
            "job_id": str(getattr(job, "id", "")),
            "status": getattr(job, "status", "succeeded"),
            "provider": getattr(job, "provider", self._provider),
            "provider_job_id": result.provider_job_id,
            "result_image_key": asset.key,
            "result_image_url": asset.url,
            "metadata": self._safe_metadata(result),
            "note": TRY_ON_DISCLAIMER,
        }

    # ----- helpers -------------------------------------------------------

    @staticmethod
    def _safe_metadata(result: FashnResult) -> dict:
        raw = result.raw if isinstance(result.raw, dict) else {}
        return {
            "provider_image_url": result.image_url,
            "provider_content_type": result.content_type,
            "provider_raw": raw,
        }

    @staticmethod
    def _safe_mark_failed(
        repo: "TryOnRepository",
        job_id: uuid.UUID,
        message: str,
    ) -> None:
        try:
            repo.mark_failed(job_id, error_message=message)
        except Exception:  # pragma: no cover - cleanup is best effort
            pass


__all__ = [
    "PROVIDER_FASHN",
    "TRY_ON_DISCLAIMER",
    "TryOnAssetError",
    "TryOnError",
    "TryOnNotFoundError",
    "TryOnPersistenceError",
    "TryOnProviderError",
    "TryOnService",
    "TryOnStorageError",
]
