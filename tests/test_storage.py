import json
from datetime import date, datetime

import pytest

from life_os.profit import ProfitTracker
from life_os.review import DailyReview
from life_os.storage import (
    AppState,
    StorageError,
    load_state,
    save_state,
)
from life_os.tasks import Task


def _state_with(*amounts: float) -> AppState:
    tracker = ProfitTracker()
    for i, amount in enumerate(amounts, start=1):
        tracker.add_profit(amount, f"entry {i}", now=datetime(2026, 9, i, 12, 0))
    return AppState(profit=tracker)


def test_load_returns_empty_state_when_file_does_not_exist(tmp_path):
    state = load_state(tmp_path / "nothing-here.json")

    assert state.profit.entries == []
    assert state.profit.total == 0


def test_save_then_load_round_trips_profit_entries(tmp_path):
    path = tmp_path / "state.json"
    save_state(_state_with(250.0, 100.0), path)

    loaded = load_state(path)

    assert loaded.profit.total == pytest.approx(350.0)
    assert [e.note for e in loaded.profit.entries] == ["entry 1", "entry 2"]
    assert loaded.profit.entries[0].timestamp == datetime(2026, 9, 1, 12, 0)


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "deeper" / "state.json"

    save_state(_state_with(10.0), path)

    assert path.exists()
    assert load_state(path).profit.total == pytest.approx(10.0)


def test_save_leaves_no_temp_files_behind(tmp_path):
    path = tmp_path / "state.json"

    save_state(_state_with(10.0), path)

    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_save_overwrites_previous_state_atomically(tmp_path):
    path = tmp_path / "state.json"
    save_state(_state_with(10.0), path)

    save_state(_state_with(20.0, 30.0), path)

    loaded = load_state(path)
    assert loaded.profit.total == pytest.approx(50.0)
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
        completed=[Task(title=f"done {i}", category="completed") for i in range(done)],
        incomplete=[Task(title=f"missed {i}", category="carried") for i in range(missed)],
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

    assert loaded.profit.total == pytest.approx(50.0)
    assert loaded.reviews == []


def test_saving_upgrades_a_version_1_file_to_version_2(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema_version": 1, "profit_entries": []}), encoding="utf-8")

    save_state(load_state(path), path)

    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2


def test_malformed_review_raises_storage_error(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps({"schema_version": 2, "reviews": [{"review_date": "not-a-date"}]}),
        encoding="utf-8",
    )

    with pytest.raises(StorageError):
        load_state(path)
