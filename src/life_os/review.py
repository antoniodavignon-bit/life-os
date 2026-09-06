"""Review System — Module 4 of Life OS.

Closes the Plan → Execute → Track → Review loop. An end-of-day review
records what got done, what didn't, and tomorrow's single highest
priority; incomplete work carries forward instead of quietly
disappearing. Weekly summaries aggregate those reviews so execution
patterns become visible over time rather than felt.

Carry-forward selection lives here rather than in the CLI (ADR-006):
deciding *which* review a day inherits from, and whether the inherited
pile is too big, is domain reasoning. The CLI only decides how to say
it.

Follows the same conventions as the other modules: frozen dataclasses,
pure functions, validation at construction, and no I/O in domain logic.
"""

from dataclasses import dataclass
from datetime import date

from life_os.tasks import Task

# Above this many carried tasks, you are not planning a fresh day —
# you are behind. Life OS says so rather than absorbing it silently.
# Carried work is deliberately exempt from MAX_ACTIVE_GOALS (ADR-006);
# this threshold is the pressure valve that exemption needs.
CARRY_WARNING_THRESHOLD = 3


@dataclass(frozen=True)
class DailyReview:
    """One end-of-day review.

    ``top_priority_tomorrow`` is deliberately required: the review loop
    is only useful if it produces a concrete next action.

    ``completed`` and ``incomplete`` are stored as tuples; lists passed
    in are converted, so the frozen guarantee is real rather than
    nominal.
    """

    review_date: date
    completed: tuple[Task, ...]
    incomplete: tuple[Task, ...]
    top_priority_tomorrow: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.top_priority_tomorrow.strip():
            raise ValueError("top_priority_tomorrow must not be empty")

        # Callers pass lists; a frozen dataclass holding a mutable list
        # is a promise it can't keep, so coerce at the boundary.
        object.__setattr__(self, "completed", tuple(self.completed))
        object.__setattr__(self, "incomplete", tuple(self.incomplete))

    @property
    def total_tasks(self) -> int:
        """How many tasks this review covers."""
        return len(self.completed) + len(self.incomplete)

    @property
    def completion_rate(self) -> float:
        """Fraction of tasks completed, 0.0 through 1.0.

        A day with no logged tasks scores 0.0 rather than raising —
        an empty day is a real (if unproductive) outcome, not an error.
        """
        if self.total_tasks == 0:
            return 0.0
        return len(self.completed) / self.total_tasks


@dataclass(frozen=True)
class WeeklySummary:
    """Aggregate execution stats across a set of daily reviews."""

    reviews_logged: int
    tasks_completed: int
    tasks_missed: int
    completion_rate: float


def carry_forward(review: DailyReview) -> list[Task]:
    """Return the tasks that should roll into the next day.

    Returns a new list so mutating the result can't corrupt the review.
    """
    return list(review.incomplete)


def summarize_week(reviews: list[DailyReview]) -> WeeklySummary:
    """Aggregate a week's reviews into a single performance summary.

    An empty list yields a zeroed summary rather than raising, so a
    week with no reviews logged still reports cleanly.
    """
    completed = sum(len(r.completed) for r in reviews)
    missed = sum(len(r.incomplete) for r in reviews)
    total = completed + missed

    return WeeklySummary(
        reviews_logged=len(reviews),
        tasks_completed=completed,
        tasks_missed=missed,
        completion_rate=(completed / total) if total else 0.0,
    )


@dataclass(frozen=True)
class CarryForward:
    """Unfinished work inherited from the most recent prior review.

    ``source_date`` is the review the tasks came from, or ``None`` when
    there is nothing to carry — a first run, or a genuinely clean slate.
    Both are normal states, not errors.
    """

    tasks: tuple[Task, ...] = ()
    source_date: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tasks", tuple(self.tasks))

        if self.source_date is not None and not isinstance(self.source_date, date):
            raise ValueError(f"source_date must be a date, got {type(self.source_date).__name__}")

    @property
    def count(self) -> int:
        """How many tasks are being carried."""
        return len(self.tasks)

    @property
    def is_empty(self) -> bool:
        """Whether there is nothing to carry."""
        return not self.tasks

    @property
    def is_overloaded(self) -> bool:
        """Whether the carried pile has passed the warning threshold.

        The domain decides *that* you are overloaded; the presentation
        layer decides how to tell you (ADR-002, ADR-006).
        """
        return self.count > CARRY_WARNING_THRESHOLD


def latest_review_before(reviews: list[DailyReview], day: date) -> DailyReview | None:
    """The most recent review dated strictly before ``day``.

    Strictly before matters. Log this morning's review and then plan
    again this afternoon: without the strict comparison the day would
    inherit its own misses and show you work you already accounted for.

    Returns ``None`` when no earlier review exists.
    """
    earlier = [r for r in reviews if r.review_date < day]
    if not earlier:
        return None
    return max(earlier, key=lambda r: r.review_date)


def carried_forward(reviews: list[DailyReview], day: date) -> CarryForward:
    """What ``day`` inherits from the last review before it.

    An empty history yields an empty ``CarryForward`` rather than
    raising — a first run carries nothing, which is a real outcome
    (ADR-002, rule 5).
    """
    source = latest_review_before(reviews, day)
    if source is None:
        return CarryForward()

    return CarryForward(tasks=tuple(source.incomplete), source_date=source.review_date)


def upsert_review(
    reviews: list[DailyReview], review: DailyReview
) -> tuple[list[DailyReview], DailyReview | None]:
    """Insert ``review``, replacing any existing review for its date.

    Returns the new list — sorted by date, so callers get a stable
    order regardless of the sequence entries arrived in — together with
    the review that was displaced, or ``None`` if this is the first one
    for that date. Callers are expected to surface a replacement rather
    than let a correction happen silently.

    A day has one review. Appending a second meant ``summarize_week``
    counted the same day twice and reported a completion rate that was
    arithmetically fine and factually wrong.
    """
    replaced = next((r for r in reviews if r.review_date == review.review_date), None)
    kept = [r for r in reviews if r.review_date != review.review_date]
    kept.append(review)

    return sorted(kept, key=lambda r: r.review_date), replaced
