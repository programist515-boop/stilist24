"""Item compatibility graph.

Builds a pairwise compatibility map over a wardrobe: each (item_a, item_b)
edge carries a score in [0, 1] and a list of reasons. Uses the same rule
sources as ``ScoringService`` (YAML rules + NEUTRAL_COLORS) but operates on
pairs of items rather than item-vs-user-profile.

No external graph library is required — the graph is a plain adjacency dict.
"""

from __future__ import annotations

from typing import Any

from app.services.scoring.color_match import evaluate_color_harmony
from app.services.scoring_service import NEUTRAL_COLORS

# ---------------------------------------------------------------------------
# Category pair rules
# ---------------------------------------------------------------------------

# Hard incompatible pairs (score 0 regardless of other factors)
_INCOMPATIBLE_PAIRS: frozenset[frozenset] = frozenset(
    {
        frozenset({"tops", "dresses"}),   # dress already covers top slot
        frozenset({"bottoms", "dresses"}),
        frozenset({"tops", "bottoms", "dresses"}),  # handled via subsets
    }
)

# Pairs that form natural outfit building blocks (base compatibility bonus)
_SYNERGY_PAIRS: frozenset[frozenset] = frozenset(
    {
        frozenset({"tops", "bottoms"}),
        frozenset({"tops", "shoes"}),
        frozenset({"dresses", "shoes"}),
        frozenset({"tops", "outerwear"}),
        frozenset({"dresses", "outerwear"}),
        frozenset({"bottoms", "shoes"}),
        frozenset({"tops", "accessories"}),
        frozenset({"dresses", "accessories"}),
        frozenset({"outerwear", "accessories"}),
    }
)

# Formality rank: higher = more formal
_FORMALITY_RANK: dict[str, int] = {
    "sport": 0,
    "casual": 1,
    "smart_casual": 2,
    "business_casual": 3,
    "business": 4,
    "formal": 5,
    "evening": 5,
    "outdoor": 1,
    "beach": 0,
    "loungewear": 0,
}

# Seasons that can overlap (spring_summer covers spring + summer, etc.)
_SEASON_EXPANSIONS: dict[str, frozenset[str]] = {
    "spring": frozenset({"spring", "spring_summer", "all_season"}),
    "summer": frozenset({"summer", "spring_summer", "all_season"}),
    "autumn": frozenset({"autumn", "autumn_winter", "all_season"}),
    "winter": frozenset({"winter", "autumn_winter", "all_season"}),
    "spring_summer": frozenset({"spring_summer", "spring", "summer", "all_season"}),
    "autumn_winter": frozenset({"autumn_winter", "autumn", "winter", "all_season"}),
    "all_season": frozenset({"spring", "summer", "autumn", "winter", "spring_summer", "autumn_winter", "all_season"}),
}


def _extract_val(attrs: dict, field: str) -> str | None:
    """Get value from v2 AttributeField dict or flat string."""
    v = attrs.get(field)
    if isinstance(v, dict):
        return v.get("value")
    return v


def _season_overlap(s1: str | None, s2: str | None) -> bool:
    if not s1 or not s2:
        return True  # unknown → assume compatible
    if s1 == s2 or s1 == "all_season" or s2 == "all_season":
        return True
    expanded1 = _SEASON_EXPANSIONS.get(s1, frozenset({s1}))
    expanded2 = _SEASON_EXPANSIONS.get(s2, frozenset({s2}))
    return bool(expanded1 & expanded2)


def _formality_gap(occ1: str | None, occ2: str | None) -> int:
    if not occ1 or not occ2:
        return 0
    r1 = _FORMALITY_RANK.get(occ1, 2)
    r2 = _FORMALITY_RANK.get(occ2, 2)
    return abs(r1 - r2)


def _color_harmony(color1: str | None, color2: str | None) -> tuple[float, str]:
    """Pairwise color harmony check. Delegates to the canonical scorer."""
    result = evaluate_color_harmony(color1, color2)
    reason = (result.reasons + result.warnings + [""])[0]
    return result.score, reason


