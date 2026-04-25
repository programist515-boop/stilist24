"""Scorer-обёртка над CategoryRulesService (Фаза 2 в outfit_scorer).

Сервис возвращает score в ``[-1..+1]``, а ``BaseScorer`` ожидает ``[0..1]`` —
нормализуем через ``(x + 1) / 2``. ``quality='low'`` понижает эффективный
вес.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.services.category_rules_service import CategoryRulesService
from app.services.outfits.scoring.base import BaseScorer, ScorerResult


def _adapt_item(item: dict) -> SimpleNamespace:
    """Обернуть dict-item в объект с нужными сервису атрибутами."""
    attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else item
    attrs = attrs if isinstance(attrs, dict) else {}
    # Собираем полный кортеж потенциальных атрибутов: колонки Фазы 0 и
    # часто встречающиеся нативные (fit, length, shape, …).
    return SimpleNamespace(
        id=item.get("id") or attrs.get("id") or "item",
        category=item.get("category") or attrs.get("category"),
        attributes_json=attrs,
        # Фаза 0
        cut_lines=attrs.get("cut_lines"),
        fabric_rigidity=attrs.get("fabric_rigidity"),
        fabric_finish=attrs.get("fabric_finish"),
        structure=attrs.get("structure"),
        shoulder_emphasis=attrs.get("shoulder_emphasis"),
        sleeve_type=attrs.get("sleeve_type"),
        sleeve_length=attrs.get("sleeve_length"),
        neckline_type=attrs.get("neckline_type"),
        pattern_scale=attrs.get("pattern_scale"),
        pattern_character=attrs.get("pattern_character"),
        pattern_symmetry=attrs.get("pattern_symmetry"),
        detail_scale=attrs.get("detail_scale"),
        occasion=attrs.get("occasion"),
        style_tags=attrs.get("style_tags"),
        # нативные (не-Фаза-0) — живут в attributes_json
        fit=attrs.get("fit"),
        length=attrs.get("length"),
        shape=attrs.get("shape"),
        weight=attrs.get("weight"),
        heel_type=attrs.get("heel_type"),
        finish=attrs.get("finish"),
        toe_shape=attrs.get("toe_shape"),
        closure=attrs.get("closure"),
        sub_type=attrs.get("sub_type"),
        waist_rise=attrs.get("waist_rise"),
        details=attrs.get("details"),
        material_bonus=attrs.get("material_bonus"),
    )


class CategoryRulesScorer(BaseScorer):
    """Оценка образа по правилам категорий ``category_rules/*.yaml``.

    Каждая вещь образа оценивается по правилам своей категории
    относительно подтипа пользователя. Среднее по вещам —
    вклад этого scorer'а.
    """

    weight: float = 0.10

    def __init__(self, service: CategoryRulesService | None = None) -> None:
        self._service = service or CategoryRulesService()

    def score(self, outfit_items: list[dict], context: dict) -> ScorerResult:
        if not outfit_items:
            return ScorerResult(
                score=0.5,
                weight=0.0,
                warnings=["category_rules: empty outfit — скоринг пропущен"],
            )

        subtype: str = (
            context.get("kibbe_type")
            or context.get("identity_subtype")
            or context.get("subtype")
            or ""
        )
        if not subtype:
            return ScorerResult(
                score=0.5,
                weight=0.0,
                warnings=["category_rules: subtype не задан — скоринг пропущен"],
            )

        adapted = [_adapt_item(it) for it in outfit_items]
        result = self._service.evaluate(adapted, user_subtype=subtype)

        normalized = max(0.0, min(1.0, (result.score + 1.0) / 2.0))

        effective_weight = self.weight
        warnings: list[str] = []
        if result.quality == "low":
            effective_weight *= 0.3
            warnings.append(
                "category_rules: quality=low (мало атрибутов или подтип placeholder)"
            )
        elif result.quality == "medium":
            effective_weight *= 0.7

        reasons: list[str] = []
        if result.explanation:
            reasons.append(f"category_rules: {result.explanation}")

        return ScorerResult(
            score=round(normalized, 3),
            weight=effective_weight,
            reasons=reasons,
            warnings=warnings,
        )
