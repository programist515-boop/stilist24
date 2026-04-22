# stilist24 — навигация по проекту

Этот документ — карта проекта. Читай его в начале каждой сессии, чтобы понимать, где что лежит и как с этим работать.

## Что это за проект

**stilist24 (AI-стилист)** — сервис для девушек 22–35 (офис/IT), который подбирает образы из их же гардероба и объясняет каждое решение.

Комплексный end-to-end флоу: анализ внешности (цветотип + тип телосложения) → разбор гардероба → рекомендации, что докупить → поиск на маркетплейсах. MVP — веб-приложение (PWA), позже — мобилка.

Подробности — в `.business/INDEX.md`.

## Структура репозитория

```
stilist24/
├── CLAUDE.md             ← этот файл, навигация
├── docker-compose.prod.yml       ← прод-стек: api, web, db, redis, minio
├── .env.prod.example     ← справка по прод-переменным (сам .env.prod
│                                  генерируется CI из GitHub Secrets)
├── .github/workflows/deploy.yml  ← CI/CD: тесты + SSH-деплой на stilist24.com
├── scripts/
│   └── generate-secrets.sh       ← генератор секретов для ротации GitHub Secrets
├── docs/
│   └── DEPLOY.md                 ← архитектура прода, CI/CD, day-2 операции
├── .business/            ← бизнес-контекст (не в git)
│   ├── INDEX.md          ← оглавление, входная точка
│   ├── company/ products/ audience/ goals/
│   └── economics/ marketing/ assets/
├── plans/                ← технические планы (один план = одна функция)
│   └── archive/                  ← исторические документы (NEXT_STEPS.md)
├── ai-stylist-starter/   ← backend (FastAPI)
│   ├── docs/SCORING_SPEC.md      ← веса скоринга (item/outfit/final)
│   ├── app/
│   │   ├── main.py               ← сборка FastAPI, подключение роутов
│   │   ├── api/routes/           ← 12 роутов: auth, user_analysis, color,
│   │   │                           wardrobe, gap_analysis, outfits, tryon,
│   │   │                           feedback, today, insights, recommendations,
│   │   │                           shopping
│   │   ├── services/             ← движки и бизнес-логика (см. ниже)
│   │   ├── models/               ← 11 SQLAlchemy-моделей
│   │   ├── repositories/         ← data access layer
│   │   ├── schemas/              ← Pydantic-схемы API
│   │   ├── core/config.py        ← settings, env, feature flags
│   │   └── workers/              ← фоновые задачи
│   ├── config/rules/             ← 11 YAML-файлов с правилами стилиста
│   ├── alembic/                  ← миграции БД
│   ├── tests/
│   ├── docker-compose.yml        ← Postgres + Redis + MinIO + API
│   └── openapi.yaml
└── frontend/             ← frontend (Next.js 14)
    ├── src/app/(auth)/sign-in/
    ├── src/app/(app)/            ← analyze, wardrobe, outfits, tryon,
    │                               today, insights, recommendations
    ├── src/components/           ← analysis, insights, layout, outfits,
    │                               today, tryon, ui, wardrobe
    ├── src/lib/                  ← api, schemas, i18n, local-store, user-id
    └── src/providers/            ← React Query и т.п.
```

### Где что искать

| Что нужно | Куда смотреть |
|---|---|
| Зачем делаем проект, для кого, бизнес-логика | `.business/INDEX.md` |
| Целевой пользователь, боли, желания | `.business/audience/` |
| Продукт, тарифы, цены | `.business/products/` |
| Цели и метрики | `.business/goals/` |
| Экономика (доход/расход/юнит) | `.business/economics/` |
| Каналы, воронка, конкуренты, контент | `.business/marketing/` |
| Брендинг | `.business/assets/` |
| Технические планы реализации | `plans/` |
| Сборка FastAPI, список роутов | `ai-stylist-starter/app/main.py` |
| Движки (Color, Identity, Outfit, Scoring) | `ai-stylist-starter/app/services/` |
| Правила стилиста (YAML) | `ai-stylist-starter/config/rules/` |
| Веса скоринга | `ai-stylist-starter/docs/SCORING_SPEC.md` |
| Настройки и feature flags | `ai-stylist-starter/app/core/config.py` |
| Модели БД | `ai-stylist-starter/app/models/` |
| Миграции | `ai-stylist-starter/alembic/` |
| Страницы фронта | `frontend/src/app/(app)/` |
| API-клиент и схемы фронта | `frontend/src/lib/` |
| Архитектура прода, CI/CD, ops | `docs/DEPLOY.md` |
| Справка по прод-переменным | `.env.prod.example` |
| CI/CD workflow | `.github/workflows/deploy.yml` |
| Ротация секретов | `scripts/generate-secrets.sh` |

