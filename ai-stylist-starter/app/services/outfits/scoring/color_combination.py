"""Color combination scorer (Фаза 4 в outfit_scorer).

Обёртка над ``ColorCombinationService`` под интерфейс ``BaseScorer``:
сервис возвращает score в [-1..+1], scorer'у нужно [0..1] — нормализуем
через ``(x + 1) / 2``. ``quality='low'`` занижает эффективный вес, чтобы
неполные данные не перевешивали реально определённые вклады.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.services.color_combination_service import ColorCombinationService
from app.services.outfits.scoring.base import BaseScorer, ScorerResult


def _adapt_item(item: dict) -> SimpleNamespace:
    """Обернуть dict-item в объект с нужными сервису атрибутами."""
    attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else item
    return SimpleNamespace(
        id=item.get("id") or attrs.get("id") or "item",
        category=item.get("category") or attrs.get("category"),
        attributes_json=attrs if isinstance(attrs, dict) else {},
        fabric_finish=attrs.get("fabric_finish") if isinstance(attrs, dict) else None,
        pattern_scale=attrs.get("pattern_scale") if isinstance(attrs, dict) else None,
    )


class ColorCombinationScorer(BaseScorer):
    """Оценка цветовых сочетаний образа по ``color_schemes.yaml``.

    Работает поверх существующего ``color_harmony`` scorer'а: тот меряет,
    как цвета каждой вещи по отдельности попадают в палитру цветотипа,
    а этот — как они сочетаются между собой в пределах образа.
    """

    weight: float = 0.15

    def __init__(self, service: ColorCombinationService | None = None) -> None:
        self._service = service or ColorCombinationService()

    def score(self, outfit_items: list[dict], context: dict) -> ScorerResult:
        if not outfit_items:
            return ScorerResult(
                score=0.5,
                weight=0.0,
                warnings=["color_combination: empty outfit — скоринг пропущен"],
            )

        subtype: str = (
            context.get("kibbe_type")
            or context.get("identity_subtype")
            or context.get("subtype")
            or ""
        )
        color_profile: Any = context.get("color_profile") or {}
        season = (
            context.get("color_season")
            or (color_profile.get("season_top_1") if isinstance(color_profile, dict) else None)
            or ""
        )

        adapted = [_adapt_item(it) for it in outfit_items]
        result = self._service.evaluate(adapted, user_subtype=subtype, user_season=season)

        normalized = max(0.0, min(1.0, (result.score + 1.0) / 2.0))

        # Неполные данные → вес пропорционально снижаем,
        # чтобы выборка из 1 определённого цвета не доминировала.
        effective_weight = self.weight
        warnings: list[str] = []
        if result.quality == "low":
            effective_weight *= 0.3
            warnings.append("color_combination: quality=low (мало данных о цвете)")
        elif result.quality == "medium":
            effective_weight *= 0.7

        reasons = [f"color_combination: {result.explanation}"] if result.explanation else []
        for s in result.matched_schemes:
            reasons.append(
                f"color_combination: схема {s.scheme} (confidence {s.confidence:.2f})"
            )
        for f in result.forbidden_hits:
            warnings.append(f"color_combination: {f.reason}")

        return ScorerResult(
            score=round(normalized, 3),
            weight=effective_weight,
            reasons=reasons,
            warnings=warnings,
        )
