import uuid
from sqlalchemy import ForeignKey, DateTime, Date, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class WearLog(Base):
    __tablename__ = "wear_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("wardrobe_items.id"), nullable=False)
    outfit_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("outfits.id"), nullable=True)
    worn_date: Mapped[str] = mapped_column(Date, nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1–5
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
