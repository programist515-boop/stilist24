"""Preference-based color-season quiz orchestrator.

Responsibility split
--------------------
- :func:`build_family_candidates` / :func:`build_season_candidates`
  materialize one drape card per candidate season, upload the JPEG to
  storage, and return dicts ready to persist in
  ``PreferenceQuizSession.candidates_json``.
- :func:`record_vote` appends a vote to ``votes_json`` and mirrors it
  into the user-event stream via :class:`FeedbackService` so downstream
  personalization vectors benefit from the color signal.
- :func:`resolve_family_stage` and :func:`resolve_final_winner` are
  pure reducers over the stored votes — no DB, no storage. They stay
  side-effect free so the routes can preview results without mutating
  state.

Candidate colors
----------------
Each card shows the *canonical* color of a season (first entry of
``canonical_colors`` in ``seasons_palette.yaml``). Using a fixed index
keeps the quiz deterministic and reproducible; swapping to
palette-center sampling can happen later without changing this module's
public contract.

Family → representative season mapping (used on the family stage):
- spring  → true_spring
- summer  → true_summer
- autumn  → true_autumn
- winter  → true_winter

Family → three-season breakdown (used on the season stage):
- spring  → light_spring,  true_spring,  bright_spring
- summer  → light_summer,  true_summer,  soft_summer
- autumn  → soft_autumn,   true_autumn,  deep_autumn
- winter  → bright_winter, true_winter,  deep_winter
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.preference_quiz_session import (
    PreferenceQuizSession,
    STAGE_FAMILY,
    STAGE_SEASON,
)
from app.models.user_photo import UserPhoto
from app.repositories.user_photo_repository import UserPhotoRepository
from app.services.color_engine import ColorEngine
from app.services.feedback_service import FeedbackService
from app.services.preference_quiz.drapery_renderer import render_drapery


logger = logging.getLogger(__name__)


FAMILY_ORDER: tuple[str, ...] = ("spring", "summer", "autumn", "winter")

# Representative season shown on each family card.
FAMILY_REPRESENTATIVE: dict[str, str] = {
    "spring": "true_spring",
    "summer": "true_summer",
    "autumn": "true_autumn",
    "winter": "true_winter",
}

# Three-season breakdown shown on the season-stage cards.
FAMILY_SEASONS: dict[str, tuple[str, str, str]] = {
    "spring": ("light_spring", "true_spring", "bright_spring"),
    "summer": ("light_summer", "true_summer", "soft_summer"),
    "autumn": ("soft_autumn", "true_autumn", "deep_autumn"),
    "winter": ("bright_winter", "true_winter", "deep_winter"),
}


# ---------------------------------------------------------------- helpers


class PortraitMissingError(Exception):
    """Raised when the caller has no ``slot='portrait'`` photo stored."""


def _get_portrait_bytes(user_id: uuid.UUID, db: Session, storage: Any) -> bytes:
    """Fetch the portrait photo bytes for the caller.

    Raises :class:`PortraitMissingError` when either the row or the
    backing object is missing — the route layer turns that into a 409.
    """
    repo = UserPhotoRepository(db)
    row: UserPhoto | None = repo.latest_by_slot(user_id, "portrait")
    if row is None:
        raise PortraitMissingError(
            "no portrait photo on file — run /user/analyze first"
        )
    obj = storage.get_object(row.image_key)
    if obj is None:
        raise PortraitMissingError(
            f"portrait object {row.image_key!r} is missing from storage"
        )
    data, _ct = obj
    return data


def _canonical_hex(engine: ColorEngine, season: str) -> str:
    """Pick the first ``canonical_colors`` swatch for a season.

    Falls back to the first ``accent_colors`` swatch if the palette
    somehow has no canonical entry — the palette YAML shipped in the
    repo always defines at least one, so the fallback is a belt-and-
    braces check rather than a hot path.
    """
    palette = engine.get_palette(season)
    canonical = palette.get("canonical_colors") or []
    if canonical:
        return canonical[0]
    accents = palette.get("accent_colors") or []
    if accents:
        return accents[0]
    # Extremely defensive: neutral grey so the quiz still renders.
    return "#808080"


def _upload_candidate_card(
    storage: Any,
    user_id: uuid.UUID,
    session_id: uuid.UUID | str,
    candidate_id: str,
    image_bytes: bytes,
) -> str:
    """Push a drape card into storage and return its public URL.

    The key path intentionally lives outside the per-slot ``user_photos``
    tree — quiz cards are ephemeral artefacts, not reference photos, and
    should not be listed by ``/user/photos``.
    """
    key = f"users/{user_id}/preference_quiz/{session_id}/{candidate_id}.jpg"
    storage.backend.put(key, image_bytes, content_type="image/jpeg")
    return storage.backend.public_url(key)


# ---------------------------------------------------------------- candidates


def build_family_candidates(
    user_id: uuid.UUID,
    db: Session,
    storage: Any,
    *,
    session_id: uuid.UUID | str,
    algorithmic_family: str | None = None,
) -> list[dict]:
    """Render the 4 family-stage cards and return candidate dicts.

    If ``algorithmic_family`` is supplied and known, that family is moved
    to the head of the list — the UX puts the algorithm's best guess
    first so a confident user can validate it in one swipe.
    """
    portrait_bytes = _get_portrait_bytes(user_id, db, storage)
    engine = ColorEngine()

    families = list(FAMILY_ORDER)
    if algorithmic_family in families:
        families.remove(algorithmic_family)
        families.insert(0, algorithmic_family)

    candidates: list[dict] = []
    for family in families:
        season = FAMILY_REPRESENTATIVE[family]
        hex_color = _canonical_hex(engine, season)
        image = render_drapery(portrait_bytes, hex_color)
        candidate_id = str(uuid.uuid4())
        url = _upload_candidate_card(
            storage, user_id, session_id, candidate_id, image
        )
        candidates.append(
            {
                "candidate_id": candidate_id,
                "family": family,
                "season": season,
                "hex": hex_color,
                "image_url": url,
                "stage": STAGE_FAMILY,
            }
        )
    return candidates


def build_season_candidates(
    user_id: uuid.UUID,
    db: Session,
    storage: Any,
    *,
    session_id: uuid.UUID | str,
    winner_family: str,
) -> list[dict]:
    """Render the 3 season-stage cards for the winning family."""
    if winner_family not in FAMILY_SEASONS:
        raise ValueError(f"unknown family {winner_family!r}")

    portrait_bytes = _get_portrait_bytes(user_id, db, storage)
    engine = ColorEngine()

    candidates: list[dict] = []
    for season in FAMILY_SEASONS[winner_family]:
        hex_color = _canonical_hex(engine, season)
        image = render_drapery(portrait_bytes, hex_color)
        candidate_id = str(uuid.uuid4())
        url = _upload_candidate_card(
            storage, user_id, session_id, candidate_id, image
        )
        candidates.append(
            {
                "candidate_id": candidate_id,
                "family": winner_family,
                "season": season,
                "hex": hex_color,
                "image_url": url,
                "stage": STAGE_SEASON,
            }
        )
    return candidates


# ---------------------------------------------------------------- votes


def _find_candidate(session: PreferenceQuizSession, candidate_id: str) -> dict | None:
    for cand in session.candidates_json or []:
        if cand.get("candidate_id") == candidate_id:
            return cand
    return None


def record_vote(
    session: PreferenceQuizSession,
    candidate_id: str,
    action: str,
    db: Session,
) -> dict:
    """Append a vote to the session and mirror it into user-events.

    ``action`` must be ``"like"`` or ``"dislike"``. Anything else is a
    routing bug and raises — the Pydantic schema already constrains the
    value at the API boundary, so reaching this path with a bad value
    indicates a caller bypassed validation.
    """
    if action not in {"like", "dislike"}:
        raise ValueError(f"invalid vote action {action!r}")

    candidate = _find_candidate(session, candidate_id)
    if candidate is None:
        raise ValueError(f"unknown candidate_id {candidate_id!r}")

    vote = {
        "candidate_id": candidate_id,
        "action": action,
        "family": candidate.get("family"),
        "season": candidate.get("season"),
        "hex": candidate.get("hex"),
        "stage": candidate.get("stage"),
    }

    # SQLAlchemy JSONB tracking only picks up whole-object reassignment.
    votes = list(session.votes_json or [])
    votes.append(vote)
    session.votes_json = votes

    event_type = (
        "color_preference_liked" if action == "like" else "color_preference_disliked"
    )
    payload = {
        "family": candidate.get("family"),
        "season": candidate.get("season"),
        "hex": candidate.get("hex"),
        "stage": candidate.get("stage"),
    }
    try:
        FeedbackService(db).process(session.user_id, event_type, payload)
    except Exception:  # pragma: no cover - defensive
        logger.exception("failed to mirror color-quiz vote into feedback stream")

    return vote


# ---------------------------------------------------------------- reducers


def resolve_family_stage(session: PreferenceQuizSession) -> str | None:
    """Return the top-1 family by likes on the family stage.

    Only votes whose candidate belonged to ``stage == STAGE_FAMILY`` and
    action ``"like"`` are counted. When nothing was liked we return
    ``None`` — the route turns that into a 409 so the UI can nudge the
    user to pick at least one card.

    Ties are broken by the canonical :data:`FAMILY_ORDER` so the result
    is deterministic even with empty tie-breakers.
    """
    tally: dict[str, int] = {}
    for vote in session.votes_json or []:
        if vote.get("stage") != STAGE_FAMILY:
            continue
        if vote.get("action") != "like":
            continue
        family = vote.get("family")
        if not family:
            continue
        tally[family] = tally.get(family, 0) + 1

    if not tally:
        return None

    def _sort_key(item: tuple[str, int]) -> tuple[int, int]:
        family, count = item
        # Higher count first; on ties, earlier FAMILY_ORDER wins (lower index).
        order = (
            FAMILY_ORDER.index(family) if family in FAMILY_ORDER else len(FAMILY_ORDER)
        )
        return (-count, order)

    return sorted(tally.items(), key=_sort_key)[0][0]


def resolve_final_winner(session: PreferenceQuizSession) -> dict:
    """Return the winning season and a likes-based ranking.

    ``confidence`` is the share of season-stage *like* votes that went to
    the winner. When there are no likes at all we fall back to 0.0 and
    ``winner`` is ``None`` — the route then skips writing to the style
    profile and lets the client surface a "pick at least one" message.
    """
    tally: dict[str, int] = {}
    dislikes: dict[str, int] = {}
    for vote in session.votes_json or []:
        if vote.get("stage") != STAGE_SEASON:
            continue
        season = vote.get("season")
        if not season:
            continue
        if vote.get("action") == "like":
            tally[season] = tally.get(season, 0) + 1
        elif vote.get("action") == "dislike":
            dislikes[season] = dislikes.get(season, 0) + 1

    total_likes = sum(tally.values())
    if not tally:
        return {
            "winner": None,
            "confidence": 0.0,
            "ranking": [
                {"season": season, "likes": 0, "dislikes": dislikes.get(season, 0)}
                for season in sorted(dislikes.keys())
            ],
        }

    ranking = [
        {
            "season": season,
            "likes": likes,
            "dislikes": dislikes.get(season, 0),
        }
        for season, likes in sorted(
            tally.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    # Include any seasons that were only disliked — useful for analytics.
    for season, count in sorted(dislikes.items()):
        if season not in tally:
            ranking.append({"season": season, "likes": 0, "dislikes": count})

    winner = ranking[0]["season"]
    confidence = round(tally[winner] / total_likes, 3) if total_likes else 0.0
    return {"winner": winner, "confidence": confidence, "ranking": ranking}


__all__ = [
    "FAMILY_ORDER",
    "FAMILY_REPRESENTATIVE",
    "FAMILY_SEASONS",
    "PortraitMissingError",
    "build_family_candidates",
    "build_season_candidates",
    "record_vote",
    "resolve_family_stage",
    "resolve_final_winner",
]
