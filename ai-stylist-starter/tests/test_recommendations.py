"""Tests for RecommendationGuideService.

The service is a pure projection over two data sources
(``StyleProfile`` for Kibbe family / color profile, ``PersonalizationProfile``
for the style vector) into a curated YAML bundle, so tests go through
the DI seam — no DB, no real YAML file needed, same pattern as
``test_today.py``.

A small representative YAML bundle is used as the guides_loader stub
so tests don't depend on the production copy file and remain stable
if the Russian strings get rewritten.
"""

import uuid

import re

from app.services.recommendation_guide_service import (
    KIBBE_FAMILIES,
    SECTION_ORDER,
    RecommendationGuideService,
    _color_profile_summary,
    _normalize_fashion_terms,
    _resolve_family,
    _top_style_tags,
)


USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


# ---------------------------------------------------------------- fixtures


_DEFAULT_COLOR_PROFILE = {
    "undertone": "cool",
    "depth": "medium",
    "chroma": "soft",
    "contrast": "low",
}


class _FakeStyleProfile:
    def __init__(
        self,
        kibbe_type: str | None = "dramatic",
        color_profile: dict | None = None,
    ):
        self.kibbe_type = kibbe_type
        # Same None-vs-empty distinction as _FakePersonalization so tests
        # can pass `color_profile={}` and actually get an empty profile.
        self.color_profile_json = (
            dict(_DEFAULT_COLOR_PROFILE) if color_profile is None else color_profile
        )


_DEFAULT_STYLE_VECTOR = {
    "classic": 0.8,
    "minimal": 0.5,
    "romantic": 0.2,
}


class _FakePersonalization:
    def __init__(self, style_vector: dict | None = None):
        # Distinguish "not specified" (None → default) from "explicitly
        # empty" ({} → empty) so tests can exercise the empty-vector
        # branch without the `or` fallback stomping the value.
        self.style_vector_json = (
            dict(_DEFAULT_STYLE_VECTOR) if style_vector is None else style_vector
        )


def _fake_guides() -> dict:
    """Small curated stub — covers every Kibbe family plus section shape."""
    base_section = lambda k, t: {
        "key": k,
        "title": t,
        "description": f"desc for {k}",
        "recommended": [f"do {k} A", f"do {k} B"],
        "avoid": [f"avoid {k} A"],
    }
    sections = [
        base_section("lines_silhouette", "Линии и силуэт"),
        base_section("necklines", "Вырезы и горловины"),
        base_section("fabrics", "Ткани"),
        base_section("textures", "Фактуры"),
        base_section("prints", "Принты"),
        base_section("details", "Детали и декор"),
        base_section("jackets", "Жакеты"),
        base_section("tops", "Верх"),
        base_section("emphasize", "Акцент"),
        base_section("avoid_overall", "Избегать"),
    ]
    family_bundle = lambda name: {
        "style_key": f"style key {name}",
        "summary": f"summary for {name}",
        "closing_note": f"closing for {name}",
        "sections": sections,
    }
    return {
        "dramatic": family_bundle("dramatic"),
        "natural": family_bundle("natural"),
        "classic": family_bundle("classic"),
        "gamine": family_bundle("gamine"),
        "romantic": family_bundle("romantic"),
    }


def _make_service(
    *,
    kibbe: str | None = "dramatic",
    color_profile: dict | None = None,
    style_vector: dict | None = None,
    guides: dict | None = None,
) -> RecommendationGuideService:
    style = (
        _FakeStyleProfile(kibbe_type=kibbe, color_profile=color_profile)
        if kibbe is not None or color_profile is not None
        else None
    )
    perso = _FakePersonalization(style_vector)
    return RecommendationGuideService(
        db=None,
        style_profile_loader=lambda _uid: style,
        personalization_loader=lambda _uid: perso,
        guides_loader=lambda: guides or _fake_guides(),
    )


# ---------------------------------------------------------------- pure helpers


def test_resolve_family_matches_plain_family():
    for family in KIBBE_FAMILIES:
        assert _resolve_family(family) == family


def test_resolve_family_matches_subtype_with_modifier():
    assert _resolve_family("soft_dramatic") == "dramatic"
    assert _resolve_family("flamboyant_gamine") == "gamine"
    assert _resolve_family("Soft Natural") == "natural"
    assert _resolve_family("theatrical_romantic") == "romantic"


def test_resolve_family_returns_none_for_empty_or_unknown():
    assert _resolve_family(None) is None
    assert _resolve_family("") is None
    assert _resolve_family("unknown_type") is None


