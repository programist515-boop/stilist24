#!/bin/sh
# Prod entrypoint: apply pending migrations, then start uvicorn workers.
set -e

# Стартовая диагностика DATABASE_URL — пишет в лог host/user/db/длину
# пароля. Пароль не светим. Помогает быстро отличить расхождение env
# от проблем с самой БД. Если переменная не приехала — увидим пустые
# значения, а не молчаливый дефолт из config.py.
if [ -n "$DATABASE_URL" ]; then
  db_user=$(echo "$DATABASE_URL" | sed -E 's|^[^/]+//([^:]+):.*|\1|')
  db_host=$(echo "$DATABASE_URL" | sed -E 's|.*@([^:/]+).*|\1|')
  db_name=$(echo "$DATABASE_URL" | sed -E 's|.*/([^?]+).*|\1|')
  db_pwd_len=$(echo "$DATABASE_URL" | sed -E 's|^[^/]+//[^:]+:([^@]+)@.*|\1|' | wc -c)
  echo "[startup] DATABASE_URL user=$db_user host=$db_host db=$db_name pwd_len=$((db_pwd_len - 1))"
else
  echo "[startup] DATABASE_URL is EMPTY — env not propagated"
fi

if alembic upgrade head; then
  echo "[startup] migrations applied"
else
  echo "[startup] WARNING: alembic upgrade head failed — starting API anyway so /health responds for diagnostics"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8002 --workers 4
