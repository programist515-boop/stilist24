import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.repositories.tryon_repository import TryOnRepository
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


class TryOnIn(BaseModel):
    item_id: uuid.UUID
    user_photo_id: uuid.UUID


def _serialize_job(job) -> dict:
    return {
        "job_id": str(job.id),
        "status": job.status,
        "provider": job.provider,
        "provider_job_id": job.provider_job_id,
        "result_image_key": job.result_image_key,
        "result_image_url": job.result_image_url,
        "metadata": job.metadata_json or {},
        "error_message": job.error_message,
        "note": TRY_ON_DISCLAIMER,
    }


@router.post("/generate")
async def generate_tryon(
    payload: TryOnIn,
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


@router.get("/{job_id}")
def get_tryon_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    repo = TryOnRepository(db)
    job = repo.get_by_id(job_id)
    if job is None or job.user_id != user_id:
        raise HTTPException(status_code=404, detail="try-on job not found")
    return _serialize_job(job)
