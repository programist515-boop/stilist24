"""User analysis response schema.

Pins the shape of ``POST /user/analyze``, which is the public face of
:class:`app.services.user_analysis_service.UserAnalysisService.analyze`.

* :class:`AnalyzedPhotoOut` — one persisted photo reference, matching
  the dict entries the service appends to its ``persisted`` list.
* :class:`UserAnalyzeResponse` — the top-level response body. The
  ``kibbe`` / ``color`` fields are modelled as open dicts because
  :class:`app.services.identity_engine.IdentityEngine.analyze` and
  :class:`app.services.color_engine.ColorEngine.analyze` return
  engine-defined shapes (family scores, main type, alternatives, etc.)
  that evolve with the rule YAML. Locking the outer envelope is what
  the frontend needs; the inner analysis payload stays loose on
  purpose.

The key name ``kibbe`` is kept as-is per the Phase 0 decision — no
rename to ``identity`` in this pass.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AnalyzedPhotoOut(BaseModel):
    """One persisted user photo as surfaced in ``/user/analyze``.

    Mirrors the dict built in ``UserAnalysisService.analyze`` around
    ``persisted.append({...})``. ``id`` is a UUID string to match the
    existing wire format (``str(getattr(row, "id", photo_id))``).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    slot: str
    image_key: str
    image_url: str


class UserAnalyzeResponse(BaseModel):
    """Response body for ``POST /user/analyze``.

    ``kibbe`` and ``color`` are engine outputs. Their internal shape is
    defined in :mod:`app.services.identity_engine` /
    :mod:`app.services.color_engine` and unit-tested there; this schema
    only guarantees they are present as JSON objects.
    """

    model_config = ConfigDict(extra="forbid")

    kibbe: dict[str, Any]
    color: dict[str, Any]
    style_vector: dict[str, float]
    analyzed_at: datetime
    photos: list[AnalyzedPhotoOut]


__all__ = ["AnalyzedPhotoOut", "UserAnalyzeResponse"]
