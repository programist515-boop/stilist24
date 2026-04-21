"""Tests for beta telemetry routes and schemas (``app.api.routes.events``).

The tests validate two things:

1. :class:`TrackEventIn` and :class:`BetaFeedbackIn` accept the inputs we
   expect from the frontend and reject the inputs we don't. These are
   pure Pydantic tests — no DB, no FastAPI.
2. The route handlers call ``EventRepository.create`` with the right
   ``event_type`` and payload. We mock the repository class so the test
   does not need a live Postgres.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("pydantic")

from pydantic import ValidationError  # noqa: E402

from app.schemas.events import BetaFeedbackIn, TrackEventIn  # noqa: E402


# --------------------------------------------------------- schema tests


class TestTrackEventIn:
    def test_accepts_simple_event_type(self):
        model = TrackEventIn(event_type="page_viewed", payload={"path": "/today"})
        assert model.event_type == "page_viewed"
        assert model.payload == {"path": "/today"}

    def test_accepts_dotted_namespace(self):
        # Client may namespace funnel events — e.g. ``funnel.analyze_started``.
        model = TrackEventIn(event_type="funnel.analyze_started")
        assert model.event_type == "funnel.analyze_started"

    def test_payload_defaults_to_empty_dict(self):
        model = TrackEventIn(event_type="page_viewed")
        assert model.payload == {}

    @pytest.mark.parametrize(
        "bad",
        [
            "PageViewed",  # uppercase
            "1page",  # starts with a digit
            "page viewed",  # whitespace
            "page-viewed",  # dash
            "<script>",  # anything HTML-ish
            "",  # empty
            "a" * 65,  # too long
        ],
    )
    def test_rejects_malformed_event_type(self, bad: str):
        with pytest.raises(ValidationError):
            TrackEventIn(event_type=bad)


class TestBetaFeedbackIn:
    def test_requires_message(self):
        with pytest.raises(ValidationError):
            BetaFeedbackIn(message="")  # blank after strip

    def test_contact_and_context_are_optional(self):
        model = BetaFeedbackIn(message="нравится, но не хватает X")
        assert model.contact is None
        assert model.context == {}

    def test_trims_whitespace(self):
        model = BetaFeedbackIn(message="  привет  ", contact="  @alice  ")
        assert model.message == "привет"
        assert model.contact == "@alice"

    def test_rejects_oversized_message(self):
        with pytest.raises(ValidationError):
            BetaFeedbackIn(message="x" * 2001)


# ---------------------------------------------------------- route tests


class TestTrackRoute:
    def test_persists_event_with_expected_shape(self):
        # Route module pulls in ``sqlalchemy.orm.Session`` for dependency
        # typing. Skip cleanly when the minimal CI interpreter ships
        # without SQLAlchemy — schema tests above still run there.
        pytest.importorskip("sqlalchemy")
        from app.api.routes.events import track_event

        db = MagicMock()
        user_id = uuid.uuid4()
        payload = TrackEventIn(
            event_type="outfits_generated",
            payload={"count": 4},
        )

        with patch("app.api.routes.events.EventRepository") as MockRepo:
            result = track_event(payload=payload, db=db, user_id=user_id)

        MockRepo.assert_called_once_with(db)
        MockRepo.return_value.create.assert_called_once_with(
            user_id=user_id,
            event_type="outfits_generated",
            payload={"count": 4},
        )
        assert result == {"status": "ok"}


class TestBetaFeedbackRoute:
    def test_persists_with_beta_feedback_type_and_full_envelope(self):
        pytest.importorskip("sqlalchemy")
        from app.api.routes.events import submit_beta_feedback

        db = MagicMock()
        user_id = uuid.uuid4()
        payload = BetaFeedbackIn(
            message="не понял, как добавить юбку",
            contact="@alice",
            context={"path": "/wardrobe"},
        )

        with patch("app.api.routes.events.EventRepository") as MockRepo:
            result = submit_beta_feedback(payload=payload, db=db, user_id=user_id)

        MockRepo.assert_called_once_with(db)
        MockRepo.return_value.create.assert_called_once_with(
            user_id=user_id,
            event_type="beta_feedback",
            payload={
                "message": "не понял, как добавить юбку",
                "contact": "@alice",
                "context": {"path": "/wardrobe"},
            },
        )
        assert result == {"status": "ok"}
