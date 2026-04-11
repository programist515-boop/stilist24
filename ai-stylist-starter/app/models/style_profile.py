import uuid
from sqlalchemy import ForeignKey, DateTime, func, Float, String
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class StyleProfile(Base):
    __tablename__ = "style_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    kibbe_type: Mapped[str | None] = mapped_column(String, nullable=True)
    kibbe_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    color_profile_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    style_vector_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
