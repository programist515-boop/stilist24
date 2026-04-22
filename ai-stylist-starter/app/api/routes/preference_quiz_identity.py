"""Preference-based identity quiz routes.

Thin HTTP layer over :mod:`app.services.preference_quiz.identity_quiz`.

To register in ``app/main.py``::

    from app.api.routes.preference_quiz_identity import router as preference_quiz_identity_router
    app.include_router(
        preference_quiz_identity_router,
        prefix="/preference-quiz/identity",
        tags=["preference-quiz"],
    )

Routes (all require ``X-User-Id`` / ``?user_id=`` per
:func:`app.api.deps.get_current_user_id`):

* ``POST /start`` — create session, build stock cards.
* ``POST /{session_id}/vote`` — record a like/dislike vote.
* ``POST /{session_id}/advance-to-tryon`` — launch try-on for the top-3 subtypes.
* ``GET  /{session_id}/tryon-status`` — poll status of the launched try-on jobs.
* ``POST /{session_id}/complete`` — finalize and write the preference profile.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.storage import fresh_public_url
from app.models.preference_quiz_session import (
    QUIZ_TYPE_IDENTITY,
    STAGE_STOCK,
    STAGE_TRYON,
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    PreferenceQuizSession,
)
from app.models.style_profile import (
    PROFILE_SOURCE_PREFERENCE,
    StyleProfile,
)
from app.models.tryon_job import TryOnJob
from app.schemas.preference_quiz import (
    CandidateOut,
    IdentityQuizAdvanceResponse,
    IdentityQuizCompleteResponse,
    IdentityQuizStartResponse,
    IdentityQuizTryonStatusResponse,
    IdentityQuizVoteIn,
    TryonJobStatus,
)
from app.services.preference_quiz import identity_quiz
from app.services.tryon_service import TryOnService

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------- helpers


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_session_or_404(
    db: Session, session_id: uuid.UUID, user_id: uuid.UUID
) -> PreferenceQuizSession:
    session = db.get(PreferenceQuizSession, session_id)
    if session is None or session.user_id != user_id:
        raise HTTPException(status_code=404, detail="preference quiz session not found")
    if session.quiz_type != QUIZ_TYPE_IDENTITY:
        raise HTTPException(status_code=400, detail="session is not an identity quiz")
    return session


def _candidate_to_out(candidate: dict) -> CandidateOut:
    return CandidateOut(
        candidate_id=str(candidate.get("candidate_id", "")),
        subtype=candidate.get("subtype"),
        season=candidate.get("season"),
        image_url=str(candidate.get("image_url") or ""),
        title=str(candidate.get("title") or candidate.get("subtype") or ""),
        stage=str(candidate.get("stage") or STAGE_STOCK),
        tryon_job_id=candidate.get("tryon_job_id"),
    )


# ---------------------------------------------------------------- POST /start


@router.post("/start", response_model=IdentityQuizStartResponse)
def start_identity_quiz(
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> IdentityQuizStartResponse:
    # Read algorithmic winner from StyleProfile.kibbe_type if we have one.
    profile = db.get(StyleProfile, user_id)
    algorithmic_subtype = profile.kibbe_type if profile is not None else None

    candidates = identity_quiz.build_stock_candidates(
        user_id=user_id, db=db, algorithmic_subtype=algorithmic_subtype
    )
    if not candidates:
        # No reference_looks YAMLs at all — can't run the quiz.
        raise HTTPException(
            status_code=503,
            detail="no reference looks are configured; identity quiz is unavailable",
        )

    session = PreferenceQuizSession(
        user_id=user_id,
        quiz_type=QUIZ_TYPE_IDENTITY,
        status=STATUS_ACTIVE,
        stage=STAGE_STOCK,
        candidates_json=candidates,
        votes_json=[],
        result_json={},
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    logger.info(
        "preference_quiz: started identity quiz session=%s for user=%s (%d candidates)",
        session.id,
        user_id,
        len(candidates),
    )
    return IdentityQuizStartResponse(
        session_id=str(session.id),
        candidates=[_candidate_to_out(c) for c in candidates],
    )


# ---------------------------------------------------------------- POST /vote


@router.post("/{session_id}/vote")
def vote_on_candidate(
    session_id: uuid.UUID,
    payload: IdentityQuizVoteIn,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    session = _get_session_or_404(db, session_id, user_id)
    try:
        identity_quiz.record_vote(
            session=session,
            candidate_id=payload.candidate_id,
            action=payload.action,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.add(session)
    db.commit()
    return {"status": "ok", "votes_recorded": len(session.votes_json or [])}


# ---------------------------------------------------------------- POST /advance-to-tryon


@router.post(
    "/{session_id}/advance-to-tryon",
    response_model=IdentityQuizAdvanceResponse,
)
async def advance_to_tryon(
    session_id: uuid.UUID,
    user_photo_id: uuid.UUID = Query(
        ..., description="UserPhoto.id of the user's full-figure photo"
    ),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> IdentityQuizAdvanceResponse:
    session = _get_session_or_404(db, session_id, user_id)

    finalists = identity_quiz.resolve_stock_stage(session)
    if not finalists:
        raise HTTPException(
            status_code=409,
            detail="need at least 3 liked subtypes before advancing to try-on",
        )

    session.stage = STAGE_TRYON
    tryon_service = TryOnService(db)
    try:
        new_cards = await identity_quiz.build_tryon_finalists(
            session=session,
            user_figure_photo_id=user_photo_id,
            tryon_service=tryon_service,
            db=db,
        )
    except Exception as exc:
        logger.exception(
            "preference_quiz: advance_to_tryon failed for session=%s", session_id
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not new_cards:
        raise HTTPException(
            status_code=422,
            detail="could not launch try-on for any finalist (missing wardrobe items)",
        )

    db.add(session)
    db.commit()
    db.refresh(session)

    return IdentityQuizAdvanceResponse(
        session_id=str(session.id),
        candidates=[_candidate_to_out(c) for c in new_cards],
        tryon_job_ids=[str(c.get("tryon_job_id")) for c in new_cards if c.get("tryon_job_id")],
    )


# ---------------------------------------------------------------- GET /tryon-status


@router.get(
    "/{session_id}/tryon-status",
    response_model=IdentityQuizTryonStatusResponse,
)
def get_tryon_status(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> IdentityQuizTryonStatusResponse:
    session = _get_session_or_404(db, session_id, user_id)
    jobs: list[TryonJobStatus] = []
    for candidate in session.candidates_json or []:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("stage") != STAGE_TRYON:
            continue
        raw_job_id = candidate.get("tryon_job_id")
        if not raw_job_id:
            continue
        try:
            job_uuid = uuid.UUID(str(raw_job_id))
        except (ValueError, TypeError):
            continue
        job = db.get(TryOnJob, job_uuid)
        if job is None or job.user_id != user_id:
            continue
        jobs.append(
            TryonJobStatus(
                job_id=str(job.id),
                status=job.status,
                result_image_url=fresh_public_url(
                    job.result_image_key, job.result_image_url
                ),
            )
        )
    return IdentityQuizTryonStatusResponse(jobs=jobs)


# ---------------------------------------------------------------- POST /complete


@router.post(
    "/{session_id}/complete",
    response_model=IdentityQuizCompleteResponse,
)
def complete_identity_quiz(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> IdentityQuizCompleteResponse:
    session = _get_session_or_404(db, session_id, user_id)

    result = identity_quiz.resolve_final_winner(session)
    winner = result.get("winner")
    confidence = float(result.get("confidence") or 0.0)

    # Persist into StyleProfile.
    profile = db.get(StyleProfile, user_id)
    if profile is None:
        profile = StyleProfile(user_id=user_id)
        db.add(profile)
    if winner is not None:
        profile.kibbe_type_preference = winner
        profile.kibbe_preference_confidence = confidence
        profile.preference_completed_at = _now()
        profile.active_profile_source = PROFILE_SOURCE_PREFERENCE

    session.status = STATUS_COMPLETED
    session.completed_at = _now()
    session.result_json = result

    db.add(session)
    db.add(profile)
    db.commit()

    logger.info(
        "preference_quiz: identity quiz completed session=%s user=%s winner=%s confidence=%.3f",
        session_id,
        user_id,
        winner,
        confidence,
    )
    return IdentityQuizCompleteResponse(
        winner=winner,
        confidence=confidence,
        ranking=list(result.get("ranking") or []),
    )


__all__ = ["router"]
