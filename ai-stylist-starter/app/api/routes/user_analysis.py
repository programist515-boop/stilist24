"""Thin route layer for user analysis.

The route has exactly one job: turn three :class:`UploadFile` handles into
an ordered list of :class:`AnalysisPhotoUpload` objects and hand them to
:class:`UserAnalysisService`. Every failure mode maps to an HTTP status
code via a typed-exception catch block. No business logic, no direct
storage or DB calls, no feature extraction.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.storage import fresh_public_url
from app.repositories.user_photo_repository import UserPhotoRepository
from app.schemas.user_analysis import (
    AnalyzedPhotoOut,
    ColorOverrideIn,
    ColorOverrideOut,
    UserAnalyzeResponse,
)
from app.services.color_engine import ColorEngine
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
            "image_url": fresh_public_url(row.image_key, row.image_url),
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


@router.patch("/color-override", response_model=ColorOverrideOut)
def apply_color_override(
    body: ColorOverrideIn,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    """Apply manual corrections to the auto-detected color profile.

    Merges supplied manual_* fields into ``color_overrides_json``,
    re-scores the 12-season analysis using the corrected axes, and
    persists the result back to ``color_profile_json``.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.style_profile import StyleProfile

    row = db.query(StyleProfile).filter(StyleProfile.user_id == user_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="No style profile found — run /user/analyze first")

    existing_overrides: dict = dict(row.color_overrides_json or {})
    history: list = list(existing_overrides.get("override_history", []))

    applied: dict[str, str] = {}
    override_fields = {
        "manual_hair_color": body.manual_hair_color,
        "manual_eye_color": body.manual_eye_color,
        "manual_undertone": body.manual_undertone,
        "manual_selected_season": body.manual_selected_season,
    }
    for field, value in override_fields.items():
        if value is not None:
            existing_overrides[field] = value
            applied[field] = value

    if applied:
        history.append({"at": datetime.now(timezone.utc).isoformat(), "changed": applied})
        existing_overrides["override_history"] = history

    # Build the axes dict used for re-scoring: start from existing auto axes,
    # then apply manual_undertone override if present.
    existing_color: dict = dict(row.color_profile_json or {})
    axes: dict = dict(existing_color.get("axes", {}))
    if existing_overrides.get("manual_undertone"):
        axes["undertone"] = existing_overrides["manual_undertone"]

    # If user manually selected a season, skip re-scoring and use that season.
    manual_season = existing_overrides.get("manual_selected_season")
    if manual_season:
        engine = ColorEngine()
        palette = engine.get_palette(manual_season)
        palette_hex = palette["best_neutrals"] + palette["accent_colors"]
        color_result: dict = {
            **existing_color,
            "season_top_1": manual_season,
            "manual_override": True,
            "palette": palette,
            "palette_hex": palette_hex,
        }
    else:
        color_result = ColorEngine().analyze(axes) if axes else existing_color
        color_result["manual_override"] = bool(applied)

    # Persist updates
    stmt = (
        pg_insert(StyleProfile)
        .values(
            user_id=user_id,
            color_profile_json=color_result,
            color_overrides_json=existing_overrides,
        )
        .on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "color_profile_json": color_result,
                "color_overrides_json": existing_overrides,
            },
        )
    )
    db.execute(stmt)
    db.commit()

    return {
        "color": color_result,
        "overrides_applied": applied,
        "overrides_history_length": len(history),
    }
