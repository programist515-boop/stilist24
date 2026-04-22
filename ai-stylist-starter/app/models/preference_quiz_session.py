import uuid
from sqlalchemy import ForeignKey, DateTime, func, String
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


QUIZ_TYPE_IDENTITY = "identity"
QUIZ_TYPE_COLOR = "color"

STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"
STATUS_ABANDONED = "abandoned"

# Identity quiz stages: stock cards → try-on on finalists.
STAGE_STOCK = "stock"
STAGE_TRYON = "tryon"
# Color quiz stages: family (4 seasons) → season (3 within winner family).
STAGE_FAMILY = "family"
STAGE_SEASON = "season"


class PreferenceQuizSession(Base):
    __tablename__ = "preference_quiz_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    quiz_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_PENDING)
    stage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    candidates_json: Mapped[list] = mapped_column(JSONB, default=list)
    votes_json: Mapped[list] = mapped_column(JSONB, default=list)
    result_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
