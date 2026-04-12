"""Weekly insights response schema.

Pins the shape of ``GET /insights/weekly``, produced by
:meth:`app.services.insights_service.InsightsService.weekly`. The
service's outputs are all deterministic, unit-tested, and stable
enough to model tightly — unlike the template-driven outfit shape.
Every field name here matches ``InsightsService.weekly`` exactly so
Phase 3 is a one-line ``response_model=InsightsResponse`` attach with
no data reshape.

Schema breakdown
----------------

* :class:`InsightsWindow` — ``{start, end, days}`` at the top.
* :class:`BehaviorSummary` — 10 counters: ``total_events`` plus the
  9 ``event_type`` buckets emitted by ``_behavior_summary``.
* :class:`PreferencePatterns` — human-readable ``patterns`` list and
  the raw ``tag_counts`` split by axis (``style`` / ``line`` /
  ``color`` / ``avoidance``).
* :class:`UnderusedItem` — ``{id, category, reason}``.
* :class:`StyleShiftDelta` — ``{tag, delta}``, a rounded-to-3 float.
* :class:`StyleShift` — three ranked delta lists (``style`` / ``line``
  / ``color``) plus a human-readable ``lines`` list.
* :class:`InsightsResponse` — top-level envelope.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------- window


class InsightsWindow(BaseModel):
    """Rolling 7-day window covered by the insights response."""

    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime
    days: int


# ---------------------------------------------------------------- behavior


class BehaviorSummary(BaseModel):
    """Event-type counters emitted by ``_behavior_summary``.

    Field set is locked: these are the exact keys the service builds.
    If a new event type is added, both the service and this schema
    must move together.
    """

    model_config = ConfigDict(extra="forbid")

    total_events: int
    outfits_liked: int
    outfits_disliked: int
    outfits_saved: int
    outfits_worn: int
    items_liked: int
    items_disliked: int
    items_worn: int
    items_ignored: int
    tryons_opened: int


# ---------------------------------------------------------------- patterns


class PreferencePatterns(BaseModel):
    """Preference patterns over the week.

    ``patterns`` is a short list of human-readable lines
    (``"You leaned toward classic looks"`` etc.). ``tag_counts`` is the
    raw per-axis tag frequency map the service builds before emitting
    the lines — useful for a frontend that wants to render its own UI.
    """

    model_config = ConfigDict(extra="forbid")

    patterns: list[str]
    tag_counts: dict[str, dict[str, int]]


# ---------------------------------------------------------------- underused


class UnderusedItem(BaseModel):
    """Wardrobe item that saw no positive touches this week."""

    model_config = ConfigDict(extra="forbid")

    id: str
    category: str
    reason: str


# ---------------------------------------------------------------- style shift


class StyleShiftDelta(BaseModel):
    """One (tag, delta) row inside a :class:`StyleShift` axis.

    ``delta`` is in ``[-1.0, +1.0]`` and already rounded to 3 decimal
    places by the service.
    """

    model_config = ConfigDict(extra="forbid")

    tag: str
    delta: float


class StyleShift(BaseModel):
    """Week-over-baseline shift broken down per axis.

    Each of ``style`` / ``line`` / ``color`` carries up to the top 3
    most-positive and top 3 most-negative deltas relative to the
    user's stored personalization vectors. ``lines`` is a flat list
    of the most interesting shifts expressed as English sentences,
    sorted biggest-absolute-shift first.
    """

    model_config = ConfigDict(extra="forbid")

    style: list[StyleShiftDelta]
    line: list[StyleShiftDelta]
    color: list[StyleShiftDelta]
    lines: list[str]


# ---------------------------------------------------------------- envelope


class InsightsResponse(BaseModel):
    """Top-level response body for ``GET /insights/weekly``."""

    model_config = ConfigDict(extra="forbid")

    window: InsightsWindow
    behavior: BehaviorSummary
    preference_patterns: PreferencePatterns
    underused_items: list[UnderusedItem]
    underused_categories: list[str]
    style_shift: StyleShift
    notes: list[str]


__all__ = [
    "BehaviorSummary",
    "InsightsResponse",
    "InsightsWindow",
    "PreferencePatterns",
    "StyleShift",
    "StyleShiftDelta",
    "UnderusedItem",
]
