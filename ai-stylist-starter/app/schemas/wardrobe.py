"""Wardrobe response/input schemas.

Pins the shapes currently emitted by :mod:`app.api.routes.wardrobe`:

* :class:`WardrobeItemOut` — matches ``_serialize(item)`` exactly.
* :class:`WardrobeListOut` — the list wrapper (``{items, count}``) that
  replaces the bare JSON array ``GET /wardrobe/items`` returns today.
* :class:`WardrobeConfirmIn` — the payload for ``POST /wardrobe/confirm``,
  with ``item_id`` typed as a real :class:`uuid.UUID` so Pydantic
  rejects malformed ids before they reach the route. Replaces the
  existing ``item_id: str`` version currently defined inline in the
  route module.
* :class:`WardrobeConfirmOut` — the 200 success body for
  ``POST /wardrobe/confirm`` (``{item: WardrobeItemOut}``). A 404
  case goes through the error envelope, not this model.

The ``id`` field is a plain ``str`` rather than ``uuid.UUID`` to match
the current wire format (``str(item.id)``) byte-for-byte. Phase 3 keeps
that behaviour — we're only adding schemas, not changing the wire.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WardrobeItemOut(BaseModel):
    """Single wardrobe item as exposed on the wire.

    Shape is locked to ``_serialize`` in ``app/api/routes/wardrobe.py``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Wardrobe item id (UUID as string)")
    category: str | None
    attributes: dict[str, Any]
    image_key: str | None
    image_url: str
    is_verified: bool


class WardrobeListOut(BaseModel):
    """Wrapped list response for ``GET /wardrobe/items``.

    The bare JSON array currently returned by the route is a
    pagination-hostile shape; wrapping in ``{items, count}`` leaves
    room for ``cursor``/``next`` later without another breaking change.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[WardrobeItemOut]
    count: int


class WardrobeConfirmIn(BaseModel):
    """Payload for ``POST /wardrobe/confirm``.

    ``item_id`` is a real UUID — any malformed string is rejected by
    Pydantic and rewritten by :func:`app.api.errors.validation_error_handler`
    into a ``VALIDATION_ERROR`` envelope, keeping the UUID parse out of
    the route layer.
    """

    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    attributes: dict[str, Any]


class WardrobeConfirmOut(BaseModel):
    """Success body for ``POST /wardrobe/confirm``.

    The ``not_found`` case is no longer surfaced here — it goes through
    the 404 error envelope. The field ``item`` mirrors the current
    ``{"status": "updated", "item": ...}`` but drops the cosmetic
    ``status`` string in favour of the HTTP status.
    """

    model_config = ConfigDict(extra="forbid")

    item: WardrobeItemOut


__all__ = [
    "WardrobeConfirmIn",
    "WardrobeConfirmOut",
    "WardrobeItemOut",
    "WardrobeListOut",
]
