"""Template-driven outfit generator with pre-scoring filtering and diversity.

Pipeline:

    1. Bucket items by category (accessory-like raw categories are unified).
    2. For each template in ``OUTFIT_TEMPLATES`` generate candidate combos via
       deterministic ``itertools.product``. Templates that declare optional
       layers only emit the extended combos; the plain base is covered by the
       sibling template without the optional layer.
    3. Drop invalid candidates via ``_filter_candidate`` (soft, structural
       rules — missing metadata never rejects).
    4. Score surviving candidates via ``ScoringService.score_outfit``.
    5. Sort by overall score with a stable deterministic tie-break.
    6. Collapse near-duplicates via ``_reduce_diversity`` using a semantic
       ``(template, (category, id)...)`` signature.
    7. Return the top-N outfits.

Two global safety caps stop the pipeline on pathological wardrobes:

    * ``MAX_TOTAL_CANDIDATES`` — total candidates generated across all
      templates before filtering.
    * ``MAX_ACCEPTED_CANDIDATES_FOR_SCORING`` — candidates that survive
      filtering and are forwarded to scoring.

Internal explanations are kept structured (``filter_pass_reasons`` and
``scoring_reasons``); ``explanation`` is the flattened convenience view.
"""

from itertools import product

from app.services.scoring_service import ScoringService


# ----------------------------------------------------------------- templates

OUTFIT_TEMPLATES: tuple[dict, ...] = (
    {
        "name": "top_bottom_shoes",
        "required": ("top", "bottom", "shoes"),
        "optional": (),
    },
    {
        "name": "top_bottom_shoes_accessory",
        "required": ("top", "bottom", "shoes"),
        "optional": ("accessory",),
    },
    {
        "name": "top_bottom_shoes_outerwear",
        "required": ("top", "bottom", "shoes"),
        "optional": ("outerwear",),
    },
    {
        "name": "dress_shoes",
        "required": ("dress", "shoes"),
        "optional": (),
    },
    {
        "name": "dress_shoes_accessory",
        "required": ("dress", "shoes"),
        "optional": ("accessory",),
    },
    {
        "name": "dress_shoes_outerwear",
        "required": ("dress", "shoes"),
        "optional": ("outerwear",),
    },
)


# --------------------------------------------------------- structural tables

#: Raw categories treated as a single optional "accessory" bucket for MVP.
#: Items keep their raw ``category`` for breakdown and explanation.
ACCESSORY_LIKE: frozenset[str] = frozenset({"accessory", "bag", "jewelry", "hat"})

#: Ordered coarse-grained formality ladder. A span > ``MAX_FORMALITY_SPAN``
#: across tagged items of the same outfit is treated as a hard conflict.
FORMALITY_LADDER: tuple[str, ...] = (
    "very_casual",
    "casual",
    "smart_casual",
    "business",
    "formal",
)
FORMALITY_INDEX: dict[str, int] = {k: i for i, k in enumerate(FORMALITY_LADDER)}
MAX_FORMALITY_SPAN: int = 2

#: Line-type groups that clash hard enough to reject the outfit outright.
CLASHING_LINE_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"sharp", "severe", "clean"}),
    frozenset({"fussy", "ornate"}),
)


