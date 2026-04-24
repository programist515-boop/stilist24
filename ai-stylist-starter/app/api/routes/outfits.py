import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_persona_id, get_current_user_id, get_db
from app.api.errors import ApiError, ErrorCode
from app.repositories.outfit_repository import OutfitRepository
from app.repositories.wardrobe_repository import WardrobeRepository
from app.schemas.outfit import OutfitGenerateIn, OutfitGenerateOut
from app.services.outfits.outfit_generator import OutfitGenerator
from app.services.user_context import build_user_context_from_db

router = APIRouter()


def _item_to_dict(item) -> dict:
    attrs = item.attributes_json or {}
    return {
        **attrs,
        "id": str(item.id),
        "category": item.category,
        "cost": item.cost,
        "wear_count": item.wear_count or 0,
        "attributes": attrs,
    }


_build_user_context = build_user_context_from_db


@router.post("/generate", response_model=OutfitGenerateOut)
def generate_outfits(
    payload: OutfitGenerateIn,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Generate labelled outfits from the caller's wardrobe.

    Wire-level change: the top-level collection key was renamed from
    ``items`` to ``outfits`` to remove the ambiguity with the per-outfit
    ``items`` list (which holds wardrobe entries for that outfit). The
    new shape is locked to :class:`OutfitGenerateOut`.
    """
    wardrobe_repo = WardrobeRepository(db)
    outfit_repo = OutfitRepository(db)

    items = [_item_to_dict(i) for i in wardrobe_repo.list_by_persona(persona_id)]
    user_context = _build_user_context(db, user_id)
    generated = OutfitGenerator().generate(
        items,
        user_profile=user_context,
        occasion=payload.occasion,
    )

    for outfit in generated:
        outfit_repo.create(
            user_id=user_id,
            items=outfit.get("items", []),
            scores=outfit.get("scores", {}),
            explanation="; ".join(outfit.get("explanation", []) or []),
        )

    return {"outfits": generated, "count": len(generated)}


@router.get("/for-item/{item_id}")
def outfits_for_item(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Return scored outfits anchored on a specific wardrobe item.

    Every returned outfit includes the requested item. The ``breakdown``
    field exposes per-scorer scores (color_harmony, palette_fit, reuse, …).
    """
    wardrobe_repo = WardrobeRepository(db)
    item = wardrobe_repo.get_by_id(item_id)
    # IDOR guard: item must belong to the active persona, not just the
    # user — otherwise switching personas would leak secondary-profile
    # items into the primary's outfits.
    if item is None or item.persona_id != persona_id:
        raise ApiError(
            code=ErrorCode.NOT_FOUND,
            message="wardrobe item not found",
            status_code=404,
        )
    items = [_item_to_dict(i) for i in wardrobe_repo.list_by_persona(persona_id)]
    user_context = _build_user_context(db, user_id)
    outfits = OutfitGenerator().generate_for_item(
        str(item_id), items, user_profile=user_context
    )
    return {"item_id": str(item_id), "outfits": outfits, "count": len(outfits)}


@router.get("/for-occasion/{occasion}")
def outfits_for_occasion(
    occasion: str,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Return scored outfits filtered for a specific occasion.

    ``occasion`` must be a string matching the item attribute values used in
    the wardrobe (e.g. ``casual``, ``business``, ``evening``).
    """
    wardrobe_repo = WardrobeRepository(db)
    items = [_item_to_dict(i) for i in wardrobe_repo.list_by_persona(persona_id)]
    user_context = _build_user_context(db, user_id)
    outfits = OutfitGenerator().generate_for_occasion(
        occasion, items, user_profile=user_context
    )
    return {"occasion": occasion, "outfits": outfits, "count": len(outfits)}


@router.post("/{outfit_id}/worn")
def mark_outfit_worn(
    outfit_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    """Record that the user wore this outfit today.

    Increments ``wear_count`` for every item in the outfit and fires an
    ``outfit_worn`` personalization event so the preference scorer adapts.
    Returns the list of updated wear-log entries.
    """
    from app.services.wardrobe.wear_log_service import WearLogService
    from app.services.feedback_service import FeedbackService

    logs = WearLogService(db).log_outfit_worn(
        user_id=user_id,
        outfit_id=outfit_id,
    )
    if not logs:
        outfit = OutfitRepository(db).get_by_id(outfit_id)
        if outfit is None or outfit.user_id != user_id:
            raise ApiError(
                code=ErrorCode.NOT_FOUND,
                message="outfit not found",
                status_code=404,
            )
    # Fire personalization event
    FeedbackService(db).process(
        user_id=user_id,
        event_type="outfit_worn",
        payload={"outfit_id": str(outfit_id)},
    )
    return {"outfit_id": str(outfit_id), "items_logged": len(logs), "logs": logs}
