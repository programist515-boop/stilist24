import uuid
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.item_attributes import NEW_ATTRIBUTE_NAMES
from app.models.wardrobe_item import WardrobeItem


class WardrobeRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        user_id: uuid.UUID,
        image_url: str,
        *,
        persona_id: uuid.UUID | None = None,
        category: str | None = None,
        name: str | None = None,
        attributes: dict | None = None,
        structured_attrs: dict | None = None,
        scores: dict | None = None,
        is_verified: bool = False,
        image_key: str | None = None,
        item_id: uuid.UUID | None = None,
    ) -> WardrobeItem:
        """Insert a ``WardrobeItem`` row.

        ``persona_id`` can be omitted by legacy callers: we then resolve
        (or create on first use) the user's primary persona so the
        NOT NULL FK is satisfied without rewriting every route at once.

        ``structured_attrs`` принимает плоский dict из 14 Phase-0 атрибутов
        (fabric_rigidity, ..., style_tags). Чужие ключи игнорируются.
        Валидация значений — на уровне SQLAlchemy ``@validates`` в
        ``WardrobeItem``.
        """
        if persona_id is None:
            from app.repositories.persona_repository import PersonaRepository

            persona_id = PersonaRepository(self.db).ensure_primary(user_id).id
        item = WardrobeItem(
            user_id=user_id,
            persona_id=persona_id,
            category=category,
            name=name,
            attributes_json=attributes or {},
            scores_json=scores or {},
            image_key=image_key,
            image_url=image_url,
            is_verified=is_verified,
        )
        if structured_attrs:
            for key, value in structured_attrs.items():
                if key in NEW_ATTRIBUTE_NAMES:
                    setattr(item, key, value)
        if item_id is not None:
            item.id = item_id
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def get_by_id(self, item_id: uuid.UUID) -> WardrobeItem | None:
        return self.db.get(WardrobeItem, item_id)

    def list_by_user(self, user_id: uuid.UUID) -> list[WardrobeItem]:
        """Account-wide listing across all personas (legacy/admin usage)."""
        stmt = (
            select(WardrobeItem)
            .where(WardrobeItem.user_id == user_id)
            .order_by(WardrobeItem.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_by_persona(self, persona_id: uuid.UUID) -> list[WardrobeItem]:
        stmt = (
            select(WardrobeItem)
            .where(WardrobeItem.persona_id == persona_id)
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
