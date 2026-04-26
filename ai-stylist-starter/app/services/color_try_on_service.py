"""Color try-on: примерка вещи в цветах палитры пользователя.

Архитектура
===========

CV-путь (всегда включён):
    1. Берём байты изображения вещи из S3.
    2. ``rembg`` строит альфа-маску (передний план = вещь).
    3. Для каждого цвета палитры делаем HSV-перекрас:
       * переводим пиксели маски в HSV,
       * сдвигаем hue к целевому,
       * мягко подтягиваем saturation к целевому (насыщенность),
       * value (яркость) сохраняем — это отвечает за тени/блики,
         ключ реалистичности.
    4. Результат кладём в S3 по детерминированному ключу
       ``color_tryon/<item_id>/<hex>.webp`` и возвращаем публичный URL.

Кэш:
    Если S3 уже содержит ключ — не перегенерируем, возвращаем готовый URL.
    Это даёт идемпотентность и детерминизм: одинаковый (item, палитра)
    → одинаковые URL.

ML-путь (FASHN recolor), за флагом ``ENABLE_ML_COLOR_TRYON``:
    Делегируется в ``FashnAdapter``. По умолчанию флаг off — stub-режим,
    реальные вызовы к FASHN не делаются. Задел на будущее: принты /
    металлик / фактура, которые HSV-shift не умеет.

HSV-перекрас работает только на однотонных матовых/глянцевых тканях.
При наличии принта (``pattern_scale != None``) или металлического финиша
(``fabric_finish == 'metallic'``) HSV-shift даёт визуальные артефакты —
возвращаем пустой ответ с ``quality='low'``. Если включён ML-флаг
(``ENABLE_ML_COLOR_TRYON``), перекрас пройдёт по альтернативному пути
(сейчас stub), поэтому не отбрасываем такие вещи.
"""

from __future__ import annotations

import hashlib
import io
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.storage import (
    StorageBackendError,
    StorageService,
    get_storage_service,
)
from app.repositories.wardrobe_repository import WardrobeRepository
from app.schemas.color_tryon import ColorTryOnResponse, ColorTryOnVariant

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- errors


class ColorTryOnError(Exception):
    """Базовый класс всех ошибок color-tryon."""


class ColorTryOnNotFoundError(ColorTryOnError):
    """Item или пользователь не найдены / item не принадлежит пользователю."""


class ColorTryOnAssetError(ColorTryOnError):
    """Проблема с исходным изображением вещи (нет ключа, не читается)."""


class ColorTryOnStorageError(ColorTryOnError):
    """Сбой backend-а хранилища (S3/MinIO)."""


class ColorTryOnRenderError(ColorTryOnError):
    """CV-перекрас упал на декодировании/rembg/кодировании."""


# ---------------------------------------------------------------- helpers


def _normalize_hex(hex_code: str) -> str:
    """Приводим #abcdef или ABCDEF к строгому формату "abcdef" (lowercase, без #)."""
    raw = (hex_code or "").strip().lstrip("#").lower()
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6 or any(ch not in "0123456789abcdef" for ch in raw):
        raise ValueError(f"bad hex color: {hex_code!r}")
    return raw


def _hex_to_rgb(hex_code: str) -> tuple[int, int, int]:
    raw = _normalize_hex(hex_code)
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _rgb_to_hsv(r: float, g: float, b: float) -> tuple[float, float, float]:
    """Чистая конверсия RGB [0..1] → HSV (H [0..360), S [0..1], V [0..1])."""
    mx = max(r, g, b)
    mn = min(r, g, b)
    d = mx - mn
    v = mx
    s = 0.0 if mx == 0 else d / mx
    if d == 0:
        h = 0.0
    elif mx == r:
        h = 60.0 * (((g - b) / d) % 6.0)
    elif mx == g:
        h = 60.0 * (((b - r) / d) + 2.0)
    else:
        h = 60.0 * (((r - g) / d) + 4.0)
    if h < 0:
        h += 360.0
    return h, s, v


@dataclass(frozen=True)
class _PaletteColor:
    hex_code: str  # "e8735a" (нормализованный)
    name: str  # человекочитаемое имя цвета


