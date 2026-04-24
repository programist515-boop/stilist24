"""Тесты сервиса цветовых сочетаний (Фаза 4)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.color_combination_service import (
    ColorCombinationResult,
    ColorCombinationService,
    ColorSchemeMatch,
)


# ---------------------------------------------------------------- helpers


def _item(
    id_: str,
    *,
    category: str | None = "top",
    hex_color: str | None = None,
    color_name: str | None = None,
    fabric_finish: str | None = None,
    pattern_scale: str | None = None,
) -> SimpleNamespace:
    """Сконструировать совместимый с сервисом item-подобный объект."""
    attrs: dict = {}
    if hex_color:
        attrs["primary_color_hex"] = hex_color
    if color_name:
        attrs["primary_color"] = color_name
    return SimpleNamespace(
        id=id_,
        category=category,
        attributes_json=attrs,
        fabric_finish=fabric_finish,
        pattern_scale=pattern_scale,
    )


@pytest.fixture
def service() -> ColorCombinationService:
    return ColorCombinationService()


# ---------------------------------------------------------------- tests


class TestEmptyAndNoColor:
    def test_empty_items_returns_low_quality(self, service: ColorCombinationService) -> None:
        res = service.evaluate([], "flamboyant_gamine", "bright_spring")
        assert res.score == 0.0
        assert res.quality == "low"
        assert res.matched_schemes == []

    def test_no_color_data_returns_low_quality(
        self, service: ColorCombinationService
    ) -> None:
        # attributes_json пуст — цвет не определить.
        items = [_item("a", category="top"), _item("b", category="bottom")]
        res = service.evaluate(items, "flamboyant_gamine", "bright_spring")
        assert res.quality == "low"
        assert res.matched_schemes == []


class TestSchemes:
    def test_monochromatic_detected(self, service: ColorCombinationService) -> None:
        # Два оттенка синего — hue в пределах 15°.
        items = [
            _item("a", hex_color="#1E3A8A"),  # dark blue, hue ~224
            _item("b", hex_color="#3B82F6"),  # bright blue, hue ~217
        ]
        res = service.evaluate(items, "classic", "true_winter")
        scheme_names = {s.scheme for s in res.matched_schemes}
        assert "monochromatic" in scheme_names

    def test_fg_monochromatic_is_penalized(
        self, service: ColorCombinationService
    ) -> None:
        """FG имеет avoid_for_subtypes на monochromatic — ожидаем штраф."""
        items = [
            _item("a", hex_color="#1E3A8A"),
            _item("b", hex_color="#3B82F6"),
        ]
        res = service.evaluate(items, "flamboyant_gamine", "bright_spring")
        # Схема обнаружена, но для FG она в стоп-списке.
        assert any(s.scheme == "monochromatic" for s in res.matched_schemes)
        # Explanation должен упомянуть "не подходит".
        assert "не подходит" in res.explanation.lower() or "моноцвет" in res.explanation.lower()

    def test_complementary_blue_orange(self, service: ColorCombinationService) -> None:
        items = [
            _item("a", hex_color="#1E90FF"),  # dodger blue, ~210°
            _item("b", hex_color="#FF8C00"),  # dark orange, ~30°
        ]
        res = service.evaluate(items, "flamboyant_gamine", "bright_spring")
        schemes = {s.scheme for s in res.matched_schemes}
        assert "complementary" in schemes

    def test_triad_red_yellow_blue(self, service: ColorCombinationService) -> None:
        items = [
            _item("a", hex_color="#E63946", category="top"),     # red ~355
            _item("b", hex_color="#FFD60A", category="bottom"),  # yellow ~51
            _item("c", hex_color="#0077B6", category="shoes"),   # blue ~200
        ]
        res = service.evaluate(items, "flamboyant_gamine", "bright_spring")
        schemes = {s.scheme for s in res.matched_schemes}
        # Триада не всегда идеальная — но complementary/triadic/split должен быть
        assert schemes & {"triadic", "complementary", "split_complementary"}


class TestForbiddenPalettes:
    def test_fg_pastel_hits_forbidden(self, service: ColorCombinationService) -> None:
        """Пастельные вещи (низкая saturation, высокая value) у FG — штраф."""
        items = [
            _item("a", hex_color="#FAD0C4"),  # светло-персиковый пастель
            _item("b", hex_color="#C1E1C1"),  # мятно-пастель
        ]
        res = service.evaluate(items, "flamboyant_gamine", "bright_spring")
        assert len(res.forbidden_hits) > 0
        assert res.score < 0


class TestCompositionRules:
    def test_fg_break_vertical_bonus(self, service: ColorCombinationService) -> None:
        """Контрастный top/bottom по hue для FG — composition boost."""
        items = [
            _item("top1", category="top", hex_color="#FFFFFF"),      # белый
            _item("bot1", category="pants", hex_color="#8B0000"),    # тёмно-красный
        ]
        res = service.evaluate(items, "flamboyant_gamine", "bright_spring")
        assert "break_vertical_by_color" in res.composition_hits


class TestQualityDowngrade:
    def test_partial_data_quality_medium(
        self, service: ColorCombinationService
    ) -> None:
        """50%+ вещей имеют цвет → quality=medium (не low)."""
        items = [
            _item("a", hex_color="#1E90FF"),
            _item("b", hex_color="#FF8C00"),
            _item("c"),  # нет цвета
        ]
        res = service.evaluate(items, "flamboyant_gamine", "bright_spring")
        assert res.quality in {"medium", "high"}

    def test_mostly_missing_quality_low(
        self, service: ColorCombinationService
    ) -> None:
        items = [
            _item("a", hex_color="#1E90FF"),
            _item("b"),
            _item("c"),
            _item("d"),
        ]
        res = service.evaluate(items, "flamboyant_gamine", "bright_spring")
        # 3 из 4 без цвета = 75% missing → low
        assert res.quality == "low"

    def test_shiny_fabric_drops_quality_to_medium(
        self, service: ColorCombinationService
    ) -> None:
        items = [
            _item("a", hex_color="#C0C0C0", fabric_finish="metallic"),
            _item("b", hex_color="#FFD700", fabric_finish="sequin"),
        ]
        res = service.evaluate(items, "flamboyant_gamine", "bright_spring")
        assert res.quality == "medium"


class TestDeterminism:
    def test_same_input_same_output(self, service: ColorCombinationService) -> None:
        items = [
            _item("a", hex_color="#1E90FF", category="top"),
            _item("b", hex_color="#FF8C00", category="bottom"),
        ]
        r1 = service.evaluate(items, "flamboyant_gamine", "bright_spring")
        r2 = service.evaluate(items, "flamboyant_gamine", "bright_spring")
        assert r1.score == r2.score
        assert r1.explanation == r2.explanation
        assert [s.scheme for s in r1.matched_schemes] == [
            s.scheme for s in r2.matched_schemes
        ]

    def test_item_order_does_not_change_result(
        self, service: ColorCombinationService
    ) -> None:
        a = _item("a", hex_color="#1E90FF", category="top")
        b = _item("b", hex_color="#FF8C00", category="bottom")
        r1 = service.evaluate([a, b], "flamboyant_gamine", "bright_spring")
        r2 = service.evaluate([b, a], "flamboyant_gamine", "bright_spring")
        assert r1.score == r2.score
        # Схемы детектируются на одном и том же множестве items — одинаковый порядок.
        assert {s.scheme for s in r1.matched_schemes} == {
            s.scheme for s in r2.matched_schemes
        }


class TestScoreBounds:
    def test_score_in_range(self, service: ColorCombinationService) -> None:
        items = [
            _item("a", hex_color="#FF0000"),
            _item("b", hex_color="#00FF00"),
            _item("c", hex_color="#0000FF"),
        ]
        res = service.evaluate(items, "flamboyant_gamine", "bright_spring")
        assert -1.0 <= res.score <= 1.0

    def test_result_type(self, service: ColorCombinationService) -> None:
        res = service.evaluate([], "flamboyant_gamine", "bright_spring")
        assert isinstance(res, ColorCombinationResult)
