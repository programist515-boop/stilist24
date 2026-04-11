import uuid
from sqlalchemy import ForeignKey, DateTime, func, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class UserPhoto(Base):
    """A user-supplied reference photo (front / side / portrait).

    The image bytes live in the storage layer; this row only carries the
    canonical ``image_key`` reference and a backward-compatible ``image_url``
    projection — exactly the same discipline as :class:`WardrobeItem`.
    """

    __tablename__ = "user_photos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    slot: Mapped[str] = mapped_column(String(32), nullable=False)
    image_key: Mapped[str] = mapped_column(String, nullable=False)
    image_url: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
