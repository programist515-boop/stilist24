"""Diversity reranker — extracted from OutfitEngine._reduce_diversity.

Collapses near-duplicate outfits (same base items, different accessories /
optional layers) and biases the top-N picks toward wardrobe coverage.
"""

from __future__ import annotations

from typing import Any

#: Two scores within this distance are considered tied.
TIE_TOLERANCE: float = 0.005

#: Categories treated as accessories (excluded from the base signature check
#: so dress+heels+bag and dress+heels+clutch collapse to the same base).
_ACCESSORY_LIKE: frozenset[str] = frozenset({"accessory", "bag", "jewelry", "hat"})


def _base_signature(outfit: dict) -> tuple:
    """Semantic signature = ``(template, sorted((category, id) pairs))``.

    Excludes accessory-like items so two outfits that differ only by which
    accessory is attached collapse to the same signature while keeping
    "with outerwear" vs "without outerwear" as distinct choices.
    """
    template = (outfit.get("generation") or {}).get("template", "")
    pairs = tuple(
        sorted(
            (it.get("category") or "", str(it.get("id")))
            for it in outfit.get("items", [])
            if it.get("category") not in _ACCESSORY_LIKE
            and it.get("id") is not None
        )
    )
    return (template, pairs)


def _outfit_score(outfit: dict) -> float:
    """Extract the primary sort score from an outfit dict."""
    scores = outfit.get("scores") or {}
    return scores.get("overall", scores.get("total", 0.0))


def rerank(
    outfits: list[dict[str, Any]],
    max_n: int,
    *,
    tie_tolerance: float = TIE_TOLERANCE,
) -> list[dict[str, Any]]:
    """Return at most ``max_n`` diverse, high-scoring outfits.

    Algorithm:
    1. Keep only the best-scoring outfit per base signature (deduplication).
    2. Sort by score descending.
    3. At each pick, scan the tie band (within ``tie_tolerance``) and prefer
       the outfit that introduces the most previously-unseen item ids.
    """
    # --- step 1: deduplicate by signature ---
    by_sig: dict[tuple, dict] = {}
    for outfit in outfits:
        sig = _base_signature(outfit)
        incumbent = by_sig.get(sig)
        if incumbent is None or _outfit_score(outfit) > _outfit_score(incumbent):
            by_sig[sig] = outfit

    deduped = sorted(by_sig.values(), key=_outfit_score, reverse=True)

    # --- step 2: greedy wardrobe-coverage pick ---
    picked: list[dict] = []
    seen_ids: set[str] = set()
    remaining = list(deduped)

    while remaining and len(picked) < max_n:
        best_score = _outfit_score(remaining[0])
        tie_band = [
            o for o in remaining
            if best_score - _outfit_score(o) <= tie_tolerance
        ]
        # Within the band, prefer the outfit that introduces the most new item ids
        tie_band.sort(
            key=lambda o: (
                -sum(
                    1 for it in o.get("items", [])
                    if str(it.get("id")) not in seen_ids
                ),
                tuple(str(it.get("id")) for it in o.get("items", [])),
            )
        )
        chosen = tie_band[0]
        picked.append(chosen)
        remaining.remove(chosen)
        for it in chosen.get("items", []):
            if it.get("id") is not None:
                seen_ids.add(str(it["id"]))

    return picked
