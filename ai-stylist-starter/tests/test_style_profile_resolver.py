"""Tests for :mod:`app.services.style_profile_resolver`.

The resolver is the single read-seam that chooses between the algorithmic
(photo-analysis) profile and the preference-quiz profile. All tests are
pure — no DB, no HTTP. They exercise plain stub objects that mirror the
:class:`StyleProfile` attribute surface.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.models.style_profile import (
    PROFILE_SOURCE_ALGORITHMIC,
    PROFILE_SOURCE_PREFERENCE,
)
from app.services import style_profile_resolver as resolver_module
from app.services.style_profile_resolver import (
    ResolvedProfile,
    get_active_profile,
    get_active_profile_by_user_id,
    set_active_profile_source,
)


# ---------------------------------------------------------------- stubs


@dataclass
class _StubStyleProfile:
    """Mirror of the :class:`StyleProfile` attribute surface.

    Good enough for the resolver, which only does ``getattr`` reads.
    """

    user_id: uuid.UUID = field(
        default_factory=lambda: uuid.UUID("11111111-1111-1111-1111-111111111111")
    )
    kibbe_type: str | None = None
    kibbe_confidence: float | None = None
    color_profile_json: dict = field(default_factory=dict)
    style_vector_json: dict = field(default_factory=dict)
    color_overrides_json: dict = field(default_factory=dict)
    kibbe_type_preference: str | None = None
    kibbe_preference_confidence: float | None = None
    color_season_preference: str | None = None
    color_preference_confidence: float | None = None
    preference_completed_at: Any = None
    active_profile_source: str = PROFILE_SOURCE_ALGORITHMIC


class _StubSession:
    """Minimal SQLAlchemy-session-shape for resolver.set_active_profile_source."""

    def __init__(self, rows: dict[uuid.UUID, _StubStyleProfile] | None = None) -> None:
        self._rows = dict(rows or {})
        self.add_calls: list[_StubStyleProfile] = []
        self.commits = 0
        self.refreshes: list[_StubStyleProfile] = []

    # SQLAlchemy 2.0 surface used by the resolver
    def get(self, _model, pk):
        return self._rows.get(pk)

    def add(self, row) -> None:
        self.add_calls.append(row)
        self._rows[row.user_id] = row

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, row) -> None:
        self.refreshes.append(row)


# ---------------------------------------------------------------- get_active_profile


def test_get_active_profile_algorithmic_default() -> None:
    """Default (empty) source => algorithmic branch: kibbe_type + season_top_1."""
    profile = _StubStyleProfile(
        kibbe_type="soft_natural",
        kibbe_confidence=0.78,
        color_profile_json={
            "season_top_1": "soft_summer",
            "palette_hex": ["#aabbcc"],
            "axes": {"undertone": "cool"},
        },
        style_vector_json={"minimal": 0.6},
        active_profile_source="",  # empty string => treated as algorithmic
    )

    resolved = get_active_profile(profile)

    assert resolved.source == PROFILE_SOURCE_ALGORITHMIC
    assert resolved.kibbe_type == "soft_natural"
    assert resolved.kibbe_confidence == pytest.approx(0.78)
    assert resolved.color_season == "soft_summer"
    assert resolved.color_confidence is None
    assert resolved.raw_color_profile["palette_hex"] == ["#aabbcc"]
    assert resolved.style_vector == {"minimal": 0.6}


def test_get_active_profile_algorithmic_explicit() -> None:
    """Explicit "algorithmic" source => same algorithmic branch."""
    profile = _StubStyleProfile(
        kibbe_type="classic",
        color_profile_json={"season_top_1": "true_winter"},
        active_profile_source=PROFILE_SOURCE_ALGORITHMIC,
        # Even if preference fields are filled, algorithmic source wins.
        kibbe_type_preference="dramatic",
        color_season_preference="deep_winter",
    )
    resolved = get_active_profile(profile)
    assert resolved.source == PROFILE_SOURCE_ALGORITHMIC
    assert resolved.kibbe_type == "classic"
    assert resolved.color_season == "true_winter"


def test_get_active_profile_none_row() -> None:
    """``None`` row => empty resolved profile, algorithmic source."""
    resolved = get_active_profile(None)
    assert resolved.source == PROFILE_SOURCE_ALGORITHMIC
    assert resolved.kibbe_type is None
    assert resolved.color_season is None
    assert resolved.raw_color_profile == {}
    assert resolved.style_vector == {}


# ---------------------------------------------------------------- preference branch


def test_get_active_profile_preference() -> None:
    """Preference source with both fields => preference wins over algorithmic."""
    profile = _StubStyleProfile(
        kibbe_type="classic",
        color_profile_json={"season_top_1": "true_winter"},
        kibbe_type_preference="soft_gamine",
        kibbe_preference_confidence=0.82,
        color_season_preference="light_spring",
        color_preference_confidence=0.71,
        active_profile_source=PROFILE_SOURCE_PREFERENCE,
    )

    resolved = get_active_profile(profile)

    assert resolved.source == PROFILE_SOURCE_PREFERENCE
    assert resolved.kibbe_type == "soft_gamine"
    assert resolved.kibbe_confidence == pytest.approx(0.82)
    assert resolved.color_season == "light_spring"
    assert resolved.color_confidence == pytest.approx(0.71)
    # Raw color profile is preserved so palette_hex / axes readers still work.
    assert resolved.raw_color_profile == {"season_top_1": "true_winter"}


def test_get_active_profile_preference_partial_kibbe_only() -> None:
    """Preference with only kibbe filled is still preference (not fallback)."""
    profile = _StubStyleProfile(
        kibbe_type="classic",
        color_profile_json={"season_top_1": "true_winter"},
        kibbe_type_preference="theatrical_romantic",
        active_profile_source=PROFILE_SOURCE_PREFERENCE,
    )
    resolved = get_active_profile(profile)
    assert resolved.source == PROFILE_SOURCE_PREFERENCE
    assert resolved.kibbe_type == "theatrical_romantic"
    # Color season is None because preference did not set it.
    assert resolved.color_season is None


def test_get_active_profile_preference_fallback_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Preference selected but both preference fields empty => fallback + warn."""
    profile = _StubStyleProfile(
        kibbe_type="natural",
        color_profile_json={"season_top_1": "soft_autumn"},
        kibbe_type_preference=None,
        color_season_preference=None,
        active_profile_source=PROFILE_SOURCE_PREFERENCE,
    )

    with caplog.at_level(logging.WARNING, logger=resolver_module.__name__):
        resolved = get_active_profile(profile)

    assert resolved.source == PROFILE_SOURCE_ALGORITHMIC
    assert resolved.kibbe_type == "natural"
    assert resolved.color_season == "soft_autumn"
    assert any(
        "preference fields are empty" in record.getMessage()
        for record in caplog.records
    )


