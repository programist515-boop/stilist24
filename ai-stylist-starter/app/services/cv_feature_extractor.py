"""Real CV feature extractor — MediaPipe Pose + FaceMesh.

Replaces the stub :class:`StructuredFeatureExtractor` with actual
computer-vision measurements derived from the user's uploaded photos.

Pipeline
--------

1. For each ``PhotoReference`` in the canonical slot list, fetch the
   image bytes from storage (via ``StorageService.get_object``).
2. Decode the JPEG/PNG bytes into an RGB numpy array (Pillow).
3. Run **MediaPipe PoseLandmarker** (for ``front`` and ``side`` slots)
   and **MediaPipe FaceLandmarker** (for the ``portrait`` slot).
4. Extract normalised geometric measurements from the detected
   landmarks (shoulder/hip ratio, vertical alignment, face shape, …).
5. Map the raw measurements onto the 20-key ``SCHEMA_KEYS`` contract,
   clamped to ``[0.0, 1.0]``.

Fallback
--------

If any step fails (image fetch, decode, no landmarks detected) the
extractor falls back to a **per-key baseline** of ``0.45`` for the
affected slot's contributions.  If *all* slots fail, the output is
equivalent to the old stub.  The extractor **never raises** — the
``UserAnalysisService`` already has a catch-all fallback to
``_stub_features()``, and this module adds a second inner safety net
so partial failures still yield the best possible vector.

Thread safety
-------------

MediaPipe task instances are **not thread-safe** when shared.  This
module creates fresh instances per call and closes them
deterministically in a ``try/finally`` block.

Dependencies
------------

* ``mediapipe`` ≥ 0.10.9 — PoseLandmarker + FaceLandmarker (Tasks API).
  CPU-only, ~50–100 ms per image on modern hardware.
* ``numpy`` — array backend for MediaPipe.
* ``Pillow`` — JPEG/PNG decode.

Model files
-----------

The Tasks API requires pre-trained ``.task`` model files:

* ``models/pose_landmarker_lite.task``
* ``models/face_landmarker.task``

These live under ``ai-stylist-starter/models/`` and are fetched once
from Google's public storage bucket (see ``scripts/download_models.py``
or the Docker build step).
"""

from __future__ import annotations

import io
import logging
import math
import os
import uuid
from pathlib import Path
from typing import Any

from app.services.feature_extractor import BASELINE, SCHEMA_KEYS, PhotoReference

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- model paths

_MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "models"
_POSE_MODEL = _MODELS_DIR / "pose_landmarker_lite.task"
_FACE_MODEL = _MODELS_DIR / "face_landmarker.task"


# ---------------------------------------------------------------- helpers


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _normalize(value: float, lo: float, hi: float) -> float:
    """Map *value* from ``[lo, hi]`` into ``[0, 1]``, clamped."""
    if hi <= lo:
        return 0.5
    return _clamp01((value - lo) / (hi - lo))


def _dist(a: Any, b: Any) -> float:
    """Euclidean distance between two landmarks with .x, .y attributes."""
    dx = a.x - b.x
    dy = a.y - b.y
    return math.sqrt(dx * dx + dy * dy)


def _midpoint(a: Any, b: Any):
    """Return a simple namespace with .x, .y = midpoint of two landmarks."""

    class _P:
        pass

    p = _P()
    p.x = (a.x + b.x) / 2.0
    p.y = (a.y + b.y) / 2.0
    return p


# ---------------------------------------------------------------- image loading


def _load_image_from_bytes(data: bytes):
    """Decode image bytes → RGB numpy array via Pillow."""
    from PIL import Image
    import numpy as np

    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")
    return np.asarray(img)


def _fetch_image_bytes(photo: PhotoReference) -> bytes | None:
    """Fetch photo bytes from storage.  Returns None on failure."""
    try:
        from app.core.storage import StorageService

        storage = StorageService()
        result = storage.get_object(photo.image_key)
        if result is None:
            logger.warning("cv_extractor: image not found for key %s", photo.image_key)
            return None
        return result[0]
    except Exception as exc:
        logger.warning("cv_extractor: failed to fetch %s: %s", photo.image_key, exc)
        return None


