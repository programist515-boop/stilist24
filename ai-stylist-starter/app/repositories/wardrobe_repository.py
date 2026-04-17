import uuid
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.wardrobe_item import WardrobeItem


class WardrobeRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        user_id: uuid.UUID,
        image_url: str,
        category: str | None = None,
        attributes: dict | None = None,
        scores: dict | None = None,
        is_verified: bool = False,
        image_key: str | None = None,
        item_id: uuid.UUID | None = None,
    ) -> WardrobeItem:
        item = WardrobeItem(
            user_id=user_id,
            category=category,
            attributes_json=attributes or {},
            scores_json=scores or {},
            image_key=image_key,
            image_url=image_url,
            is_verified=is_verified,
        )
        if item_id is not None:
            item.id = item_id
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def get_by_id(self, item_id: uuid.UUID) -> WardrobeItem | None:
        return self.db.get(WardrobeItem, item_id)

    def list_by_user(self, user_id: uuid.UUID) -> list[WardrobeItem]:
        stmt = (
            select(WardrobeItem)
            .where(WardrobeItem.user_id == user_id)
            .order_by(WardrobeItem.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def increment_wear_count(self, item_id: uuid.UUID) -> WardrobeItem | None:
        stmt = (
            update(WardrobeItem)
            .where(WardrobeItem.id == item_id)
            .values(wear_count=WardrobeItem.wear_count + 1)
            .returning(WardrobeItem)
        )
        result = self.db.execute(stmt).scalars().first()
        self.db.commit()
        return result

    def update(self, item_id: uuid.UUID, **fields) -> WardrobeItem | None:
        item = self.get_by_id(item_id)
        if item is None:
            return None
        for key, value in fields.items():
            if hasattr(item, key):
                setattr(item, key, value)
        self.db.commit()
        self.db.refresh(item)
        return item
