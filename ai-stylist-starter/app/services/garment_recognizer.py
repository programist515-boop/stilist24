"""Garment attribute extractor — v1-lite.

Extracts only two attributes that can be estimated reliably from a photo:
  primary_color  — dominant garment color mapped to a named label
  print_type     — "solid" or "patterned" (binary, no sub-classification)

Every attribute result carries a _source marker:
  "cv"      — extracted from real image pixels
  "default" — step failed; fallback value used

Design principles:
- All heavy imports (rembg, cv2, PIL, numpy) are deferred inside methods.
  The module can be imported in test environments without these libraries.
- Every step is wrapped in try/except; any failure returns the fallback
  value and marks _source as "default". The pipeline always produces a
  complete dict.
- Background removal runs first so color sampling is not contaminated by
  the background. If rembg fails, raw pixels are used instead.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_RULES_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "config/rules/garment_recognition_rules.yaml"
)

FALLBACK_ATTRIBUTES: dict[str, Any] = {
    "primary_color": "white",
    "print_type": "solid",
    "_color_source": "default",
    "_print_source": "default",
}


def _load_rules() -> dict:
    with _RULES_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("garment_recognition", {})


class GarmentRecognizer:
    """v1-lite garment attribute extractor with per-step fallbacks."""

    def __init__(self, *, rules: dict | None = None) -> None:
        self._rules = rules if rules is not None else _load_rules()

    def recognize(
        self,
        image_bytes: bytes,
        hint_category: str | None = None,  # noqa: ARG002 — reserved for v2
    ) -> dict[str, Any]:
        """Run the v1-lite pipeline on raw image bytes.

        Returns a dict with keys:
          primary_color, print_type, _color_source, _print_source.
        Never raises — all failures return fallback values.
        """
        fg_image, fg_mask = self._remove_background(image_bytes)

        primary_color, color_source = self._extract_primary_color(fg_image, fg_mask)
        print_type, print_source = self._detect_print(fg_image, fg_mask)

        return {
            "primary_color": primary_color,
            "print_type": print_type,
            "_color_source": color_source,
            "_print_source": print_source,
        }

    # ---------------------------------------------------------- step 1: bg removal

    def _remove_background(
        self, image_bytes: bytes
    ) -> tuple[Any, Any]:
        """Remove background via rembg. Returns (rgb_array, alpha_mask).

        Falls back to (decoded_rgb, None) on any failure.
        """
        try:
            from rembg import remove  # lazy import
            from PIL import Image  # lazy import
            import io
            import numpy as np  # lazy import

            output = remove(image_bytes)
            img = Image.open(io.BytesIO(output)).convert("RGBA")
            arr = np.asarray(img)
            rgb = arr[:, :, :3]
            mask = arr[:, :, 3]  # alpha: >0 = foreground
            logger.debug("garment_recognizer: bg_removal OK shape=%s", rgb.shape)
            return rgb, mask
        except Exception as exc:
            logger.warning(
                "garment_recognizer: bg_removal FAILED %s: %s — using raw pixels",
                type(exc).__name__, exc,
            )
            return self._decode_raw(image_bytes)

    def _decode_raw(self, image_bytes: bytes) -> tuple[Any, Any]:
        try:
            from PIL import Image  # lazy import
            import io
            import numpy as np  # lazy import

            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            return np.asarray(img), None
        except Exception as exc:
            logger.warning(
                "garment_recognizer: raw_decode FAILED %s: %s",
                type(exc).__name__, exc,
            )
            return None, None

    # ---------------------------------------------------------- step 2: color

    def _extract_primary_color(
        self, fg_image: Any, fg_mask: Any
    ) -> tuple[str, str]:
        """Return (color_name, source) from mean foreground pixel color."""
        try:
            import numpy as np  # lazy import

            if fg_image is None:
                return FALLBACK_ATTRIBUTES["primary_color"], "default"

            if fg_mask is not None:
                fg_pixels = fg_image[fg_mask > 10].reshape(-1, 3)
            else:
                fg_pixels = fg_image.reshape(-1, 3)

            if len(fg_pixels) < 50:
                return FALLBACK_ATTRIBUTES["primary_color"], "default"

            if len(fg_pixels) > 5000:
                idx = np.random.choice(len(fg_pixels), 5000, replace=False)
                fg_pixels = fg_pixels[idx]

            mean_rgb = fg_pixels.mean(axis=0).astype(np.uint8)
            name = self._nearest_color_name(mean_rgb)
            return name, "cv"
        except Exception as exc:
            logger.warning(
                "garment_recognizer: color_extract FAILED %s: %s",
                type(exc).__name__, exc,
            )
            return FALLBACK_ATTRIBUTES["primary_color"], "default"

    def _nearest_color_name(self, rgb: Any) -> str:
        import numpy as np  # lazy import

        clusters = self._rules.get("color_clusters", {})
        best_name = "white"
        best_dist = float("inf")
        for name, hex_list in clusters.items():
            if not hex_list:
                continue
            cluster_rgb = np.array([_hex_to_rgb(h) for h in hex_list]).mean(axis=0)
            dist = float(np.linalg.norm(rgb.astype(float) - cluster_rgb))
            if dist < best_dist:
                best_dist = dist
                best_name = name
        return best_name

    # ---------------------------------------------------------- step 3: print

    def _detect_print(
        self, fg_image: Any, fg_mask: Any
    ) -> tuple[str, str]:
        """Return ("solid"|"patterned", source) from CIE Lab color variance."""
        try:
            import cv2  # lazy import
            import numpy as np  # lazy import

            if fg_image is None:
                return FALLBACK_ATTRIBUTES["print_type"], "default"

            if fg_mask is not None:
                fg_pixels = fg_image[fg_mask > 10].reshape(-1, 3)
            else:
                fg_pixels = fg_image.reshape(-1, 3)

            if len(fg_pixels) < 100:
                return FALLBACK_ATTRIBUTES["print_type"], "default"

            lab = cv2.cvtColor(
                fg_pixels.reshape(-1, 1, 3).astype(np.uint8),
                cv2.COLOR_RGB2LAB,
            ).reshape(-1, 3).astype(float)

            variance = (float(np.std(lab[:, 1])) + float(np.std(lab[:, 2]))) / 2
            threshold = float(self._rules.get("print_variance_threshold", 15.0))
            print_type = "patterned" if variance > threshold else "solid"
            return print_type, "cv"
        except Exception as exc:
            logger.warning(
                "garment_recognizer: print_detect FAILED %s: %s",
                type(exc).__name__, exc,
            )
            return FALLBACK_ATTRIBUTES["print_type"], "default"


# ---------------------------------------------------------- helpers

def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ---------------------------------------------------------- public API

def recognize_garment(
    image_bytes: bytes,
    hint_category: str | None = None,
    *,
    rules: dict | None = None,
) -> dict[str, Any]:
    """Module-level entry point. Never raises — all failures use fallbacks."""
    try:
        return GarmentRecognizer(rules=rules).recognize(
            image_bytes, hint_category=hint_category
        )
    except Exception as exc:
        logger.error(
            "garment_recognizer: critical failure %s: %s",
            type(exc).__name__, exc,
        )
        return dict(FALLBACK_ATTRIBUTES)


__all__ = ["FALLBACK_ATTRIBUTES", "GarmentRecognizer", "recognize_garment"]
