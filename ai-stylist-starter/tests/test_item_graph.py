"""Tests for ItemCompatibilityGraph and compatibility_score (Sprint 2)."""

from __future__ import annotations

import pytest

from app.services.analytics.item_graph import (
    ItemCompatibilityGraph,
    compatibility_score,
    _season_overlap,
    _formality_gap,
)


def _item(id: str, category: str, **attrs) -> dict:
    return {"id": id, "category": category, "attributes": attrs}


# ---------------------------------------------------------------------------
# _season_overlap
# ---------------------------------------------------------------------------

class TestSeasonOverlap:
    def test_same_season(self):
        assert _season_overlap("summer", "summer") is True

    def test_spring_and_spring_summer(self):
        assert _season_overlap("spring", "spring_summer") is True

    def test_spring_and_autumn_overlap_via_all_season(self):
        # Both expansions include "all_season" so overlap is truthy
        assert _season_overlap("spring", "autumn") is True

    def test_all_season_always_overlaps(self):
        assert _season_overlap("all_season", "winter") is True
        assert _season_overlap("summer", "all_season") is True

    def test_none_values_compatible(self):
        assert _season_overlap(None, "summer") is True
        assert _season_overlap(None, None) is True


# ---------------------------------------------------------------------------
# _formality_gap
# ---------------------------------------------------------------------------

class TestFormalityGap:
    def test_same_occasion(self):
        assert _formality_gap("casual", "casual") == 0

    def test_sport_vs_formal(self):
        assert _formality_gap("sport", "formal") == 5

    def test_casual_vs_smart_casual(self):
        assert _formality_gap("casual", "smart_casual") == 1

    def test_unknown_occasion_treated_as_rank_2(self):
        gap = _formality_gap("unknown_occ", "sport")
        assert gap == 2

    def test_none_returns_zero(self):
        assert _formality_gap(None, "formal") == 0


# ---------------------------------------------------------------------------
# compatibility_score — category pairs
# ---------------------------------------------------------------------------

class TestCompatibilityScoreCategories:
    def test_tops_bottoms_synergy(self):
        a = _item("1", "tops")
        b = _item("2", "bottoms")
        result = compatibility_score(a, b)
        assert result["score"] > 0.5
        assert any("natural outfit pair" in r for r in result["reasons"])

    def test_tops_dresses_incompatible(self):
        a = _item("1", "tops")
        b = _item("2", "dresses")
        result = compatibility_score(a, b)
        assert result["score"] == 0.0
        assert any("incompatible" in r for r in result["reasons"])

    def test_bottoms_dresses_incompatible(self):
        a = _item("1", "bottoms")
        b = _item("2", "dresses")
        result = compatibility_score(a, b)
        assert result["score"] == 0.0

    def test_dresses_shoes_synergy(self):
        a = _item("1", "dresses")
        b = _item("2", "shoes")
        result = compatibility_score(a, b)
        assert result["score"] > 0.5

    def test_tops_outerwear_synergy(self):
        a = _item("1", "tops")
        b = _item("2", "outerwear")
        result = compatibility_score(a, b)
        assert result["score"] > 0.5


# ---------------------------------------------------------------------------
# compatibility_score — season mismatch
# ---------------------------------------------------------------------------

