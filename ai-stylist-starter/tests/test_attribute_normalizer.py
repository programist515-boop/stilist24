"""Tests for the attribute normalizer (Sprint 1).

Covers:
- legacy flat dict → v2 structured dict conversion
- legacy value mapping (color/pattern/fit)
- source preservation from v2 input dicts
- confidence capping for unknown ontology values
- default fills for missing optional fields
- category-specific defaults (layer_role, occasion)
- neckline/sleeve_length only populated for tops/dresses
- apply_manual_update marks fields as source="manual", confidence=1.0
- normalize does not crash on empty input
- to_legacy_dict returns flat values
"""

import pytest
from app.services.wardrobe.attribute_normalizer import normalize, apply_manual_update, to_legacy_dict


# ── helpers ──────────────────────────────────────────────────────────────── #


def _attr(value, source="cv", confidence=0.7, editable=True):
    return {"value": value, "confidence": confidence, "source": source, "editable": editable}


# ── basic normalization ───────────────────────────────────────────────────── #


def test_normalize_flat_dict_returns_dict():
    result = normalize({"category": "tops", "primary_color": "white", "pattern": "solid"})
    assert isinstance(result, dict)
    assert "primary_color" in result
    assert isinstance(result["primary_color"], dict)


def test_normalize_primary_color_from_flat():
    result = normalize({"primary_color": "white"})
    assert result["primary_color"]["value"] == "white"


def test_normalize_color_legacy_alias():
    result = normalize({"color": "black"})
    assert result["primary_color"]["value"] == "black"


def test_normalize_pattern_from_print_type():
    result = normalize({"print_type": "solid"})
    assert result["pattern"]["value"] == "solid"


def test_normalize_legacy_color_clean_maps_to_white():
    result = normalize({"primary_color": "clean"})
    assert result["primary_color"]["value"] == "white"


def test_normalize_legacy_pattern_patterned_maps_to_print():
    result = normalize({"pattern": "patterned"})
    assert result["pattern"]["value"] == "print"


def test_normalize_legacy_fit_loose_maps_to_relaxed():
    result = normalize({"fit": "loose"})
    assert result["fit"]["value"] == "relaxed"


# ── source tracking ───────────────────────────────────────────────────────── #


def test_normalize_preserves_cv_source_from_v2_dict():
    raw = {"primary_color": _attr("navy", source="cv", confidence=0.85)}
    result = normalize(raw)
    assert result["primary_color"]["source"] == "cv"
    assert result["primary_color"]["confidence"] == 0.85


def test_normalize_flat_string_defaults_to_cv_source():
    result = normalize({"primary_color": "red"})
    assert result["primary_color"]["source"] == "cv"


def test_normalize_missing_field_is_default_source():
    result = normalize({})
    assert result["primary_color"]["source"] == "default"
    assert result["primary_color"]["confidence"] == 0.0


# ── confidence capping for unknown values ─────────────────────────────────── #


def test_normalize_unknown_color_capped_confidence():
    result = normalize({"primary_color": "electric_chartreuse_unknown"})
    assert result["primary_color"]["confidence"] <= 0.5


def test_normalize_known_color_keeps_confidence():
    result = normalize({"primary_color": _attr("navy", confidence=0.9)})
    assert result["primary_color"]["confidence"] == 0.9


# ── category-specific defaults ───────────────────────────────────────────── #


def test_normalize_tops_default_layer_role_base():
    result = normalize({"category": "tops"})
    assert result["layer_role"]["value"] == "base"
    assert result["layer_role"]["source"] == "default"


def test_normalize_outerwear_default_layer_role_outer():
    result = normalize({"category": "outerwear"})
    assert result["layer_role"]["value"] == "outer"


def test_normalize_default_occasion_casual():
    result = normalize({"category": "bottoms"})
    assert result["occasion"]["value"] == "casual"
    assert result["occasion"]["source"] == "default"


def test_normalize_default_seasonality_all_season():
    result = normalize({"category": "tops"})
    assert result["seasonality"]["value"] == "all_season"


# ── neckline/sleeve only for tops/dresses ─────────────────────────────────── #


def test_normalize_neckline_kept_for_tops():
    result = normalize({"category": "tops", "neckline": "v_neck"})
    assert result["neckline"]["value"] == "v_neck"


def test_normalize_neckline_for_bottoms_confidence_capped():
    # Bottoms don't have neckline in ontology, so confidence capped at 0.5
    result = normalize({"category": "bottoms", "neckline": "v_neck"})
    assert result["neckline"]["confidence"] <= 0.5


def test_normalize_sleeve_length_kept_for_dresses():
    result = normalize({"category": "dresses", "sleeve_length": "short"})
    assert result["sleeve_length"]["value"] == "short"


# ── apply_manual_update ───────────────────────────────────────────────────── #


def test_apply_manual_update_sets_source_manual():
    base = normalize({"category": "tops", "primary_color": "white"})
    updated = apply_manual_update(base, {"primary_color": "navy"})
    assert updated["primary_color"]["value"] == "navy"
    assert updated["primary_color"]["source"] == "manual"
    assert updated["primary_color"]["confidence"] == 1.0


def test_apply_manual_update_does_not_mutate_original():
    base = normalize({"category": "tops", "primary_color": "white"})
    _ = apply_manual_update(base, {"primary_color": "navy"})
    assert base["primary_color"]["value"] == "white"


def test_apply_manual_update_unknown_field_ignored():
    base = normalize({"category": "tops"})
    updated = apply_manual_update(base, {"nonexistent_field": "value"})
    assert "nonexistent_field" not in updated
    assert updated["category"]["value"] == base["category"]["value"]


# ── to_legacy_dict ────────────────────────────────────────────────────────── #


def test_to_legacy_dict_returns_flat_values():
    result = normalize({"category": "tops", "primary_color": "white", "pattern": "solid"})
    legacy = to_legacy_dict(result)
    assert legacy["primary_color"] == "white"
    assert legacy["pattern"] == "solid"
    assert legacy["category"] == "tops"


# ── edge cases ────────────────────────────────────────────────────────────── #


def test_normalize_empty_dict_does_not_crash():
    result = normalize({})
    assert isinstance(result, dict)
    assert "primary_color" in result


def test_normalize_all_none_values_does_not_crash():
    result = normalize({"primary_color": None, "pattern": None})
    assert isinstance(result, dict)


def test_normalize_v2_input_preserves_structure():
    v2_input = {
        "category": _attr("bottoms", source="manual", confidence=1.0),
        "primary_color": _attr("navy", source="cv", confidence=0.8),
    }
    result = normalize(v2_input)
    assert result["primary_color"]["value"] == "navy"
    assert result["primary_color"]["source"] == "cv"
    assert result["category"]["value"] == "bottoms"
    assert result["category"]["source"] == "manual"


def test_normalize_returns_all_required_fields():
    result = normalize({"category": "tops"})
    required = [
        "category", "subcategory", "primary_color", "pattern",
        "material", "fit", "silhouette", "neckline", "sleeve_length",
        "occasion", "seasonality", "layer_role",
    ]
    for field in required:
        assert field in result, f"Missing field: {field}"


def test_normalize_each_field_has_v2_structure():
    result = normalize({"category": "tops", "primary_color": "white"})
    for key, val in result.items():
        assert isinstance(val, dict), f"{key} is not a dict"
        assert "value" in val, f"{key} missing 'value'"
        assert "confidence" in val, f"{key} missing 'confidence'"
        assert "source" in val, f"{key} missing 'source'"
        assert "editable" in val, f"{key} missing 'editable'"
