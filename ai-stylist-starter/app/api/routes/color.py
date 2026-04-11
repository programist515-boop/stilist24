from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class DrapingIn(BaseModel):
    pair_id: str
    better: str


@router.post("/drape")
def save_drape(payload: DrapingIn) -> dict:
    return {"status": "saved", "pair_id": payload.pair_id, "better": payload.better}