class OutfitEngine:
    """Template-driven outfit generator scored by ``ScoringService``."""

    #: Hard upper bound on candidates *per template* before scoring. Prevents a
    #: single template from monopolising the pipeline on large wardrobes.
    MAX_CANDIDATES_PER_TEMPLATE: int = 200

    #: Global cap on the total number of candidates generated across every
    #: template (pre-filter). Safety net.
    MAX_TOTAL_CANDIDATES: int = 2000

    #: Global cap on the number of candidates that survive filtering and are
    #: forwarded to :class:`ScoringService`.
    MAX_ACCEPTED_CANDIDATES_FOR_SCORING: int = 500

    #: Default number of outfits returned by :meth:`generate`.
    DEFAULT_TOP_N: int = 20

    #: Two scores within this distance are considered tied for the diversity
    #: reducer's secondary sort.
    TIE_TOLERANCE: float = 0.005

    def __init__(self, scoring_service: ScoringService | None = None) -> None:
        self.scoring_service = scoring_service or ScoringService()
        #: Rejected candidates from the most recent :meth:`generate` call.
        self.last_rejections: list[dict] = []
        #: Summary counters from the most recent :meth:`generate` call.
        self.last_stats: dict = {
            "total_candidates": 0,
            "accepted_for_scoring": 0,
            "rejected": 0,
            "returned": 0,
            "caps_hit": [],
        }

    # --------------------------------------------------------------- public

    def generate(
        self,
        items: list[dict],
        user_context: dict | None = None,
        occasion: str | None = None,
        top_n: int | None = None,
    ) -> list[dict]:
        self.last_rejections = []
        caps_hit: list[str] = []
        ctx = dict(user_context or {})
        if occasion is not None:
            ctx.setdefault("occasion", occasion)

        buckets = self._bucket_by_category(items)
        effective_top_n = top_n or self.DEFAULT_TOP_N

        scored: list[dict] = []
        total_candidates = 0
        accepted = 0

        for template in OUTFIT_TEMPLATES:
            if total_candidates >= self.MAX_TOTAL_CANDIDATES:
                break
            if accepted >= self.MAX_ACCEPTED_CANDIDATES_FOR_SCORING:
                break
            for candidate_items, used_optional in self._iter_template_candidates(
                template, buckets
            ):
                if total_candidates >= self.MAX_TOTAL_CANDIDATES:
                    if "MAX_TOTAL_CANDIDATES" not in caps_hit:
                        caps_hit.append("MAX_TOTAL_CANDIDATES")
                    break
                if accepted >= self.MAX_ACCEPTED_CANDIDATES_FOR_SCORING:
                    if "MAX_ACCEPTED_CANDIDATES_FOR_SCORING" not in caps_hit:
                        caps_hit.append("MAX_ACCEPTED_CANDIDATES_FOR_SCORING")
                    break
                total_candidates += 1

                ok, reasons = self._filter_candidate(candidate_items, ctx)
                if not ok:
                    self.last_rejections.append(
                        {
                            "template": template["name"],
                            "items": [it.get("id") for it in candidate_items],
                            "reasons": reasons,
                        }
                    )
                    continue

                scoring = self.scoring_service.score_outfit(candidate_items, ctx)
                scores = dict(scoring["sub_scores"])
                scores["overall"] = scoring["score"]
                filter_pass_reasons = list(reasons)
                scoring_reasons = list(scoring["explanation"])

                outfit = {
                    "items": candidate_items,
                    "occasion": occasion,
                    "scores": scores,
                    # Structured views — not flattened too early.
                    "filter_pass_reasons": filter_pass_reasons,
                    "scoring_reasons": scoring_reasons,
                    # Flattened convenience view (backward compatible).
                    "explanation": filter_pass_reasons + scoring_reasons,
                    "breakdown": self._category_breakdown(candidate_items),
                    "generation": {
                        "template": template["name"],
                        "optional_used": used_optional,
                    },
                }
                scored.append(outfit)
                accepted += 1

        scored.sort(key=self._sort_key)
        diverse = self._reduce_diversity(scored, effective_top_n)

        self.last_stats = {
            "total_candidates": total_candidates,
            "accepted_for_scoring": accepted,
            "rejected": len(self.last_rejections),
            "returned": len(diverse),
            "caps_hit": caps_hit,
        }
        return diverse

    # ------------------------------------------------------------- bucketing

    @staticmethod
    def _bucket_by_category(items: list[dict]) -> dict[str, list[dict]]:
        """Bucket items by category, folding accessory-like raw categories
        (``accessory``, ``bag``, ``jewelry``, ``hat``) into a single
        ``accessory`` bucket. Items keep their raw ``category`` field so the
        breakdown and explanations can still show ``bag`` or ``hat``.
        """
        buckets: dict[str, list[dict]] = {
            "top": [],
            "bottom": [],
            "dress": [],
            "shoes": [],
            "outerwear": [],
            "accessory": [],
        }
        for item in items:
            cat = item.get("category")
            if cat in ACCESSORY_LIKE:
                buckets["accessory"].append(item)
            elif cat in buckets:
                buckets[cat].append(item)
        return buckets

    @staticmethod
    def _category_breakdown(items: list[dict]) -> dict[str, list[str]]:
        breakdown: dict[str, list[str]] = {}
        for item in items:
            cat = item.get("category") or "unknown"
            breakdown.setdefault(cat, []).append(str(item.get("id")))
        return breakdown

    # ------------------------------------------------------------ candidates

    def _iter_template_candidates(
        self,
        template: dict,
        buckets: dict[str, list[dict]],
    ):
        """Yield ``(items, used_optional_or_None)`` tuples for a template.

        Templates without optional layers yield the required-only base combo.
        Templates with optional layers yield **only** extended combos (one per
        optional item) — the plain base is already produced by the sibling
        template that declares no optional layer, so we avoid duplicates.
        Capped at :attr:`MAX_CANDIDATES_PER_TEMPLATE`.
        """
        required = template["required"]
        if any(not buckets.get(cat) for cat in required):
            return

        required_lists = [buckets[cat] for cat in required]
        optional = template["optional"]
        emitted = 0

        for base_combo in product(*required_lists):
            if emitted >= self.MAX_CANDIDATES_PER_TEMPLATE:
                return

            if not optional:
                yield list(base_combo), None
                emitted += 1
                continue

            for opt_cat in optional:
                opt_items = buckets.get(opt_cat) or []
                for opt_item in opt_items:
                    if emitted >= self.MAX_CANDIDATES_PER_TEMPLATE:
                        return
                    yield list(base_combo) + [opt_item], opt_cat
                    emitted += 1

    # --------------------------------------------------------------- filters

    def _filter_candidate(
        self,
        items: list[dict],
        ctx: dict,
    ) -> tuple[bool, list[str]]:
        """Return ``(ok, reasons)`` after structural validity checks.

        All filters are *soft*: missing metadata never rejects an outfit,
        only explicit conflicts do. Each reason is a human-readable string.
        """
        # 1. Missing required categories (safety net — templates already enforce).
        if not items:
            return False, ["filter: empty candidate"]

        # 2. Duplicate item id.
        ids = [it.get("id") for it in items if it.get("id") is not None]
        if len(ids) != len(set(ids)):
            return False, ["filter: duplicate item id in candidate"]

        # 3. Duplicate category usage (accessory-like may stack — bag + hat +
        #    jewelry on the same outfit is fine).
        cats: dict[str, int] = {}
        for it in items:
            cat = it.get("category")
            if cat is None:
                continue
            cats[cat] = cats.get(cat, 0) + 1
        for cat, count in cats.items():
            if count > 1 and cat not in ACCESSORY_LIKE:
                return False, [f"filter: category '{cat}' used {count}x"]

        # 4. Formality span.
        formality_idxs = [
            FORMALITY_INDEX[it["formality"]]
            for it in items
            if it.get("formality") in FORMALITY_INDEX
        ]
        if formality_idxs:
            span = max(formality_idxs) - min(formality_idxs)
            if span > MAX_FORMALITY_SPAN:
                return False, [
                    f"filter: formality span {span} exceeds {MAX_FORMALITY_SPAN}"
                ]

        # 5. Season compatibility (soft). Reject only when at least two items
        #    carry explicit non-all_season tags AND they share no season.
        #    Missing or partial season metadata is never a reason to reject.
        season_sets: list[set[str]] = []
        any_all_season = False
        for it in items:
            tags = it.get("season") or []
            if not tags:
                continue
            if "all_season" in tags:
                any_all_season = True
                continue
            season_sets.append(set(tags))
        if len(season_sets) >= 2 and not any_all_season:
            common = set.intersection(*season_sets)
            if not common:
                return False, [
                    "filter: no overlapping season across tagged items"
                ]

        # 6. Obviously broken line combinations.
        line_types = [
            str(it.get("line_type")).lower()
            for it in items
            if it.get("line_type")
        ]
        hit_groups: set[int] = set()
        for lt in line_types:
            for idx, group in enumerate(CLASHING_LINE_GROUPS):
                if lt in group:
                    hit_groups.add(idx)
        if len(hit_groups) >= 2:
            return False, [
                "filter: conflicting line_type groups "
                f"({sorted(set(line_types))})"
            ]

        # 7. Too many statement pieces.
        statement_count = sum(
            1
            for it in items
            if it.get("statement") is True
            or str(it.get("detail_density") or "").lower() == "high"
        )
        if statement_count > 1:
            return False, [
                f"filter: {statement_count} statement pieces (max 1)"
            ]

        # 8. Occasion hard filter (soft — only explicit non-empty mismatches).
        requested_occasion = ctx.get("occasion")
        if requested_occasion:
            for it in items:
                item_occasions = it.get("occasions")
                if item_occasions and requested_occasion not in item_occasions:
                    return False, [
                        f"filter: item {it.get('id')} has explicit occasions "
                        f"{item_occasions} excluding '{requested_occasion}'"
                    ]

        return True, ["filter: passed structural checks"]

    # ------------------------------------------------------- sort + diversity

    def _sort_key(self, outfit: dict):
        # Ascending sort: negate the score so the highest overall comes first.
        # Secondary deterministic key on template name.
        return (
            -outfit["scores"].get("overall", 0.0),
            outfit["generation"]["template"],
        )

    @staticmethod
    def _base_signature(outfit: dict) -> tuple:
        """Semantic signature = ``(template, sorted((category, id) pairs))``.

        Excludes accessory-like items so two outfits that differ only by which
        accessory they add collapse to the same signature. Keeping the
        template in the signature preserves "same base with vs without
        outerwear" as two distinct styling choices.
        """
        template = outfit["generation"]["template"]
        pairs = tuple(
            sorted(
                (it.get("category") or "", str(it.get("id")))
                for it in outfit["items"]
                if it.get("category") not in ACCESSORY_LIKE
                and it.get("id") is not None
            )
        )
        return (template, pairs)

    def _reduce_diversity(
        self,
        outfits: list[dict],
        top_n: int,
    ) -> list[dict]:
        """Collapse duplicates and bias toward wardrobe coverage.

        * at most one outfit per ``_base_signature`` (the best-scoring wins);
        * within a ``TIE_TOLERANCE`` score band, prefer the outfit that
          introduces the most previously-unseen item ids.
        """
        by_signature: dict[tuple, dict] = {}
        for outfit in outfits:
            sig = self._base_signature(outfit)
            incumbent = by_signature.get(sig)
            if incumbent is None or (
                outfit["scores"].get("overall", 0.0)
                > incumbent["scores"].get("overall", 0.0)
            ):
                by_signature[sig] = outfit

        deduped = sorted(by_signature.values(), key=self._sort_key)

        picked: list[dict] = []
        seen_ids: set[str] = set()
        remaining = list(deduped)
        while remaining and len(picked) < top_n:
            best_score = remaining[0]["scores"].get("overall", 0.0)
            tie_band = [
                o
                for o in remaining
                if best_score - o["scores"].get("overall", 0.0)
                <= self.TIE_TOLERANCE
            ]
            tie_band.sort(
                key=lambda o: (
                    -sum(
                        1
                        for it in o["items"]
                        if str(it.get("id")) not in seen_ids
                    ),
                    tuple(str(it.get("id")) for it in o["items"]),
                )
            )
            chosen = tie_band[0]
            picked.append(chosen)
            remaining.remove(chosen)
            for it in chosen["items"]:
                if it.get("id") is not None:
                    seen_ids.add(str(it["id"]))
        return picked