def test_color_profile_summary_builds_russian_line():
    summary = _color_profile_summary(
        {"undertone": "cool", "depth": "medium", "chroma": "soft", "contrast": "low"}
    )
    assert summary is not None
    assert "Холодный подтон" in summary
    assert "средняя глубина" in summary
    assert "мягкая насыщенность" in summary
    assert "низкий контраст" in summary
    assert " · " in summary


def test_color_profile_summary_returns_none_on_empty():
    assert _color_profile_summary(None) is None
    assert _color_profile_summary({}) is None


def test_top_style_tags_orders_by_weight_desc():
    tags = _top_style_tags({"classic": 0.5, "minimal": 0.9, "romantic": 0.2})
    assert tags == ["minimal", "classic", "romantic"]


def test_top_style_tags_drops_zero_and_non_numeric():
    tags = _top_style_tags(
        {"classic": 0.5, "broken": "nope", "empty": 0, "minimal": 0.2}
    )
    assert tags == ["classic", "minimal"]


def test_top_style_tags_deterministic_on_ties():
    tags = _top_style_tags({"b": 0.5, "a": 0.5, "c": 0.5})
    # Same weight → alpha order
    assert tags == ["a", "b", "c"]


def test_top_style_tags_respects_limit():
    tags = _top_style_tags(
        {"a": 0.9, "b": 0.8, "c": 0.7, "d": 0.6, "e": 0.5}, limit=3
    )
    assert tags == ["a", "b", "c"]


def test_top_style_tags_empty_on_missing_or_empty():
    assert _top_style_tags(None) == []
    assert _top_style_tags({}) == []


# ---------------------------------------------------------------- happy path


def test_get_guide_returns_full_bundle_for_dramatic():
    service = _make_service(kibbe="dramatic")
    result = service.get_guide(USER_ID)

    assert result["identity"]["kibbe_family"] == "dramatic"
    assert result["identity"]["kibbe_type"] == "dramatic"
    assert result["identity"]["style_key"] == "style key dramatic"
    assert result["identity"]["color_profile_summary"] is not None
    assert result["summary"] == "summary for dramatic"
    assert result["closing_note"] == "closing for dramatic"
    assert len(result["sections"]) == len(SECTION_ORDER)


def test_get_guide_resolves_subtype_to_family():
    service = _make_service(kibbe="soft_dramatic")
    result = service.get_guide(USER_ID)

    assert result["identity"]["kibbe_family"] == "dramatic"
    # Raw kibbe_type is preserved for UI display.
    assert result["identity"]["kibbe_type"] == "soft_dramatic"
    assert result["summary"] == "summary for dramatic"


def test_get_guide_sections_follow_canonical_order():
    service = _make_service(kibbe="natural")
    result = service.get_guide(USER_ID)

    keys = [s["key"] for s in result["sections"]]
    assert keys == list(SECTION_ORDER)


def test_get_guide_sections_reordered_even_if_yaml_shuffled():
    # Deliberately shuffle section order in the stub guides to verify
    # the service re-orders them.
    guides = _fake_guides()
    for family in KIBBE_FAMILIES:
        guides[family]["sections"] = list(
            reversed(guides[family]["sections"])
        )
    service = _make_service(kibbe="gamine", guides=guides)
    result = service.get_guide(USER_ID)

    keys = [s["key"] for s in result["sections"]]
    assert keys == list(SECTION_ORDER)


def test_get_guide_includes_top_style_tags_in_notes():
    service = _make_service(
        kibbe="classic",
        style_vector={"classic": 0.9, "minimal": 0.6, "tomboy": 0.3},
    )
    result = service.get_guide(USER_ID)

    assert result["identity"]["top_style_tags"] == [
        "classic",
        "minimal",
        "tomboy",
    ]
    assert any("classic" in note for note in result["notes"])


def test_get_guide_works_without_style_vector():
    service = _make_service(kibbe="classic", style_vector={})
    result = service.get_guide(USER_ID)

    assert result["identity"]["top_style_tags"] == []
    # No "strong directions" note when style vector is empty.
    assert result["notes"] == []
    assert result["summary"] == "summary for classic"


# ---------------------------------------------------------------- degraded


def test_get_guide_returns_empty_state_when_kibbe_missing():
    service = _make_service(kibbe=None)
    result = service.get_guide(USER_ID)

    assert result["identity"]["kibbe_family"] is None
    assert result["sections"] == []
    assert len(result["notes"]) == 1
    assert "Анализ" in result["notes"][0] or "анализ" in result["notes"][0]
    # Summary is still a friendly prompt, not empty.
    assert result["summary"]


