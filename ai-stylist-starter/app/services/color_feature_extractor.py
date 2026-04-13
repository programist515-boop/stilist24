"""Photo-based color feature extractor.

Extracts real color characteristics from user photos using MediaPipe
FaceLandmarker for face detection and OpenCV/CIE Lab for color analysis.

This is a **real photo-based color pipeline** — it reads actual pixel data
from the user's uploaded photos, NOT geometric body features.

What IS real photo-based extraction
------------------------------------
* Skin colour sampled from cheek ROIs (real pixels).
* Hair colour sampled from above-forehead ROI (real pixels).
* Eye colour from iris landmarks (optional, real pixels).
* CIE Lab colour-space analysis for perceptual measurements.
* Axis mapping based on measured L*, a*, b* values.

What is NOT done here (remains tech debt)
------------------------------------------
* True undertone modelling (illumination correction, skin-tone
  databases).  ``_map_undertone`` is an engineering proxy.
* Hair segmentation — the above-forehead heuristic can capture
  background.  A proper segmentation model would be more robust.
* Lighting normalisation — no white-balance correction is applied.
* Threshold calibration on a real annotated dataset.

When this module fails, ``UserAnalysisService`` falls back to
``_derive_color_axes(features)`` — a heuristic bridge that derives
colour from geometric body features.  That fallback is NOT photo-based.

Pipeline
--------
1. Load the portrait photo (primary) or front photo (fallback).
2. Detect face landmarks via MediaPipe FaceLandmarker (478 points).
3. Define ROIs for skin (cheeks), hair (above forehead), eyes (iris).
4. Convert ROI pixels to CIE Lab color space.
5. Compute perceptual color measurements (lightness, warmth, chroma).
6. Map measurements to ColorEngine axes: undertone, contrast, depth, chroma.

The output feeds directly into ``ColorEngine.analyze(color_axes)``.

Limitations
-----------
* Accuracy depends on photo quality, lighting, and face visibility.
* Heavy makeup (especially foundation) can shift apparent undertone.
* Very dark or overexposed photos will trigger fallback.
* Hair ROI may miss hair if covered, cropped, or head is shaved.
* Eye (iris) detection is optional and may fail in low-res images.
* Artificial lighting (fluorescent, tungsten) can skew all colour
  measurements — daylight photos produce the most reliable results.

Dependencies
------------
* ``mediapipe`` — FaceLandmarker for face detection.
* ``opencv-python`` (transitive via mediapipe) — RGB→Lab conversion.
* ``numpy`` — array operations.
* ``Pillow`` — image decoding.
"""

from __future__ import annotations

import io
import logging
import math
from pathlib import Path
from typing import Any

import numpy as np

from app.services.feature_extractor import PhotoReference

logger = logging.getLogger(__name__)


class ColorExtractionFailedError(Exception):
    """Raised when photo-based color extraction cannot produce results.

    The caller should fall back to the heuristic bridge
    (``_derive_color_axes``) or another alternative.
    """


# ---------------------------------------------------------------- model path

_MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "models"
_FACE_MODEL = _MODELS_DIR / "face_landmarker.task"


# ---------------------------------------------------------------- image loading


