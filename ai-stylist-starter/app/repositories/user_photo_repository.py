import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user_photo import UserPhoto


class UserPhotoRepository:
    """Thin CRUD for stored user reference photos.

    No business logic — only persistence. The image bytes themselves are
    owned by the storage layer; this repository only handles the row that
    points at the canonical ``image_key``.

    After the multi-persona migration (0010), every photo is scoped to
    a ``persona_id``. ``user_id`` is kept on the row for compatibility
    and account-wide queries, but read methods that want isolated
    persona-level results should use ``list_by_persona`` / ``latest_by_slot_for_persona``.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        user_id: uuid.UUID,
        slot: str,
        image_key: str,
        image_url: str,
        persona_id: uuid.UUID | None = None,
        photo_id: uuid.UUID | None = None,
    ) -> UserPhoto:
        """Insert a ``UserPhoto`` row.

        ``persona_id`` can be left out by legacy callers: we then resolve
        (or create on first use) the user's primary persona. This keeps
        pre-multi-persona code paths working without a big-bang refactor.
        """
        if persona_id is None:
            from app.repositories.persona_repository import PersonaRepository

            persona_id = PersonaRepository(self.db).ensure_primary(user_id).id
        photo = UserPhoto(
            user_id=user_id,
            persona_id=persona_id,
            slot=slot,
            image_key=image_key,
            image_url=image_url,
        )
        if photo_id is not None:
            photo.id = photo_id
        self.db.add(photo)
        self.db.commit()
        self.db.refresh(photo)
        return photo

    def get_by_id(self, photo_id: uuid.UUID) -> UserPhoto | None:
        return self.db.get(UserPhoto, photo_id)

    def list_by_user(self, user_id: uuid.UUID) -> list[UserPhoto]:
        """Account-wide listing across all personas (legacy/admin usage)."""
        stmt = (
            select(UserPhoto)
            .where(UserPhoto.user_id == user_id)
            .order_by(UserPhoto.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_by_persona(self, persona_id: uuid.UUID) -> list[UserPhoto]:
        stmt = (
            select(UserPhoto)
            .where(UserPhoto.persona_id == persona_id)
            .order_by(UserPhoto.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def latest_by_slot(
        self, user_id: uuid.UUID, slot: str
    ) -> UserPhoto | None:
        """Kept for compatibility with callers that still key by user_id."""
        stmt = (
            select(UserPhoto)
            .where(UserPhoto.user_id == user_id, UserPhoto.slot == slot)
            .order_by(UserPhoto.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def latest_by_slot_for_persona(
        self, persona_id: uuid.UUID, slot: str
    ) -> UserPhoto | None:
        stmt = (
            select(UserPhoto)
            .where(UserPhoto.persona_id == persona_id, UserPhoto.slot == slot)
            .order_by(UserPhoto.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()
