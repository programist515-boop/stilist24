"""Tests for STEP 13 — structured feature extractor.

The extractor is a pure function of ``(user_id, photos)`` built on top of a
baseline + slot contributions + stable per-user jitter. These tests verify:

1. The output schema matches the 20-key Identity Engine contract exactly.
2. Every value lands in ``[0, 1]`` after clamping.
3. The output is deterministic across calls.
4. Different users / different slot sets produce observably different vectors.
5. Each slot's documented contribution actually moves the right feature.
6. Jitter is stable and uses ``blake2b`` rather than Python's ``hash()``.
"""

from __future__ import annotations

import hashlib
import uuid

from app.services.feature_extractor import (
    BASELINE,
    PhotoReference,
    SCHEMA_KEYS,
    StructuredFeatureExtractor,
    _stable_jitter,
    default_feature_extractor,
)


# ---------------------------------------------------------------- ids + helpers


USER_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _ref(slot: str) -> PhotoReference:
    return PhotoReference(
        slot=slot,
        image_key=f"users/x/photos/{slot}/00.jpg",
        image_url=f"memory://users/x/photos/{slot}/00.jpg",
        photo_id=uuid.uuid4(),
    )


def _three_refs() -> list[PhotoReference]:
    return [_ref("front"), _ref("side"), _ref("portrait")]


def _extract(
    user_id: uuid.UUID, photos: list[PhotoReference]
) -> dict[str, float]:
    return StructuredFeatureExtractor(user_id=user_id, photos=photos).extract()


# ================================================================ tests


# 1. schema: exactly the 20 documented keys, nothing more, nothing less
def test_returns_exact_20_key_schema() -> None:
    features = _extract(USER_A, _three_refs())
    assert frozenset(features.keys()) == SCHEMA_KEYS
    assert len(features) == 20


# 2. every value is a clamped float in [0.0, 1.0]
def test_all_values_in_unit_interval() -> None:
    features = _extract(USER_A, _three_refs())
    for key, value in features.items():
        assert isinstance(value, float), f"{key} is {type(value).__name__}"
        assert 0.0 <= value <= 1.0, f"{key}={value} is outside [0,1]"


# 3. deterministic: same inputs, same outputs
def test_deterministic_same_input_same_output() -> None:
    refs = _three_refs()
    a = _extract(USER_A, refs)
    b = _extract(USER_A, refs)
    assert a == b

    # Also: distinct but equivalent ref lists give the same output (the
    # extractor must not depend on object identity or photo_id).
    c = _extract(USER_A, _three_refs())
    assert a == c


# 4. different users get different vectors (jitter is user-scoped)
def test_different_users_get_different_vectors() -> None:
    refs = _three_refs()
    a = _extract(USER_A, refs)
    b = _extract(USER_B, refs)
    assert a != b
    # but structure is the same
    assert frozenset(a.keys()) == frozenset(b.keys()) == SCHEMA_KEYS


# 5. different slot sets give observably different vectors
def test_different_slot_sets_get_different_vectors() -> None:
    full = _extract(USER_A, _three_refs())
    front_only = _extract(USER_A, [_ref("front")])
    assert full != front_only

    side_only = _extract(USER_A, [_ref("side")])
    portrait_only = _extract(USER_A, [_ref("portrait")])
    assert front_only != side_only != portrait_only


# 6. front slot boosts symmetry above baseline (even after jitter)
def test_front_slot_boosts_symmetry() -> None:
    no_slots = _extract(USER_A, [])
    front = _extract(USER_A, [_ref("front")])
    # front contribution for symmetry is +0.10, jitter is at most 0.05 total
    # so the front vector's symmetry must strictly exceed the empty one.
    assert front["symmetry"] > no_slots["symmetry"]
    # And it must still be >= baseline even with worst-case negative jitter.
    assert front["symmetry"] >= BASELINE["symmetry"] + 0.10 - 0.05 - 1e-9


# 7. side slot boosts vertical_line above baseline
def test_side_slot_boosts_vertical_line() -> None:
    no_slots = _extract(USER_A, [])
    side = _extract(USER_A, [_ref("side")])
    assert side["vertical_line"] > no_slots["vertical_line"]
    assert side["vertical_line"] >= BASELINE["vertical_line"] + 0.10 - 0.05 - 1e-9


# 8. portrait slot boosts facial_sharpness above baseline
def test_portrait_slot_boosts_facial_sharpness() -> None:
    no_slots = _extract(USER_A, [])
    portrait = _extract(USER_A, [_ref("portrait")])
    assert portrait["facial_sharpness"] > no_slots["facial_sharpness"]
    assert (
        portrait["facial_sharpness"]
        >= BASELINE["facial_sharpness"] + 0.08 - 0.05 - 1e-9
    )


# 9. unknown slot is silently ignored (tolerance, per STEP 13 constraint #3)
def test_unknown_slot_is_ignored_gracefully() -> None:
    unknown = _extract(USER_A, [_ref("unknown-slot")])
    empty = _extract(USER_A, [])
    # unknown slot contributes nothing, so the vectors must be identical
    assert unknown == empty


# 10. empty photo list is valid: returns baseline + jitter
def test_empty_photos_returns_baseline_plus_jitter() -> None:
    features = _extract(USER_A, [])
    # Every feature must be within 0.05 of BASELINE (jitter range)
    for key, value in features.items():
        assert abs(value - BASELINE[key]) <= 0.05 + 1e-9, (
            f"{key}={value} drifted too far from BASELINE={BASELINE[key]}"
        )


# 11. jitter is stable across 100 calls with the same arguments
def test_jitter_is_stable_across_calls() -> None:
    values = {_stable_jitter(USER_A, "vertical_line") for _ in range(100)}
    assert len(values) == 1
    (only,) = values
    assert -0.05 <= only <= 0.05


# 12. jitter uses blake2b, NOT python hash() — reproducible across processes
def test_jitter_uses_blake2b_not_python_hash() -> None:
    # Reproduce the formula here. If the extractor ever switches to
    # hash(), this test will still pass locally (within one process) but
    # will drift on any other machine / interpreter restart. The point
    # of the test is to pin the algorithm, so we pin it explicitly.
    key = "vertical_line"
    payload = f"{USER_A}|{key}".encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=2).digest()
    expected_n = int.from_bytes(digest, "big") % 21
    expected = (expected_n - 10) / 200.0

    assert _stable_jitter(USER_A, key) == expected
    # Sanity: the value also matches what StructuredFeatureExtractor
    # applies to that key when no slots are present.
    features = _extract(USER_A, [])
    assert abs(features[key] - (BASELINE[key] + expected)) < 1e-9


# ---------------------------------------------------------------- seam entry point


def test_default_feature_extractor_matches_class() -> None:
    """Module-level ``default_feature_extractor`` must equal the class output."""
    refs = _three_refs()
    via_class = _extract(USER_A, refs)
    via_entry = default_feature_extractor(USER_A, refs)
    assert via_class == via_entry
