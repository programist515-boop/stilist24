"""Wardrobe gap analysis service.

Identifies:
1. Missing wardrobe categories and projects how many new outfits each
   suggested item would unlock.
2. Existing items that rarely appear in valid outfit combinations (untapped).

Reuses:
  OutfitEngine._bucket_by_category  (staticmethod)
  OutfitEngine._iter_template_candidates
  OutfitEngine._filter_candidate
  OUTFIT_TEMPLATES, ACCESSORY_LIKE
"""

from __future__ import annotations

import logging
import uuid as _uuid_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from app.services.explainer import gap_action_label
from app.services.outfit_engine import ACCESSORY_LIKE, OUTFIT_TEMPLATES, OutfitEngine

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_RULES_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "config/rules/gap_analysis_rules.yaml"
)

ALL_CATEGORIES: tuple[str, ...] = (
    "top", "bottom", "dress", "shoes", "outerwear", "accessory",
)


def _load_gap_rules() -> dict:
    with _RULES_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("gap_analysis", {})


class GapAnalysisService:
    def __init__(
        self,
        db: "Session | None" = None,
        *,
        outfit_engine: OutfitEngine | None = None,
    ) -> None:
        self.db = db
        self._engine = outfit_engine or OutfitEngine()
        self._rules = _load_gap_rules()

    def analyze(
        self,
        wardrobe: list[dict],
        user_context: dict | None = None,
    ) -> dict:
        """Run gap analysis on a user's wardrobe.

        Args:
            wardrobe: list of item dicts in OutfitEngine format
                (keys: id, category, attributes hoisted at top level).
            user_context: same dict OutfitEngine.generate expects.

        Returns:
            dict matching GapAnalysisResponse schema.
        """
        ctx = user_context or {}
        notes: list[str] = []

        if not wardrobe:
            notes.append("Гардероб пуст — добавьте вещи")
            return {
                "suggestions": [],
                "untapped_items": [],
                "missing_categories": list(ALL_CATEGORIES),
                "notes": notes,
            }

        buckets = OutfitEngine._bucket_by_category(wardrobe)
        owned_categories = {cat for cat, items in buckets.items() if items}
        missing_categories = [
            cat for cat in ALL_CATEGORIES if cat not in owned_categories
        ]

        item_combo_counts = self._count_current_combos(wardrobe, buckets, ctx)

        suggestions = self._build_suggestions(
            missing_categories, buckets, ctx, owned_categories
        )

        untapped_threshold = self._rules.get("untapped_threshold", 2)
        untapped_items = self._find_untapped(
            wardrobe, item_combo_counts, buckets, untapped_threshold
        )

        return {
            "suggestions": suggestions,
            "untapped_items": untapped_items,
            "missing_categories": missing_categories,
            "notes": notes,
        }

    # ---------------------------------------------------------------- private

    def _count_current_combos(
        self,
        wardrobe: list[dict],
        buckets: dict[str, list[dict]],
        ctx: dict,
    ) -> dict[str, int]:
        counts: dict[str, int] = {str(it.get("id")): 0 for it in wardrobe}
        for template in OUTFIT_TEMPLATES:
            for combo_items, _ in self._engine._iter_template_candidates(
                template, buckets
            ):
                ok, _ = self._engine._filter_candidate(combo_items, ctx)
                if not ok:
                    continue
                for it in combo_items:
                    iid = str(it.get("id"))
                    if iid in counts:
                        counts[iid] += 1
        return counts

    def _build_suggestions(
        self,
        missing_categories: list[str],
        buckets: dict[str, list[dict]],
        ctx: dict,
        owned_categories: set[str],
    ) -> list[dict]:
        suggestions: list[dict] = []
        suggestion_defs = self._rules.get("suggestions", {})
        scored: list[tuple[int, dict]] = []

        for missing_cat in missing_categories:
            cat_defs = suggestion_defs.get(missing_cat, [])
            for suggestion_def in cat_defs[:2]:
                new_combos = self._project_new_combos(
                    buckets, missing_cat, suggestion_def, ctx
                )
                if new_combos == 0:
                    continue
                label = suggestion_def.get("label", missing_cat)
                scored.append((
                    new_combos,
                    {
                        "item": label,
                        "category": missing_cat,
                        "why": "Добавит много новых сочетаний",
                        "action": gap_action_label(missing_cat),
                    },
                ))

        scored.sort(key=lambda row: -row[0])
        for _, suggestion in scored:
            suggestions.append(suggestion)
        return suggestions

    def _project_new_combos(
        self,
        buckets: dict[str, list[dict]],
        missing_cat: str,
        suggestion_def: dict[str, Any],
        ctx: dict,
    ) -> int:
        synthetic_id = str(_uuid_module.uuid4())
        synthetic: dict[str, Any] = {
            "id": synthetic_id,
            "category": missing_cat,
            "line_type": suggestion_def.get("line_type", "clean"),
            "fit": suggestion_def.get("fit", "regular"),
            "style_tags": suggestion_def.get("style_tags", ["classic"]),
            "occasions": suggestion_def.get("occasions", []),
            "formality": self._infer_formality(
                suggestion_def.get("occasions", [])
            ),
        }

        bucket_key = "accessory" if missing_cat in ACCESSORY_LIKE else missing_cat
        projected = {cat: list(items) for cat, items in buckets.items()}
        projected.setdefault(bucket_key, []).append(synthetic)

        new_count = 0
        for template in OUTFIT_TEMPLATES:
            for combo_items, _ in self._engine._iter_template_candidates(
                template, projected
            ):
                if synthetic not in combo_items:
                    continue
                ok, _ = self._engine._filter_candidate(combo_items, ctx)
                if ok:
                    new_count += 1

        return new_count

    def _find_untapped(
        self,
        wardrobe: list[dict],
        item_combo_counts: dict[str, int],
        buckets: dict[str, list[dict]],
        threshold: int,
    ) -> list[dict]:
        untapped: list[dict] = []
        for it in wardrobe:
            iid = str(it.get("id"))
            count = item_combo_counts.get(iid, 0)
            if count < threshold:
                cat = it.get("category") or "unknown"
                reason = self._untapped_reason(it, cat, count, buckets)
                untapped.append({
                    "item_id": iid,
                    "category": cat,
                    "outfit_count": count,
                    "reason": reason,
                })
        untapped.sort(key=lambda u: u["outfit_count"])
        return untapped

    @staticmethod
    def _untapped_reason(
        item: dict,
        category: str,
        count: int,
        buckets: dict[str, list[dict]],
    ) -> str:
        if count == 0:
            return "Почти не используется"
        return "Сложно сочетать с другими вещами"

    @staticmethod
    def _infer_formality(occasions: list[str]) -> str:
        if "formal" in occasions:
            return "formal"
        if "business" in occasions:
            return "business"
        if "smart_casual" in occasions:
            return "smart_casual"
        return "casual"


__all__ = ["GapAnalysisService"]
