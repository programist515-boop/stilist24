import uuid
from sqlalchemy.orm import Session

from app.models.personalization_profile import PersonalizationProfile


class PersonalizationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, user_id: uuid.UUID) -> PersonalizationProfile:
        profile = PersonalizationProfile(
            user_id=user_id,
            style_vector_json={},
            line_vector_json={},
            color_vector_json={},
            avoidance_vector_json={},
            experimentation_score=0.3,
        )
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(profile)
        return profile

    def get_by_id(self, user_id: uuid.UUID) -> PersonalizationProfile | None:
        return self.db.get(PersonalizationProfile, user_id)

    def get_or_create(self, user_id: uuid.UUID) -> PersonalizationProfile:
        profile = self.get_by_id(user_id)
        if profile is None:
            profile = self.create(user_id)
        return profile

    def update(self, user_id: uuid.UUID, **fields) -> PersonalizationProfile | None:
        profile = self.get_by_id(user_id)
        if profile is None:
            return None
        for key, value in fields.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        self.db.commit()
        self.db.refresh(profile)
        return profile
