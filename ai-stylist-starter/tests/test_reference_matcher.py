"""Тесты матчера референсных луков (Фаза 7).

Используем dict-вещи вместо ORM ``WardrobeItem`` — сервис поддерживает
обе формы (см. ``_item_attr``). Это убирает зависимость от БД в юнит-тестах.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.reference_matcher import (
    CategoryRulesServiceProtocol,
    MatchedItem,
    MissingSlot,
    ReferenceLookMatch,
    ReferenceMatcher,
)


# ---------------------------------------------------------------- fixtures


def _item(**overrides: Any) -> dict:
    """Собрать dict-вещь; все поля Фазы 0 по умолчанию None."""
    base = {
        "id": "x",
        "category": "dress",
        "fabric_rigidity": None,
        "fabric_finish": None,
        "occasion": None,
        "neckline_type": None,
        "sleeve_type": None,
        "sleeve_length": None,
        "pattern_scale": None,
        "pattern_character": None,
        "pattern_symmetry": None,
        "detail_scale": None,
        "structure": None,
        "cut_lines": None,
        "shoulder_emphasis": None,
        "style_tags": None,
        "attributes_json": {},
        "wear_count": 0,
    }
    base.update(overrides)
    return base


class _AlwaysDenyRules:
    """Моковая реализация протокола: всё блокирует."""

    def validate_item_for_category(self, item: Any, subtype: str, category: str) -> bool:
        return False


class _LogRules:
    """Логирует вызовы валидатора, пропускает всё."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def validate_item_for_category(self, item: Any, subtype: str, category: str) -> bool:
        self.calls.append((subtype, category))
        return True


# ---------------------------------------------------------------- tests


class TestLoader:
    def test_unknown_subtype_returns_empty(self) -> None:
        matcher = ReferenceMatcher()
        assert matcher.match_wardrobe([_item()], "nonexistent_subtype") == []

    def test_empty_subtype_returns_empty(self) -> None:
        matcher = ReferenceMatcher()
        assert matcher.match_wardrobe([_item()], "") == []

    def test_fg_returns_five_looks(self) -> None:
        matcher = ReferenceMatcher()
        result = matcher.match_wardrobe([], "flamboyant_gamine")
        # В YAML 5 луков; с пустым гардеробом все слоты — missing, но структура возвращается.
        assert len(result) == 5
        assert all(isinstance(r, ReferenceLookMatch) for r in result)
        # Пустой гардероб → completeness=0
        for look in result:
            assert look.completeness == 0.0
            assert look.matched_items == []
            assert len(look.missing_slots) > 0


class TestPartialMatch:
    def test_fg_sheath_partial(self) -> None:
        """Только платье — закрывается 1 из 2 обязательных слотов."""
        matcher = ReferenceMatcher()
        wardrobe = [
            _item(
                id="dress1",
                category="dress",
                structure="structured",
                fabric_rigidity="medium",
                cut_lines="straight",
                attributes_json={"fit": "sheath", "shoulder_accent": "required"},
            ),
        ]
        result = matcher.match_wardrobe(wardrobe, "flamboyant_gamine")
        sheath = next(r for r in result if r.look_id == "fg_sheath_dress")
        assert any(m.slot == "dress" for m in sheath.matched_items)
        assert 0.0 < sheath.completeness < 1.0
        assert any(ms.slot == "shoes" for ms in sheath.missing_slots)

    def test_shopping_hint_has_category_and_attrs(self) -> None:
        matcher = ReferenceMatcher()
        result = matcher.match_wardrobe([], "flamboyant_gamine")
        sheath = next(r for r in result if r.look_id == "fg_sheath_dress")
        shoes_missing = next(ms for ms in sheath.missing_slots if ms.slot == "shoes")
        # shopping_hint должен упоминать категорию обуви.
        assert shoes_missing.shopping_hint
        assert any(
            cat in shoes_missing.shopping_hint
            for cat in ("heels", "pointed_flats")
        )


class TestFullMatch:
    def test_casual_telnyashka_completes(self) -> None:
        """Полный гардероб под fg_casual_telnyashka."""
        matcher = ReferenceMatcher()
        wardrobe = [
            _item(
                id="tel",
                category="top",
                pattern_character="stripe",
                pattern_scale="small",
                cut_lines="straight",
            ),
            _item(
                id="jeans",
                category="jeans",
                structure="structured",
                cut_lines="straight",
            ),
            _item(
                id="sneak",
                category="sneakers",
            ),
        ]
        result = matcher.match_wardrobe(wardrobe, "flamboyant_gamine")
        tel_look = next(r for r in result if r.look_id == "fg_casual_telnyashka")
        matched_slots = {m.slot for m in tel_look.matched_items}
        assert "top" in matched_slots
        assert "bottom" in matched_slots
        assert "shoes" in matched_slots
        # outerwear — optional, отсутствие не мешает completeness=1.0 по required.
        assert tel_look.completeness == 1.0


