"""Schema tests for ``WardrobeCategoryPatchIn`` after the 6→15 enum widening.

The schema is the gateway for both fresh PATCH requests and legacy PWA
caches that may still send the old 6-value enum (top, bottom, ...). The
former must pass through; the latter must auto-map to the closest
detailed category. Anything else must raise — we don't want silent
storage of unknown categories.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic")

from pydantic import ValidationError  # noqa: E402

from app.schemas.wardrobe import WardrobeCategoryPatchIn  # noqa: E402
from app.services.categories import WARDROBE_CATEGORIES  # noqa: E402


class TestDetailedCategories:
    @pytest.mark.parametrize("category", WARDROBE_CATEGORIES)
    def test_accepts_every_detailed_category(self, category: str):
        model = WardrobeCategoryPatchIn(category=category)
        assert model.category == category


class TestLegacyMapping:
    """Old PWA caches send legacy values — auto-map them so the user
    doesn't see a 422 after we widen the enum."""

    def test_top_maps_to_blouses(self):
        assert WardrobeCategoryPatchIn(category="top").category == "blouses"

    def test_bottom_maps_to_pants(self):
        assert WardrobeCategoryPatchIn(category="bottom").category == "pants"

    def test_dress_maps_to_dresses(self):
        assert WardrobeCategoryPatchIn(category="dress").category == "dresses"

    def test_outerwear_stays_outerwear(self):
        # Legacy "outerwear" matches a detailed name 1:1 — happily passes
        # through the detailed branch without triggering legacy mapping.
        assert WardrobeCategoryPatchIn(category="outerwear").category == "outerwear"

    def test_shoes_stays_shoes(self):
        assert WardrobeCategoryPatchIn(category="shoes").category == "shoes"

    def test_accessory_raises_because_no_safe_mapping(self):
        """`accessory` covers bags/belts/eyewear/headwear/jewelry — picking
        one would silently throw away information. Force the user to
        choose explicitly."""
        with pytest.raises(ValidationError):
            WardrobeCategoryPatchIn(category="accessory")


class TestRejection:
    def test_rejects_unknown_category(self):
        with pytest.raises(ValidationError):
            WardrobeCategoryPatchIn(category="zorblax")

    def test_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            WardrobeCategoryPatchIn(category="")

    def test_rejects_extra_fields(self):
        # extra="forbid" — unknown fields must be rejected, not silently
        # stripped, so frontend bugs surface early.
        with pytest.raises(ValidationError):
            WardrobeCategoryPatchIn(category="blouses", confidence=0.9)  # type: ignore[call-arg]
