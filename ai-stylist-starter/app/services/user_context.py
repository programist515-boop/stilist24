"""Canonical user context builder.

Single source of truth for all pipelines (outfit scoring, analytics,
shopping, today). Every route and service should call one of these two
functions instead of building the context dict inline.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session


def build_user_context(
    style_profile: Any = None,
    personalization_profile: Any = None,
) -> dict:
    """Build canonical user context from already-loaded profile objects.

    Parameters
    ----------
    style_profile:
        ``StyleProfile`` ORM row or ``None``.
    personalization_profile:
        ``PersonalizationProfile`` ORM row or ``None``.

    Returns
    -------
    Dict with the guaranteed keys every pipeline downstream expects:
    ``identity_family``, ``color_profile``, ``color_axes``, ``palette_hex``,
    ``color_source``, ``style_vector``, ``occasion_defaults``, ``lifestyle``.
    """
    palette_hex: list[str] = []
    color_axes: dict = {}
    color_source: str = "cv"

    if style_profile is not None:
        cp = getattr(style_profile, "color_profile_json", None) or {}
        palette_hex = cp.get("palette_hex") or (
            cp.get("best_neutrals", []) + cp.get("accent_colors", [])
        )
        color_axes = cp.get("axes") or {}
        overrides = getattr(style_profile, "color_overrides_json", None) or {}
        if overrides.get("manual_selected_season") or any(
            overrides.get(k)
            for k in ("manual_hair_color", "manual_eye_color", "manual_undertone")
        ):
            color_source = "override"

    return {
        "identity_family": getattr(style_profile, "kibbe_type", None),
        "color_profile": (
            (getattr(style_profile, "color_profile_json", None) or {})
            if style_profile is not None
            else {}
        ),
        "color_axes": color_axes,
        "palette_hex": palette_hex,
        "color_source": color_source,
        "style_vector": (
            (getattr(personalization_profile, "style_vector_json", None) or {})
            if personalization_profile is not None
            else {}
        ),
        "occasion_defaults": [],
        "lifestyle": [],
    }


def build_user_context_from_db(
    db: "Session",
    user_id: uuid.UUID,
) -> dict:
    """Load style and personalization profiles from DB and build the context.

    Thin wrapper over :func:`build_user_context` for use in route handlers.
    """
    from app.models.style_profile import StyleProfile
    from app.repositories.personalization_repository import PersonalizationRepository

    style = db.get(StyleProfile, user_id)
    perso = PersonalizationRepository(db).get_or_create(user_id)
    return build_user_context(style, perso)
