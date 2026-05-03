"""Production-grade observability for the CV category classifier.

Two read-only endpoints (no auth — values are non-sensitive):

* ``GET /api/cv-classifier/config`` — reflects the active settings
  (env values that Pydantic Settings actually loaded). The OpenAI API
  key is reduced to ``set: bool`` and ``length: int`` — never echoed.
* ``GET /api/cv-classifier/recent`` — last ~100 classifier attempts as
  JSONL stored in /tmp (shared across uvicorn workers via ``fcntl.flock``).

Kept permanently because the alternative is what we did all afternoon:
debug endpoints get added on every prod report, removed in a "cleanup"
PR, then re-added on the next report. Observability isn't debt — for a
feature gated by a paid third-party API it's part of the feature.
"""

from __future__ import annotations

import time

import httpx
from fastapi import APIRouter

from app.core.config import settings
from app.services.category_classifier import (
    _PROXY_SCHEMES_CASCADE,
    _proxy_creds,
    get_category_classifier,
    get_recent_attempts,
    get_vision_analyzer,
)

router = APIRouter()


@router.get("/config")
def cv_classifier_config() -> dict:
    vision_analyzer = get_vision_analyzer(settings)
    proxy = (settings.openai_http_proxy or "").strip()
    return {
        "use_cv_category_classifier": settings.use_cv_category_classifier,
        "enable_vision_analysis": settings.enable_vision_analysis,
        "category_classifier_provider": settings.category_classifier_provider,
        "category_confidence_threshold": settings.category_confidence_threshold,
        "openai_base_url": settings.openai_base_url,
        "openai_model": settings.openai_model,
        "openai_api_key_set": bool(settings.openai_api_key),
        "openai_api_key_length": len(settings.openai_api_key),
        "openai_http_proxy_set": bool(proxy),
        "openai_http_proxy_scheme": proxy.split("://", 1)[0] if "://" in proxy else None,
        "active_classifier_type": type(get_category_classifier(settings)).__name__,
        "vision_analyzer_active": vision_analyzer is not None,
    }


@router.get("/recent")
def cv_classifier_recent(limit: int = 20) -> dict:
    """Last classifier attempts in chronological order.

    Each entry has timestamp, image bytes count, full prediction
    (category/confidence/source/reasoning), and on cloud failures the
    raw OpenAI response + parsed JSON for diagnosis.
    """
    attempts = get_recent_attempts()
    return {
        "count": len(attempts),
        "attempts": attempts[-limit:],
    }


@router.get("/probe-proxy")
def cv_classifier_probe_proxy(timeout_s: float = 5.0) -> dict:
    """Live-проверка прокси: дёргает /v1/models через каждую схему каскада.

    Не тратит токены (GET /v1/models — листинг моделей, бесплатный).
    Возвращает по каждой схеме либо ``{ok: true, status, model_count}``
    либо ``{ok: false, error_type, error_message}``. Если все три
    схемы провалились с тем же типом ошибки — проблема не в схеме URL,
    а в самом прокси (whitelist по IP, неверные креды, прокси выключен).

    Креды login:pass@host:port не светим — берём из settings и не
    включаем в ответ.
    """
    proxy_raw = (settings.openai_http_proxy or "").strip()
    if not proxy_raw:
        return {"ok": False, "reason": "OPENAI_HTTP_PROXY is not set"}
    if not settings.openai_api_key:
        return {"ok": False, "reason": "OPENAI_API_KEY is not set"}

    creds = _proxy_creds(proxy_raw)
    base_url = settings.openai_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}

    results = []
    for prefix in _PROXY_SCHEMES_CASCADE:
        proxy_url = prefix + creds
        scheme_result = {"scheme": prefix.rstrip(":/")}
        t0 = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout_s, proxy=proxy_url) as client:
                resp = client.get(f"{base_url}/v1/models", headers=headers)
            scheme_result["latency_s"] = round(time.perf_counter() - t0, 2)
            scheme_result["status"] = resp.status_code
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    scheme_result["model_count"] = len(data.get("data", []))
                except Exception:  # noqa: BLE001
                    scheme_result["model_count"] = None
                scheme_result["ok"] = True
            else:
                scheme_result["ok"] = False
                scheme_result["body_preview"] = resp.text[:200]
        except Exception as exc:  # noqa: BLE001
            scheme_result["latency_s"] = round(time.perf_counter() - t0, 2)
            scheme_result["ok"] = False
            scheme_result["error_type"] = type(exc).__name__
            scheme_result["error_message"] = str(exc)[:300]
        results.append(scheme_result)

    any_ok = any(r.get("ok") for r in results)
    return {
        "ok": any_ok,
        "diagnosis": (
            "одна из схем сработала — vision-pipeline должен работать"
            if any_ok
            else "все схемы упали → проблема не в URL: проверь IP whitelist "
                 "у proxy-seller, креды login/password, оплачен ли план"
        ),
        "schemes": results,
    }
