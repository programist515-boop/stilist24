"""Identity preference quiz engine.

Two-step flow:

1. ``stock``: pre-rendered reference looks for all configured subtypes
   are shown to the user, one look per subtype. The algorithmic winner
   (if any) is surfaced first. The user likes/dislikes cards.
2. After ≥3 distinct subtypes have been liked, the backend can:
   - run :func:`build_wardrobe_match` to project each liked look against
     the user's wardrobe (matched items + missing slots), and
   - run :func:`resolve_final_winner` to pick the dominant subtype from
     the same stock votes (used to write
     :attr:`StyleProfile.kibbe_type_preference`).

Earlier iterations had a virtual-try-on second stage powered by FASHN.
That branch has been removed: matching the wardrobe to the liked looks
is the actual signal users wanted ("can I assemble this outfit from
what I own — and what's missing?"), and try-on for individual items
already lives on the dedicated ``/tryon`` page.
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
    from app.services.reference_matcher import ReferenceLookMatch

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- constants

REFERENCE_LOOKS_DIR = Path("config/rules/reference_looks")
IDENTITY_SUBTYPE_PROFILES_FILE = Path("config/rules/identity_subtype_profiles.yaml")

ACTION_LIKE = "like"
ACTION_DISLIKE = "dislike"

EVENT_LIKED = "style_preference_liked"
EVENT_DISLIKED = "style_preference_disliked"

#: All identity quiz cards live in the ``stock`` stage now. Constant
#: kept for backwards-compatible test code and DB fixtures that still
#: reference it.
STAGE_STOCK = "stock"


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


# ---------------------------------------------------------------- stage resolve helpers


def _candidate_index(session: PreferenceQuizSession) -> dict[str, dict]:
    """Map candidate_id → candidate dict (skipping malformed entries)."""
    index: dict[str, dict] = {}
    for c in session.candidates_json or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("candidate_id")
        if cid:
            index[cid] = c
    return index


def _iter_stock_likes(session: PreferenceQuizSession) -> list[dict]:
    """Return candidate dicts for every liked stock-stage vote.

    Dislikes, votes against unknown candidates, and votes against
    non-stock candidates are filtered out. Order matches ``votes_json``
    so callers can use ``Counter.most_common()`` for stable ranking.
    """
    candidates = _candidate_index(session)
    out: list[dict] = []
    for vote in session.votes_json or []:
        if not isinstance(vote, dict):
            continue
        if vote.get("action") != ACTION_LIKE:
            continue
        cid = vote.get("candidate_id")
        if not cid:
            continue
        candidate = candidates.get(cid)
        if not candidate:
            continue
        if (candidate.get("stage") or STAGE_STOCK) != STAGE_STOCK:
            continue
        out.append(candidate)
    return out


def resolve_stock_stage(session: PreferenceQuizSession) -> list[str]:
    """Return the top-3 subtypes by number of likes in the stock stage.

    Returns an empty list if fewer than 3 distinct subtypes received a
    like — the caller should interpret this as "needs more likes" and
    prompt the user.
    """
    like_counts: Counter[str] = Counter()
    for candidate in _iter_stock_likes(session):
        subtype = candidate.get("subtype")
        if subtype:
            like_counts[subtype] += 1

    if len(like_counts) < 3:
        return []

    # ``most_common`` is stable for equal counts by insertion order, so
    # ties fall back to "whichever subtype was voted on first" — a
    # deterministic ordering that matches how the frontend rendered the
    # cards.
    return [subtype for subtype, _ in like_counts.most_common(3)]


# ---------------------------------------------------------------- wardrobe match


def build_wardrobe_match(
    session: PreferenceQuizSession,
    wardrobe: list[Any],
) -> list[tuple[str, ReferenceLookMatch]]:
    """For each liked stock look, project it against the user's wardrobe.

    Returns a list of ``(subtype, ReferenceLookMatch)`` tuples — one per
    distinct ``(subtype, look_id)`` the user liked, in the order the
    likes were cast. Each match contains ``matched_items``,
    ``missing_slots`` (with shopping hints) and ``completeness``,
    sourced from :class:`ReferenceMatcher`.

    Looks whose YAML is missing or whose ``look_id`` is unknown are
    skipped with a warning — the caller still gets matches for every
    well-formed liked look.
    """
    # Local imports keep this module DB-free for unit tests that don't
    # need the full reference_matcher chain.
    from app.services.reference_matcher import (
        ReferenceMatcher,
        _item_blocked_by_global_stop,
        _load_reference_looks_yaml,
    )

    # Collect ``(subtype, look_id)`` pairs in like-order, deduplicated.
    seen: set[tuple[str, str]] = set()
    pairs: list[tuple[str, str]] = []
    for candidate in _iter_stock_likes(session):
        subtype = candidate.get("subtype")
        look_id = candidate.get("look_id")
        if not subtype or not look_id:
            continue
        key = (str(subtype), str(look_id))
        if key in seen:
            continue
        seen.add(key)
        pairs.append(key)

    if not pairs:
        return []

    matcher = ReferenceMatcher()
    # Cache YAML loads + filtered wardrobes per subtype so multiple
    # liked looks of the same subtype don't re-read the file or
    # re-walk the global stop list.
    yaml_cache: dict[str, dict] = {}
    allowed_cache: dict[str, list[Any]] = {}

    results: list[tuple[str, ReferenceLookMatch]] = []
    for subtype, look_id in pairs:
        data = yaml_cache.get(subtype)
        if data is None:
            data = _load_reference_looks_yaml(subtype) or {}
            yaml_cache[subtype] = data
        looks = data.get("reference_looks") if isinstance(data, dict) else None
        if not isinstance(looks, list):
            logger.warning(
                "wardrobe_match: no reference_looks for subtype=%s", subtype
            )
            continue

        look = next(
            (
                entry
                for entry in looks
                if isinstance(entry, dict) and str(entry.get("id") or "") == look_id
            ),
            None,
        )
        if look is None:
            logger.warning(
                "wardrobe_match: look_id=%s not found in subtype=%s YAML",
                look_id,
                subtype,
            )
            continue

        allowed = allowed_cache.get(subtype)
        if allowed is None:
            global_stop = data.get("global_stop_items") or []
            allowed = [
                item
                for item in wardrobe
                if _item_blocked_by_global_stop(item, global_stop) is None
            ]
            allowed_cache[subtype] = allowed

        match = matcher._match_one_look(look, allowed, subtype)
        results.append((subtype, match))

    logger.info(
        "preference_quiz: built %d wardrobe matches for user=%s",
        len(results),
        session.user_id,
    )
    return results


# ---------------------------------------------------------------- complete


def resolve_final_winner(session: PreferenceQuizSession) -> dict:
    """Compute the winning subtype from the stock-stage likes.

    Counts ``like`` votes against ``stock`` candidates only. Confidence
    is ``likes_for_winner / total_stock_likes`` in ``[0.0, 1.0]``.

    Returns ``{"winner": None, "confidence": 0.0, "ranking": []}`` when
    there are zero stock likes — the caller (route layer) decides
    whether to surface an error or persist the empty result.
    """
    like_counts: Counter[str] = Counter()
    for candidate in _iter_stock_likes(session):
        subtype = candidate.get("subtype")
        if subtype:
            like_counts[subtype] += 1

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
    "build_stock_candidates",
    "build_wardrobe_match",
    "record_vote",
    "resolve_final_winner",
    "resolve_stock_stage",
]
