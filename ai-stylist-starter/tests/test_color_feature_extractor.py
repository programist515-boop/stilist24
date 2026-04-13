"""Tests for photo-based color feature extractor.

Tests are organised in four groups:

1. Unit tests for colour-space conversion and outlier filtering.
2. Unit tests for the four axis-mapping functions with synthetic Lab values.
3. Unit tests for ROI extraction helpers with synthetic images.
4. Integration tests verifying that blank / corrupt images raise
   ``ColorExtractionFailedError`` and that the module entry point works.
"""

from __future__ import annotations

import io
import math
import uuid

import numpy as np
import pytest
from PIL import Image

from app.services.color_feature_extractor import (
    ColorExtractionFailedError,
    ColorFeatureExtractor,
    _compute_roi_stats,
    _extract_patch,
    _filter_outliers,
    _map_chroma,
    _map_contrast,
    _map_depth,
    _map_undertone,
    _rgb_to_lab,
    color_feature_extractor,
)
from app.services.feature_extractor import PhotoReference


# ---------------------------------------------------------------- helpers


def _make_jpeg(
    w: int = 320, h: int = 480, color: tuple = (128, 128, 128),
) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _ref(slot: str) -> PhotoReference:
    pid = uuid.uuid4()
    return PhotoReference(
        slot=slot,
        image_key=f"users/x/photos/{slot}/{pid}.jpg",
        image_url=f"memory://users/x/photos/{slot}/{pid}.jpg",
        photo_id=pid,
    )


def _make_pixels(color_rgb: tuple, n: int = 100) -> np.ndarray:
    """Create an (N, 3) array of identical pixels."""
    return np.array([list(color_rgb)] * n, dtype=np.uint8)


# ================================================================ unit: _rgb_to_lab


class TestRgbToLab:
    def test_white(self) -> None:
        px = _make_pixels((255, 255, 255), 10)
        lab = _rgb_to_lab(px)
        assert lab.shape == (10, 3)
        assert lab[0, 0] > 95  # L* near 100

    def test_black(self) -> None:
        px = _make_pixels((0, 0, 0), 10)
        lab = _rgb_to_lab(px)
        assert lab[0, 0] < 5  # L* near 0

    def test_warm_skin_has_positive_b(self) -> None:
        """Warm/golden skin should have positive b* (yellow)."""
        px = _make_pixels((210, 170, 130), 10)
        lab = _rgb_to_lab(px)
        assert lab[0, 2] > 10  # b* > 10 (yellow)

    def test_cool_skin_has_lower_warmth(self) -> None:
        """Cool/pinkish skin should have lower b* relative to a*."""
        px = _make_pixels((200, 170, 175), 10)
        lab = _rgb_to_lab(px)
        assert lab[0, 2] < lab[0, 1]  # b* < a*

    def test_output_shape_matches_input(self) -> None:
        px = _make_pixels((100, 150, 200), 50)
        lab = _rgb_to_lab(px)
        assert lab.shape == (50, 3)


# ================================================================ unit: _filter_outliers


class TestFilterOutliers:
    def test_removes_extremes(self) -> None:
        mid = np.column_stack([
            np.full(100, 50.0), np.full(100, 5.0), np.full(100, 10.0),
        ])
        low = np.column_stack([
            np.full(5, 2.0), np.full(5, 5.0), np.full(5, 10.0),
        ])
        high = np.column_stack([
            np.full(5, 98.0), np.full(5, 5.0), np.full(5, 10.0),
        ])
        lab = np.vstack([mid, low, high])
        filtered = _filter_outliers(lab)
        assert len(filtered) < len(lab)

    def test_small_array_unchanged(self) -> None:
        lab = np.array([[50.0, 5.0, 10.0]] * 5)
        filtered = _filter_outliers(lab)
        assert len(filtered) == 5


# ================================================================ unit: _compute_roi_stats