def compatibility_score(
    item_a: dict[str, Any],
    item_b: dict[str, Any],
) -> dict[str, Any]:
    """Compute pairwise compatibility between two wardrobe item dicts.

    Each item dict must have ``category`` and ``attributes`` (or top-level
    attribute keys). Returns ``{score, reasons, warnings}``.
    """
    reasons: list[str] = []
    warnings: list[str] = []
    score = 0.5  # neutral baseline

    attrs_a = _item_attrs(item_a)
    attrs_b = _item_attrs(item_b)

    cat_a = (item_a.get("category") or _extract_val(attrs_a, "category") or "").lower()
    cat_b = (item_b.get("category") or _extract_val(attrs_b, "category") or "").lower()

    # --- category pair rules ---
    pair = frozenset({cat_a, cat_b})

    # Hard incompatibility (e.g. top + dress)
    if any(p.issubset(pair) and len(p) == 2 for p in _INCOMPATIBLE_PAIRS if len(p) == 2):
        return {"score": 0.0, "reasons": [f"incompatible categories: {cat_a} + {cat_b}"], "warnings": []}

    if pair in _SYNERGY_PAIRS:
        score += 0.2
        reasons.append(f"natural outfit pair: {cat_a} + {cat_b}")

    # --- season overlap ---
    seas_a = _extract_val(attrs_a, "seasonality")
    seas_b = _extract_val(attrs_b, "seasonality")
    if not _season_overlap(seas_a, seas_b):
        score -= 0.25
        warnings.append(f"season mismatch: {seas_a} vs {seas_b}")
    elif seas_a and seas_b:
        reasons.append(f"compatible seasons: {seas_a} / {seas_b}")

    # --- formality gap ---
    occ_a = _extract_val(attrs_a, "occasion")
    occ_b = _extract_val(attrs_b, "occasion")
    gap = _formality_gap(occ_a, occ_b)
    if gap >= 3:
        score -= 0.30
        warnings.append(f"formality clash ({occ_a} vs {occ_b}, gap={gap})")
    elif gap == 2:
        score -= 0.10
        warnings.append(f"formality mismatch ({occ_a} vs {occ_b})")
    elif gap <= 1 and occ_a and occ_b:
        reasons.append(f"compatible formality: {occ_a} / {occ_b}")

    # --- color harmony ---
    color_a = _extract_val(attrs_a, "primary_color")
    color_b = _extract_val(attrs_b, "primary_color")
    delta, harmony_reason = _color_harmony(color_a, color_b)
    score += delta
    if harmony_reason:
        (warnings if delta < 0 else reasons).append(harmony_reason)

    # --- silhouette volume clash: two oversized pieces ---
    fit_a = _extract_val(attrs_a, "fit")
    fit_b = _extract_val(attrs_b, "fit")
    if fit_a == "oversized" and fit_b == "oversized":
        score -= 0.15
        warnings.append("both pieces oversized — high volume clash risk")

    return {
        "score": round(max(0.0, min(1.0, score)), 3),
        "reasons": reasons,
        "warnings": warnings,
    }


def _item_attrs(item: dict[str, Any]) -> dict:
    """Extract the attributes dict from an item dict."""
    attrs = item.get("attributes")
    if isinstance(attrs, dict):
        return attrs
    return item


class ItemCompatibilityGraph:
    """Builds and queries pairwise compatibility across a wardrobe.

    ``build()`` computes all pairs; ``get_partners()`` returns the top-N
    most compatible items for a given item_id.
    """

    def __init__(self) -> None:
        # adjacency: {item_id_str: {other_id_str: result_dict}}
        self._adj: dict[str, dict[str, dict]] = {}

    def build(self, items: list[dict[str, Any]]) -> "ItemCompatibilityGraph":
        """Compute compatibility for all pairs in ``items``.

        Items must have an ``id`` key.
        """
        self._adj = {}
        for i, item_a in enumerate(items):
            id_a = str(item_a.get("id", i))
            if id_a not in self._adj:
                self._adj[id_a] = {}
            for j, item_b in enumerate(items):
                if i >= j:
                    continue
                id_b = str(item_b.get("id", j))
                result = compatibility_score(item_a, item_b)
                self._adj.setdefault(id_a, {})[id_b] = result
                self._adj.setdefault(id_b, {})[id_a] = result
        return self

    def get_partners(self, item_id: str, top_n: int = 5) -> list[dict]:
        """Return top-N most compatible items for ``item_id``.

        Each entry: ``{partner_id, score, reasons, warnings}``.
        """
        edges = self._adj.get(str(item_id), {})
        ranked = sorted(edges.items(), key=lambda kv: kv[1]["score"], reverse=True)
        return [
            {"partner_id": pid, **result}
            for pid, result in ranked[:top_n]
        ]

    def edge_count(self, item_id: str, min_score: float = 0.5) -> int:
        """Count how many items have a compatibility score >= min_score."""
        edges = self._adj.get(str(item_id), {})
        return sum(1 for r in edges.values() if r["score"] >= min_score)

    def all_scores(self, item_id: str) -> dict[str, float]:
        """Return {partner_id: score} for all edges from item_id."""
        return {pid: r["score"] for pid, r in self._adj.get(str(item_id), {}).items()}
