"""wardrobe_items.name: пользователь видит и правит короткое название вещи

Добавляет одну nullable Text-колонку. Заполняется vision-анализатором
при загрузке (``OpenAIVisionAnalyzer``); если vision выключен или упал
— остаётся NULL, фронт ничего не показывает в поле имени.

Revision ID: 0011_wardrobe_item_name
Revises: 0010_personas
Create Date: 2026-05-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0011_wardrobe_item_name"
down_revision = "0010_personas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wardrobe_items",
        sa.Column("name", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wardrobe_items", "name")
