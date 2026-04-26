"""Тесты GapAnalysisService.

Главный фокус — интеграция reference_matcher: missing_slots реф-луков
становятся дополнительными suggestions с пометкой `from_reference_look`.
Базовая ветка (без subtype) тестируется на регрессию.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.gap_analysis_service import GapAnalysisService
from app.services.reference_matcher import (
    MatchedItem,
    MissingSlot,
    ReferenceLookMatch,
)


# --------------------------- helpers ---------------------------------------


def _item(id_: str, category: str, **attrs: Any) -> dict:
    """Минимальный item dict в формате OutfitEngine."""
    base = {"id": id_, "category": category, "attributes": attrs, **attrs}
    return base


class _StubReferenceMatcher:
    """Стаб ReferenceMatcher с предзаданными матчами."""

    def __init__(self, matches: list[ReferenceLookMatch]) -> None:
        self._matches = matches
        self.calls: list[tuple[list, str]] = []

    def match_wardrobe(
        self, wardrobe: list, user_subtype: str
    ) -> list[ReferenceLookMatch]:
        self.calls.append((wardrobe, user_subtype))
        return self._matches


def _make_match(
    *,
    look_id: str,
    title: str,
    matched: list[MatchedItem] | None = None,
    missing: list[MissingSlot] | None = None,
    completeness: float = 0.5,
) -> ReferenceLookMatch:
    return ReferenceLookMatch(
        look_id=look_id,
        title=title,
        occasion=None,
        matched_items=matched or [],
        missing_slots=missing or [],
        completeness=completeness,
    )


# --------------------------- regression (no subtype) -----------------------


class TestGapAnalysisRegression:
    def test_empty_wardrobe(self) -> None:
        svc = GapAnalysisService()
        result = svc.analyze([], user_context={})
        assert result["suggestions"] == []
        assert "Гардероб пуст" in result["notes"][0]

    def test_no_subtype_no_reference_suggestions(self) -> None:
        """Без subtype ref-suggestions не генерятся (нет identity_family)."""
        stub = _StubReferenceMatcher(matches=[
            _make_match(
                look_id="ref-1",
                title="Тест",
                missing=[MissingSlot(
                    slot="top",
                    requires={"category": "blouse"},
                    shopping_hint="блузка",
                )],
            ),
        ])
        svc = GapAnalysisService(reference_matcher=stub)
        wardrobe = [_item("a", "top"), _item("b", "bottom")]
        result = svc.analyze(wardrobe, user_context={})
        # Не было subtype → matcher вообще не должен был вызываться
        assert stub.calls == []
        assert all(
            s.get("from_reference_look") is None for s in result["suggestions"]
        )


# --------------------------- reference-based integration -------------------


class TestReferenceBasedSuggestions:
    def test_missing_slots_become_suggestions(self) -> None:
        stub = _StubReferenceMatcher(matches=[
            _make_match(
                look_id="ref-1",
                title="Дерзкая работа",
                missing=[
                    MissingSlot(
                        slot="top",
                        requires={"category": "blouse"},
                        shopping_hint="блузка свободная",
                    ),
                    MissingSlot(
                        slot="shoes",
                        requires={"category": "shoes"},
                        shopping_hint="ботильоны на каблуке",
                    ),
                ],
            ),
        ])
        svc = GapAnalysisService(reference_matcher=stub)
        wardrobe = [_item("a", "top"), _item("b", "bottom")]
        result = svc.analyze(
            wardrobe,
            user_context={"identity_family": "flamboyant_gamine"},
        )
        ref_sugs = [
            s for s in result["suggestions"] if s.get("from_reference_look")
        ]
        assert len(ref_sugs) == 2
        assert all(s["from_reference_look"] == "ref-1" for s in ref_sugs)
        slots = {s["slot_hint"] for s in ref_sugs}
        assert slots == {"top", "shoes"}
        # why содержит название лука
        assert all("Дерзкая работа" in s["why"] for s in ref_sugs)

    def test_dedup_within_multiple_looks(self) -> None:
        """Один и тот же missing-слот в двух луках → один suggestion."""
        m1 = MissingSlot(
            slot="shoes",
            requires={"category": "shoes"},
            shopping_hint="ботильоны на каблуке",
        )
        # Идентичный shopping_hint → дубликат
        m2 = MissingSlot(
            slot="shoes",
            requires={"category": "shoes"},
            shopping_hint="ботильоны на каблуке",
        )
        stub = _StubReferenceMatcher(matches=[
            _make_match(look_id="ref-1", title="A", missing=[m1]),
            _make_match(look_id="ref-2", title="B", missing=[m2]),
        ])
        svc = GapAnalysisService(reference_matcher=stub)
        wardrobe = [_item("a", "top")]
        result = svc.analyze(
            wardrobe,
            user_context={"identity_family": "flamboyant_gamine"},
        )
        ref_sugs = [
            s for s in result["suggestions"] if s.get("from_reference_look")
        ]
        assert len(ref_sugs) == 1

    def test_dedup_against_existing_suggestion(self) -> None:
        """Если category+item уже есть в base-suggestion'ах — не дублируем."""
        stub = _StubReferenceMatcher(matches=[
            _make_match(
                look_id="ref-1",
                title="X",
                missing=[MissingSlot(
                    slot="bottom",
                    requires={"category": "pants"},
                    # Совпадёт с item-меткой одного из base-suggestion'ов?
                    # Зависит от gap_analysis_rules — не гарантировано.
                    # Поэтому просто проверяем, что dedup работает в принципе.
                    shopping_hint="прямые брюки",
                )],
            ),
        ])
        svc = GapAnalysisService(reference_matcher=stub)
        # Подделываем базу: уже есть suggestion (pants, "прямые брюки")
        wardrobe = [_item("a", "top")]
        # Здесь мы не управляем base-suggestion'ами напрямую, но если
        # совпадение случится — ref-suggestion должен отсутствовать
        result = svc.analyze(
            wardrobe,
            user_context={"identity_family": "flamboyant_gamine"},
        )
        keys = [(s["category"], s["item"]) for s in result["suggestions"]]
        # Все пары уникальны
        assert len(keys) == len(set(keys))

    def test_unknown_subtype_safe(self) -> None:
        """Для подтипа без YAML-файла matcher вернёт [] — не падаем."""
        stub = _StubReferenceMatcher(matches=[])
        svc = GapAnalysisService(reference_matcher=stub)
        result = svc.analyze(
            [_item("a", "top")],
            user_context={"identity_family": "unknown_subtype"},
        )
        ref_sugs = [
            s for s in result["suggestions"] if s.get("from_reference_look")
        ]
        assert ref_sugs == []
        # Stub был вызван
        assert len(stub.calls) == 1
        assert stub.calls[0][1] == "unknown_subtype"

    def test_matcher_exception_does_not_break_analysis(self) -> None:
        """Если matcher падает — gap_analysis работает дальше без ref-suggestions."""

        class _BrokenMatcher:
            def match_wardrobe(self, wardrobe: list, user_subtype: str):
                raise RuntimeError("boom")

        svc = GapAnalysisService(reference_matcher=_BrokenMatcher())
        result = svc.analyze(
            [_item("a", "top")],
            user_context={"identity_family": "flamboyant_gamine"},
        )
        assert isinstance(result["suggestions"], list)
        ref_sugs = [
            s for s in result["suggestions"] if s.get("from_reference_look")
        ]
        assert ref_sugs == []

    def test_missing_slot_with_list_category(self) -> None:
        """requires.category может быть списком — берём первый элемент."""
        stub = _StubReferenceMatcher(matches=[
            _make_match(
                look_id="ref-1",
                title="L",
                missing=[MissingSlot(
                    slot="outer",
                    requires={"category": ["coat", "trench"]},
                    shopping_hint="пальто или тренч",
                )],
            ),
        ])
        svc = GapAnalysisService(reference_matcher=stub)
        result = svc.analyze(
            [_item("a", "top")],
            user_context={"identity_family": "flamboyant_gamine"},
        )
        ref_sug = next(
            s for s in result["suggestions"] if s.get("from_reference_look")
        )
        assert ref_sug["category"] == "coat"

    def test_response_schema_compatibility(self) -> None:
        """Расширенный suggestion должен валидно парситься в GapSuggestion."""
        from app.schemas.gap_analysis import GapAnalysisResponse

        stub = _StubReferenceMatcher(matches=[
            _make_match(
                look_id="ref-1",
                title="X",
                missing=[MissingSlot(
                    slot="top",
                    requires={"category": "blouse"},
                    shopping_hint="белая блуза",
                )],
            ),
        ])
        svc = GapAnalysisService(reference_matcher=stub)
        raw = svc.analyze(
            [_item("a", "bottom")],
            user_context={"identity_family": "flamboyant_gamine"},
        )
        # Pydantic-валидация не должна упасть на новых полях
        parsed = GapAnalysisResponse.model_validate(raw)
        ref = next(
            s for s in parsed.suggestions if s.from_reference_look
        )
        assert ref.from_reference_look == "ref-1"
        assert ref.slot_hint == "top"
