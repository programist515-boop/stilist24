"""Сервис оценки вещи по правилам её категории per-subtype.

Фаза 2 плана ``plans/2026-04-21-каталог-фич-из-отчёта-типажа.md``.

Принцип работы
--------------
Для каждой вещи в образе сервис:

1. Определяет категорию-файл в ``config/rules/category_rules/`` по
   ``item.category`` (через словарь алиасов).
2. Берёт блок правил для подтипа пользователя:
   ``rules[user_subtype].prefer`` + ``stop[]``.
3. По ``prefer`` суммирует буст за атрибуты, попадающие в список
   предпочтений. Поддерживаются списки, скаляры, ``bonus``-метки.
4. По ``stop`` — справочник причин для объяснений (каждый rule имеет
   поле ``reason``). Полноценный маппинг stop-правил на предикаты —
   follow-up (каждое правило требует знания специфики категории).
5. Возвращает ``CategoryRuleScore`` со score в ``[-1.0, +1.0]``,
   matched_prefer[], stop_notes[], quality.

Сервис сознательно дополняет (не дублирует) ``SilhouetteRulesService`` —
тот работает на уровне *образа* и общих силуэтных атрибутов, этот — на
уровне *вещи* и её конкретных атрибутов категории (длина, крой, каблук,
фурнитура). Сигналы разные.

Дизайн-принципы
---------------
* **Честный quality**: если подтип placeholder (пустой prefer/stop) —
  ``quality='low'`` и нейтральный score. Если у вещи нет ни одного
  из оцениваемых атрибутов — тоже low.
* **Детерминизм**: сортировка items by id, порядок объяснений стабилен.
* **Отказоустойчивость**: YAML-файл категории может отсутствовать —
  возвращаем нейтральный результат с warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml


# ----------------------------- модели результата ---------------------------


@dataclass
class CategoryRuleScore:
    """Итог оценки одной вещи по правилам её категории."""

    item_id: str
    category: str | None
    score: float                               # -1..+1
    matched_prefer: list[str] = field(default_factory=list)
    matched_stop: list[str] = field(default_factory=list)
    stop_notes: list[str] = field(default_factory=list)
    quality: Literal["high", "medium", "low"] = "high"


@dataclass
class CategoryRulesOutfitResult:
    """Итог оценки всех вещей образа по category_rules."""

    score: float                               # -1..+1 (среднее по вещам)
    explanation: str                           # на русском
    per_item: list[CategoryRuleScore] = field(default_factory=list)
    quality: Literal["high", "medium", "low"] = "high"


# ----------------------------- загрузка YAML -------------------------------


_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "config/rules"
_CATEGORY_RULES_DIR = _RULES_PATH / "category_rules"


# item.category (lower) → имя файла без .yaml
# Один файл может соответствовать нескольким алиасам.
_CATEGORY_FILE_ALIASES: dict[str, str] = {
    # ---- верх
    "blouse": "blouses",
    "blouses": "blouses",
    "shirt": "blouses",
    "tshirt": "blouses",
    "t_shirt": "blouses",
    "top": "blouses",
    "tops": "blouses",
    # ---- жакеты/блейзеры
    "jacket": "jackets",
    "jackets": "jackets",
    "blazer": "jackets",
    # ---- свитера
    "sweater": "sweaters",
    "sweaters": "sweaters",
    "knit": "sweaters",
    "knitwear": "sweaters",
    "cardigan": "sweaters",
    # ---- верхняя
    "coat": "outerwear",
    "outerwear": "outerwear",
    "trench": "outerwear",
    "puffer": "outerwear",
    "parka": "outerwear",
    # ---- платья
    "dress": "dresses",
    "dresses": "dresses",
    # ---- низ
    "pants": "pants",
    "trousers": "pants",
    "jeans": "pants",
    "shorts": "pants",
    "skirt": "skirts",
    "skirts": "skirts",
    # ---- обувь
    "shoes": "shoes",
    "boots": "shoes",
    "sneakers": "shoes",
    "heels": "shoes",
    "loafers": "shoes",
    # ---- сумки/пояса/украшения/очки/шляпы/колготки
    "bag": "bags",
    "bags": "bags",
    "handbag": "bags",
    "clutch": "bags",
    "belt": "belts",
    "belts": "belts",
    "hat": "headwear",
    "cap": "headwear",
    "beanie": "headwear",
    "headwear": "headwear",
    "glasses": "eyewear",
    "sunglasses": "eyewear",
    "eyewear": "eyewear",
    "necklace": "jewelry",
    "earrings": "jewelry",
    "bracelet": "jewelry",
    "ring": "jewelry",
    "jewelry": "jewelry",
    "tights": "hosiery",
    "socks": "hosiery",
    "hosiery": "hosiery",
    "swimsuit": "swimwear",
    "bikini": "swimwear",
    "swimwear": "swimwear",
}


def _resolve_category_file(category: str | None) -> str | None:
    if not category:
        return None
    return _CATEGORY_FILE_ALIASES.get(category.lower())


def _load_category_yaml(file_stem: str) -> dict:
    path = _CATEGORY_RULES_DIR / f"{file_stem}.yaml"
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


# ----------------------------- helpers: атрибуты ---------------------------


def _resolve_attr(item: Any, name: str) -> Any:
    """Прочитать атрибут: сначала колонка, затем attributes_json."""
    value = getattr(item, name, None)
    if value is not None:
        return value
    attrs = getattr(item, "attributes_json", None)
    if isinstance(attrs, dict):
        v = attrs.get(name)
        if v is not None:
            return v
    return None


def _item_id(item: Any) -> str:
    iid = getattr(item, "id", None) or getattr(item, "item_id", None)
    return str(iid) if iid is not None else "item"


def _item_category(item: Any) -> str | None:
    cat = getattr(item, "category", None)
    if not cat:
        attrs = getattr(item, "attributes_json", None)
        if isinstance(attrs, dict):
            cat = attrs.get("category")
    return cat if isinstance(cat, str) else None


# Префикс ``pending_`` в YAML указывает на атрибут Фазы 0 — снимаем префикс.
def _actual_attr_name(key: str) -> str:
    if key.startswith("pending_"):
        return key[len("pending_") :]
    return key


# ----------------------------- обсчёт prefer -------------------------------


# Ключи в prefer, которые НЕ соответствуют обычным атрибутам вещи и
# требуют особой обработки. Перечислены явно — чтобы не было тихих
# ложноположительных сопоставлений.
_SPECIAL_PREFER_KEYS = {
    "waist_accent",        # dict со сложной структурой (dresses, skirts)
    "jeans_rules",         # dict для частного случая jeans
    "notes",
}


def _prefer_attr_value(item: Any, yaml_key: str) -> Any:
    """Прочитать соответствующий атрибут вещи для ключа из prefer."""
    name = _actual_attr_name(yaml_key)
    return _resolve_attr(item, name)


def _value_matches(item_value: Any, expected: Any) -> bool:
    """Сравнить значение атрибута вещи с ожиданием из YAML."""
    if item_value is None or expected is None:
        return False
    if isinstance(expected, list):
        return item_value in expected
    if isinstance(expected, str):
        return str(item_value) == expected
    if isinstance(expected, bool):
        # Например, ``no_distress: true`` — нет соответствующего атрибута
        # вещи, пропускаем.
        return False
    return str(item_value) == str(expected)


def _score_prefer(
    item: Any,
    prefer: dict,
) -> tuple[float, list[str], int, int]:
    """Вернуть ``(score_delta, notes, checked_keys, matched_keys)``.

    score_delta — [-∞..+∞], потом клампится вызывающим.
    checked_keys — сколько полей prefer смогли оценить по атрибутам вещи
    (нужно для quality). matched_keys — сколько из них попало в prefer.
    """
    delta = 0.0
    notes: list[str] = []
    checked = 0
    matched = 0

    for yaml_key, expected in prefer.items():
        if yaml_key in _SPECIAL_PREFER_KEYS:
            continue
        # ``sub_types`` в YAML — список допустимых подтипов вещи;
        # атрибут вещи обычно ``sub_type`` (в колонке ``attributes_json``).
        if yaml_key == "sub_types":
            item_sub = _resolve_attr(item, "sub_type")
            if item_sub is None:
                continue
            checked += 1
            if isinstance(expected, list) and item_sub in expected:
                matched += 1
                delta += 0.15
                notes.append(f"sub_type={item_sub} — подтип любит такие вещи")
            continue
        # Пропускаем dict-значения (особые) и ``bonus``-метки —
        # атрибутов под них у вещи сейчас нет.
        if isinstance(expected, dict):
            continue
        if expected == "bonus":
            continue

        item_value = _prefer_attr_value(item, yaml_key)
        if item_value is None:
            continue

        checked += 1
        if _value_matches(item_value, expected):
            matched += 1
            delta += 0.10
            notes.append(
                f"{yaml_key}={item_value} — попадает в предпочтения подтипа"
            )

    return delta, notes, checked, matched


# ----------------------------- stop справочник -----------------------------


def _collect_stop_notes(stop_list: list) -> list[str]:
    """Вернуть reason-ы всех stop-правил категории (справка для UI)."""
    out: list[str] = []
    if not isinstance(stop_list, list):
        return out
    for rule in stop_list:
        if isinstance(rule, dict):
            reason = rule.get("reason")
            if isinstance(reason, str):
                out.append(reason)
    return out


# ----------------------------- stop predicates -----------------------------
#
# Формат `match` в YAML:
#
#   stop:
#     - rule: raglan_sleeve
#       reason: "Реглан скашивает плечи"
#       match: { sleeve_type: raglan }
#
#     - rule: long_unstructured
#       reason: "Длинная и бесформенная — не FG"
#       match: { length: long, structure: unstructured }   # AND по полям
#
#     - rule: pumps_classic
#       reason: "Классические лодочки — мимо"
#       match:
#         sub_type: pumps
#         toe_shape: [round, square]                       # любое из списка
#
# Если у правила нет ``match`` (или он пустой) — правило используется
# только как справочный reason. Если ``match`` присутствует и ВСЕ его
# условия выполнены, начисляется штраф ``_STOP_PENALTY``.


_STOP_PENALTY = 0.15


def _stop_match_satisfied(item: Any, match: Any) -> bool:
    """True, если ВСЕ условия match выполнены для вещи."""
    if not isinstance(match, dict) or not match:
        return False
    for attr_yaml_key, expected in match.items():
        item_value = _resolve_attr(item, _actual_attr_name(attr_yaml_key))
        if item_value is None:
            return False
        if isinstance(expected, list):
            if item_value not in expected:
                return False
        else:
            if str(item_value) != str(expected):
                return False
    return True


def _evaluate_stop(
    item: Any,
    stop_list: list,
) -> tuple[float, list[str]]:
    """Вернуть ``(penalty_delta, matched_stop_explanations)``.

    Перебирает stop-правила, у которых есть ``match``. Для каждого
    сработавшего — штраф ``_STOP_PENALTY`` и человекочитаемое объяснение.
    """
    if not isinstance(stop_list, list):
        return 0.0, []
    delta = 0.0
    matched: list[str] = []
    for rule in stop_list:
        if not isinstance(rule, dict):
            continue
        match = rule.get("match")
        if not _stop_match_satisfied(item, match):
            continue
        delta -= _STOP_PENALTY
        rule_id = rule.get("rule") or "stop_rule"
        reason = rule.get("reason") or ""
        matched.append(f"{rule_id}: {reason}".strip(": ").strip())
    return delta, matched


# ----------------------------- сервис --------------------------------------


class CategoryRulesService:
    """Оценка вещей образа по правилам их категорий.

    Параметры
    ---------
    rules_dir:
        Каталог с ``category_rules/*.yaml``. Для тестов можно
        подменить на другой путь.
    """

    def __init__(self, rules_dir: Path | None = None) -> None:
        self._rules_dir = rules_dir or _CATEGORY_RULES_DIR
        # кэш загруженных YAML: стандартная оптимизация — файл читается
        # один раз на инстанс сервиса.
        self._yaml_cache: dict[str, dict] = {}

    def _load(self, file_stem: str) -> dict:
        if file_stem in self._yaml_cache:
            return self._yaml_cache[file_stem]
        if self._rules_dir is _CATEGORY_RULES_DIR:
            data = _load_category_yaml(file_stem)
        else:
            path = self._rules_dir / f"{file_stem}.yaml"
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except FileNotFoundError:
                data = {}
        self._yaml_cache[file_stem] = data
        return data

    # ------------------------------------------------------------------ API

    def score_item(self, item: Any, user_subtype: str) -> CategoryRuleScore:
        """Оценить одну вещь по правилам её категории."""
        category = _item_category(item)
        iid = _item_id(item)
        file_stem = _resolve_category_file(category)

        if file_stem is None:
            return CategoryRuleScore(
                item_id=iid,
                category=category,
                score=0.0,
                stop_notes=[],
                quality="low",
            )

        yaml_data = self._load(file_stem)
        rules_block = yaml_data.get("rules") or {}
        subtype_block = rules_block.get(user_subtype) or {}
        prefer = subtype_block.get("prefer") or {}
        stop = subtype_block.get("stop") or []

        if not prefer and not stop:
            return CategoryRuleScore(
                item_id=iid,
                category=category,
                score=0.0,
                stop_notes=[],
                quality="low",
            )

        prefer_delta, prefer_notes, checked, _matched = _score_prefer(item, prefer)
        stop_delta, stop_explanations = _evaluate_stop(item, stop)
        stop_notes = _collect_stop_notes(stop)

        # quality: ни одного атрибута не удалось оценить → low.
        # Частично оценено → medium. Всё оценено — high.
        # Сработавший stop-предикат сам по себе означает, что атрибуты
        # ВЕЩИ были прочитаны — значит quality поднимается до medium
        # минимум.
        if checked == 0 and not stop_explanations:
            quality: Literal["high", "medium", "low"] = "low"
        elif checked < max(1, len(prefer) // 2) and not stop_explanations:
            quality = "medium"
        else:
            quality = "high"

        score = max(-1.0, min(1.0, prefer_delta + stop_delta))

        return CategoryRuleScore(
            item_id=iid,
            category=category,
            score=round(score, 3),
            matched_prefer=prefer_notes,
            matched_stop=stop_explanations,
            stop_notes=stop_notes,
            quality=quality,
        )

    def evaluate(
        self,
        items: list[Any],
        user_subtype: str,
    ) -> CategoryRulesOutfitResult:
        """Оценить все вещи образа и агрегировать в один score."""
        if not items:
            return CategoryRulesOutfitResult(
                score=0.0,
                explanation="Образ пустой — нечего оценивать.",
                per_item=[],
                quality="low",
            )

        # Детерминированный порядок
        items_sorted = sorted(items, key=_item_id)
        per_item: list[CategoryRuleScore] = [
            self.score_item(it, user_subtype) for it in items_sorted
        ]

        # Среднее по score, с учётом quality (low не перевешивает).
        total_weight = 0.0
        weighted_sum = 0.0
        for r in per_item:
            if r.quality == "low":
                w = 0.2
            elif r.quality == "medium":
                w = 0.7
            else:
                w = 1.0
            weighted_sum += r.score * w
            total_weight += w
        avg = weighted_sum / total_weight if total_weight else 0.0

        # Агрегированный quality
        qualities = {r.quality for r in per_item}
        if qualities <= {"low"}:
            agg_quality: Literal["high", "medium", "low"] = "low"
        elif "high" in qualities and qualities <= {"high"}:
            agg_quality = "high"
        else:
            agg_quality = "medium"

        # Объяснение: первые 3-5 значимых reasons + сработавшие stop'ы.
        lines: list[str] = []
        for r in per_item:
            if r.matched_stop:
                # Штрафы важнее — выводим первыми
                lines.append(
                    f"[{r.category or 'item'}] STOP: " + "; ".join(r.matched_stop[:2])
                )
            elif r.matched_prefer:
                lines.append(
                    f"[{r.category or 'item'}] " + "; ".join(r.matched_prefer[:2])
                )
        if not lines:
            lines.append("Ни одна вещь не набрала атрибутов, попадающих в prefer подтипа.")

        return CategoryRulesOutfitResult(
            score=round(avg, 3),
            explanation=" · ".join(lines),
            per_item=per_item,
            quality=agg_quality,
        )


__all__ = [
    "CategoryRulesService",
    "CategoryRulesOutfitResult",
    "CategoryRuleScore",
]