class TestComputeRoiStats:
    def test_uniform_pixels(self) -> None:
        px = _make_pixels((200, 160, 120), 50)
        stats = _compute_roi_stats(px)
        assert stats is not None
        assert all(k in stats for k in ("L", "a", "b", "chroma"))
        assert stats["L"] > 0
        assert stats["chroma"] > 0

    def test_none_input(self) -> None:
        assert _compute_roi_stats(None) is None

    def test_too_few_pixels(self) -> None:
        px = _make_pixels((200, 160, 120), 3)
        assert _compute_roi_stats(px) is None

    def test_chroma_computation(self) -> None:
        px = _make_pixels((200, 160, 120), 50)
        stats = _compute_roi_stats(px)
        assert stats is not None
        expected = math.sqrt(stats["a"] ** 2 + stats["b"] ** 2)
        assert abs(stats["chroma"] - expected) < 0.01


# ================================================================ unit: _extract_patch


class TestExtractPatch:
    def test_valid_patch(self) -> None:
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[40:60, 40:60] = 255
        patch = _extract_patch(img, 50, 50, 10)
        assert patch is not None
        assert len(patch) > 0

    def test_edge_clipping(self) -> None:
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        patch = _extract_patch(img, 0, 0, 10)
        assert patch is not None

    def test_too_small(self) -> None:
        img = np.zeros((5, 5, 3), dtype=np.uint8)
        assert _extract_patch(img, 0, 0, 1) is None


# ================================================================ unit: mapping functions


class TestMapUndertone:
    def test_warm(self) -> None:
        # High b*, moderate a* → warm
        stats = {"L": 65.0, "a": 12.0, "b": 25.0, "chroma": 27.7}
        assert _map_undertone(stats) == "warm"

    def test_cool(self) -> None:
        # High a*, low b* → cool
        stats = {"L": 65.0, "a": 15.0, "b": 2.0, "chroma": 15.1}
        assert _map_undertone(stats) == "cool"

    def test_neutral_warm(self) -> None:
        stats = {"L": 65.0, "a": 10.0, "b": 12.0, "chroma": 15.6}
        assert _map_undertone(stats) == "neutral-warm"

    def test_cool_neutral(self) -> None:
        stats = {"L": 65.0, "a": 12.0, "b": 5.0, "chroma": 13.0}
        assert _map_undertone(stats) == "cool-neutral"


class TestMapDepth:
    def test_light(self) -> None:
        skin = {"L": 75.0, "a": 10.0, "b": 15.0, "chroma": 18.0}
        assert _map_depth(skin, None) == "light"

    def test_deep_with_dark_hair(self) -> None:
        skin = {"L": 45.0, "a": 10.0, "b": 15.0, "chroma": 18.0}
        hair = {"L": 15.0, "a": 2.0, "b": 3.0, "chroma": 3.6}
        # 0.6*45 + 0.4*15 = 33 → deep
        assert _map_depth(skin, hair) == "deep"

    def test_medium(self) -> None:
        skin = {"L": 55.0, "a": 10.0, "b": 15.0, "chroma": 18.0}
        assert _map_depth(skin, None) == "medium"

    def test_hair_shifts_depth(self) -> None:
        skin = {"L": 65.0, "a": 10.0, "b": 15.0, "chroma": 18.0}

        dark_hair = {"L": 20.0, "a": 2.0, "b": 3.0, "chroma": 3.6}
        # 0.6*65 + 0.4*20 = 47 → medium
        assert _map_depth(skin, dark_hair) == "medium"

        light_hair = {"L": 70.0, "a": 5.0, "b": 10.0, "chroma": 11.2}
        # 0.6*65 + 0.4*70 = 67 → medium-light
        assert _map_depth(skin, light_hair) == "medium-light"

    def test_medium_light(self) -> None:
        skin = {"L": 62.0, "a": 10.0, "b": 15.0, "chroma": 18.0}
        assert _map_depth(skin, None) == "medium-light"

    def test_medium_deep(self) -> None:
        skin = {"L": 40.0, "a": 10.0, "b": 15.0, "chroma": 18.0}
        assert _map_depth(skin, None) == "medium-deep"

    def test_no_hair_uses_skin_only(self) -> None:
        """Bald/short hair/covered: depth based on skin L* alone."""
        skin = {"L": 50.0, "a": 10.0, "b": 15.0, "chroma": 18.0}
        assert _map_depth(skin, None) == "medium"


