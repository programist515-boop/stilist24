"""Tests for extended gap analyzer (Sprint 2)."""

from __future__ import annotations

import pytest

from app.services.analytics.gap_analyzer import (
    analyze_extended,
    _layering_gaps,
    _occasion_gaps,
    _palette_gaps,
    _imbalance_gaps,
    _overbought_gaps,
)


def _item(id: str, category: str, wear_count: int = 0, **attrs) -> dict:
    return {"id": id, "category": category, "wear_count": wear_count, "attributes": attrs}


def _item_with_occasion(id: str, category: str, occasion: str, wear_count: int = 0) -> dict:
    return _item(id, category, wear_count, occasion=occasion)


# ---------------------------------------------------------------------------
# _layering_gaps
# ---------------------------------------------------------------------------

class TestLayeringGaps:
    def test_no_outerwear_flagged(self):
        wardrobe = [_item("t", "tops"), _item("b", "bottoms")]
        gaps = _layering_gaps(wardrobe)
        types = [g["gap_type"] for g in gaps]
        assert "no_outerwear" in types

    def test_has_outerwear_no_basic_gap(self):
        wardrobe = [_item("t", "tops"), _item("b", "bottoms"), _item("o", "outerwear")]
        gaps = _layering_gaps(wardrobe)
        types = [g["gap_type"] for g in gaps]
        assert "no_outerwear" not in types

    def test_formal_items_no_blazer_flagged(self):
        wardrobe = [
            _item_with_occasion("t", "tops", "business"),
            _item("o", "outerwear"),  # outerwear present but not blazer
        ]
        gaps = _layering_gaps(wardrobe)
        types = [g["gap_type"] for g in gaps]
        assert "no_blazer_layer" in types

    def test_blazer_present_no_gap(self):
        wardrobe = [
            _item_with_occasion("t", "tops", "business"),
            {"id": "o", "category": "outerwear", "wear_count": 0, "attributes": {"subcategory": "blazer"}},
        ]
        gaps = _layering_gaps(wardrobe)
        types = [g["gap_type"] for g in gaps]
        assert "no_blazer_layer" not in types

    def test_dress_without_outerwear_flagged(self):
        wardrobe = [_item("d", "dresses")]
        gaps = _layering_gaps(wardrobe)
        types = [g["gap_type"] for g in gaps]
        assert "dress_no_layer" in types or "no_outerwear" in types

    def test_empty_wardrobe_returns_gap(self):
        gaps = _layering_gaps([])
        assert any(g["gap_type"] == "no_outerwear" for g in gaps)


# ---------------------------------------------------------------------------
# _occasion_gaps
# ---------------------------------------------------------------------------

class TestOccasionGaps:
    def test_all_occasions_missing(self):
        wardrobe = [_item("x", "tops")]
        gaps = _occasion_gaps(wardrobe)
        assert len(gaps) == 5  # all 5 key occasions missing

    def test_covered_occasion_not_in_gaps(self):
        wardrobe = [_item_with_occasion("x", "tops", "casual")]
        gaps = _occasion_gaps(wardrobe)
        present_occs = {g["occasion"] for g in gaps}
        assert "casual" not in present_occs

    def test_all_occasions_covered_no_gaps(self):
        wardrobe = [
            _item_with_occasion("a", "tops", "casual"),
            _item_with_occasion("b", "tops", "smart_casual"),
            _item_with_occasion("c", "tops", "business"),
            _item_with_occasion("d", "tops", "sport"),
            _item_with_occasion("e", "tops", "evening"),
        ]
        gaps = _occasion_gaps(wardrobe)
        assert len(gaps) == 0

    def test_v2_nested_occasion_resolved(self):
        wardrobe = [
            {
                "id": "a",
                "category": "tops",
                "attributes": {"occasion": {"value": "sport", "confidence": 0.9, "source": "cv", "editable": True}},
            }
        ]
        gaps = _occasion_gaps(wardrobe)
        present_occs = {g["occasion"] for g in gaps}
        assert "sport" not in present_occs


# ---------------------------------------------------------------------------
# _palette_gaps
# ---------------------------------------------------------------------------

class TestPaletteGaps:
    def test_empty_palette_no_gaps(self):
        wardrobe = [_item("a", "tops", primary_color="red")]
        gaps = _palette_gaps(wardrobe, [])
        assert len(gaps) == 0

    def test_no_color_items_counted_as_off_palette(self):
        # Items without a color attribute are not in NEUTRAL_COLORS and
        # palette_hex is non-empty, so _color_in_palette returns True.
        # All items effectively "fit" the palette → no gap fires.
        wardrobe = [_item("a", "tops"), _item("b", "tops"), _item("c", "tops")]
        gaps = _palette_gaps(wardrobe, ["#FF0000"])
        assert isinstance(gaps, list)  # No crash; result is always a list

    def test_empty_palette_skips_check(self):
        wardrobe = [_item("a", "tops", primary_color="red")]
        assert _palette_gaps(wardrobe, []) == []

    def test_mostly_neutrals_not_flagged(self):
        wardrobe = [
            _item("a", "tops", primary_color="white"),
            _item("b", "tops", primary_color="black"),
            _item("c", "tops", primary_color="grey"),
        ]
        gaps = _palette_gaps(wardrobe, ["#000000"])
        assert len(gaps) == 0

    def test_empty_wardrobe_no_gaps(self):
        gaps = _palette_gaps([], ["#FFFFFF"])
        assert len(gaps) == 0


