"""Garment attribute extractor — v1-lite + Phase-0 расширение.

Извлекает атрибуты одежды из фото:

**v1 (исходный, стабильный):**
  primary_color  — доминирующий цвет вещи (ближайший именованный кластер)
  print_type     — "solid" / "patterned" (бинарно)

**Phase-0 расширение** (``recognize_extended``), 14 новых атрибутов из
Фазы 0 плана ``plans/2026-04-21-каталог-фич-из-отчёта-типажа.md``:
  fabric_rigidity, fabric_finish, occasion, neckline_type, sleeve_type,
  sleeve_length, pattern_scale, pattern_character, pattern_symmetry,
  detail_scale, structure, cut_lines, shoulder_emphasis, style_tags.

Каждый результат помечается ``_source``:
  "cv"       — извлечено из реальных пикселей
  "default"  — шаг упал, использовано fallback-значение
  None       — эвристика честно не справилась (Phase-0 — атрибут не заполнен)

Принципы:
- Тяжёлые импорты (rembg, cv2, PIL, numpy) ленивые, внутри методов.
- Каждый шаг в try/except — один сбойный атрибут не ломает остальные.
- Предпочтение — честный None, чем фейковое значение
  (design_philosophy: «честные quality downgrades»).
- Детерминизм: никакой случайности без seed. Sub-sampling пикселей
  при необходимости использует фиксированный seed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from app.models.item_attributes import (
    NEW_ATTRIBUTE_NAMES,
    validate_scalar,
    validate_style_tags,
)

logger = logging.getLogger(__name__)

# Фиксированный seed для детерминизма любого sub-sampling-а пикселей.
_DETERMINISTIC_SEED = 42

_RULES_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "config/rules/garment_recognition_rules.yaml"
)

FALLBACK_ATTRIBUTES: dict[str, Any] = {
    "primary_color": "white",
    "print_type": "solid",
    "_color_source": "default",
    "_print_source": "default",
}


def _load_rules() -> dict:
    with _RULES_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("garment_recognition", {})


class GarmentRecognizer:
    """v1-lite garment attribute extractor with per-step fallbacks."""

    def __init__(self, *, rules: dict | None = None) -> None:
        self._rules = rules if rules is not None else _load_rules()

    def recognize(
        self,
        image_bytes: bytes,
        hint_category: str | None = None,  # noqa: ARG002 — reserved for v2
    ) -> dict[str, Any]:
        """Run the v1-lite pipeline on raw image bytes.

        Returns a dict with keys:
          primary_color, print_type, _color_source, _print_source.
        Never raises — all failures return fallback values.
        """
        fg_image, fg_mask = self._remove_background(image_bytes)

        primary_color, color_source = self._extract_primary_color(fg_image, fg_mask)
        print_type, print_source = self._detect_print(fg_image, fg_mask)

        return {
            "primary_color": primary_color,
            "print_type": print_type,
            "_color_source": color_source,
            "_print_source": print_source,
        }

    # ---------------------------------------------------------- step 1: bg removal

    def _remove_background(
        self, image_bytes: bytes
    ) -> tuple[Any, Any]:
        """Remove background via rembg. Returns (rgb_array, alpha_mask).

        Falls back to (decoded_rgb, None) on any failure.
        """
        try:
            from rembg import remove  # lazy import
            from PIL import Image  # lazy import
            import io
            import numpy as np  # lazy import

            output = remove(image_bytes)
            img = Image.open(io.BytesIO(output)).convert("RGBA")
            arr = np.asarray(img)
            rgb = arr[:, :, :3]
            mask = arr[:, :, 3]  # alpha: >0 = foreground
            logger.debug("garment_recognizer: bg_removal OK shape=%s", rgb.shape)
            return rgb, mask
        except Exception as exc:
            logger.warning(
                "garment_recognizer: bg_removal FAILED %s: %s — using raw pixels",
                type(exc).__name__, exc,
            )
            return self._decode_raw(image_bytes)

    def _decode_raw(self, image_bytes: bytes) -> tuple[Any, Any]:
        try:
            from PIL import Image  # lazy import
            import io
            import numpy as np  # lazy import

            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            return np.asarray(img), None
        except Exception as exc:
            logger.warning(
                "garment_recognizer: raw_decode FAILED %s: %s",
                type(exc).__name__, exc,
            )
            return None, None

    # ---------------------------------------------------------- step 2: color

    def _extract_primary_color(
        self, fg_image: Any, fg_mask: Any
    ) -> tuple[str, str]:
        """Return (color_name, source) from mean foreground pixel color."""
        try:
            import numpy as np  # lazy import

            if fg_image is None:
                return FALLBACK_ATTRIBUTES["primary_color"], "default"

            if fg_mask is not None:
                fg_pixels = fg_image[fg_mask > 10].reshape(-1, 3)
            else:
                fg_pixels = fg_image.reshape(-1, 3)

            if len(fg_pixels) < 50:
                return FALLBACK_ATTRIBUTES["primary_color"], "default"

            if len(fg_pixels) > 5000:
                # Детерминистический subsample: тот же seed → тот же ответ
                rng = np.random.default_rng(_DETERMINISTIC_SEED)
                idx = rng.choice(len(fg_pixels), 5000, replace=False)
                fg_pixels = fg_pixels[idx]

            mean_rgb = fg_pixels.mean(axis=0).astype(np.uint8)
            name = self._nearest_color_name(mean_rgb)
            return name, "cv"
        except Exception as exc:
            logger.warning(
                "garment_recognizer: color_extract FAILED %s: %s",
                type(exc).__name__, exc,
            )
            return FALLBACK_ATTRIBUTES["primary_color"], "default"

    def _nearest_color_name(self, rgb: Any) -> str:
        import numpy as np  # lazy import

        clusters = self._rules.get("color_clusters", {})
        best_name = "white"
        best_dist = float("inf")
        for name, hex_list in clusters.items():
            if not hex_list:
                continue
            cluster_rgb = np.array([_hex_to_rgb(h) for h in hex_list]).mean(axis=0)
            dist = float(np.linalg.norm(rgb.astype(float) - cluster_rgb))
            if dist < best_dist:
                best_dist = dist
                best_name = name
        return best_name

    # ---------------------------------------------------------- step 3: print

    def _detect_print(
        self, fg_image: Any, fg_mask: Any
    ) -> tuple[str, str]:
        """Return ("solid"|"patterned", source) from CIE Lab color variance."""
        try:
            import cv2  # lazy import
            import numpy as np  # lazy import

            if fg_image is None:
                return FALLBACK_ATTRIBUTES["print_type"], "default"

            if fg_mask is not None:
                fg_pixels = fg_image[fg_mask > 10].reshape(-1, 3)
            else:
                fg_pixels = fg_image.reshape(-1, 3)

            if len(fg_pixels) < 100:
                return FALLBACK_ATTRIBUTES["print_type"], "default"

            lab = cv2.cvtColor(
                fg_pixels.reshape(-1, 1, 3).astype(np.uint8),
                cv2.COLOR_RGB2LAB,
            ).reshape(-1, 3).astype(float)

            variance = (float(np.std(lab[:, 1])) + float(np.std(lab[:, 2]))) / 2
            threshold = float(self._rules.get("print_variance_threshold", 15.0))
            print_type = "patterned" if variance > threshold else "solid"
            return print_type, "cv"
        except Exception as exc:
            logger.warning(
                "garment_recognizer: print_detect FAILED %s: %s",
                type(exc).__name__, exc,
            )
            return FALLBACK_ATTRIBUTES["print_type"], "default"

    # ================================================================
    # Phase-0: 14 новых атрибутов одежды
    # ================================================================
    #
    # Каждый метод _infer_* возвращает скаляр из whitelist-а
    # app.models.item_attributes или None. Честный None лучше фейка
    # (design_philosophy: честные quality downgrades).
    #
    # Методы НЕ raise — все ошибки логируются и возвращают None.
    # Эвристики простые (MVP) — прокси-сигналы, не ML. Каждая
    # эвристика документирована: какой сигнал, какой диапазон.

    def recognize_extended(
        self,
        image_bytes: bytes,
        hint_category: str | None = None,
    ) -> dict[str, Any]:
        """Полный проход: v1 (primary_color, print_type) + 14 новых атрибутов.

        Возвращает плоский dict вида::

            {
              "primary_color": "navy", "_color_source": "cv",
              "print_type": "patterned", "_print_source": "cv",
              "fabric_rigidity": "medium",        # или None
              "fabric_finish": "matte",           # или None
              ...
              "style_tags": None,                 # эвристики нет — честный None
              "quality": "low",                   # "high"/"medium"/"low" в зависимости
                                                  # от доли заполненных атрибутов
              "_filled_count": 6,                 # сколько из 14 заполнено (для диагностики)
            }

        Quality downgrade-правило:
          * ``high``   — 10+ из 14 заполнены;
          * ``medium`` — 7-9 из 14;
          * ``low``    — 0-6 из 14 (в т.ч. когда CV полностью упал).
        """
        # v1 пайплайн
        v1 = self.recognize(image_bytes, hint_category=hint_category)

        # Повторно считаем fg_image + fg_mask, т.к. метрики Phase-0
        # пересекаются с v1-пайплайном и нам нужен доступ к маске.
        fg_image, fg_mask = self._remove_background(image_bytes)

        # Предрасчёт сигналов, которые переиспользуются несколькими эвристиками.
        signals = self._precompute_signals(fg_image, fg_mask)

        extended: dict[str, Any] = dict(v1)

        # Сырые оценки (до валидации whitelist-ом)
        raw: dict[str, Any] = {
            "fabric_rigidity": self._infer_fabric_rigidity(signals),
            "fabric_finish": self._infer_fabric_finish(signals),
            "occasion": self._infer_occasion(signals, hint_category),
            "neckline_type": None,         # Без MediaPipe на одежде — честный None
            "sleeve_type": None,           # Аналогично
            "sleeve_length": None,         # Аналогично
            "pattern_scale": self._infer_pattern_scale(signals, v1.get("print_type")),
            "pattern_character": self._infer_pattern_character(signals, v1.get("print_type")),
            "pattern_symmetry": self._infer_pattern_symmetry(fg_mask),
            "detail_scale": self._infer_detail_scale(signals),
            "structure": self._infer_structure(signals),
            "cut_lines": self._infer_cut_lines(fg_mask),
            "shoulder_emphasis": None,     # Зависит от neckline/sleeve — Phase-1
            "style_tags": None,            # Высокоуровневый семантический атрибут — Phase-6
        }

        # Валидация whitelist-ом: всё, что не прошло — None.
        filled = 0
        for name in NEW_ATTRIBUTE_NAMES:
            if name == "style_tags":
                value = validate_style_tags(raw.get(name))
            else:
                value = validate_scalar(name, raw.get(name))
            extended[name] = value
            if value is not None:
                filled += 1

        # Честный quality downgrade: считаем долю заполненных.
        if filled >= 10:
            quality = "high"
        elif filled >= 7:
            quality = "medium"
        else:
            quality = "low"

        extended["_filled_count"] = filled
        extended["quality"] = quality

        logger.info(
            "garment_recognizer_ext: filled=%d/14 quality=%s "
            "(None's: %s)",
            filled,
            quality,
            [n for n in NEW_ATTRIBUTE_NAMES if extended.get(n) is None],
        )

        return extended

    # ---------------------------------------------------------- эвристики

    def _precompute_signals(
        self, fg_image: Any, fg_mask: Any
    ) -> dict[str, float | None]:
        """Один проход numpy/cv2 — готовит сигналы для всех эвристик.

        Возвращаемые ключи (все Optional float):
          * ``edge_density``      — доля edge-пикселей к площади маски (Canny).
          * ``contour_smoothness`` — гладкость внешнего контура (inverse of
            perimeter/area ratio — больше = более гладкий контур).
          * ``highlight_ratio``   — доля пикселей с высокой яркостью (>230) в L-канале.
          * ``lightness_std``     — std L-канала (большой = неровный lightness).
          * ``saturation_mean``   — среднее S (HSV).
          * ``ab_variance``       — (std(a) + std(b))/2 в Lab — та же метрика,
            что ``print_type``.
          * ``fg_ratio``          — доля foreground-пикселей (маска).

        Если CV-библиотеки недоступны/упали — вернётся dict со значениями None.
        """
        fallback = {
            "edge_density": None,
            "contour_smoothness": None,
            "highlight_ratio": None,
            "lightness_std": None,
            "saturation_mean": None,
            "ab_variance": None,
            "fg_ratio": None,
        }

        try:
            import cv2
            import numpy as np

            if fg_image is None:
                return fallback

            img = np.asarray(fg_image)
            h, w = img.shape[:2]
            if h < 8 or w < 8:
                return fallback

            # Foreground-маска: булевская (True = foreground)
            if fg_mask is not None:
                mask_bool = np.asarray(fg_mask) > 10
            else:
                mask_bool = np.ones((h, w), dtype=bool)

            fg_area = int(mask_bool.sum())
            fg_ratio = fg_area / float(h * w) if h * w > 0 else 0.0

            if fg_area < 100:
                return fallback

            # Edge density по Canny: грубый прокси на «сколько деталей в вещи».
            grey = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            edges = cv2.Canny(grey, 50, 150)
            # Считаем edges только внутри маски
            edges_in_fg = np.logical_and(edges > 0, mask_bool)
            edge_density = float(edges_in_fg.sum()) / float(fg_area)

            # Lab: для highlights и для вариации a/b (текстурность)
            lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
            L = lab[:, :, 0].astype(float)
            a = lab[:, :, 1].astype(float)
            b = lab[:, :, 2].astype(float)

            L_fg = L[mask_bool]
            a_fg = a[mask_bool]
            b_fg = b[mask_bool]

            highlight_ratio = float((L_fg > 230).mean())
            lightness_std = float(L_fg.std())
            ab_variance = float((a_fg.std() + b_fg.std()) / 2.0)

            # HSV: saturation (яркость цвета)
            hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
            S = hsv[:, :, 1].astype(float)
            saturation_mean = float(S[mask_bool].mean())

            # Contour smoothness: perimeter-to-sqrt(area) ratio. Круг ~ 3.54,
            # изрезанный контур — много больше. Инвертируем и нормализуем.
            mask_u8 = (mask_bool.astype(np.uint8)) * 255
            contours, _ = cv2.findContours(
                mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
            )
            contour_smoothness: float | None
            if contours:
                largest = max(contours, key=cv2.contourArea)
                perimeter = cv2.arcLength(largest, closed=True)
                area = cv2.contourArea(largest)
                if area > 1 and perimeter > 0:
                    # Нормализованный ratio: 1.0 для круга, >1 для изрезанного
                    ratio = perimeter / (2.0 * np.sqrt(np.pi * area))
                    # smoothness ∈ [0, 1]: высокое значение = гладкий
                    contour_smoothness = float(max(0.0, min(1.0, 1.0 / ratio)))
                else:
                    contour_smoothness = None
            else:
                contour_smoothness = None

            return {
                "edge_density": edge_density,
                "contour_smoothness": contour_smoothness,
                "highlight_ratio": highlight_ratio,
                "lightness_std": lightness_std,
                "saturation_mean": saturation_mean,
                "ab_variance": ab_variance,
                "fg_ratio": fg_ratio,
            }
        except Exception as exc:
            logger.warning(
                "garment_recognizer_ext: precompute_signals FAILED %s: %s",
                type(exc).__name__, exc,
            )
            return fallback

    # ---- fabric_rigidity ----------------------------------------------------
    def _infer_fabric_rigidity(self, signals: dict) -> str | None:
        """Жёсткость ткани — прокси через гладкость контура.

        * Гладкий, прямой контур (smoothness high) → rigid (пальто, деним).
        * Много изгибов контура (smoothness low) → soft (трикотаж, шифон).
        * Середина → medium.
        """
        smoothness = signals.get("contour_smoothness")
        if smoothness is None:
            return None
        if smoothness >= 0.55:
            return "rigid"
        if smoothness >= 0.35:
            return "medium"
        return "soft"

    # ---- fabric_finish ------------------------------------------------------
    def _infer_fabric_finish(self, signals: dict) -> str | None:
        """Отделка ткани: matte/glossy/metallic.

        * highlight_ratio > 0.08 + высокая saturation → metallic
          (много ярких бликов вместе с насыщенным цветом).
        * highlight_ratio > 0.03 → glossy (атлас, шёлк).
        * lightness_std < 20 и highlight_ratio < 0.01 → matte.

        sequin/brocade не детектируем — возвращаем None.
        """
        highlight = signals.get("highlight_ratio")
        lightness_std = signals.get("lightness_std")
        saturation = signals.get("saturation_mean")
        if highlight is None or lightness_std is None:
            return None
        if highlight > 0.08 and saturation is not None and saturation > 120:
            return "metallic"
        if highlight > 0.03:
            return "glossy"
        if lightness_std < 20.0 and highlight < 0.01:
            return "matte"
        # Середина — не уверены, честный None
        return None

    # ---- occasion -----------------------------------------------------------
    def _infer_occasion(
        self, signals: dict, hint_category: str | None
    ) -> str | None:
        """Повод: day/work/smart_casual/evening/sport.

        Эвристика очень грубая — без семантики категории это угадайка.
        Даём только явные сигналы:

        * category hint «sport/activewear» → "sport".
        * Очень низкое (>90%) highlight + высокая saturation + низкий
          lightness (тёмное) → ``evening`` (маленькое чёрное/металлик).

        Остальное → None, заполнится ручным вводом.
        """
        if hint_category:
            cat = hint_category.lower()
            if cat in {"sport", "sportswear", "activewear"}:
                return "sport"

        highlight = signals.get("highlight_ratio")
        saturation = signals.get("saturation_mean")
        lightness_std = signals.get("lightness_std")
        # evening: глянец + высокая насыщенность
        if highlight is not None and saturation is not None:
            if highlight > 0.06 and saturation > 100:
                return "evening"
            # Чёрный матовый «пиджак» (низкий lightness_std, matte) —
            # вероятнее work/smart_casual, но это чистая угадайка.
            # Честно возвращаем None.
        _ = lightness_std
        return None

    # ---- pattern_scale ------------------------------------------------------
    def _infer_pattern_scale(
        self, signals: dict, print_type: str | None
    ) -> str | None:
        """Масштаб принта: small/medium/large.

        Актуально только если ``print_type == "patterned"``.
        Чем выше edge_density — тем мельче и чаще узор.
        """
        if print_type != "patterned":
            return None
        edge = signals.get("edge_density")
        if edge is None:
            return None
        if edge >= 0.08:
            return "small"
        if edge >= 0.03:
            return "medium"
        return "large"

    # ---- pattern_character --------------------------------------------------
    def _infer_pattern_character(
        self, signals: dict, print_type: str | None
    ) -> str | None:
        """Характер принта — простой сплошной эвристики нет.

        Без отдельного классификатора (TF/PyTorch) честно отдаём None.
        Оставлено для будущего CV-расширения.
        """
        _ = signals, print_type
        return None

    # ---- pattern_symmetry ---------------------------------------------------
    def _infer_pattern_symmetry(self, fg_mask: Any) -> str | None:
        """Симметрия: сравниваем левую и правую половины маски.

        * Высокая корреляция (IoU) → ``symmetric``.
        * Низкая → ``asymmetric``.
        """
        try:
            import numpy as np

            if fg_mask is None:
                return None
            mask = np.asarray(fg_mask) > 10
            h, w = mask.shape
            if w < 8 or h < 8:
                return None
            half = w // 2
            left = mask[:, :half]
            right_flipped = np.fliplr(mask[:, w - half:])
            # Обе половинки одинаковой ширины
            if left.shape != right_flipped.shape:
                return None
            intersection = np.logical_and(left, right_flipped).sum()
            union = np.logical_or(left, right_flipped).sum()
            if union == 0:
                return None
            iou = float(intersection) / float(union)
            return "symmetric" if iou >= 0.75 else "asymmetric"
        except Exception as exc:
            logger.warning(
                "garment_recognizer_ext: pattern_symmetry FAILED %s: %s",
                type(exc).__name__, exc,
            )
            return None

    # ---- detail_scale -------------------------------------------------------
    def _infer_detail_scale(self, signals: dict) -> str | None:
        """Размер деталей — прокси через edge_density (фурнитура, швы).

        Разбиение чуть другое, чем у pattern_scale: чем чаще edges
        тем мельче/многочисленнее детали. Возвращаем отдельно, т.к.
        detail_scale применим и к solid-вещам (фурнитура, застёжка).
        """
        edge = signals.get("edge_density")
        if edge is None:
            return None
        if edge >= 0.07:
            return "small"
        if edge >= 0.025:
            return "medium"
        return "large"

    # ---- structure ----------------------------------------------------------
    def _infer_structure(self, signals: dict) -> str | None:
        """Структурность: structured / semi_structured / unstructured.

        Комбинация:
          * высокая contour_smoothness ⇒ вещь держит форму → structured;
          * низкая ⇒ вещь «текучая» → unstructured;
          * середина ⇒ semi_structured.
        """
        smoothness = signals.get("contour_smoothness")
        if smoothness is None:
            return None
        if smoothness >= 0.55:
            return "structured"
        if smoothness >= 0.35:
            return "semi_structured"
        return "unstructured"

    # ---- cut_lines ----------------------------------------------------------
    def _infer_cut_lines(self, fg_mask: Any) -> str | None:
        """Линии кроя: angular / straight / soft_flowing.

        Применяем HoughLinesP по внешнему контуру:
          * Много длинных прямых линий под углами близкими к 90/0° → straight.
          * Прямые под острыми разными углами (много наклонов) → angular.
          * Мало длинных прямых → soft_flowing.
        """
        try:
            import cv2
            import numpy as np

            if fg_mask is None:
                return None
            mask = (np.asarray(fg_mask) > 10).astype(np.uint8) * 255
            h, w = mask.shape
            if h < 16 or w < 16:
                return None
            # Контур маски
            edges = cv2.Canny(mask, 50, 150)
            # HoughLinesP: короткие отрезки → много «кусочков» контура
            min_line = max(10, int(min(h, w) * 0.1))
            lines = cv2.HoughLinesP(
                edges,
                rho=1,
                theta=np.pi / 180,
                threshold=50,
                minLineLength=min_line,
                maxLineGap=5,
            )
            if lines is None or len(lines) == 0:
                # Нет длинных прямых — контур плавный
                return "soft_flowing"

            # Углы в градусах
            angles = []
            for ln in lines:
                x1, y1, x2, y2 = ln[0]
                dx = x2 - x1
                dy = y2 - y1
                angle = float(np.degrees(np.arctan2(dy, dx)))
                # Нормализуем в [0, 180)
                angles.append(angle % 180.0)

            n_lines = len(angles)
            angles_np = np.asarray(angles)

            # Доля линий близких к 0° (горизонталь) или 90° (вертикаль)
            near_axis = (
                (np.abs(angles_np - 0) < 10)
                | (np.abs(angles_np - 90) < 10)
                | (np.abs(angles_np - 180) < 10)
            ).sum()
            axis_ratio = float(near_axis) / float(n_lines)

            if n_lines < 3:
                return "soft_flowing"
            if axis_ratio >= 0.7:
                return "straight"
            if axis_ratio < 0.3:
                return "angular"
            # Смешанный профиль — скорее straight, чем angular
            return "straight"
        except Exception as exc:
            logger.warning(
                "garment_recognizer_ext: cut_lines FAILED %s: %s",
                type(exc).__name__, exc,
            )
            return None


# ---------------------------------------------------------- helpers

def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ---------------------------------------------------------- public API

def recognize_garment(
    image_bytes: bytes,
    hint_category: str | None = None,
    *,
    rules: dict | None = None,
) -> dict[str, Any]:
    """Module-level entry point. Never raises — all failures use fallbacks."""
    try:
        return GarmentRecognizer(rules=rules).recognize(
            image_bytes, hint_category=hint_category
        )
    except Exception as exc:
        logger.error(
            "garment_recognizer: critical failure %s: %s",
            type(exc).__name__, exc,
        )
        return dict(FALLBACK_ATTRIBUTES)


def recognize_garment_extended(
    image_bytes: bytes,
    hint_category: str | None = None,
    *,
    rules: dict | None = None,
) -> dict[str, Any]:
    """Phase-0 entry point — v1 + 14 новых атрибутов.

    Не бросает исключений: при критической ошибке возвращает
    fallback-dict c v1-полями + все 14 новых = None, quality=low.
    """
    try:
        return GarmentRecognizer(rules=rules).recognize_extended(
            image_bytes, hint_category=hint_category
        )
    except Exception as exc:
        logger.error(
            "garment_recognizer: critical failure ext %s: %s",
            type(exc).__name__, exc,
        )
        fallback = dict(FALLBACK_ATTRIBUTES)
        for name in NEW_ATTRIBUTE_NAMES:
            fallback[name] = None
        fallback["_filled_count"] = 0
        fallback["quality"] = "low"
        return fallback


__all__ = [
    "FALLBACK_ATTRIBUTES",
    "GarmentRecognizer",
    "recognize_garment",
    "recognize_garment_extended",
]
