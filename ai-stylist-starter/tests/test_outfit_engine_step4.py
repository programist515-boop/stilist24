from app.services.outfit_engine import (
    ACCESSORY_LIKE,
    OUTFIT_TEMPLATES,
    OutfitEngine,
)
from app.services.scoring_service import ScoringService


CLASSIC_USER = {
    "identity_family": "classic",
    "color_profile": {
        "undertone": "cool",
        "depth": "medium",
        "chroma": "soft",
        "contrast": "low",
    },
    "style_vector": {"classic": 0.6, "minimal": 0.3},
}


def _item(
    item_id: str,
    category: str,
    **overrides,
) -> dict:
    base = {
        "id": item_id,
        "category": category,
        "primary_color": "white",
        "line_type": "balanced",
        "fit": "tailored",
        "structure": "structured",
        "scale": "medium",
        "style_tags": ["classic"],
        "formality": "smart_casual",
        "season": ["spring", "summer", "autumn"],
        "occasions": ["work", "smart_casual"],
        "statement": False,
        "detail_density": "medium",
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------ templates


def test_multiple_templates_are_generated():
    engine = OutfitEngine()
    items = [
        _item("t1", "top"),
        _item("b1", "bottom"),
        _item("s1", "shoes"),
        _item("d1", "dress"),
    ]
    outfits = engine.generate(items, CLASSIC_USER)
    templates_used = {o["generation"]["template"] for o in outfits}
    assert "top_bottom_shoes" in templates_used
    assert "dress_shoes" in templates_used


def test_dress_shoes_template_works_without_bottom():
    engine = OutfitEngine()
    items = [_item("d1", "dress"), _item("s1", "shoes")]
    outfits = engine.generate(items, CLASSIC_USER)
    assert len(outfits) >= 1
    templates = {o["generation"]["template"] for o in outfits}
    assert templates <= {
        "dress_shoes",
        "dress_shoes_accessory",
        "dress_shoes_outerwear",
    }
    assert "dress_shoes" in templates


def test_outerwear_optional_template():
    engine = OutfitEngine()
    items = [
        _item("t1", "top"),
        _item("b1", "bottom"),
        _item("s1", "shoes"),
        _item("o1", "outerwear"),
    ]
    outfits = engine.generate(items, CLASSIC_USER)
    templates = {o["generation"]["template"] for o in outfits}
    assert "top_bottom_shoes_outerwear" in templates
    assert any("outerwear" in o["breakdown"] for o in outfits)


# -------------------------------------------- accessory-like normalization (#1)


def test_accessory_like_categories_unified():
    """bag / jewelry / hat share the single accessory-like bucket."""
    engine = OutfitEngine()
    items = [
        _item("t1", "top"),
        _item("b1", "bottom"),
        _item("s1", "shoes"),
        _item("bag1", "bag"),
        _item("j1", "jewelry"),
        _item("h1", "hat"),
    ]
    outfits = engine.generate(items, CLASSIC_USER)
    # 1 base (top_bottom_shoes) + 3 accessory-like extensions = 4 candidates
    assert engine.last_stats["total_candidates"] == 4
    assert engine.last_stats["accepted_for_scoring"] == 4
    # At least one surviving outfit uses one of the accessory-like raw cats.
    assert any(
        any(cat in ACCESSORY_LIKE for cat in o["breakdown"])
        for o in outfits
    )


def test_accessory_like_multiple_items_may_stack():
    """Two accessory-like items from different raw categories must not
    trip the duplicate-category filter (they belong to one bucket)."""
    engine = OutfitEngine()
    # Synthesize a candidate directly through the filter.
    items = [
        _item("t1", "top"),
        _item("b1", "bottom"),
        _item("s1", "shoes"),
        _item("bag1", "bag"),
        _item("h1", "hat"),
    ]
    ok, reasons = engine._filter_candidate(items, {})
    assert ok, reasons


# ---------------------------------------------------------------- filters (#2/#3)


def test_formality_conflict_filtered_out():
    engine = OutfitEngine()
    items = [
        _item("t1", "top", formality="very_casual"),
        _item("b1", "bottom", formality="formal"),
        _item("s1", "shoes", formality="formal"),
    ]
    outfits = engine.generate(items, CLASSIC_USER)
    assert outfits == []
    assert any(
        any("formality span" in r for r in rej["reasons"])
        for rej in engine.last_rejections
    )


def test_season_explicit_conflict_filtered_out():
    """Two items with explicit non-overlapping season tags → rejected."""
    engine = OutfitEngine()
    items = [
        _item("t1", "top", season=["winter"]),
        _item("b1", "bottom", season=["summer"]),
        _item("s1", "shoes", season=["summer"]),
    ]
    outfits = engine.generate(items, CLASSIC_USER)
    assert outfits == []
    assert any(
        any("season" in r for r in rej["reasons"])
        for rej in engine.last_rejections
    )


def test_season_missing_metadata_does_not_reject():
    """Adjustment #2: missing or partial season metadata must not reject."""
    engine = OutfitEngine()
    items = [
        _item("t1", "top", season=[]),  # no season tags at all
        _item("b1", "bottom", season=["summer"]),
        _item("s1", "shoes", season=[]),
    ]
    outfits = engine.generate(items, CLASSIC_USER)
    assert outfits, "soft season filter should not reject on missing metadata"


def test_season_single_tagged_item_does_not_reject():
    """Only one item with explicit tags → no conflict possible."""
    engine = OutfitEngine()
    items = [
        _item("t1", "top", season=["winter"]),
        _item("b1", "bottom", season=[]),
        _item("s1", "shoes", season=[]),
    ]
    outfits = engine.generate(items, CLASSIC_USER)
    assert outfits


def test_occasion_hard_filter_explicit_mismatch():
    engine = OutfitEngine()
    items = [
        _item("t1", "top", occasions=["beach"]),
        _item("b1", "bottom", occasions=["work"]),
        _item("s1", "shoes", occasions=["work"]),
    ]
    outfits = engine.generate(items, CLASSIC_USER, occasion="work")
    assert outfits == []
    assert any(
        any("occasion" in r for r in rej["reasons"])
        for rej in engine.last_rejections
    )


def test_occasion_missing_metadata_does_not_reject():
    """Adjustment #3: items without explicit occasions must not reject."""
    engine = OutfitEngine()
    items = [
        _item("t1", "top", occasions=[]),
        _item("b1", "bottom", occasions=["work"]),
        _item("s1", "shoes", occasions=[]),
    ]
    outfits = engine.generate(items, CLASSIC_USER, occasion="work")
    assert outfits, "soft occasion filter should not reject on missing metadata"


def test_broken_line_combination_filtered_out():
    engine = OutfitEngine()
    items = [
        _item("t1", "top", line_type="sharp"),
        _item("b1", "bottom", line_type="fussy"),
        _item("s1", "shoes", line_type="clean"),
    ]
    outfits = engine.generate(items, CLASSIC_USER)
    assert outfits == []
    assert any(
        any("line_type" in r for r in rej["reasons"])
        for rej in engine.last_rejections
    )


def test_too_many_statement_pieces_filtered_out():
    engine = OutfitEngine()
    items = [
        _item("t1", "top", statement=True),
        _item("b1", "bottom", statement=True),
        _item("s1", "shoes"),
    ]
    outfits = engine.generate(items, CLASSIC_USER)
    assert outfits == []
    assert any(
        any("statement pieces" in r for r in rej["reasons"])
        for rej in engine.last_rejections
    )


# ---------------------------------------------------------------- diversity (#4)


def test_diversity_removes_same_base_duplicates():
    """Accessory-only variants of the same base collapse via the semantic
    ``(template, (category, id)...)`` signature."""
    engine = OutfitEngine()
    items = [
        _item("t1", "top"),
        _item("b1", "bottom"),
        _item("s1", "shoes"),
        _item("a1", "accessory"),
        _item("a2", "accessory"),
        _item("a3", "accessory"),
    ]
    outfits = engine.generate(items, CLASSIC_USER)
    sigs = {OutfitEngine._base_signature(o) for o in outfits}
    # Each surviving outfit has a unique signature.
    assert len(sigs) == len(outfits)


def test_base_signature_uses_category_id_pairs():
    engine = OutfitEngine()
    items = [
        _item("t1", "top"),
        _item("b1", "bottom"),
        _item("s1", "shoes"),
    ]
    outfits = engine.generate(items, CLASSIC_USER)
    assert outfits
    template, pairs = OutfitEngine._base_signature(outfits[0])
    assert template == "top_bottom_shoes"
    assert pairs == (("bottom", "b1"), ("shoes", "s1"), ("top", "t1"))


def test_diversity_coverage_prefers_new_items():
    engine = OutfitEngine()
    items = [
        _item("t1", "top"),
        _item("t2", "top"),
        _item("b1", "bottom"),
        _item("b2", "bottom"),
        _item("s1", "shoes"),
    ]
    outfits = engine.generate(items, CLASSIC_USER, top_n=4)
    seen: set[str] = set()
    for o in outfits:
        for it in o["items"]:
            seen.add(str(it["id"]))
    assert seen >= {"t1", "t2", "b1", "b2", "s1"}


# ----------------------------------------------------------- determinism + shape


def test_stable_deterministic_ordering():
    items = [
        _item("t1", "top"),
        _item("t2", "top"),
        _item("b1", "bottom"),
        _item("b2", "bottom"),
        _item("s1", "shoes"),
        _item("a1", "accessory"),
    ]
    first = OutfitEngine().generate(items, CLASSIC_USER)
    second = OutfitEngine().generate(items, CLASSIC_USER)
    first_sig = [
        (o["generation"]["template"], [str(it["id"]) for it in o["items"]])
        for o in first
    ]
    second_sig = [
        (o["generation"]["template"], [str(it["id"]) for it in o["items"]])
        for o in second
    ]
    assert first_sig == second_sig


def test_score_structure_preserved():
    engine = OutfitEngine()
    items = [_item("t1", "top"), _item("b1", "bottom"), _item("s1", "shoes")]
    outfits = engine.generate(items, CLASSIC_USER)
    assert outfits
    expected_subs = set(ScoringService.OUTFIT_WEIGHTS.keys())
    for o in outfits:
        assert "overall" in o["scores"]
        assert expected_subs <= set(o["scores"].keys())
        assert 0.0 <= o["scores"]["overall"] <= 1.0


def test_generation_metadata_present():
    engine = OutfitEngine()
    items = [
        _item("t1", "top"),
        _item("b1", "bottom"),
        _item("s1", "shoes"),
        _item("a1", "accessory"),
    ]
    outfits = engine.generate(items, CLASSIC_USER)
    assert outfits
    template_names = {t["name"] for t in OUTFIT_TEMPLATES}
    for o in outfits:
        gen = o["generation"]
        assert gen["template"] in template_names
        assert "optional_used" in gen
        assert o["breakdown"]  # non-empty


def test_top_n_respected():
    engine = OutfitEngine()
    items = (
        [_item(f"t{i}", "top") for i in range(3)]
        + [_item(f"b{i}", "bottom") for i in range(3)]
        + [_item(f"s{i}", "shoes") for i in range(3)]
    )
    outfits = engine.generate(items, CLASSIC_USER, top_n=3)
    assert len(outfits) == 3


# ------------------------------------------- structured explanations (#5)


def test_structured_explanations_present():
    """Adjustment #5: ``filter_pass_reasons`` and ``scoring_reasons`` are
    kept as separate fields, plus a flat ``explanation`` for convenience."""
    engine = OutfitEngine()
    items = [_item("t1", "top"), _item("b1", "bottom"), _item("s1", "shoes")]
    outfits = engine.generate(items, CLASSIC_USER)
    assert outfits
    for o in outfits:
        assert isinstance(o["filter_pass_reasons"], list)
        assert isinstance(o["scoring_reasons"], list)
        assert o["filter_pass_reasons"]
        assert o["scoring_reasons"]
        # Flat convenience view is the concatenation.
        assert o["explanation"] == o["filter_pass_reasons"] + o["scoring_reasons"]
        assert any("filter: passed" in line for line in o["filter_pass_reasons"])


# ---------------------------------------------------- safety caps (#6)


def test_max_total_candidates_cap_enforced():
    class CappedEngine(OutfitEngine):
        MAX_TOTAL_CANDIDATES = 5

    engine = CappedEngine()
    items = (
        [_item(f"t{i}", "top") for i in range(10)]
        + [_item(f"b{i}", "bottom") for i in range(10)]
        + [_item(f"s{i}", "shoes") for i in range(10)]
    )
    engine.generate(items, CLASSIC_USER)
    assert engine.last_stats["total_candidates"] <= 5
    assert "MAX_TOTAL_CANDIDATES" in engine.last_stats["caps_hit"]


def test_max_accepted_candidates_cap_enforced():
    class CappedEngine(OutfitEngine):
        MAX_ACCEPTED_CANDIDATES_FOR_SCORING = 3

    engine = CappedEngine()
    items = (
        [_item(f"t{i}", "top") for i in range(5)]
        + [_item(f"b{i}", "bottom") for i in range(5)]
        + [_item(f"s{i}", "shoes") for i in range(5)]
    )
    engine.generate(items, CLASSIC_USER)
    assert engine.last_stats["accepted_for_scoring"] <= 3
    assert "MAX_ACCEPTED_CANDIDATES_FOR_SCORING" in engine.last_stats["caps_hit"]


def test_default_cap_constants_are_positive():
    assert OutfitEngine.MAX_TOTAL_CANDIDATES > 0
    assert OutfitEngine.MAX_ACCEPTED_CANDIDATES_FOR_SCORING > 0
    assert OutfitEngine.MAX_CANDIDATES_PER_TEMPLATE > 0


def test_last_stats_summary_populated():
    engine = OutfitEngine()
    items = [_item("t1", "top"), _item("b1", "bottom"), _item("s1", "shoes")]
    engine.generate(items, CLASSIC_USER)
    stats = engine.last_stats
    assert stats["total_candidates"] >= 1
    assert stats["accepted_for_scoring"] >= 1
    assert stats["rejected"] == 0
    assert stats["returned"] >= 1
    assert stats["caps_hit"] == []
