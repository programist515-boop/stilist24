"""Scorer стилевого аффинити подтипа (Фаза 6 в outfit_scorer).

Применяет ``config/rules/style_subtype_affinity.yaml`` + ``score_modifiers``
к ``style_tags`` вещей образа. Excellent/good/avoid-теги дают буст/штраф,
neutral — ноль.

Если в ``context`` задан ``selected_style``, берутся только те ``style_tags``,
которые совпадают с выбранным стилем (фильтр для UI-селектора стилей).
Если селектор не задан — считается агрегированное аффинити по всем тегам.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.services.outfits.scoring.base import BaseScorer, ScorerResult


_RULES_PATH = Path(__file__).resolve().parents[4] / "config/rules"


def _load_affinity_yaml() -> dict:
    path = _RULES_PATH / "style_subtype_affinity.yaml"
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


# Дефолтные модификаторы — используются, если YAML не загрузился.
_DEFAULT_MODIFIERS = {
    "excellent": 0.12,
    "good": 0.06,
    "neutral": 0.0,
    "avoid": -0.10,
}


class StyleAffinityScorer(BaseScorer):
    """Скоринг соответствия стилей подтипу через style_tags вещей."""

    weight: float = 0.08

    def __init__(self, rules_loader: Any = None) -> None:
        self._rules_loader = rules_loader
        self._data = self._load()

    def _load(self) -> dict:
        if self._rules_loader is not None:
            try:
                rv = self._rules_loader()
                if isinstance(rv, dict):
                    return rv
            except TypeError:
                pass
        return _load_affinity_yaml()

    def score(self, outfit_items: list[dict], context: dict) -> ScorerResult:
        if not outfit_items:
            return ScorerResult(
                score=0.5,
                weight=0.0,
                warnings=["style_affinity: empty outfit — скоринг пропущен"],
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
                warnings=["style_affinity: subtype не задан — скоринг пропущен"],
            )

        affinity_map = (self._data.get("style_subtype_affinity") or {}).get(subtype) or {}
        modifiers: dict = self._data.get("score_modifiers") or _DEFAULT_MODIFIERS

        # Собираем все style_tags со всех вещей.
        all_tags: list[str] = []
        for it in outfit_items:
            attrs = it.get("attributes") if isinstance(it.get("attributes"), dict) else it
            tags = attrs.get("style_tags") if isinstance(attrs, dict) else None
            if isinstance(tags, list):
                all_tags.extend(t for t in tags if isinstance(t, str))

        if not affinity_map:
            return ScorerResult(
                score=0.5,
                weight=self.weight * 0.3,
                warnings=[
                    f"style_affinity: подтип «{subtype}» — placeholder, все neutral"
                ],
            )

        if not all_tags:
            return ScorerResult(
                score=0.5,
                weight=self.weight * 0.3,
                warnings=["style_affinity: у вещей нет style_tags"],
            )

        selected_style = context.get("selected_style")
        if selected_style:
            relevant = [t for t in all_tags if t == selected_style]
            if not relevant:
                return ScorerResult(
                    score=0.3,
                    weight=self.weight,
                    warnings=[
                        f"style_affinity: выбран стиль {selected_style}, "
                        "ни одна вещь не тегирована им"
                    ],
                )
            all_tags = relevant

        deltas: list[float] = []
        hits: list[str] = []
        for tag in all_tags:
            level = affinity_map.get(tag, "neutral")
            delta = float(modifiers.get(level, 0.0))
            deltas.append(delta)
            hits.append(f"{tag}={level}")

        avg_delta = sum(deltas) / len(deltas)

        # Линейно нормализуем среднее в [0..1]. score_modifier в YAML:
        # excellent=+0.12, avoid=-0.10. Умножаем на 4 — получается
        # ~[-0.4..+0.48], сдвигаем на 0.5 и клампим.
        normalized = max(0.0, min(1.0, 0.5 + avg_delta * 4.0))

        reasons: list[str] = []
        warnings: list[str] = []

        # Детерминированный ранкинг тегов по level для первых 5 упоминаний
        ordered = sorted(set(hits))
        summary = ", ".join(ordered[:5])
        reasons.append(
            f"style_affinity: средний модификатор {avg_delta:+.2f} "
            f"({summary})"
        )
        # avoid-теги — в warnings
        avoid_tags = [
            t for t in all_tags if affinity_map.get(t) == "avoid"
        ]
        if avoid_tags:
            warnings.append(
                "style_affinity: стили {} отмечены 'avoid' для подтипа".format(
                    ", ".join(sorted(set(avoid_tags)))
                )
            )

        return ScorerResult(
            score=round(normalized, 3),
            weight=self.weight,
            reasons=reasons,
            warnings=warnings,
        )
