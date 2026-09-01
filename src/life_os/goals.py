"""Goal System — Module 2 of Life OS.

Converts a 90-day goal into a weekly milestone map, and reports which
milestone a given date falls into. This is the "goal-to-task
breakdown method" from the PRD: goals get broken into weekly chunks
so daily tasks (see ``tasks.py``) always trace back to something
measurable, instead of a vague standing intention.
"""

from dataclasses import dataclass
from datetime import date, timedelta

DEFAULT_DURATION_DAYS = 90
DAYS_PER_MILESTONE = 7


@dataclass(frozen=True)
class Milestone:
    """One weekly checkpoint within a goal's timeline."""

    week_number: int
    start_date: date
    end_date: date

    def contains(self, day: date) -> bool:
        """Whether ``day`` falls within this milestone's week (inclusive)."""
        return self.start_date <= day <= self.end_date


@dataclass(frozen=True)
class Goal:
    """A goal tracked over a fixed number of days (90 by default)."""

    title: str
    category: str
    start_date: date
    duration_days: int = DEFAULT_DURATION_DAYS

    def __post_init__(self) -> None:
        if self.duration_days <= 0:
            raise ValueError("duration_days must be positive")

    @property
    def end_date(self) -> date:
        """The last day this goal is active (inclusive)."""
        return self.start_date + timedelta(days=self.duration_days - 1)

    def is_active_on(self, day: date) -> bool:
        """Whether this goal's window covers ``day``."""
        return self.start_date <= day <= self.end_date


def generate_milestones(goal: Goal) -> list[Milestone]:
    """Break a goal's duration into consecutive weekly milestones.

    The final milestone may be shorter than 7 days when
    ``duration_days`` isn't an exact multiple of a week.
    """
    milestones = []
    week_start = goal.start_date
    week_number = 1

    while week_start <= goal.end_date:
        week_end = min(week_start + timedelta(days=DAYS_PER_MILESTONE - 1), goal.end_date)
        milestones.append(
            Milestone(week_number=week_number, start_date=week_start, end_date=week_end)
        )
        week_start = week_end + timedelta(days=1)
        week_number += 1

    return milestones


def current_milestone(goal: Goal, today: date) -> Milestone | None:
    """Return the milestone covering ``today``, or None if the goal
    isn't active on that date (not started yet, or already finished).
    """
    if not goal.is_active_on(today):
        return None

    for milestone in generate_milestones(goal):
        if milestone.contains(today):
            return milestone

    return None  # unreachable given is_active_on, kept for clarity
