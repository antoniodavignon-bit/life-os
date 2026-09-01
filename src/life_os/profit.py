"""Profit Tracker — Module 3 of Life OS.

Logs income entries with timestamps and surfaces running totals and
period summaries. Ported from the original ``profit_tracker.py`` script
into the tested ``life_os`` package, following the same pattern as
``tasks.py``: plain dataclasses, no I/O or print() inside the domain
logic, and an injectable clock so behavior is deterministic in tests.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ProfitEntry:
    """A single logged profit entry."""

    amount: float
    note: str
    timestamp: datetime


@dataclass
class ProfitTracker:
    """Tracks profit entries and running totals."""

    entries: list[ProfitEntry] = field(default_factory=list)

    @property
    def total(self) -> float:
        """Sum of all logged profit."""
        return sum(entry.amount for entry in self.entries)

    def add_profit(
        self, amount: float, note: str = "", *, now: datetime | None = None
    ) -> ProfitEntry:
        """Log a new income entry and return it.

        Raises ``ValueError`` for a non-positive amount rather than
        silently accepting bad data into the total.
        """
        if amount <= 0:
            raise ValueError("Profit amount must be positive")

        entry = ProfitEntry(amount=amount, note=note, timestamp=now or datetime.now())
        self.entries.append(entry)
        return entry

    def entries_between(self, start: datetime, end: datetime) -> list[ProfitEntry]:
        """Return entries with a timestamp in [start, end)."""
        return [e for e in self.entries if start <= e.timestamp < end]

    def reset(self) -> None:
        """Clear all entries."""
        self.entries.clear()
