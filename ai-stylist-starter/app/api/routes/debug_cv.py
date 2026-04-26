"""Diagnostic endpoint for the CV category classifier — TEMPORARY.

Re-armed because user reports "Не получилось определить категорию" on
fresh uploads. Lets us run one classification end-to-end and see what
the classifier actually returned (cloud or heuristic, confidence,
exception). No auth, no DB, no secret leakage.
"""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from app.core.config import settings
from app.services.category_classifier import (
    ClaudeCategoryClassifier,
    HeuristicCategoryClassifier,
    get_category_classifier,
)

router = APIRouter()


@router.get("/cv-classifier/config")
def cv_classifier_config() -> dict:
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
    """Run classify() on the uploaded image, raw exception surfaced.

    Bypasses the wrapper-level fallback so a failing kie.ai call shows
    up as ``exception`` in the response instead of being masked as a
    heuristic prediction. The factory-built classifier is still used,
    so this matches what /wardrobe/upload would see.
    """
    data = await image.read()
    classifier = get_category_classifier(settings)
    out: dict = {
        "active_classifier_type": type(classifier).__name__,
        "image_bytes": len(data),
    }
    if isinstance(classifier, ClaudeCategoryClassifier):
        try:
            pred = classifier._call_claude(data, None, image.content_type or "image/jpeg")
            out["prediction"] = {
                "category": pred.category,
                "confidence": pred.confidence,
                "source": pred.source,
                "reasoning": pred.reasoning,
            }
        except Exception as exc:  # noqa: BLE001
            out["exception_type"] = type(exc).__name__
            out["exception_message"] = str(exc)[:500]
    else:
        # Heuristic — feed nothing; just confirm what UX path we'd take.
        pred = classifier.classify(data)
        out["prediction"] = {
            "category": pred.category,
            "confidence": pred.confidence,
            "source": pred.source,
            "reasoning": pred.reasoning,
        }
    return out
