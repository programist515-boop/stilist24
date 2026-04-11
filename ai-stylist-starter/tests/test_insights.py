"""Tests for the Weekly Insights service (STEP 9).

The service is exercised through the injectable-loader seams so the test
environment does not need SQLAlchemy or a real database. Every stub event
mirrors the attribute shape of ``app.models.user_event.UserEvent`` (``event_type``,
``payload_json``, ``created_at``).
"""

import uuid
from datetime import datetime, timedelta, timezone

from app.services.insights_service import (
    MAX_UNDERUSED_ITEMS,
    PATTERN_THRESHOLD,
    SHIFT_NOISE_FLOOR,
    InsightsService,
)

USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
NOW = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------- stub helpers


class _Event:
    def __init__(
        self,
        event_type: str,
        payload: dict | None = None,
        created_at: datetime | None = None,
    ):
        self.event_type = event_type
        self.payload_json = payload or {}
        self.created_at = created_at or NOW


class _Perso:
    def __init__(
        self,
        style: dict | None = None,
        line: dict | None = None,
        color: dict | None = None,
    ):
        self.style_vector_json = style or {}
        self.line_vector_json = line or {}
        self.color_vector_json = color or {}


def _item(item_id: str, category: str) -> dict:
    return {"id": item_id, "category": category}


def _make_service(
    events: list[_Event] | None = None,
    wardrobe: list[dict] | None = None,
    perso: _Perso | None = None,
    now: datetime = NOW,
) -> InsightsService:
    return InsightsService(
        db=None,
        event_loader=lambda _uid: list(events or []),
        wardrobe_loader=lambda _uid: list(wardrobe or []),
        personalization_loader=lambda _uid: perso,
        now=lambda: now,
    )


# ---------------------------------------------------------------- contract


def test_response_shape_and_window():
    svc = _make_service()
    resp = svc.weekly(USER_ID)
    assert set(resp.keys()) == {
        "window",
        "behavior",
        "preference_patterns",
        "underused_items",
        "underused_categories",
        "style_shift",
        "notes",
    }
    window = resp["window"]
    assert window["days"] == 7
    start = datetime.fromisoformat(window["start"])
    end = datetime.fromisoformat(window["end"])
    assert (end - start) == timedelta(days=7)


def test_empty_week_reports_zero_counts_and_note():
    svc = _make_service()
    resp = svc.weekly(USER_ID)
    assert resp["behavior"]["total_events"] == 0
    assert resp["behavior"]["outfits_liked"] == 0
    assert resp["preference_patterns"]["patterns"] == []
    assert resp["underused_items"] == []
    assert resp["underused_categories"] == []
    assert any("no events" in n for n in resp["notes"])


# ----------------------------------------------------------- behavior counts


def test_behavior_summary_counts_event_types():
    events = [
        _Event("outfit_liked"),
        _Event("outfit_liked"),
        _Event("outfit_disliked"),
        _Event("item_liked"),
        _Event("item_worn"),
        _Event("item_ignored"),
        _Event("outfit_saved"),
        _Event("outfit_worn"),
        _Event("tryon_opened"),
        _Event("item_disliked"),
    ]
    svc = _make_service(events=events)
    resp = svc.weekly(USER_ID)
    b = resp["behavior"]
    assert b["total_events"] == 10
    assert b["outfits_liked"] == 2
    assert b["outfits_disliked"] == 1
    assert b["items_liked"] == 1
    assert b["items_worn"] == 1
    assert b["items_ignored"] == 1
    assert b["outfits_saved"] == 1
    assert b["outfits_worn"] == 1
    assert b["tryons_opened"] == 1
    assert b["items_disliked"] == 1


# ------------------------------------------------------------ 7-day window


def test_events_outside_window_are_ignored():
    old = NOW - timedelta(days=10)
    fresh = NOW - timedelta(days=1)
    events = [
        _Event("outfit_liked", created_at=old),
        _Event("outfit_liked", created_at=fresh),
    ]
    svc = _make_service(events=events)
    resp = svc.weekly(USER_ID)
    assert resp["behavior"]["total_events"] == 1
    assert resp["behavior"]["outfits_liked"] == 1


