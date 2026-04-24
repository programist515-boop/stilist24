"""
Валидатор полноты identity_subtype_profiles.yaml (Фаза 8 плана identity DNA).

Логика: для каждого подтипа проверяется набор полей. Если подтип —
placeholder (associations + motto + philosophy все пусты), тест помечается
как XFAIL с пояснением. При первом же появлении контента тест переключается
в обычный режим и становится CI-gate — если контент неполный или
некачественный, тест упадёт.

Пороги подобраны по эталону flamboyant_gamine (associations=7, philosophy≈570
символов, key_principles=5, celebrities=8) с небольшим запасом.

См. plans/2026-04-21-каталог-фич-из-отчёта-типажа.md — Фаза 8.
"""
from pathlib import Path

import pytest
import yaml


RULES_DIR = Path(__file__).resolve().parent.parent / "config" / "rules"
PROFILES_PATH = RULES_DIR / "identity_subtype_profiles.yaml"

ALLOWED_FAMILIES = {"dramatic", "natural", "classic", "gamine", "romantic"}

MIN_ASSOCIATIONS = 5
MIN_PHILOSOPHY_CHARS = 300
MIN_KEY_PRINCIPLES = 4
MIN_CELEBRITIES = 6
MAX_MOTTO_CHARS = 120


def _load_profiles() -> dict:
    with PROFILES_PATH.open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc["identity_subtype_profiles"]


def _is_placeholder(profile: dict) -> bool:
    return (
        not profile.get("associations")
        and not profile.get("motto")
        and not profile.get("philosophy")
    )


@pytest.mark.parametrize("subtype", list(_load_profiles().keys()))
def test_subtype_profile_is_complete(subtype: str) -> None:
    profile = _load_profiles()[subtype]

    assert profile.get("display_name_ru"), f"{subtype}: пустой display_name_ru"
    assert profile.get("display_name_en"), f"{subtype}: пустой display_name_en"
    assert profile.get("family") in ALLOWED_FAMILIES, (
        f"{subtype}: family={profile.get('family')!r} не в "
        f"{sorted(ALLOWED_FAMILIES)}"
    )

    if _is_placeholder(profile):
        pytest.xfail(f"Фаза 8: {subtype} ещё не наполнен (placeholder)")

    assocs = profile.get("associations") or []
    assert isinstance(assocs, list) and len(assocs) >= MIN_ASSOCIATIONS, (
        f"{subtype}: ожидали associations как список длиной >= "
        f"{MIN_ASSOCIATIONS}, получили {len(assocs)}"
    )

    motto = (profile.get("motto") or "").strip()
    assert motto, f"{subtype}: пустой motto"
    assert len(motto) <= MAX_MOTTO_CHARS, (
        f"{subtype}: motto длиной {len(motto)} > {MAX_MOTTO_CHARS}"
    )

    philosophy = (profile.get("philosophy") or "").strip()
    assert len(philosophy) >= MIN_PHILOSOPHY_CHARS, (
        f"{subtype}: philosophy длиной {len(philosophy)} "
        f"< {MIN_PHILOSOPHY_CHARS} символов"
    )

    principles = profile.get("key_principles") or []
    assert isinstance(principles, list) and len(principles) >= MIN_KEY_PRINCIPLES, (
        f"{subtype}: ожидали key_principles как список длиной >= "
        f"{MIN_KEY_PRINCIPLES}, получили {len(principles)}"
    )

    celebs = profile.get("celebrity_examples") or []
    assert isinstance(celebs, list) and len(celebs) >= MIN_CELEBRITIES, (
        f"{subtype}: ожидали celebrity_examples длиной >= "
        f"{MIN_CELEBRITIES}, получили {len(celebs)}"
    )
    for idx, celeb in enumerate(celebs):
        assert isinstance(celeb, dict), f"{subtype}: celebrity #{idx} не dict"
        assert celeb.get("name"), f"{subtype}: celebrity #{idx} без поля 'name'"
