"""Wardrobe category classifier — pluggable backends.

Two implementations behind one Protocol:

* :class:`OpenAICategoryClassifier` — GPT-5 nano vision via the OpenAI
  Chat Completions API. Uses ``httpx`` directly so we control the URL,
  auth header, and request body explicitly. JSON output is forced via
  ``response_format: {"type": "json_object"}``. Bounded by an in-memory
  circuit breaker so a failing upstream doesn't cascade into 30s upload
  timeouts for every user.
* :class:`HeuristicCategoryClassifier` — rule-based on the
  ``recognize_garment`` Phase-0 attributes (occasion, structure,
  cut_lines, ...). Used when the OpenAI key is missing or the breaker
  is open. Honest 50-70% accuracy — better than the old "top" hardcode
  but not great.

The factory :func:`get_category_classifier` picks one based on
``settings.use_cv_category_classifier`` and the configured provider.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from app.core.config import Settings
from app.models.item_attributes import (
    ATTRIBUTE_WHITELISTS,
    NEW_ATTRIBUTE_NAMES,
    STYLE_TAG_VALUES,
    validate_scalar,
    validate_style_tags,
)
from app.services.categories import WARDROBE_CATEGORIES

logger = logging.getLogger(__name__)


# Cross-worker observability log for the classifier — see
# ``app/api/routes/cv_classifier_observability.py`` for the read API.
# Uvicorn runs several workers (separate Python processes) so an
# in-process deque would fragment the log; we use a JSONL file in /tmp
# with ``fcntl.flock`` for write coordination. Bounded to 100 entries.
import os as _os
from pathlib import Path as _Path

try:
    import fcntl as _fcntl  # POSIX-only; on Windows tests we no-op the lock
except ImportError:  # pragma: no cover
    _fcntl = None

_ATTEMPTS_PATH = _Path(_os.environ.get("CV_CLASSIFIER_LOG", "/tmp/cv_classifier_attempts.jsonl"))
_ATTEMPTS_MAX = 100


def _record_attempt(entry: dict) -> None:
    """Append one attempt to the shared JSONL log, then trim to MAX."""
    line = json.dumps(entry, default=str)
    try:
        _ATTEMPTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_ATTEMPTS_PATH, "a+", encoding="utf-8") as f:
            if _fcntl is not None:
                _fcntl.flock(f.fileno(), _fcntl.LOCK_EX)
            try:
                f.write(line + "\n")
                f.flush()
                f.seek(0)
                lines = [ln for ln in f.read().splitlines() if ln.strip()]
                if len(lines) > _ATTEMPTS_MAX:
                    keep = lines[-_ATTEMPTS_MAX:]
                    f.seek(0)
                    f.truncate()
                    f.write("\n".join(keep) + "\n")
            finally:
                if _fcntl is not None:
                    _fcntl.flock(f.fileno(), _fcntl.LOCK_UN)
    except Exception:  # noqa: BLE001
        logger.exception("category_classifier: failed to record attempt")


def get_recent_attempts() -> list[dict]:
    """Snapshot of the JSONL log for the diagnostic endpoint."""
    if not _ATTEMPTS_PATH.exists():
        return []
    try:
        with open(_ATTEMPTS_PATH, "r", encoding="utf-8") as f:
            if _fcntl is not None:
                _fcntl.flock(f.fileno(), _fcntl.LOCK_SH)
            try:
                lines = f.read().splitlines()
            finally:
                if _fcntl is not None:
                    _fcntl.flock(f.fileno(), _fcntl.LOCK_UN)
        out = []
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return out
    except Exception:  # noqa: BLE001
        logger.exception("category_classifier: failed to read attempts log")
        return []


CategorySource = Literal["cloud_llm", "heuristic", "fallback", "user"]


@dataclass(frozen=True)
class CategoryPrediction:
    category: str
    confidence: float
    source: CategorySource
    reasoning: str | None = None


class CategoryClassifier(Protocol):
    def classify(
        self,
        image_bytes: bytes,
        *,
        attrs_hint: dict[str, Any] | None = None,
        media_type: str = "image/jpeg",
    ) -> CategoryPrediction: ...


# ---------------------------------------------------------------------------
# OpenAI Chat Completions API (gpt-5-nano with vision)
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL = "https://api.openai.com"
_DEFAULT_MODEL = "gpt-5-nano"
# nano typically responds in 2-4s on `detail:"low"`. 30s is a generous
# ceiling that absorbs cold starts and one transient retry without the
# user-facing upload (frontend timeout 120s) ever seeing a hang.
_DEFAULT_TIMEOUT_S = 30.0
_BREAKER_FAIL_THRESHOLD = 3
_BREAKER_COOLDOWN_S = 300.0  # 5 minutes
# Single retry on transient (network/timeout) errors before giving up
# and letting the wrapper fall through to heuristic.
_TRANSIENT_RETRIES = 1

# Single-step downscale before encoding. With ``detail:"low"`` OpenAI
# resizes to 512×512 on its side and bills a fixed 85 input tokens
# regardless of source resolution, so anything above ~1024px is wasted
# bandwidth. Phone uploads are 1-3MB which makes the data-URL slow to
# transmit; 1024/85 cuts that to ~80-150KB without losing classification
# signal.
_CLASSIFIER_MAX_DIM = 1024
_CLASSIFIER_JPEG_QUALITY = 85


_CATEGORIES_LIST = ", ".join(WARDROBE_CATEGORIES)


# Per-category definitions matter: without them the model routinely
# calls a t-shirt photographed flat on a white background "outerwear"
# because the silhouette looks elongated when the garment is laid out
# without being worn. Explicit definitions + the "photographed flat"
# hint cut the false-positive rate sharply in our prod tests.
_SYSTEM_PROMPT = f"""You classify a photo of a single clothing item into exactly ONE of these 15 categories:

- blouses: t-shirts, polos, shirts, button-ups, blouses, tank tops, camisoles, basic tops with sleeves of any length. The default for any short or long-sleeved upper-body garment that is NOT a sweater, jacket, or coat.
- sweaters: knitwear — pullovers, cardigans, hoodies, sweatshirts, turtlenecks. Visibly knitted or fleecy texture.
- dresses: one-piece garments covering torso and legs/hips together (sundresses, midi/maxi dresses, shirt dresses, sheath dresses).
- jackets: structured upper-body outerwear that is hip-length or shorter — blazers, suit jackets, denim jackets, leather/biker jackets, bomber jackets.
- outerwear: coats, parkas, trench coats, puffer jackets, raincoats, capes — long enough to layer over other clothes (typically below the hip).
- pants: trousers, jeans, leggings, sweatpants, shorts. Two-leg lower-body garments.
- skirts: skirts of any length (mini, midi, maxi, A-line, pencil).
- shoes: any footwear — sneakers, boots, heels, flats, sandals, loafers.
- hosiery: tights, stockings, socks.
- bags: handbags, totes, backpacks, clutches, crossbody bags.
- belts: standalone belts (not the belt on a dress/coat).
- eyewear: sunglasses, optical glasses.
- headwear: hats, caps, beanies, scarves worn on the head.
- jewelry: necklaces, earrings, rings, bracelets, watches.
- swimwear: swimsuits, bikinis, swim trunks, beachwear cover-ups.

Important guidance for photos taken FLAT on a plain background (without a person wearing the item):
- Garment silhouette is distorted because there's no body inside; do not assume "long" garments are coats.
- Look for sleeve length, fabric texture, neckline, and collar details rather than overall length.
- A short-sleeved cotton top photographed laid out flat on white background is BLOUSES, not outerwear.
- A heavy coat will show thick fabric, lapels, lining, buttons; a t-shirt will show thin jersey fabric and a simple round/v-neckline.

