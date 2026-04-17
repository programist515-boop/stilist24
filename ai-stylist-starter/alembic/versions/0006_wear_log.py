"""wear_logs table

Stores individual wear events per wardrobe item. Enables CPW calculation,
observed versatility, and wear-pattern analytics.

Revision ID: 0006_wear_log
Revises: 0005_color_overrides
Create Date: 2026-04-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0006_wear_log"
down_revision = "0005_color_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wear_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("item_id", UUID(as_uuid=True), sa.ForeignKey("wardrobe_items.id"), nullable=False),
        sa.Column("outfit_id", UUID(as_uuid=True), sa.ForeignKey("outfits.id"), nullable=True),
        sa.Column("worn_date", sa.Date(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_wear_logs_user_item", "wear_logs", ["user_id", "item_id"])
    op.create_index("ix_wear_logs_user_date", "wear_logs", ["user_id", "worn_date"])


def downgrade() -> None:
    op.drop_index("ix_wear_logs_user_date", table_name="wear_logs")
    op.drop_index("ix_wear_logs_user_item", table_name="wear_logs")
    op.drop_table("wear_logs")
