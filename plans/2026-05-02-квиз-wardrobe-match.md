# Квиз: лайки → подбор из гардероба + что докупить (вместо FASHN try-on)

**Цель.** В preference-квизе после стокового этапа вместо виртуальной примерки на пользователе — для каждого лайкнутого образа показать `matched_items` из его гардероба + `missing_slots` с подсказкой что докупить.

**Полный плановый файл сессии** — `C:\Users\user\.claude\plans\resilient-humming-dijkstra.md`.

## Решения по развилкам (зафиксированы)

- **Shopping-формат:** описание категории + характеристики из `missing_slots[].shopping_hint`. Без поиска по маркетплейсам.
- **Try-on этап:** удалить целиком. FASHN-адаптер и страница `/tryon` — НЕ трогаем.
- **Winner-типаж:** только по стоковым лайкам (Counter по subtype, confidence = top_likes / total_likes).

## Фазы

### Фаза 1. Backend: wardrobe-match сервис
- [ ] `identity_quiz.build_wardrobe_match(session, items)` — извлекает liked stock-голоса, для каждого `(subtype, look_id)` дёргает `ReferenceMatcher._match_one_look()`, возвращает `list[ReferenceLookMatch]`.
- [ ] Pydantic-схема `IdentityWardrobeMatchResponse` (looks[] с matched_items/missing_slots/completeness).
- [ ] Endpoint `POST /preference-quiz/identity/{session}/wardrobe-match`.

### Фаза 2. Backend: complete-identity по сток-голосам
- [ ] `resolve_final_winner()` — Counter по subtype из stock-likes, confidence = top/total.

### Фаза 3. Backend: тесты
- [ ] +6 кейсов: per-look match, фильтр dislikes/tryon-стадии, completeness, shopping_hint, winner из stock, reject empty.
- [ ] − старые try-on тесты.

### Фаза 4. Frontend: identity-match шаг
- [ ] Удалить step `identity-tryon`, `IdentityTryOnStep.tsx`, `TryOnReveal.tsx`, `advanceToTryonMutation`.
- [ ] Добавить step `identity-match` + новый `IdentityMatchStep.tsx`.
- [ ] Кнопка «Достаточно, к примерке» → «Показать как собрать».
- [ ] В `result` шаг: winner card теперь живёт после wardrobe-match.

### Фаза 5. Frontend: API + Zod
- [ ] `getWardrobeMatch(sessionId)` в `preferenceQuiz.ts`.
- [ ] Zod-схемы: WardrobeMatchedItem, WardrobeMissingSlot, IdentityLookMatch, IdentityWardrobeMatchResponse.
- [ ] Удалить advanceToTryon, getTryonStatus и их схемы.

### Фаза 6. Cleanup
- [ ] Удалить `build_tryon_finalists`, advance-to-tryon route, tryon-status route.
- [ ] FASHN-адаптер и `/tryon` страница — НЕ трогаем.

### Фаза 7. Verification
- [ ] `pytest tests/test_preference_quiz_identity.py` зелёный.
- [ ] `tsc --noEmit + next build` зелёные.
- [ ] Прод-smoke по `/api/health` и HTML страниц.

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

## Итог сессии

_(будет заполнено по итогам реализации)_
