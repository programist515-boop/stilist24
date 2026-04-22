"""Color-drapery compositor for the preference quiz.

A *drape* is the offline-stylist trick of holding a swatch of fabric up to
the chin so the face can be judged against it. We mimic this by taking
the user's portrait and painting a colored "fabric" band across the lower
third of the image. The user then swipes like / dislike and, in aggregate,
the votes identify which color family (and then which season inside that
family) actually flatters them.

Design notes
------------
- No MediaPipe dependency. Chin-level geometry was considered but rejected
  for the MVP: the failure mode of a miss-detected face (band drawn over
  the forehead) is much worse than the "band is always in the bottom
  third" approximation. A proper chin-line pass can be added later
  without changing the public signature.
- The band is rendered with a short alpha ramp at the top edge so the
  swatch reads as fabric falling onto the chest instead of a hard
  rectangle glued onto the photo. The ramp length is small compared to
  the band height so the dominant color still reaches the chin area.
- Output is always JPEG on a flattened RGB canvas — quiz candidates are
  stored in S3 and served as plain <img> tags, so transparency would be
  lost on render anyway.
"""

from __future__ import annotations

import io

from PIL import Image


# Standard card size for the quiz grid. Portrait aspect (2:3) keeps the
# face dominant and leaves enough vertical room for the fabric band.
_CARD_WIDTH = 600
_CARD_HEIGHT = 900

# The drape covers the bottom third of the card.
_BAND_HEIGHT_RATIO = 1.0 / 3.0

# Top edge of the band fades in over this many pixels (relative to the
# band's own height) so the fabric blends into the portrait instead of
# reading as a pasted-on rectangle.
_BAND_FEATHER_RATIO = 0.12

_MIN_ALPHA = 217  # ~0.85 * 255
_MAX_ALPHA = 255

_JPEG_QUALITY = 88


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Parse a ``#RRGGBB`` string into an ``(r, g, b)`` tuple.

    Leading ``#`` is optional. Only 6-digit hex is accepted — the palette
    YAML only ever emits 6-digit values, so a stricter parser catches
    typos immediately rather than silently clamping them.
    """
    value = hex_color.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected #RRGGBB hex color, got {hex_color!r}")
    try:
        r = int(value[0:2], 16)
        g = int(value[2:4], 16)
        b = int(value[4:6], 16)
    except ValueError as exc:
        raise ValueError(f"invalid hex digits in {hex_color!r}") from exc
    return r, g, b


def _resize_portrait(img: Image.Image) -> Image.Image:
    """Resize to the canonical card size while preserving aspect ratio.

    The portrait is scaled to cover the card (``max`` of the two scale
    factors) and then center-cropped. This matches the behavior of a CSS
    ``object-fit: cover`` and keeps the face near the vertical center
    regardless of the source aspect.
    """
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        raise ValueError("portrait has zero width or height")

    scale = max(_CARD_WIDTH / src_w, _CARD_HEIGHT / src_h)
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))
    scaled = img.resize((new_w, new_h), Image.LANCZOS)

    left = (new_w - _CARD_WIDTH) // 2
    top = (new_h - _CARD_HEIGHT) // 2
    return scaled.crop((left, top, left + _CARD_WIDTH, top + _CARD_HEIGHT))


def _build_band(color_rgb: tuple[int, int, int]) -> Image.Image:
    """Build the RGBA band with a soft alpha ramp at the top edge."""
    band_h = int(round(_CARD_HEIGHT * _BAND_HEIGHT_RATIO))
    feather_h = max(1, int(round(band_h * _BAND_FEATHER_RATIO)))

    band = Image.new("RGBA", (_CARD_WIDTH, band_h), color_rgb + (_MAX_ALPHA,))
    pixels = band.load()

    # Ramp alpha from _MIN_ALPHA at the very top row up to _MAX_ALPHA
    # at the end of the feather zone. Everything below stays fully
    # opaque so the dominant color reaches the chin.
    for y in range(feather_h):
        # Linear ramp; good enough visually and cheap to compute.
        t = y / feather_h
        alpha = int(round(_MIN_ALPHA + (_MAX_ALPHA - _MIN_ALPHA) * t))
        for x in range(_CARD_WIDTH):
            r, g, b, _ = pixels[x, y]
            pixels[x, y] = (r, g, b, alpha)

    return band


def render_drapery(portrait_bytes: bytes, hex_color: str) -> bytes:
    """Composite a drape band under the portrait and return JPEG bytes.

    Parameters
    ----------
    portrait_bytes
        Raw image bytes — any format Pillow can decode (JPEG/PNG/WebP).
        RGBA inputs are flattened onto a white canvas so transparency
        in the source doesn't leak into the final JPEG.
    hex_color
        ``#RRGGBB`` swatch. This becomes the dominant color of the
        fabric band painted across the lower third of the card.

    Returns
    -------
    bytes
        JPEG-encoded bytes of the composited card, ready to hand off
        to :class:`~app.core.storage.StorageService`.
    """
    if not portrait_bytes:
        raise ValueError("portrait_bytes is empty")

    color_rgb = _hex_to_rgb(hex_color)

    with Image.open(io.BytesIO(portrait_bytes)) as src:
        src.load()
        if src.mode == "RGBA":
            flattened = Image.new("RGB", src.size, (255, 255, 255))
            flattened.paste(src, mask=src.split()[3])
            working = flattened
        elif src.mode != "RGB":
            working = src.convert("RGB")
        else:
            working = src.copy()

    card = _resize_portrait(working)

    band = _build_band(color_rgb)
    band_h = band.size[1]
    band_top = _CARD_HEIGHT - band_h

    # Alpha-composite the band onto the card. Pillow's ``paste`` with a
    # mask honors per-pixel alpha from the RGBA band image.
    card.paste(band, (0, band_top), band)

    buf = io.BytesIO()
    card.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return buf.getvalue()


__all__ = ["render_drapery"]
