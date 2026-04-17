"""Wear log service — record and query wear events.

Each call to ``log_item_worn`` creates a WearLog row AND increments
``wardrobe_items.wear_count`` so the two stay in sync.
``log_outfit_worn`` creates one WearLog row per item in the outfit.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class WearLogService:
    def __init__(self, db: "Session") -> None:
        self.db = db

    def log_item_worn(
        self,
        user_id: uuid.UUID,
        item_id: uuid.UUID,
        worn_date: date | None = None,
        outfit_id: uuid.UUID | None = None,
        rating: int | None = None,
        notes: str | None = None,
    ) -> dict:
        from app.repositories.wardrobe_repository import WardrobeRepository
        from app.repositories.wear_log_repository import WearLogRepository

        if worn_date is None:
            worn_date = datetime.now(timezone.utc).date()

        row = WearLogRepository(self.db).create(
            user_id=user_id,
            item_id=item_id,
            worn_date=worn_date,
            outfit_id=outfit_id,
            rating=rating,
            notes=notes,
        )
        WardrobeRepository(self.db).increment_wear_count(item_id)
        return _serialize_log(row)

    def log_outfit_worn(
        self,
        user_id: uuid.UUID,
        outfit_id: uuid.UUID,
        worn_date: date | None = None,
        rating: int | None = None,
        notes: str | None = None,
    ) -> list[dict]:
        from app.models.outfit import Outfit
        from app.repositories.wardrobe_repository import WardrobeRepository
        from app.repositories.wear_log_repository import WearLogRepository

        if worn_date is None:
            worn_date = datetime.now(timezone.utc).date()

        outfit: Outfit | None = self.db.get(Outfit, outfit_id)
        if outfit is None or outfit.user_id != user_id:
            return []

        item_ids: list[str] = outfit.items_json or []
        repo = WearLogRepository(self.db)
        wardrobe_repo = WardrobeRepository(self.db)
        results = []
        seen_item_ids: set[str] = set()  # guard against duplicates in items_json
        for item_id_str in item_ids:
            if str(item_id_str) in seen_item_ids:
                continue
            seen_item_ids.add(str(item_id_str))
            try:
                item_id = uuid.UUID(str(item_id_str))
            except (ValueError, AttributeError):
                continue
            row = repo.create(
                user_id=user_id,
                item_id=item_id,
                worn_date=worn_date,
                outfit_id=outfit_id,
                rating=rating,
                notes=notes,
            )
            wardrobe_repo.increment_wear_count(item_id)
            results.append(_serialize_log(row))
        return results

    def get_history(
        self,
        user_id: uuid.UUID,
        item_id: uuid.UUID,
    ) -> list[dict]:
        from app.repositories.wear_log_repository import WearLogRepository
        rows = WearLogRepository(self.db).list_by_item(user_id, item_id)
        return [_serialize_log(r) for r in rows]


def _serialize_log(row: Any) -> dict:
    return {
        "id": str(row.id),
        "item_id": str(row.item_id),
        "outfit_id": str(row.outfit_id) if row.outfit_id else None,
        "worn_date": str(row.worn_date),
        "rating": row.rating,
        "notes": row.notes,
        "created_at": str(row.created_at),
    }