# ---------------------------------------------------------------- pose analysis


def _analyze_pose(image_rgb) -> dict[str, float] | None:
    """Run MediaPipe PoseLandmarker on a single image and return raw metrics.

    Returns ``None`` if pose detection fails (no person found, low
    confidence, etc.).
    """
    import mediapipe as mp
    import numpy as np

    if not _POSE_MODEL.exists():
        logger.warning("cv_extractor: pose model not found at %s", _POSE_MODEL)
        return None

    landmarker = None
    try:
        base_options = mp.tasks.BaseOptions(
            model_asset_path=str(_POSE_MODEL),
        )
        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=base_options,
            num_poses=1,
            min_pose_detection_confidence=0.5,
        )
        landmarker = mp.tasks.vision.PoseLandmarker.create_from_options(options)

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=np.asarray(image_rgb),
        )
        result = landmarker.detect(mp_image)

        if not result.pose_landmarks or len(result.pose_landmarks) == 0:
            return None

        # First detected pose — list of NormalizedLandmark objects
        lm = result.pose_landmarks[0]
        return _compute_body_metrics(lm)
    except Exception as exc:
        logger.warning("cv_extractor: pose analysis failed: %s", exc)
        return None
    finally:
        if landmarker is not None:
            landmarker.close()


def _compute_body_metrics(lm) -> dict[str, float]:
    """Derive normalised body metrics from 33 MediaPipe Pose landmarks.

    All landmark coordinates are already normalised to [0, 1] by
    MediaPipe (relative to the image).  We compute ratios between
    landmarks so the results are invariant to image resolution.

    Landmark indices (MediaPipe Pose):
      0  = nose
      2  = left eye inner
      5  = right eye inner
     11  = left shoulder
     12  = right shoulder
     23  = left hip
     24  = right hip
     25  = left knee
     26  = right knee
     27  = left ankle
     28  = right ankle
    """
    # Key landmarks
    l_shoulder = lm[11]
    r_shoulder = lm[12]
    l_hip = lm[23]
    r_hip = lm[24]
    l_knee = lm[25]
    r_knee = lm[26]
    l_ankle = lm[27]
    r_ankle = lm[28]
    nose = lm[0]

    # Derived points
    mid_shoulder = _midpoint(l_shoulder, r_shoulder)
    mid_hip = _midpoint(l_hip, r_hip)
    mid_ankle = _midpoint(l_ankle, r_ankle)

    # Approximate waist as 1/3 of the way from hips to shoulders
    class _W:
        pass
    waist = _W()
    waist.x = mid_hip.x + (mid_shoulder.x - mid_hip.x) * 0.33
    waist.y = mid_hip.y + (mid_shoulder.y - mid_hip.y) * 0.33

    # Widths
    shoulder_width = _dist(l_shoulder, r_shoulder)
    hip_width = _dist(l_hip, r_hip)
    # Approximate waist width from torso taper
    waist_width = min(shoulder_width, hip_width) * 0.85

    # Heights
    body_height = abs(nose.y - mid_ankle.y)
    if body_height < 0.01:
        body_height = 0.01  # guard against degenerate pose
    torso_height = abs(mid_shoulder.y - mid_hip.y)
    leg_height = abs(mid_hip.y - mid_ankle.y)

    # --- Metrics ---

    # vertical_line: how aligned is the center column (nose → mid_shoulder → mid_hip → mid_ankle)?
    center_deviation = (
        abs(nose.x - mid_shoulder.x)
        + abs(mid_shoulder.x - mid_hip.x)
        + abs(mid_hip.x - mid_ankle.x)
    ) / 3.0
    vertical_line = 1.0 - min(center_deviation / 0.15, 1.0)

    # shoulder_to_hip_ratio
    sh_ratio = shoulder_width / max(hip_width, 0.001)

    # waist_definition: how much narrower is the waist than the hips?
    waist_def = (hip_width - waist_width) / max(hip_width, 0.001)

    # torso_leg_ratio: how close to golden proportion (0.618)?
    tl_ratio = torso_height / max(leg_height, 0.001)

    # symmetry: left/right mirror accuracy
    l_sh_to_hip = _dist(l_shoulder, l_hip)
    r_sh_to_hip = _dist(r_shoulder, r_hip)
    l_hip_to_ankle = _dist(l_hip, l_ankle)
    r_hip_to_ankle = _dist(r_hip, r_ankle)
    sym_torso = 1.0 - min(abs(l_sh_to_hip - r_sh_to_hip) / max(l_sh_to_hip, 0.001), 1.0)
    sym_leg = 1.0 - min(abs(l_hip_to_ankle - r_hip_to_ankle) / max(l_hip_to_ankle, 0.001), 1.0)
    symmetry = (sym_torso + sym_leg) / 2.0

    # compactness: body width relative to height (wider = less compact)
    max_width = max(shoulder_width, hip_width)
    compactness = 1.0 - min(max_width / max(body_height, 0.001), 1.0)

    # width: shoulder span relative to body height
    width = shoulder_width / max(body_height, 0.001)

    # narrowness: inverse of width
    narrowness = 1.0 - min(width / 0.5, 1.0)

    # line_contrast: difference between shoulder and hip width
    line_contrast_raw = abs(shoulder_width - hip_width) / max(max_width, 0.001)

    # relaxed_line: deviation of shoulders from horizontal
    shoulder_tilt = abs(l_shoulder.y - r_shoulder.y)
    relaxed_line = min(shoulder_tilt / 0.05, 1.0)

    # small_scale: how much of the frame the person occupies (less = smaller)
    small_scale = 1.0 - min(body_height / 0.9, 1.0)

    # proportion_balance: how close torso:leg is to golden ratio
    golden = 0.618
    balance_deviation = abs(tl_ratio - golden)
    proportion_balance = 1.0 - min(balance_deviation / 0.5, 1.0)

    # curve_presence: hip-waist differential (larger = more curve)
    curve_presence = min(waist_def / 0.3, 1.0)

    # softness: approximated from smooth curve between landmarks
    # (high curve + low line contrast = soft)
    softness = (curve_presence + (1.0 - line_contrast_raw)) / 2.0

    # bone_sharpness: inverse of softness, boosted by shoulder angle
    bone_sharpness = 1.0 - softness

    return {
        "vertical_line": _clamp01(vertical_line),
        "compactness": _clamp01(compactness),
        "width": _normalize(width, 0.1, 0.5),
        "shoulder_to_hip_ratio": _clamp01(sh_ratio / 2.0),  # normalize ~1.0-1.5 range
        "waist_definition": _clamp01(waist_def),
        "symmetry": _clamp01(symmetry),
        "narrowness": _clamp01(narrowness),
        "relaxed_line": _clamp01(relaxed_line),
        "small_scale": _clamp01(small_scale),
        "proportion_balance": _clamp01(proportion_balance),
        "line_contrast": _normalize(line_contrast_raw, 0.0, 0.4),
        "curve_presence": _clamp01(curve_presence),
        "softness": _clamp01(softness),
        "bone_sharpness": _clamp01(bone_sharpness),
        "bone_bluntness": _clamp01(1.0 - bone_sharpness),
    }


