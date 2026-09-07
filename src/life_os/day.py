"""Day Plan — Module 6 of Life OS.

The day in flight. ``tasks`` generates a plan, ``review`` records how a
day ended, and ``commitments`` tracks what outlived it — but nothing
held the hours in between. Nine generated tasks were printed and
forgotten, so finishing one at 11am could not be stated until the
end-of-day review, by retyping its title from memory.

This module holds that middle. A ``Task`` is a value: the pure output
of ``generate_tasks``, the same on any day from the same goals. A
``PlanItem`` is that value admitted into a specific day, where it gains
an id you can type, a status, and a date it closed. See ADR-008.

A ``PlanItem`` is deliberately *not* a ``Commitment``. A commitment is
an obligation you failed to meet, which is what makes its age and the
staleness threshold mean anything. Today's fresh plan is not owed yet.
Unfinished plan items become commitments at review time and not before.

``match_key`` and ``normalize_title`` are imported from ``commitments``
rather than reimplemented: they are pure text helpers, and two copies
of "when are two titles the same thing" would drift. ``ItemStatus`` is
defined here rather than shared, because the vocabulary matching is a
coincidence — a plan item's ``DONE`` is a fact about one day, and a
commitment's is the end of an obligation that outlived several.

Follows ADR-002: frozen dataclasses, pure functions, no I/O, injectable
clock (``on=``), validation at construction, and no mutable internal
state handed to callers.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from life_os.commitments import match_key, normalize_title
from life_os.tasks import Category, generate_tasks, normalize_goals


class ItemStatus(StrEnum):
    """Where a planned item ended up.

    ``DROPPED`` is a decision, not a failure. A dropped item is
    excluded from the day's review entirely rather than counted as
    missed — recording it as missed would reopen it as a commitment
    that night and quietly overturn the decision to drop it.
    """

    OPEN = "open"
    DONE = "done"
    DROPPED = "dropped"


@dataclass(frozen=True)
class PlanItem:
    """One task admitted into a specific day.

    ``id`` is a small integer drawn from the same space as commitment
    ids, so ``life-os done 4`` means exactly one thing regardless of
    which list the 4 came from (ADR-008).
    """

    id: int
    title: str
    category: Category
    status: ItemStatus = ItemStatus.OPEN
    closed_on: date | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, int) or isinstance(self.id, bool) or self.id < 1:
            raise ValueError(f"PlanItem id must be a positive integer, got {self.id!r}")

        title = normalize_title(self.title)
        if not title:
            raise ValueError("PlanItem title must not be empty")

        try:
            category = Category(self.category)
        except ValueError as exc:
            known = ", ".join(c.value for c in Category)
            raise ValueError(
                f"Unknown task category {self.category!r} (expected one of: {known})"
            ) from exc

        try:
            status = ItemStatus(self.status)
        except ValueError as exc:
            known = ", ".join(s.value for s in ItemStatus)
            raise ValueError(
                f"Unknown plan item status {self.status!r} (expected one of: {known})"
            ) from exc

        if status is ItemStatus.OPEN and self.closed_on is not None:
            raise ValueError("An open plan item cannot have a closed_on date")
        if status is not ItemStatus.OPEN:
            if self.closed_on is None:
                raise ValueError(f"A {status.value} plan item must have a closed_on date")
            if not isinstance(self.closed_on, date):
                raise ValueError("closed_on must be a date")

        object.__setattr__(self, "title", title)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "status", status)

    @property
    def is_open(self) -> bool:
        """Whether this item is still outstanding today."""
        return self.status is ItemStatus.OPEN

    @property
    def key(self) -> str:
        """The title key two items are considered the same work under."""
        return match_key(self.title)

    def closed(self, status: ItemStatus, on: date) -> "PlanItem":
        """Return a closed copy. Raises if this is already closed."""
        if not self.is_open:
            raise ValueError(f"Plan item {self.id} is already {self.status.value}")
        if status is ItemStatus.OPEN:
            raise ValueError("Closing a plan item requires a terminal status")

        return PlanItem(
            id=self.id,
            title=self.title,
            category=self.category,
            status=status,
            closed_on=on,
        )


@dataclass(frozen=True)
class DayPlan:
    """The set of items planned for one date, and their live status.

    ``goals`` is recorded so the plan is reproducible and so tomorrow
    can default to today's active goals without a second store to keep
    in sync (ADR-008).
    """

    plan_date: date
    goals: tuple[str, ...]
    items: tuple[PlanItem, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.plan_date, date):
            raise ValueError(f"plan_date must be a date, got {type(self.plan_date).__name__}")

        items = tuple(self.items)
        ids = [item.id for item in items]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            listed = ", ".join(str(i) for i in sorted(duplicates))
            raise ValueError(f"Plan item ids must be unique within a day, saw {listed} twice")

        object.__setattr__(self, "goals", tuple(self.goals))
        object.__setattr__(self, "items", items)

    @property
    def open_items(self) -> tuple[PlanItem, ...]:
        """Items still outstanding, in plan order."""
        return tuple(i for i in self.items if i.is_open)

    @property
    def done_items(self) -> tuple[PlanItem, ...]:
        """Items closed as done, in plan order."""
        return tuple(i for i in self.items if i.status is ItemStatus.DONE)

    @property
    def dropped_items(self) -> tuple[PlanItem, ...]:
        """Items deliberately abandoned, in plan order."""
        return tuple(i for i in self.items if i.status is ItemStatus.DROPPED)

    @property
    def total_items(self) -> int:
        """How many items the plan contains, including dropped ones."""
        return len(self.items)

    @property
    def completion_rate(self) -> float:
        """Done over done-plus-open, 0.0 through 1.0.

        Dropped items are excluded from both halves: deciding something
        no longer matters should not score as a loss, and it is not a
        win either. A plan of nothing but dropped items scores 0.0
        rather than dividing by zero.
        """
        counted = len(self.done_items) + len(self.open_items)
        if counted == 0:
            return 0.0
        return len(self.done_items) / counted

    def items_for(self, category: Category) -> tuple[PlanItem, ...]:
        """Items in ``category``, in plan order."""
        return tuple(i for i in self.items if i.category == category)

    def find(self, item_id: int) -> PlanItem | None:
        """The item with this id, or ``None``."""
        return next((i for i in self.items if i.id == item_id), None)


def build_plan(plan_date: date, goals: list[str], *, first_id: int) -> DayPlan:
    """Generate a day's plan and give every item an id.

    Ids are assigned in display order (revenue, then skill, then
    maintenance) starting at ``first_id``, which the caller derives
    from the whole id space so plan items and commitments never
    collide.

    Raises ``ValueError`` for more than ``MAX_ACTIVE_GOALS`` goals —
    the refusal comes from ``generate_tasks`` and is not softened here.
    An empty goal list yields an empty plan.
    """
    if first_id < 1:
        raise ValueError(f"first_id must be a positive integer, got {first_id!r}")

    plan = generate_tasks(goals)
    items = tuple(
        PlanItem(id=first_id + offset, title=task.title, category=task.category)
        for offset, task in enumerate(plan.all_tasks)
    )

    return DayPlan(plan_date=plan_date, goals=tuple(normalize_goals(goals)), items=items)


def replan(existing: DayPlan, goals: list[str], *, first_id: int) -> DayPlan:
    """Rebuild a day from new goals without discarding recorded work.

    Items whose titles survive the rebuild keep their id and status, so
    a goal change at noon does not erase the morning. Closed items
    whose titles do *not* survive are kept as well: they record what
    was actually done that day, and dropping them to tidy the list
    would delete the user's history to make the display neater.

    Only genuinely new titles draw fresh ids.
    """
    rebuilt = build_plan(existing.plan_date, goals, first_id=first_id)

    by_key = {item.key: item for item in existing.items}
    carried: list[PlanItem] = []
    next_id = first_id

    for item in rebuilt.items:
        previous = by_key.get(item.key)
        if previous is not None:
            carried.append(previous)
        else:
            carried.append(
                PlanItem(id=next_id, title=item.title, category=item.category)
            )
            next_id += 1

    surviving = {item.key for item in rebuilt.items}
    orphaned_but_recorded = tuple(
        item for item in existing.items if item.key not in surviving and not item.is_open
    )

    return DayPlan(
        plan_date=existing.plan_date,
        goals=rebuilt.goals,
        items=tuple(carried) + orphaned_but_recorded,
    )


def max_item_id(plans: Iterable[DayPlan]) -> int:
    """The highest plan item id in use, or 0 when there are none.

    Callers combine this with the commitment ledger's maximum to get
    the next id in the shared space (ADR-008). Day plans are retained
    rather than pruned, which is what keeps this monotonic.
    """
    return max((item.id for plan in plans for item in plan.items), default=0)


def plan_for(plans: Iterable[DayPlan], day: date) -> DayPlan | None:
    """The plan for ``day``, or ``None`` if that day was never planned."""
    return next((p for p in plans if p.plan_date == day), None)


def upsert_plan(plans: Iterable[DayPlan], plan: DayPlan) -> tuple[DayPlan, ...]:
    """Insert ``plan``, replacing any existing plan for its date.

    Returns the new collection sorted by date. A date has one plan, for
    the same reason a date has one review (ADR-006).
    """
    kept = [p for p in plans if p.plan_date != plan.plan_date]
    kept.append(plan)
    return tuple(sorted(kept, key=lambda p: p.plan_date))


def latest_plan(plans: Iterable[DayPlan]) -> DayPlan | None:
    """The most recent plan by date, or ``None`` when none exist."""
    ordered = sorted(plans, key=lambda p: p.plan_date)
    return ordered[-1] if ordered else None


def latest_goals(plans: Iterable[DayPlan]) -> tuple[str, ...]:
    """The goals from the most recent plan, or empty when none exist.

    This is how active goals persist: the plan already has to record
    what generated it, so remembering goals is a property of a decision
    already made rather than a second store to keep in sync (ADR-008).
    """
    latest = latest_plan(plans)
    return latest.goals if latest is not None else ()


def without_owed(plan: DayPlan, owed_keys: Iterable[str]) -> DayPlan:
    """The plan minus open items that are already open commitments.

    Generated titles repeat: plan for the same goal two days running
    and the second day's items are word-for-word the first day's. Once
    an item has been missed it is a commitment with an age, and showing
    the freshly generated twin beside it lists one obligation twice and
    inflates every count that touches it.

    Closed items are always kept — they are what the day actually
    recorded, and hiding them would erase work to tidy a list. The
    stored plan is untouched; this is the view, not the data.
    """
    keys = set(owed_keys)
    items = tuple(i for i in plan.items if not (i.is_open and i.key in keys))
    return DayPlan(plan_date=plan.plan_date, goals=plan.goals, items=items)


def close_item(
    plan: DayPlan, item_id: int, *, on: date, status: ItemStatus = ItemStatus.DONE
) -> tuple[DayPlan, PlanItem]:
    """Close one item by id.

    Raises ``ValueError`` for an unknown id or one already closed —
    the same contract as ``commitments.close_by_id``, so ``done`` and
    ``drop`` behave identically whichever list the id came from.
    """
    target = plan.find(item_id)
    if target is None:
        raise ValueError(f"No plan item with id {item_id}")

    closed_item = target.closed(status, on)
    items = tuple(closed_item if i.id == item_id else i for i in plan.items)

    return DayPlan(plan_date=plan.plan_date, goals=plan.goals, items=items), closed_item


def close_items_by_title(
    plan: DayPlan,
    titles: Iterable[str],
    *,
    on: date,
    status: ItemStatus = ItemStatus.DONE,
) -> tuple[DayPlan, tuple[PlanItem, ...]]:
    """Close open items whose titles match any of ``titles``.

    Titles matching nothing open are ignored: reporting work that was
    never on the plan is the normal case, not an error. This is what
    lets an explicit ``review log --done "..."`` settle the plan item
    it names as well as the commitment ledger.
    """
    wanted = {match_key(t) for t in titles if normalize_title(t)}
    if not wanted:
        return plan, ()

    items: list[PlanItem] = []
    closed: list[PlanItem] = []

    for item in plan.items:
        if item.is_open and item.key in wanted:
            closed_item = item.closed(status, on)
            items.append(closed_item)
            closed.append(closed_item)
        else:
            items.append(item)

    return DayPlan(plan_date=plan.plan_date, goals=plan.goals, items=tuple(items)), tuple(closed)


def outcome(plan: DayPlan) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The day's ``(done_titles, missed_titles)`` for the review.

    Dropped items appear in neither. A dropped item recorded as missed
    would be reopened as a commitment that night, silently reversing
    the decision to drop it (ADR-008).
    """
    return (
        tuple(i.title for i in plan.done_items),
        tuple(i.title for i in plan.open_items),
    )
