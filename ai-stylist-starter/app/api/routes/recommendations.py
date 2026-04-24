"""Recommendations route — curated per-identity stylist guide.

``GET /recommendations/style-guide`` resolves the acting user's Kibbe
family from :class:`StyleProfile`, optionally blends in their top style
vector tags from :class:`PersonalizationProfile`, and returns a
structured Russian-language guide for the frontend to render as an
editorial report.

Business logic lives in
:class:`app.services.recommendation_guide_service.RecommendationGuideService`;
the route just wires the DB + user id to it, matching the same pattern
as ``today``, ``insights`` and ``tryon``.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_persona_id, get_current_user_id, get_db
from app.schemas.recommendations import RecommendationGuideResponse
from app.services.recommendation_guide_service import (
    RecommendationGuideService,
)

router = APIRouter()


@router.get("/style-guide", response_model=RecommendationGuideResponse)
def get_style_guide(
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    # Ensure the dependency is invoked (persona cache kept fresh for
    # downstream consumers); the guide currently keys on user_id because
    # StyleProfile resolves to primary persona internally.
    _ = persona_id
    return RecommendationGuideService(db).get_guide(user_id)
