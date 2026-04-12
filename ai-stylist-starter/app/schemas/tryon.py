"""Try-on input/output schemas.

Pins the shapes currently emitted by ``app.api.routes.tryon``:

* :class:`TryOnGenerateIn` — request body for ``POST /tryon/generate``.
  Replaces the inline ``TryOnIn`` in the route module; field types are
  unchanged.
* :class:`TryOnJobOut` — unified shape for both ``POST /tryon/generate``
  and ``GET /tryon/{job_id}``. Fields mirror ``_serialize_job`` +
  :meth:`TryOnService._build_response` with two additions
  (``created_at`` / ``updated_at``) that were always present on the
  :class:`TryOnJob` ORM row but never surfaced on the wire.

Phase 2 only defines the schemas. The route edits (attach
``response_model=``, project ``created_at`` / ``updated_at`` from the
ORM row) happen in Phase 3.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TryOnGenerateIn(BaseModel):
    """Payload for ``POST /tryon/generate``.

    Both ids are typed as real UUIDs so malformed inputs are rejected
    by Pydantic before the service is even constructed.
    """

    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    user_photo_id: uuid.UUID


class TryOnJobOut(BaseModel):
    """Wire representation of a :class:`TryOnJob`.

    Shape = ``_serialize_job`` in ``app/api/routes/tryon.py`` + two new
    timestamp fields. ``job_id`` is a plain string (UUID serialised as
    ``str(job.id)``) to match the current wire format byte-for-byte.

    ``metadata`` is ``dict[str, Any]`` because it's provider-dependent
    (FASHN raw dump, etc.). ``note`` carries
    :data:`app.services.tryon_service.TRY_ON_DISCLAIMER`.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str
    provider: str
    provider_job_id: str | None
    result_image_key: str | None
    result_image_url: str | None
    metadata: dict[str, Any]
    error_message: str | None = None
    note: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


__all__ = ["TryOnGenerateIn", "TryOnJobOut"]
