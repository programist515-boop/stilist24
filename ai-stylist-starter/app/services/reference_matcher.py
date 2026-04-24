"""Матчер референсных луков (Фаза 7 плана ``2026-04-21``).

Задача сервиса:

1. Для активного подтипа пользователя взять все референсные луки из
   ``config/rules/reference_looks/<subtype>.yaml``.
2. Для каждого слота каждого лука (верх, низ, обувь, верхняя одежда,
   аксессуары) попытаться найти подходящую вещь в гардеробе пользователя.
3. Вернуть структуру ``ReferenceLookMatch`` — с ``matched_items`` и
   ``missing_slots`` — откуда UI собирает «лук из твоего гардероба»,
   а Gap-analysis достаёт «что докупить».

Принципы:

* **Честные quality-downgrade'ы.** Если у вещи NULL по ключевым
  атрибутам (``structure``, ``cut_lines``, ``fabric_rigidity`` …) —
  она может матчиться, но ``match_quality`` падает и в
  ``match_reasons`` пишется «нет данных по атрибуту X, зачли по
  категории».
* **Детерминизм.** При равенстве качества предпочитаем вещь с большим
  ``wear_count`` (уже любимая), а как tie-breaker — `id`.
* **YAML — единственный источник правил.** В коде — только движок.
* **CategoryRulesService — через Protocol.** Реальная реализация идёт
  отдельной фазой (B2). Сейчас матчер принимает любой объект с методом
  ``validate_item_for_category(item, subtype, category) -> bool``;
  в тестах подставляется моковая реализация. Дефолтная реализация в
  модуле возвращает ``True`` — чтобы боевой роут работал до мержа B2.

Совместимость с YAML:

* ``requires.category`` может быть строкой или списком строк
  (фильтр по ``WardrobeItem.category``).
* ``requires.pending_<attr>``: префикс ``pending_`` — это маркер из
  Фазы 0, что атрибут в модели появился позже. Мы его уже не
  придерживаемся — читаем атрибут без префикса (например,
  ``pending_structure`` → ``structure``).
* ``requires.color`` / ``requires.color_hint`` / ``requires.fit`` /
  ``requires.length`` — сейчас это «мягкие» требования: их наличие
  поднимает ``match_quality``, но отсутствие не блокирует матч.
* ``global_stop_items`` — если у вещи совпал хотя бы один такой
  атрибут, она НЕ может матчиться ни на один слот этого подтипа.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable

import yaml

logger = logging.getLogger(__name__)


REFERENCE_LOOKS_DIR = Path(__file__).resolve().parent.parent.parent / (
    "config/rules/reference_looks"
)


# ---------------------------------------------------------------- константы

#: Префикс «pending_» помечает атрибуты, которые были pending в момент
#: написания YAML. Сейчас модель их содержит, так что мы просто
#: отбрасываем префикс при чтении.
_PENDING_PREFIX = "pending_"

#: Атрибуты, по которым вещь матчится «жёстко» (точное совпадение).
#: Все они есть в WardrobeItem (Фаза 0).
_HARD_ATTRS: tuple[str, ...] = (
    "fabric_rigidity",
    "fabric_finish",
    "occasion",
    "neckline_type",
    "sleeve_type",
    "sleeve_length",
    "pattern_scale",
    "pattern_character",
    "pattern_symmetry",
    "detail_scale",
    "structure",
    "cut_lines",
    "shoulder_emphasis",
    "style_tag",  # в YAML — single, в модели — массив style_tags
)

#: «Мягкие» атрибуты — мы их не читаем из столбцов модели (их там нет),
#: но если у вещи в attributes_json совпадает — это бонус к качеству.
_SOFT_ATTRS: tuple[str, ...] = (
    "color",
    "color_hint",
    "color_policy",
    "fit",
    "length",
    "width",
    "shoulder_accent",
    "buckle",
    "fabric_description",
)


# ---------------------------------------------------------------- датаклассы


@dataclass(frozen=True)
class MatchedItem:
    """Сматченная вещь гардероба под конкретный слот референсного лука."""

    slot: str
    item_id: str
    match_quality: float  # [0..1]
    match_reasons: list[str]


@dataclass(frozen=True)
class MissingSlot:
    """Слот, под который в гардеробе ничего не нашлось.

    ``requires`` — сырой YAML-блок (для UI / gap_analysis).
    ``shopping_hint`` — человекочитаемая подсказка «что докупить»,
    собранная из ключевых атрибутов требования.
    """

    slot: str
    requires: dict
    shopping_hint: str


@dataclass(frozen=True)
class ReferenceLookMatch:
    """Результат матча одного референсного лука с гардеробом."""

    look_id: str
    title: str
    occasion: str | None
    matched_items: list[MatchedItem]
    missing_slots: list[MissingSlot]
    completeness: float  # доля закрытых обязательных слотов

    # Полезное для UI — ссылка на превью и короткое описание.
    image_url: str | None = None
    description: str | None = None
    # Список всех sloтов (и закрытых, и missing) в оригинальном порядке.
    # Нужен фронту, чтобы рисовать «скелет» лука даже если часть слотов пуста.
    slot_order: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- protocol


@runtime_checkable
class CategoryRulesServiceProtocol(Protocol):
    """Интерфейс валидатора вещи по правилам категории для подтипа.

    Реальная реализация — ``services/category_rules_service.py`` (Фаза 2,
    делается параллельно агентом A2). Здесь мы знаем про него только
    сигнатуру: вернул ``True`` — вещь допустима под эту категорию/подтип,
    ``False`` — отсекаем (например, «гамину противопоказаны balloon-брюки»).
    """

    def validate_item_for_category(
        self,
        item: Any,
        subtype: str,
        category: str,
    ) -> bool:  # pragma: no cover — только контракт
        ...


class _AllowAllCategoryRules:
    """Дефолт: всегда True. Даёт матчеру работать до мёржа Фазы 2."""

    def validate_item_for_category(
        self,
        item: Any,
        subtype: str,
        category: str,
    ) -> bool:
        return True


# ---------------------------------------------------------------- loader


def _load_reference_looks_yaml(subtype: str) -> dict | None:
    """Вернуть dict YAML для подтипа или None, если файла нет."""
    path = REFERENCE_LOOKS_DIR / f"{subtype}.yaml"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return raw if isinstance(raw, dict) else None


# ---------------------------------------------------------------- helpers


def _strip_pending(key: str) -> str:
    """Снять префикс ``pending_`` — сейчас эти атрибуты уже в модели."""
    if key.startswith(_PENDING_PREFIX):
        return key[len(_PENDING_PREFIX):]
    return key


def _as_list(value: Any) -> list[Any]:
    """Нормализовать «строка или список строк» в список."""
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if v is not None]
    return [value]


def _item_attr(item: Any, name: str) -> Any:
    """Прочитать атрибут у item — сначала из колонок ORM, потом из attributes_json.

    Работает и с ``WardrobeItem`` (SQLAlchemy), и с ``dict`` (в тестах).
    """
    # style_tag (singular) в YAML → style_tags (plural, ARRAY) в модели.
    if name == "style_tag":
        tags = _item_attr(item, "style_tags")
        return tags or None

    if isinstance(item, dict):
        if name in item and item[name] is not None:
            return item[name]
        attrs = item.get("attributes") or item.get("attributes_json") or {}
        if isinstance(attrs, dict) and attrs.get(name) is not None:
            return attrs.get(name)
        return None

    # ORM-объект
    val = getattr(item, name, None)
    if val is not None:
        return val
    attrs = getattr(item, "attributes_json", None) or {}
    if isinstance(attrs, dict):
        return attrs.get(name)
    return None


def _item_id(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("id"))
    return str(getattr(item, "id", ""))


def _item_wear_count(item: Any) -> int:
    if isinstance(item, dict):
        return int(item.get("wear_count") or 0)
    return int(getattr(item, "wear_count", 0) or 0)


def _item_category(item: Any) -> str | None:
    if isinstance(item, dict):
        return item.get("category")
    return getattr(item, "category", None)


# ---------------------------------------------------------------- matching core


def _matches_value(value: Any, expected: Any) -> bool:
    """Проверить, что value ∈ expected (expected — скаляр или список)."""
    if value is None:
        return False
    expected_list = _as_list(expected)
    if not expected_list:
        return False
    # Спец-случай: style_tag в YAML — строка, в модели — массив.
    if isinstance(value, list):
        return any(v in expected_list for v in value)
    return value in expected_list


def _item_blocked_by_global_stop(
    item: Any,
    global_stop_items: list[dict] | None,
) -> str | None:
    """Если вещь подпадает под global_stop_items — вернуть причину, иначе None."""
    if not global_stop_items:
        return None
    for rule in global_stop_items:
        if not isinstance(rule, dict):
            continue
        for raw_key, expected in rule.items():
            key = _strip_pending(raw_key)
            if key == "category":
                cat = _item_category(item)
                if cat and cat in _as_list(expected):
                    return f"категория {cat} в стоп-листе подтипа"
                continue
            if key in _HARD_ATTRS:
                actual = _item_attr(item, key)
                if _matches_value(actual, expected):
                    return f"{key}={actual!r} в стоп-листе подтипа"
    return None


def _score_item_against_requires(
    item: Any,
    requires: dict,
) -> tuple[float, list[str], bool]:
    """Посчитать качество матча вещи по requires-блоку слота.

    Возвращает ``(quality, reasons, category_ok)``:
      * ``quality ∈ [0..1]`` — доля выполненных требований; жёсткое
        несовпадение по hard-атрибуту → quality снижается.
      * ``reasons`` — человекочитаемые причины (для match_reasons).
      * ``category_ok`` — проходит ли по категории; если нет, матч
        вообще не засчитывается вызывающим кодом.
    """
    reasons: list[str] = []
    total_checks = 0
    passed_checks = 0
    null_attrs: list[str] = []

    # --- категория ---
    category_ok = True
    expected_cat = requires.get("category")
    if expected_cat is not None:
        total_checks += 1
        actual_cat = _item_category(item)
        if _matches_value(actual_cat, expected_cat):
            passed_checks += 1
            reasons.append(f"категория {actual_cat} подходит")
        else:
            category_ok = False
            reasons.append(
                f"категория {actual_cat!r} не совпадает с "
                f"{_as_list(expected_cat)!r}"
            )

    # --- hard-атрибуты ---
    for raw_key, expected in requires.items():
        if raw_key == "category":
            continue
        key = _strip_pending(raw_key)
        if key not in _HARD_ATTRS:
            continue
        total_checks += 1
        actual = _item_attr(item, key)
        if actual is None:
            null_attrs.append(key)
            # Честный quality-downgrade: нет данных — зачли только по
            # категории, но качество штрафуется.
            reasons.append(f"нет данных по {key}, зачли по категории")
            continue
        if _matches_value(actual, expected):
            passed_checks += 1
            reasons.append(f"{key}={actual!r} совпадает")
        else:
            reasons.append(
                f"{key}={actual!r} ожидалось {_as_list(expected)!r}"
            )

    # --- soft-атрибуты (бонус, не штраф) ---
    for raw_key, expected in requires.items():
        key = _strip_pending(raw_key)
        if key not in _SOFT_ATTRS:
            continue
        actual = _item_attr(item, key)
        if actual is None:
            continue
        total_checks += 1
        if _matches_value(actual, expected):
            passed_checks += 1
            reasons.append(f"{key}={actual!r} (soft) совпадает")
        # Несовпадение soft-атрибута не карает явно — просто не даёт бонус.

    if total_checks == 0:
        # Только экзотический YAML без requires — считаем максимум.
        return 1.0, ["нет требований — полный матч"], True

    quality = passed_checks / total_checks

    # Штраф за null-атрибуты: честный downgrade (см. design_philosophy).
    if null_attrs:
        # Каждый отсутствующий hard-атрибут режет качество ещё на 10%.
        quality = max(0.0, quality - 0.1 * len(null_attrs))

    # Если категория не совпала — качество обнуляется (вызывающий код
    # увидит category_ok=False и вообще не засчитает матч).
    return round(quality, 3), reasons, category_ok


# ---------------------------------------------------------------- hints


_ATTR_LABELS_RU: dict[str, str] = {
    "fabric_rigidity": "жёсткость ткани",
    "fabric_finish": "фактура",
    "structure": "структура",
    "cut_lines": "линии кроя",
    "pattern_character": "принт",
    "pattern_scale": "масштаб принта",
    "neckline_type": "вырез",
    "sleeve_type": "тип рукава",
    "sleeve_length": "длина рукава",
    "detail_scale": "масштаб деталей",
    "shoulder_emphasis": "акцент на плечи",
    "style_tag": "стилистика",
    "color": "цвет",
    "color_hint": "цвет",
    "fit": "посадка",
    "length": "длина",
}


def _build_shopping_hint(slot: str, requires: dict) -> str:
    """Собрать короткую подсказку «что докупить» по блоку requires."""
    parts: list[str] = []

    cat = requires.get("category")
    if cat is not None:
        cat_list = _as_list(cat)
        if len(cat_list) == 1:
            parts.append(str(cat_list[0]))
        elif cat_list:
            parts.append("/".join(str(c) for c in cat_list[:3]))

    for raw_key, expected in requires.items():
        if raw_key == "category":
            continue
        key = _strip_pending(raw_key)
        label = _ATTR_LABELS_RU.get(key)
        if label is None:
            continue
        exp_list = _as_list(expected)
        if not exp_list:
            continue
        if len(exp_list) == 1:
            parts.append(f"{label}: {exp_list[0]}")
        else:
            parts.append(f"{label}: {'/'.join(str(x) for x in exp_list[:3])}")

    if not parts:
        return f"вещь в слот {slot}"
    return ", ".join(parts)


# ---------------------------------------------------------------- matcher


class ReferenceMatcher:
    """Сопоставляет референсные луки подтипа с гардеробом пользователя."""

    def __init__(
        self,
        rules_loader: Any = None,
        category_rules: CategoryRulesServiceProtocol | None = None,
    ) -> None:
        # rules_loader принимаем для совместимости с общим паттерном
        # проекта, но напрямую читаем YAML из REFERENCE_LOOKS_DIR.
        self._rules_loader = rules_loader
        self._category_rules: CategoryRulesServiceProtocol = (
            category_rules or _AllowAllCategoryRules()
        )

    # -------- публичный API --------------------------------------------------

    def match_wardrobe(
        self,
        wardrobe: list[Any],
        user_subtype: str,
    ) -> list[ReferenceLookMatch]:
        """Для каждого лука подтипа вернуть матч с гардеробом.

        * ``wardrobe`` — список вещей (WardrobeItem или dict).
        * ``user_subtype`` — ключ из ``identity_subtype_profiles.yaml``
          (например ``"flamboyant_gamine"``).

        Если подтип неизвестен или YAML не содержит луков — возвращаем
        пустой список (не падаем).
        """
        if not user_subtype:
            return []

        data = _load_reference_looks_yaml(user_subtype)
        if not data:
            logger.info(
                "reference_matcher: no YAML for subtype=%s", user_subtype
            )
            return []

        looks = data.get("reference_looks") or []
        if not isinstance(looks, list):
            return []

        global_stop_items = data.get("global_stop_items") or []

        # Предфильтровать гардероб: вещи, попавшие в global_stop_items,
        # выкидываем один раз, а не на каждой проверке.
        allowed_items: list[Any] = []
        for item in wardrobe:
            blocked = _item_blocked_by_global_stop(item, global_stop_items)
            if blocked is None:
                allowed_items.append(item)

        result: list[ReferenceLookMatch] = []
        for look in looks:
            if not isinstance(look, dict):
                continue
            result.append(
                self._match_one_look(look, allowed_items, user_subtype)
            )
        return result

    # -------- внутренняя кухня ----------------------------------------------

    def _match_one_look(
        self,
        look: dict,
        wardrobe: list[Any],
        user_subtype: str,
    ) -> ReferenceLookMatch:
        look_id = str(look.get("id") or "")
        title = str(look.get("name") or look_id)
        occasion = look.get("style") or look.get("occasion")
        image_url = look.get("image_url") or look.get("image")
        description = look.get("description")

        slots_def: list[dict] = []
        for entry in look.get("items") or []:
            if isinstance(entry, dict):
                slots_def.append(entry)
        for entry in look.get("accessories") or []:
            if isinstance(entry, dict):
                # аксессуар: slot = "accessory:<type>"
                acc_type = entry.get("type") or "accessory"
                slots_def.append({
                    "slot": f"accessory:{acc_type}",
                    "requires": entry.get("requires") or {},
                    "optional": bool(entry.get("optional", True)),
                })

        slot_order: list[str] = []
        matched: list[MatchedItem] = []
        missing: list[MissingSlot] = []

        used_item_ids: set[str] = set()
        required_count = 0
        closed_required_count = 0

        for slot_def in slots_def:
            slot_name = str(slot_def.get("slot") or "item")
            slot_order.append(slot_name)
            requires = slot_def.get("requires") or {}
            optional = bool(slot_def.get("optional", False))
            if not optional:
                required_count += 1

            match = self._best_match_for_slot(
                requires=requires,
                wardrobe=wardrobe,
                user_subtype=user_subtype,
                used_item_ids=used_item_ids,
                slot=slot_name,
            )

            if match is None:
                missing.append(
                    MissingSlot(
                        slot=slot_name,
                        requires=dict(requires),
                        shopping_hint=_build_shopping_hint(slot_name, requires),
                    )
                )
            else:
                matched.append(match)
                used_item_ids.add(match.item_id)
                if not optional:
                    closed_required_count += 1

        if required_count == 0:
            # Редкий случай — все слоты optional. Считаем completeness по
            # общему числу слотов.
            total = max(len(slots_def), 1)
            completeness = len(matched) / total
        else:
            completeness = closed_required_count / required_count

        return ReferenceLookMatch(
            look_id=look_id,
            title=title,
            occasion=occasion,
            matched_items=matched,
            missing_slots=missing,
            completeness=round(completeness, 3),
            image_url=image_url,
            description=description,
            slot_order=slot_order,
        )

    def _best_match_for_slot(
        self,
        requires: dict,
        wardrobe: Iterable[Any],
        user_subtype: str,
        used_item_ids: set[str],
        slot: str,
    ) -> MatchedItem | None:
        """Выбрать лучшую вещь под слот.

        Возвращает ``None``, если ни одна вещь не проходит по категории.
        """
        expected_cat_list = _as_list(requires.get("category"))

        best: tuple[float, int, str, MatchedItem] | None = None
        # Ключ сортировки: (-quality, -wear_count, id) — детерминистично.

        for item in wardrobe:
            iid = _item_id(item)
            if iid in used_item_ids:
                continue

            # Проверка CategoryRulesService. Для каждой из ожидаемых
            # категорий — хотя бы одна должна пройти валидацию.
            if expected_cat_list:
                ok_any = False
                for cat in expected_cat_list:
                    if self._category_rules.validate_item_for_category(
                        item, user_subtype, str(cat)
                    ):
                        ok_any = True
                        break
                if not ok_any:
                    continue

            quality, reasons, category_ok = _score_item_against_requires(
                item, requires
            )
            if not category_ok:
                continue
            if quality <= 0:
                continue

            wear = _item_wear_count(item)
            sort_key = (-quality, -wear, iid)
            candidate = MatchedItem(
                slot=slot,
                item_id=iid,
                match_quality=quality,
                match_reasons=reasons,
            )
            if best is None or sort_key < (
                -best[0], -best[1], best[2]
            ):
                best = (quality, wear, iid, candidate)

        return best[3] if best is not None else None


__all__ = [
    "CategoryRulesServiceProtocol",
    "MatchedItem",
    "MissingSlot",
    "ReferenceLookMatch",
    "ReferenceMatcher",
]
