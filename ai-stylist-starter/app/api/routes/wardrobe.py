"""Wardrobe routes — thin layer over :class:`WardrobeRepository`.

Phase 3 cleanup:

* ``POST /wardrobe/upload`` now maps **both** ``StorageValidationError``
  (→ 400) and ``StorageError`` (→ 502) to the error envelope. Previously
  the service-level backend failure bubbled up as a raw 500.
* ``GET /wardrobe/items`` returns :class:`WardrobeListOut` —
  ``{"items": [...], "count": N}`` — instead of a bare JSON array. This
  is the wire-level breaking change approved in Phase 0.
* ``POST /wardrobe/confirm`` parses ``item_id`` as a real UUID via
  :class:`WardrobeConfirmIn`, and surfaces a missing row as a proper
  404 through :class:`ApiError` instead of the old
  ``{"status": "not_found"}`` 200 body.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_persona_id, get_current_user_id, get_db
from app.api.errors import ApiError, ErrorCode
from app.core.storage import (
    StorageError,
    StorageService,
    StorageValidationError,
    fresh_public_url,
    get_storage_service,
)
from app.models.style_profile import StyleProfile
from app.repositories.wardrobe_repository import WardrobeRepository
from app.services.user_context import build_user_context_from_db
from app.services.garment_recognizer import recognize_garment
from app.services.wardrobe.attribute_normalizer import apply_manual_update, normalize as normalize_attrs
from app.schemas.versatility import VersatilityResponse
from app.schemas.wardrobe import (
    WardrobeConfirmIn,
    WardrobeConfirmOut,
    WardrobeItemOut,
    WardrobeListOut,
)
from app.services.versatility_service import VersatilityService

router = APIRouter()


_build_user_context = build_user_context_from_db


def _serialize(item) -> dict:
    """Build the wire dict for a wardrobe item.

    Single source of truth used by every wardrobe route. The shape
    matches :class:`WardrobeItemOut` byte-for-byte — FastAPI validates
    it via ``response_model`` on each route.
    """
    return {
        "id": str(item.id),
        "category": item.category,
        "attributes": item.attributes_json or {},
        "image_key": item.image_key,
        "image_url": fresh_public_url(item.image_key, item.image_url),
        "is_verified": item.is_verified,
        "cost": item.cost,
        "wear_count": item.wear_count,
    }


@router.post("/upload", response_model=WardrobeItemOut)
async def upload_item(
    image: UploadFile = File(...),
    category: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
    persona_id: uuid.UUID = Depends(get_current_persona_id),
    storage: StorageService = Depends(get_storage_service),
) -> dict:
    # Read the uploaded file exactly once. The route stays thin — all
    # validation, key generation, and URL projection happen inside the
    # storage service.
    data = await image.read()
    item_id = uuid.uuid4()
    try:
        asset = storage.upload_wardrobe_image(
            user_id,
            item_id,
            data=data,
            content_type=image.content_type or "",
            filename=image.filename,
            persona_id=persona_id,
        )
    except StorageValidationError as exc:
        raise ApiError(
            code=ErrorCode.VALIDATION_ERROR,
            message=str(exc),
            status_code=400,
        ) from exc
    except StorageError as exc:
        raise ApiError(
            code=ErrorCode.STORAGE_ERROR,
            message=str(exc),
            status_code=502,
        ) from exc

    detected = recognize_garment(data, hint_category=category)

    # Normalize to v2 structured attributes (value + confidence + source + editable)
    raw_for_normalizer = {
        "category": category or "tops",
        "primary_color": {"value": detected["primary_color"], "confidence": 0.7, "source": detected["_color_source"]},
        "pattern": {"value": detected["print_type"], "confidence": 0.7, "source": detected["_print_source"]},
    }
    attributes_v2 = normalize_attrs(raw_for_normalizer)

    repo = WardrobeRepository(db)
    item = repo.create(
        user_id=user_id,
        persona_id=persona_id,
        item_id=item_id,
        image_key=asset.key,
        image_url=asset.url,
        category=category or "top",
        attributes=attributes_v2,
    )
    return _serialize(item)


@router.get("/items", response_model=WardrobeListOut)
def list_items(
    db: Session = Depends(get_db),
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """List the current persona's wardrobe items wrapped in ``{items, count}``."""
    repo = WardrobeRepository(db)
    items = [_serialize(item) for item in repo.list_by_persona(persona_id)]
    return {"items": items, "count": len(items)}