### Ключевые движки и сервисы (в `ai-stylist-starter/app/services/`)

- **`color_engine.py`, `color_feature_extractor.py`** — цветотип, 12 сезонов, палитра.
- **`identity_engine.py`** — типаж / тип телосложения, семейства и подтипы.
- **`outfit_engine.py`** + пакет **`outfits/`** — сборка и оценка образов. **Feature flag `USE_NEW_OUTFIT_ENGINE`** в `core/config.py` переключает на новый explainable-пайплайн.
- **`scoring_service.py`** + пакет **`scoring/`** — скоринг item/outfit/final (веса в `ai-stylist-starter/docs/SCORING_SPEC.md`).
- **`garment_recognizer.py`, `cv_feature_extractor.py`, `feature_extractor.py`** — распознавание вещей из фото (MediaPipe + rembg).
- **`rules_loader.py`** — загрузка YAML-правил.
- **`explainer.py`** — формирование человекочитаемого `explanation` к каждому решению.
- **`gap_analysis_service.py`** + пакет **`shopping/`** — что в гардеробе не хватает, рекомендации к покупке.
- **`today_service.py`, `insights_service.py`, `versatility_service.py`** — UX-фичи «образ на сегодня» и еженедельные инсайты.
- **`tryon_service.py` + `fashn_adapter.py`** — виртуальная примерка через FASHN AI (адаптер, stub по умолчанию).
- **`personalization_service.py`, `feedback_service.py`** — обучение на обратной связи.

### YAML-правила (в `ai-stylist-starter/config/rules/`)

`outfit_rules`, `gap_analysis_rules`, `garment_line_rules`, `garment_recognition_rules`, `identity_families`, `identity_subtypes`, `seasons_12`, `seasons_palette`, `season_families`, `recommendation_guides`, `shopping_explanations`, `reference_looks/` (референсные луки по подтипам, YAML на подтип — см. [план 2026-04-21](plans/2026-04-21-каталог-фич-из-отчёта-типажа.md)).

## Ключевые принципы проекта

1. **Комплексность.** Закрываем весь путь пользователя — от цветотипа до покупки. Главный дифференциатор от конкурентов.
2. **Объяснимость.** Каждая рекомендация возвращает `score + explanation`. Никакой магии.
3. **Правила в YAML, не в коде.** Бизнес-логика стилиста меняется без релиза. Никакой business logic в routes.

Дополнительно: честность качества (честные quality downgrades при недостатке данных) и детерминизм (одинаковый вход → одинаковый результат). См. `.business/company/values.md`.

## Стек

**Backend:** Python 3.11+, FastAPI, SQLAlchemy 2.0 + Alembic, Postgres (psycopg), Pydantic v2, boto3 (S3/MinIO), Redis, MediaPipe, rembg, JWT-auth. Запуск через `docker compose up --build` из `ai-stylist-starter/`. Swagger на `:8000/docs`, MinIO console на `:9001`.

**Frontend:** Next.js 14, React 18, TypeScript, Tailwind CSS, TanStack Query, Zod.

## Как работать с проектом

- Перед любой задачей — прочитай этот файл, затем нужные документы из `.business/` и `plans/`.
- Если меняется бизнес-логика — обнови `.business/INDEX.md` и нужные файлы.
- Если меняется технический план — обнови соответствующий план в `plans/`.
- Если появляется новая важная папка или документ — обнови этот `CLAUDE.md`.

## ВАЖНО: план для каждой новой функции

Любая функция, которую мы создаём в любом чате, всегда оформляется планом в папке `plans/`.

Правила:

1. Один план = одна функция. Если план уже есть — работаем с ним.
2. Имя файла: `YYYY-MM-DD-название-функции.md`.
3. План делится на фазы. У каждой фазы статус `[ ]` или `[x]`.
4. В конце плана — итоговый блок: реализован целиком или нет, что осталось.
5. Любой агент обязан актуализировать план после каждой сессии.

## ВАЖНО: завершение каждого чата

В конце каждой сессии записывай рефлексию в файл `.business/история/YYYY-MM-DD-краткое-название.md` (создавай папку при необходимости).

Формат:

1. Какая задача была поставлена.
2. Как я её решал.
3. Решил ли — да / нет / частично.
4. Эффективно ли решение, что можно было лучше.
5. Как было и как стало.

## Язык

Всегда отвечай мне на русском.
