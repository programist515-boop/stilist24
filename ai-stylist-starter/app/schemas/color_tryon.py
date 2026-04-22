"""Pydantic-схемы для color try-on (примерка вещи в цветах палитры).

Контракт API умышленно простой: один вариант = (hex, человекочитаемое
имя, ссылка на сгенерированное изображение). Фронт рисует галерею и
отправляет feedback по клику.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class ColorTryOnVariant(BaseModel):
    """Одна «примеренная» версия вещи в цвете палитры."""

    color_hex: str = Field(
        ...,
        description="HEX цвета из палитры пользователя (например, '#E8735A').",
    )
    color_name: str = Field(
        ...,
        description=(
            "Человекочитаемое имя цвета (терракотовый / мята / пудровый голубой). "
            "Когда точного имени нет — возвращается HEX."
        ),
    )
    image_url: str = Field(
        ...,
        description="Публичный URL сгенерированного превью (S3/MinIO).",
    )


class ColorTryOnResponse(BaseModel):
    """Ответ роута color-tryon: все сгенерированные варианты + качество."""

    item_id: uuid.UUID
    variants: list[ColorTryOnVariant] = Field(default_factory=list)
    # Честный quality-флаг по принципу проекта: чем больше ограничений
    # (нет палитры / мок-рендер / fallback на ML), тем ниже качество.
    # Допустимые значения: high / medium / low.
    quality: str = "high"


class ColorTryOnFeedback(BaseModel):
    """Feedback от пользователя по конкретному варианту."""

    variant_hex: str = Field(
        ...,
        description="HEX варианта, по которому пользователь кликнул лайк/дизлайк.",
    )
    liked: bool = Field(
        ...,
        description="True — понравился, False — не понравился.",
    )


__all__ = [
    "ColorTryOnFeedback",
    "ColorTryOnResponse",
    "ColorTryOnVariant",
]
