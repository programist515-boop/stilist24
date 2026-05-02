"""Pydantic schemas for the preference-based identity quiz.

Phase 2 surface: request/response shapes for
``app.api.routes.preference_quiz_identity``. All models use
``extra="forbid"`` so drift between wire contract and code is caught
by Pydantic on the request side.

The previous virtual try-on stage (``advance-to-tryon`` + ``tryon-status``)
was removed in favour of a wardrobe-match flow: after the user likes
≥3 stock looks the backend matches each liked look against the user's
wardrobe and returns ``matched_items`` + ``missing_slots`` for each.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class CandidateOut(BaseModel):
    """A single card shown to the user.

    * ``subtype`` / ``season`` are nullable so this schema can be
      re-used by the color quiz in Phase 3 (where ``subtype`` is
      replaced by ``season``).
    """

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    subtype: str | None = None
    season: str | None = None
    image_url: str
    title: str
    stage: str


class IdentityQuizStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    candidates: list[CandidateOut]


class IdentityQuizVoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    action: Literal["like", "dislike"]


# ---------------------------------------------------------------- wardrobe match


class WardrobeMatchedItemOut(BaseModel):
    """One wardrobe item matched into a slot of a liked reference look."""

    model_config = ConfigDict(extra="forbid")

    slot: str
    item_id: str
    image_url: str | None = None
    category: str | None = None
    match_quality: float
    match_reasons: list[str] = []


class WardrobeMissingSlotOut(BaseModel):
    """A slot of a liked look the wardrobe can't cover yet.

    ``shopping_hint`` is a short Russian phrase ("чёрная юбка миди со
    складками") synthesised from ``requires`` — the frontend renders
    it as the "what to buy" line for this slot.
    """

    model_config = ConfigDict(extra="forbid")

    slot: str
    requires: dict[str, Any] = {}
    shopping_hint: str


class IdentityLookMatchOut(BaseModel):
    """Per-liked-look match payload returned to the frontend."""

    model_config = ConfigDict(extra="forbid")

    look_id: str
    subtype: str
    title: str
    image_url: str | None = None
    occasion: str | None = None
    matched_items: list[WardrobeMatchedItemOut]
    missing_slots: list[WardrobeMissingSlotOut]
    completeness: float
    slot_order: list[str] = []


class IdentityWardrobeMatchResponse(BaseModel):
    """Response of ``POST /preference-quiz/identity/{id}/wardrobe-match``."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    looks: list[IdentityLookMatchOut]


# ---------------------------------------------------------------- complete


class IdentityQuizCompleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    winner: str | None
    confidence: float
    ranking: list[dict[str, Any]]


__all__ = [
    "CandidateOut",
    "IdentityLookMatchOut",
    "IdentityQuizCompleteResponse",
    "IdentityQuizStartResponse",
    "IdentityQuizVoteIn",
    "IdentityWardrobeMatchResponse",
    "WardrobeMatchedItemOut",
    "WardrobeMissingSlotOut",
]
