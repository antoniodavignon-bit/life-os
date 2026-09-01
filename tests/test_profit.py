from datetime import datetime

import pytest

from life_os.profit import ProfitTracker


def test_add_profit_increases_total():
    tracker = ProfitTracker()

    tracker.add_profit(250.00, "Product sale")
    tracker.add_profit(100.00, "Consulting session")

    assert tracker.total == pytest.approx(350.00)
    assert len(tracker.entries) == 2


def test_add_profit_rejects_non_positive_amount():
    tracker = ProfitTracker()

    with pytest.raises(ValueError):
        tracker.add_profit(0)

    with pytest.raises(ValueError):
        tracker.add_profit(-25)


def test_entries_between_filters_by_timestamp():
    tracker = ProfitTracker()
    tracker.add_profit(50, "early", now=datetime(2026, 8, 1, 9, 0))
    tracker.add_profit(75, "in range", now=datetime(2026, 8, 15, 9, 0))
    tracker.add_profit(20, "late", now=datetime(2026, 9, 1, 9, 0))

    week = tracker.entries_between(datetime(2026, 8, 10), datetime(2026, 8, 20))

    assert [e.note for e in week] == ["in range"]


def test_reset_clears_entries_and_total():
    tracker = ProfitTracker()
    tracker.add_profit(100, "sale")

    tracker.reset()

    assert tracker.entries == []
    assert tracker.total == 0
