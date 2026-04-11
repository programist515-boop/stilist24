import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.services.insights_service import InsightsService

router = APIRouter()


@router.get("/weekly")
def weekly_insights(
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    return InsightsService(db).weekly(user_id=user_id)
