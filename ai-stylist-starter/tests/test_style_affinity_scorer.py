"""Тесты StyleAffinityScorer (Фаза 6)."""

from __future__ import annotations

import pytest

from app.services.outfits.scoring.style_affinity import StyleAffinityScorer


# ----------------------------- фикстуры ------------------------------------


def _item(id_: str, *, style_tags: list[str] | None = None, **extra) -> dict:
    attrs: dict = {"style_tags": style_tags} if style_tags is not None else {}
    attrs.update(extra)
    return {"id": id_, "category": "top", "attributes": attrs}


@pytest.fixture
def scorer() -> StyleAffinityScorer:
    return StyleAffinityScorer()


# ----------------------------- пустой/нет subtype -------------------------


class TestEmpty:
    def test_empty_items_zero_weight(self, scorer: StyleAffinityScorer) -> None:
        r = scorer.score([], {"kibbe_type": "flamboyant_gamine"})
        assert r.weight == 0.0

    def test_no_subtype_zero_weight(self, scorer: StyleAffinityScorer) -> None:
        items = [_item("a", style_tags=["military"])]
        r = scorer.score(items, {})
        assert r.weight == 0.0

    def test_no_style_tags_reduced_weight(
        self, scorer: StyleAffinityScorer
    ) -> None:
        items = [_item("a")]
        r = scorer.score(items, {"kibbe_type": "flamboyant_gamine"})
        assert r.weight < scorer.weight
        assert any("нет style_tags" in w for w in r.warnings)


# ----------------------------- FG affinity --------------------------------


class TestFlamboyantGamineAffinity:
    def test_excellent_tags_boost_score(
        self, scorer: StyleAffinityScorer
    ) -> None:
        """military + dramatic + twenties — все excellent для FG."""
        items = [
            _item("a", style_tags=["military"]),
            _item("b", style_tags=["dramatic"]),
            _item("c", style_tags=["twenties"]),
        ]
        r = scorer.score(items, {"kibbe_type": "flamboyant_gamine"})
        # avg должен быть близко к +0.12 → normalized > 0.9
        assert r.score > 0.9

    def test_unknown_subtype_neutral(
        self, scorer: StyleAffinityScorer
    ) -> None:
        """Незнакомый подтип (не в YAML) → нейтральный fallback ≈ 0.5.
        Все 13 классических подтипов наполнены 2026-04-25, поэтому
        проверяем именно неизвестный, а не существующий."""
        items = [_item("a", style_tags=["military", "dramatic"])]
        r = scorer.score(items, {"kibbe_type": "future_subtype_not_in_yaml"})
        assert r.score == 0.5

    def test_good_tags_moderate_boost(
        self, scorer: StyleAffinityScorer
    ) -> None:
        """casual, smart_casual, preppy — good для FG (+0.06)."""
        items = [
            _item("a", style_tags=["casual"]),
            _item("b", style_tags=["preppy"]),
        ]
        r = scorer.score(items, {"kibbe_type": "flamboyant_gamine"})
        # avg = 0.06, normalized = 0.5 + 0.24 = 0.74
        assert r.score == pytest.approx(0.74, abs=0.02)


# ----------------------------- selected_style ------------------------------


class TestSelectedStyle:
    def test_selected_style_filters_tags(
        self, scorer: StyleAffinityScorer
    ) -> None:
        """Если selected_style=military, учитываются только теги military."""
        items = [
            _item("a", style_tags=["military", "casual"]),
            _item("b", style_tags=["dramatic"]),
        ]
        r = scorer.score(
            items,
            {"kibbe_type": "flamboyant_gamine", "selected_style": "military"},
        )
        # Единственный military — excellent → avg = 0.12 → ~0.98
        assert r.score > 0.9

    def test_selected_style_no_match_low_score(
        self, scorer: StyleAffinityScorer
    ) -> None:
        items = [_item("a", style_tags=["casual"])]
        r = scorer.score(
            items,
            {"kibbe_type": "flamboyant_gamine", "selected_style": "military"},
        )
        assert r.score == 0.3
        assert any("ни одна вещь не тегирована" in w for w in r.warnings)


# ----------------------------- детерминизм --------------------------------


class TestDeterminism:
    def test_same_input_same_result(
        self, scorer: StyleAffinityScorer
    ) -> None:
        items = [
            _item("a", style_tags=["military", "casual"]),
            _item("b", style_tags=["dramatic"]),
        ]
        ctx = {"kibbe_type": "flamboyant_gamine"}
        r1 = scorer.score(items, ctx)
        r2 = scorer.score(items, ctx)
        assert r1.score == r2.score
        assert r1.reasons == r2.reasons


# ----------------------------- rules_loader override ----------------------


class TestRulesLoader:
    def test_custom_loader(self) -> None:
        custom = {
            "style_subtype_affinity": {
                "test_subtype": {"hip_hop": "excellent", "goth": "avoid"}
            },
            "score_modifiers": {
                "excellent": 0.20,
                "good": 0.10,
                "neutral": 0.0,
                "avoid": -0.15,
            },
        }
        scorer = StyleAffinityScorer(rules_loader=lambda: custom)
        items = [{"id": "a", "attributes": {"style_tags": ["hip_hop"]}}]
        r = scorer.score(items, {"kibbe_type": "test_subtype"})
        # excellent = 0.20, normalized = 0.5 + 0.8 = 1.0 (клампится)
        assert r.score == 1.0
