"""Auth routes: email+password signup/login, JWT issuance, and ``/me``.

The token's ``sub`` claim is the user's UUID (as a string). The
frontend stores the access token locally and attaches it to every
subsequent request as ``Authorization: Bearer <token>``. The legacy
``X-User-Id`` header continues to work as a dev fallback — see
``app.api.deps.get_current_user_id``.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.repositories.user_repository import UserRepository

router = APIRouter()


# ------------------------------------------------------------- schemas


class SignupIn(BaseModel):
    # max_length=64 keeps us comfortably under bcrypt's 72-byte ceiling
    # even for UTF-8 passwords (each char can take up to 4 bytes).
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class OAuthIn(BaseModel):
    provider: str
    token: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID


class MeOut(BaseModel):
    user_id: uuid.UUID
    email: str | None
    auth_provider: str


# ------------------------------------------------------------- helpers


def _issue_token(user_id: uuid.UUID) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(subject=str(user_id)),
        user_id=user_id,
    )


# ------------------------------------------------------------- routes


@router.post("/signup", response_model=TokenOut, status_code=201)
def signup(payload: SignupIn, db: Session = Depends(get_db)) -> TokenOut:
    """Register a new email+password account and return an access token."""
    repo = UserRepository(db)
    if repo.get_by_email(payload.email) is not None:
        raise HTTPException(status_code=409, detail="email already registered")
    user = repo.create(
        auth_provider="email",
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    return _issue_token(user.id)


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    """Authenticate an existing account by email+password."""
    user = UserRepository(db).get_by_email(payload.email)
    if user is None or user.password_hash is None:
        raise HTTPException(status_code=401, detail="invalid email or password")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")
    return _issue_token(user.id)


@router.get("/me", response_model=MeOut)
def me(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MeOut:
    """Return the authenticated caller's profile — exercises the token gate."""
    user = UserRepository(db).get_by_id(current_user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")
    return MeOut(
        user_id=user.id,
        email=user.email,
        auth_provider=user.auth_provider,
    )


@router.post("/oauth", response_model=TokenOut)
def oauth_login(payload: OAuthIn, db: Session = Depends(get_db)) -> TokenOut:
    """OAuth login stub: provider id is trusted as-is for now.

    Real OAuth token verification against each provider is a separate
    track. This endpoint creates or fetches a user keyed by
    ``(auth_provider, provider_id)`` and returns a JWT so the rest of
    the flow is identical to email+password.
    """
    from sqlalchemy import select

    from app.models.user import User

    if payload.provider not in {"google", "yandex", "telegram"}:
        raise HTTPException(status_code=400, detail="Unsupported provider")

    existing = db.execute(
        select(User).where(
            User.auth_provider == payload.provider,
            User.provider_id == payload.token,
        )
    ).scalar_one_or_none()

    user = existing or UserRepository(db).create(
        auth_provider=payload.provider,
        provider_id=payload.token,
    )
    return _issue_token(user.id)