# ---------------------------------------------------------------- by_user_id wrapper


def test_get_active_profile_by_user_id_missing_row() -> None:
    """Missing row => empty ResolvedProfile, no crash."""
    user_id = uuid.uuid4()
    db = _StubSession()
    resolved = get_active_profile_by_user_id(user_id, db)
    assert isinstance(resolved, ResolvedProfile)
    assert resolved.source == PROFILE_SOURCE_ALGORITHMIC
    assert resolved.kibbe_type is None
    assert resolved.color_season is None


def test_get_active_profile_by_user_id_hit() -> None:
    user_id = uuid.uuid4()
    row = _StubStyleProfile(
        user_id=user_id,
        kibbe_type="flamboyant_natural",
        color_profile_json={"season_top_1": "true_autumn"},
    )
    db = _StubSession({user_id: row})

    resolved = get_active_profile_by_user_id(user_id, db)
    assert resolved.kibbe_type == "flamboyant_natural"
    assert resolved.color_season == "true_autumn"


# ---------------------------------------------------------------- set_active_profile_source


def test_set_active_profile_source_invalid() -> None:
    user_id = uuid.uuid4()
    row = _StubStyleProfile(user_id=user_id, kibbe_type="classic")
    db = _StubSession({user_id: row})

    with pytest.raises(ValueError, match="invalid profile source"):
        set_active_profile_source(user_id, "banana", db)

    # Nothing was persisted
    assert db.commits == 0
    assert row.active_profile_source == PROFILE_SOURCE_ALGORITHMIC


def test_set_active_profile_source_preference_not_completed() -> None:
    """preference source requires either kibbe or color preference field set."""
    user_id = uuid.uuid4()
    row = _StubStyleProfile(
        user_id=user_id,
        kibbe_type="classic",
        kibbe_type_preference=None,
        color_season_preference=None,
    )
    db = _StubSession({user_id: row})

    with pytest.raises(ValueError, match="preference profile not completed"):
        set_active_profile_source(user_id, PROFILE_SOURCE_PREFERENCE, db)

    assert db.commits == 0
    assert row.active_profile_source == PROFILE_SOURCE_ALGORITHMIC


def test_set_active_profile_source_happy_path_preference() -> None:
    user_id = uuid.uuid4()
    row = _StubStyleProfile(
        user_id=user_id,
        kibbe_type="classic",
        kibbe_type_preference="soft_gamine",
        color_season_preference="light_spring",
    )
    db = _StubSession({user_id: row})

    returned = set_active_profile_source(user_id, PROFILE_SOURCE_PREFERENCE, db)

    assert returned is row
    assert row.active_profile_source == PROFILE_SOURCE_PREFERENCE
    assert db.commits == 1


def test_set_active_profile_source_happy_path_algorithmic() -> None:
    user_id = uuid.uuid4()
    row = _StubStyleProfile(
        user_id=user_id,
        active_profile_source=PROFILE_SOURCE_PREFERENCE,
        kibbe_type_preference="soft_gamine",
    )
    db = _StubSession({user_id: row})

    returned = set_active_profile_source(user_id, PROFILE_SOURCE_ALGORITHMIC, db)
    assert returned is row
    assert row.active_profile_source == PROFILE_SOURCE_ALGORITHMIC
    assert db.commits == 1


def test_set_active_profile_source_missing_row() -> None:
    user_id = uuid.uuid4()
    db = _StubSession()
    with pytest.raises(LookupError):
        set_active_profile_source(user_id, PROFILE_SOURCE_ALGORITHMIC, db)
