import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        auth_provider: str,
        email: str | None = None,
        provider_id: str | None = None,
        password_hash: str | None = None,
    ) -> User:
        user = User(
            email=email,
            auth_provider=auth_provider,
            provider_id=provider_id,
            password_hash=password_hash,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        return self.db.execute(stmt).scalar_one_or_none()

    def update(self, user_id: uuid.UUID, **fields) -> User | None:
        user = self.get_by_id(user_id)
        if user is None:
            return None
        for key, value in fields.items():
            if hasattr(user, key):
                setattr(user, key, value)
        self.db.commit()
        self.db.refresh(user)
        return user
