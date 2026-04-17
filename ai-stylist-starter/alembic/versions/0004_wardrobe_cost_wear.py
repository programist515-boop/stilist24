"""wardrobe_items cost and wear_count

Adds optional cost (float) and wear_count (int) columns to wardrobe_items.
Both are nullable/defaulted so no existing row is affected.

Revision ID: 0004_wardrobe_cost_wear
Revises: 0003_user_photos_tryon
Create Date: 2026-04-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_wardrobe_cost_wear"
down_revision = "0003_user_photos_tryon"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wardrobe_items",
        sa.Column("cost", sa.Float(), nullable=True),
    )
    op.add_column(
        "wardrobe_items",
        sa.Column("wear_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_wardrobe_items_user_id",
        "wardrobe_items",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_wardrobe_items_user_id", table_name="wardrobe_items")
    op.drop_column("wardrobe_items", "wear_count")
    op.drop_column("wardrobe_items", "cost")
