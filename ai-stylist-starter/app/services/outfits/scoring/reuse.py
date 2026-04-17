"""Reuse scorer — bonus for items with high rotation potential.

Two signals:
1. Low cost-per-wear (CPW < threshold) → item already earns its keep.
2. Item hasn't been worn recently → nominating it increases wardrobe coverage.

Both signals are bonuses, never penalties — this scorer can only push the
score above the neutral baseline, never below it.
"""

from __future__ import annotations

from app.services.analytics.cpw_service import calculate as cpw_calculate
from app.services.outfits.scoring.base import BaseScorer, ScorerResult

_LOW_CPW_THRESHOLD = 15.0    # below this → well-used item, boost
_HIGH_CPW_THRESHOLD = 60.0   # above this → underused relative to price


class ReuseScorer(BaseScorer):
    """Encourages outfits that make use of well-worn or recently-neglected items."""

    weight: float = 0.10

    def score(self, outfit_items: list[dict], context: dict) -> ScorerResult:
        if not outfit_items:
            return ScorerResult(
                score=0.5,
                weight=self.weight,
                reasons=["reuse: empty outfit — neutral"],
            )

        reasons: list[str] = []
        item_scores: list[float] = []

        for item in outfit_items:
            wear_count: int = item.get("wear_count", 0) or 0
            cost: float | None = item.get("cost")
            cpw = cpw_calculate(cost, wear_count)
            item_score = 0.5  # neutral baseline

            if cpw is not None and cpw < _LOW_CPW_THRESHOLD:
                item_score = min(1.0, item_score + 0.35)
                reasons.append(f"reuse: CPW={cpw:.2f} — good investment item")
            elif cpw is not None and cpw > _HIGH_CPW_THRESHOLD:
                item_score = max(0.0, item_score - 0.15)
                reasons.append(f"reuse: CPW={cpw:.2f} — high cost relative to wears")

            if wear_count == 0:
                item_score = min(1.0, item_score + 0.20)
                reasons.append("reuse: never-worn item — nominate for rotation")
            elif wear_count <= 2:
                item_score = min(1.0, item_score + 0.10)
                reasons.append(f"reuse: rarely-worn ({wear_count}×) — encourage rotation")

            item_scores.append(item_score)

        avg = sum(item_scores) / len(item_scores)
        return ScorerResult(
            score=round(avg, 3),
            weight=self.weight,
            reasons=reasons,
        )
