"""personas: multi-persona per account (фаза auth/profiles)

Введение сущности ``Persona`` — лицо/человек внутри одного аккаунта.
Каждый существующий ``User`` получает ровно одну ``is_primary=True``
персону. Все производные данные (фото анализа, гардероб, style_profile,
user_profile) получают NOT NULL FK на соответствующую primary-персону.

Шаги миграции (все в одной транзакции):

1. CREATE TABLE personas + индекс по user_id + partial unique index,
   гарантирующий ровно одну primary-персону на юзера.
2. Backfill: INSERT INTO personas (id, user_id, name='Я', is_primary=true)
   по каждой строке users — так, чтобы FK-колонки из шага 3 могли быть
   сразу NOT NULL.
3. ADD COLUMN persona_id (nullable) в user_photos, wardrobe_items,
   style_profiles, user_profiles.
4. UPDATE: persona_id = primary-персона своего user_id.
5. SET NOT NULL + ADD FK + INDEX.
6. Для style_profiles и user_profiles: PK переезжает с user_id на
   persona_id (убираем старый PK, добавляем новый). user_id остаётся
   NOT NULL индексированной колонкой для обратной совместимости.

Revision ID: 0010_personas
Revises: 0009_wardrobe_item_14_attributes
Create Date: 2026-04-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_personas"
down_revision = "0009_wardrobe_item_14_attributes"
branch_labels = None
depends_on = None


# Таблицы, которые получают persona_id FK. PK-change применяется только
# к двум из них (style_profiles, user_profiles) — у остальных был свой
# ``id`` PK.
_LINKED_TABLES: tuple[str, ...] = (
    "user_photos",
    "wardrobe_items",
    "style_profiles",
    "user_profiles",
)


def upgrade() -> None:
    # ---- 1. CREATE TABLE personas --------------------------------------
    op.create_table(
        "personas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personas_user_id", "personas", ["user_id"])
    # Partial unique index: ровно одна primary-персона на юзера.
    op.execute(
        "CREATE UNIQUE INDEX ux_personas_user_primary "
        "ON personas (user_id) WHERE is_primary"
    )

    # ---- 2. Backfill: primary Persona для каждого User -----------------
    op.execute(
        """
        INSERT INTO personas (id, user_id, name, is_primary, created_at)
        SELECT gen_random_uuid(), u.id, 'Я', TRUE, NOW()
        FROM users u
        """
    )

    # ---- 3. ADD COLUMN persona_id (nullable) + backfill + NOT NULL ----
    for table in _LINKED_TABLES:
        op.add_column(
            table,
            sa.Column(
                "persona_id", postgresql.UUID(as_uuid=True), nullable=True
            ),
        )
        op.execute(
            f"""
            UPDATE {table} t
            SET persona_id = p.id
            FROM personas p
            WHERE p.user_id = t.user_id AND p.is_primary
            """
        )
        op.alter_column(table, "persona_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_persona_id",
            table,
            "personas",
            ["persona_id"],
            ["id"],
        )
        op.create_index(f"ix_{table}_persona_id", table, ["persona_id"])

    # ---- 4. PK перенос для style_profiles и user_profiles --------------
    # Был PK(user_id) → становится PK(persona_id). user_id остаётся
    # индексированной NOT NULL-колонкой.
    for table in ("style_profiles", "user_profiles"):
        op.drop_constraint(f"{table}_pkey", table, type_="primary")
        op.create_primary_key(f"{table}_pkey", table, ["persona_id"])
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])


def downgrade() -> None:
    # Снять PK(persona_id), вернуть PK(user_id) для обратной совместимости.
    for table in ("user_profiles", "style_profiles"):
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        op.drop_constraint(f"{table}_pkey", table, type_="primary")
        op.create_primary_key(f"{table}_pkey", table, ["user_id"])

    # Снять persona_id + FK + индексы на связанных таблицах.
    for table in _LINKED_TABLES:
        op.drop_index(f"ix_{table}_persona_id", table_name=table)
        op.drop_constraint(f"fk_{table}_persona_id", table, type_="foreignkey")
        op.drop_column(table, "persona_id")

    op.execute("DROP INDEX IF EXISTS ux_personas_user_primary")
    op.drop_index("ix_personas_user_id", table_name="personas")
    op.drop_table("personas")
