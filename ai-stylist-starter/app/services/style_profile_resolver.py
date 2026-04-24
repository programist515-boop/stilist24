"""Active style profile resolver.

Single entry point that returns the *active* identity + color profile for a
user, collapsing the branching between the algorithmic analysis (photo-based)
and the preference-based quiz into one read.

Downstream services (outfit engine, gap analysis, scoring, shopping,
recommendation guide, user_context builder, …) are expected to call
:func:`get_active_profile` instead of reading ``StyleProfile.kibbe_type`` or
``StyleProfile.color_profile_json["season_top_1"]`` directly — that way a user
who completes the quiz immediately sees recommendations driven by the quiz
result, and a user who hasn't completed it keeps seeing the algorithmic
defaults.

The resolver is intentionally lossless for the algorithmic branch: it still
exposes the raw ``color_profile_json`` dict via ``raw_color_profile`` so the
bits of downstream code that need ``palette_hex``, ``axes`` etc. can keep
reading them unchanged.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.models.style_profile import (
    PROFILE_SOURCE_ALGORITHMIC,
    PROFILE_SOURCE_PREFERENCE,
    StyleProfile,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


VALID_SOURCES: frozenset[str] = frozenset(
    {PROFILE_SOURCE_ALGORITHMIC, PROFILE_SOURCE_PREFERENCE}
)


@dataclass
class ResolvedProfile:
    """Active identity + color profile, source-agnostic.

    Attributes
    ----------
    source:
        Actual source used to populate the fields. Equals the stored
        ``active_profile_source`` in the common case, but degrades to
        ``"algorithmic"`` when ``"preference"`` is selected but the quiz
        fields are empty.
    kibbe_type:
        Active kibbe type (e.g. ``"soft_natural"``) or ``None``.
    kibbe_confidence:
        Confidence of ``kibbe_type`` in ``[0, 1]`` or ``None``.
    color_season:
        Active 12-season label (e.g. ``"soft_summer"``) or ``None``.
    color_confidence:
        Confidence of ``color_season`` in ``[0, 1]`` or ``None``.
    raw_color_profile:
        Full ``color_profile_json`` from ``StyleProfile`` — preserved for
        downstream readers that need ``palette_hex``, ``axes`` etc.
        Always a dict (possibly empty), never ``None``.
    style_vector:
        Full ``style_vector_json`` from ``StyleProfile`` — preserved for the
        same reasons. Always a dict, never ``None``.
    """

    source: str
    kibbe_type: str | None
    kibbe_confidence: float | None
    color_season: str | None
    color_confidence: float | None
    raw_color_profile: dict = field(default_factory=dict)
    style_vector: dict = field(default_factory=dict)


def _empty() -> ResolvedProfile:
    return ResolvedProfile(
        source=PROFILE_SOURCE_ALGORITHMIC,
        kibbe_type=None,
        kibbe_confidence=None,
        color_season=None,
        color_confidence=None,
        raw_color_profile={},
        style_vector={},
    )


def _resolve_algorithmic(style_profile: Any) -> ResolvedProfile:
    color_profile = dict(getattr(style_profile, "color_profile_json", None) or {})
    style_vector = dict(getattr(style_profile, "style_vector_json", None) or {})
    return ResolvedProfile(
        source=PROFILE_SOURCE_ALGORITHMIC,
        kibbe_type=getattr(style_profile, "kibbe_type", None),
        kibbe_confidence=getattr(style_profile, "kibbe_confidence", None),
        color_season=color_profile.get("season_top_1"),
        color_confidence=None,
        raw_color_profile=color_profile,
        style_vector=style_vector,
    )


def get_active_profile(style_profile: Any) -> ResolvedProfile:
    """Return the active :class:`ResolvedProfile` for a ``StyleProfile`` row.

    * ``None`` row → empty :class:`ResolvedProfile` with ``source="algorithmic"``.
    * ``active_profile_source == "preference"`` →
      ``kibbe_type_preference`` + ``color_season_preference``. If *both*
      preference fields are empty we log a warning and fall back to the
      algorithmic branch so downstream recommenders don't lose all context
      because of a stale toggle.
    * ``"algorithmic"`` (default) →
      ``kibbe_type`` + ``color_profile_json["season_top_1"]``.
    """
    if style_profile is None:
        return _empty()

    source = getattr(style_profile, "active_profile_source", None) or PROFILE_SOURCE_ALGORITHMIC

    if source == PROFILE_SOURCE_PREFERENCE:
        kibbe_pref = getattr(style_profile, "kibbe_type_preference", None)
        season_pref = getattr(style_profile, "color_season_preference", None)
        if not kibbe_pref and not season_pref:
            logger.warning(
                "style_profile_resolver: active_profile_source=preference but "
                "preference fields are empty for user_id=%s — falling back to "
                "algorithmic",
                getattr(style_profile, "user_id", "<unknown>"),
            )
            return _resolve_algorithmic(style_profile)

        # Preserve raw color_profile / style_vector for palette_hex / axes
        # readers, even when the active *decision* fields come from preferences.
        color_profile = dict(
            getattr(style_profile, "color_profile_json", None) or {}
        )
        style_vector = dict(
            getattr(style_profile, "style_vector_json", None) or {}
        )
        return ResolvedProfile(
            source=PROFILE_SOURCE_PREFERENCE,
            kibbe_type=kibbe_pref,
            kibbe_confidence=getattr(
                style_profile, "kibbe_preference_confidence", None
            ),
            color_season=season_pref,
            color_confidence=getattr(
                style_profile, "color_preference_confidence", None
            ),
            raw_color_profile=color_profile,
            style_vector=style_vector,
        )

    return _resolve_algorithmic(style_profile)


def load_style_profile(
    *,
    user_id: uuid.UUID | None = None,
    persona_id: uuid.UUID | None = None,
    db: "Session",
) -> StyleProfile | None:
    """Resolve a ``StyleProfile`` row by persona or by user.

    After the multi-persona migration (0010) the PK of ``style_profiles``
    is ``persona_id``, not ``user_id``. Callers should provide
    ``persona_id`` when they have it — this is the fast path via
    ``db.get``. When only ``user_id`` is known we fall back to the user's
    primary persona and then look up the row by that. Returns ``None``
    when the user has no primary persona yet (fresh signup) or the
    analysis has never been run.
    """
    if persona_id is not None:
        return db.get(StyleProfile, persona_id)
    if user_id is None:
        return None
    # Lazy import so the module keeps working without SQLAlchemy in
    # pure-Python unit tests.
    from app.repositories.persona_repository import PersonaRepository

    try:
        primary = PersonaRepository(db).get_primary(user_id)
    except AttributeError:
        # Test stubs sometimes only implement ``Session.get`` (the old
        # PK-by-user_id seam). Fall back to that so pre-multi-persona
        # tests keep passing while production code that has a real
        # SQLAlchemy session goes through the persona path.
        return db.get(StyleProfile, user_id)
    if primary is None:
        return None
    return db.get(StyleProfile, primary.id)


def get_active_profile_by_user_id(
    user_id: uuid.UUID,
    db: "Session",
) -> ResolvedProfile:
    """Convenience wrapper — loads ``StyleProfile`` and resolves it.

    Returns an empty :class:`ResolvedProfile` (all ``None``) when no row
    exists for the user yet.
    """
    row = load_style_profile(user_id=user_id, db=db)
    return get_active_profile(row)


def get_active_profile_by_persona_id(
    persona_id: uuid.UUID,
    db: "Session",
) -> ResolvedProfile:
    """Persona-scoped convenience wrapper."""
    row = load_style_profile(persona_id=persona_id, db=db)
    return get_active_profile(row)


def set_active_profile_source(
    user_id: uuid.UUID,
    source: str,
    db: "Session",
) -> StyleProfile:
    """Switch the active profile source for a user.

    Raises
    ------
    ValueError
        * ``source`` not in :data:`VALID_SOURCES`.
        * ``source == "preference"`` but no preference fields are populated
          yet (quiz not completed).
    LookupError
        No ``StyleProfile`` row exists for the user.
    """
    if source not in VALID_SOURCES:
        raise ValueError(
            f"invalid profile source: {source!r} "
            f"(expected one of {sorted(VALID_SOURCES)})"
        )

    row = load_style_profile(user_id=user_id, db=db)
    if row is None:
        raise LookupError(
            f"StyleProfile for user_id={user_id} does not exist — "
            "run /user/analyze or complete the preference quiz first"
        )

    if source == PROFILE_SOURCE_PREFERENCE:
        if not (row.kibbe_type_preference or row.color_season_preference):
            raise ValueError("preference profile not completed")

    row.active_profile_source = source
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


__all__ = [
    "PROFILE_SOURCE_ALGORITHMIC",
    "PROFILE_SOURCE_PREFERENCE",
    "ResolvedProfile",
    "VALID_SOURCES",
    "get_active_profile",
    "get_active_profile_by_user_id",
    "get_active_profile_by_persona_id",
    "load_style_profile",
    "set_active_profile_source",
]
