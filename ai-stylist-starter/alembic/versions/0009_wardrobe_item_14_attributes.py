"""wardrobe_items: 14 новых атрибутов одежды (Фаза 0)

Расширяет таблицу ``wardrobe_items`` 14 nullable-колонками с атрибутами
вещи, необходимыми для правил силуэта/категорий/стоп-листов из плана
``plans/2026-04-21-каталог-фич-из-отчёта-типажа.md`` (Фаза 0).

Все колонки nullable=True — честный NULL, если CV-экстрактор не смог
определить значение (design_philosophy: «честные quality downgrades»).

Расположение в цепочке: ``0007_shopping_candidates`` → ``0008_preference_profile``
→ ``0009_wardrobe_item_14_attributes``. Миграция 0008 пришла из
параллельного трека (preference-based профиль) и на момент применения
0009 должна быть уже в head — она добавляет колонки в style_profiles,
не пересекается с wardrobe_items.

Revision ID: 0009_wardrobe_item_14_attributes
Revises: 0008_preference_profile
Create Date: 2026-04-22 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0009_wardrobe_item_14_attributes"
down_revision = "0008_preference_profile"
branch_labels = None
depends_on = None


# Единый список 13 скалярных String-колонок (style_tags — массив, отдельно).
# Порядок совпадает с определением в ``app.models.wardrobe_item``.
_SCALAR_COLUMNS: tuple[str, ...] = (
    "fabric_rigidity",
    "fabric_finish",
    "occasion",
    "neckline_type",
    "sleeve_type",
    "sleeve_length",
    "pattern_scale",
    "pattern_character",
    "pattern_symmetry",
    "detail_scale",
    "structure",
    "cut_lines",
    "shoulder_emphasis",
)


def upgrade() -> None:
    # 13 скалярных атрибутов (все nullable, без default — чтобы
    # существующие строки остались без значения — это честный NULL,
    # а не «silent default»).
    for column in _SCALAR_COLUMNS:
        op.add_column(
            "wardrobe_items",
            sa.Column(column, sa.String(), nullable=True),
        )

    # style_tags — массив строк (военный / денди / prep и т.д.).
    op.add_column(
        "wardrobe_items",
        sa.Column("style_tags", ARRAY(sa.String()), nullable=True),
    )


def downgrade() -> None:
    # Порядок обратный upgrade — сначала массив, потом скаляры.
    op.drop_column("wardrobe_items", "style_tags")
    for column in reversed(_SCALAR_COLUMNS):
        op.drop_column("wardrobe_items", column)
