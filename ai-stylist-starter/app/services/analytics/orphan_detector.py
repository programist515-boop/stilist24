"""Orphan detector — identifies wardrobe items that are hard to outfit.

An item is an orphan when it has few compatible partners, low actual wear,
and/or poor fit with the user's season palette. The ``orphan_score`` is in
[0, 1]: 1.0 = pure orphan, 0.0 = highly versatile and well-used.
"""

from __future__ import annotations

from typing import Any

from app.services.analytics.cpw_service import calculate as cpw
from app.services.analytics.item_graph import ItemCompatibilityGraph

# Thresholds
_LOW_PARTNER_COUNT = 2      # fewer compatible partners → orphan signal
_LOW_WEAR_COUNT = 2         # fewer actual wears → orphan signal
_HIGH_CPW_THRESHOLD = 50.0  # CPW > this → low reuse signal


def detect(
    item: dict[str, Any],
    graph: ItemCompatibilityGraph,
    palette_hex: list[str] | None = None,
) -> dict[str, Any]:
    """Compute orphan score and reasons for a single item.

    Parameters
    ----------
    item:
        Wardrobe item dict with ``id``, ``cost``, ``wear_count``, and
        ``attributes``.
    graph:
        Pre-built :class:`ItemCompatibilityGraph` for the full wardrobe.
    palette_hex:
        Optional flat list of hex colors from the user's season palette.
        Used to assess palette fit.

    Returns
    -------
    ``{orphan_score, is_orphan, reasons}``
    """
    item_id = str(item.get("id", ""))
    wear_count: int = item.get("wear_count", 0)
    cost: float | None = item.get("cost")
    reasons: list[str] = []
    penalties: list[float] = []

    # --- compatibility: few partners with score ≥ 0.5 ---
    partner_count = graph.edge_count(item_id, min_score=0.5)
    if partner_count < _LOW_PARTNER_COUNT:
        penalties.append(0.35)
        reasons.append(f"only {partner_count} compatible partner(s) in wardrobe")
    elif partner_count < 4:
        penalties.append(0.15)
        reasons.append(f"limited partners: {partner_count}")

    # --- wear count ---
    if wear_count == 0:
        penalties.append(0.30)
        reasons.append("never worn")
    elif wear_count < _LOW_WEAR_COUNT:
        penalties.append(0.15)
        reasons.append(f"rarely worn ({wear_count} time(s))")

    # --- CPW signal ---
    item_cpw = cpw(cost, wear_count)
    if item_cpw is not None and item_cpw > _HIGH_CPW_THRESHOLD:
        penalties.append(0.10)
        reasons.append(f"high cost-per-wear: {item_cpw:.2f}")

    # --- palette fit ---
    if palette_hex:
        attrs = item.get("attributes", item)
        color_val = attrs.get("primary_color")
        if isinstance(color_val, dict):
            color_val = color_val.get("value")
        fit = _palette_fit(color_val, palette_hex)
        if fit == "avoid":
            penalties.append(0.15)
            reasons.append("primary color not in user palette")
        elif fit == "none":
            penalties.append(0.05)
            reasons.append("color not assessed against palette")

    orphan_score = round(min(1.0, sum(penalties)), 3)
    return {
        "orphan_score": orphan_score,
        "is_orphan": orphan_score >= 0.35,
        "reasons": reasons,
    }


def detect_batch(
    items: list[dict[str, Any]],
    graph: ItemCompatibilityGraph,
    palette_hex: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Run orphan detection on all items. Returns a list sorted by
    ``orphan_score`` descending (worst orphans first)."""
    results = []
    for item in items:
        result = detect(item, graph, palette_hex)
        results.append({
            "item_id": str(item.get("id", "")),
            "category": item.get("category"),
            **result,
        })
    return sorted(results, key=lambda x: x["orphan_score"], reverse=True)


def _palette_fit(color: str | None, palette_hex: list[str]) -> str:
    """Rough palette fit check: 'good', 'avoid', or 'none'."""
    if not color:
        return "none"
    # We don't have hex→name lookup here; just check if color is a neutral
    from app.services.scoring_service import NEUTRAL_COLORS
    if color.strip().lower() in NEUTRAL_COLORS:
        return "good"
    return "none"  # non-neutral colors require hex comparison (done in palette_fit scorer)
