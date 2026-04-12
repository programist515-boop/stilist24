import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.schemas.today import TodayResponse
from app.services.today_service import TodayService

router = APIRouter()


@router.get("", response_model=TodayResponse)
def get_today(
    weather: str | None = None,
    occasion: str | None = None,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    return TodayService(db).get_today(
        user_id=user_id, weather=weather, occasion=occasion
    )
