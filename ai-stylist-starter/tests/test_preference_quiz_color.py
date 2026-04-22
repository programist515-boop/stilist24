"""Unit tests for the preference-based color quiz.

These tests only exercise the pure pieces of the feature: the drapery
renderer (pure Pillow, no I/O beyond an in-memory JPEG encode) and the
two reducers over stored votes. The S3 upload path and route handlers
are not exercised here — they sit behind the ``StorageBackend`` protocol
and FastAPI DI, and are covered by integration tests elsewhere.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from typing import Any

from PIL import Image

from app.models.preference_quiz_session import (
    STAGE_FAMILY,
    STAGE_SEASON,
)
from app.services.preference_quiz.color_quiz import (
    record_vote,
    resolve_family_stage,
    resolve_final_winner,
)
from app.services.preference_quiz.drapery_renderer import render_drapery


# ---------------------------------------------------------------- helpers


def _make_portrait_bytes(
    width: int = 200, height: int = 200, color: tuple[int, int, int] = (128, 128, 128)
) -> bytes:
    """Return a minimal in-memory PNG portrait for the renderer to chew on."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@dataclass
class _FakeSession:
    """Stand-in for :class:`PreferenceQuizSession` in reducer tests.

    Only the fields that the reducers read are modelled; the ORM bits
    (id, foreign keys, …) are irrelevant at this layer.
    """

    user_id: uuid.UUID
    candidates_json: list[dict]
    votes_json: list[dict]


class _StubFeedbackService:
    """Captures ``process`` calls without touching the DB."""

    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, str, dict]] = []

    def process(self, user_id: uuid.UUID, event_type: str, payload: dict) -> dict:
        self.calls.append((user_id, event_type, payload))
        return {}


# ---------------------------------------------------------------- renderer


def test_render_drapery_produces_jpeg() -> None:
    portrait = _make_portrait_bytes(color=(200, 200, 200))
    target_hex = "#FF0000"

    out = render_drapery(portrait, target_hex)

    # Non-empty bytes…
    assert isinstance(out, bytes)
    assert len(out) > 0

    # …that decode as a JPEG image.
    with Image.open(io.BytesIO(out)) as decoded:
        decoded.load()
        assert decoded.format == "JPEG"
        assert decoded.mode == "RGB"
        w, h = decoded.size
        # The renderer normalizes to a 600x900 canvas.
        assert (w, h) == (600, 900)

        # The lower quarter of the image is inside the drape band — sample
        # a pixel well below the feather ramp and near the horizontal
        # center. It should read as the requested red swatch.
        sample = decoded.getpixel((w // 2, h - 30))
        # JPEG encoding introduces minor chroma shift; tolerate a wide
        # band around the target but still require that red dominates.
        r, g, b = sample
        assert r > 200, f"expected red-dominant pixel, got {sample}"
        assert g < 60, f"expected low green, got {sample}"
        assert b < 60, f"expected low blue, got {sample}"


def test_render_drapery_accepts_rgba_input() -> None:
    # Build an RGBA portrait with a transparent region — the renderer
    # must flatten it without blowing up or leaking alpha into the JPEG.
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    out = render_drapery(buf.getvalue(), "#00FF00")
    with Image.open(io.BytesIO(out)) as decoded:
        decoded.load()
        assert decoded.mode == "RGB"


# ---------------------------------------------------------------- reducers


def _vote(
    *,
    stage: str,
    action: str,
    family: str | None = None,
    season: str | None = None,
    candidate_id: str | None = None,
    hex_color: str = "#000000",
) -> dict:
    return {
        "candidate_id": candidate_id or str(uuid.uuid4()),
        "action": action,
        "family": family,
        "season": season,
        "hex": hex_color,
        "stage": stage,
    }


def test_resolve_family_stage_clear_winner() -> None:
    session = _FakeSession(
        user_id=uuid.uuid4(),
        candidates_json=[],
        votes_json=[
            _vote(stage=STAGE_FAMILY, action="like", family="spring"),
            _vote(stage=STAGE_FAMILY, action="like", family="spring"),
            _vote(stage=STAGE_FAMILY, action="dislike", family="winter"),
            _vote(stage=STAGE_FAMILY, action="like", family="summer"),
            # A stage-2 vote must be ignored by the family reducer.
            _vote(stage=STAGE_SEASON, action="like", season="true_autumn"),
        ],
    )

    assert resolve_family_stage(session) == "spring"


def test_resolve_family_stage_no_votes() -> None:
    session = _FakeSession(
        user_id=uuid.uuid4(),
        candidates_json=[],
        votes_json=[
            _vote(stage=STAGE_FAMILY, action="dislike", family="spring"),
            _vote(stage=STAGE_FAMILY, action="dislike", family="summer"),
        ],
    )

    assert resolve_family_stage(session) is None


def test_resolve_final_winner_with_ranking() -> None:
    session = _FakeSession(
        user_id=uuid.uuid4(),
        candidates_json=[],
        votes_json=[
            _vote(stage=STAGE_SEASON, action="like", season="true_spring"),
            _vote(stage=STAGE_SEASON, action="like", season="true_spring"),
            _vote(stage=STAGE_SEASON, action="like", season="light_spring"),
            _vote(stage=STAGE_SEASON, action="dislike", season="bright_spring"),
            # A stage-1 vote must not leak into the final ranking.
            _vote(stage=STAGE_FAMILY, action="like", family="spring"),
        ],
    )

    result = resolve_final_winner(session)
    assert result["winner"] == "true_spring"
    # 2 likes out of 3 total stage-2 likes → 0.667.
    assert result["confidence"] == 0.667

    ranked_seasons = [row["season"] for row in result["ranking"]]
    assert ranked_seasons[0] == "true_spring"
    assert "light_spring" in ranked_seasons
    # bright_spring was only disliked — still surfaces in the ranking.
    assert "bright_spring" in ranked_seasons


def test_record_vote_appends_to_votes_json(monkeypatch) -> None:
    user_id = uuid.uuid4()
    candidate_id = str(uuid.uuid4())
    session = _FakeSession(
        user_id=user_id,
        candidates_json=[
            {
                "candidate_id": candidate_id,
                "family": "summer",
                "season": "true_summer",
                "hex": "#6495ED",
                "image_url": "memory://ai-stylist/whatever.jpg",
                "stage": STAGE_FAMILY,
            }
        ],
        votes_json=[],
    )

    stub = _StubFeedbackService()

    # ``record_vote`` instantiates FeedbackService(db) — swap the class
    # symbol it imported for our stub so nothing touches the DB.
    from app.services.preference_quiz import color_quiz as module

    monkeypatch.setattr(module, "FeedbackService", lambda db: stub)

    recorded = module.record_vote(session, candidate_id, "like", db=None)

    # The vote is persisted on the session …
    assert len(session.votes_json) == 1
    stored = session.votes_json[0]
    assert stored["candidate_id"] == candidate_id
    assert stored["action"] == "like"
    assert stored["family"] == "summer"
    assert stored["season"] == "true_summer"
    assert stored["stage"] == STAGE_FAMILY

    # … the return value mirrors the stored row …
    assert recorded == stored

    # … and the feedback stream got a matching event with a structured payload.
    assert len(stub.calls) == 1
    call_user_id, event_type, payload = stub.calls[0]
    assert call_user_id == user_id
    assert event_type == "color_preference_liked"
    assert payload == {
        "family": "summer",
        "season": "true_summer",
        "hex": "#6495ED",
        "stage": STAGE_FAMILY,
    }
