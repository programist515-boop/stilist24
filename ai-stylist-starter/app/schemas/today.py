"""Today response schema.

Pins the shape of ``GET /today``, which is served by
:meth:`app.services.today_service.TodayService.get_today`.

* :class:`TodayOutfit` — one labelled suggestion (``safe`` /
  ``balanced`` / ``expressive``) produced by ``TodayService``'s
  selection pass. The ``outfit`` field is kept as ``dict[str, Any]``
  because its inner shape is the same template-driven dict that
  :class:`app.services.outfit_engine.OutfitEngine` emits and is
  therefore not locked in this schema pass (see ``schemas/outfit.py``
  for the rationale).
* :class:`TodayResponse` — top-level response body with optional
  ``weather`` / ``occasion`` echo, the three (or fewer) labelled
  outfits in canonical ``safe → balanced → expressive`` order, and
  the human-readable ``notes`` list.

The schema only guarantees the envelope. Selection rules, tiebreaks,
and reason text continue to live in the service and are unit-tested
there.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class TodayOutfit(BaseModel):
    """One labelled Today suggestion.

    ``label`` is one of ``"safe"``, ``"balanced"``, ``"expressive"`` —
    documented in :data:`app.services.today_service.SLOT_ORDER`. The
    schema stays open (``label: str``) because the selection vocabulary
    may grow in later steps (``bold``, ``weather_safe``, etc.) without
    a schema bump.
    """

    model_config = ConfigDict(extra="forbid")

    label: str
    outfit: dict[str, Any]
    reasons: list[str]


class TodayResponse(BaseModel):
    """Response body for ``GET /today``.

    Matches the dict ``TodayService.get_today`` returns in both the
    normal path and the degraded paths (empty wardrobe, filtered pool,
    etc.) — ``outfits`` can be empty and ``notes`` carries any
    explanatory strings the service collected along the way.
    """

    model_config = ConfigDict(extra="forbid")

    weather: str | None
    occasion: str | None
    outfits: list[TodayOutfit]
    notes: list[str]


__all__ = ["TodayOutfit", "TodayResponse"]
