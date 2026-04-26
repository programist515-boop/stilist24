"""Wardrobe category classifier — pluggable backends.

Two implementations behind one Protocol:

* :class:`ClaudeCategoryClassifier` — Claude Haiku via the Anthropic
  Messages API (or any Anthropic-compatible proxy, e.g. ``kie.ai``).
  Uses ``httpx`` directly so we control the full URL, auth header, and
  request body — proxies that wrap Claude (kie.ai, OpenRouter, Vertex)
  diverge on these details (Bearer vs ``x-api-key``, model name, base
  path), so the SDK abstraction would actually get in the way. Forced
  JSON output via ``tool_use`` + ``tool_choice``. Bounded by an
  in-memory circuit breaker so a failing upstream doesn't cascade into
  30s upload timeouts for every user.
* :class:`HeuristicCategoryClassifier` — rule-based on the
  ``recognize_garment`` Phase-0 attributes (occasion, structure,
  cut_lines, ...). Used when the cloud key is missing or the breaker
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
# Claude Messages API (Anthropic / kie.ai / Anthropic-compatible proxies)
# ---------------------------------------------------------------------------

# Default base_url targets kie.ai (the configured proxy in this project).
# For a direct Anthropic deploy, override via Settings.claude_base_url to
# ``https://api.anthropic.com`` and set claude_auth_scheme="x-api-key".
_DEFAULT_BASE_URL = "https://api.kie.ai/claude"
_DEFAULT_MODEL = "claude-haiku-4-5"
# kie.ai with a 56k-token image takes ~10-12s end-to-end on the happy
# path but occasionally drags to 20-25s (queueing in the proxy). 30s
# matches the user-facing upload timeout (frontend uses 120s) and gives
# enough room for one retry on TimeoutException without the user seeing
# a hang. Outside this budget we still fall back to heuristic.
_DEFAULT_TIMEOUT_S = 30.0
_BREAKER_FAIL_THRESHOLD = 3
_BREAKER_COOLDOWN_S = 300.0  # 5 minutes
# How many retries on transient (network/timeout) errors before giving up
# and letting the wrapper fall through to heuristic. Each retry costs one
# more kie.ai credit, so we cap low.
_TRANSIENT_RETRIES = 1

# kie.ai rejects images bigger than ~100KB with HTTP 400/500 (proxy
# limit, not Anthropic's — direct Anthropic accepts up to 5MB). User
# uploads from phones are routinely 1-3MB so we have to downscale
# before encoding. 1024px on the long side keeps the garment legible
# for Haiku Vision while staying well under the 100KB ceiling.
_CLASSIFIER_MAX_IMAGE_DIM = 1024
_CLASSIFIER_JPEG_QUALITY = 85


_CATEGORIES_LIST = ", ".join(WARDROBE_CATEGORIES)


# JSON-in-text instead of tool_use because the kie.ai proxy returns an
# empty content array when ``tools`` or ``tool_choice`` is set (input is
# accepted, but output_tokens=0). Direct Anthropic supports tool_use
# fine, but mixing two output paths in one classifier doubles the test
# surface — JSON-in-text works on both providers, so we stick with it.
_SYSTEM_PROMPT = (
    f"You classify photos of clothing items into one of 15 categories: "
    f"{_CATEGORIES_LIST}. "
    "If the photo shows a full outfit, pick the most prominent garment. "
    "Reply with ONLY a single JSON object on one line, no markdown, no "
    "code fence, no commentary: "
    '{"category": "<one of the 15>", "confidence": <0..1>, "reasoning": "<1 sentence>"}'
)


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


class ClaudeCategoryClassifier:
    """Claude vision classifier over the Anthropic Messages API.

    Works with both kie.ai (default) and the direct Anthropic API by
    swapping ``base_url`` and ``auth_scheme``:
      * kie.ai      → base_url ``https://api.kie.ai/claude``,
                      auth_scheme="bearer"
      * Anthropic   → base_url ``https://api.anthropic.com``,
                      auth_scheme="x-api-key"
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        model: str = _DEFAULT_MODEL,
        auth_scheme: Literal["bearer", "x-api-key"] = "bearer",
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
        breaker: _CircuitBreaker | None = None,
        fallback: CategoryClassifier | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._auth_scheme = auth_scheme
        self._timeout_s = timeout_s
        self._client = client  # injected for tests; lazy-built otherwise
        self._breaker = breaker or _CircuitBreaker()
        self._fallback = fallback or HeuristicCategoryClassifier()

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        self._client = httpx.Client(timeout=self._timeout_s)
        return self._client

    def _auth_headers(self) -> dict[str, str]:
        if self._auth_scheme == "x-api-key":
            # Direct Anthropic API requires the version header alongside x-api-key.
            return {"x-api-key": self._api_key, "anthropic-version": "2023-06-01"}
        return {"Authorization": f"Bearer {self._api_key}"}

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
                pred = self._call_claude(image_bytes, attrs_hint, media_type, log_entry)
                log_entry["outcome"] = "cloud_ok"
                log_entry["prediction"] = _pred_dict(pred)
                _record_attempt(log_entry)
                return pred
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                # Transient — kie.ai proxy queue spike or flaky network.
                # Retry without burning the breaker so a single slow call
                # doesn't trip 3-strike cooldown.
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
                    "category_classifier: claude call failed (%s: %s), falling back to heuristic",
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

    def _call_claude(
        self,
        image_bytes: bytes,
        attrs_hint: dict[str, Any] | None,
        media_type: str,
        log_entry: dict[str, Any] | None = None,
    ) -> CategoryPrediction:
        encoded_bytes, encoded_media_type = _shrink_for_proxy(image_bytes, media_type)
        if log_entry is not None:
            log_entry["encoded_bytes"] = len(encoded_bytes)
            log_entry["encoded_media_type"] = encoded_media_type
        b64 = base64.standard_b64encode(encoded_bytes).decode("ascii")
        user_text_parts = [
            "Classify the garment in this photo into one of the 15 supported categories."
        ]
        hint_summary = _summarize_hint(attrs_hint)
        if hint_summary:
            user_text_parts.append(f"Pre-extracted hints (may be useful): {hint_summary}")

        body = {
            "model": self._model,
            "max_tokens": 200,
            "system": _SYSTEM_PROMPT,
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": encoded_media_type,
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "\n".join(user_text_parts) + "\n\nReply with the JSON object only.",
                        },
                    ],
                }
            ],
        }

        client = self._get_client()
        t0 = time.perf_counter()
        response = client.post(
            f"{self._base_url}/v1/messages",
            headers={"Content-Type": "application/json", **self._auth_headers()},
            json=body,
            timeout=self._timeout_s,
        )
        if log_entry is not None:
            log_entry["http_status"] = response.status_code
            log_entry["latency_s"] = round(time.perf_counter() - t0, 2)
        response.raise_for_status()
        data = response.json()
        if log_entry is not None and isinstance(data, dict):
            log_entry["claude_stop_reason"] = data.get("stop_reason")
            log_entry["claude_output_tokens"] = (data.get("usage") or {}).get("output_tokens")
            log_entry["credits_consumed"] = data.get("credits_consumed")

        # kie.ai sometimes returns HTTP 200 with a proxy-level error
        # envelope: ``{"code": <int>, "msg": "...", "data": null}``. The
        # most common one is 402 ("Credits insufficient") — surfacing
        # that distinctly is much more useful than the generic "no text
        # content" we used to raise. Direct Anthropic never sets ``code``,
        # so this branch is harmless there.
        if isinstance(data, dict) and "code" in data and data.get("data") is None:
            kie_code = data.get("code")
            kie_msg = data.get("msg", "")
            if log_entry is not None:
                log_entry["proxy_error_code"] = kie_code
                log_entry["proxy_error_msg"] = kie_msg
            if kie_code == 402:
                raise RuntimeError(f"credits_insufficient: {kie_msg}")
            raise RuntimeError(f"proxy_error code={kie_code}: {kie_msg}")

        text = _extract_text_block(data)
        if log_entry is not None:
            log_entry["text_block"] = text
        if not text:
            raise ValueError("claude response had no text content")

        payload = _parse_json_object(text)
        if log_entry is not None:
            log_entry["parsed_json"] = payload
        if payload is None:
            raise ValueError(f"claude text was not parseable JSON: {text!r}")

        category = payload.get("category")
        if not isinstance(category, str) or category not in WARDROBE_CATEGORIES:
            raise ValueError(f"claude returned unknown category: {category!r}")

        confidence = payload.get("confidence")
        if not isinstance(confidence, (int, float)):
            raise ValueError(f"claude confidence missing or not numeric: {confidence!r}")
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


