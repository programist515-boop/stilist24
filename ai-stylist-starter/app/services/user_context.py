"""Canonical user context builder.

Single source of truth for all pipelines (outfit scoring, analytics,
shopping, today). Every route and service should call one of these two
functions instead of building the context dict inline.

The identity + color season surfaced here is routed through
:mod:`app.services.style_profile_resolver` so that when a user has opted
into the preference-based profile, every downstream scorer / generator /
recommender picks up the quiz-derived values transparently.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from app.services.style_profile_resolver import get_active_profile

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
    ``color_source``, ``style_vector``, ``occasion_defaults``, ``lifestyle``,
    plus ``profile_source`` / ``color_season`` for diagnostics.
    """
    resolved = get_active_profile(style_profile)

    color_profile_raw = resolved.raw_color_profile or {}
    palette_hex = color_profile_raw.get("palette_hex") or (
        color_profile_raw.get("best_neutrals", [])
        + color_profile_raw.get("accent_colors", [])
    )
    color_axes = color_profile_raw.get("axes") or {}
    color_source: str = "cv"

    if style_profile is not None:
        overrides = getattr(style_profile, "color_overrides_json", None) or {}
        if overrides.get("manual_selected_season") or any(
            overrides.get(k)
            for k in ("manual_hair_color", "manual_eye_color", "manual_undertone")
        ):
            color_source = "override"

    # When the active source is preference-driven, surface a distinct marker
    # so analytics / explanations can tell the two apart.
    from app.services.style_profile_resolver import PROFILE_SOURCE_PREFERENCE

    if resolved.source == PROFILE_SOURCE_PREFERENCE:
        color_source = "preference"

    # Carry forward the active color season into color_profile so shopping /
    # scoring readers that look up ``color_profile["season_top_1"]`` still see
    # the correct value when the user has switched to preference source.
    color_profile_out: dict = dict(color_profile_raw)
    if resolved.color_season:
        color_profile_out["season_top_1"] = resolved.color_season

    style_vector = resolved.style_vector
    if personalization_profile is not None:
        perso_vector = (
            getattr(personalization_profile, "style_vector_json", None) or {}
        )
        if perso_vector:
            style_vector = perso_vector

    return {
        "identity_family": resolved.kibbe_type,
        "color_profile": color_profile_out,
        "color_axes": color_axes,
        "palette_hex": palette_hex,
        "color_source": color_source,
        "style_vector": style_vector,
        "occasion_defaults": [],
        "lifestyle": [],
        "profile_source": resolved.source,
        "color_season": resolved.color_season,
    }


def build_user_context_from_db(
    db: "Session",
    user_id: uuid.UUID,
) -> dict:
    """Load style and personalization profiles from DB and build the context.

    Thin wrapper over :func:`build_user_context` for use in route handlers.
    """
    from app.repositories.personalization_repository import PersonalizationRepository
    from app.services.style_profile_resolver import load_style_profile

    style = load_style_profile(user_id=user_id, db=db)
    perso = PersonalizationRepository(db).get_or_create(user_id)
    return build_user_context(style, perso)
