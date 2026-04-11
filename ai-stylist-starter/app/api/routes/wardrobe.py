import uuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.storage import (
    StorageService,
    StorageValidationError,
    get_storage_service,
)
from app.repositories.wardrobe_repository import WardrobeRepository

router = APIRouter()


class WardrobeConfirmIn(BaseModel):
    item_id: str
    attributes: dict


def _serialize(item) -> dict:
    return {
        "id": str(item.id),
        "category": item.category,
        "attributes": item.attributes_json or {},
        "image_key": item.image_key,
        "image_url": item.image_url,
        "is_verified": item.is_verified,
    }


@router.post("/upload")
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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


@router.get("/items")
def list_items(
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[dict]:
    repo = WardrobeRepository(db)
    return [_serialize(item) for item in repo.list_by_user(user_id)]


@router.post("/confirm")
def confirm_item(
    payload: WardrobeConfirmIn,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    repo = WardrobeRepository(db)
    try:
        item_uuid = uuid.UUID(payload.item_id)
    except ValueError:
        return {"status": "not_found"}
    item = repo.get_by_id(item_uuid)
    if item is None or item.user_id != user_id:
        return {"status": "not_found"}
    updated = repo.update(
        item_uuid,
        attributes_json=payload.attributes,
        is_verified=True,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"status": "updated", "item": _serialize(updated)}
