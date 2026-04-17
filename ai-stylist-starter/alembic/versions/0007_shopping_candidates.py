"""shopping_candidates table

Ephemeral records for prospective purchases under evaluation.
Retained for 30 days then pruned by a background job.

Revision ID: 0007_shopping_candidates
Revises: 0006_wear_log
Create Date: 2026-04-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0007_shopping_candidates"
down_revision = "0006_wear_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shopping_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("attributes_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("price", sa.Float, nullable=True),
        sa.Column("retailer", sa.String, nullable=True),
        sa.Column("image_key", sa.String, nullable=True),
        sa.Column("image_url", sa.String, nullable=True),
        sa.Column("inferred_confidence", sa.Float, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_shopping_candidates_user_id",
        "shopping_candidates",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_shopping_candidates_user_id", "shopping_candidates")
    op.drop_table("shopping_candidates")
