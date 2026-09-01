import json
from datetime import datetime

import pytest

from life_os.profit import ProfitTracker
from life_os.storage import (
    AppState,
    StorageError,
    load_state,
    save_state,
)


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