class TestMapContrast:
    def test_high_contrast(self) -> None:
        skin = {"L": 75.0, "a": 10.0, "b": 15.0, "chroma": 18.0}
        hair = {"L": 20.0, "a": 2.0, "b": 3.0, "chroma": 3.6}
        assert _map_contrast(skin, hair, None) == "high"

    def test_low_contrast(self) -> None:
        skin = {"L": 55.0, "a": 10.0, "b": 15.0, "chroma": 18.0}
        hair = {"L": 50.0, "a": 8.0, "b": 12.0, "chroma": 14.4}
        assert _map_contrast(skin, hair, None) == "low"

    def test_medium_contrast(self) -> None:
        skin = {"L": 65.0, "a": 10.0, "b": 15.0, "chroma": 18.0}
        hair = {"L": 40.0, "a": 5.0, "b": 8.0, "chroma": 9.4}
        # diff = 25 → medium
        assert _map_contrast(skin, hair, None) == "medium"

    def test_skin_only_uses_chroma_proxy(self) -> None:
        """No hair, no eyes — proxy from skin chroma."""
        skin = {"L": 65.0, "a": 10.0, "b": 15.0, "chroma": 18.0}
        result = _map_contrast(skin, None, None)
        assert result in ("low", "medium-low", "medium")

    def test_no_hair_with_eyes_uses_skin_eye_delta(self) -> None:
        """Bald/short hair: contrast from skin–eye lightness range."""
        skin = {"L": 70.0, "a": 10.0, "b": 15.0, "chroma": 18.0}
        eye = {"L": 25.0, "a": 3.0, "b": 5.0, "chroma": 5.8}
        # Range: 70 - 25 = 45 → high
        assert _map_contrast(skin, None, eye) == "high"

    def test_eyes_contribute(self) -> None:
        skin = {"L": 75.0, "a": 10.0, "b": 15.0, "chroma": 18.0}
        hair = {"L": 50.0, "a": 5.0, "b": 8.0, "chroma": 9.4}
        eye = {"L": 25.0, "a": 3.0, "b": 5.0, "chroma": 5.8}
        # Range: 75 - 25 = 50 → high
        assert _map_contrast(skin, hair, eye) == "high"

    def test_medium_high(self) -> None:
        skin = {"L": 70.0, "a": 10.0, "b": 15.0, "chroma": 18.0}
        hair = {"L": 35.0, "a": 5.0, "b": 8.0, "chroma": 9.4}
        # diff = 35 → medium-high
        assert _map_contrast(skin, hair, None) == "medium-high"


class TestMapChroma:
    def test_bright(self) -> None:
        skin = {"L": 65.0, "a": 15.0, "b": 20.0, "chroma": 25.0}
        assert _map_chroma(skin, "medium", "warm") == "bright"

    def test_soft(self) -> None:
        skin = {"L": 65.0, "a": 5.0, "b": 6.0, "chroma": 7.8}
        assert _map_chroma(skin, "low", "cool") == "soft"

    def test_clear_for_cool_high_contrast(self) -> None:
        skin = {"L": 65.0, "a": 15.0, "b": 18.0, "chroma": 23.4}
        assert _map_chroma(skin, "high", "cool") == "clear"

    def test_medium_soft(self) -> None:
        skin = {"L": 65.0, "a": 7.0, "b": 9.0, "chroma": 11.4}
        assert _map_chroma(skin, "medium", "neutral-warm") == "medium-soft"

    def test_medium_bright(self) -> None:
        skin = {"L": 65.0, "a": 10.0, "b": 12.0, "chroma": 15.6}
        assert _map_chroma(skin, "medium", "neutral-warm") == "medium-bright"

    def test_clear_requires_cool(self) -> None:
        """High chroma + high contrast but warm → "bright", not "clear"."""
        skin = {"L": 65.0, "a": 15.0, "b": 20.0, "chroma": 25.0}
        assert _map_chroma(skin, "high", "warm") == "bright"

    def test_clear_requires_high_contrast(self) -> None:
        """Cool + high chroma but low contrast → "bright", not "clear"."""
        skin = {"L": 65.0, "a": 15.0, "b": 18.0, "chroma": 23.4}
        assert _map_chroma(skin, "low", "cool") == "bright"


