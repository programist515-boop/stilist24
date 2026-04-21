"""Versatility score schema for GET /wardrobe/{item_id}/versatility."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class VersatilityResponse(BaseModel):
    """How many valid outfit combinations an item enables."""

    model_config = ConfigDict(extra="allow")

    item_id: str
    outfit_count: int
    top_partners: list[str]       # item_ids ranked by co-occurrence count
    is_orphan: bool               # True when outfit_count < ORPHAN_THRESHOLD
    cost_per_wear: float | None   # cost / wear_count, None if no cost set
    explanation: list[str]        # short human-readable reasoning lines
    label: str = "Универсальная"         # user-facing label (see explainer.LABELS)
    status: str = "medium"               # orphan / low / medium / high


__all__ = ["VersatilityResponse"]
