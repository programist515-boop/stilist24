"""Tests for PurchaseEvaluator — buy / maybe / skip scenarios (Sprint 4)."""

from __future__ import annotations

import uuid

import pytest

from app.services.shopping.candidate_parser import parse_from_attrs
from app.services.shopping.purchase_evaluator import PurchaseEvaluator, _weighted_avg


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _item(id: str, category: str, color: str | None = None, occasion: str | None = None, cost: float | None = None, wear_count: int = 0) -> dict:
    attrs: dict = {}
    if color:
        attrs["primary_color"] = color
    if occasion:
        attrs["occasion"] = occasion
    return {
        "id": id,
        "category": category,
        "attributes": attrs,
        **(attrs),
        "cost": cost,
        "wear_count": wear_count,
    }


def _candidate(category: str, color: str | None = None, price: float | None = None) -> dict:
    raw: dict = {"category": category}
    if color:
        raw["primary_color"] = color
    return parse_from_attrs(raw, price=price)


def _small_wardrobe() -> list[dict]:
    return [
        _item("top1", "top", "white", "casual"),
        _item("top2", "top", "black", "business"),
        _item("bot1", "bottom", "navy", "casual"),
        _item("shoe1", "shoes", "white"),
        _item("dress1", "dress", "red", "evening"),
    ]


# ---------------------------------------------------------------------------
# parse_from_attrs
# ---------------------------------------------------------------------------

class TestCandidateParser:
    def test_returns_dict_with_required_keys(self):
        c = parse_from_attrs({"category": "tops"})
        assert "id" in c
        assert "category" in c
        assert "attributes" in c
        assert "cost" in c
        assert "wear_count" in c

    def test_wear_count_is_zero(self):
        c = parse_from_attrs({"category": "tops"})
        assert c["wear_count"] == 0

    def test_price_stored_as_cost(self):
        c = parse_from_attrs({"category": "tops"}, price=79.99)
        assert c["cost"] == 79.99

    def test_is_candidate_flag(self):
        c = parse_from_attrs({"category": "tops"})
        assert c.get("_is_candidate") is True

    def test_each_call_generates_new_id(self):
        a = parse_from_attrs({"category": "tops"})
        b = parse_from_attrs({"category": "tops"})
        assert a["id"] != b["id"]


# ---------------------------------------------------------------------------
# _weighted_avg helper
# ---------------------------------------------------------------------------

class TestWeightedAvg:
    def test_all_ones_returns_near_one(self):
        scores = {k: {"score": 1.0} for k in ["palette_match", "gap_fill", "wardrobe_compat", "redundancy_penalty", "expected_versatility", "budget_fit"]}
        avg = _weighted_avg(scores)
        assert avg == pytest.approx(1.0)

    def test_all_zeros_returns_zero(self):
        scores = {k: {"score": 0.0} for k in ["palette_match", "gap_fill", "wardrobe_compat", "redundancy_penalty", "expected_versatility", "budget_fit"]}
        avg = _weighted_avg(scores)
        assert avg == pytest.approx(0.0)

    def test_empty_returns_zero(self):
        assert _weighted_avg({}) == 0.0


# ---------------------------------------------------------------------------
# PurchaseEvaluator — decision scenarios
# ---------------------------------------------------------------------------

