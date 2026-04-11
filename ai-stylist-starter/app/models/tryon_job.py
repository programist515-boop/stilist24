import uuid
from sqlalchemy import ForeignKey, DateTime, func, String, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


# Status vocabulary. Plain strings (no DB-level enum) so the set is easy to
# evolve. The synchronous flow only needs pending → succeeded/failed; the
# ``running`` value is reserved for future async/queued execution.
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"


class TryOnJob(Base):
    __tablename__ = "tryon_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wardrobe_items.id"), nullable=True
    )
    user_photo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_photos.id"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="fashn")
    provider_job_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=STATUS_PENDING)
    # result_image_key is the canonical storage reference; result_image_url
    # is a derived projection retained for backward compatibility.
    result_image_key: Mapped[str | None] = mapped_column(String, nullable=True)
    result_image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