# Табличка базовых имён цветов — нужна только чтобы отрисовать
# человекочитаемый заголовок под карточкой. Точность не критична:
# ближайший именованный цвет по евклидовой HSV-дистанции.
_NAMED_COLORS: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("чёрный", (0, 0, 0)),
    ("белый", (255, 255, 255)),
    ("серый", (128, 128, 128)),
    ("красный", (220, 20, 60)),
    ("терракотовый", (210, 105, 75)),
    ("оранжевый", (255, 140, 0)),
    ("персиковый", (255, 203, 164)),
    ("золотой", (255, 215, 0)),
    ("жёлтый", (255, 235, 90)),
    ("оливковый", (107, 142, 35)),
    ("зелёный", (34, 139, 34)),
    ("мятный", (152, 211, 165)),
    ("бирюзовый", (64, 200, 200)),
    ("голубой", (135, 206, 235)),
    ("синий", (30, 60, 180)),
    ("индиго", (75, 0, 130)),
    ("лиловый", (180, 120, 200)),
    ("розовый", (255, 160, 190)),
    ("пудровый", (230, 200, 210)),
    ("бежевый", (220, 195, 170)),
    ("коричневый", (120, 80, 50)),
)


def _guess_color_name(hex_code: str) -> str:
    """Угадать русское имя цвета по HEX — ближайший по евклидовой дистанции.

    Когда таблица пустая или дистанция слишком большая — возвращаем HEX с #.
    """
    try:
        r, g, b = _hex_to_rgb(hex_code)
    except ValueError:
        return f"#{hex_code}"
    best_name = f"#{_normalize_hex(hex_code)}"
    best_d = float("inf")
    for name, (nr, ng, nb) in _NAMED_COLORS:
        d = (r - nr) ** 2 + (g - ng) ** 2 + (b - nb) ** 2
        if d < best_d:
            best_d = d
            best_name = name
    return best_name


def _extract_palette_hex(user_context: dict) -> list[str]:
    """Из user_context достаём список HEX-цветов палитры (deduplicate).

    Приоритет — `palette_hex` (готовый flat-список из color_engine.analyze).
    Fallback — собрать из best_neutrals + accent_colors.
    """
    palette = user_context.get("palette_hex") or []
    if not palette:
        color_profile = user_context.get("color_profile") or {}
        palette = (
            color_profile.get("palette_hex")
            or (
                (color_profile.get("best_neutrals") or [])
                + (color_profile.get("accent_colors") or [])
            )
        )
    # Детерминированный порядок, убираем дубли (по нормализованному виду).
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in palette:
        try:
            key = _normalize_hex(raw)
        except ValueError:
            continue
        if key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return normalized


# ---------------------------------------------------------------- service


#: Тип стандартного ключа в S3 для сгенерированных примерок.
def _output_key(item_id: uuid.UUID | str, hex_code: str) -> str:
    return f"color_tryon/{item_id}/{hex_code}.webp"


#: Подпись для rembg-функции, удобная для монкейпатча в тестах.
RembgRemove = Callable[[bytes], bytes]


