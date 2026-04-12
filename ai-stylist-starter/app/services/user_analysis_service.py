"""User analysis orchestration service.

Pipeline (synchronous):

1. Validate the uploaded photo set:
   - exactly 3 uploads
   - unique slots
   - exact slot set = {front, side, portrait}
2. For each slot (in canonical order ``front`` → ``side`` → ``portrait``):
   a. Mint a new ``photo_id`` up front (so the storage key is deterministic
      and matches the DB row).
   b. Upload the bytes through :class:`StorageService.upload_user_photo`.
   c. Persist a ``UserPhoto`` row via :class:`UserPhotoRepository.create`.
3. Compute the feature vector (currently a static stub — see
   :func:`_stub_features`; real CV lives in a later step).
4. Run :class:`IdentityEngine` and :class:`ColorEngine` on the feature
   vector and a hardcoded color-axes dict (also stubbed).
5. Return a response with ``kibbe``, ``color``, ``style_vector``,
   ``analyzed_at``, and ``photos`` (always in canonical slot order).

Partial-failure contract
------------------------

Photo persistence is upload-first, DB-row-after. If storage fails on the
second slot, the first slot's bytes remain in storage but no DB row points
at them. This is acceptable because:

* storage is the source of truth for bytes (``image_key`` is the canonical
  reference)
* orphan keys are cheap and can be garbage-collected out-of-band
* DB consistency is strictly more important than storage tidiness — we
  never want a row pointing at bytes that are not there

The service follows the same dependency-injection seam pattern as
``TryOnService`` / ``TodayService`` / ``InsightsService``: every
collaborator (storage, repository factory, feature extractor, engines)
can be replaced with a stub for tests, and SQLAlchemy is only imported
under :data:`TYPE_CHECKING` so the module is importable in environments
without it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from app.core.storage import (
    StorageError,
    StorageService,
    StorageValidationError,
)
from app.services.color_engine import ColorEngine
from app.services.feature_extractor import (
    PhotoReference,
    default_feature_extractor,
)
from app.services.identity_engine import IdentityEngine

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from app.repositories.user_photo_repository import UserPhotoRepository


# ---------------------------------------------------------------- constants


#: Canonical slot order. Both input validation and response serialisation
#: rely on this tuple — never iterate over a dict or a set here.
SLOT_ORDER: tuple[str, ...] = ("front", "side", "portrait")
_ALLOWED_SLOTS: frozenset[str] = frozenset(SLOT_ORDER)


# ---------------------------------------------------------------- errors


class UserAnalysisError(Exception):
    """Base class for user-analysis service errors."""


class UserAnalysisValidationError(UserAnalysisError):
    """The caller-supplied upload set is malformed (slots, count, duplicates)."""


class UserAnalysisStorageError(UserAnalysisError):
    """Persisting the uploaded photo bytes to storage failed."""


class UserAnalysisPersistenceError(UserAnalysisError):
    """Writing the ``user_photos`` row failed after a successful upload."""


# ---------------------------------------------------------------- input dataclass


@dataclass(frozen=True)
class AnalysisPhotoUpload:
    """An already-read photo upload ready to hand to the service.

    The route layer calls ``await file.read()`` once and wraps the bytes in
    this dataclass so the service is fully synchronous and never has to
    touch FastAPI's :class:`UploadFile`.
    """

    slot: str
    data: bytes
    content_type: str
    filename: str | None = None


# ---------------------------------------------------------------- stub feature vector


def _stub_features() -> dict[str, float]:
    """Emergency fallback user feature vector.

    Originally the one-and-only feature source, now retained as a safety
    net in case :class:`StructuredFeatureExtractor` raises. The service
    catches any exception from the extractor seam and falls back to this
    function so ``/user/analyze`` never 500s on a placeholder bug.

    The key set here must remain identical to
    :data:`app.services.feature_extractor.SCHEMA_KEYS` — the contract is
    enforced by ``test_stub_features_has_all_20_keys``.
    """
    return {
        "vertical_line": 0.42,
        "compactness": 0.71,
        "width": 0.40,
        "bone_sharpness": 0.31,
        "bone_bluntness": 0.22,
        "softness": 0.74,
        "curve_presence": 0.69,
        "symmetry": 0.44,
        "facial_sharpness": 0.28,
        "facial_roundness": 0.67,
        "waist_definition": 0.73,
        "narrowness": 0.40,
        "relaxed_line": 0.20,
        "proportion_balance": 0.45,
        "moderation": 0.40,
        "line_contrast": 0.61,
        "small_scale": 0.66,
        "feature_juxtaposition": 0.58,
        "controlled_softness_or_sharpness": 0.33,
        "low_line_contrast": 0.39,
    }


def _stub_color_axes() -> dict[str, str]:
    """Return the hardcoded color axes used until CV lands."""
    return {
        "undertone": "cool-neutral",
        "contrast": "medium-low",
        "depth": "medium",
        "chroma": "soft",
    }


def _stub_style_vector() -> dict[str, float]:
    """Return the hardcoded style vector used until CV lands."""
    return {"classic": 0.4, "romantic": 0.35, "natural": 0.25}


# ---------------------------------------------------------------- service


#: Seam signature for feature extraction. Takes the acting user id and
#: the canonical-order list of persisted photo references, returns the
#: 20-key feature vector. The default implementation is
#: :func:`app.services.feature_extractor.default_feature_extractor`.
FeatureExtractor = Callable[
    [uuid.UUID, list[PhotoReference]], dict[str, float]
]
UserPhotoRepoFactory = Callable[["Session"], "UserPhotoRepository"]
NowFactory = Callable[[], datetime]


class UserAnalysisService:
    """Persist user reference photos and compute identity/color analysis.

    Collaborators
    -------------
    * ``storage`` — a :class:`StorageService` that writes to the configured
      backend. Defaults to a freshly constructed instance.
    * ``photo_repo_factory`` — builds a :class:`UserPhotoRepository` from a
      ``Session``. Defaults to the real repository, lazily imported so
      tests can skip SQLAlchemy entirely.
    * ``feature_extractor`` — returns the user feature vector. Defaults to
      :func:`_stub_features`. This is the *one* seam the upcoming CV step
      will hook into.
    * ``identity_engine`` / ``color_engine`` — already testable, constructed
      once per request if not supplied.
    * ``now`` — ``datetime`` factory so ``analyzed_at`` is deterministic in
      tests.
    """

    def __init__(
        self,
        db: "Session | None" = None,
        *,
        storage: StorageService | None = None,
        photo_repo_factory: UserPhotoRepoFactory | None = None,
        feature_extractor: FeatureExtractor | None = None,
        identity_engine: IdentityEngine | None = None,
        color_engine: ColorEngine | None = None,
        now: NowFactory | None = None,
    ) -> None:
        self.db = db
        self._storage = storage
        self._photo_repo_factory = photo_repo_factory
        self._feature_extractor = feature_extractor
        self._identity_engine = identity_engine
        self._color_engine = color_engine
        self._now = now

    # ----- collaborators (lazy defaults) ---------------------------------

    def _get_storage(self) -> StorageService:
        if self._storage is not None:
            return self._storage
        return StorageService()

    def _get_photo_repo(self) -> "UserPhotoRepository":
        if self._photo_repo_factory is not None:
            return self._photo_repo_factory(self.db)  # type: ignore[arg-type]
        from app.repositories.user_photo_repository import (  # lazy
            UserPhotoRepository,
        )

        return UserPhotoRepository(self.db)  # type: ignore[arg-type]

    def _get_features(
        self,
        user_id: uuid.UUID,
        photos: list[PhotoReference],
    ) -> dict[str, float]:
        """Run the feature extractor seam with an emergency fallback.

        If the extractor raises (buggy heuristic, drifted schema, etc.)
        we fall back to :func:`_stub_features` so the request still
        produces a valid response. The placeholder extractor is *not*
        on the hot path for correctness — it must not 500 the route.
        """
        extractor = self._feature_extractor or default_feature_extractor
        try:
            return extractor(user_id, photos)
        except Exception:
            return _stub_features()

    def _get_identity_engine(self) -> IdentityEngine:
        if self._identity_engine is not None:
            return self._identity_engine
        return IdentityEngine()

    def _get_color_engine(self) -> ColorEngine:
        if self._color_engine is not None:
            return self._color_engine
        return ColorEngine()

    def _get_now(self) -> datetime:
        if self._now is not None:
            return self._now()
        return datetime.now(timezone.utc)

    def _persist_style_profile(
        self,
        user_id: uuid.UUID,
        *,
        kibbe_type: str | None,
        kibbe_confidence: float | None,
        color_profile: dict | None,
        style_vector: dict | None,
    ) -> None:
        """Upsert a ``StyleProfile`` row so downstream features can read it.

        Uses a Postgres ``INSERT … ON CONFLICT DO UPDATE`` so a second
        analysis overwrites the previous one atomically. If there is no
        DB session (unit-test mode with ``db=None``), we silently skip.
        """
        if self.db is None:
            return
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.models.style_profile import StyleProfile  # lazy

        stmt = (
            pg_insert(StyleProfile)
            .values(
                user_id=user_id,
                kibbe_type=kibbe_type,
                kibbe_confidence=kibbe_confidence,
                color_profile_json=color_profile or {},
                style_vector_json=style_vector or {},
            )
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "kibbe_type": kibbe_type,
                    "kibbe_confidence": kibbe_confidence,
                    "color_profile_json": color_profile or {},
                    "style_vector_json": style_vector or {},
                },
            )
        )
        self.db.execute(stmt)
        self.db.commit()

    # ----- pure helpers --------------------------------------------------

    @staticmethod
    def _validate_uploads(
        uploads: list[AnalysisPhotoUpload],
    ) -> dict[str, AnalysisPhotoUpload]:
        """Strict validation of the uploaded photo set.

        Rules:

        * exactly 3 uploads
        * unique slots (no duplicates)
        * slot set == ``{"front", "side", "portrait"}`` exactly

        Returns a dict keyed by slot so the caller can iterate in canonical
        order via :data:`SLOT_ORDER`.
        """
        if len(uploads) != 3:
            raise UserAnalysisValidationError(
                f"expected exactly 3 photo uploads, got {len(uploads)}"
            )
        by_slot: dict[str, AnalysisPhotoUpload] = {}
        for upload in uploads:
            slot = (upload.slot or "").strip().lower()
            if slot in by_slot:
                raise UserAnalysisValidationError(
                    f"duplicate slot {slot!r}"
                )
            by_slot[slot] = upload
        slot_set = frozenset(by_slot.keys())
        if slot_set != _ALLOWED_SLOTS:
            missing = sorted(_ALLOWED_SLOTS - slot_set)
            extra = sorted(slot_set - _ALLOWED_SLOTS)
            parts: list[str] = []
            if missing:
                parts.append(f"missing={missing}")
            if extra:
                parts.append(f"unexpected={extra}")
            raise UserAnalysisValidationError(
                "photo slots must be exactly {front, side, portrait}"
                + (f" ({', '.join(parts)})" if parts else "")
            )
        return by_slot

    # ----- public API ----------------------------------------------------

    def analyze(
        self,
        *,
        user_id: uuid.UUID,
        uploads: list[AnalysisPhotoUpload],
    ) -> dict:
        by_slot = self._validate_uploads(uploads)

        storage = self._get_storage()
        repo = self._get_photo_repo()

        # Upload + persist each slot in canonical order. We deliberately do
        # NOT try to roll back earlier slots on a later failure — see the
        # module docstring for the rationale.
        persisted: list[dict] = []
        for slot in SLOT_ORDER:
            upload = by_slot[slot]
            photo_id = uuid.uuid4()

            try:
                asset = storage.upload_user_photo(
                    user_id,
                    photo_id,
                    slot,
                    data=upload.data,
                    content_type=upload.content_type or "",
                    filename=upload.filename,
                )
            except (StorageError, StorageValidationError) as exc:
                raise UserAnalysisStorageError(
                    f"failed to store {slot} photo: {exc}"
                ) from exc

            try:
                row = repo.create(
                    user_id=user_id,
                    slot=slot,
                    image_key=asset.key,
                    image_url=asset.url,
                    photo_id=photo_id,
                )
            except Exception as exc:
                raise UserAnalysisPersistenceError(
                    f"failed to persist {slot} photo row: {exc}"
                ) from exc

            persisted.append(
                {
                    "id": str(getattr(row, "id", photo_id)),
                    "slot": slot,
                    "image_key": asset.key,
                    "image_url": asset.url,
                }
            )

        # Build the canonical-order reference list that the extractor
        # seam receives. Single source of truth: we iterate persisted
        # entries (which were appended in SLOT_ORDER above), so the
        # ordering cannot drift from the response ``photos`` list.
        photo_refs: list[PhotoReference] = [
            PhotoReference(
                slot=entry["slot"],
                image_key=entry["image_key"],
                image_url=entry["image_url"],
                photo_id=uuid.UUID(entry["id"]),
            )
            for entry in persisted
        ]

        features = self._get_features(user_id, photo_refs)
        identity = self._get_identity_engine().analyze(features)
        color = self._get_color_engine().analyze(_stub_color_axes())
        style_vector = _stub_style_vector()

        # Persist the computed analysis into ``style_profiles`` so
        # downstream features (Recommendations, Today, Insights) can
        # read it back without relying on the transient HTTP response.
        self._persist_style_profile(
            user_id,
            kibbe_type=identity.get("main_type"),
            kibbe_confidence=identity.get("confidence"),
            color_profile=color,
            style_vector=style_vector,
        )

        return {
            "kibbe": identity,
            "color": color,
            "style_vector": style_vector,
            "analyzed_at": self._get_now().isoformat(),
            "photos": persisted,
        }


__all__ = [
    "SLOT_ORDER",
    "AnalysisPhotoUpload",
    "UserAnalysisError",
    "UserAnalysisPersistenceError",
    "UserAnalysisService",
    "UserAnalysisStorageError",
    "UserAnalysisValidationError",
]
