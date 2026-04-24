"""API-роуты для color try-on.

Три эндпоинта:

* ``POST /color-tryon/{item_id}``  — запускает генерацию (синхронно).
* ``GET  /color-tryon/{item_id}``  — возвращает кэш (генерация по
  требованию, чтобы клиенту не пришлось думать о порядке вызовов).
* ``POST /color-tryon/{item_id}/feedback`` — записывает лайк/дизлайк
  в ``color_vector_json``.

Синхронный POST — компромисс MVP: первая генерация на 5–10 цветов
палитры занимает секунды, не десятки минут. Если станет критично —
легко превратить в BackgroundTasks через одну строку (``.add_task(...)``).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_persona_id, get_current_user_id, get_db
from app.schemas.color_tryon import (
    ColorTryOnFeedback,
    ColorTryOnResponse,
)
from app.services.color_try_on_service import (
    ColorTryOnAssetError,
    ColorTryOnNotFoundError,
    ColorTryOnRenderError,
    ColorTryOnService,
    ColorTryOnStorageError,
)

router = APIRouter()


@router.post("/{item_id}", response_model=ColorTryOnResponse)
def generate_color_tryon(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ColorTryOnResponse:
    """Запустить перекрас вещи в цвета палитры пользователя.

    Если часть вариантов уже лежит в S3 — они возвращаются из кэша,
    новые — генерируются HSV-перекрасом и сохраняются рядом.
    """
    try:
        return ColorTryOnService(db).build(user_id=user_id, item_id=item_id)
    except ColorTryOnNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ColorTryOnAssetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ColorTryOnStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ColorTryOnRenderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{item_id}", response_model=ColorTryOnResponse)
def get_color_tryon(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ColorTryOnResponse:
    """Вернуть color-tryon из кэша (или сгенерировать при первом визите).

    Метод идемпотентный: повторный вызов для той же (item, палитра)
    возвращает тот же набор URL.
    """
    try:
        return ColorTryOnService(db).build(user_id=user_id, item_id=item_id)
    except ColorTryOnNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ColorTryOnAssetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ColorTryOnStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ColorTryOnRenderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{item_id}/feedback")
def record_color_tryon_feedback(
    item_id: uuid.UUID,
    payload: ColorTryOnFeedback,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Отметить конкретный вариант как «нравится / не нравится».

    Feedback идёт в :class:`PersonalizationService.record_color_preference`
    и постепенно учит персональный color_vector пользователя.
    """
    service = ColorTryOnService(db)
    # Ранняя проверка: item существует и принадлежит активной персоне.
    item = service.wardrobe.get_by_id(item_id)
    if item is None or item.persona_id != persona_id:
        raise HTTPException(status_code=404, detail="item not found")

    service.record_feedback(
        user_id=user_id,
        item_id=item_id,
        variant_hex=payload.variant_hex,
        liked=payload.liked,
    )
    return {
        "status": "ok",
        "item_id": str(item_id),
        "variant_hex": payload.variant_hex,
        "liked": payload.liked,
    }
