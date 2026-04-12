"""Shared Pydantic schemas used across the API.

Phase 2 of the API contract polish deliberately keeps ``common`` tiny —
only the error envelope lives here, because every route emits it. Any
schema that is genuinely shared between two or more routes earns a
place here later; domain-specific schemas live in their own module
(``schemas/wardrobe.py``, ``schemas/tryon.py``, etc.).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------- error envelope


class ErrorBody(BaseModel):
    """Inner ``error`` object of the unified error envelope.

    ``code`` is one of :class:`app.api.errors.ErrorCode`. We intentionally
    type it as a plain ``str`` here instead of importing the enum: the
    schema is consumed by the frontend via OpenAPI, which should treat
    the code as an open vocabulary (new codes may be added without a
    schema bump).

    ``errors`` is populated only for Pydantic validation failures — it
    carries the raw per-field error list so the frontend can render
    inline field hints. Every other handler omits it.
    """

    model_config = ConfigDict(extra="allow")

    code: str
    message: str
    errors: list[dict[str, Any]] | None = None


class ErrorEnvelope(BaseModel):
    """Canonical shape of every HTTP error body.

    Mirrors :func:`app.api.errors._envelope`. ``detail`` is a temporary
    backward-compatibility shim that duplicates ``error.message`` so any
    client still reading FastAPI's default ``detail`` keeps working
    until the frontend migrates to ``error.code`` / ``error.message``.
    """

    error: ErrorBody
    detail: str


__all__ = ["ErrorBody", "ErrorEnvelope"]