# ---------------------------------------------------------------- face analysis


def _analyze_face(image_rgb) -> dict[str, float] | None:
    """Run MediaPipe FaceLandmarker on a portrait and return face metrics.

    Returns ``None`` if no face is detected.
    """
    import mediapipe as mp
    import numpy as np

    if not _FACE_MODEL.exists():
        logger.warning("cv_extractor: face model not found at %s", _FACE_MODEL)
        return None

    landmarker = None
    try:
        base_options = mp.tasks.BaseOptions(
            model_asset_path=str(_FACE_MODEL),
        )
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=base_options,
            num_faces=1,
            min_face_detection_confidence=0.5,
        )
        landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=np.asarray(image_rgb),
        )
        result = landmarker.detect(mp_image)

        if not result.face_landmarks or len(result.face_landmarks) == 0:
            return None

        # First detected face — list of NormalizedLandmark objects
        lm = result.face_landmarks[0]
        return _compute_face_metrics(lm)
    except Exception as exc:
        logger.warning("cv_extractor: face analysis failed: %s", exc)
        return None
    finally:
        if landmarker is not None:
            landmarker.close()


def _compute_face_metrics(lm) -> dict[str, float]:
    """Derive face-shape metrics from 478 FaceLandmarker landmarks.

    Key landmark indices:
      10   = forehead top center
      152  = chin bottom
      234  = left cheek (widest)
      454  = right cheek (widest)
      127  = left jaw angle
      356  = right jaw angle
    """
    # Face bounding measurements
    forehead = lm[10]
    chin = lm[152]
    left_cheek = lm[234]
    right_cheek = lm[454]
    left_jaw = lm[127]
    right_jaw = lm[356]

    face_height = _dist(forehead, chin)
    face_width = _dist(left_cheek, right_cheek)
    jaw_width = _dist(left_jaw, right_jaw)

    if face_height < 0.001:
        face_height = 0.001

    # facial_roundness: wider face relative to height = rounder
    wh_ratio = face_width / face_height
    facial_roundness = _normalize(wh_ratio, 0.5, 1.0)

    # facial_sharpness: narrow jaw relative to cheekbones = sharper
    if face_width > 0.001:
        jaw_taper = 1.0 - (jaw_width / face_width)
    else:
        jaw_taper = 0.5
    facial_sharpness = _normalize(jaw_taper, 0.0, 0.5)

    return {
        "facial_roundness": _clamp01(facial_roundness),
        "facial_sharpness": _clamp01(facial_sharpness),
    }


