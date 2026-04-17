"""Candidate parser — turns raw image bytes or manual attrs into a shopping candidate dict.

The output is a plain wardrobe item dict in the same format the rest of the
pipeline expects: ``{id, category, attributes, cost, wear_count}``.
``wear_count`` is 0 and ``id`` is a placeholder UUID — the item doesn't
exist in the wardrobe yet.
"""

from __future__ import annotations

import uuid
from typing import Any


def parse_from_image(
    image_bytes: bytes,
    *,
    hint_category: str | None = None,
    price: float | None = None,
    extra_attrs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Infer garment attributes from an image and return a candidate dict.

    Uses ``GarmentRecognizer`` for color + print, then normalises to v2
    attribute format via ``attribute_normalizer.normalize()``.

    Parameters
    ----------
    image_bytes:
        Raw bytes of the uploaded image.
    hint_category:
        User-supplied category hint (overrides CV detection).
    price:
        Optional purchase price.
    extra_attrs:
        Manual attribute overrides that take precedence over CV inference.
    """
    from app.services.garment_recognizer import recognize_garment
    from app.services.wardrobe.attribute_normalizer import apply_manual_update, normalize

    detected = recognize_garment(image_bytes, hint_category=hint_category)
    raw: dict[str, Any] = {
        "category": hint_category or "tops",
        "primary_color": {
            "value": detected["primary_color"],
            "confidence": 0.7,
            "source": detected["_color_source"],
        },
        "pattern": {
            "value": detected["print_type"],
            "confidence": 0.7,
            "source": detected["_print_source"],
        },
    }

    attrs_v2 = normalize(raw)
    if extra_attrs:
        attrs_v2 = apply_manual_update(attrs_v2, extra_attrs)

    # Best estimate of overall inferred confidence: average of top-level fields
    confidences = [
        v.get("confidence", 0.5)
        for v in attrs_v2.values()
        if isinstance(v, dict)
    ]
    inferred_confidence = round(sum(confidences) / max(len(confidences), 1), 3)

    return _build_candidate(
        category=hint_category or "tops",
        attributes_v2=attrs_v2,
        price=price,
        inferred_confidence=inferred_confidence,
    )


def parse_from_attrs(
    raw_attrs: dict[str, Any],
    *,
    price: float | None = None,
) -> dict[str, Any]:
    """Build a candidate from manually supplied attributes.

    Parameters
    ----------
    raw_attrs:
        Flat or v2 attribute dict.  Must contain at least ``category``.
    price:
        Optional purchase price.
    """
    from app.services.wardrobe.attribute_normalizer import normalize

    attrs_v2 = normalize(raw_attrs)
    category = raw_attrs.get("category") or "tops"

    return _build_candidate(
        category=category,
        attributes_v2=attrs_v2,
        price=price,
        inferred_confidence=None,
    )


def _build_candidate(
    *,
    category: str,
    attributes_v2: dict,
    price: float | None,
    inferred_confidence: float | None,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "category": category,
        "attributes": attributes_v2,
        "cost": price,
        "wear_count": 0,
        "_inferred_confidence": inferred_confidence,
        "_is_candidate": True,
    }
