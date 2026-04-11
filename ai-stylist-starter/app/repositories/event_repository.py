import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user_event import UserEvent


class EventRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        user_id: uuid.UUID,
        event_type: str,
        payload: dict | None = None,
    ) -> UserEvent:
        event = UserEvent(
            user_id=user_id,
            event_type=event_type,
            payload_json=payload or {},
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def get_by_id(self, event_id: uuid.UUID) -> UserEvent | None:
        return self.db.get(UserEvent, event_id)

    def list_by_user(
        self,
        user_id: uuid.UUID,
        event_type: str | None = None,
    ) -> list[UserEvent]:
        stmt = select(UserEvent).where(UserEvent.user_id == user_id)
        if event_type is not None:
            stmt = stmt.where(UserEvent.event_type == event_type)
        stmt = stmt.order_by(UserEvent.created_at.desc())
        return list(self.db.execute(stmt).scalars().all())