# ---------------------------------------------------------------- aggregation


def _merge_metrics(
    body_front: dict[str, float] | None,
    body_side: dict[str, float] | None,
    face: dict[str, float] | None,
) -> dict[str, float]:
    """Merge slot-specific raw metrics into the final 20-key schema.

    For body metrics present in both front and side, we average them.
    For missing slots, we use ``BASELINE`` values.
    """
    features: dict[str, float] = dict(BASELINE)

    # Collect all body metrics (average front + side where both exist)
    body_metrics: dict[str, list[float]] = {}
    for source in (body_front, body_side):
        if source is None:
            continue
        for key, val in source.items():
            body_metrics.setdefault(key, []).append(val)

    # Map body measurements → schema keys
    body_key_map = {
        "vertical_line": "vertical_line",
        "compactness": "compactness",
        "width": "width",
        "waist_definition": "waist_definition",
        "symmetry": "symmetry",
        "narrowness": "narrowness",
        "relaxed_line": "relaxed_line",
        "small_scale": "small_scale",
        "proportion_balance": "proportion_balance",
        "line_contrast": "line_contrast",
        "curve_presence": "curve_presence",
        "softness": "softness",
        "bone_sharpness": "bone_sharpness",
        "bone_bluntness": "bone_bluntness",
    }

    for raw_key, schema_key in body_key_map.items():
        if raw_key in body_metrics:
            vals = body_metrics[raw_key]
            features[schema_key] = _clamp01(sum(vals) / len(vals))

    # Derived: low_line_contrast is complement of line_contrast
    if "line_contrast" in body_metrics:
        features["low_line_contrast"] = _clamp01(1.0 - features["line_contrast"])

    # Map face measurements
    if face is not None:
        if "facial_roundness" in face:
            features["facial_roundness"] = _clamp01(face["facial_roundness"])
        if "facial_sharpness" in face:
            features["facial_sharpness"] = _clamp01(face["facial_sharpness"])

    # Derived: moderation = 1 − variance of all primary features
    primary_keys = [
        "vertical_line", "compactness", "width", "softness",
        "bone_sharpness", "symmetry", "curve_presence",
        "facial_sharpness", "facial_roundness",
    ]
    primary_vals = [features[k] for k in primary_keys]
    if primary_vals:
        mean = sum(primary_vals) / len(primary_vals)
        variance = sum((v - mean) ** 2 for v in primary_vals) / len(primary_vals)
        # Low variance = high moderation (all features are moderate)
        features["moderation"] = _clamp01(1.0 - math.sqrt(variance) * 3.0)

    # Derived: feature_juxtaposition = spread between yin and yang features
    yin_keys = ["softness", "curve_presence", "facial_roundness"]
    yang_keys = ["bone_sharpness", "facial_sharpness", "line_contrast"]
    yin_avg = sum(features[k] for k in yin_keys) / len(yin_keys)
    yang_avg = sum(features[k] for k in yang_keys) / len(yang_keys)
    features["feature_juxtaposition"] = _clamp01(abs(yin_avg - yang_avg) * 2.5)

    # Derived: controlled_softness_or_sharpness = how close sharpness is to midpoint
    sharpness = features["bone_sharpness"]
    features["controlled_softness_or_sharpness"] = _clamp01(
        1.0 - abs(sharpness - 0.5) * 2.0
    )

    # Final guard
    assert frozenset(features.keys()) == SCHEMA_KEYS
    return features