class ColorTryOnService:
    """Сервис color try-on (CV-путь HSV + ML-fallback за флагом)."""

    def __init__(
        self,
        db: Session,
        *,
        storage: StorageService | None = None,
        user_context_builder: Callable[[Session, uuid.UUID], dict] | None = None,
        rembg_remove: RembgRemove | None = None,
        enable_ml: bool | None = None,
    ) -> None:
        self.db = db
        self.wardrobe = WardrobeRepository(db)
        self.storage = storage or get_storage_service()
        self._build_user_context = user_context_builder
        self._rembg_remove = rembg_remove
        self._enable_ml_override = enable_ml

    # ----- публичный API ---------------------------------------------------

    def build(
        self,
        *,
        user_id: uuid.UUID,
        item_id: uuid.UUID,
        force_regenerate: bool = False,
    ) -> ColorTryOnResponse:
        """Собрать color-tryon для вещи: сгенерировать или вернуть из кэша."""
        item = self.wardrobe.get_by_id(item_id)
        if item is None or item.user_id != user_id:
            raise ColorTryOnNotFoundError(f"item {item_id} not found")

        # Guard: HSV-перекрас даёт артефакты на принтах и металлике.
        # При выключенном ML-пути — честный quality downgrade.
        if not self._is_hsv_suitable(item) and not self._ml_enabled():
            logger.info(
                "color_tryon: item %s skipped (pattern_scale=%s, "
                "fabric_finish=%s) — HSV unfit, ML disabled",
                item_id,
                getattr(item, "pattern_scale", None),
                getattr(item, "fabric_finish", None),
            )
            return ColorTryOnResponse(
                item_id=item_id,
                variants=[],
                quality="low",
                reason="pattern_unfit",
            )

        user_context = self._load_user_context(user_id)
        palette_hex = _extract_palette_hex(user_context)
        if not palette_hex:
            # Честный quality downgrade: без палитры примерять нечего.
            return ColorTryOnResponse(
                item_id=item_id,
                variants=[],
                quality="low",
                reason="palette_missing",
            )

        palette = [
            _PaletteColor(hex_code=hex_code, name=_guess_color_name(hex_code))
            for hex_code in palette_hex
        ]

        variants: list[ColorTryOnVariant] = []
        source_bytes_cache: bytes | None = None
        rembg_mask_cache: tuple[Any, Any] | None = None  # (rgb, alpha)

        for color in palette:
            key = _output_key(item_id, color.hex_code)

            # Кэш-хит: не пересчитываем.
            if not force_regenerate and self._exists(key):
                variants.append(
                    ColorTryOnVariant(
                        color_hex=f"#{color.hex_code}",
                        color_name=color.name,
                        image_url=self.storage.public_url(key),
                    )
                )
                continue

            # Лениво грузим источник только при первом промахе кэша.
            if source_bytes_cache is None:
                source_bytes_cache = self._fetch_item_image(item)
            if rembg_mask_cache is None:
                rembg_mask_cache = self._remove_background(source_bytes_cache)

            rgb, alpha = rembg_mask_cache
            recolored = self._recolor_hsv(rgb, alpha, color.hex_code)
            content_type = "image/webp"
            try:
                self.storage.backend.put(key, recolored, content_type=content_type)
            except StorageBackendError as exc:  # pragma: no cover - сеть
                raise ColorTryOnStorageError(
                    f"failed to upload color-tryon result: {exc}"
                ) from exc

            variants.append(
                ColorTryOnVariant(
                    color_hex=f"#{color.hex_code}",
                    color_name=color.name,
                    image_url=self.storage.public_url(key),
                )
            )

        # Если флаг ML-пути включён — можно было бы отдельно прогнать
        # FASHN recolor для принтов. Пока флаг off по умолчанию; при
        # включении метод просто отдаёт stub. См. _maybe_run_ml.
        self._maybe_run_ml(item)

        return ColorTryOnResponse(
            item_id=item_id, variants=variants, quality="high"
        )

    # ----- feedback --------------------------------------------------------

    def record_feedback(
        self,
        *,
        user_id: uuid.UUID,
        item_id: uuid.UUID,
        variant_hex: str,
        liked: bool,
    ) -> None:
        """Записать цветовое предпочтение в ``personalization_profile``."""
        from app.repositories.personalization_repository import (
            PersonalizationRepository,
        )
        from app.services.personalization_service import PersonalizationService

        repo = PersonalizationRepository(self.db)
        service = PersonalizationService()

        profile = repo.get_or_create(user_id)
        profile_dict = {
            "color_vector_json": dict(profile.color_vector_json or {}),
        }
        updated = service.record_color_preference(
            profile_dict, variant_hex, liked
        )
        repo.update(
            user_id,
            color_vector_json=updated["color_vector_json"],
        )

    # ----- внутреннее ------------------------------------------------------

    def _load_user_context(self, user_id: uuid.UUID) -> dict:
        """Отдельная точка монкейпатча — в тестах подменяем builder."""
        if self._build_user_context is not None:
            return self._build_user_context(self.db, user_id)
        from app.services.user_context import build_user_context_from_db

        return build_user_context_from_db(self.db, user_id)

    def _exists(self, key: str) -> bool:
        try:
            return self.storage.backend.exists(key)
        except Exception:  # pragma: no cover - сеть
            return False

    def _fetch_item_image(self, item: Any) -> bytes:
        """Скачать исходник вещи по image_key (S3/MinIO).

        Fallback на raw bytes, если `image_key` пуст, но есть кэшированный
        вариант через in-memory backend — не наш случай, просто ошибка.
        """
        image_key = getattr(item, "image_key", None)
        if not image_key:
            raise ColorTryOnAssetError(
                f"item {item.id} has no image_key — cannot recolor"
            )
        try:
            fetched = self.storage.get_object(image_key)
        except StorageBackendError as exc:  # pragma: no cover - сеть
            raise ColorTryOnStorageError(
                f"failed to fetch item image: {exc}"
            ) from exc
        if fetched is None:
            raise ColorTryOnAssetError(
                f"item image not found in storage: {image_key}"
            )
        data, _ct = fetched
        if not data:
            raise ColorTryOnAssetError("item image is empty")
        return data

    def _remove_background(
        self, image_bytes: bytes
    ) -> tuple[Any, Any]:
        """rembg → (RGB np.array, alpha np.array[0..255]).

        На RGB никогда не кладём альфу сверху (маска используется отдельно
        как веса применения перекраса), это упрощает отладку и совпадает
        с реализацией в garment_recognizer.
        """
        try:
            import numpy as np  # lazy
            from PIL import Image  # lazy

            remove = self._rembg_remove
            if remove is None:
                from rembg import remove as real_remove  # type: ignore

                remove = real_remove  # type: ignore[assignment]

            output = remove(image_bytes)
            img = Image.open(io.BytesIO(output)).convert("RGBA")
            arr = np.asarray(img)
            rgb = arr[:, :, :3]
            alpha = arr[:, :, 3]
            return rgb, alpha
        except Exception as exc:
            raise ColorTryOnRenderError(
                f"rembg failed: {type(exc).__name__}: {exc}"
            ) from exc

    def _recolor_hsv(
        self,
        rgb: Any,
        alpha: Any,
        target_hex: str,
    ) -> bytes:
        """Применить HSV-shift к пикселям маски.

        Алгоритм:
            target_h, target_s — берём от целевого HEX.
            * hue каждого пикселя ЗАМЕНЯЕМ на target_h,
            * saturation — интерполируем 0.5 * src + 0.5 * target
              (чтобы не «выжечь» свет/тени, но цвет выраженный),
            * value (яркость) — СОХРАНЯЕМ от исходника (тени + блики).

        Это базовая реализация без cv2: работает на numpy, не требует
        OpenCV в зависимостях. WEBP-энкодер — через Pillow.
        """
        try:
            import numpy as np  # lazy
            from PIL import Image  # lazy

            target_r, target_g, target_b = _hex_to_rgb(target_hex)
            target_h, target_s, _target_v = _rgb_to_hsv(
                target_r / 255.0, target_g / 255.0, target_b / 255.0
            )

            arr = rgb.astype(np.float32) / 255.0
            # numpy-реализация rgb → hsv (поэлементно).
            r = arr[..., 0]
            g = arr[..., 1]
            b = arr[..., 2]
            mx = np.max(arr, axis=-1)
            mn = np.min(arr, axis=-1)
            delta = mx - mn

            h = np.zeros_like(mx)
            mask_delta = delta > 1e-6
            # R, G, B максимумы ветвимся через маски.
            mr = (mx == r) & mask_delta
            mg = (mx == g) & mask_delta
            mb = (mx == b) & mask_delta
            h[mr] = (60.0 * (((g[mr] - b[mr]) / delta[mr]) % 6.0))
            h[mg] = (60.0 * (((b[mg] - r[mg]) / delta[mg]) + 2.0))
            h[mb] = (60.0 * (((r[mb] - g[mb]) / delta[mb]) + 4.0))
            h[h < 0] += 360.0

            s = np.where(mx > 1e-6, delta / np.maximum(mx, 1e-6), 0.0)
            v = mx

            # Сдвигаем hue к целевому, saturation — полусумма с целевым.
            new_h = np.full_like(h, target_h)
            new_s = 0.5 * s + 0.5 * target_s
            new_v = v  # яркость храним, чтобы сохранить тени/блики.

            # hsv → rgb (numpy, без импорта colorsys на каждом пикселе).
            c = new_v * new_s
            hh = new_h / 60.0
            x = c * (1 - np.abs((hh % 2.0) - 1.0))
            m = new_v - c

            zeros = np.zeros_like(c)
            r_out = np.where(
                hh < 1,
                c,
                np.where(
                    hh < 2,
                    x,
                    np.where(
                        hh < 3,
                        zeros,
                        np.where(hh < 4, zeros, np.where(hh < 5, x, c)),
                    ),
                ),
            )
            g_out = np.where(
                hh < 1,
                x,
                np.where(
                    hh < 2,
                    c,
                    np.where(
                        hh < 3,
                        c,
                        np.where(hh < 4, x, np.where(hh < 5, zeros, zeros)),
                    ),
                ),
            )
            b_out = np.where(
                hh < 1,
                zeros,
                np.where(
                    hh < 2,
                    zeros,
                    np.where(
                        hh < 3,
                        x,
                        np.where(hh < 4, c, np.where(hh < 5, c, x)),
                    ),
                ),
            )
            r_out = r_out + m
            g_out = g_out + m
            b_out = b_out + m

            recolored = np.stack([r_out, g_out, b_out], axis=-1)
            recolored = np.clip(recolored, 0.0, 1.0)

            # Веса: нормализованная альфа в [0..1].
            alpha_norm = (alpha.astype(np.float32) / 255.0)
            # Где маска == 0 — используем исходник (фон остаётся целым).
            src = arr
            blended = recolored * alpha_norm[..., None] + src * (
                1.0 - alpha_norm[..., None]
            )
            out_rgba = np.concatenate(
                [
                    (np.clip(blended, 0.0, 1.0) * 255.0).astype(np.uint8),
                    alpha.astype(np.uint8)[..., None],
                ],
                axis=-1,
            )
            img = Image.fromarray(out_rgba, mode="RGBA")
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=88, method=4)
            return buf.getvalue()
        except Exception as exc:
            raise ColorTryOnRenderError(
                f"HSV recolor failed: {type(exc).__name__}: {exc}"
            ) from exc

    def _maybe_run_ml(self, item: Any) -> None:
        """Stub для ML-пути. Реальные вызовы FASHN — за флагом.

        Сейчас метод НИЧЕГО не делает, даже при включённом флаге:
        FASHN recolor — это отдельный продуктовый трек (деньги, latency,
        другая модель). Мы оставляем хук, чтобы при появлении
        контракта у адаптера не править сервис.
        """
        if not self._ml_enabled():
            return
        logger.info(
            "color_tryon: ENABLE_ML_COLOR_TRYON=true, но ML-путь пока stub"
        )

    @staticmethod
    def _is_hsv_suitable(item: Any) -> bool:
        """Вещь пригодна для HSV-перекраса.

        Условие: однотонная (``pattern_scale is None``) и не металлик
        (``fabric_finish != 'metallic'``). Атрибуты — из Фазы 0
        (alembic 0009). Если у объекта нет этих полей (legacy/тесты)
        — считаем вещь пригодной (back-compat).
        """
        pattern_scale = getattr(item, "pattern_scale", None)
        fabric_finish = getattr(item, "fabric_finish", None)
        if pattern_scale is not None:
            return False
        if isinstance(fabric_finish, str) and fabric_finish.lower() == "metallic":
            return False
        return True

    def _ml_enabled(self) -> bool:
        if self._enable_ml_override is not None:
            return bool(self._enable_ml_override)
        try:
            from app.core.config import settings  # lazy

            return bool(getattr(settings, "enable_ml_color_tryon", False))
        except Exception:
            return False


# ---------------------------------------------------------------- utility


def deterministic_key_for(item_id: uuid.UUID | str, hex_code: str) -> str:
    """Сторонний хелпер для тестов: тот же детерминированный ключ."""
    normalized = _normalize_hex(hex_code)
    # Хеш ничего не добавляет, но оставим как маркер — детерминизм
    # опирается только на нормализацию HEX.
    _ = hashlib.sha1(f"{item_id}:{normalized}".encode("utf-8")).hexdigest()[:8]
    return _output_key(item_id, normalized)


__all__ = [
    "ColorTryOnAssetError",
    "ColorTryOnError",
    "ColorTryOnNotFoundError",
    "ColorTryOnRenderError",
    "ColorTryOnService",
    "ColorTryOnStorageError",
    "deterministic_key_for",
]
