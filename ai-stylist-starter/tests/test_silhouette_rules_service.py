"""Тесты сервиса силуэтных правил (Фаза 1)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.silhouette_rules_service import (
    SilhouetteRulesResult,
    SilhouetteRulesService,
)


# ----------------------------- фикстуры ------------------------------------


def _item(
    id_: str,
    *,
    category: str | None = "top",
    cut_lines: str | None = None,
    fabric_rigidity: str | None = None,
    structure: str | None = None,
    shoulder_emphasis: str | None = None,
    sleeve_type: str | None = None,
    fit: str | None = None,
    attributes_json: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id_,
        category=category,
        cut_lines=cut_lines,
        fabric_rigidity=fabric_rigidity,
        structure=structure,
        shoulder_emphasis=shoulder_emphasis,
        sleeve_type=sleeve_type,
        fit=fit,
        attributes_json=attributes_json or {},
    )


@pytest.fixture
def service() -> SilhouetteRulesService:
    return SilhouetteRulesService()


# ----------------------------- пустой/плейсхолдер -------------------------


class TestEmptyAndPlaceholder:
    def test_empty_items(self, service: SilhouetteRulesService) -> None:
        res = service.evaluate([], "flamboyant_gamine")
        assert res.score == 0.0
        assert res.quality == "low"
        assert "пуст" in res.explanation.lower()

    def test_unknown_subtype_returns_neutral(
        self, service: SilhouetteRulesService
    ) -> None:
        """Незнакомый подтип (которого нет в YAML) → нейтральный fallback,
        quality=low, без падений. Все 13 классических подтипов теперь
        наполнены (2026-04-25), поэтому проверяем именно неизвестный."""
        items = [_item("a", cut_lines="angular"), _item("b", cut_lines="straight")]
        res = service.evaluate(items, "future_subtype_not_in_yaml")
        assert res.score == 0.0
        assert res.quality == "low"
        assert "ещё не наполнен" in res.explanation


# ----------------------------- flamboyant_gamine --------------------------


class TestFlamboyantGaminePrefer:
    def test_shoulder_emphasis_required_matches(
        self, service: SilhouetteRulesService
    ) -> None:
        items = [
            _item(
                "a",
                category="jacket",
                shoulder_emphasis="required",
                cut_lines="angular",
            ),
            _item(
                "b",
                category="pants",
                cut_lines="straight",
                fabric_rigidity="medium",
                sleeve_type="set_in",
            ),
        ]
        res = service.evaluate(items, "flamboyant_gamine")
        assert "prefer.shoulder_emphasis=required" in res.matched_prefer
        assert res.score > 0

    def test_angular_majority_bonus(self, service: SilhouetteRulesService) -> None:
        items = [
            _item("a", cut_lines="angular"),
            _item("b", cut_lines="angular", category="bottom"),
        ]
        res = service.evaluate(items, "flamboyant_gamine")
        assert "prefer.line_character=angular" in res.matched_prefer
        assert res.score > 0

    def test_mix_opposing_fits_is_bonus(
        self, service: SilhouetteRulesService
    ) -> None:
        items = [
            _item("a", category="jacket", fit="oversized", cut_lines="angular"),
            _item("b", category="skirt", fit="fitted", cut_lines="straight"),
        ]
        res = service.evaluate(items, "flamboyant_gamine")
        # composition narrow_base_plus_wide_opposite (+0.10)
        assert "narrow_base_plus_wide_opposite" in res.composition_hits
        # также prefer.mix_opposing_shapes (+0.05)
        assert "prefer.mix_opposing_shapes" in res.matched_prefer
        assert res.score >= 0.10


class TestFlamboyantGamineAvoid:
    def test_raglan_sleeve_is_penalized(
        self, service: SilhouetteRulesService
    ) -> None:
        items = [
            _item("a", category="top", sleeve_type="raglan", cut_lines="straight"),
            _item("b", category="pants", cut_lines="straight"),
        ]
        res = service.evaluate(items, "flamboyant_gamine")
        assert "avoid.raglan_or_dropped_shoulder" in res.violated_avoid
        assert res.score < 0

    def test_both_oversized_top_and_bottom_penalized(
        self, service: SilhouetteRulesService
    ) -> None:
        items = [
            _item("a", category="top", fit="oversized"),
            _item("b", category="pants", fit="wide"),
        ]
        res = service.evaluate(items, "flamboyant_gamine")
        assert "avoid.oversized_both_top_bottom" in res.violated_avoid
        assert res.score < 0

    def test_all_soft_flowing_is_composition_penalty(
        self, service: SilhouetteRulesService
    ) -> None:
        items = [
            _item("a", category="top", cut_lines="soft_flowing"),
            _item("b", category="skirt", cut_lines="soft_flowing"),
        ]
        res = service.evaluate(items, "flamboyant_gamine")
        assert "soft_top_and_soft_bottom" in res.composition_hits
        # Также detect_soft_curved_majority срабатывает (avoid.line_character)
        assert any("line_character" in v for v in res.violated_avoid)
        # penalty большая — ожидаем чётко отрицательный score
        assert res.score <= -0.14

    def test_soft_without_structure(
        self, service: SilhouetteRulesService
    ) -> None:
        items = [
            _item("a", fabric_rigidity="soft", cut_lines="soft_flowing"),
            _item("b", fabric_rigidity="soft", category="skirt"),
        ]
        res = service.evaluate(items, "flamboyant_gamine")
        assert "avoid.draped_without_structure" in res.violated_avoid


# ----------------------------- quality ------------------------------------


class TestQualityDowngrade:
    def test_no_phase0_attrs_means_low(
        self, service: SilhouetteRulesService
    ) -> None:
        items = [
            _item("a", category="top"),  # все Phase-0 поля None
            _item("b", category="skirt"),
        ]
        res = service.evaluate(items, "flamboyant_gamine")
        assert res.quality == "low"

    def test_partial_attrs_is_medium(
        self, service: SilhouetteRulesService
    ) -> None:
        # 3 вещи: у первых двух все ключевые поля заполнены, у третьей —
        # пусто. 3 missing из 9 → 33% → medium.
        items = [
            _item(
                "a", cut_lines="angular", fabric_rigidity="rigid", sleeve_type="set_in"
            ),
            _item(
                "b", cut_lines="straight", fabric_rigidity="medium", sleeve_type="set_in"
            ),
            _item("c", category="skirt"),  # пустой
        ]
        res = service.evaluate(items, "flamboyant_gamine")
        assert res.quality == "medium"

    def test_all_attrs_present_is_high(
        self, service: SilhouetteRulesService
    ) -> None:
        items = [
            _item(
                "a",
                category="jacket",
                cut_lines="angular",
                fabric_rigidity="rigid",
                sleeve_type="set_in",
                shoulder_emphasis="required",
                fit="fitted",
            ),
            _item(
                "b",
                category="skirt",
                cut_lines="straight",
                fabric_rigidity="medium",
                sleeve_type="sleeveless",
                fit="oversized",
            ),
        ]
        res = service.evaluate(items, "flamboyant_gamine")
        assert res.quality == "high"


# ----------------------------- детерминизм --------------------------------


class TestDeterminism:
    def test_same_input_same_result(
        self, service: SilhouetteRulesService
    ) -> None:
        items = [
            _item("a", category="jacket", cut_lines="angular", sleeve_type="set_in"),
            _item("b", category="skirt", cut_lines="straight", fit="fitted"),
        ]
        r1 = service.evaluate(items, "flamboyant_gamine")
        r2 = service.evaluate(items, "flamboyant_gamine")
        assert r1.score == r2.score
        assert r1.explanation == r2.explanation

    def test_order_independent(self, service: SilhouetteRulesService) -> None:
        """Результат не должен зависеть от порядка items на входе."""
        a = _item("a", category="jacket", cut_lines="angular", sleeve_type="set_in")
        b = _item("b", category="skirt", cut_lines="straight", fit="fitted")
        r1 = service.evaluate([a, b], "flamboyant_gamine")
        r2 = service.evaluate([b, a], "flamboyant_gamine")
        assert r1.score == r2.score


# ----------------------------- attributes_json fallback -------------------


class TestAttributesJsonFallback:
    def test_reads_from_attributes_json_when_column_missing(
        self, service: SilhouetteRulesService
    ) -> None:
        """Если на объекте нет колонок Phase-0 — сервис смотрит в
        attributes_json (совместимость с legacy dict-объектами)."""
        items = [
            SimpleNamespace(
                id="a",
                category="jacket",
                attributes_json={
                    "cut_lines": "angular",
                    "sleeve_type": "set_in",
                    "fabric_rigidity": "rigid",
                    "shoulder_emphasis": "required",
                    "fit": "fitted",
                },
            ),
            SimpleNamespace(
                id="b",
                category="skirt",
                attributes_json={
                    "cut_lines": "straight",
                    "fabric_rigidity": "medium",
                    "sleeve_type": "sleeveless",
                    "fit": "fitted",
                },
            ),
        ]
        res = service.evaluate(items, "flamboyant_gamine")
        assert res.quality == "high"
        assert "prefer.shoulder_emphasis=required" in res.matched_prefer
