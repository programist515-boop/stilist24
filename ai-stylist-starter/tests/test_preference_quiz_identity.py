"""Unit tests for the identity preference quiz engine.

Covers pure logic only — candidate assembly, vote resolution, winner
computation — with lightweight in-memory stand-ins for
:class:`PreferenceQuizSession`. The route layer is not exercised here
(no DB or FastAPI is spun up).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.services.preference_quiz import identity_quiz


# ---------------------------------------------------------------- helpers


def _session(candidates=None, votes=None, stage=identity_quiz.STAGE_STOCK):
    """Build a stand-in for a PreferenceQuizSession row.

    We use SimpleNamespace so test code can reassign
    ``candidates_json``/``votes_json`` the same way the real ORM row
    allows (both live on the session object).
    """
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        stage=stage,
        candidates_json=list(candidates or []),
        votes_json=list(votes or []),
        result_json={},
    )


def _stock_card(subtype: str, look_id: str = "look_1") -> dict:
    return {
        "candidate_id": f"{subtype}:{look_id}",
        "subtype": subtype,
        "look_id": look_id,
        "image_url": f"/static/{subtype}.jpg",
        "title": subtype,
        "stage": identity_quiz.STAGE_STOCK,
    }


def _tryon_card(subtype: str, job_id: str = "job-1") -> dict:
    return {
        "candidate_id": f"{subtype}:tryon:{job_id}",
        "subtype": subtype,
        "tryon_job_id": job_id,
        "stage": identity_quiz.STAGE_TRYON,
    }


def _like(candidate_id: str) -> dict:
    return {"candidate_id": candidate_id, "action": identity_quiz.ACTION_LIKE, "at": "t"}


def _dislike(candidate_id: str) -> dict:
    return {"candidate_id": candidate_id, "action": identity_quiz.ACTION_DISLIKE, "at": "t"}


# ---------------------------------------------------------------- resolve_stock_stage


def test_resolve_stock_stage_clear_top_3():
    # 5 subtypes, three clear leaders by like count, two laggards.
    cards = [
        _stock_card("dramatic", "l1"),
        _stock_card("romantic", "l2"),
        _stock_card("natural", "l3"),
        _stock_card("classic", "l4"),
        _stock_card("gamine", "l5"),
    ]
    votes = [
        # dramatic: 3 likes
        _like("dramatic:l1"), _like("dramatic:l1"), _like("dramatic:l1"),
        # romantic: 2 likes
        _like("romantic:l2"), _like("romantic:l2"),
        # natural: 2 likes
        _like("natural:l3"), _like("natural:l3"),
        # classic: 1 like
        _like("classic:l4"),
        # gamine: 0 likes, 1 dislike
        _dislike("gamine:l5"),
    ]
    session = _session(candidates=cards, votes=votes)

    top3 = identity_quiz.resolve_stock_stage(session)

    assert top3[0] == "dramatic"  # 3 likes → clear winner
    assert set(top3) == {"dramatic", "romantic", "natural"}
    assert len(top3) == 3


def test_resolve_stock_stage_not_enough_likes():
    cards = [
        _stock_card("dramatic"),
        _stock_card("romantic"),
        _stock_card("natural"),
    ]
    # Only two distinct subtypes liked — under the 3-finalist threshold.
    votes = [
        _like("dramatic:look_1"),
        _like("romantic:look_1"),
        _dislike("natural:look_1"),
    ]
    session = _session(candidates=cards, votes=votes)

    result = identity_quiz.resolve_stock_stage(session)

    assert result == []


# ---------------------------------------------------------------- resolve_final_winner


def test_resolve_final_winner():
    # 3 try-on finalists; dramatic gets 3 likes, romantic 2, natural 0.
    cards = [
        _tryon_card("dramatic", "job-a"),
        _tryon_card("romantic", "job-b"),
        _tryon_card("natural", "job-c"),
    ]
    votes = [
        _like("dramatic:tryon:job-a"),
        _like("dramatic:tryon:job-a"),
        _like("dramatic:tryon:job-a"),
        _like("romantic:tryon:job-b"),
        _like("romantic:tryon:job-b"),
        _dislike("natural:tryon:job-c"),
    ]
    session = _session(candidates=cards, votes=votes)

    result = identity_quiz.resolve_final_winner(session)

    assert result["winner"] == "dramatic"
    # 3 of 5 total likes went to the winner.
    assert result["confidence"] == 3 / 5
    assert [r["subtype"] for r in result["ranking"]] == ["dramatic", "romantic"]
    assert result["ranking"][0]["likes"] == 3
    assert result["ranking"][1]["likes"] == 2


def test_resolve_final_winner_no_votes():
    cards = [_tryon_card("dramatic"), _tryon_card("romantic")]
    session = _session(candidates=cards, votes=[])

    result = identity_quiz.resolve_final_winner(session)

    assert result == {"winner": None, "confidence": 0.0, "ranking": []}


# ---------------------------------------------------------------- build_stock_candidates


def test_build_stock_candidates_algorithmic_first():
    # Fake the YAML loaders so the test doesn't depend on the on-disk
    # set of reference_looks files.
    profiles = {
        "dramatic": {"display_name_ru": "Драматик", "family": "dramatic"},
        "romantic": {"display_name_ru": "Романтик", "family": "romantic"},
        "natural": {"display_name_ru": "Натурал", "family": "natural"},
    }

    def fake_looks(subtype: str):
        # Every subtype has exactly one look.
        return [
            {
                "id": f"{subtype}_L1",
                "name": f"{subtype} look",
                "image_url": f"/static/{subtype}.jpg",
            }
        ]

    with patch.object(
        identity_quiz, "_load_subtype_profiles", return_value=profiles
    ), patch.object(
        identity_quiz, "_load_reference_looks_for_subtype", side_effect=fake_looks
    ):
        cards = identity_quiz.build_stock_candidates(
            user_id=uuid.uuid4(), db=None, algorithmic_subtype="romantic"
        )

    assert [c["subtype"] for c in cards] == ["romantic", "dramatic", "natural"]
    assert cards[0]["candidate_id"].startswith("romantic:")
    # Each card carries the look_id we supplied.
    assert cards[0]["look_id"] == "romantic_L1"
    assert cards[0]["stage"] == identity_quiz.STAGE_STOCK
    assert cards[0]["title"] == "romantic look"
