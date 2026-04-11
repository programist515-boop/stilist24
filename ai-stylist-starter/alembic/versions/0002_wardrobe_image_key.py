"""wardrobe_items.image_key

Adds the canonical ``image_key`` storage reference to wardrobe items. The
existing ``image_url`` column is retained for backward compatibility and
becomes a derived projection of ``image_key``.

Revision ID: 0002_wardrobe_image_key
Revises: 0001_initial
Create Date: 2026-04-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_wardrobe_image_key"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wardrobe_items",
        sa.Column("image_key", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_wardrobe_items_image_key",
        "wardrobe_items",
        ["image_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_wardrobe_items_image_key", table_name="wardrobe_items")
    op.drop_column("wardrobe_items", "image_key")
