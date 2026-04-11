import uuid
from sqlalchemy.orm import Session

from app.repositories.event_repository import EventRepository
from app.repositories.personalization_repository import PersonalizationRepository
from app.services.personalization_service import PersonalizationService


class FeedbackService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.events = EventRepository(db)
        self.profiles = PersonalizationRepository(db)
        self.personalization_service = PersonalizationService()

    def process(self, user_id: uuid.UUID, event_type: str, payload: dict) -> dict:
        self.events.create(user_id=user_id, event_type=event_type, payload=payload)

        profile = self.profiles.get_or_create(user_id)
        profile_dict = {
            "style_vector_json": dict(profile.style_vector_json or {}),
            "line_vector_json": dict(profile.line_vector_json or {}),
            "color_vector_json": dict(profile.color_vector_json or {}),
            "avoidance_vector_json": dict(profile.avoidance_vector_json or {}),
            "experimentation_score": profile.experimentation_score,
        }
        updated = self.personalization_service.update_profile(
            profile_dict, event_type, payload
        )
        self.profiles.update(
            user_id,
            style_vector_json=updated["style_vector_json"],
            line_vector_json=updated["line_vector_json"],
            color_vector_json=updated["color_vector_json"],
            avoidance_vector_json=updated["avoidance_vector_json"],
            experimentation_score=updated.get("experimentation_score", 0.3),
        )
        return updated
