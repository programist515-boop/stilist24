"""Pydantic schemas for the color-preference quiz endpoints.

Kept deliberately permissive on the server-response side: candidate
lists may contain extra diagnostic fields in the future (e.g. the
season that produced the hex), so ``ColorCandidateOut`` carries both
``family`` and ``season`` as optional. The narrow fields ``candidate_id``,
``hex``, ``image_url`` and ``stage`` are always present.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ColorCandidateOut(BaseModel):
    candidate_id: str
    family: str | None = None
    season: str | None = None
    hex: str
    image_url: str
    stage: str


class ColorQuizStartResponse(BaseModel):
    session_id: str
    candidates: list[ColorCandidateOut]


class ColorQuizVoteIn(BaseModel):
    candidate_id: str
    action: Literal["like", "dislike"]


class ColorQuizAdvanceResponse(BaseModel):
    session_id: str
    candidates: list[ColorCandidateOut]


class ColorQuizCompleteResponse(BaseModel):
    winner: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    ranking: list[dict[str, Any]] = Field(default_factory=list)
    family: str | None = None


__all__ = [
    "ColorCandidateOut",
    "ColorQuizStartResponse",
    "ColorQuizVoteIn",
    "ColorQuizAdvanceResponse",
    "ColorQuizCompleteResponse",
]
