"""Commitment Ledger — Module 5 of Life OS.

A ``Task`` is a value. Today's "Execute a direct revenue action for:
grow the store" is not yesterday's instance of that task, it is a fresh
one from the same template, and asking whether they are "the same" is
meaningless.

An unfinished obligation is not a value. It persists, it ages, and it
ends — done, or deliberately dropped. Representing both with ``Task``
is why carried work could ride along forever: nothing could say how old
it was, whether it was the thing missed on Monday, or that you had
decided it no longer mattered.

This module holds the other half: ``Commitment``, an entity with
identity, tracked in a ledger that spans days. See ADR-007.

Follows ADR-002: frozen dataclasses, pure functions, no I/O, injectable
clock (``on=``, ``today=``), validation at construction, and no mutable
internal state handed to callers.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

# A full week of carrying something without finishing it. Long enough
# that an ordinarily busy stretch does not trigger noise; short enough
# that nothing rots quietly for a month.
STALE_AFTER_DAYS = 7

# Above this many open commitments you are not planning a fresh day,
# you are behind. Life OS says so rather than absorbing it silently.
# Open work is deliberately exempt from MAX_ACTIVE_GOALS (ADR-006);
# this threshold is the pressure valve that exemption needs.
CARRY_WARNING_THRESHOLD = 3


class CommitmentStatus(StrEnum):
    """Where a commitment ended up.

    ``DROPPED`` is a first-class outcome, not a failure state. Deciding
    something no longer matters is a real decision, and a ledger that
    only allows "done" quietly pressures you into lying to it.
    """

    OPEN = "open"
    DONE = "done"
    DROPPED = "dropped"


def normalize_title(title: str) -> str:
    """Trim and collapse internal whitespace, preserving the spelling."""
    return " ".join(str(title).split())


def match_key(title: str) -> str:
    """The key two titles are considered the same obligation under.

    Case- and whitespace-insensitive: re-typing "Called the supplier"
    as "called the supplier" should continue the commitment you already
    have, not open a second one beside it.
    """
    return normalize_title(title).casefold()


@dataclass(frozen=True)
class Commitment:
    """One unfinished obligation, tracked across days.

    ``id`` is a small integer assigned by the ledger and never reused.
    Not a UUID and not a content hash: this is a single-user local tool
    where the id exists to be typed (``life-os done 7``), and an
    integer has no collision risk to guard against. See ADR-007.
    """

    id: int
    title: str
    opened_on: date
    status: CommitmentStatus = CommitmentStatus.OPEN
    closed_on: date | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, int) or isinstance(self.id, bool) or self.id < 1:
            raise ValueError(f"Commitment id must be a positive integer, got {self.id!r}")

        title = normalize_title(self.title)
        if not title:
            raise ValueError("Commitment title must not be empty")

        if not isinstance(self.opened_on, date):
            raise ValueError(f"opened_on must be a date, got {type(self.opened_on).__name__}")

        try:
            status = CommitmentStatus(self.status)
        except ValueError as exc:
            known = ", ".join(s.value for s in CommitmentStatus)
            raise ValueError(
                f"Unknown commitment status {self.status!r} (expected one of: {known})"
            ) from exc

        # An open commitment has no closing date; a closed one must
        # have one, or "how long did that take" has no answer.
        if status is CommitmentStatus.OPEN and self.closed_on is not None:
            raise ValueError("An open commitment cannot have a closed_on date")
        if status is not CommitmentStatus.OPEN:
            if self.closed_on is None:
                raise ValueError(f"A {status.value} commitment must have a closed_on date")
            if not isinstance(self.closed_on, date):
                raise ValueError("closed_on must be a date")
            if self.closed_on < self.opened_on:
                raise ValueError("closed_on cannot precede opened_on")

        object.__setattr__(self, "title", title)
        object.__setattr__(self, "status", status)

    @property
    def is_open(self) -> bool:
        """Whether this commitment is still outstanding."""
        return self.status is CommitmentStatus.OPEN

    @property
    def key(self) -> str:
        """The title key used to match a miss against this commitment."""
        return match_key(self.title)

    def age_days(self, today: date) -> int:
        """Days carried, counting the day it opened as day zero.

        Uses ``closed_on`` once closed, so the age of a finished
        commitment stops moving.
        """
        end = self.closed_on if self.closed_on is not None else today
        return (end - self.opened_on).days

    def is_stale(self, today: date, threshold: int = STALE_AFTER_DAYS) -> bool:
        """Whether this is open and old enough to demand a decision."""
        return self.is_open and self.age_days(today) >= threshold

    def closed(self, status: CommitmentStatus, on: date) -> "Commitment":
        """Return a closed copy. Raises if this is already closed."""
        if not self.is_open:
            raise ValueError(f"Commitment {self.id} is already {self.status.value}")
        if status is CommitmentStatus.OPEN:
            raise ValueError("Closing a commitment requires a terminal status")

        return Commitment(
            id=self.id,
            title=self.title,
            opened_on=self.opened_on,
            status=status,
            closed_on=on,
        )


def open_items(commitments: Iterable[Commitment]) -> tuple[Commitment, ...]:
    """Outstanding commitments, oldest first."""
    return tuple(sorted((c for c in commitments if c.is_open), key=lambda c: (c.opened_on, c.id)))


def stale_items(
    commitments: Iterable[Commitment], today: date, threshold: int = STALE_AFTER_DAYS
) -> tuple[Commitment, ...]:
    """Open commitments old enough to demand a decision, oldest first."""
    return tuple(c for c in open_items(commitments) if c.is_stale(today, threshold))


def next_id(commitments: Iterable[Commitment]) -> int:
    """The next id to hand out.

    Derived from the maximum in use rather than the count, so ids are
    never reused. Commitments are closed, never deleted, so the maximum
    only grows.
    """
    ids = [c.id for c in commitments]
    return max(ids, default=0) + 1


def find(commitments: Iterable[Commitment], commitment_id: int) -> Commitment | None:
    """The commitment with this id, or ``None``."""
    return next((c for c in commitments if c.id == commitment_id), None)


def record_misses(
    commitments: Iterable[Commitment], titles: Iterable[str], *, on: date
) -> tuple[tuple[Commitment, ...], tuple[Commitment, ...]]:
    """Open a commitment for each missed title that isn't already open.

    Returns the new ledger and the commitments newly opened.

    A title that matches something already open is left untouched —
    ``opened_on`` keeps pointing at the day the obligation first
    appeared, which is what makes the age meaningful. Missing the same
    thing four days running is one commitment aged four days, not four
    commitments aged zero.

    A title matching a *closed* commitment opens a new one. Doing
    something, then failing to do it again later, is a new obligation
    rather than a reopening of the old one — and the ledger keeps both,
    so the history stays honest.
    """
    ledger = list(commitments)
    live = {c.key for c in ledger if c.is_open}
    opened: list[Commitment] = []

    for raw in titles:
        title = normalize_title(raw)
        if not title:
            continue

        key = match_key(title)
        if key in live:
            continue

        commitment = Commitment(id=next_id(ledger), title=title, opened_on=on)
        ledger.append(commitment)
        opened.append(commitment)
        live.add(key)

    return tuple(ledger), tuple(opened)


def close_by_title(
    commitments: Iterable[Commitment],
    titles: Iterable[str],
    *,
    on: date,
    status: CommitmentStatus = CommitmentStatus.DONE,
) -> tuple[tuple[Commitment, ...], tuple[Commitment, ...]]:
    """Close open commitments whose titles match any of ``titles``.

    Returns the new ledger and the commitments closed. Titles matching
    nothing open are ignored: reporting work that was never a carried
    commitment is the normal case, not an error.
    """
    wanted = {match_key(t) for t in titles if normalize_title(t)}
    if not wanted:
        return tuple(commitments), ()

    ledger: list[Commitment] = []
    closed: list[Commitment] = []

    for commitment in commitments:
        if commitment.is_open and commitment.key in wanted:
            closed_commitment = commitment.closed(status, on)
            ledger.append(closed_commitment)
            closed.append(closed_commitment)
        else:
            ledger.append(commitment)

    return tuple(ledger), tuple(closed)


def close_by_id(
    commitments: Iterable[Commitment],
    commitment_id: int,
    *,
    on: date,
    status: CommitmentStatus = CommitmentStatus.DONE,
) -> tuple[tuple[Commitment, ...], Commitment]:
    """Close one commitment by id.

    Raises ``ValueError`` for an unknown id or one that is already
    closed — both are the user asking for something that cannot happen,
    and silently doing nothing would look like success.
    """
    target = find(commitments, commitment_id)
    if target is None:
        raise ValueError(f"No commitment with id {commitment_id}")

    closed_commitment = target.closed(status, on)
    ledger = tuple(closed_commitment if c.id == commitment_id else c for c in commitments)
    return ledger, closed_commitment
