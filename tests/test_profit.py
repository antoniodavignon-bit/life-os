from datetime import datetime
from decimal import Decimal

import pytest

from life_os.profit import ProfitEntry, ProfitTracker, to_amount


def test_add_profit_increases_total():
    tracker = ProfitTracker()

    tracker.add_profit("250.00", "Product sale")
    tracker.add_profit("100.00", "Consulting session")

    assert tracker.total == Decimal("350.00")
    assert len(tracker.entries) == 2


def test_total_is_exact_where_float_would_drift():
    """The reason ADR-004 exists: 0.1 + 0.2 != 0.3 in binary floating
    point, and an income log that drifts is not an income log."""
    tracker = ProfitTracker()
    for _ in range(10):
        tracker.add_profit("0.10", "dime")

    assert tracker.total == Decimal("1.00")
    assert str(tracker.total) == "1.00"


def test_amounts_are_quantized_to_cents():
    tracker = ProfitTracker()

    entry = tracker.add_profit("10.005", "rounds up")

    assert entry.amount == Decimal("10.01")


def test_add_profit_rejects_non_positive_amount():
    tracker = ProfitTracker()

    with pytest.raises(ValueError):
        tracker.add_profit(0)

    with pytest.raises(ValueError):
        tracker.add_profit(-25)


def test_add_profit_rejects_an_amount_that_rounds_away_to_nothing():
    tracker = ProfitTracker()

    with pytest.raises(ValueError, match="must be positive"):
        tracker.add_profit("0.001")


def test_add_profit_rejects_non_numeric_and_non_finite_amounts():
    tracker = ProfitTracker()

    with pytest.raises(ValueError, match="not a valid number"):
        tracker.add_profit("abc")

    with pytest.raises(ValueError, match="must be finite"):
        tracker.add_profit(Decimal("NaN"))

    with pytest.raises(ValueError, match="must be a number"):
        tracker.add_profit(True)


def test_float_amounts_are_routed_through_str_not_binary():
    """Decimal(0.1) is 0.1000000000000000055...; Decimal(str(0.1)) is 0.1."""
    assert to_amount(0.1) == Decimal("0.10")


def test_entries_between_filters_by_timestamp():
    tracker = ProfitTracker()
    tracker.add_profit(50, "early", now=datetime(2026, 8, 1, 9, 0))
    tracker.add_profit(75, "in range", now=datetime(2026, 8, 15, 9, 0))
    tracker.add_profit(20, "late", now=datetime(2026, 9, 1, 9, 0))

    week = tracker.entries_between(datetime(2026, 8, 10), datetime(2026, 8, 20))

    assert [e.note for e in week] == ["in range"]
    assert tracker.total_between(datetime(2026, 8, 10), datetime(2026, 8, 20)) == Decimal("75.00")


def test_total_between_is_zero_for_an_empty_window():
    tracker = ProfitTracker()
    tracker.add_profit(50, "sale", now=datetime(2026, 8, 1, 9, 0))

    assert tracker.total_between(datetime(2027, 1, 1), datetime(2027, 2, 1)) == Decimal("0.00")


def test_reset_clears_entries_and_total():
    tracker = ProfitTracker()
    tracker.add_profit(100, "sale")

    tracker.reset()

    assert tracker.entries == ()
    assert tracker.total == Decimal("0.00")


def test_entries_cannot_be_mutated_through_the_public_view():
    """The old public list let callers append past every validation."""
    tracker = ProfitTracker()
    tracker.add_profit(100, "sale")

    with pytest.raises(AttributeError):
        tracker.entries.append("not even an entry")

    assert len(tracker.entries) == 1


def test_tracker_rejects_non_entries_at_construction():
    with pytest.raises(ValueError, match="Expected ProfitEntry"):
        ProfitTracker(entries=[{"amount": "100"}])


def test_entry_validates_its_own_amount():
    """Validation on the type, not the method, so the state-file
    deserializer is held to the same rule as the CLI."""
    with pytest.raises(ValueError, match="must be positive"):
        ProfitEntry(amount="-50", note="", timestamp=datetime(2026, 9, 1, 12, 0))


def test_entry_requires_a_real_timestamp():
    with pytest.raises(ValueError, match="must be a datetime"):
        ProfitEntry(amount="50", note="", timestamp="2026-09-01")
