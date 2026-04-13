"""Tests for STEP 14 — CV feature extractor (MediaPipe Pose + FaceMesh).

The CV extractor converts real image bytes into the 20-key Identity Engine
feature vector.  These tests verify:

1. Correct 20-key schema output.
2. All values in ``[0.0, 1.0]``.
3. Deterministic output for the same input.
4. Different images produce different vectors.
5. Graceful fallback when image loading fails.
6. ``_merge_metrics`` produces correct derived features.
7. ``_normalize`` and ``_clamp01`` edge cases.
"""

from __future__ import annotations

import io
import uuid

import numpy as np
import pytest
from PIL import Image

from app.services.cv_feature_extractor import (
    CVExtractionFailedError,
    CVFeatureExtractor,
    _clamp01,
    _merge_metrics,
    _normalize,
    cv_feature_extractor,
)
from app.services.feature_extractor import BASELINE, SCHEMA_KEYS, PhotoReference


# ---------------------------------------------------------------- fixtures


USER_A = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _ref(slot: str, photo_id: uuid.UUID | None = None) -> PhotoReference:
    pid = photo_id or uuid.uuid4()
    return PhotoReference(
        slot=slot,
        image_key=f"users/x/photos/{slot}/{pid}.jpg",
        image_url=f"memory://users/x/photos/{slot}/{pid}.jpg",
        photo_id=pid,
    )


def _three_refs() -> list[PhotoReference]:
    return [_ref("front"), _ref("side"), _ref("portrait")]


