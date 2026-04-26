"""Gap analysis response schema for GET /wardrobe/gap-analysis."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GapSuggestion(BaseModel):
    """A suggested item that would unlock new outfit combinations.

    Slim UX shape:
      * ``item``   — короткое название вещи
      * ``why``    — одно короткое предложение, зачем она нужна
      * ``action`` — предлагаемое действие (кнопка)
    ``category`` сохранён для фронтенда (фильтры / иконки).

    Reference-look suggestions (Phase 7 integration) дополнительно несут
    ``from_reference_look`` (id референсного лука, под который не нашлось
    вещи в гардеробе) и ``slot_hint`` (имя слота — top/bottom/shoes/...).
    Оба поля опциональные — обычные suggestions их не выставляют.
    """

    model_config = ConfigDict(extra="forbid")

    item: str
    category: str
    why: str
    action: str = "Попробовать добавить"
    from_reference_look: str | None = None
    slot_hint: str | None = None


class UntappedItem(BaseModel):
    """An existing item that rarely appears in valid outfits."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    category: str
    outfit_count: int
    reason: str    # короткое объяснение, почему вещь редко попадает в образы


class GapAnalysisResponse(BaseModel):
    """Response for GET /wardrobe/gap-analysis."""

    model_config = ConfigDict(extra="forbid")

    suggestions: list[GapSuggestion]    # ranked by projected unlock, highest first
    untapped_items: list[UntappedItem]
    missing_categories: list[str]
    notes: list[str]


__all__ = ["GapAnalysisResponse", "GapSuggestion", "UntappedItem"]
