"""Сервис оценки цветовых сочетаний в образе.

Фаза 4 плана ``plans/2026-04-21-каталог-фич-из-отчёта-типажа.md``.

Принцип работы
--------------
На вход подаётся список ``WardrobeItem`` (вещи образа) + подтип
пользователя и его цветотип-сезон. Сервис:

1. Вытаскивает доминирующий цвет каждой вещи (имя кластера из
   ``attributes_json.primary_color`` или HEX из того же JSON).
2. Переводит цвета в HSV, чтобы работать на «цветовом круге».
3. Сопоставляет цвета с шестью схемами из
   ``config/rules/color_schemes.yaml`` (triadic, analogous,
   complementary, split_complementary, tetradic, monochromatic).
4. Проверяет ``forbidden_palettes`` подтипа — пастели, пыльные,
   тёплые нейтральные и т.п. (штраф).
5. Проверяет ``composition_rules`` подтипа — для FG применимо
   ``break_vertical_by_color`` (контрастный верх/низ даёт бонус).
6. Собирает итоговый score в диапазоне -1..+1 и человекочитаемый
   ``explanation`` на русском.

Сервис НЕ интегрируется в ``outfit_engine`` — это отдельный чистый
модуль с детерминированным API. Интеграция — follow-up задача.

Дизайн-принципы
---------------
* **Честный quality**: если >=50% вещей без цвета — ``quality='low'``.
* **Детерминизм**: сортировка by-id, порядок полей стабилен.
* **Никакой магии**: каждое решение возвращает explanation.
* **Без ML/тяжёлых зависимостей**: только stdlib ``colorsys``. YAML —
  через общий ``rules_loader``.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from app.models.wardrobe_item import WardrobeItem


# ----------------------------- данные результата ---------------------------


@dataclass
class ColorSchemeMatch:
    """Попадание образа в одну из шести цветовых схем."""

    scheme: str
    confidence: float  # 0..1 — насколько чисто цвета ложатся на схему
    items_used: list[str]


@dataclass
class ColorForbidden:
    """Попадание цвета(ов) в ``forbidden_palettes`` подтипа."""

    reason: str
    items: list[str]


@dataclass
class ColorCombinationResult:
    """Итоговая оценка сочетания цветов в образе."""

    score: float                              # -1..+1
    explanation: str                          # на русском
    matched_schemes: list[ColorSchemeMatch] = field(default_factory=list)
    forbidden_hits: list[ColorForbidden] = field(default_factory=list)
    composition_hits: list[str] = field(default_factory=list)
    quality: Literal["high", "medium", "low"] = "high"


# ----------------------------- палитра и хелперы ---------------------------


# Именованные цвета из garment_recognition_rules.yaml.color_clusters.
# Если YAML недоступен — используем этот fallback (mean hex каждого
# кластера, чтобы сервис работал автономно в тестах).
_FALLBACK_NAMED_RGB: dict[str, tuple[int, int, int]] = {
    "white":  (250, 250, 250),
    "black":  (20, 20, 20),
    "navy":   (10, 30, 100),
    "grey":   (140, 140, 140),
    "beige":  (225, 210, 185),
    "red":    (210, 40, 50),
    "blue":   (70, 130, 220),
    "green":  (50, 130, 70),
    "brown":  (140, 90, 50),
    "camel":  (195, 165, 125),
    "pink":   (250, 170, 195),
    "orange": (255, 130, 70),
    "purple": (130, 60, 150),
    "yellow": (245, 210, 70),
}


_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "config/rules"


def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    """``"#FF8800"`` → ``(255, 136, 0)``. ``None`` на любой проблеме."""
    if not isinstance(value, str):
        return None
    s = value.strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return None


def _rgb_to_hsv(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """RGB 0-255 → HSV (hue в градусах 0..360, sat/val 0..1)."""
    r, g, b = [c / 255.0 for c in rgb]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return h * 360.0, s, v


def _hue_diff(a: float, b: float) -> float:
    """Минимальная разница углов на цветовом круге, в градусах [0, 180]."""
    d = abs(a - b) % 360.0
    return d if d <= 180.0 else 360.0 - d


# ----------------------------- загрузка YAML -------------------------------


def _load_yaml_safe(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _load_color_schemes_rules() -> dict:
    """Загружает ``color_schemes.yaml`` (схемы + composition + forbidden)."""
    return _load_yaml_safe(_RULES_PATH / "color_schemes.yaml")


def _load_named_rgb() -> dict[str, tuple[int, int, int]]:
    """Загружает color_clusters из garment_recognition_rules и строит
    таблицу ``name → mean RGB``. Fallback — встроенный словарь выше.
    """
    data = _load_yaml_safe(_RULES_PATH / "garment_recognition_rules.yaml")
    clusters = (data.get("garment_recognition") or {}).get("color_clusters") or {}

    table: dict[str, tuple[int, int, int]] = {}
    for name, hex_list in clusters.items():
        rgb_values = [rgb for rgb in (_hex_to_rgb(h) for h in hex_list) if rgb]
        if not rgb_values:
            continue
        n = len(rgb_values)
        mean = (
            sum(r for r, _, _ in rgb_values) // n,
            sum(g for _, g, _ in rgb_values) // n,
            sum(b for _, _, b in rgb_values) // n,
        )
        table[name] = mean

    # Дополняем fallback'ом для названий, которых нет в YAML.
    for name, rgb in _FALLBACK_NAMED_RGB.items():
        table.setdefault(name, rgb)
    return table


# ----------------------------- извлечение цвета вещи -----------------------


@dataclass
class _ItemColor:
    """Вспомогательная структура: цвет одной вещи в образе."""

    item_id: str
    category: str | None
    color_name: str | None         # нормализованное имя (если есть)
    hue: float | None              # 0..360
    saturation: float | None       # 0..1
    value: float | None            # 0..1
    fabric_finish: str | None
    pattern_scale: str | None

    @property
    def is_colored(self) -> bool:
        return self.hue is not None


def _extract_color_from_item(
    item: WardrobeItem, named_rgb: dict[str, tuple[int, int, int]]
) -> _ItemColor:
    """Вытащить цвет из вещи: сперва hex, потом имя кластера."""
    attrs = getattr(item, "attributes_json", None) or {}

    # ---- 1. Пытаемся вытащить HEX напрямую.
    raw_hex = None
    for key in ("primary_color_hex", "color_hex", "hex"):
        candidate = attrs.get(key)
        if isinstance(candidate, str):
            raw_hex = candidate
            break

    # ---- 2. Имя цвета — либо строка, либо dict.
    raw_color = attrs.get("primary_color")
    color_name: str | None
    if isinstance(raw_color, dict):
        # форма {"value": "navy", "hex": "#001F5B"}
        color_name = raw_color.get("value") if isinstance(raw_color.get("value"), str) else None
        if raw_hex is None and isinstance(raw_color.get("hex"), str):
            raw_hex = raw_color.get("hex")
    elif isinstance(raw_color, str):
        color_name = raw_color
    else:
        color_name = None

    rgb: tuple[int, int, int] | None = None
    if raw_hex:
        rgb = _hex_to_rgb(raw_hex)
    if rgb is None and color_name:
        rgb = named_rgb.get(color_name.lower())

    hue: float | None
    sat: float | None
    val: float | None
    if rgb is None:
        hue = sat = val = None
    else:
        hue, sat, val = _rgb_to_hsv(rgb)

    return _ItemColor(
        item_id=str(getattr(item, "id", "")) or (color_name or "item"),
        category=getattr(item, "category", None),
        color_name=color_name,
        hue=hue,
        saturation=sat,
        value=val,
        fabric_finish=getattr(item, "fabric_finish", None),
        pattern_scale=getattr(item, "pattern_scale", None),
    )


# ----------------------------- детекторы схем ------------------------------


# Допуски, внутри которых считаем, что цвета «на своих местах» на круге.
_ANALOGOUS_SPACING_DEG = 30.0
_TRIAD_SPACING_DEG = 120.0
_COMPLEMENTARY_SPACING_DEG = 180.0
_SPLIT_NEIGHBOR_SPACING_DEG = 30.0
_TETRADIC_OFFSET_DEG = 60.0
_TOLERANCE_DEG = 20.0  # допуск для «идеальной» схемы
_MONO_HUE_TIGHT_DEG = 15.0
_ACHROMATIC_SAT_THRESHOLD = 0.15  # ниже — серо/чёрно/белые


def _is_achromatic(color: _ItemColor) -> bool:
    """Серый/белый/чёрный — цвет без выраженного тона."""
    return color.saturation is not None and color.saturation < _ACHROMATIC_SAT_THRESHOLD


def _scheme_confidence(actual_deg: float, target_deg: float) -> float:
    """Насколько расстояние *actual* близко к *target* (0..1)."""
    delta = abs(actual_deg - target_deg)
    if delta >= _TOLERANCE_DEG:
        return max(0.0, 1.0 - delta / 60.0)
    return 1.0 - (delta / _TOLERANCE_DEG) * 0.3  # до 0.7 даже на границе толеранса


def _detect_monochromatic(colors: list[_ItemColor]) -> ColorSchemeMatch | None:
    """Один оттенок в разных насыщенностях/значениях."""
    chromatic = [c for c in colors if not _is_achromatic(c)]
    if len(chromatic) < 2:
        return None
    hues = [c.hue for c in chromatic]
    max_diff = max(_hue_diff(a, b) for a in hues for b in hues)
    if max_diff > _MONO_HUE_TIGHT_DEG:
        return None
    # конфиденс растёт с разбросом по value (что и делает моно-палитру живой).
    values = [c.value for c in chromatic]
    v_spread = max(values) - min(values)
    confidence = min(1.0, 0.7 + v_spread)
    return ColorSchemeMatch(
        scheme="monochromatic",
        confidence=round(confidence, 3),
        items_used=[c.item_id for c in chromatic],
    )


def _detect_analogous(colors: list[_ItemColor]) -> ColorSchemeMatch | None:
    """2–3 соседних цвета (<=30° между крайними)."""
    chromatic = [c for c in colors if not _is_achromatic(c)]
    if len(chromatic) < 2:
        return None
    hues = [c.hue for c in chromatic]
    max_diff = max(_hue_diff(a, b) for a in hues for b in hues)
    # analogous — шире моно, но уже триады
    if max_diff <= _MONO_HUE_TIGHT_DEG or max_diff > _ANALOGOUS_SPACING_DEG * 2:
        return None
    confidence = _scheme_confidence(max_diff, _ANALOGOUS_SPACING_DEG)
    return ColorSchemeMatch(
        scheme="analogous",
        confidence=round(confidence, 3),
        items_used=[c.item_id for c in chromatic],
    )


def _detect_complementary(colors: list[_ItemColor]) -> ColorSchemeMatch | None:
    """Два противоположных цвета (≈180°)."""
    chromatic = [c for c in colors if not _is_achromatic(c)]
    if len(chromatic) < 2:
        return None
    best: tuple[float, list[str]] | None = None
    for i, a in enumerate(chromatic):
        for b in chromatic[i + 1 :]:
            d = _hue_diff(a.hue, b.hue)
            conf = _scheme_confidence(d, _COMPLEMENTARY_SPACING_DEG)
            if conf < 0.5:
                continue
            if best is None or conf > best[0]:
                best = (conf, [a.item_id, b.item_id])
    if best is None:
        return None
    return ColorSchemeMatch(
        scheme="complementary", confidence=round(best[0], 3), items_used=best[1]
    )


def _detect_triad(colors: list[_ItemColor]) -> ColorSchemeMatch | None:
    """Три цвета, разнесённые примерно на 120°."""
    chromatic = [c for c in colors if not _is_achromatic(c)]
    if len(chromatic) < 3:
        return None
    best: tuple[float, list[str]] | None = None
    n = len(chromatic)
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                a, b, c = chromatic[i], chromatic[j], chromatic[k]
                d_ab = _hue_diff(a.hue, b.hue)
                d_bc = _hue_diff(b.hue, c.hue)
                d_ac = _hue_diff(a.hue, c.hue)
                confs = [
                    _scheme_confidence(d_ab, _TRIAD_SPACING_DEG),
                    _scheme_confidence(d_bc, _TRIAD_SPACING_DEG),
                    _scheme_confidence(d_ac, _TRIAD_SPACING_DEG),
                ]
                # все три расстояния должны быть близки к 120°
                conf = sum(confs) / 3.0
                if min(confs) < 0.4:
                    continue
                if best is None or conf > best[0]:
                    best = (conf, [a.item_id, b.item_id, c.item_id])
    if best is None:
        return None
    return ColorSchemeMatch(
        scheme="triadic", confidence=round(best[0], 3), items_used=best[1]
    )


def _detect_split_complementary(colors: list[_ItemColor]) -> ColorSchemeMatch | None:
    """Основной + два соседа его комплиментарного (≈150° и ≈210°)."""
    chromatic = [c for c in colors if not _is_achromatic(c)]
    if len(chromatic) < 3:
        return None
    targets = (
        _COMPLEMENTARY_SPACING_DEG - _SPLIT_NEIGHBOR_SPACING_DEG,
        _COMPLEMENTARY_SPACING_DEG + _SPLIT_NEIGHBOR_SPACING_DEG,
    )
    best: tuple[float, list[str]] | None = None
    for base in chromatic:
        # ищем пару, которая на 150°/210° от base
        matches = []
        for other in chromatic:
            if other.item_id == base.item_id:
                continue
            d = _hue_diff(base.hue, other.hue)
            # расстояние симметрично по кругу → сравниваем с 150°
            conf = _scheme_confidence(d, 150.0)
            if conf >= 0.4:
                matches.append((conf, other))
        if len(matches) < 2:
            continue
        matches.sort(key=lambda m: -m[0])
        c1, c2 = matches[0], matches[1]
        conf = (c1[0] + c2[0]) / 2.0
        if best is None or conf > best[0]:
            best = (conf, [base.item_id, c1[1].item_id, c2[1].item_id])
    if best is None:
        return None
    return ColorSchemeMatch(
        scheme="split_complementary",
        confidence=round(best[0], 3),
        items_used=best[1],
    )


def _detect_tetradic(colors: list[_ItemColor]) -> ColorSchemeMatch | None:
    """Два комплиментарных сочетания: четыре цвета в прямоугольнике."""
    chromatic = [c for c in colors if not _is_achromatic(c)]
    if len(chromatic) < 4:
        return None
    n = len(chromatic)
    best: tuple[float, list[str]] | None = None
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                for m in range(k + 1, n):
                    group = [chromatic[i], chromatic[j], chromatic[k], chromatic[m]]
                    # Отсортируем по hue для детерминизма
                    group.sort(key=lambda c: c.hue)
                    # Две пары комплиментарных: 0-2 и 1-3
                    d1 = _hue_diff(group[0].hue, group[2].hue)
                    d2 = _hue_diff(group[1].hue, group[3].hue)
                    c1 = _scheme_confidence(d1, _COMPLEMENTARY_SPACING_DEG)
                    c2 = _scheme_confidence(d2, _COMPLEMENTARY_SPACING_DEG)
                    if c1 < 0.5 or c2 < 0.5:
                        continue
                    conf = (c1 + c2) / 2.0
                    if best is None or conf > best[0]:
                        best = (conf, [g.item_id for g in group])
    if best is None:
        return None
    return ColorSchemeMatch(
        scheme="tetradic", confidence=round(best[0], 3), items_used=best[1]
    )


# ----------------------------- forbidden_palettes --------------------------


def _is_pastel(color: _ItemColor) -> bool:
    """Пастельный = низкая saturation + высокая value."""
    if color.saturation is None or color.value is None:
        return False
    return color.saturation < 0.35 and color.value > 0.75


def _is_dusty_warm(color: _ItemColor) -> bool:
    """Пыльный тёплый = низкая saturation, средняя value, тёплый hue.

    Тёплые hue: 0..60° и 330..360°.
    """
    if color.saturation is None or color.value is None or color.hue is None:
        return False
    warm = color.hue <= 60.0 or color.hue >= 330.0 or (60.0 < color.hue <= 90.0)
    return warm and 0.15 < color.saturation < 0.50 and 0.35 < color.value < 0.70


def _matches_forbidden_name(color: _ItemColor, forbidden_names: list[str]) -> bool:
    """Точное совпадение имени цвета из YAML (если имя есть)."""
    if not color.color_name:
        return False
    lowered = color.color_name.lower()
    return any(n.lower() == lowered for n in forbidden_names)


def _check_forbidden_palettes(
    colors: list[_ItemColor], subtype: str, rules: dict
) -> list[ColorForbidden]:
    """Найти цвета, попадающие в ``forbidden_palettes[subtype]``."""
    palettes = (rules.get("forbidden_palettes") or {}).get(subtype) or []
    if not palettes:
        return []

    hits: list[ColorForbidden] = []
    for palette in palettes:
        name = palette.get("name", "")
        reason = palette.get("reason") or f"Цвета палитры {name} не подходят подтипу"
        forbidden_colors = palette.get("colors") or []

        matched_items: list[str] = []
        for c in colors:
            if not c.is_colored:
                continue
            if _matches_forbidden_name(c, forbidden_colors):
                matched_items.append(c.item_id)
                continue
            # Эвристика: имена в forbidden_palettes («soft», «pastels»,
            # «dusty», «muted») маппятся на HSV-признаки пастели/пыли.
            lname = name.lower()
            if ("pastel" in lname or "soft" in lname) and _is_pastel(c):
                matched_items.append(c.item_id)
            elif (
                ("dusty" in lname or "muted" in lname or "warm" in lname)
                and _is_dusty_warm(c)
            ):
                matched_items.append(c.item_id)

        if matched_items:
            hits.append(
                ColorForbidden(reason=reason, items=sorted(set(matched_items)))
            )
    return hits


# ----------------------------- composition_rules --------------------------


_TOP_CATEGORIES = {"top", "tops", "blouse", "shirt", "sweater", "jacket", "t_shirt", "tshirt"}
_BOTTOM_CATEGORIES = {"bottom", "bottoms", "pants", "skirt", "jeans", "trousers", "shorts"}


def _is_top(item: _ItemColor) -> bool:
    if not item.category:
        return False
    return item.category.lower() in _TOP_CATEGORIES


def _is_bottom(item: _ItemColor) -> bool:
    if not item.category:
        return False
    return item.category.lower() in _BOTTOM_CATEGORIES


def _check_break_vertical(colors: list[_ItemColor]) -> bool:
    """Есть ли контраст верха/низа по hue или value (≥0.3)."""
    tops = [c for c in colors if _is_top(c) and c.is_colored]
    bottoms = [c for c in colors if _is_bottom(c) and c.is_colored]
    if not tops or not bottoms:
        return False
    for t in tops:
        for b in bottoms:
            hue_d = _hue_diff(t.hue, b.hue)
            val_d = abs((t.value or 0.0) - (b.value or 0.0))
            if hue_d >= 60.0 or val_d >= 0.3:
                return True
    return False


def _check_single_tone(colors: list[_ItemColor]) -> bool:
    """Все цветные вещи находятся в пределах 20° по hue — единый тон."""
    chromatic = [c for c in colors if c.is_colored and not _is_achromatic(c)]
    if len(chromatic) < 2:
        return False
    hues = [c.hue for c in chromatic]
    spread = max(_hue_diff(a, b) for a in hues for b in hues)
    return spread <= 20.0


def _check_close_colors(colors: list[_ItemColor]) -> bool:
    """Есть ли две вещи в одной узкой зоне hue (<=20°) с близким value."""
    chromatic = [c for c in colors if c.is_colored and not _is_achromatic(c)]
    if len(chromatic) < 2:
        return False
    for i, a in enumerate(chromatic):
        for b in chromatic[i + 1 :]:
            if _hue_diff(a.hue, b.hue) <= 20.0 and abs(a.value - b.value) <= 0.2:
                return True
    return False


def _apply_composition_rules(
    colors: list[_ItemColor], subtype: str, rules: dict
) -> tuple[float, list[str], list[str]]:
    """Вернуть (delta_score, hits[], explanations[]).

    Читает ``composition_rules[subtype]`` и применяет известные id.
    Неизвестные id пропускаются — YAML «живой», id могут добавляться.
    """
    rules_list = (rules.get("composition_rules") or {}).get(subtype) or []
    delta = 0.0
    hits: list[str] = []
    explanations: list[str] = []

    for rule in rules_list:
        if not isinstance(rule, dict) or not rule:
            continue
        rid = rule.get("id")
        if not rid:
            continue

        if rid == "break_vertical_by_color":
            if _check_break_vertical(colors):
                delta += float(rule.get("score_boost") or 0.0)
                hits.append(rid)
                explanations.append(
                    "Силуэт разбит цветом: контрастный верх и низ"
                )
            else:
                pen = float(rule.get("violation_penalty") or 0.0)
                if pen and _check_single_tone(colors):
                    delta -= pen
                    explanations.append(
                        "Силуэт не разбит — один тон от верха до низа"
                    )

        elif rid == "single_tone_without_accent":
            if _check_single_tone(colors):
                delta -= float(rule.get("score_penalty") or 0.0)
                hits.append(rid)
                explanations.append(
                    "Один оттенок без ярких акцентов — теряется энергия"
                )

        elif rid == "close_colors_same_zone":
            if _check_close_colors(colors):
                delta -= float(rule.get("score_penalty") or 0.0)
                hits.append(rid)
                explanations.append(
                    "Очень близкие оттенки в одной зоне — нет разбивки"
                )

        # Остальные композиционные правила (electric_bold_colors_preferred,
        # wild_color_combinations, colorful_splashes_over_dark_light_base)
        # требуют знания «ярких» цветов цветотипа — их подключим после
        # интеграции с color_engine. Сейчас пропускаем молча.

    return delta, hits, explanations


# ----------------------------- сервис --------------------------------------


class ColorCombinationService:
    """Оценка цветовых сочетаний образа.

    Параметры
    ---------
    rules_loader
        Опциональный загрузчик правил. Должен возвращать dict из
        ``color_schemes.yaml``. Если ``None`` — грузим файл сами.
    color_engine
        Опциональный ``ColorEngine`` для доступа к палитре цветотипа
        (``get_palette``). Нужен для будущих правил «яркие цвета»;
        сейчас принимается, но используется только как справочник.
    """

    def __init__(self, rules_loader: Any = None, color_engine: Any = None) -> None:
        self._rules_loader = rules_loader
        self._color_engine = color_engine

        self._rules = self._load_rules()
        self._named_rgb = _load_named_rgb()

    def _load_rules(self) -> dict:
        if self._rules_loader is not None:
            try:
                rv = self._rules_loader()
                if isinstance(rv, dict):
                    # допускаем как прямой dict color_schemes.yaml, так и
                    # bundle из load_rules() с ключом 'color_schemes'.
                    if "color_schemes" in rv and "composition_rules" in rv:
                        return rv
                    inner = rv.get("color_schemes_rules") or rv.get("color_schemes_yaml")
                    if isinstance(inner, dict):
                        return inner
            except TypeError:
                # rules_loader — это модуль или что-то ещё, грузим сами
                pass
        return _load_color_schemes_rules()

    # ------------------------------------------------------------------ API

    def evaluate(
        self,
        items: list[WardrobeItem],
        user_subtype: str,
        user_season: str,
    ) -> ColorCombinationResult:
        """Оценить цветовое сочетание вещей образа.

        Возвращает ``ColorCombinationResult`` со score в диапазоне
        ``[-1.0, +1.0]``, списком совпавших схем, попаданий в forbidden
        и активных composition-правил.
        """
        _ = user_season  # пока не используется, задел на будущие правила

        if not items:
            return ColorCombinationResult(
                score=0.0,
                explanation="Образ пустой — нечего оценивать.",
                matched_schemes=[],
                forbidden_hits=[],
                composition_hits=[],
                quality="low",
            )

        # --- 1. Извлекаем цвет из каждой вещи (детерминированный порядок) --
        raw_colors = [
            _extract_color_from_item(item, self._named_rgb) for item in items
        ]
        # Сортируем по item_id для детерминизма сочетаний в детекторах.
        raw_colors.sort(key=lambda c: c.item_id)

        total = len(raw_colors)
        colors = [c for c in raw_colors if c.is_colored]
        missing = total - len(colors)

        # Вещи с мерцающим финишем не считаются «чистым цветом» — понижаем
        # их вес в расчёте схемы (confidence-пенальти).
        shiny_ids = {
            c.item_id for c in colors
            if c.fabric_finish in ("metallic", "sequin", "brocade")
        }

        # --- 2. Quality ---
        if not colors:
            return ColorCombinationResult(
                score=0.0,
                explanation=(
                    "Не удалось определить цвет ни одной вещи — оценка недоступна."
                ),
                matched_schemes=[],
                forbidden_hits=[],
                composition_hits=[],
                quality="low",
            )

        missing_ratio = missing / total
        if missing_ratio >= 0.5:
            quality: Literal["high", "medium", "low"] = "low"
        elif missing_ratio > 0.0 or shiny_ids or any(
            c.pattern_scale is not None for c in colors
        ):
            quality = "medium"
        else:
            quality = "high"

        # --- 3. Цветовые схемы ---
        schemes: list[ColorSchemeMatch] = []
        for detector in (
            _detect_monochromatic,
            _detect_analogous,
            _detect_complementary,
            _detect_triad,
            _detect_split_complementary,
            _detect_tetradic,
        ):
            match = detector(colors)
            if match is not None:
                schemes.append(match)

        # Учтём avoid_for_subtypes: у FG моно — штраф.
        subtype_avoid_penalty = 0.0
        avoid_reasons: list[str] = []
        scheme_block = self._rules.get("color_schemes") or {}
        for m in schemes:
            block = scheme_block.get(m.scheme) or {}
            avoid_list = block.get("avoid_for_subtypes") or []
            if user_subtype in avoid_list:
                subtype_avoid_penalty += 0.25 * m.confidence
                avoid_reasons.append(
                    block.get("avoid_reason")
                    or f"Схема {m.scheme} не подходит подтипу {user_subtype}."
                )

        # Бонус за попадание в pairs_well_with_subtypes.
        scheme_bonus = 0.0
        scheme_match_notes: list[str] = []
        for m in schemes:
            block = scheme_block.get(m.scheme) or {}
            pairs = block.get("pairs_well_with_subtypes") or []
            # confidence может быть снижена если использованные items shiny
            eff_conf = m.confidence
            if any(i in shiny_ids for i in m.items_used):
                eff_conf *= 0.7
            if user_subtype in pairs:
                scheme_bonus += 0.3 * eff_conf
                scheme_match_notes.append(
                    f"Схема {m.scheme} подходит подтипу (confidence {m.confidence:.2f})"
                )

        # Если ничего не нашли — сам факт «цвета несочетаемые» мягкий минус.
        if not schemes and len(colors) >= 2:
            scheme_bonus -= 0.1
            scheme_match_notes.append(
                "Ни одна из шести схем не опознана — сочетание случайное"
            )

        # --- 4. Forbidden palettes ---
        forbidden_hits = _check_forbidden_palettes(colors, user_subtype, self._rules)
        forbidden_penalty = 0.0
        for hit in forbidden_hits:
            # Каждое попадание — -0.2 * (количество затронутых вещей)
            forbidden_penalty += 0.2 * min(len(hit.items), 3)

        # --- 5. Composition rules ---
        composition_delta, composition_hits, composition_expl = (
            _apply_composition_rules(colors, user_subtype, self._rules)
        )

        # --- 6. Суммируем score ---
        score = 0.0
        score += scheme_bonus
        score -= subtype_avoid_penalty
        score -= forbidden_penalty
        score += composition_delta
        # Clamp
        score = max(-1.0, min(1.0, score))

        # --- 7. Explanation ---
        lines: list[str] = []
        if scheme_match_notes:
            lines.extend(scheme_match_notes)
        if avoid_reasons:
            lines.extend(avoid_reasons)
        if forbidden_hits:
            for hit in forbidden_hits:
                lines.append(f"Стоп-палитра: {hit.reason}")
        if composition_expl:
            lines.extend(composition_expl)
        if shiny_ids:
            lines.append(
                "Учтены вещи с мерцающим финишем — их цвет считается приблизительно"
            )
        if missing:
            lines.append(
                f"Цвет не определён у {missing} из {total} вещей — оценка неполная"
            )
        if not lines:
            lines.append("Сочетание нейтральное — без явных плюсов и минусов.")

        explanation = " · ".join(lines)

        return ColorCombinationResult(
            score=round(score, 3),
            explanation=explanation,
            matched_schemes=schemes,
            forbidden_hits=forbidden_hits,
            composition_hits=composition_hits,
            quality=quality,
        )


__all__ = [
    "ColorCombinationService",
    "ColorCombinationResult",
    "ColorSchemeMatch",
    "ColorForbidden",
]
