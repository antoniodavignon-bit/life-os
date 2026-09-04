"""Task Engine — Module 1 of Life OS.

Turns a short list of active goals into a structured daily plan:
revenue work, skill work, and maintenance work. Daily tasks always
trace back to a goal, so no day is spent on motion that isn't attached
to something you're actually trying to move.

Follows ADR-002: frozen dataclasses, no I/O, validation at
construction, clean degradation on empty input, and no mutable state
handed back to callers.

Task categories are a closed set (``Category``) rather than free-form
strings — see ADR-005. Before that change any typo produced a silently
valid category that round-tripped through the state file forever.
"""

from dataclasses import dataclass
from enum import StrEnum

# One goal produces one task per category, so this is also the ceiling
# on active goals. See ``generate_tasks`` for why it refuses rather
# than truncates.
MAX_ACTIVE_GOALS = 3


class Category(StrEnum):
    """The kind of work a task represents.

    A ``StrEnum`` so members serialize to plain JSON strings and
    compare equal to their value, keeping the state file readable and
    hand-editable (ADR-003).

    ``UNSPECIFIED`` covers tasks the user typed by hand — a review
    entry, for instance — where Life OS was never told what kind of
    work it was. It is an honest "unknown", not a fourth work type.
    """

    REVENUE = "revenue"
    SKILL = "skill"
    MAINTENANCE = "maintenance"
    UNSPECIFIED = "unspecified"


#: Categories a generated daily plan is built from, in display order.
PLAN_CATEGORIES: tuple[Category, ...] = (
    Category.REVENUE,
    Category.SKILL,
    Category.MAINTENANCE,
)


@dataclass(frozen=True)
class Task:
    """A single actionable Life OS task.

    ``category`` accepts a ``Category`` or its string value; anything
    else raises ``ValueError`` at construction rather than becoming a
    category nobody defined.
    """

    title: str
    category: Category

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("Task title must not be empty")

        try:
            category = Category(self.category)
        except ValueError as exc:
            known = ", ".join(c.value for c in Category)
            raise ValueError(
                f"Unknown task category {self.category!r} (expected one of: {known})"
            ) from exc

        # Normalize so a Task built from a raw string is indistinguishable
        # from one built from the enum. Frozen dataclasses need the
        # explicit setattr; this is the documented way to do it.
        object.__setattr__(self, "title", self.title.strip())
        object.__setattr__(self, "category", category)


@dataclass(frozen=True)
class DailyPlan:
    """A structured set of tasks for one day.

    Fields are tuples, not lists: a frozen dataclass wrapping mutable
    lists is a promise it can't keep.
    """

    revenue: tuple[Task, ...]
    skill: tuple[Task, ...]
    maintenance: tuple[Task, ...]

    def __post_init__(self) -> None:
        for name in ("revenue", "skill", "maintenance"):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    @property
    def all_tasks(self) -> tuple[Task, ...]:
        """Every task in the plan, in display order."""
        return self.revenue + self.skill + self.maintenance

    @property
    def total_tasks(self) -> int:
        """How many tasks the plan contains."""
        return len(self.all_tasks)

    def tasks_for(self, category: Category) -> tuple[Task, ...]:
        """Tasks in ``category``. Unused plan categories return empty."""
        return tuple(task for task in self.all_tasks if task.category == category)


def normalize_goals(goals: list[str]) -> list[str]:
    """Clean a raw goal list: trim, drop blanks, de-duplicate.

    De-duplication is case- and whitespace-insensitive but preserves
    the first spelling the user gave, because that is the one they
    will recognize in their own plan.
    """
    seen: set[str] = set()
    cleaned: list[str] = []

    for goal in goals:
        if not isinstance(goal, str):
            raise ValueError(f"Goals must be strings, got {type(goal).__name__}")

        trimmed = " ".join(goal.split())
        if not trimmed:
            continue

        key = trimmed.casefold()
        if key in seen:
            continue

        seen.add(key)
        cleaned.append(trimmed)

    return cleaned


def generate_tasks(goals: list[str]) -> DailyPlan:
    """Generate a structured daily task plan from active goals.

    Each goal yields one revenue, one skill, and one maintenance task.

    Raises ``ValueError`` when more than ``MAX_ACTIVE_GOALS`` distinct
    goals are supplied. The previous behavior — slicing to the first
    three — meant a fourth goal contributed nothing and said nothing,
    which is the silent data loss ADR-002 exists to prevent. Refusing
    is also the honest answer: a day with five top priorities has none.

    An empty goal list yields an empty plan rather than raising; a day
    with nothing active is a real outcome (ADR-002, rule 5).
    """
    active = normalize_goals(goals)

    if len(active) > MAX_ACTIVE_GOALS:
        raise ValueError(
            f"{len(active)} active goals exceeds the daily maximum of {MAX_ACTIVE_GOALS}. "
            "Narrow your focus or park a goal before planning the day."
        )

    templates: dict[Category, str] = {
        Category.REVENUE: "Execute a direct revenue action for: {goal}",
        Category.SKILL: "Improve a skill related to: {goal}",
        Category.MAINTENANCE: "Stabilize your environment for: {goal}",
    }

    by_category = {
        category: tuple(
            Task(title=template.format(goal=goal), category=category) for goal in active
        )
        for category, template in templates.items()
    }

    return DailyPlan(
        revenue=by_category[Category.REVENUE],
        skill=by_category[Category.SKILL],
        maintenance=by_category[Category.MAINTENANCE],
    )
