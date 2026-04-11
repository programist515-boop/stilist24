import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.models.style_profile import StyleProfile
from app.repositories.outfit_repository import OutfitRepository
from app.repositories.personalization_repository import PersonalizationRepository
from app.repositories.wardrobe_repository import WardrobeRepository
from app.schemas.outfit import OutfitGenerateIn
from app.services.outfit_engine import OutfitEngine

router = APIRouter()


def _item_to_dict(item) -> dict:
    attrs = item.attributes_json or {}
    return {
        "id": str(item.id),
        "category": item.category,
        "name": attrs.get("name"),
        "attributes": attrs,
        # Hoist the attributes the scoring engine expects so it can read them
        # whether it gets the flat or nested form.
        **attrs,
    }


def _build_user_context(db: Session, user_id: uuid.UUID) -> dict:
    """Assemble the user context the scoring engine consumes.

    Pulls identity family + color profile from ``StyleProfile`` (if it exists)
    and the latest preference vector from ``PersonalizationProfile``. Both
    profiles are optional — the scoring service tolerates missing keys.
    """
    style: StyleProfile | None = db.get(StyleProfile, user_id)
    perso = PersonalizationRepository(db).get_or_create(user_id)
    return {
        "identity_family": style.kibbe_type if style else None,
        "color_profile": (style.color_profile_json or {}) if style else {},
        "style_vector": perso.style_vector_json or {},
        "lifestyle": [],
    }


@router.post("/generate")
def generate_outfits(
    payload: OutfitGenerateIn,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    wardrobe_repo = WardrobeRepository(db)
    outfit_repo = OutfitRepository(db)

    items = [_item_to_dict(i) for i in wardrobe_repo.list_by_user(user_id)]
    user_context = _build_user_context(db, user_id)
    generated = OutfitEngine().generate(items, user_context=user_context, occasion=payload.occasion)

    for outfit in generated:
        outfit_repo.create(
            user_id=user_id,
            items=outfit.get("items", []),
            scores=outfit.get("scores", {}),
            explanation="; ".join(outfit.get("explanation", []) or []),
        )

    return {"count": len(generated), "items": generated}
