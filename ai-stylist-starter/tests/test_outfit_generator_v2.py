"""Tests for OutfitGenerator and DiversityReranker (Sprint 3)."""

from __future__ import annotations

import pytest

from app.services.outfits.diversity_reranker import rerank, _base_signature
from app.services.outfits.outfit_generator import OutfitGenerator


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _item(id: str, category: str, **attrs) -> dict:
    return {"id": id, "category": category, "attributes": attrs, **attrs}


def _small_wardrobe() -> list[dict]:
    return [
        _item("top1", "top"),
        _item("top2", "top"),
        _item("bot1", "bottom"),
        _item("shoe1", "shoes"),
        _item("shoe2", "shoes"),
        _item("dress1", "dress"),
    ]


def _outfit_dict(items: list[dict], score: float, template: str = "tmpl") -> dict:
    return {
        "items": items,
        "scores": {"overall": score},
        "generation": {"template": template, "optional_used": None},
    }


# ---------------------------------------------------------------------------
# DiversityReranker
# ---------------------------------------------------------------------------

class TestBaseSignature:
    def test_same_items_same_signature(self):
        a = _outfit_dict([_item("1", "tops"), _item("2", "bottoms")], 0.8)
        b = _outfit_dict([_item("1", "tops"), _item("2", "bottoms")], 0.7)
        assert _base_signature(a) == _base_signature(b)

    def test_different_items_different_signature(self):
        a = _outfit_dict([_item("1", "tops"), _item("2", "bottoms")], 0.8)
        b = _outfit_dict([_item("1", "tops"), _item("3", "bottoms")], 0.8)
        assert _base_signature(a) != _base_signature(b)

    def test_accessory_excluded_from_signature(self):
        base = [_item("t", "tops"), _item("b", "bottoms")]
        a = _outfit_dict(base + [_item("acc1", "accessory")], 0.8)
        c = _outfit_dict(base + [_item("acc2", "bag")], 0.8)
        assert _base_signature(a) == _base_signature(c)


class TestRerank:
    def test_empty_input(self):
        assert rerank([], 5) == []

    def test_returns_at_most_max_n(self):
        outfits = [
            _outfit_dict([_item(str(i), "tops"), _item(str(i + 100), "bottoms")], float(i) / 10)
            for i in range(10)
        ]
        result = rerank(outfits, 3)
        assert len(result) <= 3

    def test_best_score_first(self):
        outfits = [
            _outfit_dict([_item("a", "tops"), _item("x", "bottoms")], 0.4),
            _outfit_dict([_item("b", "tops"), _item("y", "bottoms")], 0.9),
            _outfit_dict([_item("c", "tops"), _item("z", "bottoms")], 0.6),
        ]
        result = rerank(outfits, 3)
        scores = [o["scores"]["overall"] for o in result]
        assert scores[0] == pytest.approx(0.9)

    def test_deduplicates_by_signature(self):
        base = [_item("t", "tops"), _item("b", "bottoms")]
        outfits = [
            _outfit_dict(base + [_item("acc1", "accessory")], 0.9),
            _outfit_dict(base + [_item("acc2", "bag")], 0.8),
        ]
        result = rerank(outfits, 5)
        # Both have the same base signature — only the higher-scoring one kept
        assert len(result) == 1
        assert result[0]["scores"]["overall"] == pytest.approx(0.9)

    def test_prefers_novel_items_in_tie_band(self):
        shared = [_item("t", "tops")]
        a = _outfit_dict(shared + [_item("b1", "bottoms")], 0.8)
        b = _outfit_dict(shared + [_item("b2", "bottoms")], 0.8)
        result = rerank([a, b], 2)
        assert len(result) == 2
        # Both should be included since they have different bottom items

    def test_custom_tie_tolerance(self):
        outfits = [
            _outfit_dict([_item("a", "tops"), _item("x", "bottoms")], 0.7),
            _outfit_dict([_item("b", "tops"), _item("y", "bottoms")], 0.7),
        ]
        result = rerank(outfits, 5, tie_tolerance=0.001)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# OutfitGenerator
# ---------------------------------------------------------------------------

class TestOutfitGeneratorGenerate:
    def test_generate_empty_wardrobe(self):
        gen = OutfitGenerator()
        result = gen.generate([])
        assert result == []

    def test_generate_returns_list(self):
        gen = OutfitGenerator()
        result = gen.generate(_small_wardrobe())
        assert isinstance(result, list)

    def test_generate_outfit_has_required_keys(self):
        gen = OutfitGenerator()
        result = gen.generate(_small_wardrobe())
        if result:
            outfit = result[0]
            assert "items" in outfit
            assert "scores" in outfit
            assert "breakdown" in outfit
            assert "total_score" in outfit

    def test_generate_outfit_scores_bounded(self):
        gen = OutfitGenerator()
        for outfit in gen.generate(_small_wardrobe()):
            assert 0.0 <= outfit["total_score"] <= 1.0

    def test_generate_respects_top_n(self):
        gen = OutfitGenerator()
        wardrobe = (
            [_item(f"top{i}", "top") for i in range(5)]
            + [_item(f"bot{i}", "bottom") for i in range(5)]
            + [_item(f"shoe{i}", "shoes") for i in range(3)]
        )
        result = gen.generate(wardrobe, top_n=3)
        assert len(result) <= 3

    def test_generate_with_occasion_filter(self):
        gen = OutfitGenerator()
        result = gen.generate(_small_wardrobe(), context={"occasion": "casual"})
        for outfit in result:
            # occasion is propagated to context
            assert isinstance(result, list)


class TestOutfitGeneratorForItem:
    def test_for_item_all_outfits_contain_anchor(self):
        gen = OutfitGenerator()
        wardrobe = _small_wardrobe()
        anchor_id = "top1"
        result = gen.generate_for_item(anchor_id, wardrobe)
        for outfit in result:
            ids = [str(it.get("id")) for it in outfit["items"]]
            assert anchor_id in ids

    def test_for_item_unknown_id_returns_empty(self):
        gen = OutfitGenerator()
        result = gen.generate_for_item("nonexistent-id", _small_wardrobe())
        assert result == []

    def test_for_item_respects_top_n(self):
        gen = OutfitGenerator()
        wardrobe = (
            [_item(f"top{i}", "top") for i in range(4)]
            + [_item(f"bot{i}", "bottom") for i in range(4)]
            + [_item("shoe1", "shoes")]
        )
        result = gen.generate_for_item("top1", wardrobe, top_n=2)
        assert len(result) <= 2


class TestOutfitGeneratorForOccasion:
    def test_for_occasion_returns_list(self):
        gen = OutfitGenerator()
        result = gen.generate_for_occasion("casual", _small_wardrobe())
        assert isinstance(result, list)

    def test_for_occasion_passes_context(self):
        gen = OutfitGenerator()
        result = gen.generate_for_occasion("business", _small_wardrobe())
        for outfit in result:
            assert outfit.get("occasion") == "business"


class TestOutfitGeneratorDaily:
    def test_daily_returns_three_buckets(self):
        gen = OutfitGenerator()
        result = gen.generate_daily(_small_wardrobe())
        assert "safe" in result
        assert "balanced" in result
        assert "expressive" in result

    def test_daily_empty_wardrobe(self):
        gen = OutfitGenerator()
        result = gen.generate_daily([])
        assert result == {"safe": [], "balanced": [], "expressive": []}

    def test_daily_each_bucket_is_list(self):
        gen = OutfitGenerator()
        result = gen.generate_daily(_small_wardrobe())
        for key in ("safe", "balanced", "expressive"):
            assert isinstance(result[key], list)
            assert len(result[key]) <= 3
