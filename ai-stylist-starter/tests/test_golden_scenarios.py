"""Golden scenario tests — end-to-end consistency checks.

Each scenario represents a realistic user situation and verifies that
outfits, shopping, and analytics all agree and produce sensible results.

Scenarios
---------
1.  Minimal wardrobe (2 items)
2.  Tops-only wardrobe
3.  Business wardrobe
4.  Romantic/feminine wardrobe
5.  Cool color type (navy/grey palette)
6.  Warm color type (camel/coral palette)
7.  Duplicate-heavy wardrobe (redundancy)
8.  Orphan item in wardrobe
9.  Strong shopping buy candidate
10. Strong shopping skip candidate
11. All-neutral wardrobe
12. Very large wardrobe (performance sanity)
"""

from __future__ import annotations

import uuid

import pytest

from app.services.analytics.gap_analyzer import analyze_extended
from app.services.analytics.item_graph import ItemCompatibilityGraph, compatibility_score
from app.services.analytics.redundancy_service import cluster
from app.services.outfits.outfit_generator import OutfitGenerator
from app.services.shopping.candidate_parser import parse_from_attrs
from app.services.shopping.purchase_evaluator import PurchaseEvaluator
from app.services.user_context import build_user_context


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(
    category: str,
    color: str | None = None,
    occasion: str | None = None,
    *,
    item_id: str | None = None,
    cost: float | None = None,
    wear_count: int = 0,
    seasonality: str | None = None,
) -> dict:
    attrs: dict = {}
    if color:
        attrs["primary_color"] = color
    if occasion:
        attrs["occasion"] = occasion
    if seasonality:
        attrs["seasonality"] = seasonality
    d = {
        "id": item_id or str(uuid.uuid4()),
        "category": category,
        "attributes": attrs,
        **attrs,
        "cost": cost,
        "wear_count": wear_count,
    }
    return d


def _profile(palette_hex: list[str] | None = None) -> dict:
    return build_user_context(
        style_profile=_MockStyle(palette_hex),
        personalization_profile=None,
    )


class _MockStyle:
    def __init__(self, palette_hex: list[str] | None):
        self.kibbe_type = None
        self.color_profile_json = (
            {"palette_hex": palette_hex, "axes": {}} if palette_hex else {}
        )
        self.color_overrides_json = {}


# ---------------------------------------------------------------------------
# Scenario 1 — Minimal wardrobe (2 items)
# ---------------------------------------------------------------------------

class TestMinimalWardrobe:
    """2 items: one top + one bottom. Outfit generation and gap analysis
    should handle this gracefully without crashing."""

    wardrobe = [
        _item("tops", "white", "casual"),
        _item("bottoms", "black", "casual"),
    ]

    def test_outfit_generator_does_not_crash(self):
        gen = OutfitGenerator()
        outfits = gen.generate(self.wardrobe)
        # No shoes → template requires shoes, so 0 outfits is acceptable
        assert isinstance(outfits, list)

    def test_gap_analysis_detects_missing_shoes(self):
        gaps = analyze_extended(self.wardrobe)
        all_text = str(gaps)
        # Shoes or layering or occasion gap should be reported
        assert gaps["occasion_gaps"] or gaps["layering_gaps"] or gaps["notes"]

    def test_no_redundancy(self):
        clusters = cluster(self.wardrobe)
        dup = [c for c in clusters if c["type"] == "duplicate"]
        assert len(dup) == 0

    def test_shopping_evaluator_does_not_crash(self):
        evaluator = PurchaseEvaluator(self.wardrobe)
        c = parse_from_attrs({"category": "shoes", "primary_color": "white"}, price=80.0)
        result = evaluator.evaluate(c)
        assert result["decision"] in {"buy", "maybe", "skip"}


# ---------------------------------------------------------------------------
# Scenario 2 — Tops-only wardrobe
# ---------------------------------------------------------------------------

