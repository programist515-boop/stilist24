"""Identity preference quiz engine.

Phase 2 of the "preference-based kibbe identification" feature. The
quiz runs in two stages:

1. ``stock``: pre-rendered reference looks for all 20 subtypes are shown
   to the user, one look per subtype. The algorithmic winner (if any) is
   surfaced first. The user likes/dislikes cards, the top-3 most liked
   subtypes advance.
2. ``tryon``: the 3 finalists go through virtual try-on on the user's
   own figure photo. Whichever subtype wins the most likes in this
   stage becomes the preference-based kibbe type, stored on
   :class:`StyleProfile` as ``kibbe_type_preference``.

This module owns the *pure* logic — candidate assembly, vote recording,
stage resolution, finalist try-on triggering. Persistence of the quiz
session itself and the derived profile fields is the route layer's
responsibility (it owns the HTTP boundary).
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.preference_quiz_session import PreferenceQuizSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- constants

REFERENCE_LOOKS_DIR = Path("config/rules/reference_looks")
IDENTITY_SUBTYPE_PROFILES_FILE = Path("config/rules/identity_subtype_profiles.yaml")

ACTION_LIKE = "like"
ACTION_DISLIKE = "dislike"

EVENT_LIKED = "style_preference_liked"
EVENT_DISLIKED = "style_preference_disliked"

STAGE_STOCK = "stock"
STAGE_TRYON = "tryon"


# ---------------------------------------------------------------- helpers


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_yaml(path: Path) -> dict | list | None:
    """Load a YAML file, returning ``None`` if it does not exist."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_subtype_profiles() -> dict[str, dict]:
    """Return the ``identity_subtype_profiles`` map keyed by subtype id."""
    raw = _load_yaml(IDENTITY_SUBTYPE_PROFILES_FILE) or {}
    data = raw.get("identity_subtype_profiles", {}) if isinstance(raw, dict) else {}
    return data if isinstance(data, dict) else {}


def _load_reference_looks_for_subtype(subtype: str) -> list[dict] | None:
    """Return the ``reference_looks`` list for a subtype, or ``None``.

    ``None`` means we couldn't find a YAML file for this subtype; the
    caller is expected to skip the subtype with a warning log.
    """
    path = REFERENCE_LOOKS_DIR / f"{subtype}.yaml"
    raw = _load_yaml(path)
    if not isinstance(raw, dict):
        return None
    looks = raw.get("reference_looks")
    if not isinstance(looks, list) or not looks:
        return None
    return looks


def _pick_representative_look(looks: list[dict]) -> dict | None:
    """Pick one representative look out of a subtype's look list.

    Deterministic: we always take the first look in the YAML (author
    ordering). If in the future we want variety we can swap this for a
    hash-based pick; for now "first" is the simplest honest choice.
    """
    for look in looks:
        if isinstance(look, dict):
            return look
    return None


def _look_to_candidate(
    subtype: str,
    subtype_profile: dict | None,
    look: dict,
) -> dict:
    """Convert a look YAML dict into a stock-stage candidate dict."""
    look_id = str(look.get("id") or f"{subtype}_default")
    # Prefer an explicit image_url on the look, then look.image,
    # then a derived placeholder path so the frontend can at least
    # render something deterministic.
    image_url = (
        look.get("image_url")
        or look.get("image")
        or f"/static/reference_looks/{subtype}/{look_id}.jpg"
    )
    title = (
        look.get("name")
        or (subtype_profile.get("display_name_ru") if subtype_profile else None)
        or subtype
    )
    return {
        "candidate_id": f"{subtype}:{look_id}",
        "subtype": subtype,
        "look_id": look_id,
        "image_url": image_url,
        "title": title,
        "stage": STAGE_STOCK,
    }


# ---------------------------------------------------------------- stage 1: stock