def _shrink_for_proxy(image_bytes: bytes, media_type: str) -> tuple[bytes, str]:
    """Downscale large images so the kie.ai proxy doesn't reject them.

    Returns ``(encoded_bytes, "image/jpeg")``. If Pillow can't open the
    bytes (corrupted / unsupported format), the original bytes are
    returned untouched — caller will get the upstream error and fall
    back to heuristic, same as before this helper existed. Direct
    Anthropic also gets the smaller payload (faster, cheaper) — no
    visible accuracy loss for garment classification at 1024px.
    """
    if len(image_bytes) <= 100_000:
        return image_bytes, media_type
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover — Pillow is in pyproject deps
        return image_bytes, media_type
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            # Pillow's thumbnail keeps aspect ratio and only shrinks.
            im.thumbnail(
                (_CLASSIFIER_MAX_IMAGE_DIM, _CLASSIFIER_MAX_IMAGE_DIM),
                Image.Resampling.LANCZOS,
            )
            # JPEG can't store alpha; convert RGBA/P → RGB on a white
            # background so transparent PNGs from rembg still encode.
            if im.mode in ("RGBA", "LA", "P"):
                from PIL import Image as PILImage

                bg = PILImage.new("RGB", im.size, (255, 255, 255))
                bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[-1])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=_CLASSIFIER_JPEG_QUALITY, optimize=True)
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


