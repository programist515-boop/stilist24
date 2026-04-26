"""Outfit input/output schemas.

``OutfitGenerateIn`` is the existing input payload and stays unchanged
(it's already imported by ``app.api.routes.outfits``). Phase 2 adds
:class:`OutfitGenerateOut` as the wrapped response shape for
``POST /outfits/generate``.

The outfit object itself is intentionally modelled as ``dict[str, Any]``:
:class:`app.services.outfit_engine.OutfitEngine` emits a rich,
template-driven structure (``items``, ``occasion``, ``scores``,
``filter_pass_reasons``, ``scoring_reasons``, ``explanation``,
``breakdown``, ``generation``) that is unit-tested at the engine level
but not stable enough to lock into a strict BaseModel yet. Locking the
outer wrapper (``{outfits, count}``) is the useful part for the
frontend; the inner shape evolves with the engine.

The legacy :class:`OutfitOut` below is dead code (never imported) and
is kept only to avoid a gratuitous delete in Phase 2. It will be
removed in a later cleanup.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class OutfitGenerateIn(BaseModel):
    """Payload for ``POST /outfits/generate``.

    ``style`` (опционально) — ключ стиля из ``config/rules/styles.yaml``
    (smart_casual, casual, military, dandy, preppy, romantic_adapted,
    dramatic, twenties). При указании scorer ``style_affinity`` фильтрует
    style_tags вещей под этот стиль. Если не задан — выбираются все теги.
    """

    occasion: str | None = None
    season: str | None = None
    style: str | None = None


class OutfitGenerateOut(BaseModel):
    """Wrapped response for ``POST /outfits/generate``.

    Renames the current top-level key ``items`` (which was confusingly
    reused inside each outfit for wardrobe items) to ``outfits``.
    ``count`` stays as-is.
    """

    model_config = ConfigDict(extra="forbid")

    outfits: list[dict[str, Any]]
    count: int


# ---------------------------------------------------------------- legacy

# Dead code: never imported by any route or test. Kept only so the
# Phase 2 diff is a pure addition. Remove in a later cleanup pass.
class OutfitOut(BaseModel):
    id: str
    items: list[dict[str, Any]]
    scores: dict[str, float]
    explanation: str


__all__ = ["OutfitGenerateIn", "OutfitGenerateOut", "OutfitOut"]
