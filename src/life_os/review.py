"""Review System — Module 4 of Life OS.

Closes the Plan → Execute → Track → Review loop. An end-of-day review
records what got done, what didn't, and tomorrow's single highest
priority; incomplete work carries forward instead of quietly
disappearing. Weekly summaries aggregate those reviews so execution
patterns become visible over time rather than felt.

Follows the same conventions as the other modules: frozen dataclasses,
pure functions, validation at construction, and no I/O in domain logic.
"""

from dataclasses import dataclass
from datetime import date

from life_os.tasks import Task


@dataclass(frozen=True)
class DailyReview:
    """One end-of-day review.

    ``top_priority_tomorrow`` is deliberately required: the review loop
    is only useful if it produces a concrete next action.
    """

    review_date: date
    completed: list[Task]
    incomplete: list[Task]
    top_priority_tomorrow: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.top_priority_tomorrow.strip():
            raise ValueError("top_priority_tomorrow must not be empty")

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
