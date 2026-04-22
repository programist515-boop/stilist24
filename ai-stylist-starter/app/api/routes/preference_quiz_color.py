"""Color-preference quiz routes.

The quiz is a two-stage affair:

1. ``POST /preference-quiz/color/start``
   creates a new :class:`PreferenceQuizSession` (``quiz_type="color"``,
   ``stage="family"``), renders one drape card per season family, and
   returns them. The frontend shows the cards as a swipeable deck.
2. ``POST /preference-quiz/color/{session_id}/vote``
   records a like/dislike against one candidate. Votes are appended
   to ``votes_json`` and mirrored into the user-event stream.
3. ``POST /preference-quiz/color/{session_id}/advance-to-season``
   resolves the top-1 family from the stage-1 likes, flips the session
   to ``stage="season"``, and renders the 3 cards for the winning
   family. A 409 is returned when the user liked nothing on stage 1.
4. ``POST /preference-quiz/color/{session_id}/complete``
   reduces stage-2 votes to a winning season + confidence, writes those
   onto :class:`StyleProfile`, and flips the session to
   ``status="completed"``.

Route registration in ``app/main.py`` is intentionally owned by the
integrator — this module only exposes ``router`` so the registration
step stays explicit and greppable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.storage import StorageService, get_storage_service
from app.models.preference_quiz_session import (
    PreferenceQuizSession,
    QUIZ_TYPE_COLOR,
    STAGE_FAMILY,
    STAGE_SEASON,
    STATUS_ACTIVE,
    STATUS_COMPLETED,
)
from app.models.style_profile import (
    PROFILE_SOURCE_PREFERENCE,
    StyleProfile,
)
from app.schemas.preference_quiz_color import (
    ColorQuizAdvanceResponse,
    ColorQuizCompleteResponse,
    ColorQuizStartResponse,
    ColorQuizVoteIn,
)
from app.services.preference_quiz.color_quiz import (
    FAMILY_SEASONS,
    PortraitMissingError,
    build_family_candidates,
    build_season_candidates,
    record_vote,
    resolve_family_stage,
    resolve_final_winner,
)


router = APIRouter()


# ---------------------------------------------------------------- helpers


def _load_session(
    db: Session, session_id: uuid.UUID, user_id: uuid.UUID
) -> PreferenceQuizSession:
    """Fetch a session, enforcing ownership and quiz type.

    Ownership mismatch returns 404 (rather than 403) so the endpoint
    doesn't leak the existence of other users' sessions. Wrong quiz
    type also becomes a 404 — a caller that hits the color endpoints
    with an identity session id is, from the route's perspective,
    asking for something that does not exist.
    """
    row = db.get(PreferenceQuizSession, session_id)
    if row is None or row.user_id != user_id or row.quiz_type != QUIZ_TYPE_COLOR:
        raise HTTPException(status_code=404, detail="color quiz session not found")
    return row


def _algorithmic_family(db: Session, user_id: uuid.UUID) -> str | None:
    """Best-effort read of the algorithmic family from ``StyleProfile``.

    The quiz is usable even without a prior ``/user/analyze`` — a
    missing profile just means the family cards show in canonical
    alphabetical order instead of being re-ranked.
    """
    row = db.get(StyleProfile, user_id)
    if row is None:
        return None
    color = dict(row.color_profile_json or {})
    top_season = color.get("season_top_1")
    if not top_season:
        return None
    for family, seasons in FAMILY_SEASONS.items():
        if top_season in seasons:
            return family
    return None


def _candidate_dicts(candidates: list[dict]) -> list[dict]:
    """Subset candidate fields down to the public API shape."""
    return [
        {
            "candidate_id": c["candidate_id"],
            "family": c.get("family"),
            "season": c.get("season"),
            "hex": c["hex"],
            "image_url": c["image_url"],
            "stage": c["stage"],
        }
        for c in candidates
    ]


# ---------------------------------------------------------------- endpoints


@router.post("/start", response_model=ColorQuizStartResponse)
def start_color_quiz(
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
    storage: StorageService = Depends(get_storage_service),
) -> dict:
    session = PreferenceQuizSession(
        user_id=user_id,
        quiz_type=QUIZ_TYPE_COLOR,
        status=STATUS_ACTIVE,
        stage=STAGE_FAMILY,
        candidates_json=[],
        votes_json=[],
        result_json={},
    )
    db.add(session)
    db.flush()  # materialize session.id before we use it in the S3 key

    algo_family = _algorithmic_family(db, user_id)

    try:
        candidates = build_family_candidates(
            user_id,
            db,
            storage,
            session_id=session.id,
            algorithmic_family=algo_family,
        )
    except PortraitMissingError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    session.candidates_json = candidates
    db.commit()
    db.refresh(session)

    return {
        "session_id": str(session.id),
        "candidates": _candidate_dicts(candidates),
    }


@router.post("/{session_id}/vote")
def vote_color_quiz(
    session_id: uuid.UUID,
    body: ColorQuizVoteIn,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    session = _load_session(db, session_id, user_id)
    if session.status != STATUS_ACTIVE:
        raise HTTPException(status_code=409, detail="quiz session is not active")

    try:
        vote = record_vote(session, body.candidate_id, body.action, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.commit()
    return {"status": "ok", "vote": vote}


@router.post(
    "/{session_id}/advance-to-season", response_model=ColorQuizAdvanceResponse
)
def advance_to_season(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
    storage: StorageService = Depends(get_storage_service),
) -> dict:
    session = _load_session(db, session_id, user_id)
    if session.status != STATUS_ACTIVE:
        raise HTTPException(status_code=409, detail="quiz session is not active")
    if session.stage != STAGE_FAMILY:
        raise HTTPException(
            status_code=409,
            detail=f"expected stage={STAGE_FAMILY!r}, got {session.stage!r}",
        )

    winner_family = resolve_family_stage(session)
    if winner_family is None:
        raise HTTPException(
            status_code=409,
            detail="no family selected — like at least one family card first",
        )

    try:
        season_candidates = build_season_candidates(
            user_id,
            db,
            storage,
            session_id=session.id,
            winner_family=winner_family,
        )
    except PortraitMissingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    session.stage = STAGE_SEASON
    # Append (not replace) so stage-1 cards remain for audit.
    session.candidates_json = list(session.candidates_json or []) + season_candidates
    session.result_json = {**(session.result_json or {}), "family_winner": winner_family}

    db.commit()
    db.refresh(session)

    return {
        "session_id": str(session.id),
        "candidates": _candidate_dicts(season_candidates),
    }


@router.post("/{session_id}/complete", response_model=ColorQuizCompleteResponse)
def complete_color_quiz(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    session = _load_session(db, session_id, user_id)
    if session.status != STATUS_ACTIVE:
        raise HTTPException(status_code=409, detail="quiz session is not active")
    if session.stage != STAGE_SEASON:
        raise HTTPException(
            status_code=409,
            detail=f"expected stage={STAGE_SEASON!r}, got {session.stage!r}",
        )

    result = resolve_final_winner(session)
    winner: str | None = result["winner"]
    confidence: float = float(result["confidence"])
    family = (session.result_json or {}).get("family_winner")

    now = datetime.now(timezone.utc)

    session.status = STATUS_COMPLETED
    session.completed_at = now
    session.result_json = {
        **(session.result_json or {}),
        "winner": winner,
        "confidence": confidence,
        "ranking": result["ranking"],
    }

    # Only persist onto StyleProfile when we actually have a winner.
    if winner is not None:
        stmt = (
            pg_insert(StyleProfile)
            .values(
                user_id=user_id,
                color_season_preference=winner,
                color_preference_confidence=confidence,
                preference_completed_at=now,
                active_profile_source=PROFILE_SOURCE_PREFERENCE,
            )
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "color_season_preference": winner,
                    "color_preference_confidence": confidence,
                    "preference_completed_at": now,
                    "active_profile_source": PROFILE_SOURCE_PREFERENCE,
                },
            )
        )
        db.execute(stmt)

    db.commit()

    return {
        "winner": winner,
        "confidence": confidence,
        "ranking": result["ranking"],
        "family": family,
    }


__all__ = ["router"]
