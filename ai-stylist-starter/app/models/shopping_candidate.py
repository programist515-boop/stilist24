import uuid
from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ShoppingCandidate(Base):
    """Short-lived record for a prospective purchase under evaluation.

    Created when the user hits ``POST /shopping/evaluate`` and retained so
    the evaluation can be re-fetched or referenced in a later wear-log if
    the user buys the item.  Rows are ephemeral — the expectation is that
    a background job prunes entries older than 30 days.
    """

    __tablename__ = "shopping_candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    attributes_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    retailer: Mapped[str | None] = mapped_column(String, nullable=True)
    image_key: Mapped[str | None] = mapped_column(String, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    inferred_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
