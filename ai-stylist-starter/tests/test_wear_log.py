"""Tests for CPW service and WearLogService (Sprint 2)."""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.services.analytics.cpw_service import calculate, calculate_batch, calculate_projected


# ---------------------------------------------------------------------------
# calculate()
# ---------------------------------------------------------------------------

class TestCalculate:
    def test_zero_wears_returns_full_cost(self):
        assert calculate(100.0, 0) == 100.0

    def test_one_wear(self):
        assert calculate(50.0, 1) == 50.0

    def test_ten_wears(self):
        assert calculate(100.0, 10) == 10.0

    def test_rounds_to_two_decimal_places(self):
        assert calculate(10.0, 3) == 3.33

    def test_none_cost_returns_none(self):
        assert calculate(None, 5) is None

    def test_zero_cost_returns_zero(self):
        assert calculate(0.0, 5) == 0.0

    def test_fractional_cost(self):
        assert calculate(14.99, 2) == 7.5  # 14.99/2 = 7.495 → 7.5 (banker's rounding)

    def test_high_wear_reduces_cpw(self):
        cpw = calculate(200.0, 100)
        assert cpw == 2.0


# ---------------------------------------------------------------------------
# calculate_batch()
# ---------------------------------------------------------------------------

class TestCalculateBatch:
    def test_empty_list(self):
        assert calculate_batch([]) == {}

    def test_single_item(self):
        items = [{"id": "a", "cost": 80.0, "wear_count": 4}]
        assert calculate_batch(items) == {"a": 20.0}

    def test_multiple_items(self):
        items = [
            {"id": "a", "cost": 50.0, "wear_count": 5},
            {"id": "b", "cost": None, "wear_count": 3},
            {"id": "c", "cost": 100.0, "wear_count": 0},
        ]
        result = calculate_batch(items)
        assert result["a"] == 10.0
        assert result["b"] is None
        assert result["c"] == 100.0

    def test_missing_wear_count_treated_as_zero(self):
        items = [{"id": "x", "cost": 60.0}]
        result = calculate_batch(items)
        assert result["x"] == 60.0


# ---------------------------------------------------------------------------
# calculate_projected()
# ---------------------------------------------------------------------------

class TestCalculateProjected:
    def test_current_cpw_initial_purchase(self):
        result = calculate_projected(120.0, 0, frequency_per_month=2.0, months=12)
        assert result["current_cpw"] == 120.0

    def test_projected_wears_accumulated(self):
        result = calculate_projected(100.0, 10, frequency_per_month=2.0, months=5)
        assert result["projected_wear_count"] == 20.0
        assert result["projected_cpw"] == 5.0

    def test_projected_cpw_lower_than_current(self):
        result = calculate_projected(200.0, 2, frequency_per_month=3.0, months=12)
        assert result["projected_cpw"] < result["current_cpw"]

    def test_default_months_is_12(self):
        result = calculate_projected(60.0, 0, frequency_per_month=1.0)
        assert result["projected_wear_count"] == 12.0


# ---------------------------------------------------------------------------
# WearLogService — unit-level with mocked DB
# ---------------------------------------------------------------------------

sqlalchemy = pytest.importorskip("sqlalchemy", reason="SQLAlchemy not installed")


class TestWearLogServiceUnit:
    def _make_log_row(self, item_id: uuid.UUID) -> MagicMock:
        row = MagicMock()
        row.id = uuid.uuid4()
        row.item_id = item_id
        row.outfit_id = None
        row.worn_date = date.today()
        row.rating = None
        row.notes = None
        row.created_at = "2026-01-01"
        return row

    def test_log_item_worn_returns_dict(self):
        from app.services.wardrobe.wear_log_service import WearLogService

        db = MagicMock()
        item_id = uuid.uuid4()
        user_id = uuid.uuid4()
        row = self._make_log_row(item_id)

        with (
            patch("app.services.wardrobe.wear_log_service.WearLogRepository") as MockWLR,
            patch("app.services.wardrobe.wear_log_service.WardrobeRepository") as MockWR,
        ):
            MockWLR.return_value.create.return_value = row
            MockWR.return_value.increment_wear_count.return_value = MagicMock()
            svc = WearLogService(db)
            result = svc.log_item_worn(user_id=user_id, item_id=item_id, rating=4)

        assert result["item_id"] == str(item_id)
        assert result["rating"] == 4  # row mock returns MagicMock for .rating — override
        # verify increment was called
        MockWR.return_value.increment_wear_count.assert_called_once_with(item_id)

    def test_get_history_returns_serialized_list(self):
        from app.services.wardrobe.wear_log_service import WearLogService

        db = MagicMock()
        item_id = uuid.uuid4()
        user_id = uuid.uuid4()
        rows = [self._make_log_row(item_id) for _ in range(3)]

        with patch("app.services.wardrobe.wear_log_service.WearLogRepository") as MockWLR:
            MockWLR.return_value.list_by_item.return_value = rows
            svc = WearLogService(db)
            result = svc.get_history(user_id=user_id, item_id=item_id)

        assert isinstance(result, list)
        assert len(result) == 3
        assert all("item_id" in r for r in result)

    def test_log_outfit_worn_missing_outfit_returns_empty(self):
        from app.services.wardrobe.wear_log_service import WearLogService

        db = MagicMock()
        db.get.return_value = None  # outfit not found
        svc = WearLogService(db)
        result = svc.log_outfit_worn(
            user_id=uuid.uuid4(),
            outfit_id=uuid.uuid4(),
        )
        assert result == []
