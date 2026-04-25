"""Сервис оценки силуэтных правил образа per-subtype.

Фаза 1 плана ``plans/2026-04-21-каталог-фич-из-отчёта-типажа.md``.

Принцип работы
--------------
На вход — список вещей образа (``WardrobeItem`` или duck-typed объекты с
полями Фазы 0) и подтип пользователя. Сервис:

1. Загружает ``config/rules/silhouette_rules.yaml``, берёт блок для
   подтипа (``prefer`` / ``avoid`` / ``composition_rules``).
2. Применяет детекторы, которые проверяются исключительно по формальным
   атрибутам вещи — без обращения к CV-картинкам:
   ``cut_lines``, ``fabric_rigidity``, ``structure``, ``shoulder_emphasis``,
   ``sleeve_type``, ``fit``.
3. Для каждого сработавшего правила добавляет score-delta
   (boost/penalty из YAML или дефолт) и человекочитаемое объяснение.
4. Возвращает ``SilhouetteRulesResult`` со score в ``[-1.0, +1.0]``.

Архитектурная граница
---------------------
Этот сервис НЕ дублирует цветовые композиционные правила — они живут в
``ColorCombinationService``. Правила ``broken_by_color`` и
``unbroken_vertical`` из YAML игнорируются здесь: их обсчитывает
``ColorCombinationService`` через ``color_schemes.yaml``. Разделение
ответственности: силуэт vs цвет.

Дизайн-принципы
---------------
* **Честный quality.** Если у >=50% вещей не заполнены ключевые атрибуты
  Фазы 0 (``cut_lines``, ``fabric_rigidity``, ``sleeve_type``) —
  ``quality='low'`` и scorer-обёртка понижает вес.
* **Placeholder-подтипы.** Если ``prefer`` и ``avoid`` и
  ``composition_rules`` для подтипа все пустые — возвращается
  нейтральный результат с ``quality='low'`` и объяснением, что
  правила для подтипа ещё не наполнены (не штраф).
* **Детерминизм.** Сортировка items by id, порядок объяснений стабилен.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

# NB: ``WardrobeItem`` импортируется только для типа. Сервис работает с
# duck-typed объектами — любой объект с getattr на нужные поля подойдёт.


# ----------------------------- модели результата ---------------------------


@dataclass
class SilhouetteRulesResult:
    """Итог оценки силуэтных правил образа."""

    score: float                                        # -1..+1
    explanation: str
    matched_prefer: list[str] = field(default_factory=list)   # префер-правила, которые сработали
    violated_avoid: list[str] = field(default_factory=list)   # avoid-правила, которые нарушены
    composition_hits: list[str] = field(default_factory=list) # id composition-правил
    quality: Literal["high", "medium", "low"] = "high"


# ----------------------------- helpers: загрузка YAML ----------------------


_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "config/rules"


def _load_silhouette_rules() -> dict:
    path = _RULES_PATH / "silhouette_rules.yaml"
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


# ----------------------------- helpers: атрибуты ---------------------------


# Категории вещей, различаемые правилами силуэта. Совпадают с
# аналогичным списком в ``color_combination_service`` — пока дублирование
# оправдано: сервисы независимы, категории меняются очень редко.
_TOP_CATEGORIES = {
    "top", "tops", "blouse", "shirt", "sweater", "jacket", "blazer",
    "t_shirt", "tshirt", "outerwear", "coat",
}
_BOTTOM_CATEGORIES = {
    "bottom", "bottoms", "pants", "skirt", "jeans", "trousers", "shorts",
}


def _resolve_attr(item: Any, name: str) -> Any:
    """Вернуть атрибут ``name`` с поддержкой колонки и attributes_json.

    Поля Фазы 0 живут колонками в ``WardrobeItem`` и могут одновременно
    встречаться в ``attributes_json`` у тестовых/dict-подобных объектов.
    Сначала смотрим колонку, затем JSON.
    """
    value = getattr(item, name, None)
    if value is not None:
        return value
    attrs = getattr(item, "attributes_json", None)
    if isinstance(attrs, dict):
        v = attrs.get(name)
        if v is not None:
            return v
    return None


def _category(item: Any) -> str | None:
    cat = getattr(item, "category", None)
    if not cat:
        attrs = getattr(item, "attributes_json", None)
        if isinstance(attrs, dict):
            cat = attrs.get("category")
    return cat.lower() if isinstance(cat, str) else None


def _is_top(item: Any) -> bool:
    cat = _category(item)
    return cat in _TOP_CATEGORIES if cat else False


def _is_bottom(item: Any) -> bool:
    cat = _category(item)
    return cat in _BOTTOM_CATEGORIES if cat else False


def _is_dress(item: Any) -> bool:
    return _category(item) == "dress"


def _item_id(item: Any) -> str:
    iid = getattr(item, "id", None) or getattr(item, "item_id", None)
    return str(iid) if iid is not None else "item"


# ----------------------------- детекторы -----------------------------------
#
# Все детекторы возвращают ``(matched: bool, note: str)``. ``note`` — готовая
# строка для объяснения, на русском. ``matched=False`` → note игнорируется.


def _detect_shoulder_emphasis_present(items: list[Any]) -> tuple[bool, str]:
    """Хотя бы одна вещь с ``shoulder_emphasis=required``."""
    ids = [
        _item_id(it) for it in items
        if _resolve_attr(it, "shoulder_emphasis") == "required"
    ]
    if not ids:
        return False, ""
    return True, f"Плечи выделены ({len(ids)} вещ.) — подтип любит акцент"


def _detect_shoulder_avoided(items: list[Any]) -> tuple[bool, str]:
    """Все вещи верха — ``shoulder_emphasis=avoided``."""
    tops_and_dresses = [it for it in items if _is_top(it) or _is_dress(it)]
    if not tops_and_dresses:
        return False, ""
    values = [_resolve_attr(it, "shoulder_emphasis") for it in tops_and_dresses]
    if all(v == "avoided" for v in values if v is not None) and any(
        v is not None for v in values
    ):
        return True, "У всех верхов плечи не выделены — подтип теряет свой акцент"
    return False, ""


def _detect_raglan_or_dropped(items: list[Any]) -> tuple[bool, str]:
    """``sleeve_type`` попадает в ``raglan`` или ``dropped_shoulder``."""
    bad_ids = [
        _item_id(it) for it in items
        if _resolve_attr(it, "sleeve_type") in {"raglan", "dropped_shoulder"}
    ]
    if not bad_ids:
        return False, ""
    return True, "Реглан/приспущенный рукав — размывают линию плеча"


def _detect_soft_without_structure(items: list[Any]) -> tuple[bool, str]:
    """Есть soft-вещь, но ни одной structured/semi_structured."""
    has_soft = any(
        _resolve_attr(it, "fabric_rigidity") == "soft"
        or _resolve_attr(it, "cut_lines") == "soft_flowing"
        for it in items
    )
    has_structure = any(
        _resolve_attr(it, "structure") in {"structured", "semi_structured"}
        or _resolve_attr(it, "fabric_rigidity") == "rigid"
        for it in items
    )
    if has_soft and not has_structure:
        return True, "Мягкие ткани без структурной опоры — силуэт теряет форму"
    return False, ""


def _detect_all_soft_flowing(items: list[Any]) -> tuple[bool, str]:
    """Все вещи с ``cut_lines=soft_flowing`` (composition_rule
    ``soft_top_and_soft_bottom``)."""
    values = [_resolve_attr(it, "cut_lines") for it in items]
    known = [v for v in values if v is not None]
    if not known:
        return False, ""
    if all(v == "soft_flowing" for v in known) and len(known) >= 2:
        return True, "Весь образ из мягких линий — нет контраста и энергии"
    return False, ""


def _detect_angular_majority(items: list[Any]) -> tuple[bool, str]:
    """Большинство вещей с ``cut_lines=angular`` → bonus за edge_clarity/линии."""
    values = [_resolve_attr(it, "cut_lines") for it in items]
    known = [v for v in values if v is not None]
    if len(known) < 2:
        return False, ""
    angular = sum(1 for v in known if v == "angular")
    if angular / len(known) >= 0.5:
        return True, f"Преобладают угловатые линии ({angular}/{len(known)})"
    return False, ""


def _detect_soft_curved_majority(items: list[Any]) -> tuple[bool, str]:
    """Большинство вещей с ``cut_lines=soft_flowing`` — нарушение
    ``avoid.line_character=[curved, wavy]``."""
    values = [_resolve_attr(it, "cut_lines") for it in items]
    known = [v for v in values if v is not None]
    if len(known) < 2:
        return False, ""
    soft = sum(1 for v in known if v == "soft_flowing")
    if soft / len(known) >= 0.5:
        return True, f"Преобладают плавные линии ({soft}/{len(known)})"
    return False, ""


def _detect_mix_opposing_fits(items: list[Any]) -> tuple[bool, str]:
    """Есть fitted-вещь и oversized/loose-вещь одновременно (composition_rule
    ``narrow_base_plus_wide_opposite``)."""

    def _fit(it: Any) -> str:
        return str(_resolve_attr(it, "fit") or "").lower()

    fits = [_fit(it) for it in items]
    has_fitted = any("fitted" in f or "slim" in f for f in fits)
    has_loose = any("oversized" in f or "loose" in f or "wide" in f for f in fits)
    if has_fitted and has_loose:
        return True, "Узкое + широкое: игра противоположных объёмов"
    return False, ""


def _detect_both_oversized(items: list[Any]) -> tuple[bool, str]:
    """Верх и низ одновременно oversized/loose (нарушение
    ``avoid.oversized_both_top_bottom``)."""
    def _is_loose(it: Any) -> bool:
        fit = str(_resolve_attr(it, "fit") or "").lower()
        return "oversized" in fit or "loose" in fit or "wide" in fit

    top_loose = any(_is_loose(it) for it in items if _is_top(it))
    bottom_loose = any(_is_loose(it) for it in items if _is_bottom(it))
    if top_loose and bottom_loose:
        return True, "Объёмный верх + объёмный низ — бесформенный силуэт"
    return False, ""


def _detect_drape_with_angular(items: list[Any]) -> tuple[bool, str]:
    """Есть soft-драпировка И есть angular-контраст (composition_rule
    ``drape_with_angular_counterpart``)."""
    has_soft_drape = any(
        _resolve_attr(it, "fabric_rigidity") == "soft"
        or _resolve_attr(it, "cut_lines") == "soft_flowing"
        for it in items
    )
    has_angular = any(
        _resolve_attr(it, "cut_lines") == "angular"
        or _resolve_attr(it, "fabric_rigidity") == "rigid"
        for it in items
    )
    if has_soft_drape and has_angular:
        return True, "Драпировка + острый контраст — нужный FG-баланс"
    return False, ""


def _detect_preferred_cut(items: list[Any], preferred_cuts: list[str]) -> tuple[bool, str]:
    """Хотя бы половина вещей попадает в ``prefer.cut`` (значения из YAML)."""
    if not preferred_cuts:
        return False, ""
    fits = [str(_resolve_attr(it, "fit") or "").lower() for it in items]
    known = [f for f in fits if f]
    if len(known) < 2:
        return False, ""
    hits = sum(
        1 for f in known
        if any(c.lower() in f or f == c.lower() for c in preferred_cuts)
    )
    if hits / len(known) >= 0.5:
        return True, f"Крой соответствует предпочтениям подтипа ({hits}/{len(known)})"
    return False, ""


# ----------------------------- композиционные правила ---------------------

# Id → (detector, default_boost, default_penalty). ``default_*`` используются,
# если YAML-правило не задаёт ``score_boost`` / ``score_penalty`` явно.
_COMPOSITION_DETECTORS: dict[str, Any] = {
    "narrow_base_plus_wide_opposite": (_detect_mix_opposing_fits, 0.10, 0.0),
    "drape_with_angular_counterpart": (_detect_drape_with_angular, 0.05, 0.0),
    "soft_top_and_soft_bottom": (_detect_all_soft_flowing, 0.0, 0.14),
}

# Id-ы, сознательно отданные другому сервису.
_COLOR_DOMAIN_IDS = {"broken_by_color", "unbroken_vertical"}


# ----------------------------- сервис --------------------------------------


class SilhouetteRulesService:
    """Оценка силуэтных правил образа (Фаза 1).

    Параметры
    ---------
    rules_loader:
        Опциональный callable, возвращающий dict из ``silhouette_rules.yaml``.
        Удобно для тестов и для слоя rules_loader'а проекта.
    """

    def __init__(self, rules_loader: Any = None) -> None:
        self._rules_loader = rules_loader
        self._rules = self._load_rules()

    def _load_rules(self) -> dict:
        if self._rules_loader is not None:
            try:
                data = self._rules_loader()
                if isinstance(data, dict):
                    if "silhouette_rules" in data:
                        return data
                    return {"silhouette_rules": data}
            except TypeError:
                pass
        return _load_silhouette_rules()

    # ------------------------------------------------------------------ API

    def evaluate(
        self,
        items: list[Any],
        user_subtype: str,
    ) -> SilhouetteRulesResult:
        """Оценить силуэт образа относительно правил подтипа."""
        if not items:
            return SilhouetteRulesResult(
                score=0.0,
                explanation="Образ пустой — нечего оценивать.",
                quality="low",
            )

        # Сортируем для детерминизма
        items = sorted(items, key=_item_id)

        block = (self._rules.get("silhouette_rules") or {}).get(user_subtype) or {}
        prefer: dict = block.get("prefer") or {}
        avoid: dict = block.get("avoid") or {}
        composition: list = block.get("composition_rules") or []

        if not prefer and not avoid and not composition:
            return SilhouetteRulesResult(
                score=0.0,
                explanation=(
                    f"Правила силуэта для подтипа «{user_subtype}» ещё не наполнены — "
                    "оценка нейтральная."
                ),
                quality="low",
            )

        # ---------------- честный quality по полноте атрибутов ----------------
        key_fields = ("cut_lines", "fabric_rigidity", "sleeve_type")
        missing = 0
        total = 0
        for it in items:
            for f in key_fields:
                total += 1
                if _resolve_attr(it, f) is None:
                    missing += 1
        missing_ratio = missing / total if total else 1.0
        if missing_ratio >= 0.5:
            quality: Literal["high", "medium", "low"] = "low"
        elif missing_ratio > 0.0:
            quality = "medium"
        else:
            quality = "high"

        matched_prefer: list[str] = []
        violated_avoid: list[str] = []
        composition_hits: list[str] = []
        notes: list[str] = []
        score = 0.0

        # ---------------- prefer ------------------------------------------------

        # shoulder_emphasis: required → ищем хотя бы одну вещь с required
        if prefer.get("shoulder_emphasis") == "required":
            matched, note = _detect_shoulder_emphasis_present(items)
            if matched:
                matched_prefer.append("prefer.shoulder_emphasis=required")
                notes.append(note)
                score += 0.08

        # line_character: angular — хотим больше angular cut_lines
        if prefer.get("line_character") == "angular":
            matched, note = _detect_angular_majority(items)
            if matched:
                matched_prefer.append("prefer.line_character=angular")
                notes.append(note)
                score += 0.06

        # cut: [straight, semi_fitted] — буст за попадание крой-а в список
        preferred_cuts = prefer.get("cut")
        if isinstance(preferred_cuts, list) and preferred_cuts:
            matched, note = _detect_preferred_cut(items, preferred_cuts)
            if matched:
                matched_prefer.append(f"prefer.cut∈{preferred_cuts}")
                notes.append(note)
                score += 0.05

        # mix_opposing_shapes: bonus — доп. буст, если prefer говорит bonus
        if prefer.get("mix_opposing_shapes") in {"bonus", True, "required"}:
            matched, note = _detect_mix_opposing_fits(items)
            if matched:
                matched_prefer.append("prefer.mix_opposing_shapes")
                notes.append(note)
                score += 0.05

        # ---------------- avoid ------------------------------------------------

        # raglan_or_dropped_shoulder: true
        if avoid.get("raglan_or_dropped_shoulder") is True:
            matched, note = _detect_raglan_or_dropped(items)
            if matched:
                violated_avoid.append("avoid.raglan_or_dropped_shoulder")
                notes.append(note)
                score -= 0.10

        # oversized_both_top_bottom: true
        if avoid.get("oversized_both_top_bottom") is True:
            matched, note = _detect_both_oversized(items)
            if matched:
                violated_avoid.append("avoid.oversized_both_top_bottom")
                notes.append(note)
                score -= 0.12

        # draped_without_structure: true
        if avoid.get("draped_without_structure") is True:
            matched, note = _detect_soft_without_structure(items)
            if matched:
                violated_avoid.append("avoid.draped_without_structure")
                notes.append(note)
                score -= 0.10

        # line_character: [curved, wavy]
        lc_avoid = avoid.get("line_character")
        if isinstance(lc_avoid, list) and (
            "curved" in lc_avoid or "wavy" in lc_avoid or "soft_flowing" in lc_avoid
        ):
            matched, note = _detect_soft_curved_majority(items)
            if matched:
                violated_avoid.append(f"avoid.line_character∈{lc_avoid}")
                notes.append(note)
                score -= 0.08

        # shoulder emphasis полностью avoided — тонкий сигнал
        if prefer.get("shoulder_emphasis") == "required":
            matched, note = _detect_shoulder_avoided(items)
            if matched:
                violated_avoid.append("avoid.shoulder_all_avoided")
                notes.append(note)
                score -= 0.06

        # ---------------- composition_rules -----------------------------------

        for rule in composition:
            if not isinstance(rule, dict):
                continue
            rid = rule.get("id")
            if not rid:
                continue
            if rid in _COLOR_DOMAIN_IDS:
                # Отдано ColorCombinationService
                continue
            detector_spec = _COMPOSITION_DETECTORS.get(rid)
            if detector_spec is None:
                # Неизвестный id — YAML «живой», пропускаем молча.
                continue
            detector, default_boost, default_penalty = detector_spec
            matched, note = detector(items)
            if not matched:
                continue
            boost = float(rule.get("score_boost") or default_boost or 0.0)
            penalty = float(rule.get("score_penalty") or default_penalty or 0.0)
            if boost > 0:
                score += boost
                composition_hits.append(rid)
                notes.append(f"{rid}: +{boost:.2f} — {note}")
            elif penalty > 0:
                score -= penalty
                composition_hits.append(rid)
                notes.append(f"{rid}: -{penalty:.2f} — {note}")

        # ---------------- финализация -----------------------------------------

        score = max(-1.0, min(1.0, score))

        if not notes:
            notes.append(
                "Силуэт нейтральный — явных попаданий и нарушений не найдено."
            )
        explanation = " · ".join(notes)

        return SilhouetteRulesResult(
            score=round(score, 3),
            explanation=explanation,
            matched_prefer=matched_prefer,
            violated_avoid=violated_avoid,
            composition_hits=composition_hits,
            quality=quality,
        )


__all__ = [
    "SilhouetteRulesService",
    "SilhouetteRulesResult",
]
