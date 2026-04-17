"""Gap analysis response schema for GET /wardrobe/gap-analysis."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GapSuggestion(BaseModel):
    """A suggested item that would unlock new outfit combinations."""

    model_config = ConfigDict(extra="forbid")

    suggested_item: str            # human-readable label from YAML
    category: str                  # which category the suggestion fills
    new_combinations: int          # projected new valid combos if item added
    categories_unlocked: list[str] # occasion tags this item opens up
    explanation: str               # why this item is valuable


class UntappedItem(BaseModel):
    """An existing item that rarely appears in valid outfits."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    category: str
    outfit_count: int
    reason: str    # what's keeping the item from appearing in more outfits


class GapAnalysisResponse(BaseModel):
    """Response for GET /wardrobe/gap-analysis."""

    model_config = ConfigDict(extra="forbid")

    suggestions: list[GapSuggestion]    # sorted by new_combinations desc
    untapped_items: list[UntappedItem]
    missing_categories: list[str]
    notes: list[str]


__all__ = ["GapAnalysisResponse", "GapSuggestion", "UntappedItem"]
