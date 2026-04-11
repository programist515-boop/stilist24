from app.services.scoring_service import ScoringService


CLASSIC_USER = {
    "identity_family": "soft_classic",
    "color_profile": {
        "undertone": "cool",
        "depth": "medium",
        "chroma": "soft",
        "contrast": "low",
    },
    "style_vector": {"classic": 0.6, "minimal": 0.3, "romantic": 0.1},
}


def _classic_top():
    return {
        "category": "top",
        "primary_color": "white",
        "line_type": "balanced",
        "fit": "tailored",
        "structure": "structured",
        "scale": "medium",
        "style_tags": ["classic", "minimal"],
        "occasions": ["work", "smart_casual"],
    }


def _classic_bottom():
    return {
        "category": "bottom",
        "primary_color": "navy",
        "line_type": "balanced",
        "fit": "tailored",
        "structure": "structured",
        "scale": "medium",
        "style_tags": ["classic"],
        "occasions": ["work"],
    }


def _classic_shoes():
    return {
        "category": "shoes",
        "primary_color": "black",
        "line_type": "refined",
        "fit": "polished",
        "structure": "structured",
        "scale": "medium",
        "style_tags": ["classic"],
        "occasions": ["work"],
    }


# ---------------------------------------------------------------- weights spec


def test_item_weights_match_spec():
    w = ScoringService.ITEM_WEIGHTS
    assert w == {
        "color_fit": 0.30,
        "line_fit": 0.30,
        "silhouette_fit": 0.20,
        "style_fit": 0.10,
        "utility_fit": 0.10,
    }
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_outfit_weights_match_spec():
    w = ScoringService.OUTFIT_WEIGHTS
    assert w == {
        "color_harmony": 0.30,
        "silhouette_balance": 0.25,
        "line_consistency": 0.20,
        "style_consistency": 0.15,
        "occasion_fit": 0.10,
    }
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_final_score_uses_spec_weights():
    svc = ScoringService()
    assert svc.final_score(1.0, 0.0, 0.0) == 0.45
    assert svc.final_score(0.0, 1.0, 0.0) == 0.35
    assert svc.final_score(0.0, 0.0, 1.0) == 0.20
    assert svc.final_score(1.0, 1.0, 1.0) == 1.0


# ----------------------------------------------------------------- item shape


def test_score_item_returns_full_breakdown():
    svc = ScoringService()
    result = svc.score_item(_classic_top(), CLASSIC_USER)
    assert set(result.keys()) == {"score", "sub_scores", "explanation"}
    assert set(result["sub_scores"].keys()) == set(ScoringService.ITEM_WEIGHTS.keys())
    assert 0.0 <= result["score"] <= 1.0
    assert isinstance(result["explanation"], list)
    assert all(isinstance(line, str) for line in result["explanation"])


def test_score_item_is_deterministic():
    svc = ScoringService()
    a = svc.score_item(_classic_top(), CLASSIC_USER)
    b = svc.score_item(_classic_top(), CLASSIC_USER)
    assert a == b


def test_score_item_handles_missing_user_context():
    svc = ScoringService()
    result = svc.score_item(_classic_top(), None)
    # Every sub-score must still be present and bounded.
    assert set(result["sub_scores"].keys()) == set(ScoringService.ITEM_WEIGHTS.keys())
    assert 0.0 <= result["score"] <= 1.0


def test_neutral_color_beats_unknown_color():
    svc = ScoringService()
    good = {"primary_color": "white"}
    bad = {"primary_color": "neon_orange"}
    g = svc.score_item(good, CLASSIC_USER)["sub_scores"]["color_fit"]
    b = svc.score_item(bad, CLASSIC_USER)["sub_scores"]["color_fit"]
    assert g > b


def test_color_axes_match_beats_partial():
    svc = ScoringService()
    full_match = {
        "color_axes": {
            "undertone": "cool",
            "depth": "medium",
            "chroma": "soft",
            "contrast": "low",
        }
    }
    partial = {
        "color_axes": {
            "undertone": "warm",
            "depth": "medium",
            "chroma": "bright",
            "contrast": "high",
        }
    }
    s_full = svc.score_item(full_match, CLASSIC_USER)["sub_scores"]["color_fit"]
    s_part = svc.score_item(partial, CLASSIC_USER)["sub_scores"]["color_fit"]
    assert s_full == 1.0
    assert s_full > s_part


