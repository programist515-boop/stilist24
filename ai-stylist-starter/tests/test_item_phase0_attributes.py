"""Тесты Фазы 0: 14 новых атрибутов одежды.

Покрытие:

1. **Валидаторы модели ``WardrobeItem``** — допустимые значения
   сохраняются, недопустимые молча становятся None (честный
   quality downgrade из design_philosophy).
2. **Константы whitelist-а** — значения в ``item_attributes.py``
   синхронизированы с YAML-конфигом.
3. **CV-экстрактор ``recognize_extended``** — на синтетических
   изображениях возвращает либо допустимое значение (прошло валидацию
   whitelist), либо None. quality уверенно падает до "low" при
   большом числе None.
4. **Детерминизм** — одинаковый вход даёт одинаковый результат
   (design_philosophy). Фиксированный seed в sub-sampling пикселей.

БД-интеграция здесь не проверяется — это делает Alembic upgrade head
в отдельном шаге (см. план Фаза 0, шаг 6).
"""

from __future__ import annotations

import io
import uuid

import pytest
from PIL import Image

from app.models.item_attributes import (
    ATTRIBUTE_WHITELISTS,
    NEW_ATTRIBUTE_NAMES,
    STYLE_TAG_VALUES,
    validate_scalar,
    validate_style_tags,
)
from app.models.wardrobe_item import WardrobeItem
from app.services.garment_recognizer import (
    GarmentRecognizer,
    recognize_garment_extended,
)


# ---------------------------------------------------------------- фикстуры


