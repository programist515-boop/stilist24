"""User analysis orchestration service.

Pipeline (synchronous):

1. Validate the uploaded photo set:
   - exactly 3 uploads
   - unique slots
   - exact slot set = {front, side, portrait}
2. For each slot (in canonical order ``front`` → ``side`` → ``portrait``):
   a. Mint a new ``photo_id`` up front (so the storage key is deterministic
      and matches the DB row).
   b. Upload the bytes through :class:`StorageService.upload_user_photo`.
   c. Persist a ``UserPhoto`` row via :class:`UserPhotoRepository.create`.
3. Compute the feature vector via the extractor seam (CV → structured
   fallback → emergency stub).
4. Run :class:`IdentityEngine` on the feature vector.  Extract colour
   axes from photos via ``color_feature_extractor`` (real pixel-based
   analysis); fall back to ``_derive_color_axes`` (heuristic bridge)
   if photo extraction fails.  Feed axes into :class:`ColorEngine`.
   Derive ``style_vector`` from the identity engine's family scores.
5. Return a response with ``kibbe``, ``color``, ``style_vector``,
   ``analyzed_at``, and ``photos`` (always in canonical slot order).

Partial-failure contract
------------------------

Photo persistence is upload-first, DB-row-after. If storage fails on the
second slot, the first slot's bytes remain in storage but no DB row points
at them. This is acceptable because:

* storage is the source of truth for bytes (``image_key`` is the canonical
  reference)
* orphan keys are cheap and can be garbage-collected out-of-band
* DB consistency is strictly more important than storage tidiness — we
  never want a row pointing at bytes that are not there

The service follows the same dependency-injection seam pattern as
``TryOnService`` / ``TodayService`` / ``InsightsService``: every
collaborator (storage, repository factory, feature extractor, engines)
can be replaced with a stub for tests, and SQLAlchemy is only imported
under :data:`TYPE_CHECKING` so the module is importable in environments
without it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from app.core.storage import (
    StorageError,
    StorageService,
    StorageValidationError,
)
from app.services.color_engine import ColorEngine
from app.services.feature_extractor import (
    PhotoReference,
    default_feature_extractor,
    feature_vector_fingerprint,
)
from app.services.identity_engine import IdentityEngine

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from app.repositories.user_photo_repository import UserPhotoRepository


# ---------------------------------------------------------------- constants


#: Canonical slot order. Both input validation and response serialisation
#: rely on this tuple — never iterate over a dict or a set here.
SLOT_ORDER: tuple[str, ...] = ("front", "side", "portrait")
_ALLOWED_SLOTS: frozenset[str] = frozenset(SLOT_ORDER)


# ---------------------------------------------------------------- errors


class UserAnalysisError(Exception):
    """Base class for user-analysis service errors."""


class UserAnalysisValidationError(UserAnalysisError):
    """The caller-supplied upload set is malformed (slots, count, duplicates)."""


class UserAnalysisStorageError(UserAnalysisError):
    """Persisting the uploaded photo bytes to storage failed."""


class UserAnalysisPersistenceError(UserAnalysisError):
    """Writing the ``user_photos`` row failed after a successful upload."""


# ---------------------------------------------------------------- input dataclass


@dataclass(frozen=True)
class AnalysisPhotoUpload:
    """An already-read photo upload ready to hand to the service.

    The route layer calls ``await file.read()`` once and wraps the bytes in
    this dataclass so the service is fully synchronous and never has to
    touch FastAPI's :class:`UploadFile`.
    """

    slot: str
    data: bytes
    content_type: str
    filename: str | None = None


# ---------------------------------------------------------------- stub feature vector


def _stub_features() -> dict[str, float]:
    """Emergency fallback user feature vector.

    Originally the one-and-only feature source, now retained as a safety
    net in case :class:`StructuredFeatureExtractor` raises. The service
    catches any exception from the extractor seam and falls back to this
    function so ``/user/analyze`` never 500s on a placeholder bug.

    The key set here must remain identical to
    :data:`app.services.feature_extractor.SCHEMA_KEYS` — the contract is
    enforced by ``test_stub_features_has_all_20_keys``.
    """
    return {
        "vertical_line": 0.42,
        "compactness": 0.71,
        "width": 0.40,
        "bone_sharpness": 0.31,
        "bone_bluntness": 0.22,
        "softness": 0.74,
        "curve_presence": 0.69,
        "symmetry": 0.44,
        "facial_sharpness": 0.28,
        "facial_roundness": 0.67,
        "waist_definition": 0.73,
        "narrowness": 0.40,
        "relaxed_line": 0.20,
        "proportion_balance": 0.45,
        "moderation": 0.40,
        "line_contrast": 0.61,
        "small_scale": 0.66,
        "feature_juxtaposition": 0.58,
        "controlled_softness_or_sharpness": 0.33,
        "low_line_contrast": 0.39,
    }


def _stub_color_axes() -> dict[str, str]:
    """Emergency fallback color axes when nothing better is available."""
    return {
        "undertone": "cool-neutral",
        "contrast": "medium-low",
        "depth": "medium",
        "chroma": "soft",
    }


def _stub_style_vector() -> dict[str, float]:
    """Emergency fallback style vector when nothing better is available."""
    return {"classic": 0.4, "romantic": 0.35, "natural": 0.25}


# ---------------------------------------------------------------- feature-derived helpers


def _derive_color_axes(features: dict[str, float]) -> dict[str, str]:
    """FALLBACK HEURISTIC BRIDGE — used when photo-based color extraction fails.

    Maps geometric body features to colour-axis labels so that different
    feature vectors at least produce different ``ColorEngine`` outputs.
    The mapping is purely arithmetic (softness → chroma, line_contrast →
    contrast, etc.) and has **no access to pixel-level skin, hair, or eye
    colour data**.

    This is NOT real colour detection.  The primary path is now
    ``color_feature_extractor.extract_color_axes()`` which reads actual
    photo pixels.  This function is the second-level fallback when the
    photo-based pipeline fails (no face detected, bad image, etc.).

    The output feeds into ``ColorEngine.analyze()`` which maps axes to
    colour seasons via ``season_families.yaml``.
    """
    softness = features.get("softness", 0.5)
    bone_sharpness = features.get("bone_sharpness", 0.5)
    line_contrast = features.get("line_contrast", 0.5)
    facial_roundness = features.get("facial_roundness", 0.5)

    # undertone: soft + round → warm; sharp + angular → cool
    warmth = (softness + facial_roundness) / 2.0
    if warmth > 0.6:
        undertone = "warm" if warmth > 0.75 else "neutral-warm"
    elif warmth < 0.4:
        undertone = "cool" if warmth < 0.25 else "cool-neutral"
    else:
        undertone = "neutral-warm" if warmth >= 0.5 else "cool-neutral"

    # contrast: line_contrast maps directly
    if line_contrast > 0.65:
        contrast = "high" if line_contrast > 0.8 else "medium-high"
    elif line_contrast < 0.35:
        contrast = "low" if line_contrast < 0.2 else "medium-low"
    else:
        contrast = "medium"

    # depth: bone_sharpness as proxy (sharp → deep, blunt → light)
    if bone_sharpness > 0.6:
        depth = "deep" if bone_sharpness > 0.75 else "medium-deep"
    elif bone_sharpness < 0.4:
        depth = "light" if bone_sharpness < 0.25 else "medium-light"
    else:
        depth = "medium"

    # chroma: inverse of softness (soft features → soft chroma)
    if softness > 0.6:
        chroma = "soft" if softness > 0.75 else "medium-soft"
    elif softness < 0.4:
        chroma = "bright" if softness < 0.25 else "medium-bright"
    else:
        chroma = "medium-soft" if softness >= 0.5 else "medium-bright"

    return {
        "undertone": undertone,
        "contrast": contrast,
        "depth": depth,
        "chroma": chroma,
    }


def _derive_style_vector(
    family_scores: dict[str, float],
) -> dict[str, float]:
    """Derive initial style vector from kibbe family scores.

    Uses the already-computed ``IdentityEngine.family_scores`` as a
    natural basis: each kibbe family maps to a dominant style tag.
    The result is normalised so weights sum to 1.0.

    Downstream services (``ScoringService``, ``TodayService``,
    ``PersonalizationService``) consume the same tag→weight dict,
    so this slots in without API changes.

    Tag names match the 5 kibbe families which are already the keys
    used in ``garment_line_rules.yaml`` and ``recommendation_guides.yaml``.
    """
    if not family_scores:
        return _stub_style_vector()

    total = sum(family_scores.values()) or 1.0
    return {
        family: round(score / total, 3)
        for family, score in sorted(
            family_scores.items(), key=lambda kv: kv[1], reverse=True
        )
    }


# ---------------------------------------------------------------- service


#: Seam signature for feature extraction. Takes the acting user id and
#: the canonical-order list of persisted photo references, returns the
#: 20-key feature vector. The default implementation is
#: :func:`app.services.feature_extractor.default_feature_extractor`.
FeatureExtractor = Callable[
    [uuid.UUID, list[PhotoReference]], dict[str, float]
]
UserPhotoRepoFactory = Callable[["Session"], "UserPhotoRepository"]
NowFactory = Callable[[], datetime]


class UserAnalysisService:
    """Persist user reference photos and compute identity/color analysis.

    Collaborators
    -------------
    * ``storage`` — a :class:`StorageService` that writes to the configured
      backend. Defaults to a freshly constructed instance.
    * ``photo_repo_factory`` — builds a :class:`UserPhotoRepository` from a
      ``Session``. Defaults to the real repository, lazily imported so
      tests can skip SQLAlchemy entirely.
    * ``feature_extractor`` — returns the user feature vector. Defaults to
      :func:`_stub_features`. This is the *one* seam the upcoming CV step
      will hook into.
    * ``identity_engine`` / ``color_engine`` — already testable, constructed
      once per request if not supplied.
    * ``now`` — ``datetime`` factory so ``analyzed_at`` is deterministic in
      tests.
    """

    def __init__(
        self,
        db: "Session | None" = None,
        *,
        storage: StorageService | None = None,
        photo_repo_factory: UserPhotoRepoFactory | None = None,
        feature_extractor: FeatureExtractor | None = None,
        identity_engine: IdentityEngine | None = None,
        color_engine: ColorEngine | None = None,
        now: NowFactory | None = None,
    ) -> None:
        self.db = db
        self._storage = storage
        self._photo_repo_factory = photo_repo_factory
        self._feature_extractor = feature_extractor
        self._identity_engine = identity_engine
        self._color_engine = color_engine
        self._now = now

    # ----- collaborators (lazy defaults) ---------------------------------

    def _get_storage(self) -> StorageService:
        if self._storage is not None:
            return self._storage
        return StorageService()

    def _get_photo_repo(self) -> "UserPhotoRepository":
        if self._photo_repo_factory is not None:
            return self._photo_repo_factory(self.db)  # type: ignore[arg-type]
        from app.repositories.user_photo_repository import (  # lazy
            UserPhotoRepository,
        )

        return UserPhotoRepository(self.db)  # type: ignore[arg-type]

    def _get_features(
        self,
        user_id: uuid.UUID,
        photos: list[PhotoReference],
    ) -> dict[str, float]:
        """Run the feature extractor seam with an emergency fallback.

        If the extractor raises (buggy heuristic, drifted schema, etc.)
        we fall back to :func:`_stub_features` so the request still
        produces a valid response. The placeholder extractor is *not*
        on the hot path for correctness — it must not 500 the route.
        """
        extractor = self._feature_extractor or default_feature_extractor
        try:
            result = extractor(user_id, photos)
            fp = feature_vector_fingerprint(result)
            logger.info(
                "user_analysis: extractor OK user=%s fp=%s",
                user_id, fp,
            )
            return result
        except Exception as exc:
            logger.warning(
                "user_analysis: extractor EXCEPTION user=%s error=%s: %s — using _stub_features()",
                user_id, type(exc).__name__, exc,
            )
            return _stub_features()

    def _get_identity_engine(self) -> IdentityEngine:
        if self._identity_engine is not None:
            return self._identity_engine
        return IdentityEngine()

    def _get_color_engine(self) -> ColorEngine:
        if self._color_engine is not None:
            return self._color_engine
        return ColorEngine()

    def _get_color_axes(
        self,
        user_id: uuid.UUID,
        photos: list[PhotoReference],
        features: dict[str, float],
    ) -> dict[str, str]:
        """Resolve colour axes for ColorEngine.

        Primary path: real photo-based extraction via
        ``color_feature_extractor()`` — reads actual pixel data from
        the user's portrait / front photos.

        Fallback: ``_derive_color_axes(features)`` — a heuristic bridge
        that derives colour from geometric body features.  Not real
        colour detection.  Used when the photo-based pipeline fails
        (no face, bad image, missing dependency, etc.).
        """
        try:
            from app.services.color_feature_extractor import (
                ColorExtractionFailedError,
                color_feature_extractor,
            )

            axes = color_feature_extractor(user_id, photos)
            logger.info(
                "user_analysis: color_axes source=photo_extractor "
                "user=%s axes=%s",
                user_id, axes,
            )
            return axes

        except Exception as exc:
            logger.warning(
                "user_analysis: color_axes photo extractor failed, "
                "falling back to heuristic bridge user=%s error=%r",
                user_id, exc,
            )
            axes = _derive_color_axes(features)
            logger.info(
                "user_analysis: color_axes source=heuristic_fallback "
                "user=%s axes=%s",
                user_id, axes,
            )
            return axes

    def _get_now(self) -> datetime:
        if self._now is not None:
            return self._now()
        return datetime.now(timezone.utc)

    def _persist_style_profile(
        self,
        user_id: uuid.UUID,
        *,
        persona_id: uuid.UUID,
        kibbe_type: str | None,
        kibbe_confidence: float | None,
        color_profile: dict | None,
        style_vector: dict | None,
    ) -> None:
        """Upsert a ``StyleProfile`` row so downstream features can read it.

        Uses a Postgres ``INSERT … ON CONFLICT DO UPDATE`` so a second
        analysis overwrites the previous one atomically. The conflict
        target is ``persona_id`` (the new PK after migration 0010) — one
        style profile per persona. ``user_id`` is still stored so
        account-wide queries keep working. If there is no DB session
        (unit-test mode with ``db=None``), we silently skip.
        """
        if self.db is None:
            return
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.models.style_profile import StyleProfile  # lazy

        stmt = (
            pg_insert(StyleProfile)
            .values(
                persona_id=persona_id,
                user_id=user_id,
                kibbe_type=kibbe_type,
                kibbe_confidence=kibbe_confidence,
                color_profile_json=color_profile or {},
                style_vector_json=style_vector or {},
            )
            .on_conflict_do_update(
                index_elements=["persona_id"],
                set_={
                    "kibbe_type": kibbe_type,
                    "kibbe_confidence": kibbe_confidence,
                    "color_profile_json": color_profile or {},
                    "style_vector_json": style_vector or {},
                },
            )
        )
        self.db.execute(stmt)
        self.db.commit()

    # ----- pure helpers --------------------------------------------------

    @staticmethod
    def _validate_uploads(
        uploads: list[AnalysisPhotoUpload],
    ) -> dict[str, AnalysisPhotoUpload]:
        """Strict validation of the uploaded photo set.

        Rules:

        * exactly 3 uploads
        * unique slots (no duplicates)
        * slot set == ``{"front", "side", "portrait"}`` exactly

        Returns a dict keyed by slot so the caller can iterate in canonical
        order via :data:`SLOT_ORDER`.
        """
        if len(uploads) != 3:
            raise UserAnalysisValidationError(
                f"expected exactly 3 photo uploads, got {len(uploads)}"
            )
        by_slot: dict[str, AnalysisPhotoUpload] = {}
        for upload in uploads:
            slot = (upload.slot or "").strip().lower()
            if slot in by_slot:
                raise UserAnalysisValidationError(
                    f"duplicate slot {slot!r}"
                )
            by_slot[slot] = upload
        slot_set = frozenset(by_slot.keys())
        if slot_set != _ALLOWED_SLOTS:
            missing = sorted(_ALLOWED_SLOTS - slot_set)
            extra = sorted(slot_set - _ALLOWED_SLOTS)
            parts: list[str] = []
            if missing:
                parts.append(f"missing={missing}")
            if extra:
                parts.append(f"unexpected={extra}")
            raise UserAnalysisValidationError(
                "photo slots must be exactly {front, side, portrait}"
                + (f" ({', '.join(parts)})" if parts else "")
            )
        return by_slot

    # ----- public API ----------------------------------------------------

    def analyze(
        self,
        *,
        user_id: uuid.UUID,
        uploads: list[AnalysisPhotoUpload],
        persona_id: uuid.UUID | None = None,
    ) -> dict:
        """Run the 3-photo analysis for ``user_id``/``persona_id``.

        ``persona_id`` is optional for backward-compat callers that don't
        yet pass it through (most existing tests): when omitted and a DB
        session is available, we resolve the user's primary persona here
        so every downstream write (storage key, photo row, StyleProfile)
        sees the same value. Unit-test paths without a DB ``db=None``
        continue to pass ``None`` all the way through — the stubs don't
        care.
        """
        by_slot = self._validate_uploads(uploads)

        effective_persona_id = persona_id
        if effective_persona_id is None and self.db is not None:
            from app.repositories.persona_repository import PersonaRepository

            effective_persona_id = PersonaRepository(self.db).ensure_primary(user_id).id

        storage = self._get_storage()
        repo = self._get_photo_repo()

        # Upload + persist each slot in canonical order. We deliberately do
        # NOT try to roll back earlier slots on a later failure — see the
        # module docstring for the rationale.
        persisted: list[dict] = []
        for slot in SLOT_ORDER:
            upload = by_slot[slot]
            photo_id = uuid.uuid4()

            try:
                asset = storage.upload_user_photo(
                    user_id,
                    photo_id,
                    slot,
                    data=upload.data,
                    content_type=upload.content_type or "",
                    filename=upload.filename,
                    persona_id=effective_persona_id,
                )
            except (StorageError, StorageValidationError) as exc:
                raise UserAnalysisStorageError(
                    f"failed to store {slot} photo: {exc}"
                ) from exc

            try:
                row = repo.create(
                    user_id=user_id,
                    persona_id=effective_persona_id,
                    slot=slot,
                    image_key=asset.key,
                    image_url=asset.url,
                    photo_id=photo_id,
                )
            except Exception as exc:
                raise UserAnalysisPersistenceError(
                    f"failed to persist {slot} photo row: {exc}"
                ) from exc

            persisted.append(
                {
                    "id": str(getattr(row, "id", photo_id)),
                    "slot": slot,
                    "image_key": asset.key,
                    "image_url": asset.url,
                }
            )

        # Build the canonical-order reference list that the extractor
        # seam receives. Single source of truth: we iterate persisted
        # entries (which were appended in SLOT_ORDER above), so the
        # ordering cannot drift from the response ``photos`` list.
        photo_refs: list[PhotoReference] = [
            PhotoReference(
                slot=entry["slot"],
                image_key=entry["image_key"],
                image_url=entry["image_url"],
                photo_id=uuid.UUID(entry["id"]),
            )
            for entry in persisted
        ]

        features = self._get_features(user_id, photo_refs)
        fp = feature_vector_fingerprint(features)

        identity = self._get_identity_engine().analyze(features)
        # Photo-based colour extraction with heuristic fallback.
        color_axes = self._get_color_axes(user_id, photo_refs, features)
        color = self._get_color_engine().analyze(color_axes)
        style_vector = _derive_style_vector(
            identity.get("family_scores", {}),
        )

        logger.info(
            "user_analysis: RESULT user=%s features_fp=%s "
            "kibbe=%s confidence=%s color_axes=%s color_season=%s style_vector=%s",
            user_id,
            fp,
            identity.get("main_type"),
            identity.get("confidence"),
            color_axes,
            color.get("season_top_1"),
            style_vector,
        )

        # Persist the computed analysis into ``style_profiles`` so
        # downstream features (Recommendations, Today, Insights) can
        # read it back without relying on the transient HTTP response.
        # StyleProfile upsert is keyed by persona_id after migration 0010.
        # We only persist when a persona is resolved — without a DB session
        # (`db=None` unit tests) this whole method short-circuits inside
        # _persist_style_profile anyway.
        if effective_persona_id is not None:
            self._persist_style_profile(
                user_id,
                persona_id=effective_persona_id,
                kibbe_type=identity.get("main_type"),
                kibbe_confidence=identity.get("confidence"),
                color_profile=color,
                style_vector=style_vector,
            )
        logger.info(
            "user_analysis: style_profile persisted user=%s kibbe=%s",
            user_id,
            identity.get("main_type"),
        )

        return {
            "kibbe": identity,
            "color": color,
            "style_vector": style_vector,
            "analyzed_at": self._get_now().isoformat(),
            "photos": persisted,
        }


__all__ = [
    "SLOT_ORDER",
    "AnalysisPhotoUpload",
    "UserAnalysisError",
    "UserAnalysisPersistenceError",
    "UserAnalysisService",
    "UserAnalysisStorageError",
    "UserAnalysisValidationError",
]
