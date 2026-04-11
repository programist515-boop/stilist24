import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.outfit import Outfit


class OutfitRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        user_id: uuid.UUID,
        items: list[dict] | None = None,
        scores: dict | None = None,
        explanation: str | None = None,
    ) -> Outfit:
        outfit = Outfit(
            user_id=user_id,
            items_json=items or [],
            scores_json=scores or {},
            explanation=explanation,
        )
        self.db.add(outfit)
        self.db.commit()
        self.db.refresh(outfit)
        return outfit

    def get_by_id(self, outfit_id: uuid.UUID) -> Outfit | None:
        return self.db.get(Outfit, outfit_id)

    def list_by_user(self, user_id: uuid.UUID) -> list[Outfit]:
        stmt = (
            select(Outfit)
            .where(Outfit.user_id == user_id)
            .order_by(Outfit.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def update(self, outfit_id: uuid.UUID, **fields) -> Outfit | None:
        outfit = self.get_by_id(outfit_id)
        if outfit is None:
            return None
        for key, value in fields.items():
            if hasattr(outfit, key):
                setattr(outfit, key, value)
        self.db.commit()
        self.db.refresh(outfit)
        return outfit