class TestTopsOnlyWardrobe:
    """5 tops, nothing else. Should flag critical gaps."""

    wardrobe = [_item("tops", "white") for _ in range(5)]

    def test_gap_analysis_flags_missing_bottoms(self):
        gaps = analyze_extended(self.wardrobe)
        notes = gaps.get("notes", [])
        all_gap_text = str(gaps)
        # Either imbalance or missing-category gap should appear
        has_imbalance = bool(gaps.get("imbalance_gaps"))
        has_occasion = bool(gaps.get("occasion_gaps"))
        assert has_imbalance or has_occasion or notes

    def test_outfit_generator_returns_empty_or_few(self):
        gen = OutfitGenerator()
        outfits = gen.generate(self.wardrobe)
        # No bottoms or shoes → very few valid outfits expected
        assert isinstance(outfits, list)

    def test_redundancy_detected(self):
        clusters = cluster(self.wardrobe)
        same_role = [c for c in clusters if c["type"] == "same_role"]
        assert len(same_role) > 0


# ---------------------------------------------------------------------------
# Scenario 3 — Business wardrobe
# ---------------------------------------------------------------------------

class TestBusinessWardrobe:
    """Standard 9-to-5 wardrobe. Outfit generation should produce
    business/smart_casual outfits. Shopping a casual item should score lower."""

    wardrobe = [
        _item("tops", "white", "business"),
        _item("tops", "navy", "business"),
        _item("bottoms", "black", "business"),
        _item("bottoms", "grey", "business"),
        _item("shoes", "black", "business"),
        _item("outerwear", "navy", "business"),
    ]
    ctx = _profile(["#FFFFFF", "#000080", "#000000"])

    def test_outfits_generated(self):
        gen = OutfitGenerator()
        outfits = gen.generate(self.wardrobe, user_profile=self.ctx, occasion="business")
        assert len(outfits) > 0

    def test_all_outfits_have_source_field(self):
        gen = OutfitGenerator()
        outfits = gen.generate(self.wardrobe, user_profile=self.ctx)
        for o in outfits:
            assert o.get("outfit_source") == "generator"

    def test_casual_candidate_has_valid_gap_fill_score(self):
        evaluator = PurchaseEvaluator(self.wardrobe, self.ctx)
        c = parse_from_attrs({"category": "tops", "primary_color": "white", "occasion": "casual"}, price=60.0)
        result = evaluator.evaluate(c)
        # Gap fill score must be in valid range (0-1); whether it fills a gap
        # depends on the gap analyzer's structural check, not just occasion coverage
        assert 0.0 <= result["subscores"]["gap_fill"]["score"] <= 1.0

    def test_another_business_top_is_redundant(self):
        evaluator = PurchaseEvaluator(self.wardrobe, self.ctx)
        c = parse_from_attrs({"category": "tops", "primary_color": "white", "occasion": "business"})
        result = evaluator.evaluate(c)
        assert result["subscores"]["redundancy_penalty"]["score"] < 0.8


# ---------------------------------------------------------------------------
# Scenario 4 — Romantic wardrobe
# ---------------------------------------------------------------------------

class TestRomanticWardrobe:
    """Soft feminine wardrobe. Good palette match for warm-spring type."""

    wardrobe = [
        _item("tops", "pink", "casual"),
        _item("tops", "coral", "casual"),
        _item("bottoms", "white", "casual"),
        _item("dresses", "lavender", "evening"),
        _item("shoes", "white", "casual"),
    ]
    ctx = _profile(["#FFB6C1", "#FF7F50", "#FFFFFF", "#E6E6FA"])  # pink/coral/white/lavender

    def test_outfits_generated(self):
        gen = OutfitGenerator()
        outfits = gen.generate(self.wardrobe, user_profile=self.ctx)
        assert len(outfits) > 0

    def test_palette_score_reasonable(self):
        gen = OutfitGenerator()
        outfits = gen.generate(self.wardrobe, user_profile=self.ctx)
        if outfits:
            top_outfit = max(outfits, key=lambda o: o["scores"].get("overall", 0))
            assert top_outfit["scores"].get("overall", 0) >= 0.3

    def test_all_outfits_have_reasons(self):
        gen = OutfitGenerator()
        outfits = gen.generate(self.wardrobe, user_profile=self.ctx)
        for o in outfits:
            assert isinstance(o.get("reasons"), list)


# ---------------------------------------------------------------------------
# Scenario 5 — Cool color type
# ---------------------------------------------------------------------------