class TestCompatibilityScoreSeasons:
    def test_unknown_season_vs_known_no_mismatch_warning(self):
        # known season expansions all include "all_season" so no mismatch fires
        a = _item("1", "tops", seasonality="summer")
        b = _item("2", "bottoms", seasonality="winter")
        result = compatibility_score(a, b)
        assert not any("season mismatch" in w for w in result["warnings"])

    def test_compatible_seasons_no_warning(self):
        a = _item("1", "tops", seasonality="summer")
        b = _item("2", "bottoms", seasonality="spring_summer")
        result = compatibility_score(a, b)
        assert not any("season" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# compatibility_score — formality
# ---------------------------------------------------------------------------

class TestCompatibilityScoreFormality:
    def test_large_formality_gap_penalised(self):
        a = _item("1", "tops", occasion="sport")
        b = _item("2", "bottoms", occasion="formal")
        result = compatibility_score(a, b)
        assert result["score"] < 0.5
        assert any("formality clash" in w for w in result["warnings"])

    def test_matching_occasion_no_warning(self):
        a = _item("1", "tops", occasion="casual")
        b = _item("2", "bottoms", occasion="casual")
        result = compatibility_score(a, b)
        assert not any("formality" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# compatibility_score — color harmony
# ---------------------------------------------------------------------------

class TestCompatibilityScoreColorHarmony:
    def test_both_neutrals_bonus(self):
        a = _item("1", "tops", primary_color="white")
        b = _item("2", "bottoms", primary_color="black")
        result = compatibility_score(a, b)
        assert result["score"] > 0.5

    def test_warm_cool_clash_penalty(self):
        a = _item("1", "tops", primary_color="red")
        b = _item("2", "bottoms", primary_color="blue")
        result = compatibility_score(a, b)
        assert any("clash" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# compatibility_score — silhouette
# ---------------------------------------------------------------------------

class TestCompatibilityScoreSilhouette:
    def test_two_oversized_penalised(self):
        a = _item("1", "tops", fit="oversized")
        b = _item("2", "bottoms", fit="oversized")
        result = compatibility_score(a, b)
        assert any("oversized" in w for w in result["warnings"])

    def test_one_oversized_not_penalised(self):
        a = _item("1", "tops", fit="oversized")
        b = _item("2", "bottoms", fit="slim")
        result = compatibility_score(a, b)
        assert not any("oversized" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# compatibility_score — v2 attribute format
# ---------------------------------------------------------------------------

class TestCompatibilityScoreV2Attrs:
    def test_v2_nested_attrs_extracted(self):
        a = {
            "id": "1",
            "category": "tops",
            "attributes": {
                "primary_color": {"value": "white", "confidence": 0.9, "source": "cv", "editable": True},
                "seasonality": {"value": "summer", "confidence": 0.8, "source": "cv", "editable": True},
            },
        }
        b = {
            "id": "2",
            "category": "bottoms",
            "attributes": {
                "primary_color": {"value": "navy", "confidence": 0.9, "source": "cv", "editable": True},
                "seasonality": {"value": "all_season", "confidence": 0.8, "source": "cv", "editable": True},
            },
        }
        result = compatibility_score(a, b)
        assert result["score"] > 0.0


# ---------------------------------------------------------------------------
# ItemCompatibilityGraph
# ---------------------------------------------------------------------------

class TestItemCompatibilityGraph:
    def _wardrobe(self):
        return [
            _item("top1", "tops", primary_color="white"),
            _item("bot1", "bottoms", primary_color="black"),
            _item("shoe1", "shoes"),
            _item("dress1", "dresses"),
        ]

    def test_build_populates_adjacency(self):
        g = ItemCompatibilityGraph().build(self._wardrobe())
        partners = g.get_partners("top1")
        assert len(partners) > 0

    def test_top_does_not_pair_with_dress(self):
        g = ItemCompatibilityGraph().build(self._wardrobe())
        all_scores = g.all_scores("top1")
        assert all_scores.get("dress1", -1) == 0.0

    def test_get_partners_top_n(self):
        wardrobe = [_item(str(i), "tops") for i in range(10)]
        wardrobe += [_item("bot", "bottoms")]
        g = ItemCompatibilityGraph().build(wardrobe)
        partners = g.get_partners("bot", top_n=3)
        assert len(partners) <= 3

    def test_edge_count_respects_min_score(self):
        g = ItemCompatibilityGraph().build(self._wardrobe())
        count_05 = g.edge_count("top1", min_score=0.5)
        count_09 = g.edge_count("top1", min_score=0.9)
        assert count_05 >= count_09

    def test_build_is_symmetric(self):
        wardrobe = [
            _item("a", "tops"),
            _item("b", "bottoms"),
        ]
        g = ItemCompatibilityGraph().build(wardrobe)
        assert g.all_scores("a").get("b") == g.all_scores("b").get("a")

    def test_empty_wardrobe(self):
        g = ItemCompatibilityGraph().build([])
        assert g.get_partners("x") == []
        assert g.edge_count("x") == 0

    def test_single_item_wardrobe(self):
        g = ItemCompatibilityGraph().build([_item("a", "tops")])
        assert g.get_partners("a") == []
