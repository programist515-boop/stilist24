"""Recommendation guide — curated stylist report keyed to the user's identity.

Takes a user's Kibbe family (from :class:`StyleProfile`), their color
profile, and the top tags of their personalization style vector, and
builds a structured editorial-style report in Russian: linings,
silhouettes, necklines, fabrics, textures, prints, details, jackets,
tops, what to emphasize, what to avoid.

The content is **curated**, not generated. Per-family copy lives in
``config/rules/recommendation_guides.yaml``; this service just loads
the bundle, resolves the Kibbe family, optionally adds a short color
summary and a hint of the user's top style tags, and returns a
structured response. Identical inputs always yield identical outputs,
exactly like :class:`TodayService`.

The service follows the same DI seam pattern as ``TodayService`` /
``InsightsService``: every collaborator can be replaced with a stub
for tests, and SQLAlchemy is only imported under ``TYPE_CHECKING``.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import yaml

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session


# ---------------------------------------------------------------- constants


KIBBE_FAMILIES: tuple[str, ...] = (
    "dramatic",
    "natural",
    "classic",
    "gamine",
    "romantic",
)


#: Canonical order for the sections in the response. The YAML file can
#: list them in any order — the service re-orders them so the frontend
#: always sees the same sequence.
SECTION_ORDER: tuple[str, ...] = (
    "lines_silhouette",
    "necklines",
    "fabrics",
    "textures",
    "prints",
    "details",
    "jackets",
    "tops",
    "emphasize",
    "avoid_overall",
)


# The rules file lives alongside other config/rules/*.yaml. We use a
# dedicated cached loader (instead of piggybacking on ``rules_loader``)
# to keep the blast radius small — the shared loader raises on missing
# files, which would break every other rules-backed feature if this
# file was removed by mistake.
_RULES_PATH = Path("config/rules/recommendation_guides.yaml")


@lru_cache(maxsize=1)
def _load_guides() -> dict[str, Any]:
    """Load and cache the curated guide bundle.

    Returned shape: ``{"dramatic": {...}, "natural": {...}, ...}``.
    """
    with _RULES_PATH.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("recommendation_guides") or {}


# ---------------------------------------------------------------- helpers


def _resolve_family(kibbe_type: str | None) -> str | None:
    """Map a Kibbe subtype (e.g. ``soft_dramatic``) to its family.

    The style profile stores a subtype when the analyzer is confident
    enough; otherwise it stores the family directly. Subtype strings
    follow ``<modifier>_<family>`` (``soft_natural``, ``flamboyant_gamine``)
    or just the family. We look for any known family token inside the
    string so both shapes resolve the same way.
    """
    if not kibbe_type:
        return None
    lowered = kibbe_type.strip().lower()
    if lowered in KIBBE_FAMILIES:
        return lowered
    for family in KIBBE_FAMILIES:
        if family in lowered:
            return family
    return None


def _color_profile_summary(color_profile: dict | None) -> str | None:
    """Build a short one-line human summary of the color profile.

    Example: ``"Холодный подтон · средняя глубина · мягкая насыщенность"``.
    Returns ``None`` when the profile is empty — the caller keeps the
    field as ``None`` instead of an awkward "neutral neutral neutral"
    sentence.
    """
    if not color_profile:
        return None

    undertone = str(color_profile.get("undertone") or "").lower()
    depth = str(color_profile.get("depth") or "").lower()
    chroma = str(color_profile.get("chroma") or "").lower()
    contrast = str(color_profile.get("contrast") or "").lower()

    parts: list[str] = []

    undertone_map = {
        "cool": "Холодный подтон",
        "warm": "Тёплый подтон",
        "neutral": "Нейтральный подтон",
        "olive": "Оливковый подтон",
    }
    if undertone and undertone in undertone_map:
        parts.append(undertone_map[undertone])

    depth_map = {
        "light": "светлая глубина",
        "medium": "средняя глубина",
        "deep": "глубокая глубина",
        "dark": "глубокая глубина",
    }
    if depth and depth in depth_map:
        parts.append(depth_map[depth])

    chroma_map = {
        "soft": "мягкая насыщенность",
        "muted": "приглушённая насыщенность",
        "bright": "яркая насыщенность",
        "clear": "чистая насыщенность",
    }
    if chroma and chroma in chroma_map:
        parts.append(chroma_map[chroma])

    contrast_map = {
        "low": "низкий контраст",
        "medium": "средний контраст",
        "high": "высокий контраст",
    }
    if contrast and contrast in contrast_map:
        parts.append(contrast_map[contrast])

    if not parts:
        return None
    return " · ".join(parts)


def _top_style_tags(style_vector: dict | None, limit: int = 3) -> list[str]:
    """Return the top-N tags of a style vector, ordered by weight desc.

    Deterministic: ties break on tag name (alphabetical) so two calls
    with identical inputs return the same order.
    """
    if not style_vector:
        return []
    pairs: list[tuple[float, str]] = []
    for tag, weight in style_vector.items():
        try:
            w = float(weight)
        except (TypeError, ValueError):
            continue
        if w <= 0:
            continue
        pairs.append((-w, str(tag)))
    pairs.sort()
    return [tag for _, tag in pairs[:limit]]


def _build_sections(raw_sections: list[Any]) -> list[dict]:
    """Normalise the raw YAML sections list into the response shape.

    * Reorders by :data:`SECTION_ORDER`; unknown keys go to the end in
      their original order.
    * Coerces ``recommended`` / ``avoid`` to lists of strings so a
      YAML typo doesn't leak a non-string into the response.
    * Drops sections without a key or title (defensive).
    """
    if not isinstance(raw_sections, list):
        return []

    by_key: dict[str, dict] = {}
    for entry in raw_sections:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        title = str(entry.get("title") or "").strip()
        if not key or not title:
            continue
        description = str(entry.get("description") or "").strip()
        recommended = [
            str(x).strip()
            for x in (entry.get("recommended") or [])
            if str(x).strip()
        ]
        avoid = [
            str(x).strip()
            for x in (entry.get("avoid") or [])
            if str(x).strip()
        ]
        by_key[key] = {
            "key": key,
            "title": title,
            "description": description,
            "recommended": recommended,
            "avoid": avoid,
        }

    ordered: list[dict] = []
    used: set[str] = set()
    for key in SECTION_ORDER:
        if key in by_key:
            ordered.append(by_key[key])
            used.add(key)
    for key, section in by_key.items():
        if key not in used:
            ordered.append(section)
    return ordered


# ---------------------------------------------------------------- service


StyleProfileLoader = Callable[[uuid.UUID], Any]
PersonalizationLoader = Callable[[uuid.UUID], Any]


class RecommendationGuideService:
    #: Empty-state response used when the user has no resolvable Kibbe
    #: family yet. The frontend renders a "сначала пройдите анализ"
    #: empty card off the ``notes`` list.
    EMPTY_STATE_NOTE: str = (
        "Чтобы получить персональные рекомендации, пройдите анализ "
        "в разделе «Анализ» — нам нужно определить вашу типологию."
    )

    def __init__(
        self,
        db: "Session | None" = None,
        *,
        style_profile_loader: StyleProfileLoader | None = None,
        personalization_loader: PersonalizationLoader | None = None,
        guides_loader: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.db = db
        self._style_profile_loader = style_profile_loader
        self._personalization_loader = personalization_loader
        self._guides_loader = guides_loader or _load_guides

    # ----- collaborators (lazy defaults) --------------------------------

    def _load_style_profile(self, user_id: uuid.UUID):
        if self._style_profile_loader is not None:
            return self._style_profile_loader(user_id)
        if self.db is None:
            return None
        from app.models.style_profile import StyleProfile  # lazy

        return self.db.get(StyleProfile, user_id)

    def _load_personalization(self, user_id: uuid.UUID):
        if self._personalization_loader is not None:
            return self._personalization_loader(user_id)
        if self.db is None:
            return None
        from app.repositories.personalization_repository import (  # lazy
            PersonalizationRepository,
        )

        return PersonalizationRepository(self.db).get_or_create(user_id)

    # ----- public API ---------------------------------------------------

    def get_guide(self, user_id: uuid.UUID) -> dict:
        style = self._load_style_profile(user_id)
        perso = self._load_personalization(user_id)

        kibbe_type_raw: str | None = (
            getattr(style, "kibbe_type", None) if style else None
        )
        color_profile: dict | None = (
            getattr(style, "color_profile_json", None) or {}
            if style
            else None
        )
        style_vector: dict | None = (
            getattr(perso, "style_vector_json", None) or {}
            if perso
            else None
        )

        family = _resolve_family(kibbe_type_raw)
        color_summary = _color_profile_summary(color_profile)
        top_tags = _top_style_tags(style_vector)

        notes: list[str] = []

        if family is None:
            notes.append(self.EMPTY_STATE_NOTE)
            return {
                "identity": {
                    "kibbe_family": None,
                    "kibbe_type": kibbe_type_raw,
                    "color_profile_summary": color_summary,
                    "style_key": None,
                    "top_style_tags": top_tags,
                },
                "summary": (
                    "Рекомендации появятся здесь, как только мы узнаем "
                    "вашу типологию. Это занимает пару минут — "
                    "достаточно трёх фотографий."
                ),
                "sections": [],
                "closing_note": "",
                "notes": notes,
            }

        guides = self._guides_loader() or {}
        bundle = guides.get(family)
        if not isinstance(bundle, dict):
            # YAML is malformed or the family is missing — degrade
            # gracefully instead of 500'ing the route.
            notes.append(
                f"Для вашей типологии ({family}) гид ещё не подготовлен."
            )
            return {
                "identity": {
                    "kibbe_family": family,
                    "kibbe_type": kibbe_type_raw,
                    "color_profile_summary": color_summary,
                    "style_key": None,
                    "top_style_tags": top_tags,
                },
                "summary": "",
                "sections": [],
                "closing_note": "",
                "notes": notes,
            }

        style_key = str(bundle.get("style_key") or "").strip() or None
        summary = str(bundle.get("summary") or "").strip()
        closing_note = str(bundle.get("closing_note") or "").strip()
        sections = _build_sections(bundle.get("sections") or [])

        if top_tags:
            notes.append(
                "Ваши сильные направления по предпочтениям: "
                + ", ".join(top_tags)
                + "."
            )

        return {
            "identity": {
                "kibbe_family": family,
                "kibbe_type": kibbe_type_raw,
                "color_profile_summary": color_summary,
                "style_key": style_key,
                "top_style_tags": top_tags,
            },
            "summary": summary,
            "sections": sections,
            "closing_note": closing_note,
            "notes": notes,
        }


__all__ = [
    "KIBBE_FAMILIES",
    "RecommendationGuideService",
    "SECTION_ORDER",
]
