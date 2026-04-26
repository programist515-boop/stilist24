"""Тесты color try-on сервиса.

Тестируем всё через in-memory storage + монкейпатч rembg,
чтобы не тянуть модель ONNX и не зависеть от сети/MinIO.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest
from PIL import Image

from app.core.storage import InMemoryStorageBackend, StorageService
from app.schemas.color_tryon import ColorTryOnResponse
from app.services.color_try_on_service import (
    ColorTryOnNotFoundError,
    ColorTryOnService,
    _extract_palette_hex,
    _guess_color_name,
    _normalize_hex,
    _rgb_to_hsv,
    deterministic_key_for,
)


# ---------------------------------------------------------------- fixtures


USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_USER_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")
ITEM_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


@dataclass
class _Item:
    """Минимальная реплика ``WardrobeItem`` для теста."""

    id: uuid.UUID
    user_id: uuid.UUID
    image_key: str
    image_url: str = "memory://ai-stylist/item.png"
    pattern_scale: str | None = None
    fabric_finish: str | None = None


class _StubWardrobeRepo:
    def __init__(self, item: _Item | None) -> None:
        self._item = item

    def get_by_id(self, item_id: uuid.UUID) -> _Item | None:
        if self._item and self._item.id == item_id:
            return self._item
        return None


class _FakeDB:
    """Stub ``Session`` — мы не трогаем БД из тестов, только через monkeypatch."""


def _make_pure_color_png(color: tuple[int, int, int]) -> bytes:
    """Сгенерировать маленький одноцветный PNG — это наш «исходник вещи»."""
    img = Image.new("RGB", (16, 16), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _full_mask_rembg(image_bytes: bytes) -> bytes:
    """Монкейпатч-замена rembg: маска = вся картинка (alpha=255 везде).

    Принимает RGB-PNG, возвращает RGBA-PNG с alpha=255.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    # alpha channel уже 255 после convert("RGBA") для RGB-входа.
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _install_item_in_storage(
    storage: StorageService, item: _Item, png_bytes: bytes
) -> None:
    storage.backend.put(item.image_key, png_bytes, content_type="image/png")


def _service(
    *,
    item: _Item | None,
    user_context: dict,
    rembg_remove=_full_mask_rembg,
    enable_ml: bool = False,
) -> tuple[ColorTryOnService, InMemoryStorageBackend]:
    backend = InMemoryStorageBackend(public_base_url="memory://ai-stylist")
    storage = StorageService(backend=backend)
    svc = ColorTryOnService(
        _FakeDB(),
        storage=storage,
        user_context_builder=lambda _db, _uid: user_context,
        rembg_remove=rembg_remove,
        enable_ml=enable_ml,
    )
    svc.wardrobe = _StubWardrobeRepo(item)  # type: ignore[assignment]
    return svc, backend


# ================================================================ pure helpers


class TestPureHelpers:
    def test_normalize_hex_full(self) -> None:
        assert _normalize_hex("#AABBCC") == "aabbcc"

    def test_normalize_hex_short(self) -> None:
        assert _normalize_hex("#abc") == "aabbcc"

    def test_normalize_hex_bad_raises(self) -> None:
        with pytest.raises(ValueError):
            _normalize_hex("zzz")  # не hex-символы

    def test_normalize_hex_wrong_length_raises(self) -> None:
        with pytest.raises(ValueError):
            _normalize_hex("xyzxy")

    def test_rgb_to_hsv_red_is_0_deg(self) -> None:
        h, s, v = _rgb_to_hsv(1.0, 0.0, 0.0)
        assert h == pytest.approx(0.0)
        assert s == pytest.approx(1.0)
        assert v == pytest.approx(1.0)

    def test_rgb_to_hsv_blue_is_240_deg(self) -> None:
        h, _s, _v = _rgb_to_hsv(0.0, 0.0, 1.0)
        assert h == pytest.approx(240.0)

    def test_guess_color_name_red_is_krasnyi(self) -> None:
        # Чистый красный — в словаре именованных должен выпасть красный
        # или терракотовый (оба допустимо близкие варианты).
        name = _guess_color_name("#dc143c")
        assert name in {"красный", "терракотовый"}

    def test_extract_palette_hex_dedup_and_normalize(self) -> None:
        ctx = {
            "palette_hex": ["#AABBCC", "#aabbcc", "#123456", "zzz"],
        }
        # ``zzz`` — не-hex, отсекаем. Дубли по регистру склеиваются.
        assert _extract_palette_hex(ctx) == ["aabbcc", "123456"]