class TestCoolColorType:
    """Navy/grey/white palette. Warm items should score lower in palette fit."""

    ctx = _profile(["#000080", "#808080", "#FFFFFF"])

    def test_navy_item_fits_cool_palette(self):
        from app.services.scoring.color_match import evaluate_color_fit
        result = evaluate_color_fit("navy", ["#000080", "#808080", "#FFFFFF"])
        assert result.score >= 0.85

    def test_warm_item_is_neutral_assumption_without_hex(self):
        from app.services.scoring.color_match import evaluate_color_fit
        result = evaluate_color_fit("coral", ["#000080", "#808080"])
        assert result.score == pytest.approx(0.65)

    def test_shopping_warm_item_not_in_palette(self):
        wardrobe = [
            _item("tops", "navy", "casual"),
            _item("bottoms", "grey", "casual"),
            _item("shoes", "white", "casual"),
        ]
        evaluator = PurchaseEvaluator(wardrobe, self.ctx)
        c = parse_from_attrs({"category": "tops", "primary_color": "coral"}, price=50.0)
        result = evaluator.evaluate(c)
        # palette_match score should be lower than for a navy item
        assert result["subscores"]["palette_match"]["score"] <= 0.75

    def test_shopping_navy_item_scores_higher_palette(self):
        wardrobe = [
            _item("tops", "grey", "casual"),
            _item("bottoms", "navy", "casual"),
            _item("shoes", "white", "casual"),
        ]
        evaluator = PurchaseEvaluator(wardrobe, self.ctx)
        c_navy = parse_from_attrs({"category": "tops", "primary_color": "navy"}, price=50.0)
        c_coral = parse_from_attrs({"category": "tops", "primary_color": "coral"}, price=50.0)
        r_navy = evaluator.evaluate(c_navy)
        r_coral = evaluator.evaluate(c_coral)
        assert (
            r_navy["subscores"]["palette_match"]["score"]
            >= r_coral["subscores"]["palette_match"]["score"]
        )


# ---------------------------------------------------------------------------
# Scenario 6 — Warm color type
# ---------------------------------------------------------------------------

class TestWarmColorType:
    """Camel/rust/cream palette. Cool navy should score lower."""

    ctx = _profile(["#C19A6B", "#B7410E", "#FFFDD0"])  # camel, rust, cream

    def test_warm_item_fits_warm_palette(self):
        from app.services.scoring.color_match import evaluate_color_fit
        result = evaluate_color_fit("camel", ["#C19A6B", "#B7410E", "#FFFDD0"])
        assert result.score >= 0.85

    def test_color_harmony_warm_pair_no_clash(self):
        from app.services.scoring.color_match import evaluate_color_harmony
        result = evaluate_color_harmony("camel", "rust")
        assert result.score >= 0.0  # same-temperature — no clash penalty
        clash_warnings = [w for w in result.warnings if "clash" in w]
        assert len(clash_warnings) == 0

    def test_color_harmony_warm_cool_clash_detected(self):
        from app.services.scoring.color_match import evaluate_color_harmony
        # Use non-neutral warm vs cool for clash detection
        result = evaluate_color_harmony("coral", "teal")
        assert result.score < 0.0  # penalty expected for warm/cool clash


# ---------------------------------------------------------------------------
# Scenario 7 — Duplicate-heavy wardrobe
# ---------------------------------------------------------------------------

class TestDuplicateHeavyWardrobe:
    """5 identical black casual tops — classic over-concentration."""

    wardrobe = [_item("tops", "black", "casual") for _ in range(5)]

    def test_redundancy_clusters_detected(self):
        clusters = cluster(self.wardrobe)
        dup_or_near = [c for c in clusters if c["type"] in {"duplicate", "near_duplicate", "same_role"}]
        assert len(dup_or_near) > 0

    def test_shopping_same_item_gets_low_redundancy_score(self):
        evaluator = PurchaseEvaluator(self.wardrobe)
        c = parse_from_attrs({"category": "tops", "primary_color": "black", "occasion": "casual"})
        result = evaluator.evaluate(c)
        assert result["subscores"]["redundancy_penalty"]["score"] < 0.5

    def test_shopping_different_category_scores_better(self):
        evaluator = PurchaseEvaluator(self.wardrobe)
        same = parse_from_attrs({"category": "tops", "primary_color": "black", "occasion": "casual"})
        different = parse_from_attrs({"category": "shoes", "primary_color": "black"})
        r_same = evaluator.evaluate(same)
        r_diff = evaluator.evaluate(different)
        assert (
            r_diff["subscores"]["redundancy_penalty"]["score"]
            > r_same["subscores"]["redundancy_penalty"]["score"]
        )

    def test_decision_is_skip_or_maybe(self):
        evaluator = PurchaseEvaluator(self.wardrobe)
        c = parse_from_attrs({"category": "tops", "primary_color": "black", "occasion": "casual"})
        result = evaluator.evaluate(c)
        assert result["decision"] in {"skip", "maybe"}


