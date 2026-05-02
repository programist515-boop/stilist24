# Квиз: лайки → подбор из гардероба + что докупить (вместо FASHN try-on)

**Цель.** В preference-квизе после стокового этапа вместо виртуальной примерки на пользователе — для каждого лайкнутого образа показать `matched_items` из его гардероба + `missing_slots` с подсказкой что докупить.

**Полный плановый файл сессии** — `C:\Users\user\.claude\plans\resilient-humming-dijkstra.md`.

## Решения по развилкам (зафиксированы)

- **Shopping-формат:** описание категории + характеристики из `missing_slots[].shopping_hint`. Без поиска по маркетплейсам.
- **Try-on этап:** удалить целиком. FASHN-адаптер и страница `/tryon` — НЕ трогаем.
- **Winner-типаж:** только по стоковым лайкам (Counter по subtype, confidence = top_likes / total_likes).

## Фазы

### Фаза 1. Backend: wardrobe-match сервис
- [x] `identity_quiz.build_wardrobe_match(session, items)` — извлекает liked stock-голоса, для каждого `(subtype, look_id)` дёргает `ReferenceMatcher._match_one_look()`. Кеши YAML/allowed-wardrobe per-subtype, дедупликация по like-order.
- [x] Pydantic: `IdentityWardrobeMatchResponse` + `IdentityLookMatchOut` + `WardrobeMatchedItemOut(slot, item_id, image_url, category, match_quality, match_reasons)` + `WardrobeMissingSlotOut(slot, requires, shopping_hint)`.
- [x] Endpoint `POST /preference-quiz/identity/{session}/wardrobe-match`. Обогащает matched_items превьюшками wardrobe-вещей через `fresh_public_url(image_key, image_url)`. 422 если лайков <3.

### Фаза 2. Backend: complete-identity по сток-голосам
- [x] `resolve_final_winner()` — Counter по subtype из stock-likes, confidence = top/total. Через общий хелпер `_iter_stock_likes()` (он же используется в `build_wardrobe_match` и `resolve_stock_stage`).

### Фаза 3. Backend: тесты
- [x] +6 новых кейсов в `test_preference_quiz_identity.py`: per-look match, dedupe по like-order, dislike+unknown skip, completeness, shopping_hint в missing_slot, ghost look_id, empty likes.
- [x] Переписаны старые try-on тесты под stock-формат. Удалён `_tryon_card` хелпер и зависимость от `STAGE_TRYON`.
- [x] **824/824 backend тестов passed** (полный sweep без cv2-зависимостей, ~18 минут).

### Фаза 4. Frontend: identity-match шаг
- [x] Step `identity-tryon` → `identity-match`, удалены: state `tryonCandidates`, мутация `advanceToTryonMutation`, компонент-функция `IdentityTryOnStep` в page.tsx, `<TryOnReveal>` импорт. Файл `TryOnReveal.tsx` удалён.
- [x] Новый `IdentityMatchStep.tsx`: карточка на каждый лайкнутый look — превью + completeness-progress + блок «У вас уже есть» (миниатюры matched-вещей с slot/category/quality-warning) + блок «Не хватает» (slot + shopping_hint). Кнопка «Готово, закрепить типаж» триггерит `completeIdentityMutation`.
- [x] В `IdentityStockStep` кнопка «Достаточно, к примерке» → «Готово, к подбору из гардероба» / «Показать как собрать».
- [x] Stepper labels: «Примерка» → «Из гардероба».
- [x] IntroStep копи переписан под новый flow (3 шага раньше → 4 шага сейчас).
- [x] Снят гейт `userPhotoId` для квиза (фото больше не нужно).

### Фаза 5. Frontend: API + Zod
- [x] `getWardrobeMatch(sessionId)` в [`preferenceQuiz.ts`](frontend/src/lib/api/preferenceQuiz.ts). Без особого таймаута — запрос быстрый.
- [x] Zod: `WardrobeMatchedItemSchema`, `WardrobeMissingSlotSchema`, `IdentityLookMatchSchema`, `IdentityWardrobeMatchResponseSchema`.
- [x] Удалены: `advanceToTryon`, `getTryonStatus`, `IdentityAdvanceToTryOnResponseSchema`, `IdentityTryOnStatusResponseSchema`, `IdentityTryOnCandidateSchema`, `TryOnJobStatusSchema`.

### Фаза 6. Cleanup
- [x] Удалены `build_tryon_finalists`, `_pick_tryon_item_for_subtype`, `_subtype_for_candidate_id`, `STAGE_TRYON` из `identity_quiz.py`.
- [x] Удалены route `POST /advance-to-tryon` и `GET /tryon-status`. Импорты `TryOnService`, `TryOnJob`, `Query` (для `user_photo_id`) убраны.
- [x] Из схем убраны `tryon_job_id` поле в `CandidateOut` и связанные tryon-схемы.
- [x] FASHN-адаптер ([`fashn_adapter.py`](ai-stylist-starter/app/services/fashn_adapter.py)) и страница `/tryon` НЕ тронуты.

