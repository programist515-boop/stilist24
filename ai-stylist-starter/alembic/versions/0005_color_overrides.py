"""style_profiles color_overrides_json

Adds color_overrides_json JSONB column to style_profiles for storing manual
corrections to auto-detected color axes (undertone, depth, chroma, contrast)
and manual season selection.

Revision ID: 0005_color_overrides
Revises: 0004_wardrobe_cost_wear
Create Date: 2026-04-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005_color_overrides"
down_revision = "0004_wardrobe_cost_wear"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "style_profiles",
        sa.Column(
            "color_overrides_json",
            JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("style_profiles", "color_overrides_json")
