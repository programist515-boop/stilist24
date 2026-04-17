"""Tests for PaletteFitScorer (Sprint 3)."""

from __future__ import annotations

import pytest

from app.services.outfits.scoring.palette_fit import PaletteFitScorer


def _item(id: str, category: str, primary_color: str | None = None) -> dict:
    attrs = {}
    if primary_color is not None:
        attrs["primary_color"] = primary_color
    return {"id": id, "category": category, "attributes": attrs}


def _v2_item(id: str, category: str, primary_color: str) -> dict:
    return {
        "id": id,
        "category": category,
        "attributes": {
            "primary_color": {
                "value": primary_color,
                "confidence": 0.9,
                "source": "cv",
                "editable": True,
            }
        },
    }


PALETTE = ["#C5D5CB", "#A4B5AC", "#8B9E91"]


class TestPaletteFitScorerNoContext:
    def test_no_palette_returns_neutral(self):
        scorer = PaletteFitScorer()
        items = [_item("a", "tops", "red")]
        result = scorer.score(items, context={})
        assert result.score == 0.5
        assert result.weight == pytest.approx(0.15)

    def test_empty_outfit_returns_zero(self):
        scorer = PaletteFitScorer()
        result = scorer.score([], context={"palette_hex": PALETTE})
        assert result.score == 0.0
        assert len(result.warnings) > 0


class TestPaletteFitScorerNeutrals:
    def test_neutral_white_scores_high(self):
        scorer = PaletteFitScorer()
        items = [_item("a", "tops", "white"), _item("b", "bottoms", "black")]
        result = scorer.score(items, context={"palette_hex": PALETTE})
        assert result.score >= 0.9

    def test_all_neutrals_full_score(self):
        scorer = PaletteFitScorer()
        items = [
            _item("a", "tops", "white"),
            _item("b", "bottoms", "navy"),
            _item("c", "shoes", "black"),
        ]
        result = scorer.score(items, context={"palette_hex": PALETTE})
        assert result.score >= 0.9

    def test_grey_and_beige_also_neutrals(self):
        scorer = PaletteFitScorer()
        items = [_item("a", "tops", "grey"), _item("b", "bottoms", "beige")]
        result = scorer.score(items, context={"palette_hex": PALETTE})
        assert result.score >= 0.9


class TestPaletteFitScorerNonNeutrals:
    def test_non_neutral_with_palette_gets_default_score(self):
        scorer = PaletteFitScorer()
        items = [_item("a", "tops", "coral")]
        result = scorer.score(items, context={"palette_hex": PALETTE})
        # Non-neutral defaults to _NON_NEUTRAL_DEFAULT_SCORE (0.65)
        assert 0.5 <= result.score <= 0.8

    def test_avoid_hex_lowers_score(self):
        scorer = PaletteFitScorer()
        items = [_item("a", "tops", "chartreuse")]
        result_no_avoid = scorer.score(items, context={"palette_hex": PALETTE})
        result_with_avoid = scorer.score(
            items,
            context={"palette_hex": PALETTE, "avoid_hex": ["chartreuse"]},
        )
        assert result_with_avoid.score < result_no_avoid.score


class TestPaletteFitScorerItemWithNoColor:
    def test_item_without_color_gets_neutral_score(self):
        scorer = PaletteFitScorer()
        items = [_item("a", "tops")]  # no primary_color
        result = scorer.score(items, context={"palette_hex": PALETTE})
        assert result.score == pytest.approx(0.5)

    def test_v2_nested_color_resolved(self):
        scorer = PaletteFitScorer()
        items = [_v2_item("a", "tops", "white")]
        result = scorer.score(items, context={"palette_hex": PALETTE})
        assert result.score >= 0.9


class TestPaletteFitScorerMixed:
    def test_mixed_neutral_and_non_neutral(self):
        scorer = PaletteFitScorer()
        items = [
            _item("a", "tops", "white"),   # neutral
            _item("b", "shoes", "coral"),  # non-neutral
        ]
        result = scorer.score(items, context={"palette_hex": PALETTE})
        # Average of 1.0 and 0.65 ≈ 0.825 (round down to 2 decimal places)
        assert 0.7 <= result.score <= 0.9

    def test_reasons_list_populated(self):
        scorer = PaletteFitScorer()
        items = [_item("a", "tops", "white")]
        result = scorer.score(items, context={"palette_hex": PALETTE})
        assert len(result.reasons) >= 1

    def test_weight_correct(self):
        assert PaletteFitScorer.weight == pytest.approx(0.15)