def build_stock_candidates(
    user_id: uuid.UUID,
    db: Any,
    algorithmic_subtype: str | None = None,
) -> list[dict]:
    """Build the list of stock-stage candidate cards.

    One card per subtype that has a reference_looks YAML. Subtypes
    without a YAML file are skipped with a warning (this is expected
    during the rollout — only ``flamboyant_gamine`` is populated today).

    If ``algorithmic_subtype`` is provided and it has a YAML, its card
    is moved to the front of the list so the user sees the
    algorithm's best guess first.
    """
    profiles = _load_subtype_profiles()
    if not profiles:
        logger.warning(
            "identity_subtype_profiles.yaml missing or empty; no candidates built"
        )
        return []

    candidates: list[dict] = []
    skipped: list[str] = []
    for subtype, profile in profiles.items():
        looks = _load_reference_looks_for_subtype(subtype)
        if looks is None:
            skipped.append(subtype)
            continue
        look = _pick_representative_look(looks)
        if look is None:
            skipped.append(subtype)
            continue
        candidates.append(_look_to_candidate(subtype, profile, look))

    if skipped:
        logger.warning(
            "preference_quiz: no reference_looks YAML for subtypes=%s (skipped)",
            skipped,
        )

    # Surface the algorithmic winner first if it made it into the list.
    if algorithmic_subtype:
        for idx, card in enumerate(candidates):
            if card["subtype"] == algorithmic_subtype and idx != 0:
                candidates.insert(0, candidates.pop(idx))
                break

    logger.info(
        "preference_quiz: built %d stock candidates for user=%s (algorithmic=%s)",
        len(candidates),
        user_id,
        algorithmic_subtype,
    )
    return candidates


# ---------------------------------------------------------------- voting


def record_vote(
    session: PreferenceQuizSession,
    candidate_id: str,
    action: str,
    db: Any,
) -> PreferenceQuizSession:
    """Append a vote to the session and fire a feedback event.

    ``action`` is validated against the two accepted values.
    """
    if action not in (ACTION_LIKE, ACTION_DISLIKE):
        raise ValueError(f"invalid vote action: {action!r}")

    # Find the candidate in the session to derive the subtype / stage.
    # If the candidate is not in ``candidates_json`` we still record the
    # vote so that frontend clock-skew between advance and vote doesn't
    # silently drop input.
    candidates = list(session.candidates_json or [])
    candidate = next(
        (c for c in candidates if isinstance(c, dict) and c.get("candidate_id") == candidate_id),
        None,
    )
    subtype = candidate.get("subtype") if candidate else None
    stage = (candidate.get("stage") if candidate else None) or session.stage or STAGE_STOCK

    vote = {
        "candidate_id": candidate_id,
        "action": action,
        "at": _now_iso(),
    }
    # JSONB columns are only detected as "dirty" by SQLAlchemy when the
    # attribute is reassigned, so we rebuild the list in full.
    votes = list(session.votes_json or [])
    votes.append(vote)
    session.votes_json = votes

    event_type = EVENT_LIKED if action == ACTION_LIKE else EVENT_DISLIKED
    try:
        # Lazy import: FeedbackService transitively pulls SQLAlchemy
        # via its repositories. Keeping it out of module scope means
        # unit tests that only exercise pure logic don't need a DB.
        from app.services.feedback_service import FeedbackService

        FeedbackService(db).process(
            user_id=session.user_id,
            event_type=event_type,
            payload={
                "subtype": subtype,
                "candidate_id": candidate_id,
                "stage": stage,
            },
        )
    except Exception as exc:  # pragma: no cover - feedback is best-effort
        logger.warning(
            "preference_quiz: FeedbackService.process failed (user=%s): %s",
            session.user_id,
            exc,
        )

    return session


# ---------------------------------------------------------------- stage 1 → 2 resolve


def _subtype_for_candidate_id(session: PreferenceQuizSession, candidate_id: str) -> str | None:
    for c in session.candidates_json or []:
        if isinstance(c, dict) and c.get("candidate_id") == candidate_id:
            return c.get("subtype")
    return None


