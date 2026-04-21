"""Versatility scorer — how many valid outfit combos does a wardrobe item enable?

Reuses OutfitEngine template logic and filtering without running full scoring,
so it is fast enough for per-item on-demand calls.

Algorithm:
1. Bucket the wardrobe via OutfitEngine._bucket_by_category.
2. For each OUTFIT_TEMPLATE that includes the item's bucket:
   - Iterate candidates via OutfitEngine._iter_template_candidates.
   - Keep only combos that include the target item.
   - Pass each through OutfitEngine._filter_candidate.
   - Count passing combos; accumulate partner co-occurrence counts.
3. is_orphan  = outfit_count < ORPHAN_THRESHOLD (2).
4. top_partners = top-5 partner item_ids by co-occurrence.
5. cost_per_wear = item.cost / item.wear_count (None if either is missing).
6. explanation lines describe why the item is or is not an orphan.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from typing import TYPE_CHECKING

from app.services.analytics.cpw_service import calculate as _cpw_calculate
from app.services.explainer import LABELS
from app.services.outfit_engine import ACCESSORY_LIKE, OUTFIT_TEMPLATES, OutfitEngine

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.services.analytics.item_graph import ItemCompatibilityGraph

logger = logging.getLogger(__name__)

ORPHAN_THRESHOLD: int = 2
MAX_TOP_PARTNERS: int = 5


class VersatilityService:
    def __init__(
        self,
        db: "Session | None" = None,
        *,
        outfit_engine: OutfitEngine | None = None,
    ) -> None:
        self.db = db
        self._engine = outfit_engine or OutfitEngine()

    def compute(
        self,
        item_id: uuid.UUID,
        wardrobe: list[dict],
        user_context: dict | None = None,
    ) -> dict:
        """Compute versatility metrics for a single wardrobe item.

        Args:
            item_id: UUID of the target item (must be present in wardrobe).
            wardrobe: flat list of dicts in OutfitEngine format
                (keys: id, category, and any attributes hoisted at top level).
            user_context: same dict OutfitEngine.generate expects.

        Returns:
            dict matching VersatilityResponse schema.
        """
        ctx = user_context or {}
        target_id = str(item_id)

        target = next(
            (it for it in wardrobe if str(it.get("id")) == target_id),
            None,
        )
        if target is None:
            logger.warning("versatility: item %s not found in wardrobe", item_id)
            return self._empty_result(item_id)

        buckets = OutfitEngine._bucket_by_category(wardrobe)
        target_cat = target.get("category") or ""
        bucket_key = "accessory" if target_cat in ACCESSORY_LIKE else target_cat

        outfit_count = 0
        partner_counter: Counter = Counter()
        last_reject_reasons: list[str] = []

        for template in OUTFIT_TEMPLATES:
            all_roles = list(template["required"]) + list(template["optional"])
            if bucket_key not in all_roles:
                continue

            for combo_items, _ in self._engine._iter_template_candidates(
                template, buckets
            ):
                if target not in combo_items:
                    continue

                ok, reasons = self._engine._filter_candidate(combo_items, ctx)
                if not ok:
                    last_reject_reasons = reasons
                    continue

                outfit_count += 1
                for it in combo_items:
                    pid = str(it.get("id"))
                    if pid != target_id:
                        partner_counter[pid] += 1

        top_partners = [pid for pid, _ in partner_counter.most_common(MAX_TOP_PARTNERS)]
        is_orphan = outfit_count < ORPHAN_THRESHOLD

        wear_count = target.get("wear_count", 0) or 0
        cost_per_wear = _cpw_calculate(self._resolve_cost(target), wear_count)

        explanation = self._build_explanation(
            outfit_count=outfit_count,
            is_orphan=is_orphan,
            top_partners=top_partners,
            cost_per_wear=cost_per_wear,
            wear_count=wear_count,
            last_reject_reasons=last_reject_reasons,
        )

        label, status = _versatility_label(outfit_count, is_orphan)
        return {
            "item_id": target_id,
            "outfit_count": outfit_count,
            "top_partners": top_partners,
            "is_orphan": is_orphan,
            "cost_per_wear": cost_per_wear,
            "explanation": explanation,
            "label": label,
            "status": status,
        }

    @staticmethod
    def _resolve_cost(item: dict) -> float | None:
        cost = item.get("cost")
        if cost is not None:
            return float(cost)
        attrs = item.get("attributes") or item.get("attributes_json") or {}
        if isinstance(attrs, dict) and attrs.get("cost") is not None:
            return float(attrs["cost"])
        return None

    @staticmethod
    def _build_explanation(
        *,
        outfit_count: int,
        is_orphan: bool,
        top_partners: list[str],
        cost_per_wear: float | None,
        wear_count: int,
        last_reject_reasons: list[str],
    ) -> list[str]:
        lines: list[str] = []

        if is_orphan:
            lines.append("Сложно сочетать с другими вещами")
        else:
            lines.append("Хорошо сочетается с гардеробом")

        return lines

    def _empty_result(self, item_id: uuid.UUID) -> dict:
        return {
            "item_id": str(item_id),
            "outfit_count": 0,
            "top_partners": [],
            "is_orphan": True,
            "cost_per_wear": None,
            "explanation": ["Вещь не найдена в гардеробе"],
            "label": LABELS["orphan"],
            "status": "orphan",
        }


def _versatility_label(outfit_count: int, is_orphan: bool) -> tuple[str, str]:
    """Return (human label, machine status) for a versatility result."""
    if is_orphan:
        return LABELS["orphan"], "orphan"
    if outfit_count >= 8:
        return LABELS["high"], "high"
    if outfit_count >= 4:
        return LABELS["medium"], "medium"
    return LABELS["low"], "low"


__all__ = ["VersatilityService", "ORPHAN_THRESHOLD"]