# ================================================================ HSV shift


class TestHsvShiftColor:
    def test_hsv_shift_pure_red_to_blue(self) -> None:
        """Чистый красный квадрат с полной маской → после перекраса в blue
        средний hue пикселей в маске должен быть в окрестности синего (240°)."""
        item = _Item(
            id=ITEM_ID, user_id=USER_ID, image_key=f"users/{USER_ID}/wardrobe/{ITEM_ID}.png"
        )
        svc, backend = _service(
            item=item,
            user_context={"palette_hex": ["#0000ff"]},
        )
        red_png = _make_pure_color_png((255, 0, 0))
        _install_item_in_storage(svc.storage, item, red_png)

        response = svc.build(user_id=USER_ID, item_id=ITEM_ID)

        assert isinstance(response, ColorTryOnResponse)
        assert len(response.variants) == 1
        variant = response.variants[0]
        assert variant.color_hex == "#0000ff"

        # Восстанавливаем байты из backend-а и проверяем средний цвет.
        key = deterministic_key_for(ITEM_ID, "#0000ff")
        stored = backend.get_object(key)
        assert stored is not None
        data, _ct = stored
        out_img = Image.open(io.BytesIO(data)).convert("RGBA")
        arr = np.asarray(out_img)
        rgb = arr[:, :, :3].astype(np.float32) / 255.0
        mean_r = float(rgb[..., 0].mean())
        mean_g = float(rgb[..., 1].mean())
        mean_b = float(rgb[..., 2].mean())
        # После перекраса чистого красного в синий — доминирует B-канал.
        assert mean_b > mean_r
        assert mean_b > mean_g


# ================================================================ кэш


class TestHsvSuitabilityGuard:
    """HSV-перекрас не работает на принтах и металлике — guard в build()."""

    def test_patterned_item_returns_empty_low_quality(self) -> None:
        item = _Item(
            id=ITEM_ID,
            user_id=USER_ID,
            image_key=f"users/{USER_ID}/wardrobe/{ITEM_ID}.png",
            pattern_scale="medium",  # принт → HSV-перекрас не работает
        )
        svc, _backend = _service(
            item=item,
            user_context={"palette_hex": ["#0000ff", "#ff00ff"]},
            enable_ml=False,
        )
        # Источник нам не нужен — guard сработает раньше
        response = svc.build(user_id=USER_ID, item_id=ITEM_ID)
        assert isinstance(response, ColorTryOnResponse)
        assert response.variants == []
        assert response.quality == "low"

    def test_metallic_item_returns_empty_low_quality(self) -> None:
        item = _Item(
            id=ITEM_ID,
            user_id=USER_ID,
            image_key=f"users/{USER_ID}/wardrobe/{ITEM_ID}.png",
            fabric_finish="metallic",
        )
        svc, _backend = _service(
            item=item,
            user_context={"palette_hex": ["#0000ff"]},
            enable_ml=False,
        )
        response = svc.build(user_id=USER_ID, item_id=ITEM_ID)
        assert response.variants == []
        assert response.quality == "low"

    def test_metallic_case_insensitive(self) -> None:
        item = _Item(
            id=ITEM_ID,
            user_id=USER_ID,
            image_key=f"users/{USER_ID}/wardrobe/{ITEM_ID}.png",
            fabric_finish="Metallic",  # capitalised — должно сработать
        )
        svc, _backend = _service(
            item=item,
            user_context={"palette_hex": ["#0000ff"]},
            enable_ml=False,
        )
        response = svc.build(user_id=USER_ID, item_id=ITEM_ID)
        assert response.variants == []

    def test_solid_matte_passes_through(self) -> None:
        """Однотонная матовая — guard пропускает, перекрас идёт."""
        item = _Item(
            id=ITEM_ID,
            user_id=USER_ID,
            image_key=f"users/{USER_ID}/wardrobe/{ITEM_ID}.png",
            pattern_scale=None,
            fabric_finish="matte",
        )
        svc, _backend = _service(
            item=item,
            user_context={"palette_hex": ["#0000ff"]},
            enable_ml=False,
        )
        red_png = _make_pure_color_png((255, 0, 0))
        _install_item_in_storage(svc.storage, item, red_png)
        response = svc.build(user_id=USER_ID, item_id=ITEM_ID)
        assert len(response.variants) == 1

    def test_patterned_item_passes_when_ml_enabled(self) -> None:
        """С ML-флагом on вещь пускается дальше — FASHN расскрасит принт."""
        item = _Item(
            id=ITEM_ID,
            user_id=USER_ID,
            image_key=f"users/{USER_ID}/wardrobe/{ITEM_ID}.png",
            pattern_scale="large",
            fabric_finish="matte",
        )
        svc, _backend = _service(
            item=item,
            user_context={"palette_hex": ["#0000ff"]},
            enable_ml=True,
        )
        red_png = _make_pure_color_png((255, 0, 0))
        _install_item_in_storage(svc.storage, item, red_png)
        response = svc.build(user_id=USER_ID, item_id=ITEM_ID)
        # ML-путь — stub, но HSV-перекрас всё равно идёт (хук _maybe_run_ml
        # не блокирует основной поток). Главное — guard не сработал.
        assert len(response.variants) == 1

    def test_legacy_item_without_attrs_passes_through(self) -> None:
        """У legacy-вещей нет атрибутов Фазы 0 — back-compat: пропускаем."""

        @dataclass
        class _LegacyItem:
            id: uuid.UUID
            user_id: uuid.UUID
            image_key: str
            # без pattern_scale / fabric_finish

        item = _LegacyItem(
            id=ITEM_ID,
            user_id=USER_ID,
            image_key=f"users/{USER_ID}/wardrobe/{ITEM_ID}.png",
        )
        svc, _backend = _service(
            item=item,  # type: ignore[arg-type]
            user_context={"palette_hex": ["#0000ff"]},
            enable_ml=False,
        )
        red_png = _make_pure_color_png((255, 0, 0))
        _install_item_in_storage(svc.storage, item, red_png)
        response = svc.build(user_id=USER_ID, item_id=ITEM_ID)
        assert len(response.variants) == 1