def resolve_stock_stage(session: PreferenceQuizSession) -> list[str]:
    """Return the top-3 subtypes by number of likes in the stock stage.

    Returns an empty list if fewer than 3 distinct subtypes received a
    like — the caller should interpret this as "needs more likes" and
    prompt the user.
    """
    like_counts: Counter[str] = Counter()
    for vote in session.votes_json or []:
        if not isinstance(vote, dict):
            continue
        if vote.get("action") != ACTION_LIKE:
            continue
        candidate_id = vote.get("candidate_id")
        if not candidate_id:
            continue
        subtype = _subtype_for_candidate_id(session, candidate_id)
        if subtype is None:
            # Stage filter: only count stock-stage votes. We can
            # identify stage via the candidate record; if the candidate
            # is gone we skip the vote.
            continue
        # Enforce stage == stock by checking the candidate record.
        candidate = next(
            (c for c in (session.candidates_json or []) if isinstance(c, dict) and c.get("candidate_id") == candidate_id),
            None,
        )
        if candidate and candidate.get("stage") not in (None, STAGE_STOCK):
            continue
        like_counts[subtype] += 1

    if len(like_counts) < 3:
        return []

    # ``most_common`` is stable for equal counts by insertion order, so
    # ties fall back to "whichever subtype was voted on first" — a
    # deterministic ordering that matches how the frontend rendered the
    # cards.
    return [subtype for subtype, _ in like_counts.most_common(3)]


# ---------------------------------------------------------------- stage 2: tryon


def _pick_tryon_item_for_subtype(
    subtype: str,
    user_id: uuid.UUID,
    db: Any,
) -> tuple[uuid.UUID, str] | tuple[None, str | None]:
    """Pick the wardrobe item id to try on for a given subtype.

    Returns ``(item_id, source)`` where ``source`` is either the path
    taken (``"wardrobe_top"``, ``"wardrobe_fallback"``, ``"reference"``)
    or ``None`` if nothing suitable was found. ``item_id`` is ``None``
    in the latter case.

    We look for a wardrobe item matching the ``top`` slot of the
    subtype's first look; failing that we take the first wardrobe item.
    If the user's wardrobe is empty and the YAML look carries a
    ``reference_item_id``, we fall back to that id. Otherwise we
    return ``(None, None)`` — the caller skips the finalist with a
    warning.
    """
    looks = _load_reference_looks_for_subtype(subtype) or []
    look = _pick_representative_look(looks) if looks else None
    top_categories: list[str] = []
    reference_item_id: str | None = None
    if isinstance(look, dict):
        reference_item_id = look.get("reference_item_id")
        for item in look.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("slot") in ("top", "blazer", "dress", "dress_or_set"):
                raw_cats = (item.get("requires") or {}).get("category")
                if isinstance(raw_cats, str):
                    top_categories.append(raw_cats)
                elif isinstance(raw_cats, list):
                    top_categories.extend(str(c) for c in raw_cats)
                break

    # Ask the DB for a matching wardrobe item. We use a tiny inline
    # import so this module stays import-light for unit tests.
    try:
        from sqlalchemy import select

        from app.models.wardrobe_item import WardrobeItem

        if top_categories:
            stmt = (
                select(WardrobeItem)
                .where(WardrobeItem.user_id == user_id)
                .where(WardrobeItem.category.in_(top_categories))
                .limit(1)
            )
            hit = db.execute(stmt).scalars().first()
            if hit is not None:
                return hit.id, "wardrobe_top"

        stmt = (
            select(WardrobeItem)
            .where(WardrobeItem.user_id == user_id)
            .limit(1)
        )
        hit = db.execute(stmt).scalars().first()
        if hit is not None:
            return hit.id, "wardrobe_fallback"
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning(
            "preference_quiz: wardrobe lookup for subtype=%s failed: %s",
            subtype,
            exc,
        )

    if reference_item_id:
        try:
            return uuid.UUID(str(reference_item_id)), "reference"
        except (ValueError, TypeError):
            logger.warning(
                "preference_quiz: reference_item_id=%r is not a UUID (subtype=%s)",
                reference_item_id,
                subtype,
            )

    return None, None