Reply with a single JSON object — no markdown, no commentary:
{{"category": "<one of the 15 above>", "confidence": <0..1>, "reasoning": "<1 short sentence with the visual evidence>"}}
"""


# Greedy match — covers ```json {...} ```, ``` {...} ```, plain {...},
# and stray prose around the object.
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}")


class _CircuitBreaker:
    """Tiny thread-safe circuit breaker for the cloud classifier.

    Three consecutive failures trip it; while open the classifier raises
    immediately so the route can fall through to heuristic. The breaker
    closes again after the cooldown.
    """

    def __init__(
        self,
        *,
        fail_threshold: int = _BREAKER_FAIL_THRESHOLD,
        cooldown_s: float = _BREAKER_COOLDOWN_S,
    ) -> None:
        self._fail_threshold = fail_threshold
        self._cooldown_s = cooldown_s
        self._lock = threading.Lock()
        self._consecutive_fails = 0
        self._opened_at: float | None = None

    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if time.monotonic() - self._opened_at >= self._cooldown_s:
                self._consecutive_fails = 0
                self._opened_at = None
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_fails = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_fails += 1
            if self._consecutive_fails >= self._fail_threshold:
                self._opened_at = time.monotonic()


class OpenAICategoryClassifier:
    """OpenAI vision classifier over the Chat Completions API.

    Defaults target ``api.openai.com`` directly. ``base_url`` exists so
    a future Azure/proxy migration doesn't need code edits — just change
    the URL.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        model: str = _DEFAULT_MODEL,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        proxy: str | None = None,
        client: httpx.Client | None = None,
        breaker: _CircuitBreaker | None = None,
        fallback: CategoryClassifier | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s
        self._proxy = proxy or None
        self._client = client  # injected for tests; lazy-built otherwise
        self._breaker = breaker or _CircuitBreaker()
        self._fallback = fallback or HeuristicCategoryClassifier()

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        self._client = httpx.Client(
            timeout=self._timeout_s,
            proxy=self._proxy,
        )
        return self._client

    def classify(
        self,
        image_bytes: bytes,
        *,
        attrs_hint: dict[str, Any] | None = None,
        media_type: str = "image/jpeg",
    ) -> CategoryPrediction:
        log_entry: dict[str, Any] = {
            "ts": time.time(),
            "image_bytes": len(image_bytes),
            "media_type": media_type,
            "breaker_open": self._breaker.is_open(),
            "attempts": 0,
        }

        if self._breaker.is_open():
            logger.warning("category_classifier: breaker open, using heuristic")
            pred = self._fallback.classify(
                image_bytes, attrs_hint=attrs_hint, media_type=media_type
            )
            log_entry["outcome"] = "breaker_open_fallback"
            log_entry["prediction"] = _pred_dict(pred)
            _record_attempt(log_entry)
            return pred

        last_exc: Exception | None = None
        for attempt_idx in range(_TRANSIENT_RETRIES + 1):
            log_entry["attempts"] = attempt_idx + 1
            try:
                pred = self._call_openai(image_bytes, attrs_hint, media_type, log_entry)
                log_entry["outcome"] = "cloud_ok"
                log_entry["prediction"] = _pred_dict(pred)
                _record_attempt(log_entry)
                return pred
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                # Transient — proxy queue spike or flaky network. Retry
                # without burning the breaker so a single slow call
                # doesn't trip the 3-strike cooldown.
                last_exc = exc
                logger.warning(
                    "category_classifier: transient %s on attempt %d/%d",
                    type(exc).__name__,
                    attempt_idx + 1,
                    _TRANSIENT_RETRIES + 1,
                )
                continue
            except Exception as exc:  # noqa: BLE001 — anything else is non-retryable
                self._breaker.record_failure()
                logger.warning(
                    "category_classifier: openai call failed (%s: %s), falling back to heuristic",
                    type(exc).__name__,
                    exc,
                )
                pred = self._fallback.classify(
                    image_bytes, attrs_hint=attrs_hint, media_type=media_type
                )
                log_entry["outcome"] = "cloud_exception_then_fallback"
                log_entry["exception_type"] = type(exc).__name__
                log_entry["exception_message"] = str(exc)[:500]
                log_entry["prediction"] = _pred_dict(pred)
                _record_attempt(log_entry)
                return pred

        # Exhausted retries on transient errors — count as one breaker
        # strike and fall back to heuristic.
        self._breaker.record_failure()
        logger.warning(
            "category_classifier: exhausted %d transient retries (last=%s), falling back",
            _TRANSIENT_RETRIES + 1,
            type(last_exc).__name__ if last_exc else "?",
        )
        pred = self._fallback.classify(
            image_bytes, attrs_hint=attrs_hint, media_type=media_type
        )
        log_entry["outcome"] = "transient_retries_exhausted_fallback"
        log_entry["exception_type"] = type(last_exc).__name__ if last_exc else None
        log_entry["exception_message"] = str(last_exc)[:500] if last_exc else None
        log_entry["prediction"] = _pred_dict(pred)
        _record_attempt(log_entry)
        return pred

    def _call_openai(
        self,
        image_bytes: bytes,
        attrs_hint: dict[str, Any] | None,
        media_type: str,
        log_entry: dict[str, Any] | None = None,
    ) -> CategoryPrediction:
        encoded_bytes, encoded_media_type = _shrink_for_upload(image_bytes, media_type)
        if log_entry is not None:
            log_entry["encoded_bytes"] = len(encoded_bytes)
            log_entry["encoded_media_type"] = encoded_media_type
        b64 = base64.standard_b64encode(encoded_bytes).decode("ascii")
        data_url = f"data:{encoded_media_type};base64,{b64}"

        user_text_parts = [
            "Classify the garment in this photo into one of the 15 supported categories."
        ]
        hint_summary = _summarize_hint(attrs_hint)
        if hint_summary:
            user_text_parts.append(f"Pre-extracted hints (may be useful): {hint_summary}")

        body = {
            "model": self._model,
            "max_completion_tokens": 200,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "\n".join(user_text_parts) + "\n\nReply with the JSON object only.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url, "detail": "low"},
                        },
                    ],
                },
            ],
        }

        client = self._get_client()
        t0 = time.perf_counter()
        response = client.post(
            f"{self._base_url}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            json=body,
            timeout=self._timeout_s,
        )
        if log_entry is not None:
            log_entry["http_status"] = response.status_code
            log_entry["latency_s"] = round(time.perf_counter() - t0, 2)
        response.raise_for_status()
        data = response.json()
        if log_entry is not None and isinstance(data, dict):
            choices = data.get("choices") or []
            if choices and isinstance(choices[0], dict):
                log_entry["finish_reason"] = choices[0].get("finish_reason")
            usage = data.get("usage") or {}
            log_entry["completion_tokens"] = usage.get("completion_tokens")
            log_entry["prompt_tokens"] = usage.get("prompt_tokens")

        text = _extract_openai_text(data)
        if log_entry is not None:
            log_entry["text_block"] = text
        if not text:
            raise ValueError("openai response had no text content")

        # response_format=json_object guarantees a parseable JSON when
        # the model behaves, but we keep ``_parse_json_object`` as a
        # safety net for the rare case the model returns prose anyway.
        payload = _parse_json_object(text)
        if log_entry is not None:
            log_entry["parsed_json"] = payload
        if payload is None:
            raise ValueError(f"openai text was not parseable JSON: {text!r}")

        category = payload.get("category")
        if not isinstance(category, str) or category not in WARDROBE_CATEGORIES:
            raise ValueError(f"openai returned unknown category: {category!r}")

        confidence = payload.get("confidence")
        if not isinstance(confidence, (int, float)):
            raise ValueError(f"openai confidence missing or not numeric: {confidence!r}")
        confidence = float(confidence)

        reasoning = payload.get("reasoning")
        if reasoning is not None and not isinstance(reasoning, str):
            reasoning = None

        self._breaker.record_success()
        return CategoryPrediction(
            category=category,
            confidence=max(0.0, min(1.0, confidence)),
            source="cloud_llm",
            reasoning=reasoning,
        )


