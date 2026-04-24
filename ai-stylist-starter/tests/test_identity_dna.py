"""Tests for the Identity DNA route — карточка «Кто ты стилистически»."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from app.api.routes.identity_dna import get_identity_dna


def _resolved(kibbe_type=None):
    obj = MagicMock()
    obj.kibbe_type = kibbe_type
    return obj


class TestIdentityDNARoute:
    def test_empty_when_no_subtype(self):
        db = MagicMock()
        with patch(
            "app.api.routes.identity_dna.get_active_profile_by_persona_id",
            return_value=_resolved(None),
        ):
            out = get_identity_dna(db=db, persona_id=uuid.uuid4())
        assert out.subtype is None
        assert out.motto == ""
        assert out.associations == []
        assert out.celebrity_examples == []

    def test_returns_flamboyant_gamine_content(self):
        db = MagicMock()
        with patch(
            "app.api.routes.identity_dna.get_active_profile_by_persona_id",
            return_value=_resolved("flamboyant_gamine"),
        ):
            out = get_identity_dna(db=db, persona_id=uuid.uuid4())
        assert out.subtype == "flamboyant_gamine"
        assert out.display_name_ru == "Гамин-Драматик"
        assert out.family == "gamine"
        assert len(out.associations) >= 5
        assert out.motto, "motto must be populated"
        assert len(out.philosophy) >= 300
        assert len(out.key_principles) >= 4
        assert len(out.celebrity_examples) >= 6
        # Every celebrity has a name
        assert all(c.name for c in out.celebrity_examples)

    def test_returns_populated_content_for_secondary_subtype(self):
        """All 13 subtypes are filled — pick a non-FG one and verify structure."""
        db = MagicMock()
        with patch(
            "app.api.routes.identity_dna.get_active_profile_by_persona_id",
            return_value=_resolved("soft_natural"),
        ):
            out = get_identity_dna(db=db, persona_id=uuid.uuid4())
        assert out.subtype == "soft_natural"
        assert out.display_name_ru  # filled in session 2026-04-22
        assert out.motto
        assert len(out.associations) >= 5
        assert len(out.celebrity_examples) >= 6

    def test_unknown_subtype_returns_empty(self):
        db = MagicMock()
        with patch(
            "app.api.routes.identity_dna.get_active_profile_by_persona_id",
            return_value=_resolved("not_a_real_kibbe_type"),
        ):
            out = get_identity_dna(db=db, persona_id=uuid.uuid4())
        assert out.subtype is None
        assert out.motto == ""
