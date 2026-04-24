"""SQLAlchemy-модель ``WardrobeItem`` (она же ``Item`` в плане).

Фаза 0 плана ``plans/2026-04-21-каталог-фич-из-отчёта-типажа.md``
добавила 14 новых nullable-атрибутов к этой таблице. Каждый из них —
``String`` + whitelist-валидатор на уровне SQLAlchemy, чтобы:

* Alembic-миграции были простыми (новое значение — правка whitelist в
  ``app.models.item_attributes``, без миграции Postgres-enum-а);
* фронту/JSON-API не требовались отдельные enum-ы;
* ``attributes_json`` (JSONB) остался местом для «широких» сырых
  полей (цвет, принт, fit), а типажные атрибуты стали structured-колонками
  для быстрой фильтрации и скоринга.

Все 14 новых колонок nullable — это принципиально. Если CV-экстрактор
не смог достать значение — должен быть честный NULL + quality downgrade,
а не fake value (см. design_philosophy в MEMORY).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, DateTime, func, Boolean, String, Float, Integer
from sqlalchemy.dialects.postgresql import ARRAY, UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.database import Base
from app.models.item_attributes import (
    ATTRIBUTE_WHITELISTS,
    validate_style_tags,
)


class WardrobeItem(Base):
    __tablename__ = "wardrobe_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    persona_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("personas.id"), nullable=False, index=True
    )
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    attributes_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    scores_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    # image_key is the canonical storage reference. image_url is kept for
    # backward compatibility and is a projection of image_key that may be
    # rebuilt at any time (e.g. presigned URL rotation).
    image_key: Mapped[str | None] = mapped_column(String, nullable=True)
    image_url: Mapped[str] = mapped_column(String, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    wear_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # ----- Фаза 0: 14 новых атрибутов (все nullable) ------------------------

    fabric_rigidity: Mapped[str | None] = mapped_column(String, nullable=True)
    fabric_finish: Mapped[str | None] = mapped_column(String, nullable=True)
    occasion: Mapped[str | None] = mapped_column(String, nullable=True)
    neckline_type: Mapped[str | None] = mapped_column(String, nullable=True)
    sleeve_type: Mapped[str | None] = mapped_column(String, nullable=True)
    sleeve_length: Mapped[str | None] = mapped_column(String, nullable=True)
    pattern_scale: Mapped[str | None] = mapped_column(String, nullable=True)
    pattern_character: Mapped[str | None] = mapped_column(String, nullable=True)
    pattern_symmetry: Mapped[str | None] = mapped_column(String, nullable=True)
    detail_scale: Mapped[str | None] = mapped_column(String, nullable=True)
    structure: Mapped[str | None] = mapped_column(String, nullable=True)
    cut_lines: Mapped[str | None] = mapped_column(String, nullable=True)
    shoulder_emphasis: Mapped[str | None] = mapped_column(String, nullable=True)
    # style_tags — единственный массив: вещь может сочетать несколько
    # стилевых тегов (например dramatic + twenties).
    style_tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # ----- Валидаторы: чужие значения → молча отбрасываем в None ------------
    # Принцип: лучше честный None, чем фейковое значение.

    @validates(
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
    def _validate_whitelisted_scalar(self, key: str, value: str | None) -> str | None:
        """Пропустить значение, если оно есть в whitelist для данного поля."""
        if value is None:
            return None
        whitelist = ATTRIBUTE_WHITELISTS.get(key)
        if whitelist is None:
            return None
        return value if value in whitelist else None

    @validates("style_tags")
    def _validate_style_tags(self, _key: str, value: list[str] | None) -> list[str] | None:
        """Отфильтровать теги по whitelist, сохранить порядок, убрать дубликаты."""
        return validate_style_tags(value)