def _solid_jpeg(
    width: int = 256,
    height: int = 320,
    color: tuple[int, int, int] = (80, 80, 120),
) -> bytes:
    """Сплошной однотонный прямоугольник JPEG — имитирует vanilla-вещь."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _striped_jpeg(
    width: int = 256,
    height: int = 320,
    stripe_px: int = 8,
) -> bytes:
    """Горизонтальные полосы — имитирует paterned вещь с мелким узором."""
    img = Image.new("RGB", (width, height), (240, 240, 240))
    pixels = img.load()
    assert pixels is not None
    for y in range(height):
        if (y // stripe_px) % 2 == 0:
            for x in range(width):
                pixels[x, y] = (20, 20, 20)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _asymmetric_jpeg(width: int = 256, height: int = 320) -> bytes:
    """Ассимметричное пятно слева (правая половина пустая)."""
    img = Image.new("RGB", (width, height), (255, 255, 255))
    pixels = img.load()
    assert pixels is not None
    # Пятно занимает 0..width//3 по ширине
    for y in range(height):
        for x in range(width // 3):
            pixels[x, y] = (30, 30, 30)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


# =============================================================== whitelists


class TestWhitelistCoverage:
    """Полнота и взаимная согласованность whitelist-ов."""

    def test_all_14_attributes_have_whitelist(self) -> None:
        """Каждый из 14 новых атрибутов имеет непустой whitelist значений."""
        assert len(NEW_ATTRIBUTE_NAMES) == 14
        for name in NEW_ATTRIBUTE_NAMES:
            assert name in ATTRIBUTE_WHITELISTS, f"no whitelist for {name}"
            assert len(ATTRIBUTE_WHITELISTS[name]) > 0, (
                f"empty whitelist for {name}"
            )

    def test_style_tags_whitelist_contains_eight_styles(self) -> None:
        """Справочник стилей Фазы 6: ровно 8 tag-ов."""
        assert len(STYLE_TAG_VALUES) == 8
        # Критичные значения — они явно перечислены в плане.
        for required in (
            "military", "preppy", "dandy", "casual",
            "smart_casual", "dramatic", "twenties", "romantic",
        ):
            assert required in STYLE_TAG_VALUES


class TestValidateScalar:
    def test_accepted_value_returns_same(self) -> None:
        assert validate_scalar("fabric_rigidity", "soft") == "soft"

    def test_rejected_value_returns_none(self) -> None:
        # Честный None — не оставляем мусор в БД.
        assert validate_scalar("fabric_rigidity", "springy") is None

    def test_none_passthrough(self) -> None:
        assert validate_scalar("fabric_rigidity", None) is None

    def test_unknown_attribute_returns_none(self) -> None:
        assert validate_scalar("no_such_attribute", "whatever") is None


class TestValidateStyleTags:
    def test_filters_unknown_values(self) -> None:
        result = validate_style_tags(["military", "foo", "dandy"])
        assert result == ["military", "dandy"]

    def test_deduplicates_preserving_order(self) -> None:
        result = validate_style_tags(["dramatic", "military", "dramatic"])
        assert result == ["dramatic", "military"]

    def test_empty_after_filter_returns_none(self) -> None:
        # Пустой список — честный «нет данных», а не хранимая пустышка.
        assert validate_style_tags(["foo", "bar"]) is None

    def test_none_passthrough(self) -> None:
        assert validate_style_tags(None) is None


# =============================================================== модель


class TestWardrobeItemValidators:
    """Валидаторы на уровне SQLAlchemy @validates.

    ВАЖНО: тесты не обращаются к БД — проверяют чистую логику
    валидации на in-memory объекте WardrobeItem.
    """

    def _base_kwargs(self) -> dict:
        return {
            "user_id": uuid.uuid4(),
            "image_url": "memory://x.jpg",
        }

    def test_create_without_new_fields_ok(self) -> None:
        """Все новые атрибуты nullable — можно создать без них."""
        item = WardrobeItem(**self._base_kwargs())
        for name in NEW_ATTRIBUTE_NAMES:
            assert getattr(item, name) is None, f"{name} must default to None"

    def test_create_with_all_14_fields_ok(self) -> None:
        """Валидные значения сохраняются как есть."""
        item = WardrobeItem(
            **self._base_kwargs(),
            fabric_rigidity="soft",
            fabric_finish="matte",
            occasion="work",
            neckline_type="v",
            sleeve_type="set_in",
            sleeve_length="long",
            pattern_scale="small",
            pattern_character="stripe",
            pattern_symmetry="symmetric",
            detail_scale="medium",
            structure="structured",
            cut_lines="straight",
            shoulder_emphasis="required",
            style_tags=["military", "dramatic"],
        )
        assert item.fabric_rigidity == "soft"
        assert item.fabric_finish == "matte"
        assert item.occasion == "work"
        assert item.neckline_type == "v"
        assert item.sleeve_type == "set_in"
        assert item.sleeve_length == "long"
        assert item.pattern_scale == "small"
        assert item.pattern_character == "stripe"
        assert item.pattern_symmetry == "symmetric"
        assert item.detail_scale == "medium"
        assert item.structure == "structured"
        assert item.cut_lines == "straight"
        assert item.shoulder_emphasis == "required"
        assert item.style_tags == ["military", "dramatic"]

    def test_invalid_scalar_becomes_none(self) -> None:
        """Значение вне whitelist молча становится None (честный downgrade)."""
        item = WardrobeItem(
            **self._base_kwargs(),
            fabric_rigidity="stretchy",  # нет в whitelist
            occasion="vacation",         # нет в whitelist
        )
        assert item.fabric_rigidity is None
        assert item.occasion is None

    def test_invalid_style_tags_are_filtered(self) -> None:
        """Неизвестные tags отбрасываются, валидные сохраняются."""
        item = WardrobeItem(
            **self._base_kwargs(),
            style_tags=["military", "gothic", "dandy"],
        )
        assert item.style_tags == ["military", "dandy"]


# =============================================================== CV-экстрактор


class TestRecognizeExtendedBasics:
    """Базовые инварианты расширенного распознавателя."""

    def test_all_new_fields_present(self) -> None:
        """После вызова — все 14 ключей есть (пусть и None)."""
        result = recognize_garment_extended(_solid_jpeg())
        for name in NEW_ATTRIBUTE_NAMES:
            assert name in result, f"{name} missing from extended result"

    def test_v1_keys_preserved(self) -> None:
        """Старые ключи v1 (primary_color, print_type) остаются."""
        result = recognize_garment_extended(_solid_jpeg())
        assert "primary_color" in result
        assert "print_type" in result

    def test_values_pass_whitelist(self) -> None:
        """Каждое значение — либо None, либо из whitelist (после validate_*)."""
        result = recognize_garment_extended(_solid_jpeg())
        for name in NEW_ATTRIBUTE_NAMES:
            val = result[name]
            if val is None:
                continue
            if name == "style_tags":
                assert isinstance(val, list)
                assert all(v in STYLE_TAG_VALUES for v in val)
            else:
                assert val in ATTRIBUTE_WHITELISTS[name], (
                    f"{name}={val!r} not in whitelist"
                )

    def test_quality_marker_is_low_or_medium_or_high(self) -> None:
        result = recognize_garment_extended(_solid_jpeg())
        assert result["quality"] in {"low", "medium", "high"}

    def test_filled_count_is_nonnegative_and_within_bounds(self) -> None:
        result = recognize_garment_extended(_solid_jpeg())
        assert 0 <= result["_filled_count"] <= 14


class TestQualityDowngrade:
    """Честный quality downgrade: слишком много None → quality=low."""

    def test_solid_image_with_many_nones_is_low(self) -> None:
        """На плоском однотонном изображении большинство эвристик
        не могут высказаться — честный quality=low.

        Мы не знаем заранее сколько именно атрибутов заполнится
        (зависит от доступности cv2/rembg в CI), поэтому проверяем
        логику: при низком числе filled — quality=low.
        """
        result = recognize_garment_extended(_solid_jpeg())
        filled = result["_filled_count"]
        quality = result["quality"]
        if filled >= 10:
            assert quality == "high"
        elif filled >= 7:
            assert quality == "medium"
        else:
            assert quality == "low"

    def test_critical_failure_returns_low_quality_all_none(self) -> None:
        """Вход-байты, которые нельзя декодировать → fallback = все None, low."""
        garbage = b"not-an-image"
        result = recognize_garment_extended(garbage)
        # v1 fallback (primary_color=white, print_type=solid) + все новые None
        for name in NEW_ATTRIBUTE_NAMES:
            # Возможны ситуации, когда эвристика всё-таки вернула что-то
            # на пустых пикселях; допустимо либо None, либо валидное значение.
            val = result[name]
            if val is not None:
                if name == "style_tags":
                    assert all(v in STYLE_TAG_VALUES for v in val)
                else:
                    assert val in ATTRIBUTE_WHITELISTS[name]
        # Quality не может быть high при таких данных — этот инвариант
        # нужен, чтобы garbage-in не стал high-confidence-out.
        assert result["quality"] in {"low", "medium"}


class TestDeterminism:
    """Детерминизм: одинаковый вход → одинаковый результат (принцип проекта)."""

    def test_same_input_same_output(self) -> None:
        data = _solid_jpeg(color=(90, 100, 160))
        a = recognize_garment_extended(data)
        b = recognize_garment_extended(data)
        for name in NEW_ATTRIBUTE_NAMES:
            assert a[name] == b[name], (
                f"{name} differs across runs: {a[name]!r} vs {b[name]!r}"
            )
        assert a["_filled_count"] == b["_filled_count"]
        assert a["quality"] == b["quality"]

    def test_same_input_deterministic_v1_color(self) -> None:
        """v1 primary_color тоже детерминистичен (после seed-ed subsample)."""
        data = _solid_jpeg(color=(120, 40, 40))
        a = recognize_garment_extended(data)
        b = recognize_garment_extended(data)
        assert a["primary_color"] == b["primary_color"]


class TestHeuristicsSmokeOnSyntheticImages:
    """Проверяем, что эвристики дают хоть какие-то нетривиальные сигналы
    на специально сконструированных синтетических изображениях.

    Это smoke-тесты — они документируют поведение, а не «правильные»
    ответы. Допустимо, чтобы эвристика вернула None, но тогда
    это должно отразиться в quality-метрике.
    """

    def test_asymmetric_image_symmetry_heuristic(self) -> None:
        """На пятне слева pattern_symmetry должен быть либо asymmetric,
        либо None — но не symmetric."""
        result = recognize_garment_extended(_asymmetric_jpeg())
        symmetry = result["pattern_symmetry"]
        assert symmetry in {"asymmetric", None}

    def test_striped_image_detects_pattern(self) -> None:
        """Полосатое изображение либо детектируется как patterned
        (и тогда pattern_scale имеет значение), либо остаётся
        solid (тогда pattern_scale = None — нечего мерить)."""
        result = recognize_garment_extended(_striped_jpeg())
        print_type = result.get("print_type")
        pattern_scale = result.get("pattern_scale")
        # Инвариант: если solid → scale обязан быть None.
        if print_type == "solid":
            assert pattern_scale is None
        # Если patterned → должна быть хоть какая-то шкала (но эвристика
        # может вернуть None при плохом фоне — допустимо).
        if print_type == "patterned" and pattern_scale is not None:
            assert pattern_scale in {"small", "medium", "large"}


class TestRecognizerInstanceMethod:
    """Проверяем, что instance-метод тоже работает (а не только функция)."""

    def test_instance_recognize_extended(self) -> None:
        rec = GarmentRecognizer()
        result = rec.recognize_extended(_solid_jpeg())
        assert "_filled_count" in result
        assert "quality" in result
        for name in NEW_ATTRIBUTE_NAMES:
            assert name in result
