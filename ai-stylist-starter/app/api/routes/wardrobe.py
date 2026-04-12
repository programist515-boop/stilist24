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

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.api.errors import ApiError, ErrorCode
from app.core.storage import (
    StorageError,
    StorageService,
    StorageValidationError,
    get_storage_service,
)
from app.repositories.wardrobe_repository import WardrobeRepository
from app.schemas.wardrobe import (
    WardrobeConfirmIn,
    WardrobeConfirmOut,
    WardrobeItemOut,
    WardrobeListOut,
)

router = APIRouter()


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
        "image_url": item.image_url,
        "is_verified": item.is_verified,
    }


@router.post("/upload", response_model=WardrobeItemOut)
async def upload_item(
    image: UploadFile = File(...),
    category: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
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

    repo = WardrobeRepository(db)
    item = repo.create(
        user_id=user_id,
        item_id=item_id,
        image_key=asset.key,
        image_url=asset.url,
        category=category or "top",
        attributes={
            "primary_color": "white",
            "line_type": "clean",
            "fit": "regular",
            "style_tags": ["classic", "minimal"],
        },
    )
    return _serialize(item)


@router.get("/items", response_model=WardrobeListOut)
def list_items(
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    """List the caller's wardrobe items wrapped in ``{items, count}``."""
    repo = WardrobeRepository(db)
    items = [_serialize(item) for item in repo.list_by_user(user_id)]
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
    updated = repo.update(
        payload.item_id,
        attributes_json=payload.attributes,
        is_verified=True,
    )
    if updated is None:
        raise ApiError(
            code=ErrorCode.NOT_FOUND,
            message="wardrobe item not found",
            status_code=404,
        )
    return {"item": _serialize(updated)}
