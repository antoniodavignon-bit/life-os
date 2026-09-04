"""Persistence layer for Life OS.

Domain modules hold no state between runs — a profit total that resets
every time the process exits is not a tracker. This module is the only
place that touches the filesystem, keeping ADR-002's "no I/O in domain
logic" rule intact.

State is a single JSON file (see ADR-003). Writes are atomic: content
goes to a temp file in the same directory and is then renamed over the
target, so an interrupted write cannot leave a half-written state file.

Deserialization builds real domain objects rather than plain dicts, so
every rule the domain enforces at construction also guards the file on
disk. ADR-003 sells a hand-editable state file as a feature; that only
holds if hand-edited nonsense is rejected on the way back in.
"""

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from life_os.profit import ProfitEntry, ProfitTracker
from life_os.review import DailyReview
from life_os.tasks import Category, Task

# Version 1: profit entries only.
# Version 2: adds daily reviews.
# Version 3: amounts serialize as decimal strings, not JSON floats, and
#            task categories are drawn from the closed Category set.
#
# Bumps are deliberate even when a change is additive. Reading an older
# file under newer code is a clean upgrade. But a newer file read by
# older code would load, silently drop what it didn't understand, and
# destroy it on the next save. Rejecting loudly beats losing data
# quietly — the same principle ADR-003 applies to corrupt files.
SCHEMA_VERSION = 3
SUPPORTED_VERSIONS = (1, 2, 3)

# Before ADR-005, the CLI stamped review tasks with the outcome
# ("completed" / "carried") in the category field — which described
# where the task landed, not what kind of work it was. Those files
# still exist on real machines, so they map to an honest UNSPECIFIED
# rather than being rejected.
LEGACY_CATEGORY_ALIASES: dict[str, Category] = {
    "completed": Category.UNSPECIFIED,
    "carried": Category.UNSPECIFIED,
}

DEFAULT_STATE_PATH = Path.home() / ".life-os" / "state.json"


class StorageError(Exception):
    """Raised when a state file exists but cannot be read as Life OS state."""


@dataclass(frozen=True)
class AppState:
    """Everything Life OS persists between runs."""

    profit: ProfitTracker
    reviews: list[DailyReview] = field(default_factory=list)


def _entry_to_dict(entry: ProfitEntry) -> dict:
    # str(Decimal) round-trips exactly; a JSON float would not.
    return {
        "amount": str(entry.amount),
        "note": entry.note,
        "timestamp": entry.timestamp.isoformat(),
    }


def _entry_from_dict(raw: dict) -> ProfitEntry:
    if not isinstance(raw, dict):
        raise StorageError(f"Profit entry must be an object, got {raw!r}")

    try:
        # Amount is handed to ProfitEntry as-is: v1/v2 files hold JSON
        # floats, v3 holds decimal strings, and the domain type knows
        # how to accept both and how to reject anything else.
        return ProfitEntry(
            amount=raw["amount"],
            note=str(raw.get("note", "")),
            timestamp=datetime.fromisoformat(raw["timestamp"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageError(f"Malformed profit entry in state file: {raw!r} ({exc})") from exc


def _task_to_dict(task: Task) -> dict:
    return {"title": task.title, "category": task.category.value}


def _task_from_dict(raw: dict) -> Task:
    if not isinstance(raw, dict):
        raise StorageError(f"Task must be an object, got {raw!r}")

    try:
        raw_category = str(raw["category"])
        category = LEGACY_CATEGORY_ALIASES.get(raw_category, raw_category)
        return Task(title=str(raw["title"]), category=category)
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageError(f"Malformed task in state file: {raw!r} ({exc})") from exc


def _review_to_dict(review: DailyReview) -> dict:
    return {
        "review_date": review.review_date.isoformat(),
        "completed": [_task_to_dict(t) for t in review.completed],
        "incomplete": [_task_to_dict(t) for t in review.incomplete],
        "top_priority_tomorrow": review.top_priority_tomorrow,
        "note": review.note,
    }


def _review_from_dict(raw: dict) -> DailyReview:
    if not isinstance(raw, dict):
        raise StorageError(f"Review must be an object, got {raw!r}")

    try:
        return DailyReview(
            review_date=date.fromisoformat(raw["review_date"]),
            completed=[_task_from_dict(t) for t in raw.get("completed", [])],
            incomplete=[_task_from_dict(t) for t in raw.get("incomplete", [])],
            top_priority_tomorrow=str(raw["top_priority_tomorrow"]),
            note=str(raw.get("note", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageError(f"Malformed review in state file: {raw!r} ({exc})") from exc


def serialize(state: AppState) -> dict:
    """Convert application state into a JSON-safe dict."""
    return {
        "schema_version": SCHEMA_VERSION,
        "profit_entries": [_entry_to_dict(e) for e in state.profit.entries],
        "reviews": [_review_to_dict(r) for r in state.reviews],
    }


def deserialize(raw: dict) -> AppState:
    """Rebuild application state from a parsed JSON dict.

    Older files upgrade cleanly: a version 1 file (profit only) gains
    an empty review list, and version 1 and 2 amounts stored as JSON
    floats are converted to exact ``Decimal`` cents. A version this
    build does not know is rejected rather than partially read.
    """
    if not isinstance(raw, dict):
        raise StorageError("State file must contain a JSON object")

    version = raw.get("schema_version", SCHEMA_VERSION)
    if version not in SUPPORTED_VERSIONS:
        raise StorageError(
            f"Unsupported state schema version {version!r} "
            f"(this build understands versions {', '.join(map(str, SUPPORTED_VERSIONS))})"
        )

    entries_raw = raw.get("profit_entries", [])
    if not isinstance(entries_raw, list):
        raise StorageError("'profit_entries' must be a list")

    reviews_raw = raw.get("reviews", [])
    if not isinstance(reviews_raw, list):
        raise StorageError("'reviews' must be a list")

    tracker = ProfitTracker(entries=[_entry_from_dict(e) for e in entries_raw])
    reviews = [_review_from_dict(r) for r in reviews_raw]
    return AppState(profit=tracker, reviews=reviews)


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
    except OSError as exc:
        raise StorageError(f"Could not read state file at {path}: {exc}") from exc

    return deserialize(raw)


def _json_default(value: object) -> str:
    """Serialize types ``json`` does not handle natively.

    Only ``Decimal`` reaches this today, and it must become a string —
    ``float(value)`` here would quietly undo ADR-004.
    """
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def save_state(state: AppState, path: Path = DEFAULT_STATE_PATH) -> None:
    """Write state to ``path`` atomically, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(serialize(state), handle, indent=2, default=_json_default)
            handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        # Never leave a stray temp file behind on failure.
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
