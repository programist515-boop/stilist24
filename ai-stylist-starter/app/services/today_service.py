"""Today feature — pick three labeled outfit suggestions for the current day.

The service orchestrates existing building blocks (wardrobe repository,
``StyleProfile``, ``PersonalizationProfile``, ``OutfitEngine``,
``ScoringService``) into a pool of candidate outfits, then applies three
deterministic selection strategies:

    * ``safe``       — highest rule fit, lowest experimentation / visual risk
    * ``balanced``   — strongest overall score with the best rules + prefs blend
    * ``expressive`` — strongest personalization pull, allows experimentation

Selection is a pure function over the scored pool — no new scoring formulas
are introduced here. Weather is an optional deterministic hint (no external
APIs): a small mapping deflects outfits whose **explicit** season tags
contradict the requested weather.
"""

import uuid
from typing import TYPE_CHECKING, Any, Callable, Iterable

from app.services.explainer import Explanation, explain_outfit
from app.services.outfit_engine import OutfitEngine
from app.services.scoring_service import cosine_like
from app.services.user_context import build_user_context

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.models.style_profile import StyleProfile
    from app.services.outfits.outfit_generator import OutfitGenerator


# Weather → season hints. Unknown values are echoed back and ignored.
WEATHER_SEASON_HINTS: dict[str, frozenset[str]] = {
    "cold": frozenset({"winter"}),
    "snow": frozenset({"winter"}),
    "hot": frozenset({"summer"}),
    "warm": frozenset({"summer", "spring"}),
    "cool": frozenset({"autumn", "spring"}),
    "rain": frozenset({"autumn", "spring"}),
    "mild": frozenset({"spring", "autumn"}),
}

SLOT_ORDER: tuple[str, ...] = ("safe", "balanced", "expressive")


def _mean(values: Iterable[float]) -> float:
    seq = list(values)
    return sum(seq) / len(seq) if seq else 0.0


def _to_flat_item(item) -> dict:
    """Normalize a wardrobe item (ORM or dict) to the flat dict shape the
    outfit engine and tests share."""
    if hasattr(item, "attributes_json"):
        attrs = dict(item.attributes_json or {})
        base = {
            "id": str(item.id),
            "category": item.category,
            "name": attrs.get("name"),
            "attributes": attrs,
            **attrs,
        }
        return base
    if isinstance(item, dict):
        return item
    return {}


