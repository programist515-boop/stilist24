"""Base scorer protocol and result dataclass for the outfit scoring pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ScorerResult:
    """Result from a single scorer.

    ``score`` is in [0, 1]. ``weight`` is the scorer's contribution to the
    overall total. ``reasons`` are positive signals; ``warnings`` are
    negatives or caveats.
    """

    score: float
    weight: float
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def weighted(self) -> float:
        return self.score * self.weight


class BaseScorer(ABC):
    """Abstract base for outfit-level sub-scorers."""

    weight: float = 1.0

    @abstractmethod
    def score(self, outfit_items: list[dict], context: dict) -> ScorerResult:
        """Score an outfit given the user context.

        Parameters
        ----------
        outfit_items:
            List of wardrobe item dicts (each has ``category``, ``attributes``).
        context:
            User context dict — same shape as ``OutfitEngine.generate`` expects.

        Returns
        -------
        :class:`ScorerResult`
        """
        ...

    # ------------------------------------------------------------------
    # Shared attribute extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _item_attrs(item: dict) -> dict:
        attrs = item.get("attributes")
        if isinstance(attrs, dict):
            return attrs
        return item

    @staticmethod
    def _extract_val(attrs: dict, field_name: str) -> str | None:
        v = attrs.get(field_name)
        if isinstance(v, dict):
            return v.get("value")
        return v