@router.post("/confirm", response_model=WardrobeConfirmOut)
def confirm_item(
    payload: WardrobeConfirmIn,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    """Verify attributes on an existing wardrobe item.

    * ``item_id`` is a real UUID (Pydantic rejects malformed strings
      before we get here — the error envelope handler turns them into
      a ``VALIDATION_ERROR`` 422 response).
    * A missing item, or one owned by a different user, is a **404**
      through the error envelope. No more ``{"status": "not_found"}``
      200 body.
    """
    repo = WardrobeRepository(db)
    item = repo.get_by_id(payload.item_id)
    if item is None or item.user_id != user_id:
        raise ApiError(
            code=ErrorCode.NOT_FOUND,
            message="wardrobe item not found",
            status_code=404,
        )
    # Merge manual updates into the existing structured attrs.
    # If existing attrs are v2 dicts (have "value" keys), use apply_manual_update;
    # otherwise normalize from scratch.
    existing_attrs: dict = item.attributes_json or {}
    first_val = next(iter(existing_attrs.values()), None)
    if isinstance(first_val, dict) and "value" in first_val:
        final_attrs = apply_manual_update(existing_attrs, payload.attributes)
    else:
        final_attrs = normalize_attrs({**existing_attrs, **payload.attributes})

    updated = repo.update(
        payload.item_id,
        attributes_json=final_attrs,
        is_verified=True,
    )
    if updated is None:
        raise ApiError(
            code=ErrorCode.NOT_FOUND,
            message="wardrobe item not found",
            status_code=404,
        )
    return {"item": _serialize(updated)}


@router.get("/{item_id}/versatility", response_model=VersatilityResponse)
def item_versatility(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    """Return how many valid outfit combinations this item enables."""
    repo = WardrobeRepository(db)
    item = repo.get_by_id(item_id)
    if item is None or item.user_id != user_id:
        raise ApiError(
            code=ErrorCode.NOT_FOUND,
            message="wardrobe item not found",
            status_code=404,
        )
    wardrobe = repo.list_by_user(user_id)
    items_as_dicts = [
        {
            **(i.attributes_json or {}),
            "id": str(i.id),
            "category": i.category,
            "cost": i.cost,
            "wear_count": i.wear_count,
            "attributes": i.attributes_json or {},
        }
        for i in wardrobe
    ]
    user_context = _build_user_context(db, user_id)
    return VersatilityService(db).compute(item_id, items_as_dicts, user_context)


@router.post("/{item_id}/worn", response_model=WardrobeItemOut)
def mark_item_worn(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    """Increment wear_count for an item the user has marked as worn."""
    repo = WardrobeRepository(db)
    item = repo.get_by_id(item_id)
    if item is None or item.user_id != user_id:
        raise ApiError(
            code=ErrorCode.NOT_FOUND,
            message="wardrobe item not found",
            status_code=404,
        )
    updated = repo.increment_wear_count(item_id)
    if updated is None:
        raise ApiError(
            code=ErrorCode.NOT_FOUND,
            message="wardrobe item not found",
            status_code=404,
        )
    return _serialize(updated)


# ---------------------------------------------------------------------------
# Wear log endpoints
# ---------------------------------------------------------------------------


@router.post("/{item_id}/wear-log")
def log_item_worn(
    item_id: uuid.UUID,
    worn_date: date | None = Body(default=None),
    rating: int | None = Body(default=None, ge=1, le=5),
    notes: str | None = Body(default=None),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    """Log a wear event for a wardrobe item."""
    repo = WardrobeRepository(db)
    item = repo.get_by_id(item_id)
    if item is None or item.user_id != user_id:
        raise ApiError(code=ErrorCode.NOT_FOUND, message="wardrobe item not found", status_code=404)
    from app.services.wardrobe.wear_log_service import WearLogService
    return WearLogService(db).log_item_worn(
        user_id=user_id,
        item_id=item_id,
        worn_date=worn_date,
        rating=rating,
        notes=notes,
    )


@router.get("/{item_id}/wear-log")
def get_wear_log(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    """Get wear history for a wardrobe item."""
    repo = WardrobeRepository(db)
    item = repo.get_by_id(item_id)
    if item is None or item.user_id != user_id:
        raise ApiError(code=ErrorCode.NOT_FOUND, message="wardrobe item not found", status_code=404)
    from app.services.wardrobe.wear_log_service import WearLogService
    history = WearLogService(db).get_history(user_id=user_id, item_id=item_id)
    return {"item_id": str(item_id), "entries": history, "count": len(history)}


# ---------------------------------------------------------------------------
# Analytics endpoints
# ---------------------------------------------------------------------------


@router.get("/analytics/orphans")
def get_orphan_items(
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    """Return wardrobe items ranked by orphan score (hardest to outfit first)."""
    wardrobe_repo = WardrobeRepository(db)
    items = wardrobe_repo.list_by_user(user_id)
    items_as_dicts = [
        {
            "id": str(i.id),
            "category": i.category,
            "cost": i.cost,
            "wear_count": i.wear_count,
            "attributes": i.attributes_json or {},
        }
        for i in items
    ]
    if not items_as_dicts:
        return {"orphans": [], "count": 0}

    from app.services.analytics.item_graph import ItemCompatibilityGraph
    from app.services.analytics.orphan_detector import detect_batch

    style = db.get(StyleProfile, user_id)
    palette_hex: list[str] = []
    if style and style.color_profile_json:
        palette_hex = style.color_profile_json.get("palette_hex", [])

    graph = ItemCompatibilityGraph().build(items_as_dicts)
    orphans = detect_batch(items_as_dicts, graph, palette_hex)
    return {"orphans": orphans, "count": len(orphans)}


@router.get("/analytics/redundancy")
def get_redundancy(
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    """Return redundancy clusters in the user's wardrobe."""
    wardrobe_repo = WardrobeRepository(db)
    items = wardrobe_repo.list_by_user(user_id)
    items_as_dicts = [
        {
            "id": str(i.id),
            "category": i.category,
            "attributes": i.attributes_json or {},
        }
        for i in items
    ]
    from app.services.analytics.redundancy_service import redundancy_summary
    return redundancy_summary(items_as_dicts)


@router.get("/analytics/gaps-extended")
def get_extended_gaps(
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    """Extended gap analysis: layering, occasion, palette, imbalance, overbought."""
    wardrobe_repo = WardrobeRepository(db)
    items = wardrobe_repo.list_by_user(user_id)
    items_as_dicts = [
        {
            "id": str(i.id),
            "category": i.category,
            "wear_count": i.wear_count,
            "attributes": i.attributes_json or {},
        }
        for i in items
    ]
    style = db.get(StyleProfile, user_id)
    palette_hex: list[str] = []
    if style and style.color_profile_json:
        palette_hex = style.color_profile_json.get("palette_hex", [])

    from app.services.analytics.gap_analyzer import analyze_extended
    return analyze_extended(items_as_dicts, user_context={"palette_hex": palette_hex})


@router.patch("/{item_id}/attributes", response_model=WardrobeItemOut)
def update_item_attributes(
    item_id: uuid.UUID,
    updates: dict = Body(...),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    """Apply manual attribute corrections to a wardrobe item.

    Accepts a flat dict of attribute overrides — e.g.
    ``{"primary_color": "navy", "fit": "slim"}``.  Each supplied key
    is merged into the item's v2 attribute store via
    ``apply_manual_update`` so every field retains its
    ``{value, source, editable}`` envelope and ``source`` is stamped
    ``"manual"``.
    """
    repo = WardrobeRepository(db)
    item = repo.get_by_id(item_id)
    if item is None or item.user_id != user_id:
        raise ApiError(
            code=ErrorCode.NOT_FOUND,
            message="wardrobe item not found",
            status_code=404,
        )
    existing_attrs = item.attributes_json or {}
    updated_attrs = apply_manual_update(existing_attrs, updates)
    repo.update(item_id, attributes_json=updated_attrs)
    item = repo.get_by_id(item_id)
    return _serialize(item)
