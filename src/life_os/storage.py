"""Persistence layer for Life OS.

Domain modules hold no state between runs — a profit total that resets
every time the process exits is not a tracker. This module is the only
place that touches the filesystem, keeping ADR-002's "no I/O in domain
logic" rule intact.

State is a single JSON file (see ADR-003). Writes are atomic: content
goes to a temp file in the same directory and is then renamed over the
target, so an interrupted write cannot leave a half-written state file.
"""

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from life_os.profit import ProfitEntry, ProfitTracker

SCHEMA_VERSION = 1
DEFAULT_STATE_PATH = Path.home() / ".life-os" / "state.json"


class StorageError(Exception):
    """Raised when a state file exists but cannot be read as Life OS state."""


@dataclass(frozen=True)
class AppState:
    """Everything Life OS persists between runs."""

    profit: ProfitTracker


def _entry_to_dict(entry: ProfitEntry) -> dict:
    return {
        "amount": entry.amount,
        "note": entry.note,
        "timestamp": entry.timestamp.isoformat(),
    }


def _entry_from_dict(raw: dict) -> ProfitEntry:
    try:
        return ProfitEntry(
            amount=float(raw["amount"]),
            note=str(raw.get("note", "")),
            timestamp=datetime.fromisoformat(raw["timestamp"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageError(f"Malformed profit entry in state file: {raw!r}") from exc


def serialize(state: AppState) -> dict:
    """Convert application state into a JSON-safe dict."""
    return {
        "schema_version": SCHEMA_VERSION,
        "profit_entries": [_entry_to_dict(e) for e in state.profit.entries],
    }


def deserialize(raw: dict) -> AppState:
    """Rebuild application state from a parsed JSON dict."""
    if not isinstance(raw, dict):
        raise StorageError("State file must contain a JSON object")

    version = raw.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise StorageError(
            f"Unsupported state schema version {version!r} "
            f"(this build understands version {SCHEMA_VERSION})"
        )

    entries_raw = raw.get("profit_entries", [])
    if not isinstance(entries_raw, list):
        raise StorageError("'profit_entries' must be a list")

    tracker = ProfitTracker(entries=[_entry_from_dict(e) for e in entries_raw])
    return AppState(profit=tracker)


def load_state(path: Path = DEFAULT_STATE_PATH) -> AppState:
    """Read state from ``path``.

    A missing file yields empty state — a first run is normal, not an
    error. A file that exists but cannot be parsed raises
    ``StorageError`` rather than silently discarding the user's data.
    """
    if not path.exists():
        return AppState(profit=ProfitTracker())

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StorageError(f"State file at {path} is not valid JSON: {exc}") from exc

    return deserialize(raw)


def save_state(state: AppState, path: Path = DEFAULT_STATE_PATH) -> None:
    """Write state to ``path`` atomically, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(serialize(state), handle, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        # Never leave a stray temp file behind on failure.
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
