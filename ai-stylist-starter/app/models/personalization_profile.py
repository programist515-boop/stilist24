import uuid
from sqlalchemy import ForeignKey, DateTime, func, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class PersonalizationProfile(Base):
    __tablename__ = "personalization_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    style_vector_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    line_vector_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    color_vector_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    avoidance_vector_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    experimentation_score: Mapped[float] = mapped_column(Float, default=0.3)
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