# ---------------------------------------------------------------------------
# OpenAIVisionAnalyzer — расширенный vision-вызов: за один запрос возвращает
# категорию, короткое имя, primary_color и 14 структурных атрибутов Phase 0.
# Используется при включённом флаге ``settings.enable_vision_analysis``.
# Делит инфру с ``OpenAICategoryClassifier``: тот же httpx-клиент,
# circuit breaker, retry-policy, downscale.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisionAnalysisResult:
    """Полный результат vision-анализа одной фотки.

    ``attrs`` хранит 14 атрибутов Phase 0 — по ключам из
    ``NEW_ATTRIBUTE_NAMES``. Невозможно определённые атрибуты — None
    (никаких guess'ов из system-prompt). ``style_tags`` — список или None.
    """

    category: str
    confidence: float
    name: str | None
    primary_color: str | None
    attrs: dict[str, Any]
    source: CategorySource = "cloud_llm"
    reasoning: str | None = None


# Лимит на длину `name` — короткое русское описание для UI-карточки. Если
# модель отдала слишком длинное — урезаем по слову.
_NAME_MAX_LEN = 60


def _build_vision_prompt() -> str:
    """Собрать system-prompt с whitelist'ами всех 14 атрибутов.

    Whitelist'ы читаются из ``app.models.item_attributes`` — единственного
    источника истины. Если завтра туда добавится новое значение — промпт
    автоматически расскажет о нём модели.
    """
    lines: list[str] = [_SYSTEM_PROMPT.rstrip()]
    lines.append("")
    lines.append(
        "Дополнительно к категории и confidence верни 14 структурных "
        "атрибутов одежды и короткое русское название. Если атрибут "
        "не виден на фото или сомневаешься — возвращай null. "
        "Никаких догадок не делай — лучше null, чем неверное значение."
    )
    lines.append("")
    lines.append(f'name: краткое русское название вещи (до {_NAME_MAX_LEN} символов), '
                 'например "белая блузка с пышными рукавами".')
    lines.append("primary_color: одно англ. слово из палитры "
                 "(white, black, navy, beige, ivory, gray, brown, "
                 "burgundy, red, pink, coral, orange, yellow, olive, "
                 "green, mint, teal, blue, sky_blue, lavender, purple) "
                 "или null.")
    lines.append("")
    lines.append("Атрибуты (whitelist значений):")
    for name in NEW_ATTRIBUTE_NAMES:
        whitelist = ATTRIBUTE_WHITELISTS.get(name) or frozenset()
        values = sorted(whitelist)
        lines.append(f"- {name}: {', '.join(values) or '(no values)'}")
    lines.append("")
    lines.append("Reply with a single JSON object — no markdown, no commentary:")
    lines.append('{"category":"<one of the 15 above>","confidence":<0..1>,'
                 '"name":"<short ru name>","primary_color":"<color or null>",'
                 '"attrs":{"fabric_rigidity":<value or null>,'
                 '"fabric_finish":<value or null>,"occasion":<value or null>,'
                 '"neckline_type":<value or null>,"sleeve_type":<value or null>,'
                 '"sleeve_length":<value or null>,"pattern_scale":<value or null>,'
                 '"pattern_character":<value or null>,'
                 '"pattern_symmetry":<value or null>,'
                 '"detail_scale":<value or null>,"structure":<value or null>,'
                 '"cut_lines":<value or null>,"shoulder_emphasis":<value or null>,'
                 '"style_tags":[...] or null},'
                 '"reasoning":"<1 short sentence>"}')
    return "\n".join(lines)


