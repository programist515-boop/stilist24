"""Тесты сервиса правил категорий (Фаза 2)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.category_rules_service import (
    CategoryRuleScore,
    CategoryRulesOutfitResult,
    CategoryRulesService,
)


# ----------------------------- фикстуры ------------------------------------


def _item(
    id_: str,
    *,
    category: str,
    attributes_json: dict | None = None,
    **kwargs: object,
) -> SimpleNamespace:
    """Собрать duck-typed объект, совместимый с сервисом."""
    base = SimpleNamespace(
        id=id_,
        category=category,
        attributes_json=attributes_json or {},
    )
    for k, v in kwargs.items():
        setattr(base, k, v)
    return base


@pytest.fixture
def service() -> CategoryRulesService:
    return CategoryRulesService()


# ----------------------------- пустой/неизвестный -------------------------


class TestEmptyAndUnknown:
    def test_empty_outfit(self, service: CategoryRulesService) -> None:
        res = service.evaluate([], "flamboyant_gamine")
        assert isinstance(res, CategoryRulesOutfitResult)
        assert res.score == 0.0
        assert res.quality == "low"
        assert res.per_item == []

    def test_unknown_category(self, service: CategoryRulesService) -> None:
        item = _item("a", category="mystery_gadget")
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score == 0.0
        assert r.quality == "low"

    def test_unknown_subtype_returns_neutral(
        self, service: CategoryRulesService
    ) -> None:
        """Незнакомый подтип (не в YAML) → нейтральный fallback с quality=low.
        Все 13 классических подтипов теперь наполнены (2026-04-25)."""
        item = _item(
            "a",
            category="jacket",
            attributes_json={"fit": "fitted", "length": "cropped"},
            fit="fitted",
            length="cropped",
        )
        r = service.score_item(item, "future_subtype_not_in_yaml")
        assert r.score == 0.0
        assert r.quality == "low"


# ----------------------------- flamboyant_gamine prefer -------------------


class TestFlamboyantGaminePrefer:
    def test_jacket_matching_prefer(self, service: CategoryRulesService) -> None:
        item = _item(
            "a",
            category="jacket",
            fit="fitted",
            length="cropped",
            cut_lines="angular",
            shoulder_emphasis="required",
            sleeve_type="set_in",
            structure="structured",
            attributes_json={
                "fit": "fitted",
                "length": "cropped",
                "closure": "double_breasted",
            },
            closure="double_breasted",
        )
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score > 0
        assert r.quality == "high"
        # Должны попасть несколько префов
        assert any("fit=fitted" in n for n in r.matched_prefer)
        assert any("cut_lines=angular" in n for n in r.matched_prefer)
        assert any("shoulder_emphasis=required" in n for n in r.matched_prefer)

    def test_pants_matching_prefer_alias(
        self, service: CategoryRulesService
    ) -> None:
        """`jeans` должны резолвиться в pants.yaml через алиасы."""
        item = _item(
            "a",
            category="jeans",
            fit="straight",
            attributes_json={"fit": "straight", "waist_rise": "high"},
            waist_rise="high",
        )
        r = service.score_item(item, "flamboyant_gamine")
        assert r.category == "jeans"
        assert r.score > 0
        # fit=straight и waist_rise=high — оба попадают
        assert any("fit=straight" in n for n in r.matched_prefer)
        assert any("waist_rise=high" in n for n in r.matched_prefer)

    def test_shoes_sub_type_match(self, service: CategoryRulesService) -> None:
        item = _item(
            "a",
            category="shoes",
            attributes_json={"sub_type": "ankle_boots"},
            sub_type="ankle_boots",
        )
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score > 0
        assert any("sub_type=ankle_boots" in n for n in r.matched_prefer)

    def test_no_matching_attrs_is_zero(
        self, service: CategoryRulesService
    ) -> None:
        """Вещь с атрибутами, не попадающими ни в prefer, ни в stop."""
        item = _item(
            "a",
            category="jacket",
            fit="oversized",       # не в prefer
            length="long",         # не в prefer
            cut_lines="soft_flowing",  # не в prefer
        )
        r = service.score_item(item, "flamboyant_gamine")
        # Были оцениваемые атрибуты, но ни один не попал
        assert r.score == 0.0

    def test_stop_notes_attached(self, service: CategoryRulesService) -> None:
        """stop-notes вытягиваются как справочник, не штраф."""
        item = _item("a", category="jacket", fit="fitted")
        r = service.score_item(item, "flamboyant_gamine")
        assert len(r.stop_notes) >= 3


# ----------------------------- агрегация образа ---------------------------


class TestOutfitAggregation:
    def test_full_outfit_weighted_average(
        self, service: CategoryRulesService
    ) -> None:
        items = [
            _item(
                "a",
                category="jacket",
                fit="fitted",
                length="cropped",
                cut_lines="angular",
            ),
            _item(
                "b",
                category="pants",
                fit="straight",
                attributes_json={"waist_rise": "high"},
                waist_rise="high",
            ),
            _item(
                "c",
                category="shoes",
                attributes_json={"sub_type": "ankle_boots"},
                sub_type="ankle_boots",
            ),
        ]
        res = service.evaluate(items, "flamboyant_gamine")
        assert len(res.per_item) == 3
        assert res.score > 0
        # Quality: хотя бы у одной вещи high → не low
        assert res.quality != "low"

    def test_order_independent(self, service: CategoryRulesService) -> None:
        a = _item(
            "a",
            category="jacket",
            fit="fitted",
            length="cropped",
        )
        b = _item(
            "b",
            category="pants",
            fit="straight",
        )
        r1 = service.evaluate([a, b], "flamboyant_gamine")
        r2 = service.evaluate([b, a], "flamboyant_gamine")
        assert r1.score == r2.score

    def test_all_unknown_categories_low(
        self, service: CategoryRulesService
    ) -> None:
        items = [
            _item("a", category="mystery_a"),
            _item("b", category="mystery_b"),
        ]
        res = service.evaluate(items, "flamboyant_gamine")
        assert res.quality == "low"


# ----------------------------- attributes_json fallback -------------------


class TestAttributesJsonFallback:
    def test_reads_from_attributes_json_only(
        self, service: CategoryRulesService
    ) -> None:
        item = SimpleNamespace(
            id="a",
            category="jacket",
            attributes_json={
                "fit": "fitted",
                "length": "cropped",
                "cut_lines": "angular",
            },
        )
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score > 0
        assert any("cut_lines=angular" in n for n in r.matched_prefer)


# ----------------------------- stop predicates ----------------------------


class TestStopPredicates:
    def test_jacket_raglan_sleeve_penalty(
        self, service: CategoryRulesService
    ) -> None:
        """Реглан в жакете FG — штраф."""
        item = _item(
            "a",
            category="jacket",
            sleeve_type="raglan",
        )
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score < 0
        assert any("raglan_sleeve" in m for m in r.matched_stop)

    def test_jacket_long_unstructured_penalty(
        self, service: CategoryRulesService
    ) -> None:
        """Длинный + бесструктурный — двойное условие, оба нужны."""
        item = _item(
            "a",
            category="jacket",
            length="long",
            structure="unstructured",
        )
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score < 0
        assert any("long_unstructured" in m for m in r.matched_stop)

    def test_jacket_only_one_condition_no_penalty(
        self, service: CategoryRulesService
    ) -> None:
        """Только length=long, без structure=unstructured — штрафа нет."""
        item = _item(
            "a",
            category="jacket",
            length="long",   # одно из двух условий
        )
        r = service.score_item(item, "flamboyant_gamine")
        # ни prefer, ни stop с одиночным условием не сработали
        assert r.matched_stop == []

    def test_shoes_pumps_round_toe_penalty(
        self, service: CategoryRulesService
    ) -> None:
        item = _item(
            "a",
            category="shoes",
            attributes_json={"sub_type": "pumps"},
            sub_type="pumps",
            toe_shape="round",
        )
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score < 0
        assert any("classic_round_toe_pumps" in m for m in r.matched_stop)

    def test_shoes_wedge_penalty(
        self, service: CategoryRulesService
    ) -> None:
        """heel_type=wedge — отдельный штраф (одно условие в match)."""
        item = _item(
            "a",
            category="shoes",
            heel_type="wedge",
        )
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score < 0
        assert any("wedge_platform_smooth" in m for m in r.matched_stop)

    def test_dress_lace_full_penalty(
        self, service: CategoryRulesService
    ) -> None:
        item = _item(
            "a",
            category="dress",
            fabric_finish="lace",
        )
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score < 0
        assert any("lace_full" in m for m in r.matched_stop)

    def test_skirt_circle_penalty(
        self, service: CategoryRulesService
    ) -> None:
        item = _item(
            "a",
            category="skirt",
            attributes_json={"sub_type": "circle"},
            sub_type="circle",
        )
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score < 0
        assert any("circle_skirt" in m for m in r.matched_stop)

    def test_stop_without_match_is_only_reason(
        self, service: CategoryRulesService
    ) -> None:
        """plain_blazer_symmetric (без match) не штрафует, только в stop_notes."""
        item = _item(
            "a",
            category="jacket",
            fit="oversized",   # не в prefer
        )
        r = service.score_item(item, "flamboyant_gamine")
        # Штрафа быть не должно
        assert all("plain_blazer_symmetric" not in m for m in r.matched_stop)
        # Но в stop_notes reason присутствует
        assert any("симметричный" in n for n in r.stop_notes)

    def test_prefer_and_stop_combine(
        self, service: CategoryRulesService
    ) -> None:
        """prefer-буст и stop-штраф складываются."""
        item = _item(
            "a",
            category="jacket",
            fit="fitted",            # буст
            length="long",
            structure="unstructured",  # штраф long_unstructured
        )
        r = service.score_item(item, "flamboyant_gamine")
        assert any("fit=fitted" in n for n in r.matched_prefer)
        assert any("long_unstructured" in m for m in r.matched_stop)

    def test_outfit_explanation_prioritizes_stop(
        self, service: CategoryRulesService
    ) -> None:
        items = [
            _item("a", category="jacket", sleeve_type="raglan"),
            _item("b", category="pants", fit="straight"),
        ]
        res = service.evaluate(items, "flamboyant_gamine")
        assert "STOP:" in res.explanation

    def test_blouse_soft_fabric_penalty(
        self, service: CategoryRulesService
    ) -> None:
        item = _item("a", category="blouse", fabric_rigidity="soft")
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score < 0
        assert any("fine_soft_fabric" in m for m in r.matched_stop)

    def test_sweater_oversized_loose_penalty(
        self, service: CategoryRulesService
    ) -> None:
        item = _item(
            "a",
            category="sweater",
            fit="oversized",
            structure="unstructured",
        )
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score < 0
        assert any("oversized_loose" in m for m in r.matched_stop)

    def test_bag_hobo_penalty(
        self, service: CategoryRulesService
    ) -> None:
        item = _item(
            "a",
            category="bag",
            attributes_json={"sub_type": "hobo"},
            sub_type="hobo",
        )
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score < 0
        assert any("slouchy_soft_hobo" in m for m in r.matched_stop)

    def test_eyewear_round_penalty(
        self, service: CategoryRulesService
    ) -> None:
        item = _item("a", category="glasses", shape="round")
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score < 0
        assert any("round_soft_frames" in m for m in r.matched_stop)

    def test_jewelry_round_penalty(
        self, service: CategoryRulesService
    ) -> None:
        item = _item("a", category="necklace", shape="round")
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score < 0
        assert any("round_circles_only" in m for m in r.matched_stop)

    def test_swimwear_low_rise_penalty(
        self, service: CategoryRulesService
    ) -> None:
        item = _item(
            "a",
            category="swimwear",
            attributes_json={"waist_rise": "low"},
            waist_rise="low",
        )
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score < 0
        assert any("low_rise_cutesy" in m for m in r.matched_stop)


# ----------------------------- nested rules (outerwear) -------------------


class TestNestedOuterwearRules:
    """outerwear использует nested структуру rules[subtype][sub_category].

    Сервис должен определить sub_category из item.category / item.sub_category /
    item.sub_type и применить prefer/stop вложенного блока. При неудаче —
    fallback на _DEFAULT_SUBCATEGORY (для outerwear это 'coat').
    """

    def test_dramatic_coat_long_tailored_matches_prefer(
        self, service: CategoryRulesService
    ) -> None:
        """category='coat' для Dramatic → читает rules[dramatic][coat].prefer."""
        item = _item(
            "a",
            category="coat",
            fit="tailored",
            length="long",
            structure="structured",
        )
        r = service.score_item(item, "dramatic")
        assert r.score > 0
        assert any("fit=tailored" in n for n in r.matched_prefer)
        assert any("length=long" in n for n in r.matched_prefer)

    def test_dramatic_coat_cropped_short_penalty(
        self, service: CategoryRulesService
    ) -> None:
        """cropped пальто для Dramatic — штраф (cropped_short в stop с match)."""
        item = _item(
            "a",
            category="coat",
            length="cropped",
        )
        r = service.score_item(item, "dramatic")
        assert r.score < 0
        assert any("cropped_short" in m for m in r.matched_stop)

    def test_classic_trench_via_category_alias(
        self, service: CategoryRulesService
    ) -> None:
        """category='trench' резолвится в outerwear файл, sub_category='trench'."""
        item = _item(
            "a",
            category="trench",
            length="knee",
            fit="tailored_moderate",
        )
        r = service.score_item(item, "classic")
        assert r.score > 0
        assert any("length=knee" in n for n in r.matched_prefer)

    def test_outerwear_with_explicit_sub_type(
        self, service: CategoryRulesService
    ) -> None:
        """sub_type='trench' внутри outerwear → читает trench-блок."""
        item = _item(
            "a",
            category="outerwear",
            attributes_json={"sub_type": "trench"},
            sub_type="trench",
            length="knee",
            fit="tailored",
        )
        r = service.score_item(item, "dramatic_classic")
        assert r.score > 0

    def test_unknown_sub_category_falls_back_to_coat(
        self, service: CategoryRulesService
    ) -> None:
        """category='outerwear' без sub_type → дефолт 'coat'."""
        item = _item(
            "a",
            category="outerwear",
            fit="tailored",
            length="long",
            structure="structured",
        )
        r = service.score_item(item, "dramatic")
        # Дефолт coat для dramatic заполнен — должен дать положительный score
        assert r.score > 0
        assert r.quality != "low"

    def test_biker_jacket_always_true_for_fg(
        self, service: CategoryRulesService
    ) -> None:
        """biker_jacket для FG имеет prefer={always: true} — буст без штрафов."""
        item = _item(
            "a",
            category="outerwear",
            attributes_json={"sub_type": "biker_jacket"},
            sub_type="biker_jacket",
        )
        r = service.score_item(item, "flamboyant_gamine")
        assert r.score > 0
        assert any("всегда подходит" in n for n in r.matched_prefer)

    def test_fur_coat_for_soft_dramatic(
        self, service: CategoryRulesService
    ) -> None:
        item = _item(
            "a",
            category="outerwear",
            attributes_json={"sub_type": "fur_coat"},
            sub_type="fur_coat",
        )
        r = service.score_item(item, "soft_dramatic")
        # У SD есть fur_coat блок с prefer; даже если конкретные атрибуты
        # не заполнены — quality будет low, но без падения с ошибкой.
        assert isinstance(r.score, float)
        assert r.category == "outerwear"

    def test_natural_puffer_via_sub_type(
        self, service: CategoryRulesService
    ) -> None:
        """puffer — есть в FN/Natural, нет у Dramatic. Для Natural работает."""
        item = _item(
            "a",
            category="puffer",
            attributes_json={"silhouette": "relaxed"},
        )
        r = service.score_item(item, "natural")
        # natural.puffer.prefer существует — должен сработать nested-резолвер
        # без падения; конкретные атрибуты могут не совпасть
        assert isinstance(r.score, float)
        assert r.category == "puffer"

    def test_subtype_without_requested_sub_category_falls_back(
        self, service: CategoryRulesService
    ) -> None:
        """item.sub_type='puffer', а у dramatic puffer-блока нет → fallback на 'coat'."""
        item = _item(
            "a",
            category="outerwear",
            attributes_json={"sub_type": "puffer"},
            sub_type="puffer",
            fit="tailored",
            length="long",
        )
        r = service.score_item(item, "dramatic")
        # У Dramatic нет puffer-блока — должен упасть на default 'coat'
        # и оценить вещь по coat-правилам
        assert r.score > 0
