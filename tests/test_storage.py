import json
from datetime import date, datetime
from decimal import Decimal

import pytest

from life_os.profit import ProfitTracker
from life_os.review import DailyReview
from life_os.storage import (
    SCHEMA_VERSION,
    AppState,
    StorageError,
    load_state,
    save_state,
)
from life_os.tasks import Category, Task


def _state_with(*amounts: str) -> AppState:
    tracker = ProfitTracker()
    for i, amount in enumerate(amounts, start=1):
        tracker.add_profit(amount, f"entry {i}", now=datetime(2026, 9, i, 12, 0))
    return AppState(profit=tracker)


def test_load_returns_empty_state_when_file_does_not_exist(tmp_path):
    state = load_state(tmp_path / "nothing-here.json")

    assert state.profit.entries == ()
    assert state.profit.total == Decimal("0.00")


def test_save_then_load_round_trips_profit_entries(tmp_path):
    path = tmp_path / "state.json"
    save_state(_state_with("250.00", "100.00"), path)

    loaded = load_state(path)

    assert loaded.profit.total == Decimal("350.00")
    assert [e.note for e in loaded.profit.entries] == ["entry 1", "entry 2"]
    assert loaded.profit.entries[0].timestamp == datetime(2026, 9, 1, 12, 0)


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "deeper" / "state.json"

    save_state(_state_with("10.00"), path)

    assert path.exists()
    assert load_state(path).profit.total == pytest.approx(10.0)


def test_save_leaves_no_temp_files_behind(tmp_path):
    path = tmp_path / "state.json"

    save_state(_state_with("10.00"), path)

    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_save_overwrites_previous_state_atomically(tmp_path):
    path = tmp_path / "state.json"
    save_state(_state_with("10.00"), path)

    save_state(_state_with(20.0, 30.0), path)

    loaded = load_state(path)
    assert loaded.profit.total == Decimal("50.00")
    assert len(loaded.profit.entries) == 2


def test_corrupt_json_raises_storage_error_instead_of_losing_data(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(StorageError):
        load_state(path)


def test_unknown_schema_version_is_rejected(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema_version": 999, "profit_entries": []}), encoding="utf-8")

    with pytest.raises(StorageError):
        load_state(path)


def test_malformed_entry_raises_storage_error(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps({"schema_version": 1, "profit_entries": [{"amount": "abc"}]}),
        encoding="utf-8",
    )

    with pytest.raises(StorageError):
        load_state(path)


def _review(day: int = 1, done: int = 2, missed: int = 1) -> DailyReview:
    return DailyReview(
        review_date=date(2026, 9, day),
        completed=[Task(f"done {i}", Category.UNSPECIFIED) for i in range(done)],
        incomplete=[Task(f"missed {i}", Category.UNSPECIFIED) for i in range(missed)],
        top_priority_tomorrow="Ship the landing page",
        note="steady day",
    )


def test_reviews_round_trip_through_the_state_file(tmp_path):
    path = tmp_path / "state.json"
    state = AppState(profit=ProfitTracker(), reviews=[_review(day=1), _review(day=2)])

    save_state(state, path)
    loaded = load_state(path)

    assert len(loaded.reviews) == 2
    assert loaded.reviews[0].review_date == date(2026, 9, 1)
    assert [t.title for t in loaded.reviews[0].incomplete] == ["missed 0"]
    assert loaded.reviews[0].top_priority_tomorrow == "Ship the landing page"
    assert loaded.reviews[0].note == "steady day"


def test_version_1_file_upgrades_cleanly_with_no_reviews(tmp_path):
    """A state file written before reviews existed must still load."""
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profit_entries": [
                    {"amount": 50.0, "note": "old sale", "timestamp": "2026-09-01T12:00:00"}
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_state(path)

    assert loaded.profit.total == Decimal("50.00")
    assert loaded.reviews == []


def test_saving_upgrades_an_old_file_to_the_current_schema(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema_version": 1, "profit_entries": []}), encoding="utf-8")

    save_state(load_state(path), path)

    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == SCHEMA_VERSION


def test_malformed_review_raises_storage_error(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps({"schema_version": 2, "reviews": [{"review_date": "not-a-date"}]}),
        encoding="utf-8",
    )

    with pytest.raises(StorageError):
        load_state(path)


def test_amounts_persist_as_decimal_strings_not_json_floats(tmp_path):
    """A JSON float on disk reintroduces the drift ADR-004 removes."""
    path = tmp_path / "state.json"
    save_state(_state_with("0.10", "0.20"), path)

    raw = json.loads(path.read_text(encoding="utf-8"))

    assert [e["amount"] for e in raw["profit_entries"]] == ["0.10", "0.20"]
    assert load_state(path).profit.total == Decimal("0.30")


def test_legacy_float_amounts_load_as_exact_decimals(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "profit_entries": [
                    {"amount": 0.1, "note": "dime", "timestamp": "2026-09-01T12:00:00"},
                    {"amount": 0.2, "note": "double", "timestamp": "2026-09-02T12:00:00"},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert load_state(path).profit.total == Decimal("0.30")


def test_hand_edited_negative_amount_is_rejected(tmp_path):
    """ADR-003 sells a hand-editable state file, so the deserializer
    has to enforce what the domain enforces."""
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "profit_entries": [
                    {"amount": "-500.00", "note": "oops", "timestamp": "2026-09-01T12:00:00"}
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(StorageError, match="Malformed profit entry"):
        load_state(path)


def test_legacy_review_task_categories_map_to_unspecified(tmp_path):
    """Files written before ADR-005 stamped the outcome into category."""
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "profit_entries": [],
                "reviews": [
                    {
                        "review_date": "2026-09-01",
                        "completed": [{"title": "posted content", "category": "completed"}],
                        "incomplete": [{"title": "wrote emails", "category": "carried"}],
                        "top_priority_tomorrow": "Ship the landing page",
                        "note": "",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_state(path)

    assert loaded.reviews[0].completed[0].category is Category.UNSPECIFIED
    assert loaded.reviews[0].incomplete[0].category is Category.UNSPECIFIED


def test_unknown_task_category_in_a_state_file_is_rejected(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "profit_entries": [],
                "reviews": [
                    {
                        "review_date": "2026-09-01",
                        "completed": [{"title": "posted content", "category": "revenu"}],
                        "incomplete": [],
                        "top_priority_tomorrow": "Ship it",
                        "note": "",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(StorageError, match="Malformed"):
        load_state(path)
