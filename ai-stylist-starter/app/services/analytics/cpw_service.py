"""Cost-per-wear (CPW) service.

CPW = purchase_price / max(wear_count, 1)

A low CPW means the item has paid its way; a high CPW means the user
overpaid relative to actual use. Used by orphan detector, versatility
service, and the shopping evaluator in Sprint 4.
"""

from __future__ import annotations

from typing import Any


def calculate(cost: float | None, wear_count: int) -> float | None:
    """Return CPW for a single item, or None if cost is unknown."""
    if cost is None:
        return None
    return round(cost / max(wear_count, 1), 2)


def calculate_batch(items: list[dict[str, Any]]) -> dict[str, float | None]:
    """Return {item_id: cpw} for a list of wardrobe item dicts.

    Each dict must have ``id``, ``cost`` (float | None), and
    ``wear_count`` (int).
    """
    return {
        str(item["id"]): calculate(item.get("cost"), item.get("wear_count", 0))
        for item in items
    }


def calculate_projected(
    cost: float,
    current_wear_count: int,
    frequency_per_month: float,
    months: int = 12,
) -> dict[str, float]:
    """Project CPW assuming ``frequency_per_month`` wears for ``months``.

    Returns current and projected CPW alongside expected wear count.
    """
    projected_wears = current_wear_count + frequency_per_month * months
    return {
        "current_cpw": calculate(cost, current_wear_count),
        "projected_cpw": round(cost / max(projected_wears, 1), 2),
        "projected_wear_count": round(projected_wears, 1),
    }
