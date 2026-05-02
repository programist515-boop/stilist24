"""End-to-end contract test: stock-stage of identity quiz now returns all
subtypes, each with a real image file on disk.

This is the proof-of-life check that the content drop (YAMLs + generated
placeholder images) has filled the blocker we had: before, only
flamboyant_gamine had content, so the wardrobe-match step would never
unlock (it needs ≥3 distinct subtypes liked).
"""
from __future__ import annotations

import uuid
from pathlib import Path

import yaml

from app.services.preference_quiz import identity_quiz


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_PUBLIC = REPO_ROOT / "frontend" / "public"


def test_build_stock_candidates_returns_all_known_subtypes(monkeypatch):
    """All subtypes in identity_subtype_profiles.yaml must surface as cards."""
    subtypes_yaml = (
        REPO_ROOT
        / "ai-stylist-starter"
        / "config"
        / "rules"
        / "identity_subtype_profiles.yaml"
    )
    expected = set(
        yaml.safe_load(subtypes_yaml.read_text(encoding="utf-8"))[
            "identity_subtype_profiles"
        ].keys()
    )

    cards = identity_quiz.build_stock_candidates(
        user_id=uuid.uuid4(),
        db=None,  # stock-stage build doesn't hit the db
        algorithmic_subtype=None,
    )
    got = {c["subtype"] for c in cards}

    assert got == expected, f"missing subtypes: {expected - got}; extra: {got - expected}"
    assert len(cards) >= 3, "need ≥3 cards for the wardrobe-match step to ever unlock"


def test_stock_candidate_image_urls_resolve_to_real_files():
    """Every card's image_url must point at a JPEG that actually exists."""
    cards = identity_quiz.build_stock_candidates(
        user_id=uuid.uuid4(), db=None, algorithmic_subtype=None
    )
    missing: list[str] = []
    for card in cards:
        url = card["image_url"]
        assert url.startswith("/reference_looks/"), (
            f"unexpected image_url prefix: {url} — script should have normalized it"
        )
        fs_path = FRONTEND_PUBLIC / url.lstrip("/")
        if not fs_path.is_file():
            missing.append(f"{card['subtype']} -> {url}")
    assert not missing, "unresolvable image_urls: " + "; ".join(missing)


def test_algorithmic_winner_surfaces_first():
    cards = identity_quiz.build_stock_candidates(
        user_id=uuid.uuid4(),
        db=None,
        algorithmic_subtype="flamboyant_gamine",
    )
    assert cards[0]["subtype"] == "flamboyant_gamine"
