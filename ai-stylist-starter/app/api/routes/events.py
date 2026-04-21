"""Beta telemetry routes.

* ``POST /events/track`` — record a funnel event in ``user_events``.
  Deliberately does *not* run through :class:`FeedbackService` so that a
  ``page_viewed`` does not nudge the personalization profile.
* ``POST /events/beta-feedback`` — store free-form feedback (message +
  optional contact) under ``event_type='beta_feedback'``. We read these
  by hand from the DB during the closed-beta phase.

Both endpoints rely on :func:`get_current_user_id`, which upserts a stub
user for new browser UUIDs — so a tester doesn't need to "sign up" before
their first event lands.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.repositories.event_repository import EventRepository
from app.schemas.events import BetaFeedbackIn, TrackEventIn

router = APIRouter()


@router.post("/track")
def track_event(
    payload: TrackEventIn,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    EventRepository(db).create(
        user_id=user_id,
        event_type=payload.event_type,
        payload=payload.payload,
    )
    return {"status": "ok"}


@router.post("/beta-feedback")
def submit_beta_feedback(
    payload: BetaFeedbackIn,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    EventRepository(db).create(
        user_id=user_id,
        event_type="beta_feedback",
        payload={
            "message": payload.message,
            "contact": payload.contact,
            "context": payload.context,
        },
    )
    return {"status": "ok"}
