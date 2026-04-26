"""Diagnostic endpoint for the CV category classifier — TEMPORARY.

Purpose: when the prod UI shows "Не получилось определить категорию",
this lets us inspect the live config + execute one classification call
end-to-end (with image bytes posted by the caller) and see exactly what
the classifier returned — without auth, without touching the DB.

Remove after the kie.ai integration is validated in prod (one cleanup
PR — see plan ``2026-04-26-cv-категория-вещей.md``). Safe to deploy:
no secrets are returned, the API key flag is reduced to a boolean.
"""

from __future__ import annotations

import base64
import time

import httpx
from fastapi import APIRouter, File, UploadFile

from app.core.config import settings
from app.services.category_classifier import (
    _SYSTEM_PROMPT,
    _parse_json_object,
    get_category_classifier,
    get_recent_attempts,
)

router = APIRouter()


@router.get("/cv-classifier/recent")
def cv_classifier_recent() -> dict:
    """Return the most recent in-process classifier attempts.

    Each entry includes the raw kie.ai response, the parser outcome, and
    the final prediction stored. Useful for diagnosing prod failures
    where the wrapped classifier silently fell back to heuristic and the
    user sees ``category=None``.
    """
    attempts = get_recent_attempts()
    return {
        "count": len(attempts),
        "attempts": attempts,
    }


@router.get("/cv-classifier/config")
def cv_classifier_config() -> dict:
    """Return the non-sensitive parts of the active classifier config.

    No secret values are returned — ``claude_api_key`` is reduced to a
    bool so we can confirm Pydantic Settings actually loaded the env.
    """
    return {
        "use_cv_category_classifier": settings.use_cv_category_classifier,
        "category_classifier_provider": settings.category_classifier_provider,
        "category_confidence_threshold": settings.category_confidence_threshold,
        "claude_base_url": settings.claude_base_url,
        "claude_model": settings.claude_model,
        "claude_auth_scheme": settings.claude_auth_scheme,
        "claude_api_key_set": bool(settings.claude_api_key),
        "claude_api_key_length": len(settings.claude_api_key),
        "active_classifier_type": type(get_category_classifier(settings)).__name__,
    }


@router.post("/cv-classifier/probe")
async def cv_classifier_probe(image: UploadFile = File(...)) -> dict:
    """Run one classification on the uploaded image, return raw result.

    Useful when the upload route stores ``category=None`` and we need to
    know whether the classifier returned low confidence, fell back to
    heuristic, or failed at the HTTP layer. The response includes the
    full ``CategoryPrediction`` so we can see source/reasoning directly.
    """
    data = await image.read()
    classifier = get_category_classifier(settings)
    pred = classifier.classify(data)
    return {
        "active_classifier_type": type(classifier).__name__,
        "image_bytes": len(data),
        "prediction": {
            "category": pred.category,
            "confidence": pred.confidence,
            "source": pred.source,
            "reasoning": pred.reasoning,
        },
        "would_be_stored_as": (
            pred.category
            if pred.confidence >= settings.category_confidence_threshold
            else None
        ),
    }


@router.post("/cv-classifier/raw-claude")
async def cv_classifier_raw_claude(image: UploadFile = File(...)) -> dict:
    """Direct passthrough to the configured Claude endpoint, no fallback.

    This bypasses ``ClaudeCategoryClassifier`` entirely and posts the
    image straight to ``{claude_base_url}/v1/messages``. The response
    body and parser result are returned verbatim — perfect for finding
    out *why* the wrapped classifier fell back to heuristic on a given
    image (timeout? unexpected text? truncated content? HTTP error?).
    """
    data = await image.read()
    b64 = base64.standard_b64encode(data).decode("ascii")
    body = {
        "model": settings.claude_model,
        "max_tokens": 200,
        "system": _SYSTEM_PROMPT,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image.content_type or "image/jpeg",
                            "data": b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Classify the garment. Reply with the JSON object only.",
                    },
                ],
            }
        ],
    }
    headers = {"Content-Type": "application/json"}
    if settings.claude_auth_scheme == "x-api-key":
        headers["x-api-key"] = settings.claude_api_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {settings.claude_api_key}"

    result: dict = {
        "image_bytes": len(data),
        "request_url": f"{settings.claude_base_url}/v1/messages",
        "model": settings.claude_model,
    }
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=25.0) as client:
            r = client.post(
                f"{settings.claude_base_url}/v1/messages",
                headers=headers,
                json=body,
            )
        result["http_status"] = r.status_code
        result["latency_s"] = round(time.perf_counter() - t0, 2)
        try:
            result["response_json"] = r.json()
        except Exception:
            result["response_text"] = r.text[:2000]
            return result

        # Reproduce the wrapped classifier's parser steps so we can see
        # which one fails.
        content = result["response_json"].get("content") if isinstance(result["response_json"], dict) else None
        if not content:
            result["parser_step"] = "empty_content"
            return result
        text_parts = [
            b.get("text") for b in content
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        ]
        if not text_parts:
            result["parser_step"] = "no_text_block"
            result["raw_blocks"] = content
            return result
        joined = "\n".join(text_parts)
        result["text_block"] = joined
        parsed = _parse_json_object(joined)
        if parsed is None:
            result["parser_step"] = "json_unparseable"
        else:
            result["parser_step"] = "ok"
            result["parsed_json"] = parsed
        return result
    except Exception as exc:  # noqa: BLE001
        result["latency_s"] = round(time.perf_counter() - t0, 2)
        result["exception_type"] = type(exc).__name__
        result["exception_message"] = str(exc)[:500]
        return result
