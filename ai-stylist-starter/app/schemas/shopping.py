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
    """Response from ``POST /shopping/evaluate``."""

    decision: Literal["buy", "maybe", "skip"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: list[str]
    warnings: list[str]
    pairs_with_count: int
    fills_gap_ids: list[str]
    duplicate_like_item_ids: list[str]
    subscores: dict[str, SubScore]
    candidate_attributes: dict[str, Any]
    data_quality: Literal["high", "medium", "low"] = "medium"
    data_source: Literal["image", "manual", "minimal"] = "manual"
    explanation: dict[str, Any] = Field(default_factory=dict)
