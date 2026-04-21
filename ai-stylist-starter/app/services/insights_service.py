"""Weekly Insights — deterministic 7-day behavior summary.

Aggregates the last 7 days of ``UserEvent`` rows for a given user and projects
them into four explainable views:

    1. behavior summary (counters per FeedbackIn event type)
    2. preference patterns (tag frequency on positive events)
    3. underused items + underused categories (wardrobe × events diff)
    4. style shift (week tag distribution vs stored personalization vectors)

No ML, no cosine tricks, no new scoring. Every number in the response is
either a raw count or a normalized frequency delta; every human-readable
line is a 1:1 projection of a number.
"""

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, Iterable

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

# ---------------------------------------------------------------- constants

POSITIVE_EVENT_TYPES: frozenset[str] = frozenset(
    {"outfit_liked", "item_liked", "outfit_saved", "outfit_worn", "item_worn"}
)
NEGATIVE_EVENT_TYPES: frozenset[str] = frozenset(
    {"outfit_disliked", "item_disliked", "item_ignored"}
)

#: Tag must appear at least this many times in positive events to surface as a
#: human-readable pattern line.
PATTERN_THRESHOLD: int = 2

#: Frequency deltas below this absolute value are suppressed from the
#: human-readable style_shift lines.
SHIFT_NOISE_FLOOR: float = 0.05

#: Hard cap on the underused_items list.
MAX_UNDERUSED_ITEMS: int = 20

#: Maximum human-readable pattern lines emitted.
MAX_PATTERN_LINES: int = 5


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize(counter: Counter) -> dict[str, float]:
    total = sum(counter.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in counter.items()}


def _normalize_mapping(mapping: dict | None) -> dict[str, float]:
    if not mapping:
        return {}
    total = sum(float(v) for v in mapping.values())
    if total <= 0:
        return {}
    return {k: float(v) / total for k, v in mapping.items()}