# ================================================================ unit: axis output values are valid for ColorEngine


class TestAxisValuesAreValidForColorEngine:
    """Every mapping function must return values recognised by the YAML rules."""

    VALID_UNDERTONE = {"warm", "neutral-warm", "cool", "cool-neutral", "neutral-cool"}
    VALID_CONTRAST = {"low", "medium-low", "medium", "medium-high", "high"}
    VALID_DEPTH = {"light", "medium-light", "medium", "medium-deep", "deep"}
    VALID_CHROMA = {"bright", "medium-bright", "soft", "medium-soft", "clear"}

    SAMPLE_STATS = [
        {"L": 30.0, "a": 15.0, "b": 20.0, "chroma": 25.0},
        {"L": 50.0, "a": 10.0, "b": 10.0, "chroma": 14.1},
        {"L": 70.0, "a": 5.0, "b": 5.0, "chroma": 7.1},
        {"L": 80.0, "a": 8.0, "b": 25.0, "chroma": 26.2},
        {"L": 40.0, "a": 18.0, "b": 3.0, "chroma": 18.2},
    ]

    def test_undertone_values(self) -> None:
        for stats in self.SAMPLE_STATS:
            assert _map_undertone(stats) in self.VALID_UNDERTONE

    def test_depth_values(self) -> None:
        for stats in self.SAMPLE_STATS:
            assert _map_depth(stats, None) in self.VALID_DEPTH
            assert _map_depth(stats, stats) in self.VALID_DEPTH

    def test_contrast_values(self) -> None:
        for i, stats in enumerate(self.SAMPLE_STATS):
            other = self.SAMPLE_STATS[(i + 1) % len(self.SAMPLE_STATS)]
            assert _map_contrast(stats, None, None) in self.VALID_CONTRAST
            assert _map_contrast(stats, other, None) in self.VALID_CONTRAST

    def test_chroma_values(self) -> None:
        for stats in self.SAMPLE_STATS:
            for contrast in self.VALID_CONTRAST:
                for undertone in self.VALID_UNDERTONE:
                    assert _map_chroma(stats, contrast, undertone) in self.VALID_CHROMA


# ================================================================ integration: blank images


class TestColorExtractionBlankImages:
    """Blank images have no face → extraction must fail gracefully."""

    def test_blank_images_raise(self) -> None:
        data = _make_jpeg()
        ext = ColorFeatureExtractor(image_fetcher=lambda p: data)
        with pytest.raises(ColorExtractionFailedError):
            ext.extract([_ref("portrait"), _ref("front")])

    def test_no_photos_raise(self) -> None:
        ext = ColorFeatureExtractor(image_fetcher=lambda p: None)
        with pytest.raises(ColorExtractionFailedError):
            ext.extract([])

    def test_only_side_photo_raises(self) -> None:
        """Side is not used for colour extraction."""
        data = _make_jpeg()
        ext = ColorFeatureExtractor(image_fetcher=lambda p: data)
        with pytest.raises(ColorExtractionFailedError):
            ext.extract([_ref("side")])

    def test_corrupt_data_raises(self) -> None:
        ext = ColorFeatureExtractor(image_fetcher=lambda p: b"not-a-jpeg")
        with pytest.raises(ColorExtractionFailedError):
            ext.extract([_ref("portrait")])

    def test_fetch_returns_none_raises(self) -> None:
        ext = ColorFeatureExtractor(image_fetcher=lambda p: None)
        with pytest.raises(ColorExtractionFailedError):
            ext.extract([_ref("portrait"), _ref("front")])


# ================================================================ module entry point


class TestModuleEntryPoint:
    def test_raises_on_blank(self) -> None:
        data = _make_jpeg()
        user_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        with pytest.raises(ColorExtractionFailedError):
            color_feature_extractor(
                user_id,
                [_ref("portrait")],
                image_fetcher=lambda p: data,
            )
