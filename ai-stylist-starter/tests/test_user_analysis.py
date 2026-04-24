"""Tests for STEP 12 — user photo persistence in /user/analyze.

The service is exercised purely through its dependency-injection seams.
No real DB, no real storage, no real CV, no boto3. Stubs mirror the
attribute surfaces of :class:`StorageService`, :class:`UserPhotoRepository`,
:class:`IdentityEngine`, and :class:`ColorEngine`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest

from app.core.storage import (
    StorageBackendError,
    StorageValidationError,
    StoredAsset,
)
from app.services.feature_extractor import (
    PhotoReference,
    default_feature_extractor,
)
from app.services.user_analysis_service import (
    SLOT_ORDER,
    AnalysisPhotoUpload,
    UserAnalysisPersistenceError,
    UserAnalysisService,
    UserAnalysisStorageError,
    UserAnalysisValidationError,
    _stub_features,
)


# ---------------------------------------------------------------- ids + constants


USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime(2026, 4, 11, 16, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- stubs


class _StubStorageService:
    """Records each upload_user_photo call and returns deterministic assets."""

    def __init__(
        self,
        *,
        raise_on_slot: str | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._raise_on_slot = raise_on_slot
        self._raise_exc = raise_exc

    def upload_user_photo(
        self,
        user_id: uuid.UUID,
        photo_id: uuid.UUID,
        slot: str,
        *,
        data: bytes,
        content_type: str,
        filename: str | None = None,
        persona_id: uuid.UUID | None = None,
    ) -> StoredAsset:
        self.calls.append(
            {
                "user_id": user_id,
                "photo_id": photo_id,
                "slot": slot,
                "data": data,
                "content_type": content_type,
                "filename": filename,
                "persona_id": persona_id,
            }
        )
        if self._raise_on_slot == slot and self._raise_exc is not None:
            raise self._raise_exc
        key = f"users/{user_id}/photos/{slot}/{photo_id}.jpg"
        return StoredAsset(
            key=key,
            url=f"memory://{key}",
            content_type=content_type or "image/jpeg",
            size=len(data),
        )


@dataclass
class _StubPhotoRow:
    id: uuid.UUID
    user_id: uuid.UUID
    slot: str
    image_key: str
    image_url: str


class _StubUserPhotoRepo:
    def __init__(
        self,
        *,
        raise_on_slot: str | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._raise_on_slot = raise_on_slot
        self._raise_exc = raise_exc

    def create(
        self,
        *,
        user_id: uuid.UUID,
        slot: str,
        image_key: str,
        image_url: str,
        photo_id: uuid.UUID | None = None,
        persona_id: uuid.UUID | None = None,
    ) -> _StubPhotoRow:
        self.calls.append(
            {
                "user_id": user_id,
                "slot": slot,
                "image_key": image_key,
                "image_url": image_url,
                "photo_id": photo_id,
                "persona_id": persona_id,
            }
        )
        if self._raise_on_slot == slot and self._raise_exc is not None:
            raise self._raise_exc
        return _StubPhotoRow(
            id=photo_id or uuid.uuid4(),
            user_id=user_id,
            slot=slot,
            image_key=image_key,
            image_url=image_url,
        )


class _StubIdentityEngine:
    def __init__(self, result: dict | None = None) -> None:
        self.result = result or {
            "family_scores": {"classic": 0.6, "romantic": 0.3, "natural": 0.1},
            "main_type": "classic",
            "confidence": 0.42,
            "alternatives": [],
        }
        self.calls: list[dict] = []

    def analyze(self, features: dict[str, float]) -> dict:
        self.calls.append(features)
        return self.result


class _StubColorEngine:
    def __init__(self, result: dict | None = None) -> None:
        self.result = result or {"season": "winter", "palette": ["A", "B"]}
        self.calls: list[dict] = []

    def analyze(self, axes: dict[str, str]) -> dict:
        self.calls.append(axes)
        return self.result


# ---------------------------------------------------------------- helpers


def _upload(slot: str, data: bytes = b"\xff\xd8\xff\xe0fake") -> AnalysisPhotoUpload:
    return AnalysisPhotoUpload(
        slot=slot,
        data=data,
        content_type="image/jpeg",
        filename=f"{slot}.jpg",
    )


def _three_uploads() -> list[AnalysisPhotoUpload]:
    return [_upload("front"), _upload("side"), _upload("portrait")]


def _make_service(
    *,
    storage: _StubStorageService | None = None,
    repo: _StubUserPhotoRepo | None = None,
    identity_engine: _StubIdentityEngine | None = None,
    color_engine: _StubColorEngine | None = None,
    feature_extractor=None,
    now: datetime = NOW,
) -> UserAnalysisService:
    storage = storage or _StubStorageService()
    repo = repo or _StubUserPhotoRepo()
    identity_engine = identity_engine or _StubIdentityEngine()
    color_engine = color_engine or _StubColorEngine()
    return UserAnalysisService(
        db=None,
        storage=storage,
        photo_repo_factory=lambda _db: repo,
        feature_extractor=feature_extractor,
        identity_engine=identity_engine,
        color_engine=color_engine,
        now=lambda: now,
    )


# ================================================================ tests


# 1. happy path: all top-level fields present
def test_happy_path_returns_all_fields() -> None:
    svc = _make_service()
    result = svc.analyze(user_id=USER_ID, uploads=_three_uploads())

    assert set(result.keys()) == {
        "kibbe",
        "color",
        "style_vector",
        "analyzed_at",
        "photos",
    }
    assert isinstance(result["photos"], list)
    assert len(result["photos"]) == 3
    assert result["analyzed_at"] == NOW.isoformat()


# 2. response photo order is always canonical regardless of input order
def test_photos_ordered_front_side_portrait() -> None:
    svc = _make_service()
    # Shuffle input order to ensure the service does not trust it.
    shuffled = [_upload("portrait"), _upload("front"), _upload("side")]
    result = svc.analyze(user_id=USER_ID, uploads=shuffled)

    slots = [p["slot"] for p in result["photos"]]
    assert slots == list(SLOT_ORDER)
    assert slots == ["front", "side", "portrait"]


# 3. structure of each photo entry
def test_photos_have_id_slot_key_url() -> None:
    svc = _make_service()
    result = svc.analyze(user_id=USER_ID, uploads=_three_uploads())

    for entry in result["photos"]:
        assert set(entry.keys()) == {"id", "slot", "image_key", "image_url"}
        # id is a string uuid
        uuid.UUID(entry["id"])
        assert entry["image_key"].startswith(f"users/{USER_ID}/photos/")
        assert entry["image_url"].startswith("memory://")


# 4. storage is called once per slot with the right slot value
def test_storage_called_per_slot() -> None:
    storage = _StubStorageService()
    svc = _make_service(storage=storage)
    svc.analyze(user_id=USER_ID, uploads=_three_uploads())

    assert [c["slot"] for c in storage.calls] == list(SLOT_ORDER)
    for call in storage.calls:
        assert call["user_id"] == USER_ID
        assert isinstance(call["photo_id"], uuid.UUID)
        assert call["content_type"] == "image/jpeg"


# 5. repository create is called per slot with the same photo_id storage received
def test_repo_called_per_slot_with_matching_ids() -> None:
    storage = _StubStorageService()
    repo = _StubUserPhotoRepo()
    svc = _make_service(storage=storage, repo=repo)
    svc.analyze(user_id=USER_ID, uploads=_three_uploads())

    assert [c["slot"] for c in repo.calls] == list(SLOT_ORDER)
    for storage_call, repo_call in zip(storage.calls, repo.calls):
        assert storage_call["photo_id"] == repo_call["photo_id"]
        assert storage_call["slot"] == repo_call["slot"]


# 6. the structured default extractor is used when no seam is injected
def test_default_extractor_used_when_no_seam_injected() -> None:
    identity = _StubIdentityEngine()
    svc = _make_service(identity_engine=identity)
    svc.analyze(user_id=USER_ID, uploads=_three_uploads())

    # The structured extractor only reads (user_id, slot) — the photo ids
    # are irrelevant to the numeric output, so we can rebuild an equivalent
    # ref list here and compare directly.
    dummy_refs = [
        PhotoReference(
            slot=slot,
            image_key="k",
            image_url="u",
            photo_id=uuid.uuid4(),
        )
        for slot in SLOT_ORDER
    ]
    expected = default_feature_extractor(USER_ID, dummy_refs)
    assert identity.calls == [expected]


# 7. custom feature extractor seam is respected (will be used by CV step)
def test_custom_feature_extractor_used() -> None:
    custom = {"vertical_line": 0.99, "softness": 0.01}
    identity = _StubIdentityEngine()
    svc = _make_service(
        identity_engine=identity,
        feature_extractor=lambda _uid, _refs: custom,
    )
    svc.analyze(user_id=USER_ID, uploads=_three_uploads())

    assert identity.calls == [custom]


# 8. storage failure is wrapped in UserAnalysisStorageError
def test_storage_failure_wraps_in_storage_error() -> None:
    storage = _StubStorageService(
        raise_on_slot="front",
        raise_exc=StorageBackendError("s3 is down"),
    )
    svc = _make_service(storage=storage)

    with pytest.raises(UserAnalysisStorageError) as exc_info:
        svc.analyze(user_id=USER_ID, uploads=_three_uploads())
    assert "front" in str(exc_info.value)
    assert "s3 is down" in str(exc_info.value)


# 9. repo failure is wrapped in UserAnalysisPersistenceError
def test_repo_failure_wraps_in_persistence_error() -> None:
    repo = _StubUserPhotoRepo(
        raise_on_slot="side",
        raise_exc=RuntimeError("db exploded"),
    )
    svc = _make_service(repo=repo)

    with pytest.raises(UserAnalysisPersistenceError) as exc_info:
        svc.analyze(user_id=USER_ID, uploads=_three_uploads())
    assert "side" in str(exc_info.value)
    assert "db exploded" in str(exc_info.value)


# 10. partial-failure contract: earlier slot bytes remain in storage
def test_partial_failure_leaves_earlier_bytes_in_storage() -> None:
    storage = _StubStorageService(
        raise_on_slot="side",
        raise_exc=StorageBackendError("boom"),
    )
    svc = _make_service(storage=storage)

    with pytest.raises(UserAnalysisStorageError):
        svc.analyze(user_id=USER_ID, uploads=_three_uploads())

    # front was already uploaded; side blew up; portrait was never attempted
    assert [c["slot"] for c in storage.calls] == ["front", "side"]


# 11. stub feature vector keeps all 20 keys it used to have in the route
def test_stub_features_has_all_20_keys() -> None:
    features = _stub_features()
    assert len(features) == 20
    expected_subset = {
        "vertical_line",
        "compactness",
        "width",
        "bone_sharpness",
        "bone_bluntness",
        "softness",
        "curve_presence",
        "symmetry",
        "facial_sharpness",
        "facial_roundness",
        "waist_definition",
        "narrowness",
        "relaxed_line",
        "proportion_balance",
        "moderation",
        "line_contrast",
        "small_scale",
        "feature_juxtaposition",
        "controlled_softness_or_sharpness",
        "low_line_contrast",
    }
    assert set(features.keys()) == expected_subset


# 12. response image_url matches what StorageService returned
def test_response_image_url_matches_stored_asset() -> None:
    storage = _StubStorageService()
    svc = _make_service(storage=storage)
    result = svc.analyze(user_id=USER_ID, uploads=_three_uploads())

    # each StorageService call produced a StoredAsset whose url is memory://<key>
    response_by_slot = {p["slot"]: p for p in result["photos"]}
    call_by_slot = {c["slot"]: c for c in storage.calls}
    for slot in SLOT_ORDER:
        expected_key = (
            f"users/{USER_ID}/photos/{slot}/{call_by_slot[slot]['photo_id']}.jpg"
        )
        assert response_by_slot[slot]["image_key"] == expected_key
        assert response_by_slot[slot]["image_url"] == f"memory://{expected_key}"


# 13. response never leaks internal upload fields (bytes / content_type)
def test_response_does_not_leak_bytes_or_content_type() -> None:
    svc = _make_service()
    result = svc.analyze(user_id=USER_ID, uploads=_three_uploads())

    for entry in result["photos"]:
        assert "data" not in entry
        assert "content_type" not in entry
        assert "filename" not in entry


# ================================================================ extractor integration
# (STEP 13 — structured feature extractor wiring)


# 14. default extractor receives canonical (user_id, refs) args
def test_integration_extractor_called_with_canonical_refs() -> None:
    spy_calls: list[tuple[uuid.UUID, list[PhotoReference]]] = []

    def spy_extractor(
        user_id: uuid.UUID, refs: list[PhotoReference]
    ) -> dict[str, float]:
        spy_calls.append((user_id, list(refs)))
        return _stub_features()  # any valid vector is fine here

    storage = _StubStorageService()
    svc = _make_service(storage=storage, feature_extractor=spy_extractor)
    result = svc.analyze(user_id=USER_ID, uploads=_three_uploads())

    # Exactly one call, with the acting user id.
    assert len(spy_calls) == 1
    called_user_id, called_refs = spy_calls[0]
    assert called_user_id == USER_ID

    # Refs are in canonical slot order and line up 1:1 with the
    # response ``photos`` list (same image_key and id).
    assert [r.slot for r in called_refs] == list(SLOT_ORDER)
    response_by_slot = {p["slot"]: p for p in result["photos"]}
    for ref in called_refs:
        assert isinstance(ref, PhotoReference)
        assert ref.image_key == response_by_slot[ref.slot]["image_key"]
        assert ref.image_url == response_by_slot[ref.slot]["image_url"]
        assert str(ref.photo_id) == response_by_slot[ref.slot]["id"]


# 15. extractor raising falls back to _stub_features, route stays 200-able
def test_integration_extractor_failure_falls_back_to_stub() -> None:
    def boom(_uid: uuid.UUID, _refs: list[PhotoReference]) -> dict[str, float]:
        raise RuntimeError("extractor is buggy today")

    identity = _StubIdentityEngine()
    svc = _make_service(
        identity_engine=identity,
        feature_extractor=boom,
    )

    # Must not raise — the fallback protects the happy path.
    result = svc.analyze(user_id=USER_ID, uploads=_three_uploads())

    # Identity engine still ran, with the stub vector.
    assert identity.calls == [_stub_features()]

    # Response shape is still complete.
    assert set(result.keys()) == {
        "kibbe",
        "color",
        "style_vector",
        "analyzed_at",
        "photos",
    }
    assert len(result["photos"]) == 3


# ================================================================ validation tests
# (these reinforce adjustment #3 — exactly 3 / unique / exact set)


def test_validation_rejects_wrong_count() -> None:
    svc = _make_service()
    with pytest.raises(UserAnalysisValidationError):
        svc.analyze(
            user_id=USER_ID,
            uploads=[_upload("front"), _upload("side")],
        )


def test_validation_rejects_duplicate_slots() -> None:
    svc = _make_service()
    with pytest.raises(UserAnalysisValidationError):
        svc.analyze(
            user_id=USER_ID,
            uploads=[_upload("front"), _upload("front"), _upload("side")],
        )


def test_validation_rejects_unexpected_slot_name() -> None:
    svc = _make_service()
    with pytest.raises(UserAnalysisValidationError):
        svc.analyze(
            user_id=USER_ID,
            uploads=[_upload("front"), _upload("side"), _upload("back")],
        )


def test_validation_passes_with_storage_validation_error_wrapping() -> None:
    """StorageValidationError (derived from StorageError) is wrapped too."""
    storage = _StubStorageService(
        raise_on_slot="front",
        raise_exc=StorageValidationError("not a jpeg"),
    )
    svc = _make_service(storage=storage)
    with pytest.raises(UserAnalysisStorageError) as exc_info:
        svc.analyze(user_id=USER_ID, uploads=_three_uploads())
    assert "not a jpeg" in str(exc_info.value)
