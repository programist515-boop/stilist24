"""Outfit generator — uses OutfitScorer + DiversityReranker.

Drop-in upgrade path over the existing ``OutfitEngine``:
* Templates are loaded from ``data/outfit_templates.yaml``.
* Scoring uses ``OutfitScorer`` (7 sub-scorers with breakdown).
* ``generate_for_item`` — anchor-item mode for versatility/detail pages.
* ``generate_for_occasion`` — occasion-filtered generation.
* ``generate_daily`` — {safe, balanced, expressive} daily picks.

The low-level candidate iteration and structural filtering are reused from
``OutfitEngine`` to keep the code DRY.
"""

from __future__ import annotations

import logging
from itertools import product
from pathlib import Path
from typing import Any

import yaml

from app.services.outfit_engine import ACCESSORY_LIKE, OutfitEngine
from app.services.outfits.diversity_reranker import rerank
from app.services.outfits.outfit_scorer import OutfitScore, OutfitScorer

logger = logging.getLogger(__name__)

_TEMPLATES_PATH = Path(__file__).parent.parent.parent.parent / "data" / "outfit_templates.yaml"

_MAX_TOTAL_CANDIDATES = 2000
_MAX_ACCEPTED_FOR_SCORING = 500


def _load_templates() -> list[dict]:
    try:
        with open(_TEMPLATES_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("templates", [])
    except FileNotFoundError:
        logger.warning("outfit_templates.yaml not found — falling back to OutfitEngine templates")
        from app.services.outfit_engine import OUTFIT_TEMPLATES
        return [
            {"name": t["name"], "required": list(t["required"]), "optional": list(t["optional"])}
            for t in OUTFIT_TEMPLATES
        ]


class OutfitGenerator:
    """Template-driven outfit generator with explainable per-scorer breakdown."""

    DEFAULT_TOP_N = 20

    def __init__(
        self,
        scorer: OutfitScorer | None = None,
        *,
        max_total_candidates: int = _MAX_TOTAL_CANDIDATES,
        max_accepted_for_scoring: int = _MAX_ACCEPTED_FOR_SCORING,
    ) -> None:
        self._scorer = scorer or OutfitScorer()
        self._engine = OutfitEngine()  # reuse candidate iteration + filtering
        self._templates = _load_templates()
        self.max_total_candidates = max_total_candidates
        self.max_accepted_for_scoring = max_accepted_for_scoring

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        items: list[dict],
        user_profile: dict | None = None,
        context: dict | None = None,
        *,
        occasion: str | None = None,
        top_n: int | None = None,
    ) -> list[dict]:
        """Generate diverse, scored outfits from the full wardrobe.

        Returns a list of outfit dicts — same shape as ``OutfitEngine.generate``
        but with ``breakdown`` and ``total`` added to the score envelope.
        """
        ctx: dict = {}
        if user_profile:
            ctx.update(user_profile)
        if context:
            ctx.update(context)
        if occasion:
            ctx.setdefault("occasion", occasion)

        candidates = self._build_candidates(items, ctx)
        return rerank(candidates, top_n or self.DEFAULT_TOP_N)

    def generate_for_item(
        self,
        item_id: str,
        items: list[dict],
        user_profile: dict | None = None,
        context: dict | None = None,
        *,
        top_n: int = 10,
    ) -> list[dict]:
        """Generate outfits that include a specific anchor item.

        Parameters
        ----------
        item_id:
            The ``id`` of the item to anchor every outfit on.
        items:
            Full wardrobe list.
        """
        ctx: dict = {}
        if user_profile:
            ctx.update(user_profile)
        if context:
            ctx.update(context)

        all_candidates = self._build_candidates(items, ctx, anchor_item_id=str(item_id))
        return rerank(all_candidates, top_n)

    def generate_for_occasion(
        self,
        occasion: str,
        items: list[dict],
        user_profile: dict | None = None,
        context: dict | None = None,
        *,
        top_n: int | None = None,
    ) -> list[dict]:
        """Generate outfits filtered for a specific occasion."""
        ctx: dict = {}
        if user_profile:
            ctx.update(user_profile)
        if context:
            ctx.update(context)
        ctx["occasion"] = occasion
        candidates = self._build_candidates(items, ctx)
        return rerank(candidates, top_n or self.DEFAULT_TOP_N)

    def generate_daily(
        self,
        items: list[dict],
        user_profile: dict | None = None,
        context: dict | None = None,
    ) -> dict[str, list[dict]]:
        """Return three curated daily picks.

        * ``safe``       — high-scoring, familiar combinations
        * ``balanced``   — mid-range score, rotation-bonus items
        * ``expressive`` — lower overall score but more personality (low reuse signal)
        """
        ctx: dict = {}
        if user_profile:
            ctx.update(user_profile)
        if context:
            ctx.update(context)

        all_candidates = self._build_candidates(items, ctx)
        if not all_candidates:
            return {"safe": [], "balanced": [], "expressive": []}

        sorted_by_score = sorted(
            all_candidates,
            key=lambda o: o["scores"].get("overall", 0.0),
            reverse=True,
        )

        safe = rerank(sorted_by_score[:30], 3)

        # balanced: pick from mid-tier, prefer rotation (reuse scorer bonus)
        mid_tier = sorted_by_score[len(sorted_by_score) // 4 : len(sorted_by_score) * 3 // 4]
        mid_tier.sort(
            key=lambda o: o["scores"].get("reuse", 0.0),
            reverse=True,
        )
        balanced = rerank(mid_tier[:30], 3)

        # expressive: lowest reuse scorer (items that push boundaries)
        bottom_tier = sorted_by_score[len(sorted_by_score) // 2 :]
        bottom_tier.sort(
            key=lambda o: -o["scores"].get("reuse", 0.0),
        )
        expressive = rerank(bottom_tier[:30], 3)

        return {"safe": safe, "balanced": balanced, "expressive": expressive}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_candidates(
        self,
        items: list[dict],
        ctx: dict,
        *,
        anchor_item_id: str | None = None,
    ) -> list[dict]:
        import time
        _t0 = time.perf_counter()
        buckets = OutfitEngine._bucket_by_category(items)
        scored: list[dict] = []
        total_candidates = 0
        accepted = 0

        for template in self._templates:
            required = template["required"]
            optional = template.get("optional") or []

            # Skip templates that don't involve the anchor item's bucket
            if anchor_item_id is not None:
                anchor_item = next(
                    (it for it in items if str(it.get("id")) == anchor_item_id),
                    None,
                )
                if anchor_item is None:
                    continue
                anchor_cat = anchor_item.get("category") or ""
                bucket_key = "accessory" if anchor_cat in ACCESSORY_LIKE else anchor_cat
                all_roles = list(required) + list(optional)
                if bucket_key not in all_roles:
                    continue

            if any(not buckets.get(cat) for cat in required):
                continue

            for combo_items, used_optional in self._engine._iter_template_candidates(
                {"name": template["name"], "required": required, "optional": optional},
                buckets,
            ):
                if total_candidates >= self.max_total_candidates:
                    break
                if accepted >= self.max_accepted_for_scoring:
                    break
                total_candidates += 1

                # Anchor filter
                if anchor_item_id is not None:
                    if not any(str(it.get("id")) == anchor_item_id for it in combo_items):
                        continue

                ok, filter_reasons = self._engine._filter_candidate(combo_items, ctx)
                if not ok:
                    continue

                outfit_score: OutfitScore = self._scorer.score(combo_items, context=ctx)
                scores = {
                    name: result.score
                    for name, result in outfit_score.breakdown.items()
                }
                scores["overall"] = outfit_score.total

                outfit = {
                    "items": combo_items,
                    "occasion": ctx.get("occasion"),
                    "scores": scores,
                    "total_score": outfit_score.total,
                    "breakdown": outfit_score.to_dict()["breakdown"],
                    "filter_pass_reasons": filter_reasons,
                    "reasons": outfit_score.reasons,
                    "warnings": outfit_score.warnings,
                    "explanation": filter_reasons + outfit_score.reasons,
                    "generation": {
                        "template": template["name"],
                        "optional_used": used_optional,
                    },
                    "outfit_source": "generator",
                }
                scored.append(outfit)
                accepted += 1

        elapsed = time.perf_counter() - _t0
        logger.debug(
            "outfit_generator: %d candidates accepted from %d total in %.3fs",
            accepted,
            total_candidates,
            elapsed,
        )
        if elapsed > 2.0:
            logger.warning(
                "outfit_generator: slow generation %.3fs — wardrobe size=%d, "
                "accepted=%d/%d",
                elapsed,
                len(items),
                accepted,
                total_candidates,
            )
        return scored