class TestCacheHit:
    def test_cache_hit_does_not_regenerate(self) -> None:
        """Второй вызов build не должен пересчитывать: те же URL,
        rembg не дёргается повторно."""
        item = _Item(
            id=ITEM_ID, user_id=USER_ID, image_key=f"users/{USER_ID}/wardrobe/{ITEM_ID}.png"
        )
        call_count = {"n": 0}

        def counting_rembg(data: bytes) -> bytes:
            call_count["n"] += 1
            return _full_mask_rembg(data)

        svc, _backend = _service(
            item=item,
            user_context={"palette_hex": ["#00ff00", "#0000ff"]},
            rembg_remove=counting_rembg,
        )
        _install_item_in_storage(svc.storage, item, _make_pure_color_png((200, 50, 50)))

        first = svc.build(user_id=USER_ID, item_id=ITEM_ID)
        assert len(first.variants) == 2
        # Один rembg на все цвета — кэшируем маску в рамках одного вызова.
        assert call_count["n"] == 1

        second = svc.build(user_id=USER_ID, item_id=ITEM_ID)
        # URL совпадают с первым вызовом — пришли из кэша.
        urls_first = {v.image_url for v in first.variants}
        urls_second = {v.image_url for v in second.variants}
        assert urls_first == urls_second
        # rembg больше НЕ вызывался: второй build — всё из кэша.
        assert call_count["n"] == 1


# ================================================================ детерминизм


class TestDeterministicKeys:
    def test_same_item_palette_same_keys(self) -> None:
        item = _Item(
            id=ITEM_ID, user_id=USER_ID, image_key=f"users/{USER_ID}/wardrobe/{ITEM_ID}.png"
        )
        svc_a, _ = _service(
            item=item, user_context={"palette_hex": ["#E8735A", "#98D3A5"]}
        )
        svc_b, _ = _service(
            item=item, user_context={"palette_hex": ["#e8735a", "#98D3A5"]}
        )
        _install_item_in_storage(svc_a.storage, item, _make_pure_color_png((200, 100, 80)))
        _install_item_in_storage(svc_b.storage, item, _make_pure_color_png((200, 100, 80)))

        resp_a = svc_a.build(user_id=USER_ID, item_id=ITEM_ID)
        resp_b = svc_b.build(user_id=USER_ID, item_id=ITEM_ID)

        # Путь в S3 (ключ) детерминирован для (item, hex) — разные backend,
        # одинаковые ключи.
        keys_a = sorted(
            deterministic_key_for(ITEM_ID, v.color_hex) for v in resp_a.variants
        )
        keys_b = sorted(
            deterministic_key_for(ITEM_ID, v.color_hex) for v in resp_b.variants
        )
        assert keys_a == keys_b
        # URL одинаковы у обоих backend-ов (один и тот же public_base_url).
        urls_a = sorted(v.image_url for v in resp_a.variants)
        urls_b = sorted(v.image_url for v in resp_b.variants)
        assert urls_a == urls_b


