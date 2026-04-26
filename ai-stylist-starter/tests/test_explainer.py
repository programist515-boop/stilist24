"""Тесты explainer (Identity DNA + базовые объяснения).

Главный фокус — расширение Фазы 8 (associations/motto в текстах рекомендаций).
Базовая ветка (без subtype) тестируется на регрессию.
"""

from __future__ import annotations

import pytest

from app.services import explainer
from app.services.explainer import (
    Explanation,
    explain_outfit,
    explain_shopping,
    get_identity_profile,
    identity_intro,
)


# --------------------------- identity_intro -------------------------------


class TestIdentityIntro:
    def test_known_subtype_returns_dict(self) -> None:
        intro = identity_intro("flamboyant_gamine")
        assert intro is not None
        assert intro["display_name"] == "Гамин-Драматик"
        assert "Правила были созданы" in intro["motto"]
        assert "оторва" in intro["associations"]
        assert len(intro["associations"]) == 3  # capped

    def test_unknown_subtype_returns_none(self) -> None:
        assert identity_intro("future_subtype_xyz") is None

    def test_none_subtype_returns_none(self) -> None:
        assert identity_intro(None) is None

    def test_empty_subtype_returns_none(self) -> None:
        assert identity_intro("") is None

    def test_all_13_classical_subtypes_have_intro(self) -> None:
        """Smoke: профили заполнены для всех 13 подтипов (после сессии 4)."""
        subtypes = [
            "flamboyant_gamine",
            "gamine",
            "soft_gamine",
            "dramatic",
            "soft_dramatic",
            "flamboyant_natural",
            "soft_natural",
            "natural",
            "dramatic_classic",
            "soft_classic",
            "classic",
            "romantic",
            "theatrical_romantic",
        ]
        for subtype in subtypes:
            intro = identity_intro(subtype)
            assert intro is not None, f"{subtype} имеет пустой профиль"
            assert intro["motto"], f"{subtype} без мотто"
            assert intro["associations"], f"{subtype} без ассоциаций"

    def test_yaml_loaded_once(self) -> None:
        """Повторный вызов использует кэш — один и тот же профиль-объект."""
        a = identity_intro("flamboyant_gamine")
        b = identity_intro("flamboyant_gamine")
        # Кэш на уровне _load_profiles — данные одинаковые
        assert a == b


class TestGetIdentityProfile:
    def test_returns_full_profile(self) -> None:
        prof = get_identity_profile("dramatic")
        assert prof is not None
        assert "philosophy" in prof
        assert "key_principles" in prof
        assert "celebrity_examples" in prof

    def test_unknown_returns_none(self) -> None:
        assert get_identity_profile("not_a_subtype") is None

    def test_none_returns_none(self) -> None:
        assert get_identity_profile(None) is None


# --------------------------- explain_outfit (regression + identity) -------


class TestExplainOutfitRegression:
    """Без subtype поведение должно остаться прежним."""

    def test_high_score_summary(self) -> None:
        e = explain_outfit({"total_score": 0.85, "breakdown": {}})
        assert e.summary == "Отличный образ"

    def test_low_score_summary(self) -> None:
        e = explain_outfit({"total_score": 0.20, "breakdown": {}})
        assert e.summary == "Стоит доработать"

    def test_subscore_reasons_passed(self) -> None:
        outfit = {
            "total_score": 0.80,
            "breakdown": {
                "palette_fit": {"score": 0.9},
                "silhouette": {"score": 0.8},
            },
        }
        e = explain_outfit(outfit)
        assert "Цвет хорошо подходит вам" in e.reasons
        assert "Силуэт сбалансирован" in e.reasons


class TestExplainOutfitWithIdentity:
    def test_high_score_with_subtype_prepends_associations(self) -> None:
        outfit = {
            "total_score": 0.85,
            "breakdown": {"palette_fit": {"score": 0.9}},
        }
        e = explain_outfit(outfit, subtype="flamboyant_gamine")
        assert e.reasons[0].startswith("В вашем стиле — ")
        # хотя бы одна из FG-ассоциаций
        assert any(
            assoc in e.reasons[0]
            for assoc in ("оторва", "креативная", "вызывающая")
        )

    def test_low_score_with_subtype_no_associations(self) -> None:
        """При плохом образе фраза identity не добавляется — нечестно."""
        outfit = {"total_score": 0.20, "breakdown": {}}
        e = explain_outfit(outfit, subtype="flamboyant_gamine")
        assert all(
            "В вашем стиле" not in r for r in e.reasons
        )

    def test_unknown_subtype_falls_back_to_default(self) -> None:
        outfit = {"total_score": 0.85, "breakdown": {}}
        e = explain_outfit(outfit, subtype="future_xyz")
        # Никаких identity-фраз, но summary как обычно
        assert e.summary == "Отличный образ"
        assert all("В вашем стиле" not in r for r in e.reasons)

    def test_subtype_does_not_exceed_max_reasons(self) -> None:
        outfit = {
            "total_score": 0.85,
            "breakdown": {
                "palette_fit": {"score": 0.9},
                "silhouette": {"score": 0.8},
                "occasion": {"score": 0.8},
                "preference": {"score": 0.8},
            },
        }
        e = explain_outfit(outfit, subtype="dramatic")
        # MAX_REASONS = 3 — не должно быть превышения
        assert len(e.reasons) <= 3
        # Identity-фраза идёт первой
        assert e.reasons[0].startswith("В вашем стиле — ")


# --------------------------- explain_shopping ------------------------------


class TestExplainShoppingWithIdentity:
    def test_buy_with_subtype_adds_phrase(self) -> None:
        result = {
            "decision": "buy",
            "subscores": {"palette_match": {"score": 0.9}},
        }
        e = explain_shopping(result, subtype="dramatic")
        assert e.summary == "Стоит купить"
        assert e.reasons[0].startswith("Поддержит ваш стиль: ")

    def test_skip_with_subtype_no_identity_phrase(self) -> None:
        result = {"decision": "skip", "subscores": {}}
        e = explain_shopping(result, subtype="dramatic")
        assert all(
            "Поддержит ваш стиль" not in r for r in e.reasons
        )

    def test_buy_without_subtype_unchanged(self) -> None:
        result = {
            "decision": "buy",
            "subscores": {"palette_match": {"score": 0.9}},
        }
        e = explain_shopping(result)
        assert e.summary == "Стоит купить"
        assert all("Поддержит ваш стиль" not in r for r in e.reasons)


# --------------------------- defensive ------------------------------------


class TestDefensive:
    def test_explain_outfit_returns_explanation_instance(self) -> None:
        e = explain_outfit({"total_score": 0.5}, subtype="flamboyant_gamine")
        assert isinstance(e, Explanation)

    def test_to_dict_contract_unchanged(self) -> None:
        e = explain_outfit({"total_score": 0.85}, subtype="flamboyant_gamine")
        d = e.to_dict()
        assert set(d.keys()) == {"summary", "reasons", "warnings"}
