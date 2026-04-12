"""Tests for the unified error envelope (Phase 1 of API contract polish).

The handlers in :mod:`app.api.errors` wrap every HTTP error the API
emits into the shape::

    {
        "error": {"code": "...", "message": "..."},
        "detail": "..."
    }

These tests exercise the three handlers as plain async functions
(matching the existing test style — no ``TestClient``, no live FastAPI
app). Each test asserts:

1. The response status code is preserved.
2. ``error.code`` matches the expected :class:`ErrorCode`.
3. ``error.message`` is the human-readable reason.
4. ``detail`` mirrors ``error.message`` (the backward-compat shim).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

# These tests exercise FastAPI-level handlers, so they need the real
# FastAPI + Pydantic stack. In environments that ship only the pure
# Python layer (no FastAPI installed — e.g. the minimal local dev
# interpreter), the module is skipped cleanly instead of failing
# collection. The Docker/CI image ships both, so the tests run there.
pytest.importorskip("fastapi")
pytest.importorskip("pydantic")

from fastapi import HTTPException  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from pydantic import BaseModel, ValidationError  # noqa: E402

from app.api.errors import (  # noqa: E402
    ApiError,
    ErrorCode,
    api_error_handler,
    http_error_handler,
    validation_error_handler,
)


# ---------------------------------------------------------------- helpers


def _run(coro):
    """Run an async handler in a fresh event loop (matches tryon tests)."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _body(response) -> dict[str, Any]:
    """Decode a :class:`JSONResponse` body into a dict."""
    return json.loads(response.body.decode("utf-8"))


def _fake_request() -> Any:
    """The handlers never touch ``request``; ``None`` is fine."""
    return None  # type: ignore[return-value]


# ================================================================ api_error_handler


def test_api_error_handler_produces_envelope() -> None:
    exc = ApiError(
        code=ErrorCode.NOT_FOUND,
        message="wardrobe item not found",
        status_code=404,
    )
    response = _run(api_error_handler(_fake_request(), exc))

    assert response.status_code == 404
    body = _body(response)
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"] == "wardrobe item not found"
    # backward-compat shim
    assert body["detail"] == "wardrobe item not found"


def test_api_error_handler_preserves_every_code() -> None:
    """Every :class:`ErrorCode` round-trips through the handler verbatim."""
    for code in ErrorCode:
        exc = ApiError(code=code, message="x", status_code=400)
        response = _run(api_error_handler(_fake_request(), exc))
        body = _body(response)
        assert body["error"]["code"] == code.value


def test_api_error_handler_forwards_headers() -> None:
    exc = ApiError(
        code=ErrorCode.AUTH_ERROR,
        message="missing token",
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )
    response = _run(api_error_handler(_fake_request(), exc))
    assert response.headers.get("www-authenticate") == "Bearer"


# ================================================================ http_error_handler


def test_http_error_handler_maps_400_to_validation_error() -> None:
    exc = HTTPException(status_code=400, detail="bad shape")
    response = _run(http_error_handler(_fake_request(), exc))
    body = _body(response)
    assert response.status_code == 400
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "bad shape"
    assert body["detail"] == "bad shape"


def test_http_error_handler_maps_404_to_not_found() -> None:
    exc = HTTPException(status_code=404, detail="missing")
    response = _run(http_error_handler(_fake_request(), exc))
    body = _body(response)
    assert response.status_code == 404
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"] == "missing"


def test_http_error_handler_maps_502_to_provider_error() -> None:
    exc = HTTPException(status_code=502, detail="upstream down")
    response = _run(http_error_handler(_fake_request(), exc))
    body = _body(response)
    assert response.status_code == 502
    assert body["error"]["code"] == "PROVIDER_ERROR"


def test_http_error_handler_maps_500_to_internal_error() -> None:
    exc = HTTPException(status_code=500, detail="boom")
    response = _run(http_error_handler(_fake_request(), exc))
    body = _body(response)
    assert response.status_code == 500
    assert body["error"]["code"] == "INTERNAL_ERROR"


def test_http_error_handler_unknown_status_falls_back_to_internal() -> None:
    exc = HTTPException(status_code=418, detail="teapot")
    response = _run(http_error_handler(_fake_request(), exc))
    body = _body(response)
    assert response.status_code == 418
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["message"] == "teapot"


def test_http_error_handler_stringifies_non_string_detail() -> None:
    """``HTTPException.detail`` can legally be a list/dict — the envelope
    must not crash when rendering it as ``error.message``."""
    exc = HTTPException(
        status_code=400,
        detail=[{"loc": ["body"], "msg": "missing"}],
    )
    response = _run(http_error_handler(_fake_request(), exc))
    body = _body(response)
    assert response.status_code == 400
    assert isinstance(body["error"]["message"], str)
    assert body["detail"] == body["error"]["message"]


# ================================================================ validation_error_handler


class _Sample(BaseModel):
    name: str
    age: int


def _make_request_validation_error() -> RequestValidationError:
    """Build a real :class:`RequestValidationError` from a Pydantic failure."""
    try:
        _Sample(name="ok", age="not-a-number")  # type: ignore[arg-type]
    except ValidationError as exc:
        return RequestValidationError(exc.errors())
    raise AssertionError("expected ValidationError")


def test_validation_error_handler_produces_envelope() -> None:
    exc = _make_request_validation_error()
    response = _run(validation_error_handler(_fake_request(), exc))

    assert response.status_code == 422
    body = _body(response)
    assert body["error"]["code"] == "VALIDATION_ERROR"
    # message is a human string — either "age: ..." or the raw msg.
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["message"]  # non-empty
    # detail shim matches message
    assert body["detail"] == body["error"]["message"]
    # full per-field error list is preserved for frontends that want it
    assert isinstance(body["error"]["errors"], list)
    assert len(body["error"]["errors"]) >= 1


def test_validation_error_handler_handles_empty_errors() -> None:
    exc = RequestValidationError([])
    response = _run(validation_error_handler(_fake_request(), exc))
    body = _body(response)
    assert response.status_code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "validation error"
    assert body["error"]["errors"] == []


# ================================================================ app wiring


def test_handlers_are_registered_on_app() -> None:
    """Importing :mod:`app.main` must wire all three handlers."""
    from app.main import app

    handlers = app.exception_handlers
    assert ApiError in handlers
    assert HTTPException in handlers
    assert RequestValidationError in handlers


def test_envelope_detail_shim_mirrors_error_message() -> None:
    """Across every handler, ``detail`` must mirror ``error.message`` —
    this is the backward-compat contract the frontend relies on until
    it's migrated to read ``error.message`` directly."""
    cases = [
        _run(
            api_error_handler(
                _fake_request(),
                ApiError(code=ErrorCode.NOT_FOUND, message="a", status_code=404),
            )
        ),
        _run(
            http_error_handler(
                _fake_request(),
                HTTPException(status_code=400, detail="b"),
            )
        ),
        _run(
            validation_error_handler(
                _fake_request(),
                _make_request_validation_error(),
            )
        ),
    ]
    for response in cases:
        body = _body(response)
        assert body["detail"] == body["error"]["message"]
