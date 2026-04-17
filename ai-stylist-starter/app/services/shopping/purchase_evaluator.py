"""Purchase evaluator — buy / maybe / skip decision.

Six sub-scores, each in [0, 1]:
  1. palette_match       — color fit against user's season palette
  2. gap_fill            — fills a detected wardrobe gap
  3. wardrobe_compat     — compatible with existing items
  4. redundancy_penalty  — inverse of how duplicate-like it is
  5. expected_versatility — how many outfit combos it would enable
  6. budget_fit          — CPW projection at typical wear rate

Decision thresholds (applied to the average sub-score):
  buy   ≥ 0.70
  maybe ≥ 0.45
  skip  <  0.45
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_EXPLANATIONS_PATH = (
    Path(__file__).parent.parent.parent.parent / "config" / "rules" / "shopping_explanations.yaml"
)


def _load_explanations() -> dict:
    try:
        with open(_EXPLANATIONS_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f).get("shopping_explanations", {})
    except Exception:
        return {}


_EXPLANATIONS: dict = _load_explanations()

_BUY_THRESHOLD = 0.70
_MAYBE_THRESHOLD = 0.45

# Sub-score weights (normalised internally)
_WEIGHTS: dict[str, float] = {
    "palette_match": 0.20,
    "gap_fill": 0.25,
    "wardrobe_compat": 0.20,
    "redundancy_penalty": 0.15,
    "expected_versatility": 0.15,
    "budget_fit": 0.05,
}


class PurchaseEvaluator:
    """Evaluate whether a shopping candidate is worth buying.

    Parameters
    ----------
    wardrobe:
        Full list of existing wardrobe item dicts.
    user_context:
        Dict with ``palette_hex``, ``identity_family``, etc.
    """

    def __init__(
        self,
        wardrobe: list[dict[str, Any]],
        user_context: dict[str, Any] | None = None,
    ) -> None:
        self._wardrobe = wardrobe
        self._ctx = user_context or {}

    def evaluate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Run all sub-scorers and return a decision + full explanation.

        Parameters
        ----------
        candidate:
            Output of :func:`candidate_parser.parse_from_image` or
            :func:`candidate_parser.parse_from_attrs` — a plain dict with
            ``id``, ``category``, ``attributes``, ``cost``, ``wear_count``.

        Returns
        -------
        Dict matching ``PurchaseEvalOut`` schema.
        """
        scores: dict[str, dict] = {}

        scores["palette_match"] = self._palette_match(candidate)
        scores["gap_fill"] = self._gap_fill(candidate)
        scores["wardrobe_compat"] = self._wardrobe_compat(candidate)
        scores["redundancy_penalty"] = self._redundancy_penalty(candidate)
        scores["expected_versatility"] = self._expected_versatility(candidate)
        scores["budget_fit"] = self._budget_fit(candidate)

        avg = _weighted_avg(scores)
        decision = "buy" if avg >= _BUY_THRESHOLD else ("maybe" if avg >= _MAYBE_THRESHOLD else "skip")

        all_reasons: list[str] = []
        all_warnings: list[str] = []
        for s in scores.values():
            all_reasons.extend(s.get("reasons", []))
            all_warnings.extend(s.get("warnings", []))

        # Decision-level summary from YAML explanation templates
        summary_reasons = _build_summary(decision, scores, self._ctx)
        all_reasons = summary_reasons + all_reasons

        # Convenience fields extracted from sub-scorer results
        pairs_with = scores["wardrobe_compat"].get("_pairs_with_count", 0)
        fills_gap_ids = scores["gap_fill"].get("_fills_gap_category_ids", [])
        dup_ids = scores["redundancy_penalty"].get("_duplicate_like_item_ids", [])

        return {
            "decision": decision,
            "confidence": round(avg, 3),
            "reasons": all_reasons,
            "warnings": all_warnings,
            "pairs_with_count": pairs_with,
            "fills_gap_ids": fills_gap_ids,
            "duplicate_like_item_ids": dup_ids,
            "subscores": {
                name: {
                    "score": round(s["score"], 3),
                    "reasons": s.get("reasons", []),
                    "warnings": s.get("warnings", []),
                }
                for name, s in scores.items()
            },
            "candidate_attributes": candidate.get("attributes", {}),
        }

    # ------------------------------------------------------------------
    # Sub-scorers
    # ------------------------------------------------------------------

    def _palette_match(self, candidate: dict) -> dict:
        from app.services.outfits.scoring.palette_fit import PaletteFitScorer

        palette_hex = self._ctx.get("palette_hex") or []
        scorer = PaletteFitScorer()
        result = scorer.score([candidate], {"palette_hex": palette_hex})
        return {
            "score": result.score,
            "reasons": result.reasons,
            "warnings": result.warnings,
        }

    def _gap_fill(self, candidate: dict) -> dict:
        from app.services.analytics.gap_analyzer import analyze_extended

        # Analyze current wardrobe gaps
        gaps_before = analyze_extended(self._wardrobe, self._ctx)
        gaps_after = analyze_extended(self._wardrobe + [candidate], self._ctx)

        gaps_before_count = sum(
            len(v) for k, v in gaps_before.items() if k != "notes"
        )
        gaps_after_count = sum(
            len(v) for k, v in gaps_after.items() if k != "notes"
        )

        gap_reduction = max(0, gaps_before_count - gaps_after_count)
        score = min(1.0, gap_reduction / max(gaps_before_count, 1))

        reasons: list[str] = []
        fills_categories: list[str] = []

        if gap_reduction > 0:
            score = max(score, 0.75)
            reasons.append(f"gap_fill: item reduces {gap_reduction} wardrobe gap(s)")
            # Find which occasion gaps are filled
            occ_before = {g["occasion"] for g in gaps_before.get("occasion_gaps", [])}
            occ_after = {g["occasion"] for g in gaps_after.get("occasion_gaps", [])}
            filled_occs = list(occ_before - occ_after)
            fills_categories.extend(filled_occs)
            if filled_occs:
                reasons.append(f"gap_fill: fills occasion coverage for: {', '.join(filled_occs)}")
        elif gaps_before_count == 0:
            score = 0.5
            reasons.append("gap_fill: wardrobe already well-balanced")
        else:
            score = 0.2
            reasons.append("gap_fill: does not address detected gaps")

        return {
            "score": score,
            "reasons": reasons,
            "warnings": [],
            "_fills_gap_category_ids": fills_categories,
        }

    def _wardrobe_compat(self, candidate: dict) -> dict:
        from app.services.analytics.item_graph import ItemCompatibilityGraph

        if not self._wardrobe:
            return {
                "score": 0.5,
                "reasons": ["wardrobe_compat: empty wardrobe — neutral"],
                "warnings": [],
                "_pairs_with_count": 0,
            }

        graph = ItemCompatibilityGraph().build(self._wardrobe + [candidate])
        cand_id = str(candidate.get("id"))
        partners = graph.get_partners(cand_id, top_n=50)
        good_partners = [p for p in partners if p["score"] >= 0.5]
        pairs_count = len(good_partners)

        if pairs_count >= 5:
            score = 1.0
        elif pairs_count >= 3:
            score = 0.75
        elif pairs_count >= 1:
            score = 0.50
        else:
            score = 0.15

        return {
            "score": score,
            "reasons": [f"wardrobe_compat: compatible with {pairs_count} existing item(s)"],
            "warnings": [] if pairs_count > 0 else ["wardrobe_compat: no compatible items found"],
            "_pairs_with_count": pairs_count,
        }

    def _redundancy_penalty(self, candidate: dict) -> dict:
        from app.services.analytics.redundancy_service import cluster

        combined = self._wardrobe + [candidate]
        clusters = cluster(combined)
        cand_id = str(candidate.get("id"))

        # Find clusters that include the candidate
        cand_clusters = [c for c in clusters if cand_id in c.get("item_ids", [])]
        dup_clusters = [c for c in cand_clusters if c["type"] == "duplicate"]
        near_dup_clusters = [c for c in cand_clusters if c["type"] == "near_duplicate"]

        # Collect duplicate-like item ids
        dup_like_ids: list[str] = []
        for c in (dup_clusters + near_dup_clusters):
            dup_like_ids.extend(i for i in c["item_ids"] if i != cand_id)

        reasons: list[str] = []
        warnings: list[str] = []

        if dup_clusters:
            score = 0.1
            warnings.append("redundancy: nearly identical item already in wardrobe")
        elif near_dup_clusters:
            score = 0.35
            warnings.append("redundancy: similar color+category item already in wardrobe")
        else:
            score = 0.9
            reasons.append("redundancy: no significant redundancy detected")

        return {
            "score": score,
            "reasons": reasons,
            "warnings": warnings,
            "_duplicate_like_item_ids": dup_like_ids[:5],
        }

    def _expected_versatility(self, candidate: dict) -> dict:
        from app.services.versatility_service import VersatilityService, ORPHAN_THRESHOLD

        import uuid as _uuid
        cand_id = candidate.get("id") or str(_uuid.uuid4())
        candidate_with_id = {**candidate, "id": cand_id}

        virtual_wardrobe = self._wardrobe + [candidate_with_id]
        svc = VersatilityService()
        try:
            result = svc.compute(
                _uuid.UUID(str(cand_id)),
                virtual_wardrobe,
                self._ctx,
            )
        except Exception as exc:
            logger.warning("expected_versatility: VersatilityService failed: %s", exc)
            return {"score": 0.5, "reasons": ["expected_versatility: could not compute"], "warnings": []}

        outfit_count = result.get("outfit_count", 0)
        is_orphan = result.get("is_orphan", True)

        if outfit_count >= 5:
            score = 1.0
        elif outfit_count >= 3:
            score = 0.75
        elif outfit_count >= 1:
            score = 0.50
        elif is_orphan:
            score = 0.10
        else:
            score = 0.30

        return {
            "score": score,
            "reasons": [f"expected_versatility: enables {outfit_count} outfit combination(s)"],
            "warnings": ["expected_versatility: item would be an orphan"] if is_orphan else [],
        }

    def _budget_fit(self, candidate: dict) -> dict:
        from app.services.analytics.cpw_service import calculate_projected

        price = candidate.get("cost")
        if price is None:
            return {
                "score": 0.5,
                "reasons": ["budget_fit: no price provided — neutral"],
                "warnings": [],
            }

        # Assume 2 wears/month as a default frequency
        projected = calculate_projected(price, 0, frequency_per_month=2.0, months=12)
        projected_cpw = projected["projected_cpw"]

        if projected_cpw <= 5.0:
            score = 1.0
        elif projected_cpw <= 15.0:
            score = 0.75
        elif projected_cpw <= 40.0:
            score = 0.50
        elif projected_cpw <= 80.0:
            score = 0.25
        else:
            score = 0.10

        return {
            "score": score,
            "reasons": [
                f"budget_fit: projected CPW {projected_cpw:.2f} after 1 year "
                f"(2 wears/month)"
            ],
            "warnings": [f"budget_fit: high CPW {projected_cpw:.2f} — check if you'll wear it often"]
            if projected_cpw > 40.0
            else [],
        }


