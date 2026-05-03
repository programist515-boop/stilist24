"""Production-grade observability for the CV category classifier.

Two read-only endpoints (no auth — values are non-sensitive):

* ``GET /api/cv-classifier/config`` — reflects the active settings
  (env values that Pydantic Settings actually loaded). The OpenAI API
  key is reduced to ``set: bool`` and ``length: int`` — never echoed.
* ``GET /api/cv-classifier/recent`` — last ~100 classifier attempts as
  JSONL stored in /tmp (shared across uvicorn workers via ``fcntl.flock``).

Kept permanently because the alternative is what we did all afternoon:
debug endpoints get added on every prod report, removed in a "cleanup"
PR, then re-added on the next report. Observability isn't debt — for a
feature gated by a paid third-party API it's part of the feature.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.services.category_classifier import (
    get_category_classifier,
    get_recent_attempts,
    get_vision_analyzer,
)

router = APIRouter()


@router.get("/config")
def cv_classifier_config() -> dict:
    vision_analyzer = get_vision_analyzer(settings)
    proxy = (settings.openai_http_proxy or "").strip()
    return {
        "use_cv_category_classifier": settings.use_cv_category_classifier,
        "enable_vision_analysis": settings.enable_vision_analysis,
        "category_classifier_provider": settings.category_classifier_provider,
        "category_confidence_threshold": settings.category_confidence_threshold,
        "openai_base_url": settings.openai_base_url,
        "openai_model": settings.openai_model,
        "openai_api_key_set": bool(settings.openai_api_key),
        "openai_api_key_length": len(settings.openai_api_key),
        "openai_http_proxy_set": bool(proxy),
        "openai_http_proxy_scheme": proxy.split("://", 1)[0] if "://" in proxy else None,
        "active_classifier_type": type(get_category_classifier(settings)).__name__,
        "vision_analyzer_active": vision_analyzer is not None,
    }


@router.get("/recent")
def cv_classifier_recent(limit: int = 20) -> dict:
    """Last classifier attempts in chronological order.

    Each entry has timestamp, image bytes count, full prediction
    (category/confidence/source/reasoning), and on cloud failures the
    raw OpenAI response + parsed JSON for diagnosis.
    """
    attempts = get_recent_attempts()
    return {
        "count": len(attempts),
        "attempts": attempts[-limit:],
    }
