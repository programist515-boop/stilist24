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
from app.core.config import settings
from app.core.storage import (
    StorageError,
    StorageService,
    StorageValidationError,
    fresh_public_url,
    get_storage_service,
)
from app.models.style_profile import StyleProfile
from app.repositories.wardrobe_repository import WardrobeRepository
from app.services.category_classifier import (
    get_category_classifier,
    get_vision_analyzer,
)
from app.services.user_context import build_user_context_from_db
from app.services.garment_recognizer import recognize_garment
from app.services.wardrobe.attribute_normalizer import apply_manual_update, normalize as normalize_attrs
from app.schemas.versatility import VersatilityResponse
from app.schemas.wardrobe import (
    WardrobeCategoryPatchIn,
    WardrobeConfirmIn,
    WardrobeConfirmOut,
    WardrobeItemOut,
    WardrobeItemPatchIn,
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
        "name": getattr(item, "name", None),
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
    """Upload фото вещи + автоматически определить параметры через CV.

    Pipeline:
      1. Прочитать байты, загрузить оригинал в S3.
      2. Параллельно: rembg-маска (через ``recognize_garment``) и
         vision-анализ (``OpenAIVisionAnalyzer.analyze``) — оба запускаются
         в потоках через ``asyncio.to_thread``, latency сокращается ≈ в 1.5×.
      3. Если vision успешен — берём category, name, primary_color и 14
         структурных атрибутов из его ответа. Иначе fallback на эвристики
         (``recognize_garment`` для color/print + опционально старый
         category-classifier).
      4. Сохранить nobg-версию в S3 (если rembg вернул байты).
      5. Записать item в БД с уже заполненными name/category/structured_attrs.
    """
    import asyncio

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

    # ---- Параллельный CV-pipeline ---------------------------------------
    # rembg всегда нужен (дать пользователю красивую картинку без фона);
    # vision-анализ идёт только при включённом флаге и наличии ключа.
    analyzer = get_vision_analyzer(settings)

    rembg_task = asyncio.to_thread(recognize_garment, data, hint_category=category)
    vision_task = (
        asyncio.to_thread(analyzer.analyze, data) if analyzer is not None else None
    )

    detected = await rembg_task
    vision_result = None
    if vision_task is not None:
        try:
            vision_result = await vision_task
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "wardrobe/upload: vision analysis failed for item %s: %s",
                item_id,
                exc,
            )
            vision_result = None

    # ---- Сохранить nobg PNG в S3 ---------------------------------------
    image_key_final = asset.key
    image_url_final = asset.url
    nobg_bytes = detected.get("_processed_png_bytes")
    if nobg_bytes:
        nobg_key = f"{asset.key.rsplit('.', 1)[0]}_nobg.png"
        try:
            storage.backend.put(nobg_key, nobg_bytes, content_type="image/png")
            image_key_final = nobg_key
            image_url_final = storage.backend.public_url(nobg_key)
        except StorageError as exc:
            import logging
            logging.getLogger(__name__).warning(
                "wardrobe/upload: nobg save failed for item %s: %s", item_id, exc,
            )

    # ---- Решить category, name, primary_color, structured_attrs ---------
    resolved_category: str | None = category
    category_meta: dict | None = (
        {"value": category, "confidence": 1.0, "source": "user"} if category else None
    )
    resolved_name: str | None = None
    primary_color_value: str | None = detected.get("primary_color")
    primary_color_source: str | None = detected.get("_color_source")
    primary_color_confidence: float = 0.7
    structured_attrs: dict = {}

    if vision_result is not None:
        # Vision определил всё разом — он наш единственный источник.
        resolved_name = vision_result.name
        if vision_result.primary_color:
            primary_color_value = vision_result.primary_color
            primary_color_source = "cloud_llm"
            primary_color_confidence = vision_result.confidence
        if category is None and vision_result.confidence >= settings.category_confidence_threshold:
            resolved_category = vision_result.category
        if category_meta is None:
            category_meta = {
                "value": vision_result.category,
                "confidence": vision_result.confidence,
                "source": vision_result.source,
            }
        structured_attrs = dict(vision_result.attrs)
    elif category is None and settings.use_cv_category_classifier:
        # Vision выключен — старый путь: только category, без 14 атрибутов.
        classifier = get_category_classifier(settings)
        pred = classifier.classify(data, attrs_hint=detected)
        category_meta = {
            "value": pred.category,
            "confidence": pred.confidence,
            "source": pred.source,
        }
        if pred.confidence >= settings.category_confidence_threshold:
            resolved_category = pred.category

    # ---- Собрать v2-attributes_json ------------------------------------
    raw_for_normalizer = {
        "primary_color": {
            "value": primary_color_value,
            "confidence": primary_color_confidence,
            "source": primary_color_source,
        },
        "pattern": {
            "value": detected["print_type"],
            "confidence": 0.7,
            "source": detected["_print_source"],
        },
    }
    attributes_v2 = normalize_attrs(raw_for_normalizer)
    if category_meta is not None:
        attributes_v2["category"] = {**category_meta, "editable": True}

    repo = WardrobeRepository(db)
    item = repo.create(
        user_id=user_id,
        persona_id=persona_id,
        item_id=item_id,
        image_key=image_key_final,
        image_url=image_url_final,
        category=resolved_category,
        name=resolved_name,
        attributes=attributes_v2,
        structured_attrs=structured_attrs,
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
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Verify attributes on an existing wardrobe item.

    * ``item_id`` is a real UUID (Pydantic rejects malformed strings
      before we get here — the error envelope handler turns them into
      a ``VALIDATION_ERROR`` 422 response).
    * A missing item, or one owned by a different persona, is a **404**
      through the error envelope. No more ``{"status": "not_found"}``
      200 body.
    """
    repo = WardrobeRepository(db)
    item = repo.get_by_id(payload.item_id)
    if item is None or item.persona_id != persona_id:
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
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Return how many valid outfit combinations this item enables."""
    repo = WardrobeRepository(db)
    item = repo.get_by_id(item_id)
    if item is None or item.persona_id != persona_id:
        raise ApiError(
            code=ErrorCode.NOT_FOUND,
            message="wardrobe item not found",
            status_code=404,
        )
    wardrobe = repo.list_by_persona(persona_id)
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
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Increment wear_count for an item the user has marked as worn."""
    repo = WardrobeRepository(db)
    item = repo.get_by_id(item_id)
    if item is None or item.persona_id != persona_id:
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
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Log a wear event for a wardrobe item."""
    repo = WardrobeRepository(db)
    item = repo.get_by_id(item_id)
    if item is None or item.persona_id != persona_id:
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
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Get wear history for a wardrobe item."""
    repo = WardrobeRepository(db)
    item = repo.get_by_id(item_id)
    if item is None or item.persona_id != persona_id:
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
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Return wardrobe items ranked by orphan score (hardest to outfit first)."""
    wardrobe_repo = WardrobeRepository(db)
    items = wardrobe_repo.list_by_persona(persona_id)
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

    from app.services.style_profile_resolver import load_style_profile
    style = load_style_profile(user_id=user_id, db=db)
    palette_hex: list[str] = []
    if style and style.color_profile_json:
        palette_hex = style.color_profile_json.get("palette_hex", [])

    graph = ItemCompatibilityGraph().build(items_as_dicts)
    orphans = detect_batch(items_as_dicts, graph, palette_hex)
    return {"orphans": orphans, "count": len(orphans)}


@router.get("/analytics/redundancy")
def get_redundancy(
    db: Session = Depends(get_db),
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Return redundancy clusters in the current persona's wardrobe."""
    wardrobe_repo = WardrobeRepository(db)
    items = wardrobe_repo.list_by_persona(persona_id)
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
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Extended gap analysis: layering, occasion, palette, imbalance, overbought."""
    wardrobe_repo = WardrobeRepository(db)
    items = wardrobe_repo.list_by_persona(persona_id)
    items_as_dicts = [
        {
            "id": str(i.id),
            "category": i.category,
            "wear_count": i.wear_count,
            "attributes": i.attributes_json or {},
        }
        for i in items
    ]
    from app.services.style_profile_resolver import load_style_profile
    style = load_style_profile(user_id=user_id, db=db)
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
    persona_id: uuid.UUID = Depends(get_current_persona_id),
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
    if item is None or item.persona_id != persona_id:
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


@router.patch("/{item_id}/category", response_model=WardrobeItemOut)
def update_item_category(
    item_id: uuid.UUID,
    payload: WardrobeCategoryPatchIn,
    db: Session = Depends(get_db),
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Заменить категорию вещи (ручное исправление CV-определения).

    Используется, когда CV-распознавание поставило вещь в неверный
    слот — например, тренч попал в «top» вместо «outerwear». Возвращает
    полный обновлённый item, фронт может сразу подменить в кэше.
    """
    repo = WardrobeRepository(db)
    item = repo.get_by_id(item_id)
    if item is None or item.persona_id != persona_id:
        raise ApiError(
            code=ErrorCode.NOT_FOUND,
            message="wardrobe item not found",
            status_code=404,
        )
    repo.update(item_id, category=payload.category)
    item = repo.get_by_id(item_id)
    return _serialize(item)


@router.patch("/{item_id}", response_model=WardrobeItemOut)
def update_item(
    item_id: uuid.UUID,
    payload: WardrobeItemPatchIn,
    db: Session = Depends(get_db),
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Обновить вещь (имя и/или категорию).

    Принимает только поля, которые юзер реально поменял в карточке
    после автоматического распознавания: name, category. Любое поле
    опционально. Если оба None — это no-op, возвращаем текущее
    состояние без записи.
    """
    repo = WardrobeRepository(db)
    item = repo.get_by_id(item_id)
    if item is None or item.persona_id != persona_id:
        raise ApiError(
            code=ErrorCode.NOT_FOUND,
            message="wardrobe item not found",
            status_code=404,
        )
    fields: dict = {}
    if payload.category is not None:
        fields["category"] = payload.category
    if payload.name is not None:
        fields["name"] = payload.name
    if fields:
        repo.update(item_id, **fields)
        item = repo.get_by_id(item_id)
    return _serialize(item)
