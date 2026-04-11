import uuid
from fastapi import Header, HTTPException, Query

from app.core.database import get_db


def get_current_user_id(
    user_id: uuid.UUID | None = Query(default=None),
    x_user_id: uuid.UUID | None = Header(default=None, alias="X-User-Id"),
) -> uuid.UUID:
    """Resolve the acting user id for repository-scoped operations.

    Real JWT-based auth is part of the auth step, not STEP 1. Until then,
    routes accept the user id via the ``user_id`` query parameter or the
    ``X-User-Id`` header so the repository layer can be exercised.
    """
    resolved = user_id or x_user_id
    if resolved is None:
        raise HTTPException(status_code=401, detail="user_id is required")
    return resolved


__all__ = ["get_db", "get_current_user_id"]
