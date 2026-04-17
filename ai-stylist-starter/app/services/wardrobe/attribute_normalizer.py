"""Attribute normalizer for wardrobe items.

Converts the legacy flat ``attributes_json`` dict produced by
:class:`GarmentRecognizer` (and earlier manual inputs) into the v2
structured format where each attribute carries ``value``, ``confidence``,
``source``, and ``editable``.

The normalizer works with plain Python dicts so it can be used in the
service layer without pulling in pydantic. Route layer code that needs
Pydantic validation should import and use :class:`WardrobeAttributesV2`
separately.

The normalizer:
1. Applies legacy value mappings from ``clothing_ontology.yaml``
   (e.g. "clean" → "white", "patterned" → "print").
2. Validates values against the ontology's allowed lists.
   Unknown values are kept as-is but confidence is capped at 0.5.
3. Infers ``layer_role`` and ``occasion`` defaults from category when
   not provided.
4. Preserves ``source`` metadata from v2 AttributeField dicts in the input.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_ONTOLOGY_PATH = Path(__file__).parent.parent.parent.parent / "data" / "clothing_ontology.yaml"

_ontology_cache: dict | None = None

_VALID_SOURCES = frozenset(("cv", "manual", "import", "default"))

# --------------------------------------------------------------------------- #
# category → default layer_role and occasion                                  #
# --------------------------------------------------------------------------- #
_DEFAULT_LAYER_ROLE: dict[str, str] = {
    "tops": "base",
    "bottoms": "base",
    "dresses": "base",
    "outerwear": "outer",
    "shoes": "base",
    "accessories": "base",
}

_DEFAULT_OCCASION: dict[str, str] = {
    "tops": "casual",
    "bottoms": "casual",
    "dresses": "casual",
    "outerwear": "casual",
    "shoes": "casual",
    "accessories": "casual",
}


def _load_ontology() -> dict:
    global _ontology_cache
    if _ontology_cache is None:
        with open(_ONTOLOGY_PATH, encoding="utf-8") as f:
            _ontology_cache = yaml.safe_load(f)
    return _ontology_cache


def _make_field(
    value: str | None,
    confidence: float,
    source: str,
    ontology_allowed: list[str] | None,
) -> dict:
    """Build a v2 attribute dict, capping confidence for unknown values.

    ``ontology_allowed=None`` means "no validation" (no capping).
    ``ontology_allowed=[]`` means "no valid values" (always cap if value provided).
    """
    if value and ontology_allowed is not None and value not in ontology_allowed:
        confidence = min(confidence, 0.5)
    src = source if source in _VALID_SOURCES else "default"
    return {"value": value, "confidence": confidence, "source": src, "editable": True}


def _resolve_legacy(value: str | None, legacy_map: dict[str, str]) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return legacy_map.get(normalized, normalized)


def _get(raw_attrs: dict, key: str, fallback_keys: list[str] | None = None) -> tuple[str | None, float, str]:
    """Extract (value, confidence, source) from raw_attrs.

    Supports both flat string values and nested v2 attribute dicts
    of the form ``{"value": ..., "confidence": ..., "source": ...}``.
    """
    val = raw_attrs.get(key)
    if val is None and fallback_keys:
        for fk in fallback_keys:
            val = raw_attrs.get(fk)
            if val is not None:
                break
    if isinstance(val, dict) and "value" in val:
        return val.get("value"), float(val.get("confidence", 0.7)), str(val.get("source", "cv"))
    if isinstance(val, str):
        return val, 0.7, "cv"
    return None, 0.0, "default"


def normalize(raw_attrs: dict[str, Any]) -> dict[str, dict]:
    """Normalize a raw attributes dict to v2 structured format.

    Each key in the returned dict is an attribute name; each value is a
    v2 attribute dict: ``{value, confidence, source, editable}``.

    ``raw_attrs`` may be:
    - A legacy flat dict: ``{"color": "white", "print_type": "solid"}``
    - A partial v2 dict: ``{"primary_color": {"value": "white", "confidence": 0.9, ...}}``
    - A mix of both
    """
    ontology = _load_ontology()
    legacy_color_map: dict = ontology.get("legacy_color_map", {})
    legacy_pattern_map: dict = ontology.get("legacy_pattern_map", {})
    legacy_fit_map: dict = ontology.get("legacy_fit_map", {})
    shared: dict = ontology.get("shared", {})
    categories: dict = ontology.get("categories", {})

    # category
    cat_val, cat_conf, cat_src = _get(raw_attrs, "category")
    cat_normalized = cat_val.strip().lower() if cat_val else None
    cat_field = _make_field(cat_normalized, cat_conf, cat_src, list(categories.keys()) if categories else None)

    # subcategory
    sub_val, sub_conf, sub_src = _get(raw_attrs, "subcategory")
    cat_def = categories.get(cat_normalized or "", {})
    allowed_subs = cat_def.get("subcategories")
    sub_field = _make_field(sub_val, sub_conf, sub_src, allowed_subs)

    # primary_color — apply legacy map
    color_val, color_conf, color_src = _get(raw_attrs, "primary_color", fallback_keys=["color"])
    color_normalized = _resolve_legacy(color_val, legacy_color_map)
    color_field = _make_field(color_normalized, color_conf, color_src, shared.get("color"))

    # pattern — apply legacy map
    pattern_val, pattern_conf, pattern_src = _get(raw_attrs, "pattern", fallback_keys=["print_type"])
    pattern_normalized = _resolve_legacy(pattern_val, legacy_pattern_map)
    pattern_field = _make_field(pattern_normalized, pattern_conf, pattern_src, shared.get("pattern"))

    # material
    mat_val, mat_conf, mat_src = _get(raw_attrs, "material")
    cat_attrs = cat_def.get("attributes", {})
    material_field = _make_field(mat_val, mat_conf, mat_src, cat_attrs.get("material"))

    # fit — apply legacy map
    fit_val, fit_conf, fit_src = _get(raw_attrs, "fit")
    fit_normalized = _resolve_legacy(fit_val, legacy_fit_map)
    fit_field = _make_field(fit_normalized, fit_conf, fit_src, cat_attrs.get("fit"))

    # silhouette
    sil_val, sil_conf, sil_src = _get(raw_attrs, "silhouette")
    sil_field = _make_field(sil_val, sil_conf, sil_src, cat_attrs.get("silhouette"))

    # neckline — only relevant for tops/dresses; use [] for other categories so
    # any provided value gets confidence capped (signals "unexpected attribute")
    neck_val, neck_conf, neck_src = _get(raw_attrs, "neckline")
    if cat_normalized in ("tops", "dresses"):
        neck_allowed = cat_attrs.get("neckline")
    elif cat_normalized is not None:
        neck_allowed = []  # known category but neckline doesn't apply → cap confidence
    else:
        neck_allowed = None  # unknown category → no capping
    neck_field = _make_field(neck_val, neck_conf, neck_src, neck_allowed)

    # sleeve_length — only relevant for tops/dresses; same logic as neckline
    sleeve_val, sleeve_conf, sleeve_src = _get(raw_attrs, "sleeve_length")
    if cat_normalized in ("tops", "dresses"):
        sleeve_allowed = cat_attrs.get("sleeve_length")
    elif cat_normalized is not None:
        sleeve_allowed = []
    else:
        sleeve_allowed = None
    sleeve_field = _make_field(sleeve_val, sleeve_conf, sleeve_src, sleeve_allowed)

    # occasion — with category-based default
    occ_val, occ_conf, occ_src = _get(raw_attrs, "occasion")
    if occ_val is None and cat_normalized:
        occ_val = _DEFAULT_OCCASION.get(cat_normalized)
        occ_conf = 0.3
        occ_src = "default"
    occ_field = _make_field(occ_val, occ_conf, occ_src, shared.get("occasion"))

    # seasonality
    seas_val, seas_conf, seas_src = _get(raw_attrs, "seasonality")
    if seas_val is None:
        seas_val = "all_season"
        seas_conf = 0.3
        seas_src = "default"
    seas_field = _make_field(seas_val, seas_conf, seas_src, shared.get("seasonality"))

    # layer_role — with category-based default
    role_val, role_conf, role_src = _get(raw_attrs, "layer_role")
    if role_val is None and cat_normalized:
        role_val = _DEFAULT_LAYER_ROLE.get(cat_normalized)
        role_conf = 0.4
        role_src = "default"
    allowed_roles = cat_attrs.get("layer_role") or shared.get("layer_role")
    role_field = _make_field(role_val, role_conf, role_src, allowed_roles)

    return {
        "category": cat_field,
        "subcategory": sub_field,
        "primary_color": color_field,
        "pattern": pattern_field,
        "material": material_field,
        "fit": fit_field,
        "silhouette": sil_field,
        "neckline": neck_field,
        "sleeve_length": sleeve_field,
        "occasion": occ_field,
        "seasonality": seas_field,
        "layer_role": role_field,
    }


def apply_manual_update(attrs_v2: dict[str, dict], updates: dict[str, str]) -> dict[str, dict]:
    """Return a new v2 attrs dict with the supplied fields set to manual source.

    Unknown update keys are silently ignored to match the pydantic-based
    ``WardrobeAttributesV2.apply_manual_update`` behaviour.
    """
    result = {k: dict(v) for k, v in attrs_v2.items()}
    for field_name, new_value in updates.items():
        if field_name in result:
            result[field_name] = {"value": new_value, "confidence": 1.0, "source": "manual", "editable": True}
    return result


def to_legacy_dict(attrs_v2: dict[str, dict]) -> dict[str, Any]:
    """Return a flat ``{key: value}`` dict for backward-compat code."""
    return {k: (v.get("value") if isinstance(v, dict) else v) for k, v in attrs_v2.items()}
