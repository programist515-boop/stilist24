"""Tests for STEP 11 — FASHN try-on integration.

Everything is exercised through stub objects + injectable seams so no
real DB, no real provider, no real boto3, no real network calls happen.

The tests cover three layers:

* :class:`FashnAdapter` — pure helpers ``build_payload`` and
  ``extract_result`` (the only place that knows the provider contract).
* :class:`TryOnService` — orchestration with seeded ``UserPhoto`` /
  ``WardrobeItem`` / ``TryOnRepository`` / storage / adapter stubs.
* :class:`TryOnService` error mapping — every documented failure path
  produces the typed exception the route layer maps to HTTP.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.core.storage import (
    InMemoryStorageBackend,
    StorageBackendError,
    StorageService,
)
from app.services.fashn_adapter import (
    FashnAdapter,
    FashnRequestError,
    FashnResponseError,
    FashnResult,
)
from app.services.tryon_service import (
    PROVIDER_FASHN,
    TRY_ON_DISCLAIMER,
    TryOnAssetError,
    TryOnNotFoundError,
    TryOnPersistenceError,
    TryOnProviderError,
    TryOnService,
    TryOnStorageError,
)


# ---------------------------------------------------------------- ids


USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_USER_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")
ITEM_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
PHOTO_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


# ---------------------------------------------------------------- stubs


class _Wardrobe:
    def __init__(
        self,
        *,
        item_id: uuid.UUID = ITEM_ID,
        user_id: uuid.UUID = USER_ID,
        image_key: str | None = "users/x/wardrobe/y.jpg",
        image_url: str | None = "memory://ai-stylist/wardrobe.jpg",
        category: str | None = "top",
    ):
        self.id = item_id
        self.user_id = user_id
        self.image_key = image_key
        self.image_url = image_url
        self.category = category


class _Photo:
    def __init__(
        self,
        *,
        photo_id: uuid.UUID = PHOTO_ID,
        user_id: uuid.UUID = USER_ID,
        slot: str = "front",
        image_key: str | None = "users/x/photos/front/y.jpg",
        image_url: str | None = "memory://ai-stylist/photo.jpg",
    ):
        self.id = photo_id
        self.user_id = user_id
        self.slot = slot
        self.image_key = image_key
        self.image_url = image_url


class _Job:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", uuid.uuid4())
        self.user_id = kwargs.get("user_id")
        self.item_id = kwargs.get("item_id")
        self.user_photo_id = kwargs.get("user_photo_id")
        self.provider = kwargs.get("provider", PROVIDER_FASHN)
        self.provider_job_id = kwargs.get("provider_job_id")
        self.status = kwargs.get("status", "pending")
        self.result_image_key = kwargs.get("result_image_key")
        self.result_image_url = kwargs.get("result_image_url")
        self.error_message = kwargs.get("error_message")
        self.metadata_json = kwargs.get("metadata_json", {})


class _StubTryOnRepo:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.jobs: dict[uuid.UUID, _Job] = {}
        self.fail_on_succeeded = False

    def create_pending(self, **kwargs) -> _Job:
        self.calls.append(("create_pending", kwargs))
        job_id = kwargs.get("job_id") or uuid.uuid4()
        job = _Job(
            id=job_id,
            user_id=kwargs.get("user_id"),
            item_id=kwargs.get("item_id"),
            user_photo_id=kwargs.get("user_photo_id"),
            provider=kwargs.get("provider", PROVIDER_FASHN),
            status="pending",
        )
        self.jobs[job_id] = job
        return job

    def mark_succeeded(self, job_id: uuid.UUID, **kwargs) -> _Job:
        self.calls.append(("mark_succeeded", {"job_id": job_id, **kwargs}))
        if self.fail_on_succeeded:
            raise RuntimeError("simulated DB outage")
        job = self.jobs[job_id]
        job.status = "succeeded"
        job.result_image_key = kwargs.get("result_image_key")
        job.result_image_url = kwargs.get("result_image_url")
        job.metadata_json = kwargs.get("metadata") or {}
        job.provider_job_id = kwargs.get("provider_job_id")
        job.error_message = None
        return job

    def mark_failed(self, job_id: uuid.UUID, **kwargs) -> _Job:
        self.calls.append(("mark_failed", {"job_id": job_id, **kwargs}))
        job = self.jobs.get(job_id)
        if job is None:
            return None  # type: ignore[return-value]
        job.status = "failed"
        job.error_message = kwargs.get("error_message")
        return job


class _StubAdapter:
    """Minimal stand-in for :class:`FashnAdapter` used by the service tests."""

    def __init__(
        self,
        *,
        result: FashnResult | None = None,
        raise_with: Exception | None = None,
    ):
        self._result = result or FashnResult(
            image_url="https://provider/result.jpg",
            image_bytes=_jpeg_bytes(),
            content_type="image/jpeg",
            provider_job_id="prov-1",
            raw={"image_url": "https://provider/result.jpg", "id": "prov-1"},
        )
        self._raise_with = raise_with
        self.calls: list[dict] = []

    async def generate_tryon(self, **kwargs) -> FashnResult:
        self.calls.append(kwargs)
        if self._raise_with is not None:
            raise self._raise_with
        return self._result


class _ExplodingStorageService(StorageService):
    """Storage service whose ``upload_tryon_result`` always blows up."""

    def upload_tryon_result(self, *args, **kwargs):  # type: ignore[override]
        raise StorageBackendError("simulated S3 outage")


# ---------------------------------------------------------------- helpers


def _jpeg_bytes() -> bytes:
    # Real JPEG SOI marker so the storage validation layer accepts it.
    return b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _make_service(
    *,
    wardrobe: _Wardrobe | None,
    photo: _Photo | None,
    repo: _StubTryOnRepo | None = None,
    storage: StorageService | None = None,
    adapter: _StubAdapter | None = None,
) -> tuple[TryOnService, _StubTryOnRepo, StorageService, _StubAdapter]:
    repo = repo or _StubTryOnRepo()
    backend = InMemoryStorageBackend(public_base_url="memory://ai-stylist")
    storage = storage or StorageService(backend=backend)
    adapter = adapter or _StubAdapter()
    svc = TryOnService(
        db=None,
        wardrobe_loader=lambda _id: wardrobe,
        photo_loader=lambda _id: photo,
        tryon_repo=repo,
        storage=storage,
        adapter=adapter,  # type: ignore[arg-type]
    )
    return svc, repo, storage, adapter


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- happy path


def test_happy_path_returns_succeeded_response_and_persists_result():
    svc, repo, storage, adapter = _make_service(
        wardrobe=_Wardrobe(),
        photo=_Photo(),
    )

    response = _run(
        svc.generate(user_id=USER_ID, item_id=ITEM_ID, user_photo_id=PHOTO_ID)
    )

    # Response shape
    assert response["status"] == "succeeded"
    assert response["provider"] == PROVIDER_FASHN
    assert response["result_image_key"].startswith(f"users/{USER_ID}/tryon/")
    assert response["result_image_key"].endswith(".jpg")
    assert response["result_image_url"].startswith("memory://ai-stylist/")
    assert response["note"] == TRY_ON_DISCLAIMER
    assert response["provider_job_id"] == "prov-1"
    assert isinstance(response["metadata"], dict)

    # Adapter received resolved URLs from the seeded assets.
    assert len(adapter.calls) == 1
    call = adapter.calls[0]
    assert call["person_image_url"] == "memory://ai-stylist/photo.jpg"
    assert call["garment_image_url"] == "memory://ai-stylist/wardrobe.jpg"
    assert call["garment_category"] == "top"

    # Repo saw create_pending then mark_succeeded.
    sequence = [name for name, _ in repo.calls]
    assert sequence == ["create_pending", "mark_succeeded"]


def test_response_shape_contract():
    svc, _, _, _ = _make_service(wardrobe=_Wardrobe(), photo=_Photo())
    response = _run(
        svc.generate(user_id=USER_ID, item_id=ITEM_ID, user_photo_id=PHOTO_ID)
    )
    assert set(response.keys()) == {
        "job_id",
        "status",
        "provider",
        "provider_job_id",
        "result_image_key",
        "result_image_url",
        "metadata",
        "note",
    }


def test_disclaimer_is_module_level_constant():
    svc, _, _, _ = _make_service(wardrobe=_Wardrobe(), photo=_Photo())
    response = _run(
        svc.generate(user_id=USER_ID, item_id=ITEM_ID, user_photo_id=PHOTO_ID)
    )
    assert response["note"] is TRY_ON_DISCLAIMER


def test_image_url_falls_back_to_storage_public_url_when_only_key_is_present():
    backend = InMemoryStorageBackend(public_base_url="memory://ai-stylist")
    storage = StorageService(backend=backend)

    svc, _, _, adapter = _make_service(
        wardrobe=_Wardrobe(image_url=None, image_key="users/u/wardrobe/w.jpg"),
        photo=_Photo(image_url=None, image_key="users/u/photos/front/p.jpg"),
        storage=storage,
    )
    _run(
        svc.generate(user_id=USER_ID, item_id=ITEM_ID, user_photo_id=PHOTO_ID)
    )
    call = adapter.calls[0]
    assert call["person_image_url"] == "memory://ai-stylist/users/u/photos/front/p.jpg"
    assert call["garment_image_url"] == "memory://ai-stylist/users/u/wardrobe/w.jpg"


# ---------------------------------------------------------------- not found


def test_missing_wardrobe_item_raises_not_found():
    svc, repo, _, _ = _make_service(wardrobe=None, photo=_Photo())
    with pytest.raises(TryOnNotFoundError):
        _run(
            svc.generate(
                user_id=USER_ID, item_id=ITEM_ID, user_photo_id=PHOTO_ID
            )
        )
    # No pending job is created when validation fails before persistence.
    assert [name for name, _ in repo.calls] == []


def test_missing_user_photo_raises_not_found():
    svc, repo, _, _ = _make_service(wardrobe=_Wardrobe(), photo=None)
    with pytest.raises(TryOnNotFoundError):
        _run(
            svc.generate(
                user_id=USER_ID, item_id=ITEM_ID, user_photo_id=PHOTO_ID
            )
        )
    assert [name for name, _ in repo.calls] == []


def test_wardrobe_belongs_to_other_user_raises_not_found():
    svc, _, _, _ = _make_service(
        wardrobe=_Wardrobe(user_id=OTHER_USER_ID),
        photo=_Photo(),
    )
    with pytest.raises(TryOnNotFoundError):
        _run(
            svc.generate(
                user_id=USER_ID, item_id=ITEM_ID, user_photo_id=PHOTO_ID
            )
        )


def test_user_photo_belongs_to_other_user_raises_not_found():
    svc, _, _, _ = _make_service(
        wardrobe=_Wardrobe(),
        photo=_Photo(user_id=OTHER_USER_ID),
    )
    with pytest.raises(TryOnNotFoundError):
        _run(
            svc.generate(
                user_id=USER_ID, item_id=ITEM_ID, user_photo_id=PHOTO_ID
            )
        )


# ---------------------------------------------------------------- asset errors


def test_missing_image_url_and_key_on_wardrobe_raises_asset_error():
    svc, _, _, _ = _make_service(
        wardrobe=_Wardrobe(image_url=None, image_key=None),
        photo=_Photo(),
    )
    with pytest.raises(TryOnAssetError, match="wardrobe image is missing"):
        _run(
            svc.generate(
                user_id=USER_ID, item_id=ITEM_ID, user_photo_id=PHOTO_ID
            )
        )


def test_missing_image_url_and_key_on_user_photo_raises_asset_error():
    svc, _, _, _ = _make_service(
        wardrobe=_Wardrobe(),
        photo=_Photo(image_url=None, image_key=None),
    )
    with pytest.raises(TryOnAssetError, match="user photo image is missing"):
        _run(
            svc.generate(
                user_id=USER_ID, item_id=ITEM_ID, user_photo_id=PHOTO_ID
            )
        )


# ---------------------------------------------------------------- provider failure


def test_provider_failure_marks_job_failed_and_raises_provider_error():
    adapter = _StubAdapter(raise_with=FashnRequestError("FASHN 503"))
    svc, repo, _, _ = _make_service(
        wardrobe=_Wardrobe(), photo=_Photo(), adapter=adapter
    )
    with pytest.raises(TryOnProviderError):
        _run(
            svc.generate(
                user_id=USER_ID, item_id=ITEM_ID, user_photo_id=PHOTO_ID
            )
        )
    sequence = [name for name, _ in repo.calls]
    assert sequence == ["create_pending", "mark_failed"]
    failed = next(payload for name, payload in repo.calls if name == "mark_failed")
    assert "FASHN 503" in failed["error_message"]


# ---------------------------------------------------------------- storage failure


def test_storage_failure_marks_job_failed_and_raises_storage_error():
    storage = _ExplodingStorageService(
        backend=InMemoryStorageBackend(public_base_url="memory://ai-stylist")
    )
    svc, repo, _, _ = _make_service(
        wardrobe=_Wardrobe(), photo=_Photo(), storage=storage
    )
    with pytest.raises(TryOnStorageError):
        _run(
            svc.generate(
                user_id=USER_ID, item_id=ITEM_ID, user_photo_id=PHOTO_ID
            )
        )
    sequence = [name for name, _ in repo.calls]
    assert sequence == ["create_pending", "mark_failed"]


# ---------------------------------------------------------------- persistence failure


def test_persistence_failure_after_storage_raises_persistence_error():
    repo = _StubTryOnRepo()
    repo.fail_on_succeeded = True
    svc, repo, _, _ = _make_service(
        wardrobe=_Wardrobe(), photo=_Photo(), repo=repo
    )
    with pytest.raises(TryOnPersistenceError):
        _run(
            svc.generate(
                user_id=USER_ID, item_id=ITEM_ID, user_photo_id=PHOTO_ID
            )
        )
    sequence = [name for name, _ in repo.calls]
    assert sequence == ["create_pending", "mark_succeeded", "mark_failed"]


# ---------------------------------------------------------------- adapter pure


def test_payload_builder_is_pure_and_includes_category():
    adapter = FashnAdapter(api_key="x", base_url="https://api.fashn.example")
    payload = adapter.build_payload(
        person_image_url="https://example.com/person.jpg",
        garment_image_url="https://example.com/top.jpg",
        garment_category="top",
    )
    assert payload == {
        "model_image": "https://example.com/person.jpg",
        "garment_image": "https://example.com/top.jpg",
        "category": "top",
    }


def test_payload_builder_omits_category_when_unset():
    adapter = FashnAdapter(api_key="x", base_url="https://api.fashn.example")
    payload = adapter.build_payload(
        person_image_url="https://p",
        garment_image_url="https://g",
    )
    assert "category" not in payload


def test_payload_builder_rejects_empty_urls():
    adapter = FashnAdapter(api_key="x", base_url="https://api.fashn.example")
    with pytest.raises(FashnRequestError):
        adapter.build_payload(
            person_image_url="", garment_image_url="https://g"
        )
    with pytest.raises(FashnRequestError):
        adapter.build_payload(
            person_image_url="https://p", garment_image_url=""
        )


def test_extract_result_supports_shape_a_image_url_top_level():
    adapter = FashnAdapter(api_key="x", base_url="https://x")
    result = adapter.extract_result(
        {"image_url": "https://r/a.jpg", "id": "prov-7"},
        image_bytes=_jpeg_bytes(),
        content_type="image/jpeg",
    )
    assert result.image_url == "https://r/a.jpg"
    assert result.provider_job_id == "prov-7"


def test_extract_result_supports_shape_b_output_object():
    adapter = FashnAdapter(api_key="x", base_url="https://x")
    result = adapter.extract_result(
        {"output": {"image_url": "https://r/b.jpg", "id": "prov-8"}},
        image_bytes=_jpeg_bytes(),
        content_type="image/jpeg",
    )
    assert result.image_url == "https://r/b.jpg"
    assert result.provider_job_id == "prov-8"


def test_extract_result_rejects_unknown_shape():
    adapter = FashnAdapter(api_key="x", base_url="https://x")
    with pytest.raises(FashnResponseError):
        adapter.extract_result(
            {"images": ["https://r/c.jpg"]},
            image_bytes=_jpeg_bytes(),
            content_type="image/jpeg",
        )


def test_extract_result_rejects_non_dict_response():
    adapter = FashnAdapter(api_key="x", base_url="https://x")
    with pytest.raises(FashnResponseError):
        adapter.extract_result(
            ["not", "a", "dict"],  # type: ignore[arg-type]
            image_bytes=_jpeg_bytes(),
            content_type="image/jpeg",
        )


def test_extract_result_rejects_empty_image_url():
    adapter = FashnAdapter(api_key="x", base_url="https://x")
    with pytest.raises(FashnResponseError):
        adapter.extract_result(
            {"image_url": ""},
            image_bytes=_jpeg_bytes(),
            content_type="image/jpeg",
        )