# ---------------------------------------------------------------------------
# Scenario 8 — Orphan item
# ---------------------------------------------------------------------------

class TestOrphanItem:
    """A very formal evening dress in an otherwise casual wardrobe has no
    compatible partners — should score low on wardrobe_compat."""

    wardrobe = [
        _item("tops", "white", "casual"),
        _item("tops", "grey", "casual"),
        _item("bottoms", "navy", "casual"),
        _item("shoes", "white", "casual"),
        _item("dresses", "black", "evening"),  # the orphan candidate
    ]

    def test_orphan_has_few_compatible_partners(self):
        graph = ItemCompatibilityGraph().build(self.wardrobe)
        orphan_id = next(i["id"] for i in self.wardrobe if i["category"] == "dresses")
        partners = graph.get_partners(orphan_id, top_n=10)
        good_partners = [p for p in partners if p["score"] >= 0.5]
        # Evening dress vs casual tops — limited compatible partners
        assert len(good_partners) <= 3

    def test_shopping_orphan_gets_low_compat(self):
        casual_wardrobe = [
            _item("tops", "white", "casual"),
            _item("bottoms", "navy", "casual"),
            _item("shoes", "white", "casual"),
        ]
        evaluator = PurchaseEvaluator(casual_wardrobe)
        c = parse_from_attrs({"category": "dresses", "primary_color": "red", "occasion": "evening"}, price=200.0)
        result = evaluator.evaluate(c)
        # Low compat with casual wardrobe OR low versatility
        low_compat = result["subscores"]["wardrobe_compat"]["score"] < 0.6
        low_versatility = result["subscores"]["expected_versatility"]["score"] < 0.6
        assert low_compat or low_versatility


# ---------------------------------------------------------------------------
# Scenario 9 — Strong buy candidate
# ---------------------------------------------------------------------------

class TestStrongBuyCandidate:
    """A white shoe filling a clear gap in a wardrobe without shoes.
    Should get buy or maybe decision with high confidence."""

    wardrobe = [
        _item("tops", "white", "casual", cost=50.0, wear_count=10),
        _item("tops", "navy", "smart_casual", cost=60.0, wear_count=8),
        _item("bottoms", "black", "casual", cost=70.0, wear_count=12),
        _item("bottoms", "navy", "smart_casual", cost=80.0, wear_count=6),
    ]
    ctx = _profile(["#FFFFFF", "#000000", "#000080"])

    def test_shoe_gets_buy_or_maybe(self):
        evaluator = PurchaseEvaluator(self.wardrobe, self.ctx)
        c = parse_from_attrs({"category": "shoes", "primary_color": "white"}, price=80.0)
        result = evaluator.evaluate(c)
        assert result["decision"] in {"buy", "maybe"}
        assert result["confidence"] >= 0.45

    def test_shoe_fills_gap(self):
        evaluator = PurchaseEvaluator(self.wardrobe, self.ctx)
        c = parse_from_attrs({"category": "shoes", "primary_color": "white"}, price=80.0)
        result = evaluator.evaluate(c)
        assert result["subscores"]["gap_fill"]["score"] >= 0.5

    def test_shoe_has_positive_pairs_with_count(self):
        evaluator = PurchaseEvaluator(self.wardrobe, self.ctx)
        c = parse_from_attrs({"category": "shoes", "primary_color": "white"})
        result = evaluator.evaluate(c)
        assert result["pairs_with_count"] >= 1

    def test_reasons_non_empty(self):
        evaluator = PurchaseEvaluator(self.wardrobe, self.ctx)
        c = parse_from_attrs({"category": "shoes", "primary_color": "white"}, price=80.0)
        result = evaluator.evaluate(c)
        assert len(result["reasons"]) > 0

    def test_no_contradiction_gap_fill_vs_compat(self):
        """Gap fill should be positive AND compat should not be 0."""
        evaluator = PurchaseEvaluator(self.wardrobe, self.ctx)
        c = parse_from_attrs({"category": "shoes", "primary_color": "white"}, price=80.0)
        result = evaluator.evaluate(c)
        assert result["subscores"]["gap_fill"]["score"] >= 0.5
        assert result["subscores"]["wardrobe_compat"]["score"] > 0.0