def _weighted_avg(scores: dict[str, dict]) -> float:
    total_w = sum(_WEIGHTS.get(k, 1.0) for k in scores)
    if total_w == 0:
        return 0.0
    return sum(scores[k]["score"] * _WEIGHTS.get(k, 1.0) for k in scores) / total_w


def _build_summary(
    decision: str,
    scores: dict[str, dict],
    ctx: dict,
) -> list[str]:
    """Build human-readable decision-level summary from YAML templates."""
    lines: list[str] = []
    exp = _EXPLANATIONS

    # Decision headline
    decision_tmpl = exp.get("decision", {}).get(decision, "")
    if decision_tmpl:
        lines.append(decision_tmpl)

    # Palette match
    pm_score = scores.get("palette_match", {}).get("score", 0.5)
    season = ctx.get("season_top_1") or "your"
    pm_exp = exp.get("palette_match", {})
    if pm_score >= 0.80:
        tmpl = pm_exp.get("high", "")
        if tmpl:
            lines.append(tmpl.format(season=season))
    elif pm_score >= 0.55:
        tmpl = pm_exp.get("medium", "")
        if tmpl:
            lines.append(tmpl)
    elif pm_score < 0.55:
        tmpl = pm_exp.get("low", "")
        if tmpl:
            lines.append(tmpl)

    # Gap fill
    gf_score = scores.get("gap_fill", {}).get("score", 0.5)
    gf_cats = scores.get("gap_fill", {}).get("_fills_gap_category_ids", [])
    gf_exp = exp.get("gap_fill", {})
    if gf_score >= 0.65:
        tmpl = gf_exp.get("yes", "")
        if tmpl:
            cat_str = ", ".join(gf_cats) if gf_cats else "wardrobe"
            lines.append(tmpl.format(category=cat_str, count=len(gf_cats)))
    elif gf_score < 0.35:
        tmpl = gf_exp.get("no", "")
        if tmpl:
            lines.append(tmpl.format(count=0))

    # Compatibility
    wc_score = scores.get("wardrobe_compat", {}).get("score", 0.5)
    wc_count = scores.get("wardrobe_compat", {}).get("_pairs_with_count", 0)
    wc_exp = exp.get("wardrobe_compatibility", {})
    if wc_score >= 0.75:
        tmpl = wc_exp.get("high", "")
        if tmpl:
            lines.append(tmpl.format(count=wc_count))
    elif wc_score >= 0.4:
        tmpl = wc_exp.get("medium", "")
        if tmpl:
            lines.append(tmpl.format(count=wc_count))
    else:
        tmpl = wc_exp.get("low", "")
        if tmpl:
            lines.append(tmpl.format(count=wc_count))

    # Redundancy
    rp_score = scores.get("redundancy_penalty", {}).get("score", 0.9)
    rp_exp = exp.get("redundancy_penalty", {})
    if rp_score < 0.2:
        tmpl = rp_exp.get("high", "")
        if tmpl:
            lines.append(tmpl)
    elif rp_score < 0.5:
        tmpl = rp_exp.get("medium", "")
        if tmpl:
            lines.append(tmpl)

    # Versatility
    ev_score = scores.get("expected_versatility", {}).get("score", 0.5)
    ev_exp = exp.get("expected_versatility", {})
    # Extract count from reasons if present
    ev_reasons = scores.get("expected_versatility", {}).get("reasons", [])
    ev_count = 0
    for r in ev_reasons:
        import re
        m = re.search(r"(\d+) outfit combination", r)
        if m:
            ev_count = int(m.group(1))
            break
    if ev_score >= 0.70:
        tmpl = ev_exp.get("high", "")
        if tmpl:
            lines.append(tmpl.format(count=ev_count))
    elif ev_score >= 0.40:
        tmpl = ev_exp.get("medium", "")
        if tmpl:
            lines.append(tmpl.format(count=ev_count))
    else:
        tmpl = ev_exp.get("low", "")
        if tmpl:
            lines.append(tmpl.format(count=ev_count))

    return [l for l in lines if l]
