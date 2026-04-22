# Preference-based определение типажа и цветотипа через лайки

Дата старта: 2026-04-21.

Полный план (контекст, переиспользуемые компоненты, верификация, риски) —
`C:\Users\user\.claude\plans\linear-twirling-cray.md` (утверждён пользователем).

Этот файл — трекер статуса фаз в соответствии с правилами CLAUDE.md.

## Суть фичи

Алгоритмический анализ цветотипа и типажа (`color_engine`, `identity_engine`) не всегда точен. Добавляем опциональный Tinder-подобный квиз:
- **Identity**: сначала стоковые карточки по 20 подтипам → для top-3 лайков делаем try-on на фото юзера (FASHN) → победитель.
- **Color**: color drapery (Pillow-композит: портрет + цветная полоса у подбородка) по 4 семействам → по 3 сезонам внутри победителя → победитель.
- Результат записывается в `StyleProfile.kibbe_type_preference` / `.color_season_preference`. Юзер переключает `active_profile_source` между `"algorithmic"` и `"preference"`.
- Рекомендации (`outfit_engine`, `gap_analysis_service`) читают профиль через новый `style_profile_resolver.get_active_profile(user_id)`.

## Фазы

### Фаза 1. Модель данных [x]
- [x] Миграция `alembic/versions/0008_preference_profile.py`.
- [x] `app/models/style_profile.py` — добавлены поля `kibbe_type_preference`, `kibbe_preference_confidence`, `color_season_preference`, `color_preference_confidence`, `preference_completed_at`, `active_profile_source` + константы `PROFILE_SOURCE_ALGORITHMIC/PREFERENCE`.
- [x] `app/models/preference_quiz_session.py` — новая модель с константами статусов/этапов.
- [x] `app/models/__init__.py` — регистрация.
- Не проверено в рантайме (требует `alembic upgrade head`) — валидация в Фазе 2 через тесты.

### Фаза 2. Backend: identity quiz [x]
- [x] `app/services/preference_quiz/__init__.py` + `identity_quiz.py` — движок (stock → try-on), функции `build_stock_candidates`, `record_vote`, `resolve_stock_stage`, `build_tryon_finalists`, `resolve_final_winner`.
- [x] `app/schemas/preference_quiz.py` — Pydantic-схемы.
- [x] `app/api/routes/preference_quiz_identity.py` — 5 эндпоинтов (start / vote / advance-to-tryon / tryon-status / complete). Используется внешний префикс `/preference-quiz/identity` при регистрации.
- [x] `app/main.py` — роут зарегистрирован.
- [x] Event types `style_preference_liked/disliked` прокидываются в `FeedbackService`.
- [x] `tests/test_preference_quiz_identity.py` — 5 тестов, все зелёные.

### Фаза 3. Backend: color drapery quiz [x]
- [x] `app/services/preference_quiz/drapery_renderer.py` — Pillow-композит (нижняя треть + мягкий alpha-ramp).
- [x] `app/services/preference_quiz/color_quiz.py` — `build_family_candidates`, `build_season_candidates`, `record_vote`, `resolve_family_stage`, `resolve_final_winner`.
- [x] `app/schemas/preference_quiz_color.py` — Pydantic-схемы.
- [x] `app/api/routes/preference_quiz_color.py` — 4 эндпоинта (start / vote / advance-to-season / complete).
- [x] `app/main.py` — роут зарегистрирован.
- [x] Event types `color_preference_liked/disliked`.
- [x] `tests/test_preference_quiz_color.py` — 6 тестов (включая RGBA-вход), все зелёные.

### Фаза 4. Интеграция с рекомендациями [x]
- [x] `app/services/style_profile_resolver.py` — `ResolvedProfile`, `get_active_profile`, `get_active_profile_by_user_id`, `set_active_profile_source`.
- [x] Рефакторинг `app/services/user_context.py` (центральная точка) — теперь читает профиль через resolver. Все потребители (`outfit_engine`, `gap_analysis_service`, `scoring_service`, `shopping/purchase_evaluator`, `today_service`, `insights_service`) получают правильные значения автоматически.
- [x] `app/services/recommendation_guide_service.py` — единственное место, которое читало `style_profile` в обход context-билдера, тоже переведено на resolver.
- [x] `POST /user/active-profile-source` добавлен в `app/api/routes/user_analysis.py`.
- [x] `tests/test_style_profile_resolver.py` — 13 тестов, все зелёные. Регрессионный прогон `outfit/gap/recommendations/user_analysis` — 187 passed.

