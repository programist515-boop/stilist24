"""Human-readable explanation formatter (UX Simplification Sprint).

Produces a compact, Russian-language ``Explanation`` object:

    {
        "summary": "Хорошее сочетание",
        "reasons": ["Цвет хорошо подходит вам", "Сочетается с гардеробом"],
        "warnings": ["Сложно сочетать с другими вещами"],
    }

Rules (enforced in this module — downstream callers can rely on them):
* summary — одно короткое предложение
* reasons — максимум 3
* warnings — максимум 2
* никаких технических терминов (score, penalty, threshold, compatibility index)
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Shared label dictionary (Block 3)
# ---------------------------------------------------------------------------

LABELS: dict[str, str] = {
    "high": "Базовая вещь",
    "medium": "Универсальная",
    "low": "Ограниченно сочетается",
    "orphan": "Почти не используется",
}


MAX_SUMMARY_LEN = 1      # single sentence
MAX_REASONS = 3
MAX_WARNINGS = 2


@dataclass
class Explanation:
    """Structured user-facing explanation."""

    summary: str
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "reasons": self.reasons[:MAX_REASONS],
            "warnings": self.warnings[:MAX_WARNINGS],
        }


# ---------------------------------------------------------------------------
# Outfit explanation
# ---------------------------------------------------------------------------

def explain_outfit(outfit: dict) -> Explanation:
    """Convert an outfit dict (from OutfitGenerator) into a user-facing Explanation."""
    score = outfit.get("total_score") or outfit.get("scores", {}).get("overall", 0.0)
    breakdown = outfit.get("breakdown") or {}

    if score >= 0.75:
        summary = "Отличный образ"
    elif score >= 0.55:
        summary = "Хорошее сочетание"
    elif score >= 0.35:
        summary = "Неплохой вариант"
    else:
        summary = "Стоит доработать"

    reasons: list[str] = []
    warnings: list[str] = []

    for key, score_val in _iter_subscores(breakdown):
        if score_val >= 0.7:
            reason = _SUBSCORE_POS.get(key)
            if reason and reason not in reasons:
                reasons.append(reason)
        elif score_val < 0.35:
            warning = _SUBSCORE_NEG.get(key)
            if warning and warning not in warnings:
                warnings.append(warning)

    return Explanation(summary=summary, reasons=reasons[:MAX_REASONS], warnings=warnings[:MAX_WARNINGS])


# ---------------------------------------------------------------------------
# Shopping explanation
# ---------------------------------------------------------------------------

_SHOPPING_DECISION_SUMMARY = {
    "buy": "Стоит купить",
    "maybe": "Можно рассмотреть",
    "skip": "Лучше пропустить",
}


def explain_shopping(result: dict) -> Explanation:
    """Produce a user-facing Explanation from a PurchaseEvaluator result dict."""
    decision = result.get("decision", "maybe")
    subscores = result.get("subscores") or {}

    summary = _SHOPPING_DECISION_SUMMARY.get(decision, "Можно рассмотреть")

    reasons: list[str] = []
    warnings: list[str] = []

    for key, label_hi, label_lo in _SHOPPING_SUBSCORE_MAP:
        s = subscores.get(key, {}).get("score")
        if s is None:
            continue
        if s >= 0.7 and label_hi and label_hi not in reasons:
            reasons.append(label_hi)
        elif s < 0.35 and label_lo and label_lo not in warnings:
            warnings.append(label_lo)

    return Explanation(
        summary=summary,
        reasons=reasons[:MAX_REASONS],
        warnings=warnings[:MAX_WARNINGS],
    )


# ---------------------------------------------------------------------------
# Versatility explanation
# ---------------------------------------------------------------------------

def explain_versatility(result: dict) -> Explanation:
    """Produce a user-facing Explanation from a VersatilityService result dict."""
    outfit_count = result.get("outfit_count", 0)
    is_orphan = result.get("is_orphan", True)

    status = _versatility_status(outfit_count, is_orphan)
    summary = _VERSATILITY_SUMMARY[status]

    reasons: list[str] = []
    warnings: list[str] = []

    if not is_orphan:
        reasons.append("Хорошо сочетается с гардеробом")
    else:
        warnings.append("Сложно сочетать с другими вещами")

    return Explanation(
        summary=summary,
        reasons=reasons[:MAX_REASONS],
        warnings=warnings[:MAX_WARNINGS],
    )


# ---------------------------------------------------------------------------
# Gap analysis action label
# ---------------------------------------------------------------------------

def gap_action_label(category: str) -> str:
    """Return a short friendly action string for a missing wardrobe category."""
    return "Попробовать добавить"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SUBSCORE_POS: dict[str, str] = {
    "palette_fit": "Цвет хорошо подходит вам",
    "color_harmony": "Цвета хорошо сочетаются",
    "silhouette": "Силуэт сбалансирован",
    "occasion": "Подходит под повод",
    "preference": "В вашем стиле",
    "reuse": "Свежее сочетание",
    "weather": "Подходит по погоде",
}

_SUBSCORE_NEG: dict[str, str] = {
    "palette_fit": "Цвет может не подойти",
    "color_harmony": "Цвета не очень сочетаются",
    "silhouette": "Силуэт несбалансирован",
    "occasion": "Не совсем под повод",
    "preference": "Не в вашем обычном стиле",
    "weather": "Не подходит по погоде",
}

_SHOPPING_SUBSCORE_MAP: list[tuple[str, str | None, str | None]] = [
    ("palette_match", "Цвет хорошо подходит вам", "Цвет может не подойти"),
    ("gap_fill", "Закроет пробел в гардеробе", "Похожее уже есть"),
    ("wardrobe_compat", "Сочетается с гардеробом", "Мало с чем сочетается"),
    ("redundancy_penalty", None, "Похожее уже есть"),
    ("expected_versatility", "Хорошо раскроется в образах", "Сложно будет сочетать"),
]

_VERSATILITY_SUMMARY: dict[str, str] = {
    "high": "Базовая вещь — легко сочетать",
    "medium": "Универсальная вещь",
    "low": "Ограниченно сочетается",
    "orphan": "Почти не используется",
}


def _versatility_status(outfit_count: int, is_orphan: bool) -> str:
    if is_orphan:
        return "orphan"
    if outfit_count >= 8:
        return "high"
    if outfit_count >= 4:
        return "medium"
    return "low"


def _iter_subscores(breakdown: dict):
    for key, val in breakdown.items():
        if isinstance(val, dict) and "score" in val:
            yield key, float(val["score"])
        elif isinstance(val, (int, float)):
            yield key, float(val)


__all__ = [
    "Explanation",
    "LABELS",
    "explain_outfit",
    "explain_shopping",
    "explain_versatility",
    "gap_action_label",
]
