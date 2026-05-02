"""Preference-based identity quiz routes.

Thin HTTP layer over :mod:`app.services.preference_quiz.identity_quiz`.

Routes (all require ``X-User-Id`` / ``Authorization`` per
:func:`app.api.deps.get_current_user_id`):

* ``POST /start`` — create session, build stock cards.
* ``POST /{session_id}/vote`` — record a like/dislike vote.
* ``POST /{session_id}/wardrobe-match`` — for every liked stock look,
  return matched wardrobe items + missing slots (with shopping hints).
* ``POST /{session_id}/complete`` — finalize and write the preference
  profile (winner from the stock likes).

The earlier ``advance-to-tryon`` / ``tryon-status`` pair is gone: it
fired three FASHN try-on jobs sequentially and was both slow and
off-target. Personal try-on lives on the dedicated ``/tryon`` page.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_persona_id, get_current_user_id, get_db
from app.core.storage import fresh_public_url
from app.models.preference_quiz_session import (
    QUIZ_TYPE_IDENTITY,
    STAGE_STOCK,
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    PreferenceQuizSession,
)
from app.models.style_profile import (
    PROFILE_SOURCE_PREFERENCE,
    StyleProfile,
)
from app.repositories.wardrobe_repository import WardrobeRepository
from app.schemas.preference_quiz import (
    CandidateOut,
    IdentityLookMatchOut,
    IdentityQuizCompleteResponse,
    IdentityQuizStartResponse,
    IdentityQuizVoteIn,
    IdentityWardrobeMatchResponse,
    WardrobeMatchedItemOut,
    WardrobeMissingSlotOut,
)
from app.services.preference_quiz import identity_quiz

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
    )


# ---------------------------------------------------------------- POST /start


@router.post("/start", response_model=IdentityQuizStartResponse)
def start_identity_quiz(
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> IdentityQuizStartResponse:
    # Read algorithmic winner from StyleProfile.kibbe_type if we have one.
    from app.services.style_profile_resolver import load_style_profile

    profile = load_style_profile(user_id=user_id, db=db)
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


# ---------------------------------------------------------------- POST /wardrobe-match


@router.post(
    "/{session_id}/wardrobe-match",
    response_model=IdentityWardrobeMatchResponse,
)
def wardrobe_match(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> IdentityWardrobeMatchResponse:
    """For every liked stock look, return wardrobe match + shopping hints.

    Requires the user to have liked at least 3 distinct subtypes — same
    threshold the old ``advance-to-tryon`` enforced. Returns 422 if not
    yet (the frontend uses this to keep the «Достаточно, к примерке»
    button disabled until the threshold is met).
    """
    session = _get_session_or_404(db, session_id, user_id)

    finalists = identity_quiz.resolve_stock_stage(session)
    if not finalists:
        raise HTTPException(
            status_code=422,
            detail="need at least 3 liked subtypes before matching wardrobe",
        )

    wardrobe = WardrobeRepository(db).list_by_persona(persona_id)
    matches = identity_quiz.build_wardrobe_match(session, wardrobe)

    items_by_id: dict[str, object] = {str(item.id): item for item in wardrobe}

    looks_out: list[IdentityLookMatchOut] = []
    for subtype, match in matches:
        matched_out: list[WardrobeMatchedItemOut] = []
        for mi in match.matched_items:
            item = items_by_id.get(mi.item_id)
            image_url: str | None = None
            category: str | None = None
            if item is not None:
                image_url = fresh_public_url(
                    getattr(item, "image_key", None),
                    getattr(item, "image_url", None),
                )
                category = getattr(item, "category", None)
            matched_out.append(
                WardrobeMatchedItemOut(
                    slot=mi.slot,
                    item_id=mi.item_id,
                    image_url=image_url,
                    category=category,
                    match_quality=mi.match_quality,
                    match_reasons=list(mi.match_reasons),
                )
            )
        missing_out = [
            WardrobeMissingSlotOut(
                slot=ms.slot,
                requires=dict(ms.requires),
                shopping_hint=ms.shopping_hint,
            )
            for ms in match.missing_slots
        ]
        looks_out.append(
            IdentityLookMatchOut(
                look_id=match.look_id,
                subtype=subtype,
                title=match.title,
                image_url=match.image_url,
                occasion=match.occasion,
                matched_items=matched_out,
                missing_slots=missing_out,
                completeness=match.completeness,
                slot_order=list(match.slot_order),
            )
        )

    logger.info(
        "preference_quiz: wardrobe-match returned %d looks (user=%s, wardrobe_size=%d)",
        len(looks_out),
        user_id,
        len(wardrobe),
    )
    return IdentityWardrobeMatchResponse(
        session_id=str(session.id),
        looks=looks_out,
    )


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

    # Persist into StyleProfile — keyed by primary persona of the user
    # (PK of style_profiles is persona_id since migration 0010).
    from app.repositories.persona_repository import PersonaRepository
    from app.services.style_profile_resolver import load_style_profile

    primary = PersonaRepository(db).ensure_primary(user_id)
    profile = load_style_profile(persona_id=primary.id, db=db)
    if profile is None:
        profile = StyleProfile(persona_id=primary.id, user_id=user_id)
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
