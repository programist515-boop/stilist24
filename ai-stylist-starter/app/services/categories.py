"""Wardrobe categories — single source of truth.

The 15 detailed categories mirror the YAML files in
``config/rules/category_rules/`` (one YAML per category). Imported by
schemas, the CV classifier, and the API to keep the enum aligned across
the system.

Legacy mapping converts the old 6-value flat enum (top, bottom, ...)
that the wardrobe was built with — used when reading items uploaded
before this change, and when the user-supplied hint comes through the
old form (the frontend will be updated, but old PWA caches may still
send legacy values for a while).
"""

from __future__ import annotations

from typing import Final

WARDROBE_CATEGORIES: Final[tuple[str, ...]] = (
    "bags",
    "belts",
    "blouses",
    "dresses",
    "eyewear",
    "headwear",
    "hosiery",
    "jackets",
    "jewelry",
    "outerwear",
    "pants",
    "shoes",
    "skirts",
    "sweaters",
    "swimwear",
)


_LEGACY_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"top", "bottom", "outerwear", "shoes", "dress", "accessory"}
)


_LEGACY_TO_DETAILED: Final[dict[str, str | None]] = {
    "top": "blouses",
    "bottom": "pants",
    "outerwear": "outerwear",
    "shoes": "shoes",
    "dress": "dresses",
    "accessory": None,
}


def is_legacy_category(value: str) -> bool:
    return value in _LEGACY_CATEGORIES


def legacy_to_detailed(legacy: str) -> str | None:
    """Map a legacy 6-value category to the closest detailed one.

    Returns ``None`` for ``"accessory"`` because it spans bags/belts/
    eyewear/headwear/jewelry — there's no single best detailed bucket,
    so the caller should treat this as «unknown, ask the user».
    """
    return _LEGACY_TO_DETAILED.get(legacy)


def is_known_category(value: str) -> bool:
    return value in WARDROBE_CATEGORIES or value in _LEGACY_CATEGORIES


__all__ = [
    "WARDROBE_CATEGORIES",
    "is_known_category",
    "is_legacy_category",
    "legacy_to_detailed",
]
