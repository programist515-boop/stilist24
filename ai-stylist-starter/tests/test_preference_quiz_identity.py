"""Unit tests for the identity preference quiz engine.

Covers pure logic only — candidate assembly, vote resolution, winner
computation, and wardrobe matching — with lightweight in-memory
stand-ins for :class:`PreferenceQuizSession`. The route layer is not
exercised here (no DB or FastAPI is spun up).

The previous virtual-try-on stage has been removed: the quiz now has a
single stock stage and a wardrobe-match step that maps each liked look
to ``matched_items`` + ``missing_slots``.
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


def test_resolve_final_winner_from_stock_likes():
    # 4 subtypes; soft_dramatic gets 3 likes, classic 1, others 0/disliked.
    cards = [
        _stock_card("soft_dramatic", "sd"),
        _stock_card("classic", "cl"),
        _stock_card("romantic", "ro"),
        _stock_card("gamine", "ga"),
    ]
    votes = [
        _like("soft_dramatic:sd"),
        _like("soft_dramatic:sd"),
        _like("soft_dramatic:sd"),
        _like("classic:cl"),
        _dislike("romantic:ro"),
    ]
    session = _session(candidates=cards, votes=votes)

    result = identity_quiz.resolve_final_winner(session)

    assert result["winner"] == "soft_dramatic"
    # 3 of 4 stock likes went to the winner.
    assert result["confidence"] == 3 / 4
    assert [r["subtype"] for r in result["ranking"]] == ["soft_dramatic", "classic"]
    assert result["ranking"][0]["likes"] == 3
    assert result["ranking"][1]["likes"] == 1


def test_resolve_final_winner_no_votes():
    cards = [_stock_card("dramatic"), _stock_card("romantic")]
    session = _session(candidates=cards, votes=[])

    result = identity_quiz.resolve_final_winner(session)

    assert result == {"winner": None, "confidence": 0.0, "ranking": []}


def test_resolve_final_winner_ignores_dislikes_and_unknown_candidates():
    cards = [_stock_card("dramatic", "d"), _stock_card("classic", "c")]
    votes = [
        _like("dramatic:d"),
        _dislike("dramatic:d"),       # dislike — must not count
        _like("classic:c"),
        _like("ghost:gone"),          # candidate not in candidates_json — ignore
    ]
    session = _session(candidates=cards, votes=votes)

    result = identity_quiz.resolve_final_winner(session)

    # 1 like dramatic + 1 like classic = tie, dramatic comes first by insertion order.
    assert result["winner"] == "dramatic"
    assert result["confidence"] == 0.5
    assert {r["subtype"] for r in result["ranking"]} == {"dramatic", "classic"}


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


# ---------------------------------------------------------------- build_wardrobe_match


def _fake_yaml_for(subtype: str, look_id: str, items: list[dict]) -> dict:
    """Build the minimal reference_looks YAML structure used by the matcher."""
    return {
        "reference_looks": [
            {
                "id": look_id,
                "name": f"{subtype} {look_id}",
                "image_url": f"/static/{subtype}/{look_id}.jpg",
                "items": items,
            }
        ],
        "global_stop_items": [],
    }


def test_wardrobe_match_returns_one_entry_per_distinct_liked_look():
    """Two different liked looks → two match entries with the right look_ids."""
    cards = [
        _stock_card("soft_dramatic", "sd_a"),
        _stock_card("classic", "cl_b"),
        _stock_card("natural", "na_c"),
        _stock_card("romantic", "ro_d"),
    ]
    votes = [
        _like("soft_dramatic:sd_a"),
        _like("classic:cl_b"),
        _like("classic:cl_b"),  # duplicate like — must collapse to one match entry
        _dislike("natural:na_c"),
        _like("romantic:ro_d"),
    ]
    session = _session(candidates=cards, votes=votes)

    fake_data: dict[str, dict] = {
        "soft_dramatic": _fake_yaml_for(
            "soft_dramatic",
            "sd_a",
            items=[{"slot": "top", "requires": {"category": "blouse"}, "optional": False}],
        ),
        "classic": _fake_yaml_for(
            "classic",
            "cl_b",
            items=[{"slot": "blazer", "requires": {"category": "blazer"}, "optional": False}],
        ),
        "romantic": _fake_yaml_for(
            "romantic",
            "ro_d",
            items=[{"slot": "dress", "requires": {"category": "dress"}, "optional": False}],
        ),
    }

    wardrobe = [
        {"id": "w1", "category": "blouse"},
        {"id": "w2", "category": "blazer"},
        # No dress — romantic look will have a missing slot.
    ]

    with patch(
        "app.services.reference_matcher._load_reference_looks_yaml",
        side_effect=lambda subtype: fake_data.get(subtype),
    ):
        results = identity_quiz.build_wardrobe_match(session, wardrobe)

    # Order = like-order, deduped: soft_dramatic (1st like), classic (2nd), romantic (5th).
    assert [subtype for subtype, _ in results] == ["soft_dramatic", "classic", "romantic"]

    by_subtype = {s: m for s, m in results}
    assert by_subtype["soft_dramatic"].look_id == "sd_a"
    assert by_subtype["classic"].look_id == "cl_b"
    assert by_subtype["romantic"].look_id == "ro_d"


def test_wardrobe_match_skips_dislikes_and_unknown_candidates():
    cards = [_stock_card("classic", "cl"), _stock_card("dramatic", "dr")]
    votes = [
        _dislike("classic:cl"),       # dislikes never produce matches
        _like("ghost:gone"),          # candidate not in candidates_json
        _like("dramatic:dr"),
    ]
    session = _session(candidates=cards, votes=votes)

    fake_data = {
        "dramatic": _fake_yaml_for(
            "dramatic",
            "dr",
            items=[{"slot": "top", "requires": {"category": "shirt"}, "optional": False}],
        ),
    }
    with patch(
        "app.services.reference_matcher._load_reference_looks_yaml",
        side_effect=lambda subtype: fake_data.get(subtype),
    ):
        results = identity_quiz.build_wardrobe_match(
            session, [{"id": "w", "category": "shirt"}]
        )

    assert [s for s, _ in results] == ["dramatic"]


def test_wardrobe_match_completeness_and_missing_slot_shopping_hint():
    cards = [_stock_card("classic", "cl")]
    votes = [_like("classic:cl")]
    session = _session(candidates=cards, votes=votes)

    fake_data = {
        "classic": _fake_yaml_for(
            "classic",
            "cl",
            items=[
                {"slot": "blazer", "requires": {"category": "blazer"}, "optional": False},
                {"slot": "trousers", "requires": {"category": "trousers"}, "optional": False},
            ],
        ),
    }
    wardrobe = [{"id": "w-blazer", "category": "blazer"}]

    with patch(
        "app.services.reference_matcher._load_reference_looks_yaml",
        side_effect=lambda subtype: fake_data.get(subtype),
    ):
        results = identity_quiz.build_wardrobe_match(session, wardrobe)

    assert len(results) == 1
    _, match = results[0]
    # 1 of 2 required slots closed → completeness == 0.5.
    assert match.completeness == 0.5
    assert [mi.slot for mi in match.matched_items] == ["blazer"]
    assert [ms.slot for ms in match.missing_slots] == ["trousers"]
    assert match.missing_slots[0].shopping_hint, "shopping_hint must be non-empty"
    assert "trousers" in match.missing_slots[0].shopping_hint


def test_wardrobe_match_skips_look_id_not_in_yaml():
    # User somehow liked a look_id that no longer exists in the YAML —
    # the matcher must skip it without raising.
    cards = [_stock_card("classic", "ghost_look")]
    votes = [_like("classic:ghost_look")]
    session = _session(candidates=cards, votes=votes)

    fake_data = {
        "classic": _fake_yaml_for(
            "classic",
            "real_look",
            items=[{"slot": "top", "requires": {"category": "shirt"}, "optional": False}],
        ),
    }
    with patch(
        "app.services.reference_matcher._load_reference_looks_yaml",
        side_effect=lambda subtype: fake_data.get(subtype),
    ):
        results = identity_quiz.build_wardrobe_match(session, [])

    assert results == []


def test_wardrobe_match_empty_when_no_likes():
    cards = [_stock_card("classic"), _stock_card("dramatic")]
    session = _session(candidates=cards, votes=[])

    results = identity_quiz.build_wardrobe_match(session, [])

    assert results == []
