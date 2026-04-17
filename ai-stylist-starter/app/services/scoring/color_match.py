"""Unified color match evaluation.

Single source of truth for item-vs-palette color scoring used by:
- outfit scoring  (``outfits/scoring/palette_fit.py``)
- shopping evaluator (``shopping/purchase_evaluator._palette_match``)
- analytics  (``analytics/item_graph._color_harmony`` uses item-to-item variant)

``evaluate_color_fit`` scores one item color against a user's season palette.
``evaluate_color_harmony`` scores two item colors against each other.
Both return a ``ColorMatchResult`` dataclass for consistent downstream handling.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.scoring_service import NEUTRAL_COLORS

# Heuristic warm/cool sets used for clash detection
_WARM_COLORS: frozenset[str] = frozenset(
    {"red", "orange", "yellow", "camel", "brown", "coral", "burgundy", "olive",
     "peach", "rust", "terracotta", "gold"}
)
_COOL_COLORS: frozenset[str] = frozenset(
    {"blue", "navy", "purple", "teal", "grey", "gray", "charcoal",
     "lavender", "mint", "sage", "silver"}
)


@dataclass
class ColorMatchResult:
    """Shared result type for all color scoring operations."""

    score: float
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def evaluate_color_fit(
    color: str | None,
    palette_hex: list[str],
    *,
    avoid_hex: list[str] | None = None,
) -> ColorMatchResult:
    """Score how well *color* fits a user's season palette.

    Parameters
    ----------
    color:
        Color name or hex string for the item being scored.
    palette_hex:
        List of hex or name strings from the user's season palette.
    avoid_hex:
        Optional list of colors to penalise.

    Returns
    -------
    ``ColorMatchResult`` with score in [0, 1].

    Score bands
    -----------
    1.00 — neutral color (always fits)
    0.90 — explicit palette match
    0.65 — no match (neutral assumption)
    0.45 — in the avoid list
    """
    if not color:
        return ColorMatchResult(score=0.65, reasons=["color unknown — neutral assumption"])

    c = color.strip().lower()

    if c in NEUTRAL_COLORS:
        return ColorMatchResult(score=1.0, reasons=[f"{c}: neutral — always fits"])

    palette_lower = [p.strip().lower() for p in palette_hex]
    avoid_lower = [a.strip().lower() for a in (avoid_hex or [])]

    if c in palette_lower:
        return ColorMatchResult(score=0.9, reasons=[f"{c}: matches palette"])

    if avoid_lower and c in avoid_lower:
        return ColorMatchResult(
            score=0.45,
            reasons=[],
            warnings=[f"{c}: in avoid list — may clash with your palette"],
        )

    return ColorMatchResult(score=0.65, reasons=[f"{c}: not matched against palette"])


def evaluate_color_harmony(
    color1: str | None,
    color2: str | None,
) -> ColorMatchResult:
    """Score pairwise color harmony between two items.

    Returns a delta score (positive = bonus, negative = penalty) and reasons.
    Used by the item compatibility graph and outfit color_harmony scorer.
    """
    if not color1 or not color2:
        return ColorMatchResult(score=0.0, reasons=[])

    c1 = color1.strip().lower()
    c2 = color2.strip().lower()

    if c1 in NEUTRAL_COLORS and c2 in NEUTRAL_COLORS:
        return ColorMatchResult(score=0.1, reasons=["both neutrals — safe combo"])

    if c1 in NEUTRAL_COLORS or c2 in NEUTRAL_COLORS:
        return ColorMatchResult(score=0.1, reasons=["neutral + accent — versatile"])

    if c1 == c2:
        return ColorMatchResult(score=0.05, reasons=["monochrome look"])

    if (c1 in _WARM_COLORS and c2 in _COOL_COLORS) or (
        c1 in _COOL_COLORS and c2 in _WARM_COLORS
    ):
        return ColorMatchResult(
            score=-0.15,
            reasons=[],
            warnings=[f"warm/cool clash: {c1} vs {c2}"],
        )

    return ColorMatchResult(score=0.0, reasons=[])