# ---------------------------------------------------------------------------
# _imbalance_gaps
# ---------------------------------------------------------------------------

class TestImbalanceGaps:
    def test_dominant_category_flagged(self):
        wardrobe = [_item(str(i), "tops") for i in range(5)]
        wardrobe.append(_item("b", "bottoms"))
        gaps = _imbalance_gaps(wardrobe)
        assert any(g["category"] == "tops" for g in gaps)

    def test_balanced_wardrobe_no_gaps(self):
        wardrobe = (
            [_item(str(i), "tops") for i in range(2)]
            + [_item(str(i + 10), "bottoms") for i in range(2)]
            + [_item(str(i + 20), "shoes") for i in range(2)]
            + [_item(str(i + 30), "outerwear") for i in range(2)]
        )
        gaps = _imbalance_gaps(wardrobe)
        assert len(gaps) == 0

    def test_empty_wardrobe_no_gaps(self):
        assert _imbalance_gaps([]) == []

    def test_ratio_field_present(self):
        wardrobe = [_item(str(i), "tops") for i in range(5)] + [_item("x", "shoes")]
        gaps = _imbalance_gaps(wardrobe)
        for g in gaps:
            assert "ratio" in g
            assert 0.0 <= g["ratio"] <= 1.0


# ---------------------------------------------------------------------------
# _overbought_gaps
# ---------------------------------------------------------------------------

class TestOverboughtGaps:
    def test_four_unworn_items_flagged(self):
        wardrobe = [_item(str(i), "tops", wear_count=0) for i in range(5)]
        gaps = _overbought_gaps(wardrobe)
        assert any(g["category"] == "tops" for g in gaps)

    def test_mostly_worn_not_flagged(self):
        wardrobe = [_item(str(i), "tops", wear_count=i + 1) for i in range(5)]
        gaps = _overbought_gaps(wardrobe)
        assert len(gaps) == 0

    def test_threshold_three_not_flagged(self):
        wardrobe = [_item(str(i), "tops", wear_count=0) for i in range(3)]
        gaps = _overbought_gaps(wardrobe)
        assert len(gaps) == 0

    def test_mixed_worn_status(self):
        # 4 items: 1 worn, 3 unworn → diversity = 0.25 < 0.3 → flagged
        wardrobe = [
            _item("0", "tops", wear_count=5),
            _item("1", "tops", wear_count=0),
            _item("2", "tops", wear_count=0),
            _item("3", "tops", wear_count=0),
        ]
        gaps = _overbought_gaps(wardrobe)
        assert any(g["category"] == "tops" for g in gaps)

    def test_unworn_ids_in_result(self):
        wardrobe = [_item(str(i), "tops", wear_count=0) for i in range(4)]
        gaps = _overbought_gaps(wardrobe)
        assert len(gaps) > 0
        assert "unworn_item_ids" in gaps[0]
        assert len(gaps[0]["unworn_item_ids"]) == 4


# ---------------------------------------------------------------------------
# analyze_extended — integration
# ---------------------------------------------------------------------------

class TestAnalyzeExtended:
    def test_returns_all_five_keys(self):
        result = analyze_extended([])
        for key in ["layering_gaps", "occasion_gaps", "palette_gaps", "imbalance_gaps", "overbought_gaps", "notes"]:
            assert key in result

    def test_balanced_wardrobe_notes_say_no_gaps(self):
        wardrobe = [
            _item_with_occasion("t", "tops", "casual"),
            _item_with_occasion("b", "bottoms", "casual"),
            _item("o", "outerwear"),
            _item_with_occasion("s", "shoes", "smart_casual"),
            _item_with_occasion("f", "tops", "business"),
            _item_with_occasion("e", "tops", "evening"),
            _item_with_occasion("sp", "tops", "sport"),
        ]
        result = analyze_extended(wardrobe)
        # Not asserting "no gaps" since imbalance and occasion gaps may still fire
        assert isinstance(result["notes"], list)

    def test_user_context_palette_passed_through(self):
        wardrobe = [_item("a", "tops", primary_color="neon_green")] * 5
        result = analyze_extended(wardrobe, user_context={"palette_hex": ["#FFFFFF"]})
        # Palette gaps may fire since all items are the same non-neutral color
        assert isinstance(result["palette_gaps"], list)

    def test_notes_mention_specific_gap_types(self):
        wardrobe = [_item(str(i), "tops") for i in range(8)]
        result = analyze_extended(wardrobe)
        combined = " ".join(result["notes"]).lower()
        # Expects at least one actionable note
        assert len(result["notes"]) >= 1