# ================================================================ not found


class TestNotFound:
    def test_item_not_found(self) -> None:
        svc, _ = _service(item=None, user_context={"palette_hex": ["#0000ff"]})
        with pytest.raises(ColorTryOnNotFoundError):
            svc.build(user_id=USER_ID, item_id=ITEM_ID)

    def test_item_belongs_to_other_user(self) -> None:
        item = _Item(
            id=ITEM_ID, user_id=OTHER_USER_ID, image_key=f"users/{OTHER_USER_ID}/w/{ITEM_ID}.png"
        )
        svc, _ = _service(item=item, user_context={"palette_hex": ["#0000ff"]})
        with pytest.raises(ColorTryOnNotFoundError):
            svc.build(user_id=USER_ID, item_id=ITEM_ID)


# ================================================================ пустая палитра


class TestNoPalette:
    def test_empty_palette_returns_low_quality(self) -> None:
        item = _Item(
            id=ITEM_ID, user_id=USER_ID, image_key=f"users/{USER_ID}/wardrobe/{ITEM_ID}.png"
        )
        svc, _ = _service(item=item, user_context={})
        response = svc.build(user_id=USER_ID, item_id=ITEM_ID)
        assert response.variants == []
        assert response.quality == "low"


# ================================================================ feedback


class TestFeedbackRecords:
    def test_feedback_calls_personalization(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """POST feedback → вызывает ``record_color_preference`` с корректным аргументом."""
        captured: dict[str, Any] = {}

        class _FakeProfile:
            def __init__(self) -> None:
                self.color_vector_json = {}

        class _FakePersoRepo:
            def __init__(self, db) -> None:
                pass

            def get_or_create(self, user_id: uuid.UUID) -> _FakeProfile:
                return _FakeProfile()

            def update(self, user_id: uuid.UUID, **fields) -> None:
                captured["update_args"] = fields

        class _FakePersoService:
            def record_color_preference(
                self, profile: dict, hex_code: str, liked: bool
            ) -> dict:
                captured["called_with"] = (hex_code, liked)
                profile.setdefault("color_vector_json", {})
                key = hex_code.lstrip("#").lower()
                profile["color_vector_json"][key] = 0.04 if liked else -0.03
                return profile

        monkeypatch.setattr(
            "app.repositories.personalization_repository.PersonalizationRepository",
            _FakePersoRepo,
        )
        monkeypatch.setattr(
            "app.services.personalization_service.PersonalizationService",
            _FakePersoService,
        )

        item = _Item(
            id=ITEM_ID, user_id=USER_ID, image_key=f"users/{USER_ID}/wardrobe/{ITEM_ID}.png"
        )
        svc, _ = _service(item=item, user_context={"palette_hex": ["#0000ff"]})

        svc.record_feedback(
            user_id=USER_ID,
            item_id=ITEM_ID,
            variant_hex="#E8735A",
            liked=True,
        )

        assert captured["called_with"] == ("#E8735A", True)
        assert "update_args" in captured
        assert "color_vector_json" in captured["update_args"]

    def test_personalization_service_bumps_color_vector(self) -> None:
        """Smoke-тест самого :class:`PersonalizationService.record_color_preference`."""
        from app.services.personalization_service import PersonalizationService

        service = PersonalizationService()
        profile: dict = {}
        service.record_color_preference(profile, "#E8735A", liked=True)
        assert profile["color_vector_json"]["e8735a"] > 0.0

        service.record_color_preference(profile, "#E8735A", liked=False)
        # После одного дизлайка — суммарный дельта ещё положительный
        # (STEP_UP=0.04, STEP_DOWN=0.03), но точно меньше первого бампа.
        assert profile["color_vector_json"]["e8735a"] == pytest.approx(0.01, rel=1e-3)
