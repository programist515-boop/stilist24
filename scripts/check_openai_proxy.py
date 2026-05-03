#!/usr/bin/env python3
"""Smoke-проверка: достижим ли OpenAI через настроенный HTTP-прокси.

Запуск (на сервере или локально с теми же env-переменными):

    OPENAI_API_KEY=sk-... \
    OPENAI_HTTP_PROXY=http://user:pass@host:port \
    python scripts/check_openai_proxy.py

Что делает:
  1. Читает OPENAI_API_KEY, OPENAI_HTTP_PROXY, OPENAI_BASE_URL, OPENAI_MODEL
     из process env (как в проде).
  2. Через httpx.Client(proxy=...) дёргает /v1/models — самый дешёвый
     запрос (один GET, не тратит токены) с auth-заголовком.
  3. Печатает: статус ответа, latency, видна ли модель из OPENAI_MODEL
     в списке доступных.

Этот скрипт намеренно не вызывает /v1/chat/completions с картинкой —
тратит токены и может провалиться по другим причинам. Если /v1/models
отвечает 200 и модель в списке — vision-pipeline в прод-коде должен
работать.
"""
from __future__ import annotations

import os
import sys
import time

import httpx


def _mask(value: str) -> str:
    """Показать только последние 4 символа секрета."""
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "***"
    return f"...{value[-4:]}"


def main() -> int:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    proxy = os.environ.get("OPENAI_HTTP_PROXY", "").strip() or None
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-5-mini")

    print(f"[check] base_url     = {base_url}")
    print(f"[check] model        = {model}")
    print(f"[check] api_key      = {_mask(api_key)}")
    print(f"[check] http_proxy   = {'set' if proxy else 'not set'}")
    if not api_key:
        print("[fail]  OPENAI_API_KEY is empty — set it before running")
        return 2

    client_kwargs: dict = {"timeout": 30.0}
    if proxy:
        client_kwargs["proxy"] = proxy

    print(f"[check] dialing {base_url}/v1/models ...")
    t0 = time.perf_counter()
    try:
        with httpx.Client(**client_kwargs) as client:
            response = client.get(
                f"{base_url}/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.ProxyError as exc:
        print(f"[fail]  proxy error: {exc}")
        return 3
    except httpx.ConnectError as exc:
        print(f"[fail]  connect error: {exc}")
        return 4
    except httpx.TimeoutException:
        print("[fail]  timed out after 30s")
        return 5

    latency = round(time.perf_counter() - t0, 2)
    print(f"[check] http {response.status_code} in {latency}s")

    if response.status_code == 401:
        print("[fail]  401 unauthorized — OPENAI_API_KEY is invalid or revoked")
        return 6
    if response.status_code == 403:
        print(
            "[fail]  403 forbidden — likely RU-IP geo-block. "
            "Check OPENAI_HTTP_PROXY exit IP geolocation."
        )
        return 7
    if response.status_code == 429:
        print(
            "[warn]  429 rate-limited — request reached OpenAI but you're "
            "throttled. The proxy works; retry in a minute."
        )
        return 0
    if response.status_code != 200:
        print(f"[fail]  unexpected status {response.status_code}: {response.text[:200]}")
        return 8

    payload = response.json()
    ids = [item.get("id") for item in payload.get("data", []) if isinstance(item, dict)]
    print(f"[check] received {len(ids)} models")

    if model in ids:
        print(f"[ok]    model {model!r} is available — vision pipeline ready")
        return 0
    print(
        f"[warn]  model {model!r} not found in /v1/models. "
        f"Either the key has no access to it, or the proxy hides "
        f"it. First 10 listed: {ids[:10]}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