def test_get_guide_returns_empty_state_when_style_profile_none():
    service = RecommendationGuideService(
        db=None,
        style_profile_loader=lambda _uid: None,
        personalization_loader=lambda _uid: None,
        guides_loader=_fake_guides,
    )
    result = service.get_guide(USER_ID)

    assert result["identity"]["kibbe_family"] is None
    assert result["sections"] == []
    assert result["notes"]


def test_get_guide_degrades_when_family_missing_from_guides():
    # Guides without `dramatic` — simulate missing bundle.
    guides = _fake_guides()
    guides.pop("dramatic")
    service = _make_service(kibbe="dramatic", guides=guides)
    result = service.get_guide(USER_ID)

    assert result["identity"]["kibbe_family"] == "dramatic"
    assert result["sections"] == []
    assert result["notes"]
    assert any("dramatic" in note for note in result["notes"])


def test_get_guide_degrades_on_non_dict_bundle():
    guides = {"dramatic": "not a dict"}
    service = _make_service(kibbe="dramatic", guides=guides)
    result = service.get_guide(USER_ID)

    assert result["sections"] == []
    assert result["notes"]


def test_get_guide_without_color_profile_does_not_crash():
    service = _make_service(kibbe="natural", color_profile={})
    result = service.get_guide(USER_ID)

    assert result["identity"]["color_profile_summary"] is None
    assert result["sections"]


# ---------------------------------------------------------------- real YAML


def test_real_yaml_file_has_every_family_and_every_section():
    """Sanity-check the shipped copy file itself.

    Regression guard: if someone edits the YAML and drops a family or
    a section, this catches it before it reaches production.
    """
    from app.services.recommendation_guide_service import _load_guides

    # Clear the cache so a prior test using a stub guides_loader doesn't
    # affect this real-file load.
    _load_guides.cache_clear()
    guides = _load_guides()

    for family in KIBBE_FAMILIES:
        assert family in guides, f"missing family: {family}"
        bundle = guides[family]
        assert bundle.get("style_key"), f"{family}: style_key missing"
        assert bundle.get("summary"), f"{family}: summary missing"
        assert bundle.get("closing_note"), f"{family}: closing_note missing"
        keys = {s["key"] for s in bundle.get("sections", [])}
        for required in SECTION_ORDER:
            assert required in keys, f"{family}: section '{required}' missing"


def test_service_against_real_yaml_returns_ordered_sections():
    """End-to-end: real StyleProfile stub + real YAML bundle."""
    from app.services.recommendation_guide_service import _load_guides

    _load_guides.cache_clear()
    style = _FakeStyleProfile(kibbe_type="natural")
    perso = _FakePersonalization({"minimal": 0.6, "relaxed": 0.4})
    service = RecommendationGuideService(
        db=None,
        style_profile_loader=lambda _uid: style,
        personalization_loader=lambda _uid: perso,
    )
    result = service.get_guide(USER_ID)

    assert result["identity"]["kibbe_family"] == "natural"
    assert [s["key"] for s in result["sections"]] == list(SECTION_ORDER)
    assert result["summary"]
    assert result["closing_note"]


# ------------------------------------------------ l10n safeguard unit tests


def test_normalize_replaces_single_english_term():
    assert _normalize_fashion_terms("Шёлк charmeuse") == "Шёлк шармёз"


def test_normalize_replaces_multiple_terms():
    text = "Blazer с puff-рукавом и paisley"
    result = _normalize_fashion_terms(text)
    assert "блейзер" in result.lower()
    assert "пышный" in result.lower()
    assert "пейсли" in result.lower()
    # No English left
    assert "blazer" not in result.lower()
    assert "puff" not in result.lower()
    assert "paisley" not in result.lower()


def test_normalize_case_insensitive():
    assert "блейзер" in _normalize_fashion_terms("BLAZER").lower()
    assert "пейсли" in _normalize_fashion_terms("Paisley").lower()


def test_normalize_empty_and_none():
    assert _normalize_fashion_terms("") == ""
    assert _normalize_fashion_terms("Чистый русский текст") == "Чистый русский текст"


def test_normalize_long_term_before_short():
    # "polo shirt" must match as a whole, not "polo" separately.
    result = _normalize_fashion_terms("Polo shirt из хлопка")
    assert "рубашка-поло" in result.lower()