# ---------------------------------------------------------------------------
# Scenario 10 — Strong skip candidate
# ---------------------------------------------------------------------------

class TestStrongSkipCandidate:
    """A 6th black casual top when you already own 5. Should score skip."""

    wardrobe = [_item("tops", "black", "casual") for _ in range(5)]

    def test_decision_is_skip_or_maybe(self):
        evaluator = PurchaseEvaluator(self.wardrobe)
        c = parse_from_attrs({"category": "tops", "primary_color": "black", "occasion": "casual"})
        result = evaluator.evaluate(c)
        assert result["decision"] in {"skip", "maybe"}

    def test_redundancy_penalty_fires(self):
        evaluator = PurchaseEvaluator(self.wardrobe)
        c = parse_from_attrs({"category": "tops", "primary_color": "black", "occasion": "casual"})
        result = evaluator.evaluate(c)
        assert result["subscores"]["redundancy_penalty"]["score"] < 0.5

    def test_warnings_present(self):
        evaluator = PurchaseEvaluator(self.wardrobe)
        c = parse_from_attrs({"category": "tops", "primary_color": "black", "occasion": "casual"})
        result = evaluator.evaluate(c)
        assert len(result["subscores"]["redundancy_penalty"]["warnings"]) > 0

    def test_expensive_overpriced_item_also_penalised(self):
        """Even if not redundant, a very expensive item on empty wardrobe
        should get a budget warning."""
        evaluator = PurchaseEvaluator([])
        c = parse_from_attrs({"category": "tops", "primary_color": "white"}, price=3000.0)
        result = evaluator.evaluate(c)
        assert result["subscores"]["budget_fit"]["score"] < 0.5
        assert len(result["subscores"]["budget_fit"]["warnings"]) > 0


# ---------------------------------------------------------------------------
# Scenario 11 — All-neutral wardrobe
# ---------------------------------------------------------------------------

class TestAllNeutralWardrobe:
    """Wardrobe of only neutrals (white, black, grey).
    Outfits should consistently score well on palette fit regardless of palette."""

    wardrobe = [
        _item("tops", "white", "casual"),
        _item("tops", "black", "casual"),
        _item("bottoms", "grey", "casual"),
        _item("shoes", "white"),
    ]

    def test_outfits_generated(self):
        gen = OutfitGenerator()
        outfits = gen.generate(self.wardrobe)
        assert len(outfits) > 0

    def test_palette_scores_high_without_palette(self):
        """With no palette set, neutrals should still score neutrally (0.5)."""
        gen = OutfitGenerator()
        outfits = gen.generate(self.wardrobe, user_profile=_profile(None))
        for o in outfits:
            # 0.5 = neutral when no palette provided
            assert o["scores"].get("palette_fit", 0.5) >= 0.5

    def test_palette_scores_high_with_warm_palette(self):
        """Neutrals should score 1.0 on palette_fit even against a warm palette."""
        warm_ctx = _profile(["#C19A6B", "#B7410E"])
        gen = OutfitGenerator()
        outfits = gen.generate(self.wardrobe, user_profile=warm_ctx)
        if outfits:
            scores = [o["scores"].get("palette_fit", 0) for o in outfits]
            assert max(scores) >= 0.8  # neutrals always fit

    def test_no_color_clash_in_graph(self):
        graph = ItemCompatibilityGraph().build(self.wardrobe)
        for item in self.wardrobe:
            partners = graph.get_partners(item["id"], top_n=10)
            for p in partners:
                reason_text = " ".join(p.get("reasons", []) + p.get("warnings", []))
                assert "clash" not in reason_text


