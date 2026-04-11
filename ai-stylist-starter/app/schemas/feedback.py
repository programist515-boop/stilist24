from pydantic import BaseModel, Field
from typing import Any


class FeedbackIn(BaseModel):
    event_type: str = Field(
        pattern="^(item_liked|item_disliked|outfit_liked|outfit_disliked|item_worn|item_ignored|tryon_opened|outfit_saved|outfit_worn)$"
    )
    payload: dict[str, Any]