def _load_image(data: bytes) -> np.ndarray | None:
    """Decode image bytes → RGB numpy array via Pillow."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data)).convert("RGB")
        return np.asarray(img)
    except Exception as exc:
        logger.warning(
            "color_load: decode failed: %s: %s", type(exc).__name__, exc,
        )
        return None


def _fetch_image_bytes(photo: PhotoReference) -> bytes | None:
    """Fetch photo bytes from storage.  Returns None on failure."""
    logger.info("color_fetch: slot=%s key=%s", photo.slot, photo.image_key)
    try:
        from app.core.storage import StorageService

        storage = StorageService()
        result = storage.get_object(photo.image_key)
        if result is None:
            logger.warning(
                "color_fetch: MISS slot=%s key=%s", photo.slot, photo.image_key,
            )
            return None
        data = result[0]
        logger.info(
            "color_fetch: OK slot=%s size=%d bytes", photo.slot, len(data),
        )
        return data
    except Exception as exc:
        logger.warning(
            "color_fetch: FAIL slot=%s error=%s: %s",
            photo.slot, type(exc).__name__, exc,
        )
        return None


# ---------------------------------------------------------------- face detection


def _detect_face_landmarks(image_rgb: np.ndarray):
    """Detect face landmarks using MediaPipe FaceLandmarker.

    Returns the list of 478 face landmarks, or None if no face detected.
    """
    import mediapipe as mp

    if not _FACE_MODEL.exists():
        logger.warning(
            "color_face: MODEL NOT FOUND path=%s", _FACE_MODEL,
        )
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
            logger.warning("color_face: DETECTION EMPTY — 0 faces found")
            return None

        lm = result.face_landmarks[0]
        logger.info("color_face: DETECTED landmarks=%d", len(lm))
        return lm
    except Exception as exc:
        logger.warning(
            "color_face: EXCEPTION %s: %s", type(exc).__name__, exc,
        )
        return None
    finally:
        if landmarker is not None:
            landmarker.close()


# ---------------------------------------------------------------- ROI extraction


def _landmark_px(landmark, w: int, h: int) -> tuple[int, int]:
    """Convert a normalised MediaPipe landmark to pixel coordinates."""
    return int(landmark.x * w), int(landmark.y * h)


def _extract_patch(
    image_rgb: np.ndarray,
    cx: int,
    cy: int,
    radius: int,
) -> np.ndarray | None:
    """Extract a square patch centred at *(cx, cy)*.

    Returns a flattened ``(N, 3)`` uint8 RGB array, or ``None`` if the
    resulting patch is too small (< 3 px in either dimension).
    """
    h, w = image_rgb.shape[:2]
    x0, y0 = max(0, cx - radius), max(0, cy - radius)
    x1, y1 = min(w, cx + radius), min(h, cy + radius)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    return image_rgb[y0:y1, x0:x1].reshape(-1, 3)


def _extract_skin_roi(
    image_rgb: np.ndarray,
    lm,
) -> np.ndarray | None:
    """Extract skin pixels from both cheeks.

    Cheek centres are computed as the midpoint between the nose tip
    (landmark 1) and each face edge (landmarks 234 / 454) at the face-
    edge's y-coordinate.  This reliably lands on cheek flesh regardless
    of face shape or slight head rotation.
    """
    h, w = image_rgb.shape[:2]

    face_h = abs(lm[10].y - lm[152].y) * h
    if face_h < 20:
        logger.warning("color_skin_roi: face too small (%.0f px)", face_h)
        return None

    radius = max(4, int(face_h * 0.06))
    nose = lm[1]

    patches = []
    for edge_idx in (234, 454):  # left face edge, right face edge
        edge = lm[edge_idx]
        cx = int((nose.x + edge.x) / 2 * w)
        cy = int(edge.y * h)
        patch = _extract_patch(image_rgb, cx, cy, radius)
        if patch is not None:
            patches.append(patch)

    if not patches:
        return None

    pixels = np.concatenate(patches, axis=0)

    if len(pixels) < 20:
        logger.warning("color_skin_roi: too few pixels (%d)", len(pixels))
        return None

    logger.info(
        "color_skin_roi: extracted %d pixels, radius=%d", len(pixels), radius,
    )
    return pixels


def _extract_hair_roi(
    image_rgb: np.ndarray,
    lm,
) -> np.ndarray | None:
    """Extract hair pixels from above the forehead.

    Samples a horizontal band 8–25 % of face height above landmark 10
    (forehead top centre), spanning roughly the face width.
    """
    h, w = image_rgb.shape[:2]

    face_h = abs(lm[10].y - lm[152].y) * h
    face_w = abs(lm[234].x - lm[454].x) * w
    if face_h < 20:
        return None

    forehead_y = int(lm[10].y * h)
    top = max(0, forehead_y - int(face_h * 0.25))
    bottom = max(0, forehead_y - int(face_h * 0.08))

    cx = int((lm[234].x + lm[454].x) / 2 * w)
    half_w = max(4, int(face_w * 0.3))
    left = max(0, cx - half_w)
    right = min(w, cx + half_w)

    if bottom - top < 3 or right - left < 3:
        return None

    pixels = image_rgb[top:bottom, left:right].reshape(-1, 3)

    # Reject if too few pixels for reliable measurement
    if len(pixels) < 20:
        logger.warning("color_hair_roi: too few pixels (%d)", len(pixels))
        return None

    # Check for background contamination: if L* variance is extremely
    # high, the ROI likely captured mixed hair + background.  Real hair
    # (even multi-toned) rarely exceeds std(L) of ~25.
    import cv2
    lab = cv2.cvtColor(
        pixels.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_RGB2LAB,
    ).reshape(-1, 3).astype(np.float64)
    L_std = float(np.std(lab[:, 0] * 100.0 / 255.0))
    if L_std > 25:
        logger.warning(
            "color_hair_roi: high L* variance (std=%.1f) — "
            "likely background contamination, discarding", L_std,
        )
        return None

    logger.info(
        "color_hair_roi: extracted %d pixels, L_std=%.1f", len(pixels), L_std,
    )
    return pixels


def _extract_eye_roi(
    image_rgb: np.ndarray,
    lm,
) -> np.ndarray | None:
    """Extract eye / iris pixels using iris landmarks (468–477).

    Only available with the 478-landmark model.  Returns ``None`` if
    fewer landmarks are present or patches are too small.
    """
    if len(lm) < 478:
        return None

    h, w = image_rgb.shape[:2]
    face_h = abs(lm[10].y - lm[152].y) * h
    radius = max(2, int(face_h * 0.02))

    patches = []
    for idx in (468, 473):  # left iris centre, right iris centre
        cx, cy = _landmark_px(lm[idx], w, h)
        patch = _extract_patch(image_rgb, cx, cy, radius)
        if patch is not None:
            patches.append(patch)

    if not patches:
        return None

    pixels = np.concatenate(patches, axis=0)
    logger.info("color_eye_roi: extracted %d pixels", len(pixels))
    return pixels


# ---------------------------------------------------------------- colour analysis


def _rgb_to_lab(pixels_rgb: np.ndarray) -> np.ndarray:
    """Convert *(N, 3)* RGB uint8 pixels to CIE Lab float64.

    Returns *(N, 3)* with L* [0–100], a* [−128, 127], b* [−128, 127].
    Uses OpenCV's well-tested ``COLOR_RGB2LAB`` conversion.
    """
    import cv2

    # cv2.cvtColor needs a 2-D "image"; reshape to (N, 1, 3)
    img = pixels_rgb.reshape(-1, 1, 3).astype(np.uint8)
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    lab = lab.reshape(-1, 3).astype(np.float64)

    # OpenCV Lab uint8: L [0,255]→[0,100], a/b [0,255]→[−128,127]
    lab[:, 0] = lab[:, 0] * 100.0 / 255.0
    lab[:, 1] = lab[:, 1] - 128.0
    lab[:, 2] = lab[:, 2] - 128.0

    return lab


def _filter_outliers(lab: np.ndarray) -> np.ndarray:
    """Remove extreme outlier pixels by L* percentile filtering.

    Drops the top / bottom 5 % by lightness to exclude specular
    highlights and deep shadows that would skew the measurement.
    """
    if len(lab) < 10:
        return lab

    L = lab[:, 0]
    lo, hi = float(np.percentile(L, 5)), float(np.percentile(L, 95))
    mask = (L >= lo) & (L <= hi)
    filtered = lab[mask]
    return filtered if len(filtered) >= 5 else lab


def _compute_roi_stats(
    pixels_rgb: np.ndarray | None,
) -> dict[str, float] | None:
    """Compute CIE Lab colour statistics for a pixel ROI.

    Returns median L*, a*, b* and chroma (colourfulness).
    Uses *median* rather than *mean* for robustness to remaining outliers.
    """
    if pixels_rgb is None or len(pixels_rgb) < 5:
        return None

    lab = _rgb_to_lab(pixels_rgb)
    lab = _filter_outliers(lab)

    if len(lab) < 5:
        return None

    L = float(np.median(lab[:, 0]))
    a = float(np.median(lab[:, 1]))
    b = float(np.median(lab[:, 2]))
    chroma = math.sqrt(a * a + b * b)

    return {"L": L, "a": a, "b": b, "chroma": chroma}


# ---------------------------------------------------------------- axis mapping
#
# Each mapping function converts perceptual colour measurements into a
# categorical label that ``ColorEngine`` understands.  The thresholds
# are based on typical CIE Lab ranges for human skin/hair and are
# intentionally conservative — borderline cases fall to moderate labels.
#
# These are engineering-grade first approximations, NOT clinically
# validated colour-analysis rules.  Accuracy will improve as we gather
# real-world calibration data.
# ----------------------------------------------------------------


def _map_undertone(skin: dict[str, float]) -> str:
    """Map skin Lab values to an undertone label — ENGINEERING PROXY.

    This is a pixel-based approximation of undertone, NOT a clinically
    validated colour analysis.  It uses the balance of yellow (b*) vs
    pink/red (a*) in CIE Lab space as a proxy for the warm–cool axis.

    * Warm skin tends to have higher b* relative to a* (golden / olive).
    * Cool skin tends to have higher a* relative to b* (pink / rosy).

    Warmth index = b* − 0.4 × a*

    Accuracy is limited by lighting, camera white-balance, and makeup.
    The thresholds are conservative — borderline cases fall to neutral.
    """
    warmth = skin["b"] - 0.4 * skin["a"]

    if warmth > 12:
        return "warm"
    if warmth > 4:
        return "neutral-warm"
    if warmth > -3:
        return "cool-neutral"
    return "cool"


def _map_depth(
    skin: dict[str, float],
    hair: dict[str, float] | None,
) -> str:
    """Map overall lightness to depth.

    Combines skin L* (60 % weight) and hair L* (40 % weight) when both
    are available.  Higher L* = lighter appearance.
    """
    if hair is not None:
        depth_L = 0.6 * skin["L"] + 0.4 * hair["L"]
    else:
        depth_L = skin["L"]

    if depth_L > 68:
        return "light"
    if depth_L > 58:
        return "medium-light"
    if depth_L > 45:
        return "medium"
    if depth_L > 35:
        return "medium-deep"
    return "deep"


def _map_contrast(
    skin: dict[str, float],
    hair: dict[str, float] | None,
    eye: dict[str, float] | None,
) -> str:
    """Map feature-lightness differences to contrast.

    Contrast measures the visual difference between the lightest and
    darkest natural features.  For most people this is the skin–hair
    difference; eyes contribute when available.
    """
    L_values = [skin["L"]]
    if hair is not None:
        L_values.append(hair["L"])
    if eye is not None:
        L_values.append(eye["L"])

    if len(L_values) < 2:
        # Only skin available — use chroma as rough proxy
        c = skin["chroma"]
        if c > 20:
            return "medium"
        return "medium-low" if c > 12 else "low"

    diff = max(L_values) - min(L_values)

    if diff > 40:
        return "high"
    if diff > 30:
        return "medium-high"
    if diff > 18:
        return "medium"
    if diff > 10:
        return "medium-low"
    return "low"


def _map_chroma(
    skin: dict[str, float],
    contrast: str,
    undertone: str,
) -> str:
    """Map skin saturation to chroma.

    Chroma reflects how vivid or muted the overall colouring appears.
    ``"clear"`` is used for cool + high-contrast + high-chroma combinations
    (typical of Winter colour types).  ``"bright"`` covers other high-
    chroma cases.

    Thresholds are based on typical CIE Lab chroma ranges for human
    skin (~8–35).
    """
    c = skin["chroma"]

    # "clear": specifically for cool, high-contrast, high-saturation
    if (
        c > 20
        and contrast in ("high", "medium-high")
        and undertone in ("cool", "cool-neutral")
    ):
        return "clear"
    if c > 20:
        return "bright"
    if c > 15:
        return "medium-bright"
    if c > 10:
        return "medium-soft"
    return "soft"


# ---------------------------------------------------------------- extractor


class ColorFeatureExtractor:
    """Photo-based colour feature extractor.

    Analyses real pixel data from user photos to determine colour
    characteristics.  Uses MediaPipe for face detection and CIE Lab
    colour space for perceptual colour analysis.

    This is NOT a geometric heuristic — it reads actual photo colours.

    The ``image_fetcher`` seam works the same way as in
    ``CVFeatureExtractor``: tests inject a callable that returns bytes
    for a given ``PhotoReference``, production uses the default
    ``StorageService`` fetcher.
    """

    def __init__(self, *, image_fetcher: Any | None = None) -> None:
        self._fetch = image_fetcher or _fetch_image_bytes

    def extract(self, photos: list[PhotoReference]) -> dict[str, str]:
        """Extract colour axes from photos.

        Tries portrait first (best face visibility), then front.
        Raises ``ColorExtractionFailedError`` if neither produces results.
        """
        by_slot = {p.slot: p for p in photos}

        for slot in ("portrait", "front"):
            if slot not in by_slot:
                logger.info(
                    "color_extract: slot=%s not available, skipping", slot,
                )
                continue

            result = self._try_photo(by_slot[slot])
            if result is not None:
                logger.info(
                    "color_extract: SUCCESS from slot=%s axes=%s",
                    slot, result,
                )
                return result
            logger.info("color_extract: slot=%s produced no result, trying next", slot)

        raise ColorExtractionFailedError(
            "Could not extract colour from any available photo"
        )

    def _try_photo(self, photo: PhotoReference) -> dict[str, str] | None:
        """Attempt colour extraction from a single photo."""
        # 1. Fetch image bytes
        data = self._fetch(photo)
        if data is None:
            logger.warning(
                "color_extract: fetch returned None for slot=%s", photo.slot,
            )
            return None

        # 2. Decode to RGB
        image_rgb = _load_image(data)
        if image_rgb is None:
            return None
        logger.info(
            "color_extract: decoded slot=%s shape=%s", photo.slot, image_rgb.shape,
        )

        # 3. Detect face landmarks
        landmarks = _detect_face_landmarks(image_rgb)
        if landmarks is None:
            logger.warning("color_extract: no face in slot=%s", photo.slot)
            return None

        # 4. Extract ROIs
        skin_px = _extract_skin_roi(image_rgb, landmarks)
        hair_px = _extract_hair_roi(image_rgb, landmarks)
        eye_px = _extract_eye_roi(image_rgb, landmarks)

        logger.info(
            "color_extract: ROIs slot=%s skin=%s hair=%s eye=%s",
            photo.slot,
            len(skin_px) if skin_px is not None else "NONE",
            len(hair_px) if hair_px is not None else "NONE",
            len(eye_px) if eye_px is not None else "NONE",
        )

        # 5. Compute colour stats
        skin = _compute_roi_stats(skin_px)
        if skin is None:
            logger.warning(
                "color_extract: no usable skin pixels in slot=%s", photo.slot,
            )
            return None

        hair = _compute_roi_stats(hair_px)
        eye = _compute_roi_stats(eye_px)

        # Log raw signals for diagnostics
        logger.info(
            "color_extract: raw_signals slot=%s "
            "skin={L=%.1f a=%.1f b=%.1f chroma=%.1f} "
            "hair=%s eye=%s "
            "skin_hair_L_delta=%s",
            photo.slot,
            skin["L"], skin["a"], skin["b"], skin["chroma"],
            "{L=%.1f a=%.1f b=%.1f}" % (hair["L"], hair["a"], hair["b"])
            if hair else "NONE",
            "{L=%.1f}" % eye["L"] if eye else "NONE",
            "%.1f" % abs(skin["L"] - hair["L"]) if hair else "N/A",
        )

        # 6. Validate signal quality — reject B&W or extreme exposure
        if skin["chroma"] < 3:
            logger.warning(
                "color_extract: skin chroma too low (%.1f) — "
                "possibly B&W photo or extreme exposure. slot=%s",
                skin["chroma"], photo.slot,
            )
            return None

        # 7. Map measurements to categorical axes
        undertone = _map_undertone(skin)
        depth = _map_depth(skin, hair)
        contrast = _map_contrast(skin, hair, eye)
        chroma = _map_chroma(skin, contrast, undertone)

        return {
            "undertone": undertone,
            "contrast": contrast,
            "depth": depth,
            "chroma": chroma,
        }


# ---------------------------------------------------------------- module entry point


def color_feature_extractor(
    user_id: Any,
    photos: list[PhotoReference],
    *,
    image_fetcher: Any | None = None,
) -> dict[str, str]:
    """Module-level entry point for photo-based colour extraction.

    Signature mirrors ``cv_feature_extractor(user_id, photos)`` for
    consistency.  ``user_id`` is used for logging only — colour
    extraction does not depend on user identity.

    Raises ``ColorExtractionFailedError`` if no photo yields usable
    colour data.
    """
    logger.info(
        "color_feature_extractor: starting for user=%s photos=%d",
        user_id, len(photos),
    )
    return ColorFeatureExtractor(image_fetcher=image_fetcher).extract(photos)


__all__ = [
    "ColorExtractionFailedError",
    "ColorFeatureExtractor",
    "color_feature_extractor",
]