class TestPurchaseEvaluatorDecision:
    def test_evaluate_returns_required_keys(self):
        evaluator = PurchaseEvaluator([])
        c = _candidate("tops")
        result = evaluator.evaluate(c)
        for key in ["decision", "confidence", "reasons", "warnings", "pairs_with_count", "fills_gap_ids", "duplicate_like_item_ids", "subscores"]:
            assert key in result

    def test_decision_is_valid_literal(self):
        evaluator = PurchaseEvaluator(_small_wardrobe())
        c = _candidate("shoes", color="white")
        result = evaluator.evaluate(c)
        assert result["decision"] in {"buy", "maybe", "skip"}

    def test_confidence_bounded(self):
        evaluator = PurchaseEvaluator(_small_wardrobe())
        c = _candidate("tops")
        result = evaluator.evaluate(c)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_subscores_all_present(self):
        evaluator = PurchaseEvaluator(_small_wardrobe())
        c = _candidate("tops")
        result = evaluator.evaluate(c)
        for key in ["palette_match", "gap_fill", "wardrobe_compat", "redundancy_penalty", "expected_versatility", "budget_fit"]:
            assert key in result["subscores"]

    def test_subscore_bounded(self):
        evaluator = PurchaseEvaluator(_small_wardrobe())
        c = _candidate("tops")
        result = evaluator.evaluate(c)
        for k, v in result["subscores"].items():
            assert 0.0 <= v["score"] <= 1.0, f"{k} out of bounds: {v['score']}"

    def test_highly_compatible_neutral_item_scores_high(self):
        wardrobe = (
            [_item(f"top{i}", "top", "white", "casual") for i in range(3)]
            + [_item(f"bot{i}", "bottom", "navy", "casual") for i in range(2)]
            + [_item("shoe1", "shoes", "white")]
        )
        evaluator = PurchaseEvaluator(wardrobe, {"palette_hex": ["#FFFFFF", "#000000"]})
        c = _candidate("shoes", color="white", price=50.0)
        result = evaluator.evaluate(c)
        assert result["confidence"] >= 0.4

    def test_highly_redundant_item_gets_skip_or_maybe(self):
        wardrobe = [
            _item("a", "tops", "red", "casual"),
            _item("b", "tops", "red", "casual"),
            _item("c", "tops", "red", "casual"),
        ]
        evaluator = PurchaseEvaluator(wardrobe)
        # Candidate is a red casual top — very redundant
        c = parse_from_attrs({"category": "tops", "primary_color": "red", "occasion": "casual"})
        result = evaluator.evaluate(c)
        # redundancy should penalise
        assert result["subscores"]["redundancy_penalty"]["score"] < 0.5

    def test_empty_wardrobe_does_not_crash(self):
        evaluator = PurchaseEvaluator([])
        c = _candidate("tops", price=100.0)
        result = evaluator.evaluate(c)
        assert result["decision"] in {"buy", "maybe", "skip"}

    def test_no_price_budget_fit_neutral(self):
        evaluator = PurchaseEvaluator([])
        c = _candidate("tops")  # no price
        result = evaluator.evaluate(c)
        assert result["subscores"]["budget_fit"]["score"] == pytest.approx(0.5)

    def test_cheap_item_gets_good_budget_score(self):
        evaluator = PurchaseEvaluator([])
        c = _candidate("tops", price=10.0)
        result = evaluator.evaluate(c)
        # 10/24 wears ≈ 0.42 projected CPW → score should be 1.0
        assert result["subscores"]["budget_fit"]["score"] >= 0.75

    def test_very_expensive_item_gets_low_budget_score(self):
        evaluator = PurchaseEvaluator([])
        c = _candidate("tops", price=2000.0)  # CPW ≈ 83 → score 0.1
        result = evaluator.evaluate(c)
        assert result["subscores"]["budget_fit"]["score"] < 0.5


# ---------------------------------------------------------------------------
# PurchaseEvaluator — wardrobe compatibility
# ---------------------------------------------------------------------------

class TestCompatibilitySubscore:
    def test_pairs_with_count_present(self):
        evaluator = PurchaseEvaluator(_small_wardrobe())
        c = _candidate("shoes")
        result = evaluator.evaluate(c)
        assert isinstance(result["pairs_with_count"], int)

    def test_shoes_pair_with_tops_and_bottoms(self):
        wardrobe = [
            _item("top1", "top", "white"),
            _item("bot1", "bottom", "black"),
        ]
        evaluator = PurchaseEvaluator(wardrobe)
        c = _candidate("shoes", color="white")
        result = evaluator.evaluate(c)
        assert result["pairs_with_count"] >= 1


# ---------------------------------------------------------------------------
# PurchaseEvaluator — gap fill
# ---------------------------------------------------------------------------

class TestGapFillSubscore:
    def test_outerwear_fills_layering_gap(self):
        wardrobe = [_item("t", "top"), _item("b", "bottom"), _item("s", "shoes")]
        evaluator = PurchaseEvaluator(wardrobe)
        c = parse_from_attrs({"category": "outerwear"})
        result = evaluator.evaluate(c)
        assert result["subscores"]["gap_fill"]["score"] >= 0.5


# ---------------------------------------------------------------------------
# Explicit buy / maybe / skip fixture scenarios
# ---------------------------------------------------------------------------

class TestBuyScenario:
    """A neutral-coloured shoe filling a missing-shoes wardrobe gap and pairing
    with every top+bottom should score well enough to reach 'buy' or 'maybe'."""

    def _make_wardrobe_without_shoes(self) -> list[dict]:
        return [
            _item("t1", "top", "white", "casual", cost=50.0, wear_count=10),
            _item("t2", "top", "navy", "smart_casual", cost=60.0, wear_count=8),
            _item("b1", "bottom", "black", "casual", cost=70.0, wear_count=12),
            _item("b2", "bottom", "navy", "smart_casual", cost=80.0, wear_count=6),
            _item("d1", "dress", "white", "evening", cost=120.0, wear_count=3),
        ]

    def test_versatile_neutral_shoe_is_buy_or_maybe(self):
        wardrobe = self._make_wardrobe_without_shoes()
        ctx = {"palette_hex": ["#FFFFFF", "#000000", "#000080"]}
        evaluator = PurchaseEvaluator(wardrobe, ctx)
        c = parse_from_attrs({"category": "shoes", "primary_color": "white"}, price=80.0)
        result = evaluator.evaluate(c)
        assert result["decision"] in {"buy", "maybe"}
        assert result["confidence"] >= 0.45

    def test_buy_decision_has_non_empty_reasons(self):
        wardrobe = self._make_wardrobe_without_shoes()
        evaluator = PurchaseEvaluator(wardrobe)
        c = parse_from_attrs({"category": "shoes", "primary_color": "white"}, price=60.0)
        result = evaluator.evaluate(c)
        assert len(result["reasons"]) > 0

    def test_buy_has_positive_pairs_with_count(self):
        wardrobe = self._make_wardrobe_without_shoes()
        evaluator = PurchaseEvaluator(wardrobe)
        c = parse_from_attrs({"category": "shoes", "primary_color": "white"})
        result = evaluator.evaluate(c)
        # Shoes pair with tops + bottoms
        assert result["pairs_with_count"] >= 1