def test_normalize_tie_dye():
    assert _normalize_fashion_terms("tie-dye принт") == "тай-дай принт"


def test_normalize_sweetheart_neckline():
    result = _normalize_fashion_terms("Sweetheart neckline мягкий")
    assert "вырез «сердечком»" in result.lower()


def test_normalize_double_breasted():
    result = _normalize_fashion_terms("Double-breasted жакет")
    assert "двубортный" in result.lower()


# ------------------------------------------------ l10n safeguard in _build_sections


def _guides_with_english_terms() -> dict:
    """Stub guides that deliberately contain English fashion terms."""
    sections = [
        {
            "key": "fabrics",
            "title": "Ткани",
            "description": "Выбирайте charmeuse и velour",
            "recommended": ["Blazer из кожи", "Polo shirt"],
            "avoid": ["Puff-рукава"],
        },
    ]
    return {
        "dramatic": {
            "style_key": "test",
            "summary": "Носите blazer с paisley принтом",
            "closing_note": "Избегайте oversize bomber",
            "sections": sections,
        },
    }


def test_build_sections_normalizes_english_terms():
    service = _make_service(
        kibbe="dramatic",
        guides=_guides_with_english_terms(),
    )
    result = service.get_guide(USER_ID)

    # Summary and closing_note should be normalized
    assert "blazer" not in result["summary"].lower()
    assert "блейзер" in result["summary"].lower()
    assert "пейсли" in result["summary"].lower()

    assert "oversize" not in result["closing_note"].lower()
    assert "оверсайз" in result["closing_note"].lower()
    assert "бомбер" in result["closing_note"].lower()

    # Section fields should be normalized
    fabrics = [s for s in result["sections"] if s["key"] == "fabrics"]
    assert len(fabrics) == 1
    section = fabrics[0]
    assert "charmeuse" not in section["description"].lower()
    assert "шармёз" in section["description"].lower()
    assert "велюр" in section["description"].lower()
    assert any("блейзер" in r.lower() for r in section["recommended"])
    assert any("рубашка-поло" in r.lower() for r in section["recommended"])
    assert any("пышный" in a.lower() for a in section["avoid"])


# ------------------------------------------------ YAML l10n regression


#: Regex that matches 3+ consecutive ASCII letters — i.e. an English word.
#: Excludes YAML structural keys which are internal, not user-facing.
_YAML_STRUCTURAL_KEYS = {
    "key", "title", "description", "recommended", "avoid",
    "sections", "summary", "closing_note", "style_key",
    "recommendation_guides",
}


def test_real_yaml_contains_no_english_in_user_text():
    """Regression: all user-facing text in the YAML must be Russian.

    Scans every string value in the recommendation_guides YAML and
    asserts no 3+-letter English words remain (ignoring structural keys
    and Kibbe family names which are internal identifiers).
    """
    from app.services.recommendation_guide_service import _load_guides

    _load_guides.cache_clear()
    guides = _load_guides()

    english_word_re = re.compile(r"[a-zA-Z]{3,}")

    violations: list[str] = []

    for family, bundle in guides.items():
        if not isinstance(bundle, dict):
            continue

        # Check summary and closing_note
        for field in ("summary", "closing_note", "style_key"):
            text = str(bundle.get(field) or "")
            for match in english_word_re.finditer(text):
                word = match.group(0).lower()
                if word not in _YAML_STRUCTURAL_KEYS and word not in KIBBE_FAMILIES:
                    violations.append(f"{family}.{field}: '{match.group(0)}'")

        # Check sections
        for section in bundle.get("sections") or []:
            if not isinstance(section, dict):
                continue
            section_key = section.get("key", "?")
            for field in ("title", "description"):
                text = str(section.get(field) or "")
                for match in english_word_re.finditer(text):
                    word = match.group(0).lower()
                    if word not in _YAML_STRUCTURAL_KEYS and word not in KIBBE_FAMILIES:
                        violations.append(
                            f"{family}.{section_key}.{field}: '{match.group(0)}'"
                        )
            for list_field in ("recommended", "avoid"):
                for item in section.get(list_field) or []:
                    text = str(item)
                    for match in english_word_re.finditer(text):
                        word = match.group(0).lower()
                        if word not in _YAML_STRUCTURAL_KEYS and word not in KIBBE_FAMILIES:
                            violations.append(
                                f"{family}.{section_key}.{list_field}: '{match.group(0)}'"
                            )

    assert violations == [], (
        "English terms found in user-facing YAML text:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