_VISION_SYSTEM_PROMPT = _build_vision_prompt()


def _coerce_name(value: Any) -> str | None:
    """Очистка короткого имени: trim, обрезание до _NAME_MAX_LEN."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) <= _NAME_MAX_LEN:
        return cleaned
    # Урезаем по последнему пробелу до лимита, чтобы не рвать слова.
    truncated = cleaned[:_NAME_MAX_LEN].rsplit(" ", 1)[0]
    return truncated or cleaned[:_NAME_MAX_LEN]


def _coerce_primary_color(value: Any) -> str | None:
    """Простая нормализация имени цвета — lowercase + строка."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def _coerce_vision_attrs(raw: Any) -> dict[str, Any]:
    """Прогнать сырые attrs через whitelist'ы из ``item_attributes``.

    Возвращает плоский dict с теми же 14 ключами, что в ``NEW_ATTRIBUTE_NAMES``.
    Каждое скалярное значение либо валидное (in whitelist), либо None.
    ``style_tags`` — отфильтрованный список или None.
    """
    out: dict[str, Any] = {name: None for name in NEW_ATTRIBUTE_NAMES}
    if not isinstance(raw, dict):
        return out
    for name in NEW_ATTRIBUTE_NAMES:
        value = raw.get(name)
        if name == "style_tags":
            if isinstance(value, list):
                out[name] = validate_style_tags([v for v in value if isinstance(v, str)])
            else:
                out[name] = None
            continue
        if isinstance(value, str):
            out[name] = validate_scalar(name, value)
        else:
            out[name] = None
    return out


