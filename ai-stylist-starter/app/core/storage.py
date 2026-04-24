"""Storage service for user photos, wardrobe images, and try-on outputs.

Design notes
------------
* Backends are hidden behind a ``StorageBackend`` protocol so that tests and
  local sandboxes can use an in-memory implementation without needing boto3
  or MinIO. The ``storage_backend`` setting is the single source of truth for
  which backend is active.
* ``image_key`` is the canonical storage reference. Public URLs are built
  lazily from the key (either via ``s3_public_base_url`` or presigned), so
  rotating URLs never requires a database write.
* Validation is split into small single-purpose helpers (size, content-type,
  extension, magic bytes) and orchestrated in ``_validate``. This keeps the
  rules independently testable and makes it obvious which check failed.
* Replace flow is upload-first, delete-old-after-success. The old object is
  only removed once the new one is safely persisted.
* Routes never touch boto3 or mime logic directly — they call
  ``StorageService`` methods which return a ``StoredAsset`` dataclass.
* Bucket provisioning is NOT done in ``__init__``. Docker-compose creates the
  bucket via a one-shot ``minio/mc`` container. A separate explicit
  ``ensure_bucket()`` helper exists for callers that need it (e.g. ops jobs).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mypy_boto3_s3 import S3Client  # noqa: F401


# Module-level settings are loaded lazily so tests can import this module
# without pydantic-settings being installed. Default values mirror the
# Settings class in app.core.config; the real object replaces them when
# available.
class _DefaultSettings:
    storage_backend: str = "s3"
    s3_endpoint_url: str = "http://minio:9000"
    s3_region: str = "us-east-1"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "ai-stylist"
    s3_force_path_style: bool = True
    s3_public_base_url: str | None = None
    s3_presign_expires: int = 3600
    storage_max_bytes: int = 8 * 1024 * 1024
    storage_allowed_mime: tuple[str, ...] = (
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/avif",
    )
    storage_allowed_ext: tuple[str, ...] = (
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".avif",
    )


_settings_cache: Any | None = None


def _get_settings() -> Any:
    """Return the real Settings object if importable, else defaults.

    Deferring the import lets test environments load ``app.core.storage``
    without pydantic-settings. The result is cached on first access.
    """
    global _settings_cache
    if _settings_cache is not None:
        return _settings_cache
    try:
        from app.core.config import settings as real_settings  # type: ignore

        _settings_cache = real_settings
    except Exception:
        _settings_cache = _DefaultSettings()
    return _settings_cache


class _SettingsProxy:
    """Attribute proxy so call sites can keep writing ``settings.foo``."""

    def __getattr__(self, name: str) -> Any:
        return getattr(_get_settings(), name)


settings = _SettingsProxy()


# ---------------------------------------------------------------- errors


class StorageError(Exception):
    """Base class for all storage-layer errors."""


class StorageValidationError(StorageError):
    """Raised when an upload fails validation (size/mime/extension/bytes)."""


class StorageBackendError(StorageError):
    """Raised when the underlying backend fails (network, auth, missing key)."""


# ---------------------------------------------------------------- dataclass


@dataclass(frozen=True)
class StoredAsset:
    """Canonical reference returned after a successful upload.

    ``key`` is the source of truth in the database. ``url`` is a convenience
    projection derived from the key and may change between reads (e.g. when
    presigned URLs expire).
    """

    key: str
    url: str
    content_type: str
    size: int


# ---------------------------------------------------------------- mime/ext


# Content-type → canonical extension. The canonical extension is chosen from
# content-type only; client-supplied filenames are never trusted to pick it.
_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
}

# Minimal magic-byte prefixes for the three formats we accept.
_MAGIC_PREFIXES: tuple[tuple[str, bytes], ...] = (
    ("image/jpeg", b"\xff\xd8\xff"),
    ("image/png", b"\x89PNG\r\n\x1a\n"),
    # WEBP files start with "RIFF....WEBP"
    ("image/webp", b"RIFF"),
    # AVIF: ISOBMFF container — first 4 bytes are box size (variable),
    # bytes 4-8 must be "ftyp".  We use a dummy prefix and rely on the
    # secondary check below.
    ("image/avif", b""),
)


# ---------------------------------------------------------------- validation helpers


def _check_size(data: bytes, max_bytes: int) -> int:
    size = len(data)
    if size == 0:
        raise StorageValidationError("uploaded file is empty")
    if size > max_bytes:
        raise StorageValidationError(
            f"uploaded file is {size} bytes, exceeds limit {max_bytes}"
        )
    return size


def _check_content_type(content_type: str, allowed: Iterable[str]) -> str:
    ct = (content_type or "").lower().split(";")[0].strip()
    if ct not in set(allowed):
        raise StorageValidationError(f"content-type {ct!r} is not allowed")
    return ct


def _extension_for(content_type: str) -> str:
    ext = _MIME_TO_EXT.get(content_type)
    if ext is None:
        raise StorageValidationError(
            f"no canonical extension for content-type {content_type!r}"
        )
    return ext


def _check_filename_extension(
    filename: str | None, allowed: Iterable[str]
) -> None:
    """If a filename was supplied, its extension must look like an image.

    Client filenames are not used to derive the canonical extension, but we
    still reject obvious mismatches like ``exploit.exe`` labelled as
    ``image/jpeg`` — that is a strong signal the upload is adversarial.
    """
    if not filename:
        return
    lowered = filename.lower()
    if "." not in lowered:
        return
    idx = lowered.rfind(".")
    ext = lowered[idx:]
    if ext not in set(allowed):
        raise StorageValidationError(
            f"filename extension {ext!r} is not allowed"
        )


def _detect_mime(data: bytes) -> str | None:
    """Sniff the real image MIME from the body.

    Returns the canonical MIME we support (image/jpeg, image/png,
    image/webp, image/avif) or ``None`` if the body does not look like
    any of them. Browsers routinely hand us ``image/jpeg`` regardless
    of the actual file type (especially HEIC from iPhone), so we never
    trust the client-supplied Content-Type — magic bytes win.
    """
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp"
    # AVIF + HEIC/HEIF share the ISOBMFF container. Bytes 4-8 are always
    # "ftyp"; the 4-char brand at 8-12 tells them apart.
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"avif", b"avis"):
            return "image/avif"
    return None


def _format_hint(data: bytes) -> str:
    """Human-readable guess for an unsupported body — used in the
    error message so the user knows *what* they uploaded rather than
    just "format not supported"."""
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = bytes(data[8:12]).decode("ascii", errors="replace")
        if brand in ("heic", "heix", "hevc", "mif1", "msf1"):
            return "HEIC/HEIF (iPhone по умолчанию) — сохрани как JPEG"
        return f"ISOBMFF ({brand!r}) — не поддерживается"
    if data.startswith(b"GIF8"):
        return "GIF — не поддерживается"
    if data.startswith(b"BM"):
        return "BMP — не поддерживается"
    if data.startswith(b"II*\x00") or data.startswith(b"MM\x00*"):
        return "TIFF — не поддерживается"
    return "неизвестный формат"


# Back-compat shim: existing tests call ``_check_magic_bytes(data, ct)``.
# Replay that signature on top of the new sniffer.
def _check_magic_bytes(data: bytes, content_type: str) -> None:
    detected = _detect_mime(data)
    if detected is None:
        raise StorageValidationError(
            f"формат файла не поддерживается: {_format_hint(data)}. "
            "Поддерживаются JPEG, PNG, WEBP, AVIF."
        )
    if detected != content_type:
        raise StorageValidationError(
            f"file body does not match declared content-type {content_type!r}"
        )


def _validate(
    data: bytes,
    content_type: str,
    filename: str | None,
) -> tuple[str, str, int]:
    """Orchestrate the small validation helpers.

    Returns ``(normalized_content_type, canonical_extension, size)``.

    The canonical content-type is derived from the file body (magic
    bytes), not from ``content_type``. Browsers send ``image/jpeg``
    for anything they treat as an image — notably HEIC from iPhone —
    so client-supplied MIME is not trustworthy. ``content_type`` and
    ``filename`` are still consulted by the surface-level checks to
    stop an obvious ``exploit.exe`` labelled as ``image/jpeg`` before
    it reaches the sniffer.
    """
    size = _check_size(data, settings.storage_max_bytes)
    _check_content_type(content_type, settings.storage_allowed_mime)
    _check_filename_extension(filename, settings.storage_allowed_ext)

    detected = _detect_mime(data)
    if detected is None:
        raise StorageValidationError(
            f"формат файла не поддерживается: {_format_hint(data)}. "
            "Поддерживаются JPEG, PNG, WEBP, AVIF."
        )
    if detected not in set(settings.storage_allowed_mime):
        raise StorageValidationError(
            f"содержимое файла — {detected}, но этот формат отключён политикой."
        )
    ext = _extension_for(detected)
    return detected, ext, size


# ---------------------------------------------------------------- backends


class StorageBackend(Protocol):
    """Minimal interface a storage backend must satisfy."""

    def put(self, key: str, data: bytes, *, content_type: str) -> None: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def public_url(self, key: str) -> str: ...
    def get_object(self, key: str) -> tuple[bytes, str] | None: ...


class InMemoryStorageBackend:
    """Dict-backed backend used by tests and ``storage_backend="memory"``.

    Deterministic, side-effect free, requires no external services. It is
    intentionally visible so callers know when it is active.
    """

    def __init__(self, *, public_base_url: str = "memory://ai-stylist") -> None:
        self._objects: dict[str, tuple[bytes, str]] = {}
        self._public_base_url = public_base_url.rstrip("/")

    # --- StorageBackend ---------------------------------------------------

    def put(self, key: str, data: bytes, *, content_type: str) -> None:
        self._objects[key] = (bytes(data), content_type)

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self._objects

    def public_url(self, key: str) -> str:
        return f"{self._public_base_url}/{key}"

    def get_object(self, key: str) -> tuple[bytes, str] | None:
        return self._objects.get(key)

    # --- test helpers -----------------------------------------------------

    def get(self, key: str) -> tuple[bytes, str] | None:
        """Back-compat alias for :meth:`get_object`."""
        return self.get_object(key)

    def keys(self) -> list[str]:
        return sorted(self._objects)


class S3StorageBackend:
    """boto3-backed backend for MinIO (dev) and S3 (prod).

    The bucket is NOT provisioned here — ops/infra creates it via
    ``docker-compose`` (``createbuckets`` one-shot) or an explicit call to
    :func:`ensure_bucket`. That keeps ``__init__`` side-effect free and makes
    application startup independent of write privileges on the storage tier.
    """

    def __init__(
        self,
        *,
        bucket: str | None = None,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        public_base_url: str | None = None,
        presign_expires: int | None = None,
        force_path_style: bool | None = None,
    ) -> None:
        self.bucket = bucket or settings.s3_bucket
        self._endpoint_url = endpoint_url or settings.s3_endpoint_url
        self._region = region or settings.s3_region
        self._access_key = access_key or settings.s3_access_key
        self._secret_key = secret_key or settings.s3_secret_key
        self._public_base_url = (
            public_base_url
            if public_base_url is not None
            else settings.s3_public_base_url
        )
        self._presign_expires = (
            presign_expires
            if presign_expires is not None
            else settings.s3_presign_expires
        )
        self._force_path_style = (
            force_path_style
            if force_path_style is not None
            else settings.s3_force_path_style
        )
        self._client = None  # lazy

    # --- client -----------------------------------------------------------

    def _get_client(self):
        if self._client is None:
            import boto3  # lazy import — tests never load boto3
            from botocore.client import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint_url,
                region_name=self._region,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                config=Config(
                    s3={"addressing_style": "path" if self._force_path_style else "auto"},
                    signature_version="s3v4",
                ),
            )
        return self._client

    # --- StorageBackend ---------------------------------------------------

    def put(self, key: str, data: bytes, *, content_type: str) -> None:
        try:
            self._get_client().put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except Exception as exc:  # pragma: no cover - network path
            raise StorageBackendError(f"failed to put {key!r}: {exc}") from exc

    def delete(self, key: str) -> None:
        try:
            self._get_client().delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:  # pragma: no cover - network path
            raise StorageBackendError(f"failed to delete {key!r}: {exc}") from exc

    def exists(self, key: str) -> bool:
        try:
            self._get_client().head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:  # pragma: no cover - network path
            return False

    def public_url(self, key: str) -> str:
        if self._public_base_url:
            return f"{self._public_base_url.rstrip('/')}/{key}"
        try:
            return self._get_client().generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=self._presign_expires,
            )
        except Exception as exc:  # pragma: no cover - network path
            raise StorageBackendError(
                f"failed to presign url for {key!r}: {exc}"
            ) from exc

    def get_object(self, key: str) -> tuple[bytes, str] | None:
        """Fetch the raw bytes + content-type for a stored object.

        Returns ``None`` when the key does not exist. Any other backend
        error (network, auth, etc.) surfaces as :class:`StorageBackendError`
        so the caller can distinguish "missing" from "broken".
        """
        try:
            response = self._get_client().get_object(
                Bucket=self.bucket, Key=key
            )
        except Exception as exc:  # pragma: no cover - network path
            # boto3 raises ClientError with Code=NoSuchKey (or 404 via
            # botocore). Distinguishing that from a real failure needs
            # a string match because we don't import botocore here.
            text = repr(exc)
            if "NoSuchKey" in text or "404" in text:
                return None
            raise StorageBackendError(
                f"failed to fetch object {key!r}: {exc}"
            ) from exc
        body = response.get("Body")
        if body is None:
            return None
        data = body.read()
        ct = (
            response.get("ContentType")
            or "application/octet-stream"
        )
        return data, ct

    # --- explicit ops helper ---------------------------------------------

    def ensure_bucket(self) -> None:
        """Create the bucket if it doesn't exist.

        Intentionally NOT called from ``__init__``. Invoke this from ops
        tooling or a bootstrap script if you don't want to rely on the
        docker-compose ``createbuckets`` one-shot.
        """
        client = self._get_client()
        try:
            client.head_bucket(Bucket=self.bucket)
            return
        except Exception:
            pass
        try:
            client.create_bucket(Bucket=self.bucket)
        except Exception as exc:  # pragma: no cover - network path
            raise StorageBackendError(
                f"failed to create bucket {self.bucket!r}: {exc}"
            ) from exc


# ---------------------------------------------------------------- service


class StorageService:
    """Centralized entry point for all object storage operations.

    Routes call these methods; repositories never touch file bytes. The
    service owns validation, key generation, and URL projection. The
    underlying backend is selected once at construction time and is visible
    via :pyattr:`backend`.
    """

    def __init__(self, backend: StorageBackend | None = None) -> None:
        self.backend: StorageBackend = backend or _default_backend()

    # ----- key helpers ----------------------------------------------------

    @staticmethod
    def wardrobe_key(
        user_id: uuid.UUID | str,
        item_id: uuid.UUID | str,
        ext: str,
        *,
        persona_id: uuid.UUID | str | None = None,
    ) -> str:
        """Return the canonical S3/MinIO key for a wardrobe image.

        New clients pass ``persona_id`` and get the namespaced layout
        ``users/{user}/personas/{persona}/wardrobe/{item}{ext}``. Legacy
        callers omit it and still land at
        ``users/{user}/wardrobe/{item}{ext}``; stored rows keep whichever
        key they were written with, so reads continue to work across the
        migration.
        """
        if persona_id is not None:
            return f"users/{user_id}/personas/{persona_id}/wardrobe/{item_id}{ext}"
        return f"users/{user_id}/wardrobe/{item_id}{ext}"

    @staticmethod
    def user_photo_key(
        user_id: uuid.UUID | str,
        slot: str,
        photo_id: uuid.UUID | str,
        ext: str,
        *,
        persona_id: uuid.UUID | str | None = None,
    ) -> str:
        slot_clean = slot.strip().lower()
        if slot_clean not in {"front", "side", "portrait"}:
            raise StorageValidationError(
                f"user photo slot must be front/side/portrait, got {slot!r}"
            )
        if persona_id is not None:
            return (
                f"users/{user_id}/personas/{persona_id}/photos/"
                f"{slot_clean}/{photo_id}{ext}"
            )
        return f"users/{user_id}/photos/{slot_clean}/{photo_id}{ext}"

    @staticmethod
    def tryon_key(
        user_id: uuid.UUID | str,
        job_id: uuid.UUID | str,
        ext: str,
        *,
        persona_id: uuid.UUID | str | None = None,
    ) -> str:
        if persona_id is not None:
            return f"users/{user_id}/personas/{persona_id}/tryon/{job_id}{ext}"
        return f"users/{user_id}/tryon/{job_id}{ext}"

    # ----- uploads --------------------------------------------------------

    def upload_wardrobe_image(
        self,
        user_id: uuid.UUID | str,
        item_id: uuid.UUID | str,
        *,
        data: bytes,
        content_type: str,
        filename: str | None = None,
        persona_id: uuid.UUID | str | None = None,
    ) -> StoredAsset:
        ct, ext, size = _validate(data, content_type, filename)
        key = self.wardrobe_key(user_id, item_id, ext, persona_id=persona_id)
        self.backend.put(key, data, content_type=ct)
        return StoredAsset(
            key=key,
            url=self.backend.public_url(key),
            content_type=ct,
            size=size,
        )

    def upload_user_photo(
        self,
        user_id: uuid.UUID | str,
        photo_id: uuid.UUID | str,
        slot: str,
        *,
        data: bytes,
        content_type: str,
        filename: str | None = None,
        persona_id: uuid.UUID | str | None = None,
    ) -> StoredAsset:
        ct, ext, size = _validate(data, content_type, filename)
        key = self.user_photo_key(user_id, slot, photo_id, ext, persona_id=persona_id)
        self.backend.put(key, data, content_type=ct)
        return StoredAsset(
            key=key,
            url=self.backend.public_url(key),
            content_type=ct,
            size=size,
        )

    def upload_tryon_result(
        self,
        user_id: uuid.UUID | str,
        job_id: uuid.UUID | str,
        *,
        data: bytes,
        content_type: str,
        filename: str | None = None,
        persona_id: uuid.UUID | str | None = None,
    ) -> StoredAsset:
        ct, ext, size = _validate(data, content_type, filename)
        key = self.tryon_key(user_id, job_id, ext, persona_id=persona_id)
        self.backend.put(key, data, content_type=ct)
        return StoredAsset(
            key=key,
            url=self.backend.public_url(key),
            content_type=ct,
            size=size,
        )

    # ----- mutations ------------------------------------------------------

    def delete_object(self, key: str) -> None:
        self.backend.delete(key)

    def replace_wardrobe_image(
        self,
        user_id: uuid.UUID | str,
        item_id: uuid.UUID | str,
        *,
        data: bytes,
        content_type: str,
        filename: str | None = None,
        old_key: str | None = None,
    ) -> StoredAsset:
        """Upload-first, delete-old-after-success replace flow.

        The new object is uploaded before the old one is removed. If the new
        upload fails, the old object is left intact. The old object is only
        deleted if its key differs from the new one (avoids deleting the
        image we just wrote when the canonical key happens to be identical).
        """
        asset = self.upload_wardrobe_image(
            user_id,
            item_id,
            data=data,
            content_type=content_type,
            filename=filename,
        )
        if old_key and old_key != asset.key:
            try:
                self.backend.delete(old_key)
            except StorageBackendError:
                # Upload succeeded — do not propagate cleanup failures.
                pass
        return asset

    # ----- url projection -------------------------------------------------

    def public_url(self, key: str) -> str:
        return self.backend.public_url(key)

    def get_object(self, key: str) -> tuple[bytes, str] | None:
        """Return ``(bytes, content_type)`` for a stored object.

        Thin pass-through to :meth:`StorageBackend.get_object`. Used by
        :class:`~app.services.tryon_service.TryOnService` to fetch a
        reference photo or garment image and embed it as a base64 data
        URI — the FASHN provider can't reach ``http://localhost:9000``
        in local dev, so URLs are not a usable transport.
        """
        return self.backend.get_object(key)


# ---------------------------------------------------------------- defaults


def _default_backend() -> StorageBackend:
    """Pick the backend declared in settings.

    Visible by design — callers can inspect ``storage_backend`` to understand
    which backend is in use. ``"memory"`` is intended for tests and local
    sandboxes only.
    """
    choice = (settings.storage_backend or "s3").lower()
    if choice == "memory":
        return InMemoryStorageBackend()
    if choice == "s3":
        return S3StorageBackend()
    raise StorageError(f"unknown storage_backend {choice!r}")


def get_storage_service() -> StorageService:
    """FastAPI dependency seam — returns a ``StorageService`` bound to the
    backend selected by the current settings.
    """
    return StorageService()


def fresh_public_url(image_key: str | None, fallback: str) -> str:
    """Rebuild the public URL from ``image_key`` on every call.

    The wardrobe/user_photos/tryon_jobs tables all persist ``image_url``
    as a snapshot of what the backend projected at upload time. That is
    fine until ``S3_PUBLIC_BASE_URL`` changes (e.g. the nginx proxy
    prefix is fixed) — then every already-stored URL goes stale. This
    helper re-derives the URL from the canonical ``image_key`` so one
    env update repairs every row at the next read, no DB migration
    required.

    Legacy rows that predate the ``image_key`` column (or any
    unexpected storage failure) fall through to the persisted URL.
    """
    if not image_key:
        return fallback
    try:
        return get_storage_service().public_url(image_key)
    except Exception:
        return fallback


__all__ = [
    "StorageBackend",
    "StorageBackendError",
    "StorageError",
    "StorageService",
    "StorageValidationError",
    "StoredAsset",
    "InMemoryStorageBackend",
    "S3StorageBackend",
    "get_storage_service",
]
