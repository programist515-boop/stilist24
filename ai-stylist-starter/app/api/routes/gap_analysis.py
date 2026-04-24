"""Gap analysis route — GET /wardrobe/gap-analysis.

Registered in main.py BEFORE wardrobe.router to prevent FastAPI from
matching the literal path segment "gap-analysis" as a /{item_id} UUID.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_persona_id, get_current_user_id, get_db
from app.repositories.wardrobe_repository import WardrobeRepository
from app.schemas.gap_analysis import GapAnalysisResponse
from app.services.gap_analysis_service import GapAnalysisService
from app.services.user_context import build_user_context_from_db

router = APIRouter()


def _item_to_dict(item) -> dict:
    attrs = item.attributes_json or {}
    return {
        **attrs,
        "id": str(item.id),
        "category": item.category,
        "cost": item.cost,
        "wear_count": item.wear_count,
        "attributes": attrs,
    }


_build_user_context = build_user_context_from_db


@router.get("/gap-analysis", response_model=GapAnalysisResponse)
def gap_analysis(
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Identify wardrobe gaps and project new outfit combinations per suggestion."""
    wardrobe_items = WardrobeRepository(db).list_by_persona(persona_id)
    wardrobe = [_item_to_dict(i) for i in wardrobe_items]
    user_context = _build_user_context(db, user_id)
    return GapAnalysisService(db).analyze(wardrobe, user_context)