def test_window_boundary_inclusive():
    # Exactly 7 days ago should still be in-window.
    events = [
        _Event("outfit_liked", created_at=NOW - timedelta(days=7)),
        _Event("outfit_liked", created_at=NOW),
    ]
    svc = _make_service(events=events)
    resp = svc.weekly(USER_ID)
    assert resp["behavior"]["total_events"] == 2


# ------------------------------------------------------ preference patterns


def test_preference_patterns_surface_repeating_tags():
    events = [
        _Event("outfit_liked", {"style_tags": ["classic", "minimal"]}),
        _Event("outfit_liked", {"style_tags": ["classic"]}),
        _Event("item_liked", {"color_tags": ["navy", "navy"]}),
        _Event("outfit_worn", {"line_tags": ["sharp", "sharp"]}),
    ]
    svc = _make_service(events=events)
    resp = svc.weekly(USER_ID)
    patterns = resp["preference_patterns"]["patterns"]
    tag_counts = resp["preference_patterns"]["tag_counts"]

    assert tag_counts["style"]["classic"] == 2
    assert tag_counts["color"]["navy"] == 2
    assert tag_counts["line"]["sharp"] == 2
    # minimal only appears once → below PATTERN_THRESHOLD
    assert "minimal" not in tag_counts["style"] or tag_counts["style"]["minimal"] < PATTERN_THRESHOLD

    joined = " | ".join(patterns)
    assert "classic" in joined
    assert "navy" in joined
    assert "sharp" in joined


def test_avoidance_surfaces_from_negative_events():
    events = [
        _Event("outfit_disliked", {"style_tags": ["bold"]}),
        _Event("outfit_disliked", {"style_tags": ["bold"]}),
        _Event("item_disliked", {"negative_tags": ["neon"]}),
        _Event("item_disliked", {"negative_tags": ["neon"]}),
    ]
    svc = _make_service(events=events)
    resp = svc.weekly(USER_ID)
    patterns = resp["preference_patterns"]["patterns"]
    joined = " | ".join(patterns)
    assert "avoided bold" in joined
    assert "avoided neon" in joined


def test_patterns_are_capped_and_deterministic():
    events = []
    # Generate many recurring tags so more than MAX_PATTERN_LINES qualify.
    for tag in ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"):
        events += [
            _Event("outfit_liked", {"style_tags": [tag]}),
            _Event("outfit_liked", {"style_tags": [tag]}),
        ]
    svc = _make_service(events=events)
    first = svc.weekly(USER_ID)["preference_patterns"]["patterns"]
    second = svc.weekly(USER_ID)["preference_patterns"]["patterns"]
    assert first == second
    assert len(first) <= 5  # MAX_PATTERN_LINES


# ------------------------------------------------------------ underused


def test_underused_items_flag_non_interacted_items():
    wardrobe = [
        _item("t1", "top"),
        _item("t2", "top"),
        _item("b1", "bottom"),
        _item("s1", "shoes"),
    ]
    events = [
        _Event("outfit_liked", {"item_ids": ["t1", "b1", "s1"]}),
    ]
    svc = _make_service(events=events, wardrobe=wardrobe)
    resp = svc.weekly(USER_ID)
    underused_ids = {u["id"] for u in resp["underused_items"]}
    assert "t2" in underused_ids
    assert "t1" not in underused_ids
    assert "b1" not in underused_ids


def test_underused_categories_surface_neglected_buckets():
    wardrobe = [
        _item("t1", "top"),
        _item("b1", "bottom"),
        _item("s1", "shoes"),
        _item("a1", "accessory"),
    ]
    events = [
        _Event("outfit_liked", {"item_ids": ["t1", "b1", "s1"]}),
    ]
    svc = _make_service(events=events, wardrobe=wardrobe)
    resp = svc.weekly(USER_ID)
    assert "accessory" in resp["underused_categories"]
    assert "top" not in resp["underused_categories"]
    assert "bottom" not in resp["underused_categories"]


