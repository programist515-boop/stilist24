"""Preference / style consistency scorer.

Covers both ScoringService._line_consistency and _style_consistency:
the two are averaged so that items with no style_tags still contribute
via line_type consistency.
"""

from __future__ import annotations

from app.services.outfits.scoring.base import BaseScorer, ScorerResult


class PreferenceScorer(BaseScorer):
    """Scores style coherence across the outfit's line + style tags."""

    weight: float = 0.15

    def score(self, outfit_items: list[dict], context: dict) -> ScorerResult:
        from app.services.scoring_service import ScoringService

        svc = ScoringService()
        items_attrs = [svc._extract_attrs(it) for it in outfit_items]

        lc_score, lc_reasons = svc._line_consistency(items_attrs)
        sc_score, sc_reasons = svc._style_consistency(items_attrs)

        combined = round((lc_score + sc_score) / 2, 3)
        reasons = lc_reasons + sc_reasons
        return ScorerResult(score=combined, weight=self.weight, reasons=reasons)
