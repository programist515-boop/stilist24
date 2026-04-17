"""Tests for redundancy_service (Sprint 2)."""

from __future__ import annotations

import pytest

from app.services.analytics.redundancy_service import cluster, redundancy_summary


def _item(id: str, category: str, color: str | None = None, occasion: str | None = None) -> dict:
    attrs: dict = {}
    if color is not None:
        attrs["primary_color"] = color
    if occasion is not None:
        attrs["occasion"] = occasion
    return {"id": id, "category": category, "attributes": attrs}


# ---------------------------------------------------------------------------
# cluster — duplicate
# ---------------------------------------------------------------------------

class TestDuplicateCluster:
    def test_two_identical_items_flagged(self):
        items = [
            _item("a", "tops", "white", "casual"),
            _item("b", "tops", "white", "casual"),
        ]
        clusters = cluster(items)
        dup = [c for c in clusters if c["type"] == "duplicate"]
        assert len(dup) == 1
        assert set(dup[0]["item_ids"]) == {"a", "b"}

    def test_three_identical_items_single_cluster(self):
        items = [_item(str(i), "tops", "navy", "business") for i in range(3)]
        clusters = cluster(items)
        dup = [c for c in clusters if c["type"] == "duplicate"]
        assert len(dup) == 1
        assert len(dup[0]["item_ids"]) == 3

    def test_no_duplicate_when_different_color(self):
        items = [
            _item("a", "tops", "white", "casual"),
            _item("b", "tops", "black", "casual"),
        ]
        dup = [c for c in cluster(items) if c["type"] == "duplicate"]
        assert len(dup) == 0

    def test_no_duplicate_when_category_differs(self):
        items = [
            _item("a", "tops", "white", "casual"),
            _item("b", "bottoms", "white", "casual"),
        ]
        dup = [c for c in cluster(items) if c["type"] == "duplicate"]
        assert len(dup) == 0

    def test_missing_color_not_flagged_as_duplicate(self):
        items = [
            _item("a", "tops", None, "casual"),
            _item("b", "tops", None, "casual"),
        ]
        dup = [c for c in cluster(items) if c["type"] == "duplicate"]
        assert len(dup) == 0


# ---------------------------------------------------------------------------
# cluster — near_duplicate
# ---------------------------------------------------------------------------

class TestNearDuplicateCluster:
    def test_same_cat_color_different_occasion(self):
        items = [
            _item("a", "tops", "blue", "casual"),
            _item("b", "tops", "blue", "business"),
        ]
        clusters = cluster(items)
        nd = [c for c in clusters if c["type"] == "near_duplicate"]
        assert len(nd) == 1
        assert set(nd[0]["item_ids"]) == {"a", "b"}

    def test_exact_duplicates_not_also_near_duplicate(self):
        items = [
            _item("a", "tops", "black", "casual"),
            _item("b", "tops", "black", "casual"),
        ]
        result = cluster(items)
        dup_ids = set()
        for c in result:
            if c["type"] == "duplicate":
                dup_ids.update(c["item_ids"])
        nd = [c for c in result if c["type"] == "near_duplicate"]
        # Items already in a duplicate cluster should not repeat as near-dup
        for nd_c in nd:
            assert not frozenset(nd_c["item_ids"]).issubset(dup_ids)


# ---------------------------------------------------------------------------
# cluster — same_role
# ---------------------------------------------------------------------------

class TestSameRoleCluster:
    def test_four_tops_flagged(self):
        items = [_item(str(i), "tops", f"color{i}") for i in range(4)]
        clusters = cluster(items)
        sr = [c for c in clusters if c["type"] == "same_role"]
        assert len(sr) == 1
        assert len(sr[0]["item_ids"]) == 4

    def test_three_tops_not_flagged(self):
        items = [_item(str(i), "tops", f"color{i}") for i in range(3)]
        sr = [c for c in cluster(items) if c["type"] == "same_role"]
        assert len(sr) == 0

    def test_five_items_same_category(self):
        items = [_item(str(i), "shoes") for i in range(5)]
        sr = [c for c in cluster(items) if c["type"] == "same_role"]
        assert len(sr) == 1


# ---------------------------------------------------------------------------
# redundancy_summary
# ---------------------------------------------------------------------------

class TestRedundancySummary:
    def test_empty_wardrobe_no_redundancy(self):
        result = redundancy_summary([])
        assert result["duplicate_count"] == 0
        assert result["near_duplicate_count"] == 0
        assert result["same_role_count"] == 0
        assert "No significant redundancy" in result["notes"][0]

    def test_counts_match_clusters(self):
        items = [
            _item("a", "tops", "white", "casual"),
            _item("b", "tops", "white", "casual"),
        ]
        result = redundancy_summary(items)
        assert result["duplicate_count"] == 1
        assert len(result["clusters"]) >= 1

    def test_notes_mention_duplicates(self):
        items = [
            _item("a", "bottoms", "black", "formal"),
            _item("b", "bottoms", "black", "formal"),
        ]
        result = redundancy_summary(items)
        assert any("duplicate" in n.lower() for n in result["notes"])

    def test_notes_mention_over_concentration(self):
        items = [_item(str(i), "tops") for i in range(5)]
        result = redundancy_summary(items)
        assert any("concentrated" in n.lower() or "diversif" in n.lower() for n in result["notes"])

    def test_v2_attr_format_resolved(self):
        items = [
            {
                "id": "a",
                "category": "tops",
                "attributes": {
                    "primary_color": {"value": "red", "confidence": 0.9, "source": "cv", "editable": True},
                    "occasion": {"value": "casual", "confidence": 0.9, "source": "cv", "editable": True},
                },
            },
            {
                "id": "b",
                "category": "tops",
                "attributes": {
                    "primary_color": {"value": "red", "confidence": 0.9, "source": "cv", "editable": True},
                    "occasion": {"value": "casual", "confidence": 0.9, "source": "cv", "editable": True},
                },
            },
        ]
        result = redundancy_summary(items)
        assert result["duplicate_count"] == 1
