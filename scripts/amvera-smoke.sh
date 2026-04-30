#!/bin/bash
# Smoke-test stilist24 deployment on Amvera.
#
# Запускать ПОСЛЕ того, как:
#   1. «Куб» нажат на stilist24-api и stilist24-web (контейнеры запущены).
#   2. Технический домен активирован: UI Amvera → <app> → «Домены» →
#      «Add domain name» → «Amvera Free Domain» (это создаёт Ingress
#      controller на 80 → forward на containerPort).
#
# Usage:
#   ./scripts/amvera-smoke.sh                                # default URLs
#   ./scripts/amvera-smoke.sh <api_url> <web_url>            # custom
#
# Default URLs совпадают с frontend/Dockerfile ARG NEXT_PUBLIC_API_URL и
# CORS_ALLOW_ORIGINS из amvera-api.env.
#
# Закрывает Phase 2 пункты 2.9–2.11 плана 2026-04-27-переезд-на-amvera.md.

set -u

API="${1:-https://stilist24-api.expertgds.amvera.io}"
WEB="${2:-https://stilist24-web.expertgds.amvera.io}"

echo "============================================================"
echo "Amvera smoke-test"
echo "  api = $API"
echo "  web = $WEB"
echo "============================================================"
echo

PASS=0
FAIL=0

# Ingress 404 detection — на любой Host без зарегистрированного backend
# Amvera ingress отдаёт ровно `404 page not found` (19 байт). Если пробы
# возвращают это тело — домен не активирован, падаем с понятным сообщением.
ingress_check() {
  local body
  body=$(curl -sSk --max-time 10 "$API/health" 2>/dev/null || true)
  if [ "$(echo "$body" | tr -d '[:space:]')" = "404pagenotfound" ]; then
    echo "[ABORT] api domain '$API' отвечает generic ingress 404 — домен НЕ активирован"
    echo "        Активируй: UI → stilist24-api → Домены → Add domain name → Amvera Free Domain"
    echo "        Дальнейшие тесты бессмысленны до активации."
    exit 2
  fi
}

check() {
  local name="$1"
  local cmd="$2"
  local pattern="$3"
  local got
  got=$(eval "$cmd" 2>&1)
  if echo "$got" | grep -qiE "$pattern"; then
    echo "[PASS] $name"
    PASS=$((PASS + 1))
  else
    echo "[FAIL] $name"
    echo "       expected match: $pattern"
    echo "       got: $(echo "$got" | head -c 200)"
    FAIL=$((FAIL + 1))
  fi
}

ingress_check

# Phase 2.9 — API
check "api /health → JSON status:ok" \
  "curl -sSk --max-time 15 $API/health" \
  '"status"[[:space:]]*:[[:space:]]*"ok"'

check "api /health → HTTP 200" \
  "curl -sSk -o /dev/null -w '%{http_code}' --max-time 15 $API/health" \
  '^200$'

check "api /docs → HTTP 200 (Swagger UI)" \
  "curl -sSk -o /dev/null -w '%{http_code}' --max-time 15 $API/docs" \
  '^200$'

check "api /docs → содержит Swagger title" \
  "curl -sSk --max-time 15 $API/docs" \
  '(swagger-ui|Swagger UI)'

check "api /openapi.json → HTTP 200" \
  "curl -sSk -o /dev/null -w '%{http_code}' --max-time 15 $API/openapi.json" \
  '^200$'

# Phase 2.10 — CORS (web → api cross-origin)
check "api OPTIONS preflight → 200/204" \
  "curl -sSk -o /dev/null -w '%{http_code}' -X OPTIONS \
   -H 'Origin: $WEB' \
   -H 'Access-Control-Request-Method: POST' \
   -H 'Access-Control-Request-Headers: content-type' \
   --max-time 15 $API/auth/login" \
  '^(200|204)$'

cors_origin_pattern=$(echo "$WEB" | sed 's/\./\\./g')
check "api Access-Control-Allow-Origin echoes $WEB" \
  "curl -sSkI -X OPTIONS -H 'Origin: $WEB' -H 'Access-Control-Request-Method: POST' --max-time 15 $API/auth/login" \
  "Access-Control-Allow-Origin: ($cors_origin_pattern|\\*)"

# Phase 2.10 — Web
check "web / → HTTP 200" \
  "curl -sSk -o /dev/null -w '%{http_code}' --max-time 15 $WEB/" \
  '^200$'

check "web / → Next.js HTML (не пустое)" \
  "curl -sSk --max-time 15 $WEB/ | wc -c" \
  '^[[:space:]]*[0-9]{4,}$'

api_in_html_pattern=$(echo "$API" | sed 's|https://||' | sed 's/\./\\./g')
check "web / → HTML содержит $API (build-arg вшит правильно)" \
  "curl -sSk --max-time 15 $WEB/" \
  "$api_in_html_pattern"

# Phase 2.11 — alembic upgrade head в логах api проверяется отдельно через
# `amvera logs run --slug stilist24-api` (см. scripts/amvera-diagnose.sh).
# Через HTTP это не проверить.

echo
echo "============================================================"
echo "Summary: $PASS passed, $FAIL failed"
echo "============================================================"

exit "$FAIL"
