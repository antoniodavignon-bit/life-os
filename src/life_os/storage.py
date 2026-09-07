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
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from life_os.commitments import Commitment, CommitmentStatus
from life_os.day import DayPlan, ItemStatus, PlanItem
from life_os.profit import ProfitEntry, ProfitTracker
from life_os.review import DailyReview
from life_os.tasks import Category, Task

# Version 1: profit entries only.
# Version 2: adds daily reviews.
# Version 3: amounts serialize as decimal strings, not JSON floats, and
#            task categories are drawn from the closed Category set.
# Version 4: adds the commitment ledger — unfinished work as tracked
#            entities rather than repeated task titles (ADR-007).
# Version 5: adds day plans — the generated day persisted with per-item
#            identity and status, so progress is recordable during the
#            day rather than only at review time (ADR-008).
#
# Bumps are deliberate even when a change is additive. Reading an older
# file under newer code is a clean upgrade. But a newer file read by
# older code would load, silently drop what it didn't understand, and
# destroy it on the next save. Rejecting loudly beats losing data
# quietly — the same principle ADR-003 applies to corrupt files.
SCHEMA_VERSION = 5
SUPPORTED_VERSIONS = (1, 2, 3, 4, 5)

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
    """Everything Life OS persists between runs.

    ``reviews`` is a tuple: the state object is frozen, and a frozen
    object holding a mutable list is a promise it can't keep. Callers
    build a new ``AppState`` to change the reviews rather than mutating
    the one they were handed.
    """

    profit: ProfitTracker
    reviews: tuple[DailyReview, ...] = ()
    commitments: tuple[Commitment, ...] = ()
    day_plans: tuple[DayPlan, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "reviews", tuple(self.reviews))
        object.__setattr__(self, "commitments", tuple(self.commitments))
        object.__setattr__(self, "day_plans", tuple(self.day_plans))


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


def _commitment_to_dict(commitment: Commitment) -> dict:
    return {
        "id": commitment.id,
        "title": commitment.title,
        "opened_on": commitment.opened_on.isoformat(),
        "status": commitment.status.value,
        "closed_on": commitment.closed_on.isoformat() if commitment.closed_on else None,
    }


def _commitment_from_dict(raw: dict) -> Commitment:
    if not isinstance(raw, dict):
        raise StorageError(f"Commitment must be an object, got {raw!r}")

    try:
        closed_raw = raw.get("closed_on")
        return Commitment(
            id=raw["id"],
            title=str(raw["title"]),
            opened_on=date.fromisoformat(raw["opened_on"]),
            status=str(raw.get("status", CommitmentStatus.OPEN.value)),
            closed_on=date.fromisoformat(closed_raw) if closed_raw else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageError(f"Malformed commitment in state file: {raw!r} ({exc})") from exc


def _seed_commitments_from_reviews(reviews: tuple[DailyReview, ...]) -> tuple[Commitment, ...]:
    """Build a starting ledger for a state file written before v4.

    Seeded from the most recent review's incomplete tasks only — the
    work that would have been carried under the old display-only
    behavior. Walking every review in history would resurrect months of
    long-dead items on the first run after upgrading, which is worse
    than starting slightly light.
    """
    if not reviews:
        return ()

    latest = max(reviews, key=lambda r: r.review_date)
    return tuple(
        Commitment(id=i, title=task.title, opened_on=latest.review_date)
        for i, task in enumerate(latest.incomplete, start=1)
    )


def _plan_item_to_dict(item: PlanItem) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "category": item.category.value,
        "status": item.status.value,
        "closed_on": item.closed_on.isoformat() if item.closed_on else None,
    }


