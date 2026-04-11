from pydantic import BaseModel
from typing import Any


class OutfitGenerateIn(BaseModel):
    occasion: str | None = None
    season: str | None = None


class OutfitOut(BaseModel):
    id: str
    items: list[dict[str, Any]]
    scores: dict[str, float]
    explanation: str
