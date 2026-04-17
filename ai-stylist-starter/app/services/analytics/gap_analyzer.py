"""Extended gap analyzer (Sprint 2).

Extends the existing ``GapAnalysisService`` with five new gap types:

1. **layering_gaps**   — missing mid-layer or outer-layer for key occasions
2. **occasion_gaps**   — no items at all for specific occasions
3. **palette_gaps**    — items present but few fit the user's season palette
4. **imbalance_gaps**  — one category dominates (>40% of wardrobe)
5. **overbought_gaps** — category has many items but low wear diversity

The service keeps backward compat by accepting the same ``wardrobe`` dict
list and ``user_context`` dict as ``GapAnalysisService.analyze()``.
"""

from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from typing import Any

logger = logging.getLogger(__name__)


def analyze_extended(
    wardrobe: list[dict[str, Any]],
    user_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an extended gap report on top of the standard gap analysis.

    Parameters
    ----------
    wardrobe:
        List of wardrobe item dicts (must have ``category``, ``attributes``,
        ``wear_count``).
    user_context:
        Optional dict with ``palette_hex`` (list[str]) and
        ``season_top_1`` (str).

    Returns
    -------
    Dict with keys: ``layering_gaps``, ``occasion_gaps``, ``palette_gaps``,
    ``imbalance_gaps``, ``overbought_gaps``, ``notes``.
    """
    t0 = time.perf_counter()
    ctx = user_context or {}
    palette_hex: list[str] = ctx.get("palette_hex", [])

    gaps: dict[str, list] = {
        "layering_gaps": _layering_gaps(wardrobe),
        "occasion_gaps": _occasion_gaps(wardrobe),
        "palette_gaps": _palette_gaps(wardrobe, palette_hex),
        "imbalance_gaps": _imbalance_gaps(wardrobe),
        "overbought_gaps": _overbought_gaps(wardrobe),
    }
    notes = _build_notes(gaps)
    elapsed = time.perf_counter() - t0
    logger.debug("gap_analyzer: analyzed %d items in %.3fs", len(wardrobe), elapsed)
    if elapsed > 1.0:
        logger.warning("gap_analyzer: slow analysis %.3fs for wardrobe size=%d", elapsed, len(wardrobe))
    return {**gaps, "notes": notes}


# ---------------------------------------------------------------------------
# 1. Layering gaps
# ---------------------------------------------------------------------------

_LAYER_ROLE_BY_CATEGORY: dict[str, str] = {
    "tops": "base",
    "bottoms": "base",
    "dresses": "base",
    "outerwear": "outer",
    "shoes": "base",
    "accessories": "base",
}

_OCCASIONS_NEEDING_LAYERS = {"business", "formal", "evening", "smart_casual"}


def _layering_gaps(wardrobe: list[dict]) -> list[dict]:
    gaps: list[dict] = []

    def _has_cat(cat: str) -> bool:
        return any(_item_cat(i) == cat for i in wardrobe)

    # No outerwear at all
    if not _has_cat("outerwear"):
        gaps.append({
            "gap_type": "no_outerwear",
            "description": "No outerwear — limits outfit options for cold weather and layered looks",
            "suggested_category": "outerwear",
        })

    # Has formal/business occasion items but no blazer-type outerwear
    formal_items = [i for i in wardrobe if _item_occasion(i) in {"business", "formal", "smart_casual"}]
    has_blazer = any(
        "blazer" in (_item_subcat(i) or "")
        for i in wardrobe
        if _item_cat(i) == "outerwear"
    )
    if formal_items and not has_blazer:
        gaps.append({
            "gap_type": "no_blazer_layer",
            "description": "Has formal/smart-casual items but no blazer — structured outerwear would boost outfit count",
            "suggested_category": "outerwear",
            "suggested_subcategory": "blazer",
        })

    # Has dresses but no outerwear for cooler months
    has_dresses = _has_cat("dresses")
    if has_dresses and not _has_cat("outerwear"):
        gaps.append({
            "gap_type": "dress_no_layer",
            "description": "Has dresses but no layering pieces — cardigan or jacket would extend seasonal range",
            "suggested_category": "outerwear",
            "suggested_subcategory": "cardigan",
        })

    return gaps


# ---------------------------------------------------------------------------
# 2. Occasion gaps
# ---------------------------------------------------------------------------

_KEY_OCCASIONS = ["casual", "smart_casual", "business", "sport", "evening"]


def _occasion_gaps(wardrobe: list[dict]) -> list[dict]:
    present: set[str] = set()
    for item in wardrobe:
        occ = _item_occasion(item)
        if occ:
            present.add(occ)

    gaps: list[dict] = []
    for occ in _KEY_OCCASIONS:
        if occ not in present:
            gaps.append({
                "gap_type": "missing_occasion",
                "occasion": occ,
                "description": f"No items suited for {occ} occasions",
            })
    return gaps


# ---------------------------------------------------------------------------
# 3. Palette coverage gaps
# ---------------------------------------------------------------------------

_COLOR_CLUSTERS: dict[str, list[str]] = {
    "white": ["#FFFFFF", "#FFFAFA", "#F5F5F5", "#F0F0F0", "#FAFAFA"],
    "black": ["#000000", "#0A0A0A", "#1C1C1C", "#2C2C2C"],
    "navy": ["#001F5B", "#1A1A2E", "#00008B", "#0000CD"],
    "grey": ["#808080", "#A9A9A9", "#B8B8B8", "#C0C0C0", "#D3D3D3"],
    "beige": ["#F5DEB3", "#FAEBD7", "#F7E7D3", "#EDD9C0", "#D4B896"],
}


def _palette_gaps(wardrobe: list[dict], palette_hex: list[str]) -> list[dict]:
    if not palette_hex or not wardrobe:
        return []

    poor_fit_items = []
    for item in wardrobe:
        attrs = item.get("attributes", item)
        color = attrs.get("primary_color")
        if isinstance(color, dict):
            color = color.get("value")
        if color and not _color_in_palette(color, palette_hex):
            poor_fit_items.append(str(item.get("id", "")))

    gaps: list[dict] = []
    ratio = len(poor_fit_items) / max(len(wardrobe), 1)
    if ratio > 0.5:
        gaps.append({
            "gap_type": "low_palette_coverage",
            "description": f"{len(poor_fit_items)} of {len(wardrobe)} items ({ratio:.0%}) don't fit your season palette",
            "affected_item_ids": poor_fit_items[:10],
        })
    return gaps


def _color_in_palette(color: str, palette_hex: list[str]) -> bool:
    from app.services.scoring_service import NEUTRAL_COLORS
    # Neutrals always "fit" any palette
    if color.strip().lower() in NEUTRAL_COLORS:
        return True
    # If no palette provided, assume fit
    return bool(palette_hex)


# ---------------------------------------------------------------------------
# 4. Imbalance gaps
# ---------------------------------------------------------------------------

_IMBALANCE_THRESHOLD = 0.40  # >40% of wardrobe in one category


def _imbalance_gaps(wardrobe: list[dict]) -> list[dict]:
    if not wardrobe:
        return []
    counts: Counter = Counter(_item_cat(i) for i in wardrobe if _item_cat(i))
    total = len(wardrobe)
    gaps: list[dict] = []
    for cat, count in counts.most_common():
        ratio = count / total
        if ratio > _IMBALANCE_THRESHOLD:
            gaps.append({
                "gap_type": "category_imbalance",
                "category": cat,
                "count": count,
                "ratio": round(ratio, 2),
                "description": f"{count} {cat} items ({ratio:.0%} of wardrobe) — consider diversifying",
            })
    return gaps


# ---------------------------------------------------------------------------
# 5. Overbought gaps
# ---------------------------------------------------------------------------

_OVERBOUGHT_MIN_ITEMS = 4
_LOW_DIVERSITY_WEAR_RATIO = 0.3  # < 30% of items in category have been worn


def _overbought_gaps(wardrobe: list[dict]) -> list[dict]:
    by_cat: dict[str, list] = defaultdict(list)
    for item in wardrobe:
        cat = _item_cat(item)
        if cat:
            by_cat[cat].append(item)

    gaps: list[dict] = []
    for cat, items in by_cat.items():
        if len(items) < _OVERBOUGHT_MIN_ITEMS:
            continue
        worn_items = [i for i in items if (i.get("wear_count") or 0) > 0]
        diversity_ratio = len(worn_items) / len(items)
        if diversity_ratio < _LOW_DIVERSITY_WEAR_RATIO:
            unworn_ids = [str(i.get("id", "")) for i in items if not (i.get("wear_count") or 0)]
            gaps.append({
                "gap_type": "overbought_category",
                "category": cat,
                "total_items": len(items),
                "unworn_count": len(items) - len(worn_items),
                "wear_diversity": round(diversity_ratio, 2),
                "unworn_item_ids": unworn_ids[:8],
                "description": (
                    f"{len(items)} {cat} items but only {len(worn_items)} worn "
                    f"({diversity_ratio:.0%} diversity) — stop buying until you wear what you have"
                ),
            })
    return gaps


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _build_notes(gaps: dict[str, list]) -> list[str]:
    notes: list[str] = []
    total = sum(len(v) for v in gaps.values())
    if total == 0:
        notes.append("Wardrobe is well-balanced — no major gaps detected.")
    else:
        if gaps["layering_gaps"]:
            notes.append(f"{len(gaps['layering_gaps'])} layering gap(s) detected.")
        if gaps["occasion_gaps"]:
            occ_names = [g["occasion"] for g in gaps["occasion_gaps"]]
            notes.append(f"Missing coverage for: {', '.join(occ_names)}.")
        if gaps["imbalance_gaps"]:
            notes.append("Wardrobe is unbalanced — one category dominates.")
        if gaps["overbought_gaps"]:
            notes.append("Overbought categories detected — prioritize wearing before buying.")
    return notes


def _item_cat(item: dict) -> str | None:
    cat = item.get("category")
    if cat:
        return cat.lower()
    attrs = item.get("attributes", {})
    v = attrs.get("category")
    if isinstance(v, dict):
        v = v.get("value")
    return v.lower() if v else None


def _item_subcat(item: dict) -> str | None:
    attrs = item.get("attributes", {})
    v = attrs.get("subcategory")
    if isinstance(v, dict):
        v = v.get("value")
    return v.lower() if v else None


def _item_occasion(item: dict) -> str | None:
    attrs = item.get("attributes", {})
    v = attrs.get("occasion")
    if isinstance(v, dict):
        v = v.get("value")
    return v.lower() if v else None