class InsightsService:
    def __init__(
        self,
        db: "Session | None" = None,
        *,
        event_loader: Callable[[uuid.UUID], list[Any]] | None = None,
        wardrobe_loader: Callable[[uuid.UUID], list[dict]] | None = None,
        personalization_loader: Callable[[uuid.UUID], Any] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.db = db
        self._event_loader = event_loader
        self._wardrobe_loader = wardrobe_loader
        self._personalization_loader = personalization_loader
        self._now = now or (lambda: datetime.now(timezone.utc))

    # ----------------------------------------------------------- data loading

    def _load_events(self, user_id: uuid.UUID) -> list[Any]:
        if self._event_loader is not None:
            return self._event_loader(user_id)
        if self.db is None:
            return []
        from app.repositories.event_repository import EventRepository

        return EventRepository(self.db).list_by_user(user_id)

    def _load_wardrobe(self, user_id: uuid.UUID) -> list[dict]:
        if self._wardrobe_loader is not None:
            return self._wardrobe_loader(user_id)
        if self.db is None:
            return []
        from app.repositories.wardrobe_repository import WardrobeRepository

        raw = WardrobeRepository(self.db).list_by_user(user_id)
        return [_to_flat_item(i) for i in raw]

    def _load_personalization(self, user_id: uuid.UUID):
        if self._personalization_loader is not None:
            return self._personalization_loader(user_id)
        if self.db is None:
            return None
        from app.repositories.personalization_repository import (
            PersonalizationRepository,
        )

        return PersonalizationRepository(self.db).get_or_create(user_id)

    # ----------------------------------------------------------------- public

    def weekly(self, user_id: uuid.UUID) -> dict:
        now = _to_utc(self._now())
        window_start = now - timedelta(days=7)

        events = self._load_events(user_id)
        week_events = [e for e in events if self._in_window(e, window_start, now)]

        wardrobe = self._load_wardrobe(user_id)
        personalization = self._load_personalization(user_id)

        notes: list[str] = []

        behavior = self._behavior_summary(week_events)
        patterns = self._preference_patterns(week_events)
        underused_items, underused_categories = self._underused(
            wardrobe, week_events, notes
        )
        style_shift = self._style_shift(patterns["tag_counts"], personalization, notes)

        if behavior["total_events"] == 0:
            notes.append("no events in the last 7 days")

        return {
            "window": {
                "start": window_start.isoformat(),
                "end": now.isoformat(),
                "days": 7,
            },
            "behavior": behavior,
            "preference_patterns": patterns,
            "underused_items": underused_items,
            "underused_categories": underused_categories,
            "style_shift": style_shift,
            "notes": notes,
        }

    # ---------------------------------------------------------------- windows

    @staticmethod
    def _in_window(event, start: datetime, end: datetime) -> bool:
        raw = getattr(event, "created_at", None)
        if raw is None:
            return False
        if isinstance(raw, str):
            try:
                raw = datetime.fromisoformat(raw)
            except ValueError:
                return False
        dt = _to_utc(raw)
        return start <= dt <= end

    # ---------------------------------------------------------------- section

    @staticmethod
    def _behavior_summary(events: Iterable) -> dict[str, int]:
        counter: Counter = Counter()
        total = 0
        for e in events:
            et = getattr(e, "event_type", None)
            if et is None:
                continue
            counter[et] += 1
            total += 1
        return {
            "total_events": total,
            "outfits_liked":    counter.get("outfit_liked", 0),
            "outfits_disliked": counter.get("outfit_disliked", 0),
            "outfits_saved":    counter.get("outfit_saved", 0),
            "outfits_worn":     counter.get("outfit_worn", 0),
            "items_liked":      counter.get("item_liked", 0),
            "items_disliked":   counter.get("item_disliked", 0),
            "items_worn":       counter.get("item_worn", 0),
            "items_ignored":    counter.get("item_ignored", 0),
            "tryons_opened":    counter.get("tryon_opened", 0),
        }

    # ---------------------------------------------------------------- section

    @staticmethod
    def _iter_payload_tags(events: Iterable, event_types: frozenset[str], key: str):
        for e in events:
            if getattr(e, "event_type", None) not in event_types:
                continue
            payload = getattr(e, "payload_json", None) or {}
            tags = payload.get(key) or []
            for tag in tags:
                if isinstance(tag, str) and tag:
                    yield tag

    def _preference_patterns(self, events: list) -> dict:
        style_counts: Counter = Counter(
            self._iter_payload_tags(events, POSITIVE_EVENT_TYPES, "style_tags")
        )
        line_counts: Counter = Counter(
            self._iter_payload_tags(events, POSITIVE_EVENT_TYPES, "line_tags")
        )
        color_counts: Counter = Counter(
            self._iter_payload_tags(events, POSITIVE_EVENT_TYPES, "color_tags")
        )
        avoidance_counts: Counter = Counter(
            self._iter_payload_tags(events, NEGATIVE_EVENT_TYPES, "negative_tags")
        )
        # Fall back: negative events without explicit negative_tags contribute
        # their style/line/color tags to the avoidance counter so "I disliked
        # outfits tagged classic" still surfaces somewhere.
        for axis_key in ("style_tags", "line_tags", "color_tags"):
            for tag in self._iter_payload_tags(
                events, NEGATIVE_EVENT_TYPES, axis_key
            ):
                avoidance_counts[tag] += 1

        patterns: list[str] = []
        candidates: list[tuple[int, str, str]] = []
        for tag, count in style_counts.items():
            if count >= PATTERN_THRESHOLD:
                candidates.append((count, tag, f"You leaned toward {tag} looks"))
        for tag, count in line_counts.items():
            if count >= PATTERN_THRESHOLD:
                candidates.append((count, tag, f"You favored {tag} lines"))
        for tag, count in color_counts.items():
            if count >= PATTERN_THRESHOLD:
                candidates.append((count, tag, f"You preferred {tag} colors"))
        for tag, count in avoidance_counts.items():
            if count >= PATTERN_THRESHOLD:
                candidates.append((count, tag, f"You consistently avoided {tag}"))

        # Deterministic: count desc, then tag alpha, then line alpha.
        candidates.sort(key=lambda t: (-t[0], t[1], t[2]))
        for _, _, line in candidates[:MAX_PATTERN_LINES]:
            patterns.append(line)

        return {
            "patterns": patterns,
            "tag_counts": {
                "style":     dict(sorted(style_counts.items())),
                "line":      dict(sorted(line_counts.items())),
                "color":     dict(sorted(color_counts.items())),
                "avoidance": dict(sorted(avoidance_counts.items())),
            },
        }

    # ---------------------------------------------------------------- section

    def _underused(
        self,
        wardrobe: list[dict],
        events: list,
        notes: list[str],
    ) -> tuple[list[dict], list[str]]:
        if not wardrobe:
            notes.append("wardrobe is empty — skipping underused items")
            return [], []

        usage: dict[str, dict] = {}

        def _touch(item_id: str, event_type: str) -> None:
            bucket = usage.setdefault(
                item_id,
                {"positive": 0, "negative": 0, "last_event_type": None},
            )
            if event_type in POSITIVE_EVENT_TYPES:
                bucket["positive"] += 1
            elif event_type in NEGATIVE_EVENT_TYPES:
                bucket["negative"] += 1
            bucket["last_event_type"] = event_type

        for e in events:
            et = getattr(e, "event_type", None)
            if et is None:
                continue
            payload = getattr(e, "payload_json", None) or {}
            item_id = payload.get("item_id")
            if item_id:
                _touch(str(item_id), et)
            for iid in payload.get("item_ids") or []:
                _touch(str(iid), et)

        underused: list[dict] = []
        categories_with_positive: set[str] = set()
        owned_categories: set[str] = set()

        for item in wardrobe:
            cat = item.get("category") or "unknown"
            owned_categories.add(cat)
            item_id = str(item.get("id"))
            bucket = usage.get(item_id)
            if bucket is None:
                underused.append(
                    {
                        "id": item_id,
                        "category": cat,
                        "reason": "not interacted with this week",
                    }
                )
                continue
            if bucket["positive"] > 0:
                categories_with_positive.add(cat)
                continue
            # No positive touches → classify by the negative signal.
            if bucket["last_event_type"] == "item_ignored":
                reason = f"ignored {bucket['negative']} time(s) this week"
            elif bucket["negative"] > 0:
                reason = f"disliked {bucket['negative']} time(s) this week"
            else:
                reason = "not interacted with this week"
            underused.append(
                {"id": item_id, "category": cat, "reason": reason}
            )

        underused.sort(key=lambda u: (u["category"], u["id"]))
        underused = underused[:MAX_UNDERUSED_ITEMS]

        underused_categories = sorted(owned_categories - categories_with_positive)

        return underused, underused_categories

    # ---------------------------------------------------------------- section

    def _style_shift(
        self,
        tag_counts: dict[str, dict[str, int]],
        personalization,
        notes: list[str],
    ) -> dict:
        baselines = {
            "style": _normalize_mapping(
                getattr(personalization, "style_vector_json", None) if personalization else None
            ),
            "line": _normalize_mapping(
                getattr(personalization, "line_vector_json", None) if personalization else None
            ),
            "color": _normalize_mapping(
                getattr(personalization, "color_vector_json", None) if personalization else None
            ),
        }
        has_baseline = any(baselines.values())
        if not has_baseline:
            notes.append(
                "no personalization baseline yet — shift computed against zero"
            )

        result: dict[str, Any] = {"style": [], "line": [], "color": [], "lines": []}
        lines: list[tuple[float, str]] = []

        for axis in ("style", "line", "color"):
            week = _normalize(Counter(tag_counts.get(axis, {})))
            baseline = baselines[axis]
            all_tags = sorted(set(week) | set(baseline))
            deltas: list[dict] = []
            for tag in all_tags:
                delta = week.get(tag, 0.0) - baseline.get(tag, 0.0)
                deltas.append({"tag": tag, "delta": round(delta, 3)})
            # Keep up to 3 most positive and 3 most negative deltas for this
            # axis — deterministic tag-alpha tiebreak.
            deltas.sort(key=lambda d: (-d["delta"], d["tag"]))
            top_positive = [d for d in deltas if d["delta"] > 0][:3]
            deltas.sort(key=lambda d: (d["delta"], d["tag"]))
            top_negative = [d for d in deltas if d["delta"] < 0][:3]
            result[axis] = top_positive + top_negative

            for d in top_positive:
                if d["delta"] >= SHIFT_NOISE_FLOOR:
                    lines.append(
                        (
                            -d["delta"],
                            f"You leaned more into {d['tag']} {axis} this week "
                            f"(+{d['delta']:.2f})",
                        )
                    )
            for d in top_negative:
                if -d["delta"] >= SHIFT_NOISE_FLOOR:
                    lines.append(
                        (
                            d["delta"],
                            f"You pulled back from {d['tag']} {axis} this week "
                            f"({d['delta']:.2f})",
                        )
                    )

        lines.sort(key=lambda pair: pair[0])  # biggest absolute shift first
        result["lines"] = [line for _, line in lines]
        return result


# ------------------------------------------------------------ orm → flat dict

def _to_flat_item(item) -> dict:
    if hasattr(item, "attributes_json"):
        attrs = dict(item.attributes_json or {})
        # Spread attrs into root first so callers that read e.g. ``item["primary_color"]``
        # keep working. Explicit keys (``id``, ``category``, ``attributes``) go *after*
        # the spread so they take precedence — otherwise attrs with the same key (e.g.
        # the envelope-shaped ``category: {value, source, ...}`` produced by the upload
        # pipeline) would clobber the raw string ``item.category`` and break downstream
        # code that does ``set.add(item["category"])``.
        return {
            **attrs,
            "id": str(item.id),
            "category": item.category,
            "name": attrs.get("name"),
            "attributes": attrs,
        }
    if isinstance(item, dict):
        return item
    return {}