# ---------------------------------------------------------------- public API


class CVFeatureExtractor:
    """Computer-vision feature extractor using MediaPipe.

    Fetches photo bytes from storage, runs Pose/FaceMesh detection,
    and computes a 20-key normalised feature vector.

    If ``image_fetcher`` is provided it overrides the default storage
    fetch — this is the seam tests use to inject synthetic images
    without needing a running MinIO instance.
    """

    def __init__(
        self,
        *,
        image_fetcher: Any | None = None,
    ) -> None:
        self._image_fetcher = image_fetcher or _fetch_image_bytes

    def extract(
        self,
        user_id: uuid.UUID,
        photos: list[PhotoReference],
    ) -> dict[str, float]:
        """Main entry point matching the service seam signature."""
        photos_by_slot: dict[str, PhotoReference] = {}
        for p in photos:
            photos_by_slot[p.slot] = p

        body_front: dict[str, float] | None = None
        body_side: dict[str, float] | None = None
        face: dict[str, float] | None = None

        # --- front slot → pose
        if "front" in photos_by_slot:
            body_front = self._process_body(photos_by_slot["front"])

        # --- side slot → pose
        if "side" in photos_by_slot:
            body_side = self._process_body(photos_by_slot["side"])

        # --- portrait slot → face mesh
        if "portrait" in photos_by_slot:
            face = self._process_face(photos_by_slot["portrait"])

        return _merge_metrics(body_front, body_side, face)

    def _load_image(self, photo: PhotoReference):
        """Fetch + decode one photo.  Returns numpy RGB array or None."""
        data = self._image_fetcher(photo)
        if data is None:
            return None
        try:
            return _load_image_from_bytes(data)
        except Exception as exc:
            logger.warning(
                "cv_extractor: failed to decode image %s: %s",
                photo.image_key,
                exc,
            )
            return None

    def _process_body(self, photo: PhotoReference) -> dict[str, float] | None:
        image = self._load_image(photo)
        if image is None:
            return None
        return _analyze_pose(image)

    def _process_face(self, photo: PhotoReference) -> dict[str, float] | None:
        image = self._load_image(photo)
        if image is None:
            return None
        return _analyze_face(image)


def cv_feature_extractor(
    user_id: uuid.UUID,
    photos: list[PhotoReference],
) -> dict[str, float]:
    """Module-level entry point matching the service seam signature.

    This is the callable that replaces ``default_feature_extractor``
    when the CV pipeline is active.
    """
    return CVFeatureExtractor().extract(user_id, photos)


__all__ = [
    "CVFeatureExtractor",
    "cv_feature_extractor",
]
