"""Color harmony scorer — extracted from ScoringService._color_harmony."""

from __future__ import annotations

from app.services.outfits.scoring.base import BaseScorer, ScorerResult
from app.services.scoring_service import NEUTRAL_COLORS


class ColorHarmonyScorer(BaseScorer):
    """Scores how well the outfit's color story hangs together.

    Delegates per-item color-fit logic to ScoringService so the rules stay
    in one place. Adds outfit-level bonuses from outfit_rules.yaml.
    """

    weight: float = 0.30

    def score(self, outfit_items: list[dict], context: dict) -> ScorerResult:
        from app.services.scoring_service import ScoringService

        svc = ScoringService()
        items_attrs = [svc._extract_attrs(it) for it in outfit_items]
        user_color = context.get("color_profile")

        if not items_attrs:
            return ScorerResult(
                score=0.0,
                weight=self.weight,
                warnings=["color_harmony: empty outfit"],
            )

        per_item_scores = []
        neutral_count = 0
        reasons: list[str] = []

        for attrs in items_attrs:
            s, _ = svc._color_fit(attrs, user_color)
            per_item_scores.append(s)
            primary = str(attrs.get("primary_color") or "").strip().lower()
            if primary in NEUTRAL_COLORS:
                neutral_count += 1

        base = sum(per_item_scores) / len(per_item_scores)
        reasons.append(f"color_harmony: avg per-item color_fit {base:.2f}")

        # Bonus: one accent + two+ neutrals
        bonus = (
            svc.rules.get("outfit_rules", {})
            .get("outfit_rules", {})
            .get("bonuses", {})
            .get("one_accent_plus_neutrals", 0.0)
        )
        accent_count = len(items_attrs) - neutral_count
        if accent_count == 1 and neutral_count >= 2 and bonus > 0:
            base = min(1.0, base + bonus)
            reasons.append(
                f"color_harmony: one accent + {neutral_count} neutrals (+{bonus:.2f})"
            )

        return ScorerResult(
            score=round(base, 3),
            weight=self.weight,
            reasons=reasons,
        )