async def build_tryon_finalists(
    session: PreferenceQuizSession,
    user_figure_photo_id: uuid.UUID,
    tryon_service: Any,
    db: Any,
) -> list[dict]:
    """Kick off try-on jobs for the top-3 subtypes and record them.

    Each finalist becomes a new candidate row in
    ``session.candidates_json`` with ``stage=tryon`` and a
    ``tryon_job_id`` pointing at the launched job.

    If we can't find a wardrobe item (or a YAML reference fallback)
    for a subtype, we log a warning and skip that finalist — the
    remaining finalists still proceed.
    """
    finalists = resolve_stock_stage(session)
    if not finalists:
        logger.info(
            "preference_quiz: advance-to-tryon called but no top-3 finalists (user=%s)",
            session.user_id,
        )
        return []

    new_cards: list[dict] = []
    for subtype in finalists:
        item_id, source = _pick_tryon_item_for_subtype(subtype, session.user_id, db)
        if item_id is None:
            logger.warning(
                "preference_quiz: no try-on item for subtype=%s (user=%s), skipping finalist",
                subtype,
                session.user_id,
            )
            continue
        try:
            response = await tryon_service.generate(
                user_id=session.user_id,
                item_id=item_id,
                user_photo_id=user_figure_photo_id,
            )
        except Exception as exc:
            logger.warning(
                "preference_quiz: TryOnService.generate failed for subtype=%s: %s",
                subtype,
                exc,
            )
            continue
        job_id = (response or {}).get("job_id") if isinstance(response, dict) else None
        if not job_id:
            logger.warning(
                "preference_quiz: TryOnService.generate returned no job_id for subtype=%s",
                subtype,
            )
            continue
        card = {
            "candidate_id": f"{subtype}:tryon:{job_id}",
            "subtype": subtype,
            "tryon_job_id": job_id,
            "item_source": source,
            "stage": STAGE_TRYON,
        }
        new_cards.append(card)

    # Append to candidates_json; reassign to trigger JSONB dirty flag.
    candidates = list(session.candidates_json or [])
    candidates.extend(new_cards)
    session.candidates_json = candidates

    logger.info(
        "preference_quiz: launched %d try-on finalists for user=%s",
        len(new_cards),
        session.user_id,
    )
    return new_cards


# ---------------------------------------------------------------- stage 2 resolve


def resolve_final_winner(session: PreferenceQuizSession) -> dict:
    """Compute the winning subtype among the try-on finalists.

    Counts likes for ``stage == "tryon"`` candidates only. Confidence
    is ``likes_for_winner / total_tryon_likes``, in ``[0.0, 1.0]``.

    Returns ``{"winner": None, "confidence": 0.0, "ranking": []}`` when
    there are zero try-on likes.
    """
    # Map candidate_id → subtype, but only for try-on cards.
    tryon_subtype_by_cid: dict[str, str] = {}
    for c in session.candidates_json or []:
        if not isinstance(c, dict):
            continue
        if c.get("stage") != STAGE_TRYON:
            continue
        cid = c.get("candidate_id")
        subtype = c.get("subtype")
        if cid and subtype:
            tryon_subtype_by_cid[cid] = subtype

    like_counts: Counter[str] = Counter()
    for vote in session.votes_json or []:
        if not isinstance(vote, dict):
            continue
        if vote.get("action") != ACTION_LIKE:
            continue
        cid = vote.get("candidate_id")
        if cid not in tryon_subtype_by_cid:
            continue
        like_counts[tryon_subtype_by_cid[cid]] += 1

    total = sum(like_counts.values())
    if total == 0:
        return {"winner": None, "confidence": 0.0, "ranking": []}

    ranking = [
        {"subtype": subtype, "likes": likes, "share": likes / total}
        for subtype, likes in like_counts.most_common()
    ]
    winner = ranking[0]["subtype"]
    confidence = ranking[0]["likes"] / total
    return {
        "winner": winner,
        "confidence": confidence,
        "ranking": ranking,
    }


__all__ = [
    "ACTION_DISLIKE",
    "ACTION_LIKE",
    "EVENT_DISLIKED",
    "EVENT_LIKED",
    "STAGE_STOCK",
    "STAGE_TRYON",
    "build_stock_candidates",
    "build_tryon_finalists",
    "record_vote",
    "resolve_final_winner",
    "resolve_stock_stage",
]