def _plan_item_from_dict(raw: dict) -> PlanItem:
    if not isinstance(raw, dict):
        raise StorageError(f"Plan item must be an object, got {raw!r}")

    try:
        closed_raw = raw.get("closed_on")
        raw_category = str(raw["category"])
        return PlanItem(
            id=raw["id"],
            title=str(raw["title"]),
            category=LEGACY_CATEGORY_ALIASES.get(raw_category, raw_category),
            status=str(raw.get("status", ItemStatus.OPEN.value)),
            closed_on=date.fromisoformat(closed_raw) if closed_raw else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageError(f"Malformed plan item in state file: {raw!r} ({exc})") from exc


def _day_plan_to_dict(plan: DayPlan) -> dict:
    return {
        "plan_date": plan.plan_date.isoformat(),
        "goals": list(plan.goals),
        "items": [_plan_item_to_dict(i) for i in plan.items],
    }


def _day_plan_from_dict(raw: dict) -> DayPlan:
    if not isinstance(raw, dict):
        raise StorageError(f"Day plan must be an object, got {raw!r}")

    goals_raw = raw.get("goals", [])
    if not isinstance(goals_raw, list):
        raise StorageError(f"Day plan 'goals' must be a list, got {goals_raw!r}")

    items_raw = raw.get("items", [])
    if not isinstance(items_raw, list):
        raise StorageError(f"Day plan 'items' must be a list, got {items_raw!r}")

    try:
        return DayPlan(
            plan_date=date.fromisoformat(raw["plan_date"]),
            goals=tuple(str(g) for g in goals_raw),
            items=tuple(_plan_item_from_dict(i) for i in items_raw),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageError(f"Malformed day plan in state file: {raw!r} ({exc})") from exc


def serialize(state: AppState) -> dict:
    """Convert application state into a JSON-safe dict."""
    return {
        "schema_version": SCHEMA_VERSION,
        "profit_entries": [_entry_to_dict(e) for e in state.profit.entries],
        "reviews": [_review_to_dict(r) for r in state.reviews],
        "commitments": [_commitment_to_dict(c) for c in state.commitments],
        "day_plans": [_day_plan_to_dict(p) for p in state.day_plans],
    }


def deserialize(raw: dict) -> AppState:
    """Rebuild application state from a parsed JSON dict.

    Older files upgrade cleanly: a version 1 file (profit only) gains
    an empty review list, version 1 and 2 amounts stored as JSON floats
    are converted to exact ``Decimal`` cents, and a file written before
    version 4 has its commitment ledger seeded from the last review's
    unfinished work. A file written before version 5 simply has no day
    plans. A version this build does not know is rejected rather than
    partially read.
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

    commitments_raw = raw.get("commitments")
    if commitments_raw is not None and not isinstance(commitments_raw, list):
        raise StorageError("'commitments' must be a list")

    # A pre-v5 file simply has no day plans. Unlike the v4 commitment
    # migration there is nothing to seed from: a day plan records which
    # of today's generated items you closed, and no earlier version
    # ever recorded that. Reconstructing it from reviews would invent
    # per-item history the user never stated.
    plans_raw = raw.get("day_plans", [])
    if not isinstance(plans_raw, list):
        raise StorageError("'day_plans' must be a list")

    tracker = ProfitTracker(entries=[_entry_from_dict(e) for e in entries_raw])
    reviews = tuple(_review_from_dict(r) for r in reviews_raw)

    if commitments_raw is None:
        # Pre-v4 file: no ledger was ever written, so build one.
        commitments = _seed_commitments_from_reviews(reviews)
    else:
        commitments = tuple(_commitment_from_dict(c) for c in commitments_raw)

    day_plans = tuple(_day_plan_from_dict(p) for p in plans_raw)

    return AppState(
        profit=tracker,
        reviews=reviews,
        commitments=commitments,
        day_plans=day_plans,
    )


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
    """Write state to ``path`` atomically, creating parent dirs as needed.

    Filesystem failures — a read-only directory, a full disk, a path
    the user cannot write — surface as ``StorageError`` so the CLI
    reports them the same way it reports a corrupt file, rather than
    letting a raw ``OSError`` traceback reach the terminal.
    """
    try:
        _write_atomically(state, path)
    except OSError as exc:
        raise StorageError(f"Could not write state file to {path}: {exc}") from exc


def _write_atomically(state: AppState, path: Path) -> None:
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
