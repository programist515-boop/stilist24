"""Tests for the storage hardening layer (STEP 10).

The tests exercise the ``StorageService`` against the in-memory backend —
no boto3, no MinIO, no network. This is the backend that
``storage_backend="memory"`` selects in dev/test environments.
"""

import uuid

import pytest

from app.core.storage import (
    InMemoryStorageBackend,
    StorageService,
    StorageValidationError,
    StoredAsset,
    _check_magic_bytes,
)


# ------------------------------------------------------------- fixtures


USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
ITEM_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
PHOTO_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
JOB_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")

JPEG_HEADER = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
WEBP_HEADER = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32


def _make_service() -> tuple[StorageService, InMemoryStorageBackend]:
    backend = InMemoryStorageBackend(public_base_url="memory://ai-stylist")
    return StorageService(backend=backend), backend


# ------------------------------------------------------------- key structure


def test_wardrobe_key_structure():
    svc, backend = _make_service()
    asset = svc.upload_wardrobe_image(
        USER_ID,
        ITEM_ID,
        data=JPEG_HEADER,
        content_type="image/jpeg",
        filename="hoodie.jpg",
    )
    assert asset.key == f"users/{USER_ID}/wardrobe/{ITEM_ID}.jpg"
    assert backend.exists(asset.key)


def test_user_photo_key_structure_per_slot():
    svc, _ = _make_service()
    for slot in ("front", "side", "portrait"):
        asset = svc.upload_user_photo(
            USER_ID,
            PHOTO_ID,
            slot,
            data=PNG_HEADER,
            content_type="image/png",
            filename=f"{slot}.png",
        )
        assert asset.key == f"users/{USER_ID}/photos/{slot}/{PHOTO_ID}.png"


def test_user_photo_rejects_unknown_slot():
    svc, _ = _make_service()
    with pytest.raises(StorageValidationError):
        svc.upload_user_photo(
            USER_ID,
            PHOTO_ID,
            "selfie",
            data=JPEG_HEADER,
            content_type="image/jpeg",
            filename="selfie.jpg",
        )


def test_tryon_key_structure():
    svc, _ = _make_service()
    asset = svc.upload_tryon_result(
        USER_ID,
        JOB_ID,
        data=WEBP_HEADER,
        content_type="image/webp",
    )
    assert asset.key == f"users/{USER_ID}/tryon/{JOB_ID}.webp"


# ------------------------------------------------------------- validation


def test_content_type_validation_rejects_pdf():
    svc, _ = _make_service()
    with pytest.raises(StorageValidationError):
        svc.upload_wardrobe_image(
            USER_ID,
            ITEM_ID,
            data=b"%PDF-1.4\n" + b"\x00" * 32,
            content_type="application/pdf",
            filename="whatever.pdf",
        )


def test_extension_validation_rejects_exe_filename():
    svc, _ = _make_service()
    with pytest.raises(StorageValidationError):
        svc.upload_wardrobe_image(
            USER_ID,
            ITEM_ID,
            data=JPEG_HEADER,
            content_type="image/jpeg",
            filename="exploit.exe",
        )


def test_size_validation_rejects_oversized(monkeypatch):
    svc, _ = _make_service()
    # Shrink the cap to make a tiny payload "oversized" deterministically.
    from app.core import storage as storage_module

    cached = storage_module._get_settings()
    monkeypatch.setattr(cached, "storage_max_bytes", 16, raising=False)
    with pytest.raises(StorageValidationError):
        svc.upload_wardrobe_image(
            USER_ID,
            ITEM_ID,
            data=JPEG_HEADER * 10,
            content_type="image/jpeg",
            filename="huge.jpg",
        )


def test_size_validation_rejects_empty():
    svc, _ = _make_service()
    with pytest.raises(StorageValidationError):
        svc.upload_wardrobe_image(
            USER_ID,
            ITEM_ID,
            data=b"",
            content_type="image/jpeg",
            filename="empty.jpg",
        )


def test_magic_byte_check_rejects_fake_jpeg():
    # Declared jpeg, actual body is PNG — must be rejected.
    with pytest.raises(StorageValidationError):
        _check_magic_bytes(PNG_HEADER, "image/jpeg")


def test_magic_byte_check_rejects_fake_webp():
    # "RIFF" prefix but no "WEBP" marker.
    fake = b"RIFF" + b"\x00\x00\x00\x00" + b"AVI " + b"\x00" * 32
    with pytest.raises(StorageValidationError):
        _check_magic_bytes(fake, "image/webp")


