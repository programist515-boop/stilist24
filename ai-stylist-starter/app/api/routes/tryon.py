"""Try-on routes — thin layer over :class:`TryOnService`.

Phase 3 cleanup:

* Input schema ``TryOnGenerateIn`` moved to :mod:`app.schemas.tryon`
  so the OpenAPI contract and the route signature share one source of
  truth.
* Both routes now carry ``response_model=TryOnJobOut``, which locks
  the wire shape (``extra="forbid"``) and adds two previously invisible
  fields: ``created_at`` and ``updated_at``, pulled from the ORM row.
* ``_serialize_job`` (GET) and :meth:`TryOnService._build_response`
  (POST) both emit the same key set now — no more drift between the
  two entry points.

Error handling already goes through the typed service exceptions;
they map to the envelope via :func:`app.api.errors.http_error_handler`.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_persona_id, get_current_user_id, get_db
from app.core.storage import fresh_public_url
from app.repositories.tryon_repository import TryOnRepository
from app.schemas.tryon import TryOnGenerateIn, TryOnJobOut
from app.services.tryon_service import (
    TRY_ON_DISCLAIMER,
    TryOnAssetError,
    TryOnNotFoundError,
    TryOnPersistenceError,
    TryOnProviderError,
    TryOnService,
    TryOnStorageError,
)

router = APIRouter()


def _iso_or_none(value) -> str | None:
    """Safely render a datetime-like attribute as an ISO string."""
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


def _serialize_job(job) -> dict:
    """Build the wire dict for a :class:`TryOnJob` row.

    Shape is locked to :class:`TryOnJobOut`. ``created_at`` /
    ``updated_at`` are surfaced as ISO strings (or ``None`` on fake
    in-memory rows) so the GET and POST endpoints emit identical keys.
    """
    return {
        "job_id": str(job.id),
        "status": job.status,
        "provider": job.provider,
        "provider_job_id": job.provider_job_id,
        "result_image_key": job.result_image_key,
        "result_image_url": fresh_public_url(job.result_image_key, job.result_image_url),
        "metadata": job.metadata_json or {},
        "error_message": job.error_message,
        "note": TRY_ON_DISCLAIMER,
        "created_at": _iso_or_none(getattr(job, "created_at", None)),
        "updated_at": _iso_or_none(getattr(job, "updated_at", None)),
    }


@router.post("/generate", response_model=TryOnJobOut)
async def generate_tryon(
    payload: TryOnGenerateIn,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    try:
        return await TryOnService(db).generate(
            user_id=user_id,
            item_id=payload.item_id,
            user_photo_id=payload.user_photo_id,
        )
    except TryOnNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TryOnAssetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TryOnProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except TryOnStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except TryOnPersistenceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{job_id}", response_model=TryOnJobOut)
def get_tryon_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Tryon jobs are keyed by the account user_id, not persona.

    We still accept ``persona_id`` in the dependency so the frontend
    always sends a consistent header set, but ownership is checked at
    the account level (a job spans whichever persona was active when
    it was created).
    """
    repo = TryOnRepository(db)
    job = repo.get_by_id(job_id)
    if job is None or job.user_id != user_id:
        raise HTTPException(status_code=404, detail="try-on job not found")
    return _serialize_job(job)
