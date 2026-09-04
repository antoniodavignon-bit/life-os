"""Profit Tracker — Module 3 of Life OS.

Logs income entries with timestamps and surfaces running totals and
period summaries.

Amounts are ``Decimal``, never ``float`` — see ADR-004. Binary floats
cannot represent most decimal cents exactly, so a float income log
accumulates error silently and reports a total that is off by a
fraction of a cent per entry. For the one module in Life OS that holds
real money, "close enough" is the wrong default.

Follows ADR-002: no I/O in domain logic, injectable clock, validation
at construction, and no mutable internal state handed to callers.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

#: Money is stored to the cent. Anything finer is not a currency amount.
CENTS = Decimal("0.01")

ZERO = Decimal("0.00")


def to_amount(value: "Decimal | int | str | float") -> Decimal:
    """Coerce ``value`` into a currency amount quantized to cents.

    Accepts ``Decimal``, ``int``, and numeric strings directly. A
    ``float`` is routed through ``str`` first: ``Decimal(0.1)`` is
    ``0.1000000000000000055511151231257827``, while
    ``Decimal(str(0.1))`` is ``0.1`` — the number the caller meant.
    Floats are tolerated for callers we don't control, not endorsed.

    Raises ``ValueError`` for anything that is not a finite number.
    """
    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, bool):
        # bool is an int subclass; silently logging True as $1 is nonsense.
        raise ValueError(f"Amount must be a number, got {value!r}")
    elif isinstance(value, int):
        candidate = Decimal(value)
    elif isinstance(value, float):
        candidate = Decimal(str(value))
    elif isinstance(value, str):
        try:
            candidate = Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError(f"Amount {value!r} is not a valid number") from exc
    else:
        raise ValueError(f"Amount must be a number, got {type(value).__name__}")

    if not candidate.is_finite():
        raise ValueError(f"Amount must be finite, got {candidate}")

    return candidate.quantize(CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ProfitEntry:
    """A single logged profit entry.

    Validation lives here rather than in ``ProfitTracker.add_profit``
    so that every path into an entry — the CLI, a test, the state file
    deserializer — is held to the same rule. A negative amount
    hand-edited into ``state.json`` is rejected on load for exactly the
    same reason ``life-os profit add -50`` is rejected at the terminal.
    """

    amount: Decimal
    note: str
    timestamp: datetime

    def __post_init__(self) -> None:
        amount = to_amount(self.amount)

        if amount <= ZERO:
            raise ValueError(f"Profit amount must be positive, got {amount}")

        if not isinstance(self.timestamp, datetime):
            raise ValueError(f"Timestamp must be a datetime, got {type(self.timestamp).__name__}")

        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "note", str(self.note).strip())


class ProfitTracker:
    """Tracks profit entries and running totals.

    Deliberately not a dataclass with a public ``entries`` list. That
    shape let callers do ``tracker.entries.append(...)``, writing
    straight past every validation ``add_profit`` performs — the exact
    "return copies, not internals" rule in ADR-002. ``entries`` is now
    a read-only snapshot; the only way in is ``add_profit``.
    """

    __slots__ = ("_entries",)

    def __init__(self, entries: Iterable[ProfitEntry] = ()) -> None:
        self._entries: list[ProfitEntry] = []
        for entry in entries:
            if not isinstance(entry, ProfitEntry):
                raise ValueError(f"Expected ProfitEntry, got {type(entry).__name__}")
            self._entries.append(entry)

    @property
    def entries(self) -> tuple[ProfitEntry, ...]:
        """An immutable snapshot of every logged entry, oldest first."""
        return tuple(self._entries)

    @property
    def total(self) -> Decimal:
        """Sum of all logged profit, to the cent."""
        return sum((entry.amount for entry in self._entries), start=ZERO)

    def add_profit(
        self,
        amount: "Decimal | int | str | float",
        note: str = "",
        *,
        now: datetime | None = None,
    ) -> ProfitEntry:
        """Log a new income entry and return it.

        Raises ``ValueError`` for a non-positive or non-numeric amount
        rather than letting bad data into the total. Note that an
        amount that rounds to zero at cent precision (``0.001``) is
        non-positive money and is refused.
        """
        entry = ProfitEntry(
            amount=amount,
            note=note,
            timestamp=now if now is not None else datetime.now(),
        )
        self._entries.append(entry)
        return entry

    def entries_between(self, start: datetime, end: datetime) -> tuple[ProfitEntry, ...]:
        """Return entries with a timestamp in ``[start, end)``."""
        return tuple(e for e in self._entries if start <= e.timestamp < end)

    def total_between(self, start: datetime, end: datetime) -> Decimal:
        """Sum of entries with a timestamp in ``[start, end)``."""
        return sum((e.amount for e in self.entries_between(start, end)), start=ZERO)

    def reset(self) -> None:
        """Clear all entries."""
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[ProfitEntry]:
        return iter(self._entries)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProfitTracker):
            return NotImplemented
        return self._entries == other._entries

    def __repr__(self) -> str:
        return f"ProfitTracker(entries={len(self._entries)}, total={self.total})"
