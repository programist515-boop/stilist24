import uuid

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User


def get_current_user_id(
    user_id: uuid.UUID | None = Query(default=None),
    x_user_id: uuid.UUID | None = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> uuid.UUID:
    """Resolve the acting user id for repository-scoped operations.

    Real JWT-based auth is part of the auth step, not STEP 1. Until then,
    routes accept the user id via the ``user_id`` query parameter or the
    ``X-User-Id`` header so the repository layer can be exercised.

    Dev-convenience: if the caller presents a ``user_id`` that does not
    exist yet (e.g. a brand-new browser UUID minted in local storage by
    the frontend), we upsert a stub ``User`` row with ``auth_provider='dev'``
    so that downstream foreign keys (``user_photos.user_id``,
    ``tryon_jobs.user_id``, ``wardrobe_items.user_id``, …) don't fire on
    first request. The upsert is idempotent and concurrency-safe thanks
    to ``INSERT ... ON CONFLICT DO NOTHING``. When real auth lands this
    block is removed and replaced with a JWT-issued user id.
    """
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


__all__ = ["get_db", "get_current_user_id"]
