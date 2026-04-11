import uuid
from sqlalchemy import Integer, String, DateTime, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lifestyle: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