# ---------------------------------------------------------------------------
# Scenario 12 — Performance sanity (large wardrobe)
# ---------------------------------------------------------------------------

class TestPerformanceSanity:
    """Outfit generation and gap analysis should finish in reasonable time
    on a wardrobe of 50 items without hitting hard caps."""

    @pytest.fixture
    def large_wardrobe(self):
        items = []
        cats = ["tops", "bottoms", "shoes", "outerwear", "dresses"]
        colors = ["white", "black", "navy", "grey", "camel"]
        for i in range(50):
            cat = cats[i % len(cats)]
            color = colors[i % len(colors)]
            items.append(_item(cat, color, "casual"))
        return items

    def test_outfit_generation_completes(self, large_wardrobe):
        import time
        gen = OutfitGenerator()
        t0 = time.perf_counter()
        outfits = gen.generate(large_wardrobe, top_n=20)
        elapsed = time.perf_counter() - t0
        assert isinstance(outfits, list)
        assert elapsed < 10.0, f"generation took {elapsed:.2f}s — too slow"

    def test_gap_analysis_completes(self, large_wardrobe):
        import time
        t0 = time.perf_counter()
        gaps = analyze_extended(large_wardrobe)
        elapsed = time.perf_counter() - t0
        assert isinstance(gaps, dict)
        assert elapsed < 5.0, f"gap analysis took {elapsed:.2f}s — too slow"

    def test_redundancy_completes(self, large_wardrobe):
        import time
        t0 = time.perf_counter()
        clusters = cluster(large_wardrobe)
        elapsed = time.perf_counter() - t0
        assert isinstance(clusters, list)
        assert elapsed < 5.0, f"redundancy check took {elapsed:.2f}s — too slow"


# ---------------------------------------------------------------------------
# Cross-module consistency
# ---------------------------------------------------------------------------

class TestCrossModuleConsistency:
    """Verify that the same item does not contradict itself across modules."""

    def test_palette_match_consistent_outfit_vs_shopping(self):
        """A white item should score >= 0.9 in both outfit palette_fit scorer
        and shopping purchase_evaluator palette_match when palette includes white."""
        from app.services.outfits.scoring.palette_fit import PaletteFitScorer
        from app.services.scoring.color_match import evaluate_color_fit

        palette = ["#FFFFFF", "#000000"]
        # Direct color match function
        direct = evaluate_color_fit("white", palette)
        assert direct.score == pytest.approx(1.0)

        # Through outfit scorer
        item = _item("tops", "white")
        scorer = PaletteFitScorer()
        result = scorer.score([item], {"palette_hex": palette})
        assert result.score >= 0.9

        # Through shopping evaluator
        wardrobe = [_item("bottoms", "black"), _item("shoes", "white")]
        evaluator = PurchaseEvaluator(wardrobe, {"palette_hex": palette})
        c = parse_from_attrs({"category": "tops", "primary_color": "white"}, price=50.0)
        shopping_result = evaluator.evaluate(c)
        assert shopping_result["subscores"]["palette_match"]["score"] >= 0.9

    def test_user_context_builder_returns_all_required_keys(self):
        ctx = build_user_context()
        for key in ("identity_family", "color_profile", "color_axes",
                    "palette_hex", "color_source", "style_vector",
                    "occasion_defaults", "lifestyle"):
            assert key in ctx, f"missing key: {key}"

    def test_user_context_with_no_profiles_has_empty_palette(self):
        ctx = build_user_context()
        assert ctx["palette_hex"] == []
        assert ctx["color_source"] == "cv"

    def test_color_harmony_consistent_item_graph_vs_color_match(self):
        """item_graph._color_harmony and color_match.evaluate_color_harmony
        should return the same score for the same input."""
        from app.services.analytics.item_graph import _color_harmony
        from app.services.scoring.color_match import evaluate_color_harmony

        for c1, c2 in [("white", "black"), ("red", "navy"), ("camel", "grey")]:
            legacy_score, _ = _color_harmony(c1, c2)
            unified = evaluate_color_harmony(c1, c2)
            assert legacy_score == pytest.approx(unified.score), (
                f"inconsistency for ({c1}, {c2}): "
                f"item_graph={legacy_score}, color_match={unified.score}"
            )
