"""Structured feature extractor (pre-CV).

This module replaces the zero-input ``_stub_features()`` placeholder with a
deterministic, structured extractor that turns *photo references* (not
image bytes) into a valid 20-key feature vector for the Identity Engine.

Design
------

The output is the sum of three contributions, clamped to ``[0, 1]``:

1. **Baseline** — a constant vector in the middle of the range. Every
   feature starts here so the vector is always valid input for the
   downstream engines.
2. **Slot contributions** — each ``PhotoReference.slot`` adds a small,
   slot-specific delta to a handful of features. Front emphasises
   symmetry/width, side emphasises vertical/narrow, portrait emphasises
   facial/bone structure. These are *placeholder heuristics*, not real
   CV output — their only jobs are (a) to make different photo sets
   produce observably different vectors, and (b) to surface exactly
   the seam a real CV pipeline will plug into.
3. **Stable per-user jitter** — a tiny deterministic offset derived
   from ``blake2b(user_id, key)``. Same user → same jitter forever,
   different users → different jitter. ``blake2b`` is used instead of
   Python's built-in ``hash()`` because the latter is randomised
   between processes (``PYTHONHASHSEED``) and would destroy
   determinism in any multi-process setup.

What this module is NOT
-----------------------

* It is **not** ML. No models, no tensors, no image decoding.
* It is **not** CV. It never reads image bytes — only metadata
  (``slot``, ``image_key``, ``photo_id``).
* It is **not** a scoring rule, so slot weights live in code rather
  than YAML — they are an implementation detail of the placeholder
  and will be deleted when the real extractor lands.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import ClassVar


# ---------------------------------------------------------------- schema


#: The exact set of 20 feature keys the Identity Engine's YAML rules
#: operate on. Any extractor that returns a different set is a bug.
SCHEMA_KEYS: frozenset[str] = frozenset(
    {
        "vertical_line",
        "compactness",
        "width",
        "bone_sharpness",
        "bone_bluntness",
        "softness",
        "curve_presence",
        "symmetry",
        "facial_sharpness",
        "facial_roundness",
        "waist_definition",
        "narrowness",
        "relaxed_line",
        "proportion_balance",
        "moderation",
        "line_contrast",
        "small_scale",
        "feature_juxtaposition",
        "controlled_softness_or_sharpness",
        "low_line_contrast",
    }
)


#: Per-key baseline value. Chosen to sit comfortably in the middle of
#: ``[0, 1]`` so slot contributions and jitter never blow the clamp.
BASELINE: dict[str, float] = {
    "vertical_line": 0.45,
    "compactness": 0.45,
    "width": 0.45,
    "bone_sharpness": 0.45,
    "bone_bluntness": 0.45,
    "softness": 0.45,
    "curve_presence": 0.45,
    "symmetry": 0.45,
    "facial_sharpness": 0.45,
    "facial_roundness": 0.45,
    "waist_definition": 0.45,
    "narrowness": 0.45,
    "relaxed_line": 0.45,
    "proportion_balance": 0.45,
    "moderation": 0.45,
    "line_contrast": 0.45,
    "small_scale": 0.45,
    "feature_juxtaposition": 0.45,
    "controlled_softness_or_sharpness": 0.45,
    "low_line_contrast": 0.45,
}

# Guard: baseline must cover the whole schema exactly.
assert frozenset(BASELINE.keys()) == SCHEMA_KEYS, (
    "BASELINE keys drifted from SCHEMA_KEYS"
)


#: Slot-specific additive contributions. Keys that are not listed stay
#: at baseline. Unknown slots are ignored (see extractor docstring).
_SLOT_CONTRIBUTIONS: dict[str, dict[str, float]] = {
    "front": {
        "symmetry": +0.10,
        "width": +0.05,
        "compactness": +0.05,
        "waist_definition": +0.08,
        "proportion_balance": +0.05,
    },
    "side": {
        "vertical_line": +0.10,
        "narrowness": +0.05,
        "relaxed_line": -0.05,
    },
    "portrait": {
        "facial_sharpness": +0.08,
        "facial_roundness": -0.03,
        "bone_sharpness": +0.05,
        "bone_bluntness": -0.03,
        "softness": +0.05,
        "curve_presence": +0.05,
    },
}

# Guard: every slot-contribution key must be a real schema key. Catches
# typos in the constant above at import time rather than at test time.
for _slot, _weights in _SLOT_CONTRIBUTIONS.items():
    _bad = set(_weights) - SCHEMA_KEYS
    assert not _bad, f"_SLOT_CONTRIBUTIONS[{_slot!r}] has unknown keys: {_bad}"
del _slot, _weights, _bad  # keep the module namespace clean


# ---------------------------------------------------------------- dataclass


@dataclass(frozen=True)
class PhotoReference:
    """Lightweight reference to a persisted user photo.

    The extractor only needs the *metadata*, not the bytes, so this
    dataclass is deliberately minimal. A real CV pipeline will use the
    same shape and fetch bytes from storage via ``image_key``.
    """

    slot: str
    image_key: str
    image_url: str
    photo_id: uuid.UUID


# ---------------------------------------------------------------- pure helpers


def _clamp01(value: float) -> float:
    """Clamp a float into the closed interval ``[0.0, 1.0]``."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _stable_jitter(user_id: uuid.UUID | str, key: str) -> float:
    """Deterministic jitter in ``[-0.05, +0.05]`` for a ``(user_id, key)`` pair.

    Uses ``blake2b`` (not Python's built-in ``hash()``) so the value is
    stable across processes, interpreter restarts, and machines.
    """
    payload = f"{user_id}|{key}".encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=2).digest()
    n = int.from_bytes(digest, "big") % 21  # 0..20
    return (n - 10) / 200.0  # -0.05 .. +0.05 in 1/200 steps


