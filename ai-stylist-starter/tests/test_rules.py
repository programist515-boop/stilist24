from app.services.identity_engine import IdentityEngine
from app.services.color_engine import ColorEngine


def test_identity_engine_returns_main_type():
    features = {
        "vertical_line": 0.42,
        "compactness": 0.71,
        "width": 0.40,
        "bone_sharpness": 0.31,
        "bone_bluntness": 0.22,
        "softness": 0.74,
        "curve_presence": 0.69,
        "symmetry": 0.44,
        "facial_sharpness": 0.28,
        "facial_roundness": 0.67,
        "waist_definition": 0.73,
        "narrowness": 0.40,
        "relaxed_line": 0.20,
        "proportion_balance": 0.45,
        "moderation": 0.40,
        "line_contrast": 0.61,
        "small_scale": 0.66,
        "feature_juxtaposition": 0.58,
        "controlled_softness_or_sharpness": 0.33,
        "low_line_contrast": 0.39,
    }
    result = IdentityEngine().analyze(features)
    assert "main_type" in result
    assert "confidence" in result


def test_color_engine_returns_season():
    result = ColorEngine().analyze({
        "undertone": "cool-neutral",
        "contrast": "medium-low",
        "depth": "medium",
        "chroma": "soft",
    })
    assert "season_top_1" in result
