"""Pydantic schemas for the shopping evaluator."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ShoppingCandidateIn(BaseModel):
    """Input for ``POST /shopping/evaluate`` (non-image path).

    Either ``price`` or ``attributes`` (or both) must be provided for a
    meaningful evaluation. The route also accepts an image upload — when an
    image is present, attributes are inferred from the image and merged with
    any manually supplied values here.
    """

    price: float | None = Field(default=None, gt=0)
    retailer: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class SubScore(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PurchaseEvalOut(BaseModel):
    """Response from ``POST /shopping/evaluate``.

    Slim UX shape:
      * ``decision``   — buy / maybe / skip
      * ``summary``    — одно короткое предложение
      * ``reasons``    — до 3 коротких причин
      * ``warnings``   — до 2 коротких предупреждений
      * ``confidence`` — 0..1
    """

    decision: Literal["buy", "maybe", "skip"]
    summary: str
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
