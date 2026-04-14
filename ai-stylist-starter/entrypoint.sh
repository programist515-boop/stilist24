#!/bin/sh
# Prod entrypoint: apply pending migrations, then start uvicorn workers.
set -e

alembic upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port 8002 --workers 4
