import uuid
from sqlalchemy import ForeignKey, DateTime, func, Boolean, String
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class WardrobeItem(Base):
    __tablename__ = "wardrobe_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    attributes_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    scores_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    # image_key is the canonical storage reference. image_url is kept for
    # backward compatibility and is a projection of image_key that may be
    # rebuilt at any time (e.g. presigned URL rotation).
    image_key: Mapped[str | None] = mapped_column(String, nullable=True)
    image_url: Mapped[str] = mapped_column(String, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
