"""API-роут ``GET /reference-looks`` (Фаза 7).

Отдаёт референсные луки активного подтипа пользователя вместе со
сматченными вещами из гардероба и списком недостающих слотов (для
последующей передачи в gap_analysis).

Подтип определяется через ``style_profile_resolver`` — то есть учитывает
как алгоритмический результат, так и preference-quiz, если пользователь
его прошёл.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.repositories.wardrobe_repository import WardrobeRepository
from app.schemas.reference_looks import (
    MatchedItemOut,
    MissingSlotOut,
    ReferenceLookOut,
    ReferenceLooksResponse,
)
from app.services.reference_matcher import ReferenceMatcher
from app.services.style_profile_resolver import get_active_profile_by_user_id

router = APIRouter()


def _build_matcher() -> ReferenceMatcher:
    """Сборка матчера.

    TODO(A2-merge): подменить дефолтный ``_AllowAllCategoryRules`` на
    реальный ``CategoryRulesService`` (Фаза 2) когда он приедет в main.
    Сейчас дефолт — pass-through, матчер отрабатывает без валидатора.
    """
    return ReferenceMatcher()


@router.get("", response_model=ReferenceLooksResponse)
def list_reference_looks(
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ReferenceLooksResponse:
    profile = get_active_profile_by_user_id(user_id, db)
    subtype = profile.kibbe_type
    if not subtype:
        return ReferenceLooksResponse(subtype=None, looks=[])

    wardrobe = WardrobeRepository(db).list_by_user(user_id)
    matcher = _build_matcher()
    matches = matcher.match_wardrobe(wardrobe, subtype)

    looks = [
        ReferenceLookOut(
            look_id=m.look_id,
            title=m.title,
            occasion=m.occasion,
            image_url=m.image_url,
            description=m.description,
            matched_items=[
                MatchedItemOut(
                    slot=mi.slot,
                    item_id=mi.item_id,
                    match_quality=mi.match_quality,
                    match_reasons=list(mi.match_reasons),
                )
                for mi in m.matched_items
            ],
            missing_slots=[
                MissingSlotOut(
                    slot=ms.slot,
                    requires=dict(ms.requires),
                    shopping_hint=ms.shopping_hint,
                )
                for ms in m.missing_slots
            ],
            completeness=m.completeness,
            slot_order=list(m.slot_order),
        )
        for m in matches
    ]

    return ReferenceLooksResponse(subtype=subtype, looks=looks)
