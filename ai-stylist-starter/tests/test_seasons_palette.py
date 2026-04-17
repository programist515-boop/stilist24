"""Validates seasons_palette.yaml: all 12 seasons present, groups non-empty, valid hex."""
import re

import pytest

from app.services.rules_loader import load_rules

EXPECTED_SEASONS = {
    "light_spring", "true_spring", "bright_spring",
    "light_summer", "true_summer", "soft_summer",
    "soft_autumn", "true_autumn", "deep_autumn",
    "deep_winter", "true_winter", "bright_winter",
}
EXPECTED_GROUPS = ("best_neutrals", "accent_colors", "metals")
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


@pytest.fixture(autouse=True)
def clear_rules_cache():
    load_rules.cache_clear()
    yield
    load_rules.cache_clear()


def _palette() -> dict:
    return load_rules()["seasons_palette"]["seasons_palette"]


def test_all_12_seasons_present():
    assert set(_palette().keys()) == EXPECTED_SEASONS


def test_groups_non_empty():
    for season, groups in _palette().items():
        for group in EXPECTED_GROUPS:
            assert groups.get(group), f"{season}.{group} is empty or missing"


def test_all_hex_valid():
    for season, groups in _palette().items():
        for group in EXPECTED_GROUPS:
            for hex_str in groups.get(group, []):
                assert HEX_RE.match(hex_str), (
                    f"{season}.{group}: invalid hex '{hex_str}'"
                )


def test_get_palette_returns_all_groups():
    from app.services.color_engine import ColorEngine
    engine = ColorEngine()
    for season in EXPECTED_SEASONS:
        palette = engine.get_palette(season)
        for group in EXPECTED_GROUPS:
            assert palette[group], f"get_palette('{season}').{group} empty"


def test_get_palette_unknown_season_returns_empty_lists():
    from app.services.color_engine import ColorEngine
    palette = ColorEngine().get_palette("nonexistent_season")
    # all groups (including new avoid_colors / canonical_colors) should be empty lists
    assert palette["best_neutrals"] == []
    assert palette["accent_colors"] == []
    assert palette["metals"] == []
    assert palette["avoid_colors"] == []
    assert palette["canonical_colors"] == []


def test_analyze_includes_palette():
    from app.services.color_engine import ColorEngine
    profile = {"undertone": "warm", "depth": "light", "chroma": "bright", "contrast": "medium"}
    result = ColorEngine().analyze(profile)
    assert "palette" in result
    assert result["palette"]["best_neutrals"]
    assert result["palette"]["accent_colors"]
    assert result["palette"]["metals"]