def _extract_text_block(response: dict | Any) -> str | None:
    """Concatenate all text blocks in a Messages API response.

    Claude usually returns a single text block, but a model may emit
    several (e.g. ``thinking`` + ``text``) — joining them gives the
    JSON parser the best chance.
    """
    content = response.get("content") if isinstance(response, dict) else getattr(response, "content", None)
    if not content:
        return None
    parts: list[str] = []
    for block in content:
        block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if block_type == "text":
            text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts) if parts else None


def _parse_json_object(text: str) -> dict | None:
    """Pull a single JSON object out of a possibly-decorated string.

    Handles three response shapes the model emits in practice:
      * a clean ``{...}`` (system prompt is followed)
      * a ``json`` code fence around the object
      * stray prose with the object somewhere inside

    Returns ``None`` when nothing parseable is found — the caller treats
    that as a failure and falls back to the heuristic.
    """
    # Strip markdown code fences first — they confuse json.loads even
    # when the inner payload is valid.
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()

    # Direct parse — fastest path when the model behaves.
    try:
        result = json.loads(cleaned)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass

    # Fall back to scanning for any ``{...}`` slice that parses.
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
    provider is set to ``"heuristic"``, or the Claude key is missing.
    """
    if not settings.use_cv_category_classifier:
        return HeuristicCategoryClassifier()

    provider = settings.category_classifier_provider
    if provider in {"claude", "anthropic"} and settings.claude_api_key:
        return ClaudeCategoryClassifier(
            api_key=settings.claude_api_key,
            base_url=settings.claude_base_url,
            model=settings.claude_model,
            auth_scheme=settings.claude_auth_scheme,  # type: ignore[arg-type]
        )

    return HeuristicCategoryClassifier()


__all__ = [
    "CategoryClassifier",
    "CategoryPrediction",
    "CategorySource",
    "ClaudeCategoryClassifier",
    "HeuristicCategoryClassifier",
    "get_category_classifier",
]
