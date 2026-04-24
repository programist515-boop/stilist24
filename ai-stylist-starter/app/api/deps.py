import uuid

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import TokenError, decode_access_token
from app.models.user import User
from app.repositories.persona_repository import PersonaRepository


def _user_id_from_bearer(authorization: str | None) -> uuid.UUID | None:
    """Extract a user id from an ``Authorization: Bearer <jwt>`` header.

    Returns ``None`` when the header is missing/malformed. Raises 401
    when a token is present but invalid/expired — we do not silently
    downgrade to dev-fallback in that case, otherwise an attacker with
    an expired token could trick the API into trusting ``X-User-Id``.
    """
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=f"invalid or expired token: {exc}")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="token missing 'sub'")
    try:
        return uuid.UUID(sub)
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="token 'sub' is not a uuid")


def get_current_user_id(
    user_id: uuid.UUID | None = Query(default=None),
    x_user_id: uuid.UUID | None = Header(default=None, alias="X-User-Id"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> uuid.UUID:
    """Resolve the acting user id for repository-scoped operations.

    Resolution order (first match wins):

    1. ``Authorization: Bearer <jwt>`` — the real auth flow. The token
       is decoded and its ``sub`` claim is the canonical user id. No
       stub upsert: the user must already exist because signup created
       it before the token was issued.
    2. ``X-User-Id`` header or ``user_id`` query param — the dev
       fallback. We upsert a stub ``User`` row with ``auth_provider='dev'``
       so downstream foreign keys don't fire on first request from a
       brand-new browser UUID. This path stays until the frontend fully
       migrates to JWT, and is gated by the presence of the header —
       production deployments can drop it by stripping the header at
       the edge.
    """
    bearer_uid = _user_id_from_bearer(authorization)
    if bearer_uid is not None:
        # Real auth path: user must already exist (signup created them).
        # We deliberately do NOT upsert here — if a token references a
        # non-existent user, that's a hard error, not a silent recovery.
        existing = db.get(User, bearer_uid)
        if existing is None:
            raise HTTPException(status_code=401, detail="token user no longer exists")
        return bearer_uid

    resolved = user_id or x_user_id
    if resolved is None:
        raise HTTPException(status_code=401, detail="user_id is required")

    stmt = (
        pg_insert(User)
        .values(id=resolved, auth_provider="dev")
        .on_conflict_do_nothing(index_elements=["id"])
    )
    db.execute(stmt)
    db.commit()

    return resolved


def get_current_persona_id(
    x_persona_id: uuid.UUID | None = Header(default=None, alias="X-Persona-Id"),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> uuid.UUID:
    """Resolve the current persona for repository-scoped operations.

    Resolution order:

    1. ``X-Persona-Id`` header — explicit persona selection from the
       frontend's persona switcher. Validated to belong to the calling
       user (prevents horizontal IDOR).
    2. Fallback to the user's primary persona. For brand-new dev users
       created via ``X-User-Id`` fallback, the primary persona is
       created on the fly (migration backfill never ran for them).
    """
    repo = PersonaRepository(db)
    if x_persona_id is not None:
        if not repo.belongs_to(x_persona_id, current_user_id):
            raise HTTPException(status_code=403, detail="persona does not belong to user")
        return x_persona_id
    return repo.ensure_primary(current_user_id).id


__all__ = ["get_db", "get_current_user_id", "get_current_persona_id"]
