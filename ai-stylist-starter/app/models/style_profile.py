import uuid
from sqlalchemy import ForeignKey, DateTime, func, Float, String
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


PROFILE_SOURCE_ALGORITHMIC = "algorithmic"
PROFILE_SOURCE_PREFERENCE = "preference"


class StyleProfile(Base):
    __tablename__ = "style_profiles"

    # PK is persona_id: one StyleProfile per persona, not per user.
    # user_id is retained as a NOT NULL indexed column for backward-compat
    # queries that still resolve by owning account.
    persona_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("personas.id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    kibbe_type: Mapped[str | None] = mapped_column(String, nullable=True)
    kibbe_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    color_profile_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    style_vector_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Stores manual corrections to auto-detected color axes and season selection.
    # Schema: {auto_hair_color, auto_eye_color, auto_undertone,
    #          manual_hair_color, manual_eye_color, manual_undertone,
    #          manual_selected_season, override_history: []}
    color_overrides_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Preference-quiz-derived profile (alternative to algorithmic analysis).
    # Populated by the Tinder-style style quiz; consumed via style_profile_resolver.
    kibbe_type_preference: Mapped[str | None] = mapped_column(String, nullable=True)
    kibbe_preference_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    color_season_preference: Mapped[str | None] = mapped_column(String, nullable=True)
    color_preference_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    preference_completed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Which profile feeds downstream recommendations: "algorithmic" | "preference".
    active_profile_source: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=PROFILE_SOURCE_ALGORITHMIC
    )
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