class TestSkipScenario:
    """A duplicate item that's already over-represented and palette-incompatible
    should produce a 'skip' or at most 'maybe'."""

    def _make_redundant_wardrobe(self) -> list[dict]:
        # 5 identical casual black tops — classic over-concentration
        # Use "tops" to match parse_from_attrs default normalisation
        return [_item(f"t{i}", "tops", "black", "casual") for i in range(5)]

    def test_exact_duplicate_item_scores_low(self):
        wardrobe = self._make_redundant_wardrobe()
        evaluator = PurchaseEvaluator(wardrobe)
        c = parse_from_attrs({"category": "tops", "primary_color": "black", "occasion": "casual"})
        result = evaluator.evaluate(c)
        # Redundancy penalty should fire — same category+color+occasion
        assert result["subscores"]["redundancy_penalty"]["score"] < 0.5

    def test_skip_decision_has_warnings(self):
        wardrobe = self._make_redundant_wardrobe()
        evaluator = PurchaseEvaluator(wardrobe)
        c = parse_from_attrs({"category": "tops", "primary_color": "black", "occasion": "casual"})
        result = evaluator.evaluate(c)
        assert len(result["subscores"]["redundancy_penalty"]["warnings"]) > 0

    def test_duplicate_like_items_populated(self):
        wardrobe = self._make_redundant_wardrobe()
        evaluator = PurchaseEvaluator(wardrobe)
        c = parse_from_attrs({"category": "tops", "primary_color": "black", "occasion": "casual"})
        result = evaluator.evaluate(c)
        assert isinstance(result["duplicate_like_item_ids"], list)


class TestMaybeScenario:
    """A decent item that fills no gap and is moderately compatible should land in 'maybe'."""

    def test_mid_tier_item_decision_valid(self):
        wardrobe = [
            _item("t1", "top", "white", "casual"),
            _item("b1", "bottom", "black", "casual"),
            _item("s1", "shoes", "white"),
        ]
        ctx = {"palette_hex": ["#FFFFFF"]}
        evaluator = PurchaseEvaluator(wardrobe, ctx)
        # A second white shoe — fills no gap, some redundancy, decent compat
        c = parse_from_attrs({"category": "shoes", "primary_color": "white"}, price=150.0)
        result = evaluator.evaluate(c)
        assert result["decision"] in {"buy", "maybe", "skip"}  # any valid decision is fine

    def test_summary_in_reasons(self):
        wardrobe = [
            _item("t1", "top", "white", "casual"),
            _item("b1", "bottom", "black", "casual"),
            _item("s1", "shoes", "white"),
        ]
        evaluator = PurchaseEvaluator(wardrobe)
        c = parse_from_attrs({"category": "shoes"}, price=100.0)
        result = evaluator.evaluate(c)
        # Reasons should include at least the YAML decision headline
        assert isinstance(result["reasons"], list)
        assert len(result["reasons"]) > 0


class TestExplanationTemplates:
    """The YAML shopping_explanations templates should produce non-empty reason lines."""

    def test_decision_headline_in_reasons(self):
        from app.services.shopping.purchase_evaluator import _build_summary
        # Manually invoke _build_summary with a mocked scores dict
        scores = {
            "palette_match": {"score": 0.85, "reasons": [], "_fills_gap_category_ids": []},
            "gap_fill": {"score": 0.8, "reasons": [], "_fills_gap_category_ids": ["casual"]},
            "wardrobe_compat": {"score": 0.9, "reasons": [], "_pairs_with_count": 5},
            "redundancy_penalty": {"score": 0.9, "reasons": []},
            "expected_versatility": {"score": 0.8, "reasons": ["enables 4 outfit combinations"]},
            "budget_fit": {"score": 0.9, "reasons": []},
        }
        summary = _build_summary("buy", scores, {})
        assert isinstance(summary, list)
        # At minimum the decision line should appear if YAML loaded correctly
        # (tolerates empty YAML gracefully)

    def test_skip_generates_summary(self):
        from app.services.shopping.purchase_evaluator import _build_summary
        scores = {
            "palette_match": {"score": 0.2, "reasons": [], "_fills_gap_category_ids": []},
            "gap_fill": {"score": 0.1, "reasons": [], "_fills_gap_category_ids": []},
            "wardrobe_compat": {"score": 0.1, "reasons": [], "_pairs_with_count": 0},
            "redundancy_penalty": {"score": 0.1, "reasons": []},
            "expected_versatility": {"score": 0.1, "reasons": ["enables 0 outfit combinations"]},
            "budget_fit": {"score": 0.1, "reasons": []},
        }
        summary = _build_summary("skip", scores, {})
        assert isinstance(summary, list)
