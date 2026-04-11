# AI Stylist Starter

Стартовый репозиторий для сервиса AI-стилиста.

## Что внутри
- FastAPI backend
- SQLAlchemy 2.x + Alembic
- PostgreSQL
- Redis
- MinIO как S3-compatible storage
- YAML-based rules engine
- базовые endpoints для auth, анализа пользователя, гардероба, образов, feedback, today, weekly insights, try-on

## Быстрый старт
```bash
cp .env.example .env
docker compose up --build
```

После запуска:
- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- MinIO Console: http://localhost:9001

## Основные команды
```bash
docker compose exec api alembic upgrade head
docker compose exec api pytest -q
```

## Текущий статус
Это стартовый каркас. CV-инференс, OAuth-проверка токенов и полноценная интеграция с FASHN AI оставлены как расширяемые адаптеры и stub-реализации.