### Фаза 7. Verification
- [x] `pytest tests/test_preference_quiz_identity.py` — 14/14 passed.
- [x] Полный backend sweep — 824/824 passed.
- [x] `tsc --noEmit` — clean.
- [x] `next build` — clean. `/style-quiz` route 8.3 KB → 10.3 KB (новый IdentityMatchStep).
- [x] Коммит `c87733e` запушен в main → auto-deploy на Amvera.
- [ ] Прод-smoke (curl `/api/health`, HTML `/style-quiz`, ручной прогон под учеткой с гардеробом) — за пользователем.

## Критические файлы

| Файл | Что |
|---|---|
| `ai-stylist-starter/app/services/preference_quiz/identity_quiz.py` | +build_wardrobe_match, переписать resolve_final_winner, удалить build_tryon_finalists |
| `ai-stylist-starter/app/api/routes/preference_quiz_identity.py` | +/wardrobe-match, −/advance-to-tryon, −/tryon-status |
| `ai-stylist-starter/app/schemas/preference_quiz.py` | +Wardrobe* схемы, −TryOn схемы |
| `ai-stylist-starter/tests/test_preference_quiz_identity.py` | +6 кейсов, −старые |
| `frontend/src/app/(app)/style-quiz/page.tsx` | step identity-tryon → identity-match |
| `frontend/src/lib/api/preferenceQuiz.ts` | +getWardrobeMatch, −advanceToTryon |
| `frontend/src/lib/schemas/preferenceQuiz.ts` | +match-схемы, −tryon-схемы |
| `frontend/src/components/style-quiz/IdentityMatchStep.tsx` | **новый** |
| `frontend/src/components/style-quiz/IdentityTryOnStep.tsx` | **удалить** |
| `frontend/src/components/style-quiz/TryOnReveal.tsx` | **удалить** |

## Итог сессии 2026-05-02 / 2026-05-03

**Реализовано целиком.** Все фазы [x], кроме ручной прод-приёмки (за пользователем).

**Что сделано:**
- Backend: новый `wardrobe-match` endpoint, переписан `resolve_final_winner` под stock-голоса, удалены `build_tryon_finalists` и связанные FASHN-роуты. 824/824 тестов зелёные.
- Frontend: `identity-tryon` step заменён на `identity-match` с новым компонентом `IdentityMatchStep.tsx`, удалён `TryOnReveal.tsx`, обновлены Zod-схемы и API-клиент. tsc + next build clean.
- Коммит `c87733e feat(style-quiz): подбор из гардероба + что докупить вместо try-on` запушен в main. Auto-deploy на Amvera.

**Ключевые архитектурные решения:**
- 80% логики переиспользовали из существующих компонентов (`ReferenceMatcher._match_one_look`, `MatchedItem`/`MissingSlot` dataclass'ы, `WardrobeRepository`, `gap_analysis_rules.yaml`). Новой матчинг-логики не написали.
- Полностью вычистили FASHN из квизового флоу. FASHN-адаптер и страница `/tryon` остались нетронутыми — это отдельная фича виртуальной примерки одежды.
- shopping-рекомендация — описание категории + характеристики (`shopping_hint` из YAML). Без поиска по маркетплейсам — отдельная итерация.
- winner-типаж: только по стоковым лайкам.

**Что осталось (post-deploy verification, не блокирует):**
- Ручная проверка флоу: лайкнуть 3+ образа → нажать «Готово, к подбору из гардероба» → должны появиться карточки «Из гардероба» с matched-вещами и shopping-хинтами.
- Проверить, что `complete-identity` записывает winner в `StyleProfile.kibbe_type_preference` (через UI «закрепить типаж»).

**Стоимость и время:**
- Общее время сессии: ~3 часа от первого Explore до коммита.
- Pytest sweep: ~18 минут (824 тестов с импортами SQLAlchemy/PIL).
- Frontend build: ~1 минута.
- Стоимость API: 0 (никаких внешних вызовов в этой сессии).

**Что можно было лучше:**
- Изначально я неверно понял задачу пользователя как «виртуальная try-on на фото пользователя» вместо «подбор из гардероба + что докупить». Это стоило целого предыдущего рефакторинга (timeout 240s на advance-to-tryon в коммите `13ca2e2`, который теперь стал не нужен). Урок: переспрашивать на user-stories формате до того, как писать код, особенно если фича включает «пробу» или «примерку».
- Можно было сделать Phase 1+2 одним коммитом без кода, чтобы пользователь мог посмотреть на бэкенд-контракт раньше. Но в данном случае пользователь явно просил «сразу пиши» — оправдано.

**Извлечённый урок:** ReferenceMatcher был спроектирован хорошо — `_match_one_look()` оказался idiomatic re-usable building block. Новая фича превратилась в очень тонкую обёртку поверх (~50 строк кода в `build_wardrobe_match`). Это пример того, как правильно проектировать сервисы: атомарные публичные методы, которые можно соединять в новые цепочки без переписки.
