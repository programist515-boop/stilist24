"""Redundancy service — finds duplicate, near-duplicate, and over-concentrated items.

Three cluster types:
  - ``duplicate``:      same category + same primary_color + same occasion
  - ``near_duplicate``: same category + same primary_color, different occasion
  - ``same_role``:      4+ items in the same category (over-concentration)
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _extract_val(attrs: dict, field: str) -> str | None:
    v = attrs.get(field)
    if isinstance(v, dict):
        return v.get("value")
    return v


def _item_key(item: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else item
    cat = (item.get("category") or _extract_val(attrs, "category") or "").lower() or None
    color = (_extract_val(attrs, "primary_color") or "").lower() or None
    occ = (_extract_val(attrs, "occasion") or "").lower() or None
    return cat, color, occ


def cluster(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect redundancy clusters across a list of wardrobe item dicts.

    Each item must have ``id``, ``category``, and ``attributes``.
    Returns a list of cluster dicts: ``{type, item_ids, reason}``.
    """
    clusters: list[dict[str, Any]] = []
    id_of = lambda item: str(item.get("id", ""))  # noqa: E731

    # Build indexes
    # (category, color, occasion) → list of items  →  duplicates
    # (category, color)           → list of items  →  near-duplicates
    # category                    → list of items  →  same-role
    exact: dict[tuple, list] = defaultdict(list)
    approx: dict[tuple, list] = defaultdict(list)
    by_cat: dict[str, list] = defaultdict(list)

    for item in items:
        cat, color, occ = _item_key(item)
        exact[(cat, color, occ)].append(item)
        approx[(cat, color)].append(item)
        if cat:
            by_cat[cat].append(item)

    seen_ids: set[str] = set()

    # --- duplicates: same cat+color+occasion, 2+ items ---
    for (cat, color, occ), group in exact.items():
        if len(group) < 2:
            continue
        ids = [id_of(i) for i in group]
        if not (cat and color):
            continue
        frozen = frozenset(ids)
        if frozen & seen_ids:
            continue
        seen_ids |= frozen
        reason = f"same {cat} in {color or '?'} for {occ or '?'} occasions ({len(ids)} items)"
        clusters.append({"type": "duplicate", "item_ids": ids, "reason": reason})

    # --- near-duplicates: same cat+color, different occasions, 2+ items ---
    for (cat, color), group in approx.items():
        if len(group) < 2 or not (cat and color):
            continue
        ids = [id_of(i) for i in group]
        frozen = frozenset(ids)
        if frozen.issubset(seen_ids):
            continue  # already flagged as exact duplicate
        new_ids = [i for i in ids if i not in seen_ids]
        if len(new_ids) < 2:
            continue
        seen_ids |= frozenset(new_ids)
        reason = f"very similar {cat} items in {color} ({len(ids)} items, different occasions)"
        clusters.append({"type": "near_duplicate", "item_ids": ids, "reason": reason})

    # --- same-role: 4+ items in the same category ---
    _SAME_ROLE_THRESHOLD = 4
    for cat, group in by_cat.items():
        if len(group) < _SAME_ROLE_THRESHOLD:
            continue
        ids = [id_of(i) for i in group]
        reason = f"{len(ids)} {cat} items — possible over-concentration in this category"
        clusters.append({"type": "same_role", "item_ids": ids, "reason": reason})

    return clusters


def redundancy_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Return clusters plus a human-readable summary."""
    found = cluster(items)
    duplicate_count = sum(1 for c in found if c["type"] == "duplicate")
    near_dup_count = sum(1 for c in found if c["type"] == "near_duplicate")
    same_role_count = sum(1 for c in found if c["type"] == "same_role")
    notes = []
    if not found:
        notes.append("No significant redundancy detected.")
    if duplicate_count:
        notes.append(f"{duplicate_count} duplicate group(s) found — consider parting with one.")
    if near_dup_count:
        notes.append(f"{near_dup_count} near-duplicate group(s) — similar items filling the same role.")
    if same_role_count:
        notes.append(f"{same_role_count} over-concentrated category(ies) — try diversifying.")
    return {
        "clusters": found,
        "duplicate_count": duplicate_count,
        "near_duplicate_count": near_dup_count,
        "same_role_count": same_role_count,
        "notes": notes,
    }