def test_magic_byte_accepts_valid_prefixes():
    _check_magic_bytes(JPEG_HEADER, "image/jpeg")
    _check_magic_bytes(PNG_HEADER, "image/png")
    _check_magic_bytes(WEBP_HEADER, "image/webp")


# ------------------------------------------------------------- mutations


def test_delete_object_removes_from_backend():
    svc, backend = _make_service()
    asset = svc.upload_wardrobe_image(
        USER_ID,
        ITEM_ID,
        data=JPEG_HEADER,
        content_type="image/jpeg",
        filename="x.jpg",
    )
    assert backend.exists(asset.key)
    svc.delete_object(asset.key)
    assert not backend.exists(asset.key)


def test_replace_uploads_first_then_deletes_old():
    svc, backend = _make_service()
    old_key = f"users/{USER_ID}/wardrobe/{ITEM_ID}.old.jpg"
    backend.put(old_key, JPEG_HEADER, content_type="image/jpeg")

    new_asset = svc.replace_wardrobe_image(
        USER_ID,
        ITEM_ID,
        data=PNG_HEADER,
        content_type="image/png",
        filename="new.png",
        old_key=old_key,
    )
    # New key exists, old key was cleaned up.
    assert backend.exists(new_asset.key)
    assert not backend.exists(old_key)


def test_replace_preserves_old_when_upload_fails():
    svc, backend = _make_service()
    old_key = f"users/{USER_ID}/wardrobe/{ITEM_ID}.old.jpg"
    backend.put(old_key, JPEG_HEADER, content_type="image/jpeg")

    # Invalid new payload — upload must fail and the old object must survive.
    with pytest.raises(StorageValidationError):
        svc.replace_wardrobe_image(
            USER_ID,
            ITEM_ID,
            data=b"%PDF-1.4\n",
            content_type="application/pdf",
            filename="bad.pdf",
            old_key=old_key,
        )
    assert backend.exists(old_key)


def test_replace_with_same_key_does_not_delete_new_object():
    svc, backend = _make_service()
    # Old key is exactly the canonical key for this (user, item, ext).
    same_key = f"users/{USER_ID}/wardrobe/{ITEM_ID}.jpg"
    backend.put(same_key, JPEG_HEADER, content_type="image/jpeg")

    new_asset = svc.replace_wardrobe_image(
        USER_ID,
        ITEM_ID,
        data=JPEG_HEADER,
        content_type="image/jpeg",
        filename="new.jpg",
        old_key=same_key,
    )
    # The upload overwrote the old object in place; we must not then delete it.
    assert new_asset.key == same_key
    assert backend.exists(same_key)


# ------------------------------------------------------------- backend contract


def test_in_memory_backend_roundtrip():
    backend = InMemoryStorageBackend()
    backend.put("a/b/c.jpg", b"hello", content_type="image/jpeg")
    assert backend.exists("a/b/c.jpg")
    assert backend.get("a/b/c.jpg") == (b"hello", "image/jpeg")
    backend.delete("a/b/c.jpg")
    assert not backend.exists("a/b/c.jpg")


def test_public_url_uses_public_base_url_when_set():
    backend = InMemoryStorageBackend(public_base_url="https://cdn.example.com/x")
    svc = StorageService(backend=backend)
    asset = svc.upload_wardrobe_image(
        USER_ID,
        ITEM_ID,
        data=JPEG_HEADER,
        content_type="image/jpeg",
        filename="x.jpg",
    )
    assert asset.url == f"https://cdn.example.com/x/{asset.key}"


def test_service_returns_stored_asset_dataclass():
    svc, _ = _make_service()
    asset = svc.upload_wardrobe_image(
        USER_ID,
        ITEM_ID,
        data=JPEG_HEADER,
        content_type="image/jpeg",
        filename="x.jpg",
    )
    assert isinstance(asset, StoredAsset)
    assert asset.content_type == "image/jpeg"
    assert asset.size == len(JPEG_HEADER)
    assert asset.key.startswith(f"users/{USER_ID}/wardrobe/{ITEM_ID}")


def test_extension_derived_from_content_type_not_filename():
    svc, _ = _make_service()
    # Filename says ".jpeg", content-type says "image/png" with a real PNG body.
    asset = svc.upload_wardrobe_image(
        USER_ID,
        ITEM_ID,
        data=PNG_HEADER,
        content_type="image/png",
        filename="surprise.jpeg",
    )
    # Canonical extension follows content-type, not the client filename.
    assert asset.key.endswith(".png")