class TestQualityDowngrade:
    def test_null_hard_attrs_reduce_quality(self) -> None:
        """Вещь с 1 из 3 hard-атрибутов — матч есть, но match_quality низкий,
        и в match_reasons видны «нет данных по X»."""
        matcher = ReferenceMatcher()
        wardrobe = [
            # Только structure подходит, fabric_rigidity и cut_lines — None.
            _item(id="sparse_dress", category="dress", structure="structured"),
            _item(id="heels", category="heels"),
        ]
        result = matcher.match_wardrobe(wardrobe, "flamboyant_gamine")
        sheath = next(r for r in result if r.look_id == "fg_sheath_dress")
        dress_match = next(m for m in sheath.matched_items if m.slot == "dress")
        assert dress_match.match_quality < 0.5
        assert any("нет данных" in r for r in dress_match.match_reasons)
        assert dress_match.item_id == "sparse_dress"


class TestCategoryRulesProtocol:
    def test_allow_all_default_used_when_no_rules_passed(self) -> None:
        matcher = ReferenceMatcher()
        wardrobe = [_item(id="d1", category="dress")]
        # Должно отработать без CategoryRulesService.
        result = matcher.match_wardrobe(wardrobe, "flamboyant_gamine")
        assert len(result) == 5

    def test_deny_all_produces_no_matches(self) -> None:
        matcher = ReferenceMatcher(category_rules=_AlwaysDenyRules())
        wardrobe = [
            _item(id="d1", category="dress"),
            _item(id="s1", category="heels"),
        ]
        result = matcher.match_wardrobe(wardrobe, "flamboyant_gamine")
        for look in result:
            assert look.matched_items == []
            assert look.completeness == 0.0

    def test_protocol_called_with_expected_args(self) -> None:
        log = _LogRules()
        matcher = ReferenceMatcher(category_rules=log)
        wardrobe = [_item(id="d1", category="dress")]
        matcher.match_wardrobe(wardrobe, "flamboyant_gamine")
        # Проверяем что валидатор был вызван с корректным subtype.
        assert any(subtype == "flamboyant_gamine" for subtype, _ in log.calls)


class TestGlobalStopItems:
    def test_item_with_forbidden_cut_lines_excluded(self) -> None:
        """Вещь с cut_lines=soft_flowing попадает в global_stop_items FG."""
        matcher = ReferenceMatcher()
        wardrobe = [
            _item(id="forbidden", category="dress", cut_lines="soft_flowing"),
            _item(
                id="good",
                category="dress",
                structure="structured",
                fabric_rigidity="medium",
                cut_lines="straight",
                attributes_json={"fit": "sheath", "shoulder_accent": "required"},
            ),
        ]
        result = matcher.match_wardrobe(wardrobe, "flamboyant_gamine")
        sheath = next(r for r in result if r.look_id == "fg_sheath_dress")
        # Заматчиться должна только good, не forbidden.
        matched_ids = {m.item_id for m in sheath.matched_items}
        assert "forbidden" not in matched_ids
        assert "good" in matched_ids


class TestDeterminism:
    def test_same_wardrobe_same_result(self) -> None:
        matcher = ReferenceMatcher()
        wardrobe = [
            _item(id="a", category="dress", structure="structured", cut_lines="straight",
                  attributes_json={"fit": "sheath"}),
            _item(id="b", category="dress", structure="structured", cut_lines="straight",
                  attributes_json={"fit": "sheath"}),
            _item(id="heels", category="heels"),
        ]
        r1 = matcher.match_wardrobe(wardrobe, "flamboyant_gamine")
        r2 = matcher.match_wardrobe(wardrobe, "flamboyant_gamine")
        # Сравниваем «шоу-форму» — матчи/missing по id'ам.
        def key(looks: list[ReferenceLookMatch]) -> list[tuple[str, tuple, tuple]]:
            return [
                (
                    L.look_id,
                    tuple((m.slot, m.item_id) for m in L.matched_items),
                    tuple(ms.slot for ms in L.missing_slots),
                )
                for L in looks
            ]
        assert key(r1) == key(r2)

    def test_wear_count_tiebreaker(self) -> None:
        """При равном качестве выигрывает вещь с большим wear_count."""
        matcher = ReferenceMatcher()
        wardrobe = [
            _item(
                id="loved",
                category="dress",
                structure="structured",
                fabric_rigidity="medium",
                cut_lines="straight",
                wear_count=50,
                attributes_json={"fit": "sheath", "shoulder_accent": "required"},
            ),
            _item(
                id="fresh",
                category="dress",
                structure="structured",
                fabric_rigidity="medium",
                cut_lines="straight",
                wear_count=0,
                attributes_json={"fit": "sheath", "shoulder_accent": "required"},
            ),
        ]
        result = matcher.match_wardrobe(wardrobe, "flamboyant_gamine")
        sheath = next(r for r in result if r.look_id == "fg_sheath_dress")
        dress_match = next(m for m in sheath.matched_items if m.slot == "dress")
        assert dress_match.item_id == "loved"