class OpenAIVisionAnalyzer:
    """Расширенный vision-анализатор: один запрос → category + name + attrs.

    Делит инфру с ``OpenAICategoryClassifier`` (единый httpx-клиент,
    breaker, retry, downscale). Если анализ упал по сети/таймауту — поднимает
    исключение, вызывающий код откатывается на эвристики ``recognize_extended()``.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        model: str = _DEFAULT_MODEL,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        proxy: str | None = None,
        client: httpx.Client | None = None,
        breaker: _CircuitBreaker | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s
        self._proxy = proxy or None
        self._client = client
        self._breaker = breaker or _CircuitBreaker()

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        self._client = httpx.Client(
            timeout=self._timeout_s,
            proxy=self._proxy,
        )
        return self._client

    def analyze(
        self,
        image_bytes: bytes,
        *,
        media_type: str = "image/jpeg",
    ) -> VisionAnalysisResult:
        log_entry: dict[str, Any] = {
            "ts": time.time(),
            "image_bytes": len(image_bytes),
            "media_type": media_type,
            "breaker_open": self._breaker.is_open(),
            "attempts": 0,
            "kind": "vision_analysis",
        }

        if self._breaker.is_open():
            log_entry["outcome"] = "breaker_open"
            _record_attempt(log_entry)
            raise RuntimeError("vision_analyzer: breaker open")

        last_exc: Exception | None = None
        for attempt_idx in range(_TRANSIENT_RETRIES + 1):
            log_entry["attempts"] = attempt_idx + 1
            try:
                result = self._call_openai(image_bytes, media_type, log_entry)
                log_entry["outcome"] = "cloud_ok"
                log_entry["prediction"] = {
                    "category": result.category,
                    "confidence": result.confidence,
                    "name": result.name,
                    "primary_color": result.primary_color,
                }
                _record_attempt(log_entry)
                self._breaker.record_success()
                return result
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                logger.warning(
                    "vision_analyzer: transient %s on attempt %d/%d",
                    type(exc).__name__,
                    attempt_idx + 1,
                    _TRANSIENT_RETRIES + 1,
                )
                continue
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "vision_analyzer: openai call failed (%s: %s)",
                    type(exc).__name__,
                    exc,
                )
                break

        self._breaker.record_failure()
        log_entry["outcome"] = "fallback_after_failure"
        log_entry["error"] = repr(last_exc) if last_exc else None
        _record_attempt(log_entry)
        raise RuntimeError(
            f"vision_analyzer: exhausted retries ({last_exc!r})"
        ) from last_exc

    def _call_openai(
        self,
        image_bytes: bytes,
        media_type: str,
        log_entry: dict[str, Any],
    ) -> VisionAnalysisResult:
        shrunk_bytes, shrunk_type = _shrink_for_upload(image_bytes, media_type)
        log_entry["shrunk_bytes"] = len(shrunk_bytes)
        b64 = base64.b64encode(shrunk_bytes).decode("ascii")
        data_url = f"data:{shrunk_type};base64,{b64}"

        body = {
            "model": self._model,
            "max_completion_tokens": 600,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _VISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Analyze the garment in this photo and reply "
                                "with the JSON object only."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url, "detail": "low"},
                        },
                    ],
                },
            ],
        }

        client = self._get_client()
        t0 = time.perf_counter()
        response = client.post(
            f"{self._base_url}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            json=body,
            timeout=self._timeout_s,
        )
        log_entry["http_status"] = response.status_code
        log_entry["latency_s"] = round(time.perf_counter() - t0, 2)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            choices = data.get("choices") or []
            if choices and isinstance(choices[0], dict):
                log_entry["finish_reason"] = choices[0].get("finish_reason")
            usage = data.get("usage") or {}
            log_entry["completion_tokens"] = usage.get("completion_tokens")
            log_entry["prompt_tokens"] = usage.get("prompt_tokens")

        text = _extract_openai_text(data)
        log_entry["text_block"] = text
        if not text:
            raise ValueError("openai response had no text content")

        payload = _parse_json_object(text)
        log_entry["parsed_json"] = payload
        if payload is None:
            raise ValueError(f"openai text was not parseable JSON: {text!r}")

        category = payload.get("category")
        if not isinstance(category, str) or category not in WARDROBE_CATEGORIES:
            raise ValueError(f"openai returned unknown category: {category!r}")

        confidence = payload.get("confidence")
        if not isinstance(confidence, (int, float)):
            raise ValueError(f"openai confidence missing or not numeric: {confidence!r}")
        confidence = float(confidence)

        reasoning = payload.get("reasoning")
        if reasoning is not None and not isinstance(reasoning, str):
            reasoning = None

        return VisionAnalysisResult(
            category=category,
            confidence=max(0.0, min(1.0, confidence)),
            name=_coerce_name(payload.get("name")),
            primary_color=_coerce_primary_color(payload.get("primary_color")),
            attrs=_coerce_vision_attrs(payload.get("attrs")),
            source="cloud_llm",
            reasoning=reasoning,
        )


def get_vision_analyzer(settings: Settings) -> OpenAIVisionAnalyzer | None:
    """Build a vision analyzer or None if disabled / not configured."""
    if not settings.enable_vision_analysis:
        return None
    if not settings.openai_api_key:
        return None
    return OpenAIVisionAnalyzer(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.openai_model,
        proxy=getattr(settings, "openai_http_proxy", "") or None,
    )


def _shrink_for_upload(image_bytes: bytes, media_type: str) -> tuple[bytes, str]:
    """Downscale to ~1024px max-dim before encoding.

    With ``detail:"low"`` OpenAI scales to 512×512 on its side and bills
    a fixed 85 input tokens regardless of source resolution, so anything
    above ~1024px is just bandwidth waste. We re-encode as JPEG (smaller
    than PNG for photos) at quality 85, which gives ~80-150KB on typical
    garment photos.

    If Pillow can't open the bytes, the original is returned and the
    caller gets whatever error the upstream throws (then heuristic
    fallback kicks in).
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover — Pillow is in pyproject deps
        return image_bytes, media_type

    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            im.load()
            # JPEG can't store alpha; convert RGBA/P → RGB on a white
            # background so transparent PNGs from rembg still encode.
            if im.mode in ("RGBA", "LA", "P"):
                from PIL import Image as PILImage

                rgba = im.convert("RGBA")
                bg = PILImage.new("RGB", rgba.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[-1])
                base = bg
            elif im.mode != "RGB":
                base = im.convert("RGB")
            else:
                base = im.copy()

            base.thumbnail(
                (_CLASSIFIER_MAX_DIM, _CLASSIFIER_MAX_DIM),
                Image.Resampling.LANCZOS,
            )
            buf = io.BytesIO()
            base.save(buf, format="JPEG", quality=_CLASSIFIER_JPEG_QUALITY, optimize=True)
            return buf.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001
        logger.exception("category_classifier: shrink failed, sending original")
        return image_bytes, media_type


