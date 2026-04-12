"""Unified error envelope for the HTTP layer.

Every error response the API emits has the same shape::

    {
        "error": {"code": "<ERROR_CODE>", "message": "<human message>"},
        "detail": "<human message>"
    }

``error.code`` is a stable, machine-readable identifier from
:class:`ErrorCode`; the frontend switches on it. ``error.message`` is the
human-readable reason (safe to surface in a toast). ``detail`` is a
temporary backward-compatibility shim that mirrors ``error.message`` —
it lets any old client that still reads FastAPI's default
``{"detail": ...}`` shape keep working during the migration.

The envelope is produced by three handlers, registered in
:mod:`app.main`:

1. :func:`api_error_handler` — catches :class:`ApiError`, which carries
   an explicit :class:`ErrorCode` (the preferred way for new code).
2. :func:`http_error_handler` — catches plain
   :class:`fastapi.HTTPException` (the existing route code still raises
   these). The code is inferred from the status via
   :data:`_STATUS_TO_CODE`, so every legacy ``HTTPException`` is
   wrapped without touching the routes.
3. :func:`validation_error_handler` — catches Pydantic's
   :class:`RequestValidationError` and rewrites the default 422 body
   into the same envelope with ``code=VALIDATION_ERROR``.

No route layer edits are required for existing errors to start using
the envelope — the handlers wrap everything at the edge.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import HTTPException, Request, status  # noqa: F401 - status re-exported for clarity
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


# ---------------------------------------------------------------- codes


class ErrorCode(str, Enum):
    """Stable machine-readable error codes emitted on the wire.

    The set is intentionally small. New codes should be added only when
    the frontend needs to branch on a genuinely new failure category —
    otherwise reuse the closest existing code.
    """

    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    AUTH_ERROR = "AUTH_ERROR"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    STORAGE_ERROR = "STORAGE_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    PERSISTENCE_ERROR = "PERSISTENCE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


#: Fallback mapping from HTTP status code → :class:`ErrorCode`. Used when
#: a plain :class:`HTTPException` bubbles up without an explicit code.
_STATUS_TO_CODE: dict[int, ErrorCode] = {
    status.HTTP_400_BAD_REQUEST: ErrorCode.VALIDATION_ERROR,
    status.HTTP_401_UNAUTHORIZED: ErrorCode.AUTH_ERROR,
    status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
    status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
    status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
    # 422 is the Pydantic validation status. We use the literal rather
    # than ``status.HTTP_422_UNPROCESSABLE_ENTITY`` / ``_CONTENT`` to
    # avoid churning on FastAPI's renamed constants between versions.
    422: ErrorCode.VALIDATION_ERROR,
    status.HTTP_500_INTERNAL_SERVER_ERROR: ErrorCode.INTERNAL_ERROR,
    status.HTTP_502_BAD_GATEWAY: ErrorCode.PROVIDER_ERROR,
}


def _code_for_status(status_code: int) -> ErrorCode:
    """Pick a default :class:`ErrorCode` for a raw HTTP status."""
    return _STATUS_TO_CODE.get(status_code, ErrorCode.INTERNAL_ERROR)


# ---------------------------------------------------------------- exception


class ApiError(HTTPException):
    """HTTP exception carrying an explicit :class:`ErrorCode`.

    New route code should raise ``ApiError`` instead of bare
    :class:`HTTPException` so the wire code is stable and not inferred
    from the status. The two co-exist during the migration — plain
    ``HTTPException`` still gets wrapped by :func:`http_error_handler`.
    """

    def __init__(
        self,
        *,
        code: ErrorCode,
        message: str,
        status_code: int,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code, detail=message, headers=headers
        )
        self.code = code
        self.message = message


# ---------------------------------------------------------------- envelope


def _envelope(code: ErrorCode, message: str) -> dict[str, Any]:
    """Build the canonical ``{"error": ..., "detail": ...}`` body.

    ``detail`` is the temporary shim that mirrors ``error.message`` so
    any legacy client still reading FastAPI's default ``detail`` field
    keeps working. Remove the shim once the frontend is migrated.
    """
    return {
        "error": {"code": code.value, "message": message},
        "detail": message,
    }


# ---------------------------------------------------------------- handlers


async def api_error_handler(
    request: Request, exc: ApiError
) -> JSONResponse:
    """Handler for :class:`ApiError` — the preferred error type."""
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(exc.code, exc.message),
        headers=exc.headers,
    )


async def http_error_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """Handler for plain :class:`HTTPException`.

    Infers :class:`ErrorCode` from the status so legacy routes that
    still raise ``HTTPException`` directly get the same envelope.
    """
    # ``detail`` on HTTPException can be anything (dict, list, str).
    # Normalise it to a string for ``error.message``.
    raw = exc.detail
    message = raw if isinstance(raw, str) else str(raw)
    code = _code_for_status(exc.status_code)
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(code, message),
        headers=getattr(exc, "headers", None),
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handler for Pydantic request-validation failures.

    FastAPI's default 422 body is a list of per-field error dicts. We
    surface the first problem as ``error.message`` and stash the full
    list under ``error.errors`` so the frontend can still show
    per-field hints if it wants to.
    """
    errors = exc.errors()
    if errors:
        first = errors[0]
        loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        msg = first.get("msg") or "validation error"
        message = f"{loc}: {msg}" if loc else msg
    else:
        message = "validation error"

    body = _envelope(ErrorCode.VALIDATION_ERROR, message)
    body["error"]["errors"] = errors
    return JSONResponse(
        status_code=422,
        content=body,
    )


__all__ = [
    "ApiError",
    "ErrorCode",
    "api_error_handler",
    "http_error_handler",
    "validation_error_handler",
]
