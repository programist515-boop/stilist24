"""FASHN provider adapter.

The adapter is intentionally split into three explicit, narrowly scoped
methods so that everything that depends on the FASHN API contract is
isolated and trivially testable:

* :meth:`build_payload`  — pure function (no I/O) that returns the request
  body. Easy to test, easy to swap when the documented contract changes.
* :meth:`extract_result` — pure function (no I/O) that maps a known
  response shape onto :class:`FashnResult`. **Narrow on purpose**: it
  supports only clearly defined shapes and raises ``FashnResponseError``
  on anything unknown. There is no "magic parser".
* :meth:`generate_tryon` — the only method that touches the network. It
  composes the two pure helpers and is the only place that needs HTTP
  mocking in tests.

Settings (api key, base URL) are loaded lazily so the module is importable
in test environments without ``pydantic-settings``.

# --- PROVIDER CONTRACT (verify against FASHN docs) -------------------
# Endpoint  : POST  {fashn_base_url}/tryon
# Auth      : "Authorization: Bearer {fashn_api_key}"
# Request   : {"model_image": <url>, "garment_image": <url>,
#              "category": <optional str>}
# Response  : one of the two shapes below
#
#   shape A : {"image_url": "...", "id": "..."}
#   shape B : {"output": {"image_url": "...", "id": "..."}}
#
# extract_result understands EXACTLY these two shapes. Any other shape
# (including the legacy "result"/"images" forms) raises FashnResponseError
# so we never silently ship a partially understood result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


# ---------------------------------------------------------------- errors


class FashnAdapterError(Exception):
    """Base class for every error raised by :class:`FashnAdapter`."""


class FashnAuthError(FashnAdapterError):
    """Provider rejected the request because of invalid credentials."""


class FashnRequestError(FashnAdapterError):
    """Provider returned a non-success status that is not auth-related."""


class FashnTimeoutError(FashnAdapterError):
    """Provider did not respond within the configured timeout."""


class FashnResponseError(FashnAdapterError):
    """Provider response did not match a known supported shape."""


# ---------------------------------------------------------------- result


@dataclass(frozen=True)
class FashnResult:
    """Normalized representation of a FASHN response.

    ``image_bytes`` is the actual generated image. The adapter is the
    component that knows how to fetch them — the service consumes bytes
    and never thinks about FASHN URLs.
    """

    image_url: str
    image_bytes: bytes
    content_type: str
    provider_job_id: str | None
    raw: dict = field(default_factory=dict)


# ---------------------------------------------------------------- http seam


class _AsyncHTTPClient(Protocol):
    """Minimal subset of an httpx-like async client used by the adapter."""

    async def post(
        self, url: str, *, headers: dict[str, str], json: dict[str, Any]
    ) -> Any: ...

    async def get(self, url: str) -> Any: ...

    async def aclose(self) -> None: ...


# ---------------------------------------------------------------- adapter


class FashnAdapter:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        http_client: _AsyncHTTPClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._explicit_api_key = api_key
        self._explicit_base_url = base_url
        self._http_client = http_client
        self._timeout = timeout

    # ----- settings -------------------------------------------------------

    @property
    def api_key(self) -> str:
        if self._explicit_api_key is not None:
            return self._explicit_api_key
        return self._load_settings_value("fashn_api_key", "")

    @property
    def base_url(self) -> str:
        if self._explicit_base_url is not None:
            return self._explicit_base_url
        return self._load_settings_value("fashn_base_url", "https://api.fashn.ai")

    @staticmethod
    def _load_settings_value(name: str, default: Any) -> Any:
        try:
            from app.core.config import settings  # lazy

            return getattr(settings, name, default)
        except Exception:
            return default

    # ----- pure helpers ---------------------------------------------------

    def build_payload(
        self,
        *,
        person_image_url: str,
        garment_image_url: str,
        garment_category: str | None = None,
    ) -> dict[str, Any]:
        """Pure payload builder. No I/O."""
        if not person_image_url:
            raise FashnRequestError("person_image_url is required")
        if not garment_image_url:
            raise FashnRequestError("garment_image_url is required")
        payload: dict[str, Any] = {
            "model_image": person_image_url,
            "garment_image": garment_image_url,
        }
        if garment_category:
            payload["category"] = garment_category
        return payload

    def extract_result(
        self,
        response_json: dict,
        *,
        image_bytes: bytes,
        content_type: str,
    ) -> FashnResult:
        """Pure response extractor — narrow and explicit.

        Supports exactly two documented shapes (see PROVIDER CONTRACT at
        the top of this module). Anything else raises
        :class:`FashnResponseError`.
        """
        if not isinstance(response_json, dict):
            raise FashnResponseError(
                f"expected JSON object from provider, got {type(response_json).__name__}"
            )

        # Shape A: {"image_url": "...", "id": "..."}
        if "image_url" in response_json:
            image_url = response_json.get("image_url")
            provider_job_id = response_json.get("id")
            if not isinstance(image_url, str) or not image_url:
                raise FashnResponseError(
                    "shape A: 'image_url' must be a non-empty string"
                )
            return FashnResult(
                image_url=image_url,
                image_bytes=image_bytes,
                content_type=content_type,
                provider_job_id=provider_job_id if isinstance(provider_job_id, str) else None,
                raw=response_json,
            )

        # Shape B: {"output": {"image_url": "...", "id": "..."}}
        if "output" in response_json and isinstance(response_json["output"], dict):
            output = response_json["output"]
            image_url = output.get("image_url")
            provider_job_id = output.get("id")
            if not isinstance(image_url, str) or not image_url:
                raise FashnResponseError(
                    "shape B: 'output.image_url' must be a non-empty string"
                )
            return FashnResult(
                image_url=image_url,
                image_bytes=image_bytes,
                content_type=content_type,
                provider_job_id=provider_job_id if isinstance(provider_job_id, str) else None,
                raw=response_json,
            )

        raise FashnResponseError(
            "provider response did not match any supported shape "
            "(expected 'image_url' or 'output.image_url')"
        )

    # ----- network --------------------------------------------------------

    async def generate_tryon(
        self,
        *,
        person_image_url: str,
        garment_image_url: str,
        garment_category: str | None = None,
    ) -> FashnResult:
        """Composes the pure helpers around a single network round trip."""
        payload = self.build_payload(
            person_image_url=person_image_url,
            garment_image_url=garment_image_url,
            garment_category=garment_category,
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        owns_client = False
        client = self._http_client
        if client is None:
            import httpx  # lazy

            client = httpx.AsyncClient(timeout=self._timeout)
            owns_client = True

        try:
            try:
                response = await client.post(
                    f"{self.base_url}/tryon",
                    headers=headers,
                    json=payload,
                )
            except Exception as exc:  # network/timeout
                # Map any low-level transport error to FashnTimeoutError so the
                # service layer has a single category to catch for "provider
                # is unreachable / slow".
                raise FashnTimeoutError(
                    f"FASHN request failed before response: {exc}"
                ) from exc

            status = getattr(response, "status_code", 200)
            if status in (401, 403):
                raise FashnAuthError(f"FASHN auth failed (status {status})")
            if status >= 400:
                raise FashnRequestError(
                    f"FASHN request failed with status {status}"
                )

            try:
                response_json = response.json()
            except Exception as exc:
                raise FashnResponseError(
                    f"FASHN response was not valid JSON: {exc}"
                ) from exc

            # Provisional extraction to learn the URL of the generated image.
            provisional = self.extract_result(
                response_json,
                image_bytes=b"",
                content_type="application/octet-stream",
            )

            # Fetch the actual bytes. The adapter owns this fetch — the
            # service layer never makes outbound HTTP calls.
            try:
                image_response = await client.get(provisional.image_url)
            except Exception as exc:
                raise FashnTimeoutError(
                    f"FASHN result image fetch failed: {exc}"
                ) from exc

            image_status = getattr(image_response, "status_code", 200)
            if image_status >= 400:
                raise FashnRequestError(
                    f"FASHN result image fetch returned status {image_status}"
                )

            image_bytes = getattr(image_response, "content", b"") or b""
            if not image_bytes:
                raise FashnResponseError("FASHN result image was empty")
            content_type = "image/jpeg"
            headers_obj = getattr(image_response, "headers", None)
            if headers_obj is not None:
                ct = headers_obj.get("content-type") or headers_obj.get("Content-Type")
                if isinstance(ct, str) and ct:
                    content_type = ct.split(";")[0].strip()

            return FashnResult(
                image_url=provisional.image_url,
                image_bytes=image_bytes,
                content_type=content_type,
                provider_job_id=provisional.provider_job_id,
                raw=provisional.raw,
            )
        finally:
            if owns_client:
                try:
                    await client.aclose()
                except Exception:  # pragma: no cover - best effort cleanup
                    pass


__all__ = [
    "FashnAdapter",
    "FashnAdapterError",
    "FashnAuthError",
    "FashnRequestError",
    "FashnResponseError",
    "FashnResult",
    "FashnTimeoutError",
]