def test_line_fit_uses_yaml_for_family():
    svc = ScoringService()
    # 'soft' is in the romantic 'prefer.line_type' list
    romantic_user = {**CLASSIC_USER, "identity_family": "romantic"}
    item = {"line_type": "soft", "style_tags": ["romantic"]}
    s_romantic = svc.score_item(item, romantic_user)["sub_scores"]["line_fit"]
    # 'soft' is not in dramatic.prefer; 'severe' is in romantic.avoid — pick a value
    # that's avoided by dramatic to make the contrast obvious.
    dramatic_user = {**CLASSIC_USER, "identity_family": "dramatic"}
    item_bad = {"line_type": "fussy", "style_tags": ["romantic"]}
    s_dramatic_bad = svc.score_item(item_bad, dramatic_user)["sub_scores"]["line_fit"]
    assert s_romantic > s_dramatic_bad


def test_silhouette_fit_responds_to_avoided_axis():
    svc = ScoringService()
    # classic 'avoid.fit' contains 'oversized'
    item = {"fit": "oversized", "structure": "moderate", "scale": "medium"}
    res = svc.score_item(item, CLASSIC_USER)
    assert res["sub_scores"]["silhouette_fit"] < 0.7
    assert any("oversized" in line for line in res["explanation"])


def test_style_fit_uses_personalization_vector():
    svc = ScoringService()
    aligned = {"style_tags": ["classic"]}
    misaligned = {"style_tags": ["streetwear"]}
    s_aligned = svc.score_item(aligned, CLASSIC_USER)["sub_scores"]["style_fit"]
    s_miss = svc.score_item(misaligned, CLASSIC_USER)["sub_scores"]["style_fit"]
    assert s_aligned > s_miss


def test_utility_fit_uses_occasion():
    svc = ScoringService()
    item = {"occasions": ["work", "smart_casual"]}
    ctx_match = {**CLASSIC_USER, "occasion": "work"}
    ctx_miss = {**CLASSIC_USER, "occasion": "beach"}
    s_match = svc.score_item(item, ctx_match)["sub_scores"]["utility_fit"]
    s_miss = svc.score_item(item, ctx_miss)["sub_scores"]["utility_fit"]
    assert s_match == 1.0
    assert s_miss == 0.0


# --------------------------------------------------------------- outfit shape


def test_score_outfit_returns_full_breakdown():
    svc = ScoringService()
    result = svc.score_outfit(
        [_classic_top(), _classic_bottom(), _classic_shoes()],
        {**CLASSIC_USER, "occasion": "work"},
    )
    assert set(result.keys()) == {"score", "sub_scores", "explanation"}
    assert set(result["sub_scores"].keys()) == set(ScoringService.OUTFIT_WEIGHTS.keys())
    assert 0.0 <= result["score"] <= 1.0
    assert isinstance(result["explanation"], list)


def test_outfit_occasion_match_beats_mismatch():
    svc = ScoringService()
    items = [_classic_top(), _classic_bottom(), _classic_shoes()]
    s_match = svc.score_outfit(items, {**CLASSIC_USER, "occasion": "work"})
    s_miss = svc.score_outfit(items, {**CLASSIC_USER, "occasion": "beach"})
    assert s_match["sub_scores"]["occasion_fit"] > s_miss["sub_scores"]["occasion_fit"]


def test_outfit_line_consistency_strong_when_all_same():
    svc = ScoringService()
    items = [
        {"line_type": "balanced"},
        {"line_type": "balanced"},
        {"line_type": "balanced"},
    ]
    res = svc.score_outfit(items, CLASSIC_USER)
    # 1.0 base + line_consistency_strong bonus is clamped to 1.0
    assert res["sub_scores"]["line_consistency"] == 1.0


def test_outfit_score_is_deterministic():
    svc = ScoringService()
    items = [_classic_top(), _classic_bottom(), _classic_shoes()]
    ctx = {**CLASSIC_USER, "occasion": "work"}
    assert svc.score_outfit(items, ctx) == svc.score_outfit(items, ctx)


def test_color_harmony_bonus_for_one_accent_plus_neutrals():
    svc = ScoringService()
    items = [
        {"primary_color": "white"},
        {"primary_color": "beige"},
        {"primary_color": "burgundy"},  # the single non-neutral
    ]
    bonus_res = svc.score_outfit(items, CLASSIC_USER)
    no_bonus_items = [
        {"primary_color": "burgundy"},
        {"primary_color": "burgundy"},
        {"primary_color": "burgundy"},
    ]
    no_bonus_res = svc.score_outfit(no_bonus_items, CLASSIC_USER)
    assert bonus_res["sub_scores"]["color_harmony"] > no_bonus_res["sub_scores"]["color_harmony"]
    assert any("bonus" in line for line in bonus_res["explanation"])