# ---------------------------------------------------------------- extractor


class StructuredFeatureExtractor:
    """Deterministic 20-key feature extractor built on photo metadata.

    Construction takes the user id and the list of photo references.
    :meth:`extract` is pure: calling it twice with the same inputs
    always returns the same dict. Calling it with *different* inputs
    (different user, different slot set) returns observably different
    dicts — which is how the downstream engines can tell they are
    wired up correctly.

    Unknown slots are **silently ignored** (they contribute zero). The
    service layer owns the strict "exactly front/side/portrait"
    validation; the extractor itself is deliberately tolerant so unit
    tests can exercise edge cases without tripping a hard assertion.
    """

    SCHEMA_KEYS: ClassVar[frozenset[str]] = SCHEMA_KEYS
    BASELINE: ClassVar[dict[str, float]] = BASELINE

    def __init__(
        self,
        *,
        user_id: uuid.UUID | str,
        photos: list[PhotoReference],
    ) -> None:
        self._user_id = user_id
        self._photos = list(photos)  # defensive copy

    def extract(self) -> dict[str, float]:
        # 1. Start from a fresh copy of the baseline.
        features: dict[str, float] = dict(self.BASELINE)

        # 2. Apply slot contributions. Unknown slots are a no-op by
        #    design — the service already enforces the strict set.
        for photo in self._photos:
            weights = _SLOT_CONTRIBUTIONS.get(photo.slot)
            if not weights:
                continue
            for key, delta in weights.items():
                features[key] += delta

        # 3. Apply stable per-user jitter and clamp each feature.
        for key in features:
            features[key] = _clamp01(
                features[key] + _stable_jitter(self._user_id, key)
            )

        # 4. Contract guard — catches any drift between the schema and
        #    what we actually return. Same assertion the unit tests hit.
        assert frozenset(features.keys()) == self.SCHEMA_KEYS, (
            "StructuredFeatureExtractor output drifted from SCHEMA_KEYS"
        )
        return features


# ---------------------------------------------------------------- default seam


def default_feature_extractor(
    user_id: uuid.UUID,
    photos: list[PhotoReference],
) -> dict[str, float]:
    """Module-level entry point matching the service's seam signature.

    ``UserAnalysisService`` uses this as the default implementation of
    its ``feature_extractor`` seam. Tests can still inject any other
    callable with the same signature to stub the behaviour.
    """
    return StructuredFeatureExtractor(user_id=user_id, photos=photos).extract()


__all__ = [
    "BASELINE",
    "PhotoReference",
    "SCHEMA_KEYS",
    "StructuredFeatureExtractor",
    "default_feature_extractor",
]
