"""Silhouette balance scorer — extracted from ScoringService._silhouette_balance."""

from __future__ import annotations

from app.services.outfits.scoring.base import BaseScorer, ScorerResult


class SilhouetteScorer(BaseScorer):
    """Checks that silhouettes complement each other across outfit pieces."""

    weight: float = 0.25

    def score(self, outfit_items: list[dict], context: dict) -> ScorerResult:
        from app.services.scoring_service import ScoringService

        svc = ScoringService()
        items_attrs = [svc._extract_attrs(it) for it in outfit_items]
        family = svc.normalize_identity_family(context.get("identity_family"))
        score, reasons = svc._silhouette_balance(items_attrs, family)
        return ScorerResult(score=score, weight=self.weight, reasons=reasons)
