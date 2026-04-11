"""Deterministic, explainable scoring engine.

Implements the formulas from SCORING_SPEC.md:

Item score (base):
    0.30 color_fit + 0.30 line_fit + 0.20 silhouette_fit + 0.10 style_fit + 0.10 utility_fit

Outfit score:
    0.30 color_harmony + 0.25 silhouette_balance + 0.20 line_consistency
    + 0.15 style_consistency + 0.10 occasion_fit

Final score (composition with personalization):
    0.45 base + 0.35 preference + 0.20 behavior

All scoring is rule-based (YAML-driven where applicable) and pure: same input
always yields the same output. Every sub-score returns its reasons so the
caller can present an explanation alongside the number.
"""

from app.services.rules_loader import load_rules


def cosine_like(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 0.0
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    na = sum(a.get(k, 0.0) ** 2 for k in keys) ** 0.5
    nb = sum(b.get(k, 0.0) ** 2 for k in keys) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


# A small palette of universally compatible neutrals. Items in this set get a
# safe default color score when their full color axes are unknown.
NEUTRAL_COLORS: frozenset[str] = frozenset(
    {
        "white",
        "off_white",
        "ivory",
        "cream",
        "beige",
        "stone",
        "taupe",
        "sand",
        "camel",
        "gray",
        "grey",
        "charcoal",
        "black",
        "navy",
    }
)

IDENTITY_FAMILIES: tuple[str, ...] = (
    "dramatic",
    "natural",
    "classic",
    "gamine",
    "romantic",
)


class ScoringService:
    ITEM_WEIGHTS: dict[str, float] = {
        "color_fit": 0.30,
        "line_fit": 0.30,
        "silhouette_fit": 0.20,
        "style_fit": 0.10,
        "utility_fit": 0.10,
    }

    OUTFIT_WEIGHTS: dict[str, float] = {
        "color_harmony": 0.30,
        "silhouette_balance": 0.25,
        "line_consistency": 0.20,
        "style_consistency": 0.15,
        "occasion_fit": 0.10,
    }

    LINE_AXES: tuple[str, ...] = (
        "line_type",
        "texture",
        "fabric_drape",
        "detail_density",
    )
    SILHOUETTE_AXES: tuple[str, ...] = ("fit", "structure", "scale")
    COLOR_AXES: tuple[str, ...] = ("undertone", "depth", "chroma", "contrast")

    def __init__(self) -> None:
        self.rules = load_rules()

    # ------------------------------------------------------------------ utils

    @staticmethod
    def normalize_identity_family(value: str | None) -> str | None:
        """Map a Kibbe subtype like ``soft_classic`` to its family ``classic``.

        Returns ``None`` if no family can be detected.
        """
        if not value:
            return None
        v = value.lower()
        for fam in IDENTITY_FAMILIES:
            if fam in v:
                return fam
        return None

    @staticmethod
    def _extract_attrs(item) -> dict:
        """Coerce a wardrobe item (ORM, nested dict, or flat dict) to a flat
        attributes dict, copying ``category`` in if present so the scorer can
        use it.
        """
        if item is None:
            return {}
        # ORM model
        if hasattr(item, "attributes_json"):
            attrs = dict(item.attributes_json or {})
            category = getattr(item, "category", None)
            if category and "category" not in attrs:
                attrs["category"] = category
            return attrs
        if isinstance(item, dict):
            inner = item.get("attributes")
            if isinstance(inner, dict):
                attrs = dict(inner)
                if item.get("category") and "category" not in attrs:
                    attrs["category"] = item["category"]
                return attrs
            return dict(item)
        return {}

    # ----------------------------------------------------------- item scoring

    def _color_fit(
        self,
        attrs: dict,
        user_color: dict | None,
    ) -> tuple[float, list[str]]:
        if not user_color:
            return 0.5, ["color: no user color profile — neutral score"]
        item_axes = attrs.get("color_axes")
        if isinstance(item_axes, dict) and item_axes:
            matched = 0
            total = 0
            reasons: list[str] = []
            for axis in self.COLOR_AXES:
                if axis in item_axes and axis in user_color:
                    total += 1
                    if item_axes[axis] == user_color[axis]:
                        matched += 1
                        reasons.append(f"color: {axis}={item_axes[axis]} matches user")
                    else:
                        reasons.append(
                            f"color: {axis}={item_axes[axis]} != user {user_color[axis]}"
                        )
            if total == 0:
                return 0.5, ["color: item color_axes missing user-relevant keys"]
            return round(matched / total, 3), reasons
        primary = str(attrs.get("primary_color") or "").strip().lower()
        if not primary:
            return 0.5, ["color: no color information on item"]
        if primary in NEUTRAL_COLORS:
            return 0.85, [f"color: {primary} is a universal neutral"]
        return 0.5, [f"color: {primary} not analyzed against season axes"]

    def _rule_axis_score(
        self,
        attrs_value,
        axis_name: str,
        prefer: dict,
        avoid: dict,
    ) -> float | None:
        if attrs_value is None:
            return None
        prefer_list = prefer.get(axis_name) or []
        avoid_list = avoid.get(axis_name) or []
        if attrs_value in prefer_list:
            return 1.0
        if attrs_value in avoid_list:
            return 0.0
        return 0.5

    def _line_silhouette_score(
        self,
        attrs: dict,
        family: str | None,
        axes: tuple[str, ...],
        label: str,
    ) -> tuple[float, list[str]]:
        if not family:
            return 0.5, [f"{label}: no identity family — neutral score"]
        family_rules = (
            self.rules.get("garment_line_rules", {})
            .get("garment_line_rules", {})
            .get(family)
        )
        if not family_rules:
            return 0.5, [f"{label}: no rules for family '{family}' — neutral score"]
        prefer = family_rules.get("prefer", {}) or {}
        avoid = family_rules.get("avoid", {}) or {}
        scores: list[float] = []
        reasons: list[str] = []
        for axis in axes:
            value = attrs.get(axis)
            s = self._rule_axis_score(value, axis, prefer, avoid)
            if s is None:
                continue
            scores.append(s)
            if s == 1.0:
                reasons.append(f"{label}: {axis}={value} preferred for {family}")
            elif s == 0.0:
                reasons.append(f"{label}: {axis}={value} avoided for {family}")
            else:
                reasons.append(f"{label}: {axis}={value} neutral for {family}")
        if not scores:
            return 0.5, [f"{label}: no relevant attributes provided"]
        return round(sum(scores) / len(scores), 3), reasons

    def _line_fit(
        self, attrs: dict, family: str | None
    ) -> tuple[float, list[str]]:
        return self._line_silhouette_score(attrs, family, self.LINE_AXES, "line")

    def _silhouette_fit(
        self, attrs: dict, family: str | None
    ) -> tuple[float, list[str]]:
        return self._line_silhouette_score(
            attrs, family, self.SILHOUETTE_AXES, "silhouette"
        )

    def _style_fit(
        self,
        attrs: dict,
        style_vector: dict | None,
    ) -> tuple[float, list[str]]:
        style_tags = attrs.get("style_tags") or []
        if not style_tags:
            return 0.5, ["style: item has no style_tags"]
        if not style_vector:
            return 0.5, ["style: user has no style preferences yet"]
        item_vec = {tag: 1.0 for tag in style_tags}
        score = cosine_like(item_vec, style_vector)
        matched = [t for t in style_tags if style_vector.get(t, 0.0) > 0.05]
        if matched:
            reasons = [f"style: matches user preferences ({', '.join(matched)})"]
        else:
            reasons = [f"style: tags {style_tags} not in user preferences"]
        return round(_clamp01(score), 3), reasons

    def _utility_fit(
        self,
        attrs: dict,
        occasion: str | None,
        lifestyle: list | None,
    ) -> tuple[float, list[str]]:
        item_occasions = attrs.get("occasions") or []
        components: list[float] = []
        reasons: list[str] = []
        if occasion:
            if occasion in item_occasions:
                components.append(1.0)
                reasons.append(f"utility: occasion '{occasion}' supported")
            elif item_occasions:
                components.append(0.0)
                reasons.append(
                    f"utility: occasion '{occasion}' not in {item_occasions}"
                )
        if lifestyle:
            overlap = sorted(set(lifestyle) & set(item_occasions))
            if overlap:
                components.append(1.0)
                reasons.append(f"utility: lifestyle overlap {overlap}")
            elif item_occasions:
                components.append(0.3)
                reasons.append("utility: no lifestyle overlap")
        if not components:
            return 0.5, ["utility: insufficient context — neutral score"]
        return round(sum(components) / len(components), 3), reasons

    def score_item(self, item, user_context: dict | None = None) -> dict:
        """Score a single wardrobe item.

        Returns ``{"score", "sub_scores", "explanation"}`` where ``score`` is
        the weighted aggregate per ``ITEM_WEIGHTS`` and ``explanation`` is a
        flat list of reason strings.
        """
        ctx = user_context or {}
        attrs = self._extract_attrs(item)
        family = self.normalize_identity_family(ctx.get("identity_family"))

        color_score, color_reasons = self._color_fit(attrs, ctx.get("color_profile"))
        line_score, line_reasons = self._line_fit(attrs, family)
        silhouette_score, silhouette_reasons = self._silhouette_fit(attrs, family)
        style_score, style_reasons = self._style_fit(attrs, ctx.get("style_vector"))
        utility_score, utility_reasons = self._utility_fit(
            attrs, ctx.get("occasion"), ctx.get("lifestyle")
        )

        sub_scores = {
            "color_fit": color_score,
            "line_fit": line_score,
            "silhouette_fit": silhouette_score,
            "style_fit": style_score,
            "utility_fit": utility_score,
        }
        total = sum(self.ITEM_WEIGHTS[k] * sub_scores[k] for k in self.ITEM_WEIGHTS)
        explanation = (
            color_reasons
            + line_reasons
            + silhouette_reasons
            + style_reasons
            + utility_reasons
        )
        return {
            "score": round(_clamp01(total), 3),
            "sub_scores": sub_scores,
            "explanation": explanation,
        }

    # --------------------------------------------------------- outfit scoring

    def _color_harmony(
        self,
        items_attrs: list[dict],
        user_color: dict | None,
    ) -> tuple[float, list[str]]:
        if not items_attrs:
            return 0.0, ["color_harmony: outfit empty"]
        per_item = []
        neutral_count = 0
        for attrs in items_attrs:
            score, _ = self._color_fit(attrs, user_color)
            per_item.append(score)
            primary = str(attrs.get("primary_color") or "").strip().lower()
            if primary in NEUTRAL_COLORS:
                neutral_count += 1
        base = sum(per_item) / len(per_item)
        reasons = [f"color_harmony: avg per-item color_fit {base:.2f}"]
        bonus = (
            self.rules.get("outfit_rules", {})
            .get("outfit_rules", {})
            .get("bonuses", {})
            .get("one_accent_plus_neutrals", 0.0)
        )
        if (
            len(items_attrs) - neutral_count == 1
            and neutral_count >= 2
            and bonus > 0
        ):
            base = _clamp01(base + bonus)
            reasons.append(
                f"color_harmony: one accent + {neutral_count} neutrals (+{bonus:.2f} bonus)"
            )
        return round(base, 3), reasons

    def _silhouette_balance(
        self,
        items_attrs: list[dict],
        family: str | None,
    ) -> tuple[float, list[str]]:
        if not items_attrs:
            return 0.0, ["silhouette_balance: outfit empty"]
        per_item = []
        oversized = 0
        for attrs in items_attrs:
            s, _ = self._silhouette_fit(attrs, family)
            per_item.append(s)
            fit = str(attrs.get("fit") or "").lower()
            if "oversized" in fit or "loose" in fit:
                oversized += 1
        base = sum(per_item) / len(per_item)
        reasons = [f"silhouette_balance: avg per-item silhouette_fit {base:.2f}"]
        penalty = (
            self.rules.get("outfit_rules", {})
            .get("outfit_rules", {})
            .get("penalties", {})
            .get("oversized_top_and_bottom_for_compact_user", 0.0)
        )
        if oversized >= 2 and penalty > 0:
            base = _clamp01(base - penalty)
            reasons.append(
                f"silhouette_balance: {oversized} oversized pieces (-{penalty:.2f} penalty)"
            )
        return round(base, 3), reasons

    def _line_consistency(
        self,
        items_attrs: list[dict],
    ) -> tuple[float, list[str]]:
        if not items_attrs:
            return 0.0, ["line_consistency: outfit empty"]
        line_types = [a.get("line_type") for a in items_attrs if a.get("line_type")]
        if not line_types:
            return 0.5, ["line_consistency: no line_type data"]
        n = len(line_types)
        distinct = len(set(line_types))
        if n == 1:
            score = 1.0
            reasons = [f"line_consistency: only one tagged item ({line_types[0]})"]
        else:
            score = 1.0 - (distinct - 1) / (n - 1)
            score = _clamp01(score)
            reasons = [
                f"line_consistency: {distinct} distinct line types over {n} items"
            ]
        bonus = (
            self.rules.get("outfit_rules", {})
            .get("outfit_rules", {})
            .get("bonuses", {})
            .get("line_consistency_strong", 0.0)
        )
        if score >= 0.85 and bonus > 0:
            score = _clamp01(score + bonus)
            reasons.append(
                f"line_consistency: strong consistency (+{bonus:.2f} bonus)"
            )
        return round(score, 3), reasons

    def _style_consistency(
        self,
        items_attrs: list[dict],
    ) -> tuple[float, list[str]]:
        if not items_attrs:
            return 0.0, ["style_consistency: outfit empty"]
        tag_sets = [set(a.get("style_tags") or []) for a in items_attrs]
        tag_sets = [s for s in tag_sets if s]
        if not tag_sets:
            return 0.5, ["style_consistency: no style_tags"]
        if len(tag_sets) == 1:
            return 1.0, ["style_consistency: only one tagged item"]
        total = 0.0
        pairs = 0
        for i in range(len(tag_sets)):
            for j in range(i + 1, len(tag_sets)):
                a, b = tag_sets[i], tag_sets[j]
                union = a | b
                if not union:
                    continue
                total += len(a & b) / len(union)
                pairs += 1
        avg = total / pairs if pairs else 0.0
        return round(avg, 3), [
            f"style_consistency: avg pairwise tag overlap {avg:.2f}"
        ]

    def _occasion_fit(
        self,
        items_attrs: list[dict],
        occasion: str | None,
    ) -> tuple[float, list[str]]:
        if not occasion:
            return 0.5, ["occasion_fit: no occasion requested — neutral score"]
        if not items_attrs:
            return 0.0, ["occasion_fit: outfit empty"]
        matches = 0
        total = 0
        for attrs in items_attrs:
            item_occasions = attrs.get("occasions") or []
            if item_occasions:
                total += 1
                if occasion in item_occasions:
                    matches += 1
        if total == 0:
            return 0.5, ["occasion_fit: items lack occasion data"]
        score = matches / total
        reasons = [f"occasion_fit: {matches}/{total} items support '{occasion}'"]
        bonus = (
            self.rules.get("outfit_rules", {})
            .get("outfit_rules", {})
            .get("bonuses", {})
            .get("occasion_exact_match", 0.0)
        )
        if score == 1.0 and bonus > 0:
            score = _clamp01(score + bonus)
            reasons.append(f"occasion_fit: every item matches (+{bonus:.2f} bonus)")
        return round(score, 3), reasons

    def score_outfit(self, items, user_context: dict | None = None) -> dict:
        """Score a full outfit.

        Returns ``{"score", "sub_scores", "explanation"}`` aggregated per
        ``OUTFIT_WEIGHTS``. ``items`` may be ORM models, nested dicts, or flat
        attribute dicts.
        """
        ctx = user_context or {}
        items_attrs = [self._extract_attrs(it) for it in (items or [])]
        family = self.normalize_identity_family(ctx.get("identity_family"))

        ch_score, ch_reasons = self._color_harmony(items_attrs, ctx.get("color_profile"))
        sb_score, sb_reasons = self._silhouette_balance(items_attrs, family)
        lc_score, lc_reasons = self._line_consistency(items_attrs)
        sc_score, sc_reasons = self._style_consistency(items_attrs)
        of_score, of_reasons = self._occasion_fit(items_attrs, ctx.get("occasion"))

        sub_scores = {
            "color_harmony": ch_score,
            "silhouette_balance": sb_score,
            "line_consistency": lc_score,
            "style_consistency": sc_score,
            "occasion_fit": of_score,
        }
        total = sum(self.OUTFIT_WEIGHTS[k] * sub_scores[k] for k in self.OUTFIT_WEIGHTS)
        explanation = (
            ch_reasons + sb_reasons + lc_reasons + sc_reasons + of_reasons
        )
        return {
            "score": round(_clamp01(total), 3),
            "sub_scores": sub_scores,
            "explanation": explanation,
        }

    # ------------------------------------------------- final composite score

    def final_score(
        self,
        base_score: float,
        preference_score: float,
        behavior_score: float,
    ) -> float:
        """Compose base × preference × behavior per SCORING_SPEC.md FINAL SCORE."""
        return round(
            0.45 * base_score + 0.35 * preference_score + 0.20 * behavior_score, 3
        )
