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

    ``label`` is one of ``"safe"``, ``"balanced"``, ``"expressive"``.
    ``actions`` holds the compact CTA list (``Wear today`` / ``Save`` /
    optional ``Adjust`` when the explanation reports warnings).
    ``explanation`` is the UI-ready summary produced by the explainer
    (one-sentence summary, ≤3 reasons, ≤2 warnings — all in Russian).
    """

    model_config = ConfigDict(extra="forbid")

    label: str
    outfit: dict[str, Any]
    reasons: list[str]
    actions: list[str] = []
    explanation: dict[str, Any] = {}


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
