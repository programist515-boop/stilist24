"""Recommendation guide schema.

Pins the shape of ``GET /recommendations/style-guide``, served by
:meth:`app.services.recommendation_guide_service.RecommendationGuideService.get_guide`.

The response is an editorial-style style guide keyed off the user's
Kibbe family / color profile / style vector — think "your stylist's
cheat sheet". It's a deterministic projection of a curated YAML
bundle, not an LLM output. The schema pins only the envelope; the
copy lives in ``config/rules/recommendation_guides.yaml``.

All user-visible strings come back from the backend already in Russian
so the frontend just renders them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RecommendationItem(BaseModel):
    """A single bullet inside ``recommended`` or ``avoid``.

    The text is always present; ``slug`` and ``image_url`` are populated
    when an illustration has been generated for this item (see
    ``scripts/generate_recommendation_images.py``). The frontend
    falls back to a marker dot when ``image_url`` is null, so adding
    illustrations is incremental — items without one still render fine.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    slug: str | None = None
    image_url: str | None = None


class RecommendationSection(BaseModel):
    """One themed block of the style guide (e.g. Линии и силуэт)."""

    model_config = ConfigDict(extra="forbid")

    key: str
    title: str
    description: str
    recommended: list[RecommendationItem]
    avoid: list[RecommendationItem]


class RecommendationIdentity(BaseModel):
    """Resolved identity context used to pick the content bundle.

    All fields are optional so a user who hasn't finished the
    Kibbe/color analysis still gets a valid response (the service
    uses ``notes`` to tell the frontend to show the "сначала пройдите
    анализ" empty state).
    """

    model_config = ConfigDict(extra="forbid")

    kibbe_family: str | None = None
    kibbe_type: str | None = None
    color_profile_summary: str | None = None
    style_key: str | None = None
    top_style_tags: list[str] = []


class RecommendationGuideResponse(BaseModel):
    """Response body for ``GET /recommendations/style-guide``.

    * ``identity`` — resolved Kibbe family + short color summary +
      the "style key" for the family (a single sentence the UI can
      use as an eyebrow line above the sections).
    * ``summary`` — 2–3 sentence stylist intro in Russian.
    * ``sections`` — ordered list of themed blocks. The order is
      stable across calls so the UI can render them as-is.
    * ``closing_note`` — one-line "rule of thumb" at the end.
    * ``notes`` — degraded-path messages (e.g. "kibbe_type missing,
      complete analysis first") for the frontend's empty state.
    """

    model_config = ConfigDict(extra="forbid")

    identity: RecommendationIdentity
    summary: str
    sections: list[RecommendationSection]
    closing_note: str
    notes: list[str]


__all__ = [
    "RecommendationGuideResponse",
    "RecommendationIdentity",
    "RecommendationItem",
    "RecommendationSection",
]
