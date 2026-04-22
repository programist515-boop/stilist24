"""Единые константы допустимых значений для 14 новых атрибутов одежды.

Эти константы — единственный источник истины для:
  * валидаторов SQLAlchemy-модели ``WardrobeItem`` (см. Фазу 0 плана
    ``plans/2026-04-21-каталог-фич-из-отчёта-типажа.md``);
  * CV-эвристик в ``app.services.garment_recognizer`` (расширение v2);
  * YAML-правил стилиста (``config/rules/garment_recognition_rules.yaml``
    содержит зеркальный список — должен совпадать со словарями ниже).

Принципы:
  * **Все атрибуты nullable.** Если CV не смог определить значение —
    честный ``None`` + ``quality=low`` в отчёте экстрактора
    (см. design_philosophy: «честные quality downgrades»).
  * **String + whitelist.** Используем простые строки вместо
    ``sqlalchemy.Enum`` — это упрощает Alembic-миграции
    (новое значение добавляется правкой whitelist, а не миграцией
    типа enum в Postgres) и совместимо с JSONB-наследием.
  * **Детерминизм.** Никаких случайных значений — одни и те же сигналы
    должны давать один и тот же ответ.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------- whitelist-ы

FABRIC_RIGIDITY_VALUES: Final[frozenset[str]] = frozenset({
    "soft",
    "medium",
    "rigid",
})

FABRIC_FINISH_VALUES: Final[frozenset[str]] = frozenset({
    "matte",
    "glossy",
    "metallic",
    "sequin",
    "brocade",
})

OCCASION_VALUES: Final[frozenset[str]] = frozenset({
    "day",
    "work",
    "smart_casual",
    "evening",
    "sport",
})

NECKLINE_TYPE_VALUES: Final[frozenset[str]] = frozenset({
    "v",
    "straight",
    "boat",
    "round",
    "sweetheart",
    "halter",
    "asymmetric",
    "turtleneck",
    "off_shoulder",
})

SLEEVE_TYPE_VALUES: Final[frozenset[str]] = frozenset({
    "set_in",
    "raglan",
    "batwing",
    "dropped_shoulder",
    "cap",
    "puff_sharp",
    "sleeveless",
})

SLEEVE_LENGTH_VALUES: Final[frozenset[str]] = frozenset({
    "short",
    "three_quarter",
    "long_wrist",
    "long",
})

PATTERN_SCALE_VALUES: Final[frozenset[str]] = frozenset({
    "small",
    "medium",
    "large",
})

PATTERN_CHARACTER_VALUES: Final[frozenset[str]] = frozenset({
    "geometric",
    "abstract",
    "floral_soft",
    "floral_bold",
    "watercolor",
    "animal",
    "stripe",
    "dots",
    "checks",
    "asymmetric",
})

PATTERN_SYMMETRY_VALUES: Final[frozenset[str]] = frozenset({
    "symmetric",
    "asymmetric",
})

DETAIL_SCALE_VALUES: Final[frozenset[str]] = frozenset({
    "small",
    "medium",
    "large",
})

STRUCTURE_VALUES: Final[frozenset[str]] = frozenset({
    "structured",
    "semi_structured",
    "unstructured",
})

CUT_LINES_VALUES: Final[frozenset[str]] = frozenset({
    "angular",
    "straight",
    "soft_flowing",
})

SHOULDER_EMPHASIS_VALUES: Final[frozenset[str]] = frozenset({
    "required",
    "neutral",
    "avoided",
})

STYLE_TAG_VALUES: Final[frozenset[str]] = frozenset({
    "military",
    "preppy",
    "dandy",
    "casual",
    "smart_casual",
    "dramatic",
    "twenties",
    "romantic",
})


# ---------------------------------------------------------------- мета-список

#: Список всех 14 новых атрибутов. Используется CV-экстрактором
#: для честной оценки quality (сколько атрибутов удалось заполнить).
NEW_ATTRIBUTE_NAMES: Final[tuple[str, ...]] = (
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
    "style_tags",
)

#: Атрибут → множество допустимых значений.
#: Для ``style_tags`` — допустимые значения отдельных элементов списка.
ATTRIBUTE_WHITELISTS: Final[dict[str, frozenset[str]]] = {
    "fabric_rigidity": FABRIC_RIGIDITY_VALUES,
    "fabric_finish": FABRIC_FINISH_VALUES,
    "occasion": OCCASION_VALUES,
    "neckline_type": NECKLINE_TYPE_VALUES,
    "sleeve_type": SLEEVE_TYPE_VALUES,
    "sleeve_length": SLEEVE_LENGTH_VALUES,
    "pattern_scale": PATTERN_SCALE_VALUES,
    "pattern_character": PATTERN_CHARACTER_VALUES,
    "pattern_symmetry": PATTERN_SYMMETRY_VALUES,
    "detail_scale": DETAIL_SCALE_VALUES,
    "structure": STRUCTURE_VALUES,
    "cut_lines": CUT_LINES_VALUES,
    "shoulder_emphasis": SHOULDER_EMPHASIS_VALUES,
    "style_tags": STYLE_TAG_VALUES,
}


# ---------------------------------------------------------------- валидаторы

def validate_scalar(attribute: str, value: str | None) -> str | None:
    """Вернёт value, если оно допустимо, иначе None.

    Для скалярных (не list) атрибутов. При недопустимом значении
    возвращает None — это честный quality downgrade.
    """
    if value is None:
        return None
    whitelist = ATTRIBUTE_WHITELISTS.get(attribute)
    if whitelist is None:
        return None
    return value if value in whitelist else None


def validate_style_tags(values: list[str] | None) -> list[str] | None:
    """Отфильтровать список style_tags, оставив только допустимые.

    Пустой список после фильтрации возвращается как None
    (честный «нет данных»), чтобы БД не хранила бессмысленные пустышки.
    Порядок сохраняется, дубликаты удаляются детерминистично.
    """
    if values is None:
        return None
    seen: set[str] = set()
    filtered: list[str] = []
    for v in values:
        if v in STYLE_TAG_VALUES and v not in seen:
            seen.add(v)
            filtered.append(v)
    return filtered or None


__all__ = [
    "ATTRIBUTE_WHITELISTS",
    "CUT_LINES_VALUES",
    "DETAIL_SCALE_VALUES",
    "FABRIC_FINISH_VALUES",
    "FABRIC_RIGIDITY_VALUES",
    "NECKLINE_TYPE_VALUES",
    "NEW_ATTRIBUTE_NAMES",
    "OCCASION_VALUES",
    "PATTERN_CHARACTER_VALUES",
    "PATTERN_SCALE_VALUES",
    "PATTERN_SYMMETRY_VALUES",
    "SHOULDER_EMPHASIS_VALUES",
    "SLEEVE_LENGTH_VALUES",
    "SLEEVE_TYPE_VALUES",
    "STRUCTURE_VALUES",
    "STYLE_TAG_VALUES",
    "validate_scalar",
    "validate_style_tags",
]
