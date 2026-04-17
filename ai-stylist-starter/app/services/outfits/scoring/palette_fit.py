"""Palette fit scorer — how well the outfit matches the user's season palette.

Delegates per-item color scoring to the canonical
:func:`app.services.scoring.color_match.evaluate_color_fit` so the logic
is consistent with the shopping evaluator and analytics pipeline.
"""

from __future__ import annotations

from app.services.outfits.scoring.base import BaseScorer, ScorerResult
from app.services.scoring.color_match import evaluate_color_fit


class PaletteFitScorer(BaseScorer):
    """Scores how well the outfit's colors fit the user's season palette.

    Uses ``context['palette_hex']`` (from ColorEngine) and optionally
    ``context['avoid_hex']`` for penalty colours.
    """

    weight: float = 0.15

    def score(self, outfit_items: list[dict], context: dict) -> ScorerResult:
        palette_hex: list[str] = context.get("palette_hex") or []
        avoid_hex: list[str] = context.get("avoid_hex") or []

        if not palette_hex:
            return ScorerResult(
                score=0.5,
                weight=self.weight,
                reasons=["palette_fit: no palette provided — neutral"],
            )

        if not outfit_items:
            return ScorerResult(
                score=0.0,
                weight=self.weight,
                warnings=["palette_fit: empty outfit"],
            )

        item_scores: list[float] = []
        reasons: list[str] = []
        warnings: list[str] = []

        for item in outfit_items:
            attrs = self._item_attrs(item)
            color = self._extract_val(attrs, "primary_color")
            if not color:
                item_scores.append(0.5)
                reasons.append("palette_fit: item has no color — neutral")
                continue
            result = evaluate_color_fit(color, palette_hex, avoid_hex=avoid_hex)
            item_scores.append(result.score)
            prefix = "palette_fit: "
            for r in result.reasons:
                (reasons if result.score >= 0.6 else warnings).append(prefix + r)
            for w in result.warnings:
                warnings.append(prefix + w)

        avg = sum(item_scores) / len(item_scores)
        return ScorerResult(
            score=round(avg, 3),
            weight=self.weight,
            reasons=reasons,
            warnings=warnings,
        )