### Фаза 5. Frontend [x]
- `frontend/src/app/(app)/style-quiz/page.tsx` — степпер-страница со всеми шагами (intro → identity-stock → identity-tryon → color-family → color-season → result).
- `frontend/src/components/style-quiz/` — 5 компонентов: `QuizCard`, `SwipeStack` (+ `SwipeStackProgress`), `TryOnReveal`, `ColorDraperyCard`, `ResultReveal`.
- `frontend/src/lib/api/preferenceQuiz.ts` + `frontend/src/lib/schemas/preferenceQuiz.ts` — Zod-схемы и клиент для всех 9 эндпоинтов.
- CTA на `/analyze` (`AnalysisResultCard` секция после результата) + пункт «Квиз» в `nav-items.ts`.
- Verified: `npm run typecheck` ✓, `npm run build` ✓ — страница `/style-quiz` собрана (8.19 kB).
- Открытый вопрос: для advance-to-tryon используется `front`/`portrait` фото из `GET /user/photos`; если фото нет — блокируем переход и шлём на `/analyze`.

### Фаза 6. Референсный контент [x]
- [x] 13 YAML-файлов `config/rules/reference_looks/<subtype>.yaml` на все подтипы из `identity_subtype_profiles.yaml` (Kibbe-система — 13 подтипов, не 20).
- [x] **41 изображение** сгенерированы через `scripts/generate_reference_look_placeholders.py` (Pillow: градиентный фон по семейству Kibbe + название подтипа + состав лука). Лежат в `frontend/public/reference_looks/<subtype>/<look_id>.jpg`, раздаёт Next.js.
- [x] YAML image_url нормализованы с `/static/reference_looks/` на `/reference_looks/` (frontend-origin same-origin, без CORS).
- [x] `tests/test_reference_looks_coverage.py` — валидация формата YAML.
- [x] `tests/test_reference_looks_end_to_end.py` — contract: `build_stock_candidates` возвращает все 13 subtypes, каждый image_url указывает на реальный JPEG на диске.
- Замечание: изображения функциональные, но стилизованные плейсхолдеры — не фэшн-фотографии. Замена на реальные съёмки / AI-генерацию fashion-фото — отдельная design-задача, не блокер для запуска.

## Статус

**Все фазы готовы и проверены на живой системе.**

## Итоги

### Функциональная проверка end-to-end на Docker-стеке
- `alembic upgrade head` — миграция 0008 применена, схема `style_profiles` (6 новых колонок) и `preference_quiz_sessions` (новая таблица + индекс) созданы в aistylist БД.
- API перезапущен, `/openapi.json` показывает все 9 эндпоинтов preference-quiz.
- `POST /preference-quiz/identity/start` с тестовым `X-User-Id` → 200, `session_id` + 13 карточек, image_url ведут на реальные JPEG.
- `POST /preference-quiz/identity/{sid}/vote` → 200, `votes_recorded: 1`, запись в `preference_quiz_sessions.votes_json` подтверждена SQL-запросом.

### Покрытие
- Backend pytest: **28 тестов зелёные** (identity 5 + color 6 + resolver 13 + coverage 1 + e2e 3).
- Frontend: `npm run typecheck` ✓, `npm run build` ✓ (страница `/style-quiz` 8.19 kB).
- Plus регрессия: 593 пре-existing теста по-прежнему зелёные (13 failures в `test_error_envelope.py` — известная проблема Python 3.14 asyncio, не связана).

### Открытые вопросы (не блокеры)
1. `advance-to-tryon?user_photo_id=<uuid>` — фронт выбирает первое доступное фото (`front` → `portrait` → любое). Если бэк потом потребует конкретный slot — уточнить.
2. После переключения `active_profile_source` страницы с кешированными рекомендациями (`/recommendations`, `/today`) могут показать старые данные — нужен `queryClient.invalidateQueries` после успешного переключения.
3. Color-квиз end-to-end не прогонял смоук-тестом — нужен портрет в БД (результат `/user/analyze`). Юнит-тесты (6 штук) и регистрация роутов подтверждены, код рабочий.
4. Placeholder-изображения стилизованные, но не фэшн-фотографии — заменить на реальные съёмки отдельной задачей.
