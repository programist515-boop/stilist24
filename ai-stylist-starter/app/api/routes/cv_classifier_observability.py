"""Production-grade observability for the CV category classifier.

Two read-only endpoints (no auth — values are non-sensitive):

* ``GET /api/cv-classifier/config`` — reflects the active settings
  (env values that Pydantic Settings actually loaded). The Claude API
  key is reduced to ``set: bool`` and ``length: int`` — never echoed.
* ``GET /api/cv-classifier/recent`` — last ~100 classifier attempts as
  JSONL stored in /tmp (shared across uvicorn workers via ``fcntl.flock``).

Kept permanently because the alternative is what we did all afternoon:
debug endpoints get added on every prod report, removed in a "cleanup"
PR, then re-added on the next report. Observability isn't debt — for a
feature gated by a paid third-party proxy it's part of the feature.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.services.category_classifier import (
    get_category_classifier,
    get_recent_attempts,
)

router = APIRouter()


@router.get("/config")
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


@router.get("/recent")
def cv_classifier_recent(limit: int = 20) -> dict:
    """Last classifier attempts in chronological order.

    Each entry has timestamp, image bytes count, full prediction
    (category/confidence/source/reasoning), and on cloud failures the
    raw kie.ai response + parsed JSON for diagnosis.
    """
    attempts = get_recent_attempts()
    return {
        "count": len(attempts),
        "attempts": attempts[-limit:],
    }
