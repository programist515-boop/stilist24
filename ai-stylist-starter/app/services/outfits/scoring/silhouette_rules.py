"""Scorer-обёртка над SilhouetteRulesService (Фаза 1 в outfit_scorer).

Сервис возвращает score в ``[-1..+1]``, а ``BaseScorer`` ожидает ``[0..1]`` —
нормализуем через ``(x + 1) / 2``. ``quality='low'`` понижает эффективный
вес, чтобы неполные данные не перевешивали реальные вклады остальных
сub-скореров.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.services.outfits.scoring.base import BaseScorer, ScorerResult
from app.services.silhouette_rules_service import SilhouetteRulesService


def _adapt_item(item: dict) -> SimpleNamespace:
    """Обернуть dict-item в объект с нужными сервису атрибутами.

    Сервис работает через ``_resolve_attr``: сначала читает getattr,
    затем ``attributes_json``. Передаём атрибут первого уровня И
    ``attributes_json`` — это закрывает оба сценария (ORM-объекты и
    тестовые dict-и) без пропусков.
    """
    attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else item
    attrs = attrs if isinstance(attrs, dict) else {}
    return SimpleNamespace(
        id=item.get("id") or attrs.get("id") or "item",
        category=item.get("category") or attrs.get("category"),
        attributes_json=attrs,
        cut_lines=attrs.get("cut_lines"),
        fabric_rigidity=attrs.get("fabric_rigidity"),
        structure=attrs.get("structure"),
        shoulder_emphasis=attrs.get("shoulder_emphasis"),
        sleeve_type=attrs.get("sleeve_type"),
        fit=attrs.get("fit"),
    )


class SilhouetteRulesScorer(BaseScorer):
    """Оценка силуэта по ``silhouette_rules.yaml`` per-subtype.

    Работает поверх существующего ``SilhouetteScorer`` (family-level):
    тот меряет общее соответствие силуэтной семье (natural/gamine/…),
    этот — конкретные per-subtype prefer/avoid и composition-правила.
    """

    weight: float = 0.10

    def __init__(self, service: SilhouetteRulesService | None = None) -> None:
        self._service = service or SilhouetteRulesService()

    def score(self, outfit_items: list[dict], context: dict) -> ScorerResult:
        if not outfit_items:
            return ScorerResult(
                score=0.5,
                weight=0.0,
                warnings=["silhouette_rules: empty outfit — скоринг пропущен"],
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
                warnings=["silhouette_rules: subtype не задан — скоринг пропущен"],
            )

        adapted = [_adapt_item(it) for it in outfit_items]
        result = self._service.evaluate(adapted, user_subtype=subtype)

        normalized = max(0.0, min(1.0, (result.score + 1.0) / 2.0))

        effective_weight = self.weight
        warnings: list[str] = []
        if result.quality == "low":
            effective_weight *= 0.3
            warnings.append("silhouette_rules: quality=low (мало данных или нет правил)")
        elif result.quality == "medium":
            effective_weight *= 0.7

        reasons: list[str] = []
        if result.explanation:
            reasons.append(f"silhouette_rules: {result.explanation}")

        for rid in result.composition_hits:
            reasons.append(f"silhouette_rules: композиция {rid}")

        for v in result.violated_avoid:
            warnings.append(f"silhouette_rules: {v}")

        return ScorerResult(
            score=round(normalized, 3),
            weight=effective_weight,
            reasons=reasons,
            warnings=warnings,
        )
