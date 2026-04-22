"""Pydantic schemas for the preference-based identity quiz.

Phase 2 surface: request/response shapes for
``app.api.routes.preference_quiz_identity``. All models use
``extra="forbid"`` so drift between wire contract and code is caught
by Pydantic on the request side.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class CandidateOut(BaseModel):
    """A single card shown to the user.

    * ``subtype`` / ``season`` are nullable so this schema can be
      re-used by the color quiz in Phase 3 (where ``subtype`` is
      replaced by ``season``).
    * ``tryon_job_id`` is only populated for try-on-stage cards.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    subtype: str | None = None
    season: str | None = None
    image_url: str
    title: str
    stage: str
    tryon_job_id: str | None = None


class IdentityQuizStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    candidates: list[CandidateOut]


class IdentityQuizVoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    action: Literal["like", "dislike"]


class IdentityQuizAdvanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    candidates: list[CandidateOut]
    tryon_job_ids: list[str]


class TryonJobStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str
    result_image_url: str | None = None


class IdentityQuizTryonStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobs: list[TryonJobStatus]


class IdentityQuizCompleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    winner: str | None
    confidence: float
    ranking: list[dict[str, Any]]


__all__ = [
    "CandidateOut",
    "IdentityQuizAdvanceResponse",
    "IdentityQuizCompleteResponse",
    "IdentityQuizStartResponse",
    "IdentityQuizTryonStatusResponse",
    "IdentityQuizVoteIn",
    "TryonJobStatus",
]
