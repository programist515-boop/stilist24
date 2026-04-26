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

from fastapi import APIRouter, File, UploadFile

from app.core.config import settings
from app.services.category_classifier import get_category_classifier

router = APIRouter()


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
