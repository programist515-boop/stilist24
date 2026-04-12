"""Thin route layer for user analysis.

The route has exactly one job: turn three :class:`UploadFile` handles into
an ordered list of :class:`AnalysisPhotoUpload` objects and hand them to
:class:`UserAnalysisService`. Every failure mode maps to an HTTP status
code via a typed-exception catch block. No business logic, no direct
storage or DB calls, no feature extraction.
"""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.repositories.user_photo_repository import UserPhotoRepository
from app.schemas.user_analysis import AnalyzedPhotoOut, UserAnalyzeResponse
from app.services.user_analysis_service import (
    AnalysisPhotoUpload,
    UserAnalysisPersistenceError,
    UserAnalysisService,
    UserAnalysisStorageError,
    UserAnalysisValidationError,
)

router = APIRouter()


@router.get("/photos", response_model=list[AnalyzedPhotoOut])
def list_user_photos(
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[dict]:
    """Return the caller's stored reference photos, freshest first.

    This endpoint exists so the frontend does not have to rely on a
    stale ``localStorage`` snapshot of the last ``/user/analyze``
    response. Downstream screens (``/tryon``, "Today") always read
    the live rows, so fixes to the storage URL (e.g. switching to a
    browser-reachable ``S3_PUBLIC_BASE_URL``) take effect on the next
    page load without forcing the user to re-run the analysis.
    """
    rows = UserPhotoRepository(db).list_by_user(user_id)
    return [
        {
            "id": str(row.id),
            "slot": row.slot,
            "image_key": row.image_key,
            "image_url": row.image_url,
        }
        for row in rows
    ]


@router.post("/analyze", response_model=UserAnalyzeResponse)
async def analyze_user(
    front_photo: UploadFile = File(...),
    side_photo: UploadFile = File(...),
    portrait_photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    uploads = [
        AnalysisPhotoUpload(
            slot="front",
            data=await front_photo.read(),
            content_type=front_photo.content_type or "",
            filename=front_photo.filename,
        ),
        AnalysisPhotoUpload(
            slot="side",
            data=await side_photo.read(),
            content_type=side_photo.content_type or "",
            filename=side_photo.filename,
        ),
        AnalysisPhotoUpload(
            slot="portrait",
            data=await portrait_photo.read(),
            content_type=portrait_photo.content_type or "",
            filename=portrait_photo.filename,
        ),
    ]
    try:
        return UserAnalysisService(db).analyze(user_id=user_id, uploads=uploads)
    except UserAnalysisValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UserAnalysisStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except UserAnalysisPersistenceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
