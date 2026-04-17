"""Unified outfit scorer — delegates to individual sub-scorers.

Replaces the monolithic ``ScoringService.score_outfit`` with a plug-in
architecture. Every scorer returns a :class:`ScorerResult`; the overall
score is the weighted sum of all sub-scores.

Default weights:
  color_harmony     0.30  (from outfit_rules.yaml)
  silhouette        0.25
  preference        0.15
  palette_fit       0.15  (new Sprint 3)
  occasion          0.10
  reuse             0.10  (new Sprint 3)
  weather           0.10  (new Sprint 3)

When weather and palette_fit are unused (no context), they return 0.5 and
do not dominate the final score. Their weights are proportionally normalised
before summing so the total always sums to 1.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.outfits.scoring.base import ScorerResult
from app.services.outfits.scoring.color_harmony import ColorHarmonyScorer
from app.services.outfits.scoring.occasion import OccasionScorer
from app.services.outfits.scoring.palette_fit import PaletteFitScorer
from app.services.outfits.scoring.preference import PreferenceScorer
from app.services.outfits.scoring.reuse import ReuseScorer
from app.services.outfits.scoring.silhouette import SilhouetteScorer
from app.services.outfits.scoring.weather import WeatherScorer


@dataclass
class OutfitScore:
    """Aggregated outfit score with per-scorer breakdown."""

    total: float
    breakdown: dict[str, ScorerResult] = field(default_factory=dict)

    @property
    def reasons(self) -> list[str]:
        out: list[str] = []
        for r in self.breakdown.values():
            out.extend(r.reasons)
        return out

    @property
    def warnings(self) -> list[str]:
        out: list[str] = []
        for r in self.breakdown.values():
            out.extend(r.warnings)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "breakdown": {
                name: {
                    "score": r.score,
                    "weight": r.weight,
                    "reasons": r.reasons,
                    "warnings": r.warnings,
                }
                for name, r in self.breakdown.items()
            },
            "reasons": self.reasons,
            "warnings": self.warnings,
        }


_DEFAULT_SCORERS: dict[str, type] = {
    "color_harmony": ColorHarmonyScorer,
    "silhouette": SilhouetteScorer,
    "preference": PreferenceScorer,
    "palette_fit": PaletteFitScorer,
    "occasion": OccasionScorer,
    "reuse": ReuseScorer,
    "weather": WeatherScorer,
}


class OutfitScorer:
    """Calls all registered sub-scorers and aggregates into a single score.

    Weights are taken from each scorer's ``weight`` class attribute. They are
    normalised to sum to 1.0 so adding or removing scorers doesn't require
    manual re-balancing.
    """

    def __init__(
        self,
        scorers: dict[str, Any] | None = None,
    ) -> None:
        """Instantiate with optional scorer override map.

        Parameters
        ----------
        scorers:
            ``{name: scorer_instance}`` mapping. Defaults to all scorers in
            ``_DEFAULT_SCORERS``.
        """
        if scorers is not None:
            self._scorers = scorers
        else:
            self._scorers = {name: cls() for name, cls in _DEFAULT_SCORERS.items()}

    def score(
        self,
        outfit_items: list[dict],
        user_profile: dict | None = None,
        context: dict | None = None,
    ) -> OutfitScore:
        """Score an outfit.

        Parameters
        ----------
        outfit_items:
            List of wardrobe item dicts.
        user_profile:
            User identity/color profile. Merged into ``context`` if provided.
        context:
            Runtime context (occasion, weather, palette_hex, …).
        """
        ctx: dict = {}
        if user_profile:
            ctx.update(user_profile)
        if context:
            ctx.update(context)

        breakdown: dict[str, ScorerResult] = {}
        for name, scorer in self._scorers.items():
            breakdown[name] = scorer.score(outfit_items, ctx)

        total = _weighted_total(breakdown)
        return OutfitScore(total=round(total, 3), breakdown=breakdown)


def _weighted_total(breakdown: dict[str, ScorerResult]) -> float:
    """Normalised weighted average."""
    total_weight = sum(r.weight for r in breakdown.values())
    if total_weight == 0:
        return 0.0
    return sum(r.score * r.weight for r in breakdown.values()) / total_weight
