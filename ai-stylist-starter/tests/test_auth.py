"""Tests for email+password auth routes and JWT-based access.

Pattern mirrors other route tests in this suite (see ``test_events.py``):
we exercise handler functions directly with a mocked DB/repository,
and we cover ``app.core.security`` with pure-Python unit tests.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.api.routes.auth import LoginIn, SignupIn, login, signup
from app.core.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from fastapi import HTTPException


# ------------------------------------------------------------ security unit


class TestPasswordHashing:
    def test_hash_verifies(self):
        h = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", h) is True

    def test_wrong_password_rejected(self):
        h = hash_password("right")
        assert verify_password("wrong", h) is False


class TestToken:
    def test_roundtrip_sub_preserved(self):
        uid = uuid.uuid4()
        token = create_access_token(subject=str(uid))
        payload = decode_access_token(token)
        assert payload["sub"] == str(uid)
        assert "exp" in payload

    def test_tampered_signature_raises(self):
        token = create_access_token(subject=str(uuid.uuid4()))
        # Flip a byte in the signature section (last chunk after the 2nd dot).
        tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")
        with pytest.raises(TokenError):
            decode_access_token(tampered)

    def test_expired_token_raises(self):
        from datetime import datetime, timedelta, timezone

        from jose import jwt

        from app.core.config import settings

        payload = {
            "sub": str(uuid.uuid4()),
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        }
        expired = jwt.encode(
            payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
        )
        with pytest.raises(TokenError):
            decode_access_token(expired)


# ------------------------------------------------------------ signup route


class TestSignupRoute:
    def test_creates_user_and_issues_token(self):
        db = MagicMock()
        created_user = MagicMock()
        created_user.id = uuid.uuid4()

        with patch("app.api.routes.auth.UserRepository") as MockRepo:
            MockRepo.return_value.get_by_email.return_value = None
            MockRepo.return_value.create.return_value = created_user
            result = signup(
                payload=SignupIn(email="alice@example.com", password="hunter22!"),
                db=db,
            )

        MockRepo.return_value.get_by_email.assert_called_once_with("alice@example.com")
        create_kwargs = MockRepo.return_value.create.call_args.kwargs
        assert create_kwargs["auth_provider"] == "email"
        assert create_kwargs["email"] == "alice@example.com"
        # password must be hashed, never stored plaintext
        assert create_kwargs["password_hash"] != "hunter22!"
        assert verify_password("hunter22!", create_kwargs["password_hash"])

        assert result.user_id == created_user.id
        assert result.token_type == "bearer"
        assert decode_access_token(result.access_token)["sub"] == str(created_user.id)

    def test_rejects_duplicate_email(self):
        db = MagicMock()
        with patch("app.api.routes.auth.UserRepository") as MockRepo:
            MockRepo.return_value.get_by_email.return_value = MagicMock()  # exists
            with pytest.raises(HTTPException) as exc:
                signup(
                    payload=SignupIn(email="taken@example.com", password="hunter22!"),
                    db=db,
                )
        assert exc.value.status_code == 409

    def test_rejects_short_password(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SignupIn(email="alice@example.com", password="short")


# ------------------------------------------------------------- login route


class TestLoginRoute:
    def _make_user(self, password: str) -> MagicMock:
        user = MagicMock()
        user.id = uuid.uuid4()
        user.password_hash = hash_password(password)
        return user

    def test_success(self):
        db = MagicMock()
        user = self._make_user("hunter22!")
        with patch("app.api.routes.auth.UserRepository") as MockRepo:
            MockRepo.return_value.get_by_email.return_value = user
            result = login(
                payload=LoginIn(email="alice@example.com", password="hunter22!"),
                db=db,
            )
        assert result.user_id == user.id
        assert decode_access_token(result.access_token)["sub"] == str(user.id)

    def test_wrong_password_returns_401(self):
        db = MagicMock()
        user = self._make_user("correct")
        with patch("app.api.routes.auth.UserRepository") as MockRepo:
            MockRepo.return_value.get_by_email.return_value = user
            with pytest.raises(HTTPException) as exc:
                login(
                    payload=LoginIn(email="alice@example.com", password="wrong"),
                    db=db,
                )
        assert exc.value.status_code == 401

    def test_missing_user_returns_401(self):
        db = MagicMock()
        with patch("app.api.routes.auth.UserRepository") as MockRepo:
            MockRepo.return_value.get_by_email.return_value = None
            with pytest.raises(HTTPException) as exc:
                login(
                    payload=LoginIn(email="ghost@example.com", password="whatever!"),
                    db=db,
                )
        assert exc.value.status_code == 401

    def test_user_without_password_hash_returns_401(self):
        # OAuth-only accounts have no password_hash; email+password
        # login must refuse them instead of crashing.
        db = MagicMock()
        user = MagicMock()
        user.id = uuid.uuid4()
        user.password_hash = None
        with patch("app.api.routes.auth.UserRepository") as MockRepo:
            MockRepo.return_value.get_by_email.return_value = user
            with pytest.raises(HTTPException) as exc:
                login(
                    payload=LoginIn(email="oauth@example.com", password="anything!"),
                    db=db,
                )
        assert exc.value.status_code == 401


# ------------------------------------------------------- token gate (deps)


class TestTokenGate:
    """``get_current_user_id`` resolves bearer tokens before dev fallback."""

    def _call(self, *, authorization=None, x_user_id=None, db=None):
        from app.api.deps import get_current_user_id

        return get_current_user_id(
            user_id=None,
            x_user_id=x_user_id,
            authorization=authorization,
            db=db or MagicMock(),
        )

    def test_valid_bearer_returns_token_user_id(self):
        uid = uuid.uuid4()
        token = create_access_token(subject=str(uid))
        db = MagicMock()
        db.get.return_value = MagicMock()  # user exists
        resolved = self._call(authorization=f"Bearer {token}", db=db)
        assert resolved == uid

    def test_bearer_for_nonexistent_user_returns_401(self):
        token = create_access_token(subject=str(uuid.uuid4()))
        db = MagicMock()
        db.get.return_value = None  # user deleted
        with pytest.raises(HTTPException) as exc:
            self._call(authorization=f"Bearer {token}", db=db)
        assert exc.value.status_code == 401

    def test_invalid_bearer_returns_401_without_dev_fallback(self):
        # Even when X-User-Id is supplied, a malformed token must fail —
        # otherwise an attacker could present a broken token and have the
        # server silently trust X-User-Id.
        fallback_uid = uuid.uuid4()
        with pytest.raises(HTTPException) as exc:
            self._call(authorization="Bearer not-a-token", x_user_id=fallback_uid)
        assert exc.value.status_code == 401

    def test_missing_authorization_falls_back_to_x_user_id(self):
        fallback_uid = uuid.uuid4()
        db = MagicMock()
        resolved = self._call(x_user_id=fallback_uid, db=db)
        assert resolved == fallback_uid
        # dev fallback path upserts a stub User
        assert db.execute.called
        assert db.commit.called

    def test_neither_bearer_nor_x_user_id_returns_401(self):
        with pytest.raises(HTTPException) as exc:
            self._call()
        assert exc.value.status_code == 401
