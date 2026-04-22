"""preference-based profile + quiz sessions

Adds preference-derived fields to style_profiles (kibbe_type_preference,
color_season_preference, active_profile_source, etc.) and creates a new
preference_quiz_sessions table that tracks Tinder-style style/color quizzes.

Revision ID: 0008_preference_profile
Revises: 0007_shopping_candidates
Create Date: 2026-04-21 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0008_preference_profile"
down_revision = "0007_shopping_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "style_profiles",
        sa.Column("kibbe_type_preference", sa.String(), nullable=True),
    )
    op.add_column(
        "style_profiles",
        sa.Column("kibbe_preference_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "style_profiles",
        sa.Column("color_season_preference", sa.String(), nullable=True),
    )
    op.add_column(
        "style_profiles",
        sa.Column("color_preference_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "style_profiles",
        sa.Column("preference_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "style_profiles",
        sa.Column(
            "active_profile_source",
            sa.String(length=16),
            nullable=False,
            server_default="algorithmic",
        ),
    )

    op.create_table(
        "preference_quiz_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("quiz_type", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("stage", sa.String(length=16), nullable=True),
        sa.Column("candidates_json", JSONB, nullable=False, server_default="[]"),
        sa.Column("votes_json", JSONB, nullable=False, server_default="[]"),
        sa.Column("result_json", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_preference_quiz_sessions_user_id",
        "preference_quiz_sessions",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_preference_quiz_sessions_user_id", "preference_quiz_sessions"
    )
    op.drop_table("preference_quiz_sessions")

    op.drop_column("style_profiles", "active_profile_source")
    op.drop_column("style_profiles", "preference_completed_at")
    op.drop_column("style_profiles", "color_preference_confidence")
    op.drop_column("style_profiles", "color_season_preference")
    op.drop_column("style_profiles", "kibbe_preference_confidence")
    op.drop_column("style_profiles", "kibbe_type_preference")