class TodayService:
    #: Pool size requested from :class:`OutfitEngine`. Small enough to stay
    #: fast, wide enough to give the three strategies elbow room.
    POOL_SIZE: int = 12

    def __init__(
        self,
        db: "Session | None" = None,
        *,
        outfit_engine: OutfitEngine | None = None,
        outfit_generator: "OutfitGenerator | None" = None,
        wardrobe_loader: Callable[[uuid.UUID], list[dict]] | None = None,
        style_profile_loader: Callable[[uuid.UUID], Any] | None = None,
        personalization_loader: Callable[[uuid.UUID], Any] | None = None,
    ) -> None:
        self.db = db
        self._outfit_generator = outfit_generator
        self.outfit_engine = outfit_engine or OutfitEngine()
        self._wardrobe_loader = wardrobe_loader
        self._style_profile_loader = style_profile_loader
        self._personalization_loader = personalization_loader

    # --------------------------------------------------------- data loading

    def _load_wardrobe(self, user_id: uuid.UUID) -> list[dict]:
        if self._wardrobe_loader is not None:
            return self._wardrobe_loader(user_id)
        if self.db is None:
            return []
        # Lazy import so the service can be unit-tested without SQLAlchemy.
        from app.repositories.wardrobe_repository import WardrobeRepository

        raw = WardrobeRepository(self.db).list_by_user(user_id)
        return [_to_flat_item(i) for i in raw]

    def _load_style_profile(self, user_id: uuid.UUID):
        if self._style_profile_loader is not None:
            return self._style_profile_loader(user_id)
        if self.db is None:
            return None
        from app.models.style_profile import StyleProfile

        return self.db.get(StyleProfile, user_id)

    def _load_personalization(self, user_id: uuid.UUID):
        if self._personalization_loader is not None:
            return self._personalization_loader(user_id)
        if self.db is None:
            return None
        from app.repositories.personalization_repository import (
            PersonalizationRepository,
        )

        return PersonalizationRepository(self.db).get_or_create(user_id)

    def _build_user_context(self, user_id: uuid.UUID) -> tuple[dict, float]:
        style = self._load_style_profile(user_id)
        perso = self._load_personalization(user_id)
        user_context = build_user_context(style, perso)
        experimentation_score = float(
            getattr(perso, "experimentation_score", 0.3) or 0.3
        )
        return user_context, experimentation_score

    # ----------------------------------------------------------- public API

    def get_today(
        self,
        user_id: uuid.UUID,
        weather: str | None = None,
        occasion: str | None = None,
    ) -> dict:
        notes: list[str] = []
        items = self._load_wardrobe(user_id)

        if not items:
            return {
                "weather": weather,
                "occasion": occasion,
                "outfits": [],
                "notes": ["wardrobe is empty — add items to see Today picks"],
            }

        user_context, experimentation_score = self._build_user_context(user_id)

        if self._outfit_generator is not None:
            pool = self._outfit_generator.generate(
                items,
                user_profile=user_context,
                occasion=occasion,
                top_n=self.POOL_SIZE,
            )
        else:
            pool = self.outfit_engine.generate(
                items,
                user_context=user_context,
                occasion=occasion,
                top_n=self.POOL_SIZE,
            )

        if weather:
            pool = self._apply_weather_hint(pool, weather, notes)

        if not pool:
            notes.insert(
                0,
                "no valid outfits could be generated — try adding more items "
                "or relaxing filters",
            )
            return {
                "weather": weather,
                "occasion": occasion,
                "outfits": [],
                "notes": notes,
            }

        selected = self.select_from_pool(
            pool, user_context, experimentation_score
        )

        if len(selected) < len(SLOT_ORDER):
            notes.append(
                f"only {len(selected)} distinct outfit(s) available for "
                f"Today slots — wardrobe may be too small"
            )

        return {
            "weather": weather,
            "occasion": occasion,
            "outfits": selected,
            "notes": notes,
        }

    # ---------------------------------------------------- weather soft hint

    @staticmethod
    def _outfit_season_set(outfit: dict) -> set[str] | None:
        """Intersection of explicit, non-all-season tags across items.

        Returns ``None`` when the outfit has no explicit season information
        on any item (the soft filter leaves those alone).
        """
        tagged_sets: list[set[str]] = []
        any_all_season = False
        for it in outfit.get("items", []):
            tags = it.get("season") or []
            if not tags:
                continue
            if "all_season" in tags:
                any_all_season = True
                continue
            tagged_sets.append(set(tags))
        if any_all_season:
            return None
        if not tagged_sets:
            return None
        return set.intersection(*tagged_sets) if tagged_sets else None

    def _apply_weather_hint(
        self,
        pool: list[dict],
        weather: str,
        notes: list[str],
    ) -> list[dict]:
        hint = WEATHER_SEASON_HINTS.get(weather.lower())
        if not hint:
            notes.append(f"weather '{weather}' not recognized — ignored")
            return pool
        filtered: list[dict] = []
        dropped = 0
        for outfit in pool:
            season_set = self._outfit_season_set(outfit)
            if season_set is not None and not (season_set & hint):
                dropped += 1
                continue
            filtered.append(outfit)
        if dropped:
            notes.append(
                f"weather '{weather}' dropped {dropped} outfit(s) with "
                f"conflicting season tags"
            )
        return filtered

    # ------------------------------------------------ pool → three strategies

    def select_from_pool(
        self,
        pool: list[dict],
        user_context: dict,
        experimentation_score: float,
    ) -> list[dict]:
        """Pure selection: pick up to 3 distinct outfits labeled
        ``safe``, ``balanced``, ``expressive``.

        Exposed as a public method so tests can exercise selection without
        touching the database.
        """
        if not pool:
            return []

        style_vector = user_context.get("style_vector") or {}
        annotated = [
            self._annotate(outfit, style_vector, experimentation_score)
            for outfit in pool
        ]

        used_signatures: set[tuple] = set()
        results: list[dict] = []

        # Order: balanced first (the anchor), then safe, then expressive.
        # Each slot picks its top-ranked outfit that has not been used yet.
        chosen_by_label: dict[str, dict] = {}
        for label in ("balanced", "safe", "expressive"):
            picked = self._pick_for_label(label, annotated, used_signatures)
            if picked is None:
                continue
            chosen_by_label[label] = picked
            used_signatures.add(OutfitEngine._base_signature(picked["outfit"]))

        # Emit in the spec-requested order: safe, balanced, expressive.
        for label in SLOT_ORDER:
            picked = chosen_by_label.get(label)
            if picked is None:
                continue
            results.append(
                {
                    "label": label,
                    "outfit": picked["outfit"],
                    "reasons": picked["reasons"],
                    "actions": picked.get("actions", []),
                    "explanation": picked.get("explanation", {}),
                }
            )
        return results

    # ------------------------------------------------------- selection utils

    @staticmethod
    def _rule_fit(outfit: dict) -> float:
        scores = outfit.get("scores") or {}
        # Support both OutfitEngine keys and OutfitGenerator keys
        silhouette = scores.get("silhouette_balance") if "silhouette_balance" in scores else scores.get("silhouette", 0.0)
        preference = scores.get("preference", 0.0)
        line_c = scores.get("line_consistency", preference)
        style_c = scores.get("style_consistency", preference)
        return _mean([
            scores.get("color_harmony", 0.0),
            silhouette,
            line_c,
            style_c,
        ])

    @staticmethod
    def _visual_risk(outfit: dict) -> float:
        risk = 0.0
        for it in outfit.get("items", []):
            if it.get("statement") is True:
                risk = max(risk, 1.0)
            if str(it.get("detail_density") or "").lower() == "high":
                risk = max(risk, 0.8)
        return risk

    @staticmethod
    def _experimentation(outfit: dict) -> float:
        scores = outfit.get("scores") or {}
        # Support both OutfitEngine ("style_consistency") and OutfitGenerator ("preference") keys
        style_consistency = float(
            scores.get("style_consistency") if "style_consistency" in scores else scores.get("preference", 1.0)
        )
        items = outfit.get("items") or []
        n = max(len(items), 1)
        statement = sum(
            1
            for it in items
            if it.get("statement") is True
            or str(it.get("detail_density") or "").lower() == "high"
        )
        outerwear = any(it.get("category") == "outerwear" for it in items)
        experimentation = (
            (statement / n) + (1.0 - style_consistency) + (0.2 if outerwear else 0.0)
        ) / 2.0
        return max(0.0, min(1.0, experimentation))

    @staticmethod
    def _personalization_pull(outfit: dict, style_vector: dict) -> float:
        if not style_vector:
            return 0.0
        item_tags: dict[str, float] = {}
        for it in outfit.get("items", []):
            for tag in it.get("style_tags") or []:
                item_tags[tag] = 1.0
        return cosine_like(item_tags, style_vector)

    @classmethod
    def _annotate(
        cls,
        outfit: dict,
        style_vector: dict,
        experimentation_score: float,
    ) -> dict:
        scores = outfit.get("scores") or {}
        return {
            "outfit": outfit,
            "overall": float(scores.get("overall", 0.0)),
            "rule_fit": cls._rule_fit(outfit),
            "experimentation": cls._experimentation(outfit),
            "visual_risk": cls._visual_risk(outfit),
            "personalization_pull": cls._personalization_pull(outfit, style_vector),
            "user_experimentation": experimentation_score,
            # Deterministic tiebreak based on item ids so two calls with
            # identical inputs always rank the same way.
            "tiebreak": tuple(
                str(it.get("id")) for it in outfit.get("items", [])
            ),
        }

    @classmethod
    def _pick_for_label(
        cls,
        label: str,
        annotated: list[dict],
        used_signatures: set[tuple],
    ) -> dict | None:
        """Ascending sort with negated-numeric keys so "higher is better"
        becomes "lower sorts first". The string tuple tiebreak is appended
        as-is so determinism holds across calls with identical inputs.
        """
        if label == "safe":
            def key(a: dict):
                return (
                    -a["rule_fit"],
                    a["experimentation"],
                    a["visual_risk"],
                    -a["overall"],
                    a["tiebreak"],
                )
            reason_builder = cls._safe_reasons
        elif label == "expressive":
            def key(a: dict):
                return (
                    -a["personalization_pull"],
                    -a["experimentation"],
                    -a["overall"],
                    a["tiebreak"],
                )
            reason_builder = cls._expressive_reasons
        else:  # balanced
            def key(a: dict):
                return (
                    -a["overall"],
                    -(a["rule_fit"] + a["personalization_pull"]),
                    a["tiebreak"],
                )
            reason_builder = cls._balanced_reasons

        ranked = sorted(annotated, key=key)
        for candidate in ranked:
            sig = OutfitEngine._base_signature(candidate["outfit"])
            if sig in used_signatures:
                continue
            outfit = candidate["outfit"]
            return {
                "outfit": outfit,
                "reasons": reason_builder(candidate),
                "actions": _outfit_actions(outfit, label),
                "explanation": explain_outfit(outfit).to_dict(),
            }
        return None

    # -------------------------------------------------------- reason builders

    @staticmethod
    def _safe_reasons(a: dict) -> list[str]:
        return [
            f"safe: rule_fit={a['rule_fit']:.2f} (highest rule alignment)",
            f"safe: experimentation={a['experimentation']:.2f} (low)",
            f"safe: visual_risk={a['visual_risk']:.2f} (low)",
            f"safe: overall={a['overall']:.2f}",
        ]

    @staticmethod
    def _balanced_reasons(a: dict) -> list[str]:
        blend = a["rule_fit"] + a["personalization_pull"]
        return [
            f"balanced: overall={a['overall']:.2f} (strongest)",
            f"balanced: rules+prefs blend={blend:.2f}",
            f"balanced: rule_fit={a['rule_fit']:.2f}, "
            f"personalization_pull={a['personalization_pull']:.2f}",
        ]

    @staticmethod
    def _expressive_reasons(a: dict) -> list[str]:
        return [
            f"expressive: personalization_pull={a['personalization_pull']:.2f} "
            f"(strongest)",
            f"expressive: experimentation={a['experimentation']:.2f} allowed "
            f"by user score {a['user_experimentation']:.2f}",
            f"expressive: overall={a['overall']:.2f}",
        ]


def _outfit_actions(outfit: dict, label: str) -> list[str]:
    """Generate context-aware action labels for a Today outfit slot."""
    actions = ["Wear today", "Save outfit"]
    cats = {it.get("category") for it in outfit.get("items", [])}
    # Normalise plural/singular
    has_top = bool({"top", "tops"} & cats)
    has_shoes = bool({"shoes"} & cats)
    has_outerwear = bool({"outerwear"} & cats)
    if has_top:
        actions.append("Replace top")
    if has_shoes:
        actions.append("Replace shoes")
    if has_outerwear:
        actions.append("Remove outerwear")
    if label == "expressive":
        actions.append("Too bold? Try balanced")
    return actions
