from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from app.core.security import create_access_token

router = APIRouter()


class OAuthIn(BaseModel):
    provider: str
    token: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


@router.post("/oauth")
def oauth_login(payload: OAuthIn) -> dict:
    if payload.provider not in {"google", "yandex", "telegram"}:
        raise HTTPException(status_code=400, detail="Unsupported provider")
    return {
        "access_token": create_access_token(subject=f"oauth:{payload.provider}"),
        "refresh_token": "stub-refresh",
        "token_type": "bearer",
    }


@router.post("/login")
def login(payload: LoginIn) -> dict:
    return {
        "access_token": create_access_token(subject=payload.email),
        "refresh_token": "stub-refresh",
        "token_type": "bearer",
    }