def test_underused_reason_reflects_negative_signal():
    wardrobe = [_item("t1", "top"), _item("t2", "top")]
    events = [
        _Event("item_disliked", {"item_id": "t1"}),
        _Event("item_disliked", {"item_id": "t1"}),
        _Event("item_ignored", {"item_id": "t2"}),
    ]
    svc = _make_service(events=events, wardrobe=wardrobe)
    resp = svc.weekly(USER_ID)
    by_id = {u["id"]: u for u in resp["underused_items"]}
    assert "disliked" in by_id["t1"]["reason"]
    assert "ignored" in by_id["t2"]["reason"]


def test_empty_wardrobe_produces_note_and_empty_underused():
    svc = _make_service(events=[_Event("outfit_liked")], wardrobe=[])
    resp = svc.weekly(USER_ID)
    assert resp["underused_items"] == []
    assert resp["underused_categories"] == []
    assert any("wardrobe is empty" in n for n in resp["notes"])


def test_underused_items_are_capped():
    wardrobe = [_item(f"x{i}", "top") for i in range(MAX_UNDERUSED_ITEMS + 5)]
    svc = _make_service(events=[], wardrobe=wardrobe)
    resp = svc.weekly(USER_ID)
    assert len(resp["underused_items"]) == MAX_UNDERUSED_ITEMS


# ---------------------------------------------------------------- style shift


def test_style_shift_reports_positive_and_negative_deltas():
    events = [
        _Event("outfit_liked", {"style_tags": ["minimal"]}),
        _Event("outfit_liked", {"style_tags": ["minimal"]}),
        _Event("outfit_liked", {"style_tags": ["minimal"]}),
    ]
    perso = _Perso(style={"classic": 1.0})
    svc = _make_service(events=events, perso=perso)
    resp = svc.weekly(USER_ID)
    shift = resp["style_shift"]
    style_deltas = {d["tag"]: d["delta"] for d in shift["style"]}
    assert style_deltas.get("minimal", 0.0) > 0
    assert style_deltas.get("classic", 0.0) < 0

    joined = " | ".join(shift["lines"])
    assert "minimal" in joined
    assert "classic" in joined


def test_style_shift_no_baseline_emits_note():
    events = [
        _Event("outfit_liked", {"style_tags": ["classic"]}),
        _Event("outfit_liked", {"style_tags": ["classic"]}),
    ]
    svc = _make_service(events=events, perso=None)
    resp = svc.weekly(USER_ID)
    assert any("no personalization baseline" in n for n in resp["notes"])


def test_style_shift_noise_floor_suppresses_tiny_deltas():
    # Tag appears once out of 20 positive tags → delta = 0.05 exactly.
    # We build a scenario where deltas are smaller than SHIFT_NOISE_FLOOR.
    events = []
    # 100 equally distributed tags → each freq ~= 0.01.
    for i in range(100):
        events.append(
            _Event("outfit_liked", {"style_tags": [f"tag{i}"]})
        )
    perso = _Perso(style={f"tag{i}": 1.0 for i in range(100)})
    svc = _make_service(events=events, perso=perso)
    resp = svc.weekly(USER_ID)
    for line in resp["style_shift"]["lines"]:
        # Every emitted line must clear the noise floor.
        assert (
            f"+{SHIFT_NOISE_FLOOR:.2f}" in line
            or "+" in line
            or "-" in line
        )
    # With perfectly aligned baselines, no lines should emerge.
    assert resp["style_shift"]["lines"] == []


# ----------------------------------------------------------- determinism


def test_deterministic_across_calls():
    events = [
        _Event("outfit_liked", {"style_tags": ["classic"]}),
        _Event("outfit_liked", {"style_tags": ["classic", "minimal"]}),
        _Event("item_disliked", {"item_id": "x1", "style_tags": ["bold"]}),
        _Event("item_disliked", {"item_id": "x1", "style_tags": ["bold"]}),
    ]
    wardrobe = [_item("x1", "top"), _item("x2", "top"), _item("b1", "bottom")]
    perso = _Perso(style={"classic": 0.6, "bold": 0.4})

    svc_a = _make_service(events=events, wardrobe=wardrobe, perso=perso)
    svc_b = _make_service(events=events, wardrobe=wardrobe, perso=perso)
    assert svc_a.weekly(USER_ID) == svc_b.weekly(USER_ID)
