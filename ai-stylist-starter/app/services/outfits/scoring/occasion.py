"""Occasion fit scorer — extracted from ScoringService._occasion_fit."""

from __future__ import annotations

from app.services.outfits.scoring.base import BaseScorer, ScorerResult


class OccasionScorer(BaseScorer):
    """Checks that outfit items match the requested occasion."""

    weight: float = 0.10

    def score(self, outfit_items: list[dict], context: dict) -> ScorerResult:
        from app.services.scoring_service import ScoringService

        svc = ScoringService()
        items_attrs = [svc._extract_attrs(it) for it in outfit_items]
        occasion = context.get("occasion")
        score, reasons = svc._occasion_fit(items_attrs, occasion)
        return ScorerResult(score=score, weight=self.weight, reasons=reasons)
