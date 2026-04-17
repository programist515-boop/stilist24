from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class WearLogRepository:
    def __init__(self, db: "Session") -> None:
        self.db = db

    def create(
        self,
        user_id: uuid.UUID,
        item_id: uuid.UUID,
        worn_date: date,
        outfit_id: uuid.UUID | None = None,
        rating: int | None = None,
        notes: str | None = None,
    ):
        from app.models.wear_log import WearLog
        row = WearLog(
            id=uuid.uuid4(),
            user_id=user_id,
            item_id=item_id,
            outfit_id=outfit_id,
            worn_date=worn_date,
            rating=rating,
            notes=notes,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_by_item(self, user_id: uuid.UUID, item_id: uuid.UUID) -> list:
        from app.models.wear_log import WearLog
        return (
            self.db.query(WearLog)
            .filter(WearLog.user_id == user_id, WearLog.item_id == item_id)
            .order_by(WearLog.worn_date.desc())
            .all()
        )

    def list_by_user(self, user_id: uuid.UUID, since: date | None = None) -> list:
        from app.models.wear_log import WearLog
        q = self.db.query(WearLog).filter(WearLog.user_id == user_id)
        if since is not None:
            q = q.filter(WearLog.worn_date >= since)
        return q.order_by(WearLog.worn_date.desc()).all()

    def count_by_item(self, user_id: uuid.UUID, item_id: uuid.UUID) -> int:
        from app.models.wear_log import WearLog
        return (
            self.db.query(WearLog)
            .filter(WearLog.user_id == user_id, WearLog.item_id == item_id)
            .count()
        )
