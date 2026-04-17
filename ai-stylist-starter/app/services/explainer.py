"""Human-readable explanation formatter (Block 2 — Explainability UX).

Converts raw scorer reasons / warnings / scores produced by the backend
into a product-friendly ``Explanation`` object:

    {
        "summary": "Great fit for your wardrobe",
        "reasons": ["Color matches your palette", "Pairs with 5 items"],
        "warnings": ["Rarely worn so far"],
    }

Import and call the helpers at the API boundary so the shape is consistent
across outfits, shopping, versatility, and gap analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Explanation:
    """Structured user-facing explanation."""

    summary: str
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "reasons": self.reasons,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Outfit explanation
# ---------------------------------------------------------------------------

def explain_outfit(outfit: dict) -> Explanation:
    """Convert an outfit dict (from OutfitGenerator) into a user-facing Explanation."""
    score = outfit.get("total_score") or outfit.get("scores", {}).get("overall", 0.0)
    breakdown = outfit.get("breakdown") or {}
    raw_reasons = list(outfit.get("reasons") or [])
    raw_warnings = list(outfit.get("warnings") or [])

    # Pick a summary based on overall score
    if score >= 0.75:
        summary = "Great outfit — strong palette and style match"
    elif score >= 0.55:
        summary = "Good combination — works well together"
    elif score >= 0.35:
        summary = "Decent option — a few things could be improved"
    else:
        summary = "Worth considering — check the notes below"

    reasons = _clean_reasons(raw_reasons)
    warnings = _clean_reasons(raw_warnings)

    # Highlight the strongest positive sub-scorer
    best_key, best_score = _best_subscore(breakdown)
    if best_key and best_score >= 0.7:
        reasons.insert(0, _subscore_label(best_key, best_score))

    return Explanation(summary=summary, reasons=reasons[:5], warnings=warnings[:3])


# ---------------------------------------------------------------------------
# Shopping explanation
# ---------------------------------------------------------------------------

def explain_shopping(result: dict) -> Explanation:
    """Produce a user-facing Explanation from a PurchaseEvaluator result dict."""
    decision = result.get("decision", "maybe")
    confidence = result.get("confidence", 0.5)
    subscores = result.get("subscores") or {}

    _DECISION_SUMMARY = {
        "buy": "Worth buying — strong fit for your wardrobe",
        "maybe": "Decent option — consider if it fills a real need",
        "skip": "Probably skip — too redundant, off-palette, or pricey for the wear",
    }
    summary = _DECISION_SUMMARY.get(decision, "See details below")
    if confidence >= 0.75:
        summary += " (high confidence)"
    elif confidence < 0.5:
        summary += " (low confidence — limited wardrobe data)"

    reasons: list[str] = []
    warnings: list[str] = []

    for raw in result.get("reasons") or []:
        cleaned = _clean_one(raw)
        if cleaned:
            reasons.append(cleaned)

    for raw in result.get("warnings") or []:
        cleaned = _clean_one(raw)
        if cleaned:
            warnings.append(cleaned)

    # Highlight key sub-scores
    for key, label_hi, label_lo in [
        ("palette_match", "Color matches your palette", "Color may not fit your palette"),
        ("gap_fill", "Fills a gap in your wardrobe", "You already have similar items"),
        ("wardrobe_compat", "Pairs well with existing pieces", "Few compatible items found"),
        ("redundancy_penalty", "Unique addition — no duplicates", "You already own something similar"),
    ]:
        s = subscores.get(key, {}).get("score")
        if s is None:
            continue
        if s >= 0.7 and label_hi not in reasons:
            reasons.append(label_hi)
        elif s < 0.35 and label_lo not in warnings:
            warnings.append(label_lo)

    return Explanation(summary=summary, reasons=reasons[:5], warnings=warnings[:3])


# ---------------------------------------------------------------------------
# Versatility explanation
# ---------------------------------------------------------------------------

def explain_versatility(result: dict) -> Explanation:
    """Produce a user-facing Explanation from a VersatilityService result dict."""
    outfit_count = result.get("outfit_count", 0)
    is_orphan = result.get("is_orphan", True)
    cpw = result.get("cost_per_wear")
    wear_count = result.get("wear_count", 0) or 0

    if outfit_count >= 8:
        summary = "Highly versatile — a wardrobe staple"
        label = "Wardrobe staple"
    elif outfit_count >= 4:
        summary = f"Good versatility — fits into {outfit_count} outfit combinations"
        label = "Versatile piece"
    elif outfit_count >= 1:
        summary = f"Limited versatility — only {outfit_count} combination(s) found"
        label = "Needs partners"
    else:
        summary = "Orphan item — no valid outfits found with current wardrobe"
        label = "Rarely used"

    reasons: list[str] = []
    warnings: list[str] = []

    if not is_orphan:
        reasons.append(f"Enables {outfit_count} valid outfit combinations")
    else:
        warnings.append("Consider adding complementary items to unlock this piece")

    if cpw is not None:
        if cpw <= 10:
            reasons.append(f"Excellent value — cost per wear is {cpw:.1f}")
        elif cpw <= 30:
            reasons.append(f"Reasonable cost per wear: {cpw:.1f}")
        else:
            warnings.append(f"High cost per wear ({cpw:.1f}) — wear it more often")

    if wear_count == 0:
        warnings.append("Not yet worn — can't calculate real CPW")

    return Explanation(
        summary=summary,
        reasons=reasons,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Gap analysis action label
# ---------------------------------------------------------------------------

_GAP_CATEGORY_LABELS: dict[str, str] = {
    "top": "tops",
    "bottom": "bottoms",
    "dress": "dresses",
    "shoes": "footwear",
    "outerwear": "outerwear",
    "accessory": "accessories",
}


def gap_action_label(category: str) -> str:
    """Return a friendly action string for a missing wardrobe category."""
    friendly = _GAP_CATEGORY_LABELS.get(category, category)
    return f"Add {friendly} to unlock new outfits"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_PREFIX_STRIP = (
    "palette_fit: ",
    "wardrobe_compat: ",
    "redundancy: ",
    "budget_fit: ",
    "gap_fill: ",
    "expected_versatility: ",
    "color_harmony: ",
    "silhouette: ",
    "preference: ",
    "reuse: ",
    "weather: ",
    "occasion: ",
    "filter: ",
)

_SCORE_LABELS: dict[str, tuple[str, str]] = {
    "palette_fit": ("palette_fit", "Palette match"),
    "color_harmony": ("color_harmony", "Color harmony"),
    "silhouette": ("silhouette", "Silhouette balance"),
    "occasion": ("occasion", "Occasion fit"),
    "reuse": ("reuse", "Wear frequency bonus"),
    "preference": ("preference", "Style preference"),
    "weather": ("weather", "Weather suitability"),
}


def _clean_one(raw: str) -> str:
    """Strip internal prefix tags from a reason string."""
    for prefix in _PREFIX_STRIP:
        if raw.lower().startswith(prefix.lower()):
            return raw[len(prefix):].strip().capitalize()
    return raw.strip()


def _clean_reasons(raws: list[str]) -> list[str]:
    cleaned = []
    seen: set[str] = set()
    for r in raws:
        c = _clean_one(r)
        if c and c not in seen:
            seen.add(c)
            cleaned.append(c)
    return cleaned


def _best_subscore(breakdown: dict) -> tuple[str | None, float]:
    best_key = None
    best_score = -1.0
    for key, val in breakdown.items():
        if isinstance(val, dict) and "score" in val:
            s = float(val["score"])
        elif isinstance(val, (int, float)):
            s = float(val)
        else:
            continue  # skip OutfitEngine's category→list breakdown
        if s > best_score:
            best_score = s
            best_key = key
    return best_key, best_score


def _subscore_label(key: str, score: float) -> str:
    labels = {
        "color_harmony": "Colors coordinate well together",
        "palette_fit": "Colors fit your season palette",
        "silhouette": "Silhouette is well-balanced",
        "occasion": "Right for the occasion",
        "reuse": "Good rotation — includes items due for wear",
        "preference": "Matches your style preferences",
        "weather": "Appropriate for the weather",
    }
    return labels.get(key, f"{key.replace('_', ' ').capitalize()} looks good")