def _pred_dict(pred: CategoryPrediction) -> dict:
    return {
        "category": pred.category,
        "confidence": pred.confidence,
        "source": pred.source,
        "reasoning": pred.reasoning,
    }


def _extract_openai_text(response: dict | Any) -> str | None:
    """Extract the assistant text from a Chat Completions response.

    Standard shape is ``{"choices":[{"message":{"content":"..."}}]}``.
    Older/edge responses may emit content as a list of blocks; we
    concatenate their ``text`` fields as a safety net.
    """
    if not isinstance(response, dict):
        return None
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content if content.strip() else None
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts) if parts else None
    return None


def _parse_json_object(text: str) -> dict | None:
    """Pull a single JSON object out of a possibly-decorated string.

    Handles three response shapes the model emits in practice:
      * a clean ``{...}`` (system prompt is followed)
      * a ``json`` code fence around the object
      * stray prose with the object somewhere inside

    Returns ``None`` when nothing parseable is found — the caller treats
    that as a failure and falls back to the heuristic.
    """
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()

    try:
        result = json.loads(cleaned)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass

    for match in _JSON_OBJECT_RE.finditer(cleaned):
        try:
            result = json.loads(match.group(0))
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _summarize_hint(hint: dict[str, Any] | None) -> str:
    if not hint:
        return ""
    parts: list[str] = []
    for key in ("primary_color", "print_type", "occasion", "structure", "cut_lines"):
        val = hint.get(key)
        if val and not (isinstance(val, str) and val.startswith("_")):
            parts.append(f"{key}={val}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Heuristic fallback
# ---------------------------------------------------------------------------


_OUTERWEAR_OCCASIONS = {"work", "smart_casual", "evening"}


class HeuristicCategoryClassifier:
    """Rule-based fallback on Phase-0 attributes.

    Cannot reliably distinguish blouses vs sweaters (no fabric sensor),
    pants vs skirts (no leg-shape feature), bags vs belts vs jewelry.
    For accessories we honestly return low confidence so the API stores
    ``category=None`` and the user picks manually.
    """

    def classify(
        self,
        image_bytes: bytes,  # noqa: ARG002 — heuristic doesn't need pixels
        *,
        attrs_hint: dict[str, Any] | None = None,
        media_type: str = "image/jpeg",  # noqa: ARG002
    ) -> CategoryPrediction:
        hint = attrs_hint or {}
        occasion = hint.get("occasion")
        structure = hint.get("structure")
        cut_lines = hint.get("cut_lines")

        # Without any signal we honestly admit defeat — confidence 0,
        # the route stores category=None and asks the user.
        if not occasion and not structure and not cut_lines:
            return CategoryPrediction(
                category="blouses",
                confidence=0.0,
                source="heuristic",
                reasoning="no attribute hints available",
            )

        # Crude rules — calibrated to «better than category=top hardcode»,
        # not to compete with the cloud classifier.
        if occasion in _OUTERWEAR_OCCASIONS and structure in {"tailored", "tailored_moderate"}:
            return CategoryPrediction(
                category="jackets",
                confidence=0.5,
                source="heuristic",
                reasoning="tailored structure + work/evening occasion",
            )

        return CategoryPrediction(
            category="blouses",
            confidence=0.35,
            source="heuristic",
            reasoning="default top-half guess from heuristic tree",
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_category_classifier(settings: Settings) -> CategoryClassifier:
    """Build a classifier matching the current Settings.

    Returns the heuristic classifier if the feature flag is off, the
    provider is set to ``"heuristic"``, or the OpenAI key is missing.
    """
    if not settings.use_cv_category_classifier:
        return HeuristicCategoryClassifier()

    provider = settings.category_classifier_provider
    if provider == "openai" and settings.openai_api_key:
        return OpenAICategoryClassifier(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            proxy=getattr(settings, "openai_http_proxy", "") or None,
        )

    return HeuristicCategoryClassifier()


__all__ = [
    "CategoryClassifier",
    "CategoryPrediction",
    "CategorySource",
    "OpenAICategoryClassifier",
    "OpenAIVisionAnalyzer",
    "VisionAnalysisResult",
    "HeuristicCategoryClassifier",
    "get_category_classifier",
    "get_vision_analyzer",
]
