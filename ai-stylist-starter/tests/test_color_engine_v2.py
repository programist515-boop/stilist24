"""Tests for the extended ColorEngine.analyze() output (Sprint 1).

Covers:
- top_3_seasons returned as list with season/score/explanation
- confidence is gap-based (top1 - top2), not raw score
- adjacent_seasons present and non-overlapping with top_3
- palette_hex is a flat list of hex strings
- palette contains avoid_colors and canonical_colors
- explanation strings are non-empty and include axis labels
- backward-compat fields (season_top_1, alternatives) still present
- determinism: same profile → same output
"""

import pytest
from app.services.color_engine import ColorEngine


_SOFT_SUMMER_PROFILE = {
    "undertone": "cool-neutral",
    "depth": "medium",
    "chroma": "soft",
    "contrast": "medium-low",
}

_TRUE_WINTER_PROFILE = {
    "undertone": "cool",
    "depth": "deep",
    "chroma": "clear",
    "contrast": "high",
}

_WARM_SPRING_PROFILE = {
    "undertone": "warm",
    "depth": "light",
    "chroma": "medium-bright",
    "contrast": "low",
}


@pytest.fixture
def engine():
    return ColorEngine()


def test_analyze_returns_top_3_seasons(engine):
    result = engine.analyze(_SOFT_SUMMER_PROFILE)
    top3 = result["top_3_seasons"]
    assert isinstance(top3, list)
    assert len(top3) == 3


def test_top_3_seasons_have_required_keys(engine):
    result = engine.analyze(_SOFT_SUMMER_PROFILE)
    for entry in result["top_3_seasons"]:
        assert "season" in entry
        assert "score" in entry
        assert "explanation" in entry


def test_top_3_seasons_descending_order(engine):
    result = engine.analyze(_SOFT_SUMMER_PROFILE)
    scores = [e["score"] for e in result["top_3_seasons"]]
    assert scores == sorted(scores, reverse=True)


def test_confidence_is_gap_based(engine):
    result = engine.analyze(_SOFT_SUMMER_PROFILE)
    top3 = result["top_3_seasons"]
    expected_gap = round(top3[0]["score"] - top3[1]["score"], 3)
    assert result["confidence"] == expected_gap


def test_confidence_is_non_negative(engine):
    for profile in (_SOFT_SUMMER_PROFILE, _TRUE_WINTER_PROFILE, _WARM_SPRING_PROFILE):
        result = engine.analyze(profile)
        assert result["confidence"] >= 0.0


def test_adjacent_seasons_present(engine):
    result = engine.analyze(_SOFT_SUMMER_PROFILE)
    assert "adjacent_seasons" in result
    assert isinstance(result["adjacent_seasons"], list)


def test_adjacent_seasons_not_in_top_3(engine):
    result = engine.analyze(_SOFT_SUMMER_PROFILE)
    top3_names = {e["season"] for e in result["top_3_seasons"]}
    for s in result["adjacent_seasons"]:
        assert s not in top3_names


def test_palette_hex_is_flat_list(engine):
    result = engine.analyze(_SOFT_SUMMER_PROFILE)
    palette_hex = result["palette_hex"]
    assert isinstance(palette_hex, list)
    assert len(palette_hex) > 0
    for item in palette_hex:
        assert isinstance(item, str)
        assert item.startswith("#")


def test_palette_contains_avoid_colors(engine):
    result = engine.analyze(_SOFT_SUMMER_PROFILE)
    assert "avoid_colors" in result["palette"]
    assert isinstance(result["palette"]["avoid_colors"], list)


def test_palette_contains_canonical_colors(engine):
    result = engine.analyze(_SOFT_SUMMER_PROFILE)
    assert "canonical_colors" in result["palette"]
    assert isinstance(result["palette"]["canonical_colors"], list)


def test_explanation_strings_non_empty(engine):
    result = engine.analyze(_SOFT_SUMMER_PROFILE)
    for entry in result["top_3_seasons"]:
        assert entry["explanation"]
        assert len(entry["explanation"]) > 0


def test_explanation_contains_checkmarks(engine):
    result = engine.analyze(_TRUE_WINTER_PROFILE)
    # cool+deep+clear+high matches both deep_winter and true_winter with score 1.0
    # — whichever wins, the explanation should have 4 ✓ axes
    top1 = result["top_3_seasons"][0]
    assert top1["score"] == 1.0
    assert top1["explanation"].count("✓") == 4


def test_backward_compat_season_top_1(engine):
    result = engine.analyze(_SOFT_SUMMER_PROFILE)
    assert "season_top_1" in result
    assert result["season_top_1"] == result["top_3_seasons"][0]["season"]


def test_backward_compat_alternatives(engine):
    result = engine.analyze(_SOFT_SUMMER_PROFILE)
    assert "alternatives" in result
    assert len(result["alternatives"]) == 2


def test_axes_returned(engine):
    result = engine.analyze(_SOFT_SUMMER_PROFILE)
    assert result["axes"] == _SOFT_SUMMER_PROFILE


def test_determinism(engine):
    r1 = engine.analyze(_SOFT_SUMMER_PROFILE)
    r2 = engine.analyze(_SOFT_SUMMER_PROFILE)
    assert r1["season_top_1"] == r2["season_top_1"]
    assert r1["confidence"] == r2["confidence"]
    assert r1["top_3_seasons"] == r2["top_3_seasons"]


def test_true_winter_profile_scores_well(engine):
    result = engine.analyze(_TRUE_WINTER_PROFILE)
    # cool+deep+clear+high → perfect score; deep_winter or true_winter may win (both = 1.0)
    top1 = result["top_3_seasons"][0]
    assert top1["score"] == 1.0
    assert result["season_top_1"] in ("true_winter", "deep_winter")


def test_empty_profile_does_not_crash(engine):
    result = engine.analyze({})
    assert "season_top_1" in result
    assert "top_3_seasons" in result


def test_partial_profile_does_not_crash(engine):
    result = engine.analyze({"undertone": "warm"})
    assert "season_top_1" in result
    top3 = result["top_3_seasons"]
    assert len(top3) == 3


def test_family_scores_four_seasons(engine):
    result = engine.analyze(_SOFT_SUMMER_PROFILE)
    family = result["family_scores"]
    assert set(family.keys()) == {"spring", "summer", "autumn", "winter"}
