import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.schemas.feedback import FeedbackIn
from app.services.feedback_service import FeedbackService

router = APIRouter()


@router.post("")
def save_feedback(
    payload: FeedbackIn,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict:
    FeedbackService(db).process(user_id, payload.event_type, payload.payload)
    return {"status": "ok", "event_type": payload.event_type, "payload": payload.payload}
