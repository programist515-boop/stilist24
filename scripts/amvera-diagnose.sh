#!/bin/bash
# Полная диагностика stilist24-api / stilist24-web в Amvera через CLI.
#
# Требует: пользователь сделал `amvera login -u <email> -p <password>` в
# этом же терминале (баг amvera-cli v1.0.5 — токен не персистится между
# сессиями, нужно цепочкой). Если в `~/.amvera/` пусто — скрипт падает.
#
# Usage:
#   ./scripts/amvera-diagnose.sh
#
# Закрывает 2.11 плана (alembic upgrade head в логах api).

set -u

AMVERA="${AMVERA_BIN:-/c/Users/user/amvera/amvera}"
[ -x "$AMVERA" ] || AMVERA="amvera"

# Sanity check — токен есть?
if ! "$AMVERA" whoami >/dev/null 2>&1; then
  echo "[ABORT] amvera-cli не залогинен."
  echo "        Выполни в этой же сессии:"
  echo "        $AMVERA login -u <email> -p <password>"
  echo "        Затем повтори: ./scripts/amvera-diagnose.sh"
  exit 1
fi

echo "============================================================"
echo "1. WHOAMI"
echo "============================================================"
"$AMVERA" whoami 2>&1

echo
echo "============================================================"
echo "2. ALL PROJECTS"
echo "============================================================"
"$AMVERA" get 2>&1 | head -60

for slug in stilist24-api stilist24-web; do
  echo
  echo "============================================================"
  echo "3. PROJECT: $slug"
  echo "============================================================"
  "$AMVERA" describe project --slug "$slug" 2>&1 | head -40

  echo
  echo "--- $slug DOMAINS ---"
  "$AMVERA" get domain --slug "$slug" 2>&1

  echo
  echo "--- $slug BUILD LOGS (last 60) ---"
  "$AMVERA" logs build --slug "$slug" 2>&1 | tail -60

  echo
  echo "--- $slug RUN LOGS (last 60) ---"
  "$AMVERA" logs run --slug "$slug" 2>&1 | tail -60

  if [ "$slug" = "stilist24-api" ]; then
    echo
    echo "--- $slug: alembic / startup в логах ---"
    "$AMVERA" logs run --slug "$slug" 2>&1 | grep -E '(startup|alembic|migrations|DATABASE_URL|ERROR|FAIL)' | tail -30
  fi
done

echo
echo "============================================================"
echo "DIAGNOSTIC COMPLETE"
echo "============================================================"