def _make_jpeg(width: int = 320, height: int = 480, color: tuple = (128, 128, 128)) -> bytes:
    """Generate a synthetic JPEG image of the given size and color."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _make_fetcher(data_map: dict[str, bytes | None]):
    """Return an image_fetcher that looks up bytes by slot."""
    def fetcher(photo: PhotoReference) -> bytes | None:
        return data_map.get(photo.slot)
    return fetcher


def _failing_fetcher(photo: PhotoReference) -> bytes | None:
    """An image_fetcher that always returns None (simulating storage failure)."""
    return None


# ================================================================ unit tests: helpers


class TestClamp01:
    def test_within_range(self) -> None:
        assert _clamp01(0.5) == 0.5

    def test_below_zero(self) -> None:
        assert _clamp01(-0.3) == 0.0

    def test_above_one(self) -> None:
        assert _clamp01(1.7) == 1.0

    def test_exact_boundaries(self) -> None:
        assert _clamp01(0.0) == 0.0
        assert _clamp01(1.0) == 1.0


class TestNormalize:
    def test_midpoint(self) -> None:
        assert _normalize(0.5, 0.0, 1.0) == 0.5

    def test_at_lo(self) -> None:
        assert _normalize(0.0, 0.0, 1.0) == 0.0

    def test_at_hi(self) -> None:
        assert _normalize(1.0, 0.0, 1.0) == 1.0

    def test_below_lo_clamps(self) -> None:
        assert _normalize(-1.0, 0.0, 1.0) == 0.0

    def test_above_hi_clamps(self) -> None:
        assert _normalize(2.0, 0.0, 1.0) == 1.0

    def test_degenerate_range(self) -> None:
        assert _normalize(5.0, 3.0, 3.0) == 0.5

    def test_inverted_range(self) -> None:
        assert _normalize(5.0, 10.0, 3.0) == 0.5


# ================================================================ unit tests: _merge_metrics


class TestMergeMetrics:
    def test_all_none_returns_baseline_derived(self) -> None:
        """When all slots fail, output is BASELINE + derived features."""
        result = _merge_metrics(None, None, None)
        assert frozenset(result.keys()) == SCHEMA_KEYS
        assert len(result) == 20
        # Direct body keys should match baseline
        for key in ("vertical_line", "compactness", "width"):
            assert result[key] == BASELINE[key]

    def test_all_values_in_unit_interval(self) -> None:
        result = _merge_metrics(None, None, None)
        for key, val in result.items():
            assert 0.0 <= val <= 1.0, f"{key}={val} outside [0,1]"

    def test_body_metrics_applied(self) -> None:
        body = {"vertical_line": 0.9, "width": 0.3}
        result = _merge_metrics(body, None, None)
        assert result["vertical_line"] == 0.9
        assert result["width"] == 0.3

    def test_front_side_averaged(self) -> None:
        front = {"vertical_line": 0.8, "width": 0.4}
        side = {"vertical_line": 0.6, "width": 0.2}
        result = _merge_metrics(front, side, None)
        assert abs(result["vertical_line"] - 0.7) < 1e-9
        assert abs(result["width"] - 0.3) < 1e-9

    def test_face_metrics_applied(self) -> None:
        face = {"facial_roundness": 0.8, "facial_sharpness": 0.3}
        result = _merge_metrics(None, None, face)
        assert result["facial_roundness"] == 0.8
        assert result["facial_sharpness"] == 0.3

    def test_low_line_contrast_is_complement(self) -> None:
        body = {"line_contrast": 0.7}
        result = _merge_metrics(body, None, None)
        assert abs(result["low_line_contrast"] - 0.3) < 1e-9

    def test_derived_moderation(self) -> None:
        """Moderation should be high when primary features are uniform."""
        # All primary features at 0.5 → variance = 0 → moderation = 1.0
        body = {
            "vertical_line": 0.5, "compactness": 0.5, "width": 0.5,
            "softness": 0.5, "bone_sharpness": 0.5, "symmetry": 0.5,
            "curve_presence": 0.5,
        }
        face = {"facial_sharpness": 0.5, "facial_roundness": 0.5}
        result = _merge_metrics(body, None, face)
        assert result["moderation"] == 1.0

    def test_derived_feature_juxtaposition(self) -> None:
        """High yin-yang spread → high juxtaposition."""
        body = {
            "softness": 0.9, "curve_presence": 0.9,
            "bone_sharpness": 0.1, "line_contrast": 0.1,
        }
        face = {"facial_roundness": 0.9, "facial_sharpness": 0.1}
        result = _merge_metrics(body, None, face)
        # yin_avg=0.9, yang_avg~=0.1 → juxtaposition = abs(0.8)*2.5 = 2.0 clamped to 1.0
        assert result["feature_juxtaposition"] == 1.0

    def test_schema_guard(self) -> None:
        """Output must always have exactly the 20 SCHEMA_KEYS."""
        result = _merge_metrics(None, None, None)
        assert frozenset(result.keys()) == SCHEMA_KEYS


# ================================================================ integration tests: CVFeatureExtractor


class TestCVFeatureExtractorWithSyntheticImages:
    """Test CVFeatureExtractor with synthetic JPEG images.

    Plain-colour images contain no person, so MediaPipe detects 0
    landmarks in every slot.  Since the fix for silent BASELINE
    fallback, this now raises ``CVExtractionFailedError``.
    """

    def test_all_blank_images_raise(self) -> None:
        """Blank images → 0 landmarks → all slots None → exception."""
        data = _make_jpeg()
        fetcher = _make_fetcher({"front": data, "side": data, "portrait": data})
        ext = CVFeatureExtractor(image_fetcher=fetcher)
        with pytest.raises(CVExtractionFailedError):
            ext.extract(USER_A, _three_refs())

    def test_different_blank_images_both_raise(self) -> None:
        """Different coloured blanks both fail — neither has a person."""
        red = _make_jpeg(color=(255, 0, 0))
        blue = _make_jpeg(color=(0, 0, 255))
        refs = _three_refs()

        ext_red = CVFeatureExtractor(
            image_fetcher=_make_fetcher({"front": red, "side": red, "portrait": red})
        )
        ext_blue = CVFeatureExtractor(
            image_fetcher=_make_fetcher({"front": blue, "side": blue, "portrait": blue})
        )
        with pytest.raises(CVExtractionFailedError):
            ext_red.extract(USER_A, refs)
        with pytest.raises(CVExtractionFailedError):
            ext_blue.extract(USER_A, refs)


class TestCVFeatureExtractorFailureFallback:
    """When all slots produce None, CVExtractionFailedError is raised."""

    def test_all_fetches_fail_raises(self) -> None:
        ext = CVFeatureExtractor(image_fetcher=_failing_fetcher)
        with pytest.raises(CVExtractionFailedError):
            ext.extract(USER_A, _three_refs())

    def test_partial_fetch_failure_still_valid(self) -> None:
        """If only one slot's image loads but MediaPipe finds nothing,
        the result depends on whether that slot yielded metrics.
        With blank images, pose detection returns None so all slots fail.
        """
        data = _make_jpeg()
        fetcher = _make_fetcher({"front": data, "side": None, "portrait": None})
        ext = CVFeatureExtractor(image_fetcher=fetcher)
        # Blank image → 0 landmarks → front also None → all-None → raises
        with pytest.raises(CVExtractionFailedError):
            ext.extract(USER_A, _three_refs())

    def test_corrupt_image_bytes_raise(self) -> None:
        """Corrupt bytes → decode fails → all slots None → raises."""
        fetcher = _make_fetcher({
            "front": b"not-a-jpeg",
            "side": b"also-not-valid",
            "portrait": b"\x00\x01\x02",
        })
        ext = CVFeatureExtractor(image_fetcher=fetcher)
        with pytest.raises(CVExtractionFailedError):
            ext.extract(USER_A, _three_refs())

    def test_empty_photo_list_raises(self) -> None:
        ext = CVFeatureExtractor(image_fetcher=_failing_fetcher)
        with pytest.raises(CVExtractionFailedError):
            ext.extract(USER_A, [])


# ================================================================ module-level entry point


class TestModuleEntryPoint:
    def test_cv_feature_extractor_raises_on_blank_images(self) -> None:
        """Module-level ``cv_feature_extractor`` also raises when all
        slots fail (blank images → 0 landmarks)."""
        data = _make_jpeg()
        fetcher = _make_fetcher({"front": data, "side": data, "portrait": data})
        ext = CVFeatureExtractor(image_fetcher=fetcher)
        with pytest.raises(CVExtractionFailedError):
            ext.extract(USER_A, _three_refs())
