"""Command-line interface for Life OS.

This is the presentation layer ADR-002 keeps out of the domain modules:
all formatting, argument parsing, and terminal output lives here, so
`tasks`, `goals`, `profit`, `review`, `commitments`, and `day` stay
pure and testable.

Only the commands that need persisted state load it (ADR-006).
``tasks`` stays a pure generator so it remains scriptable and reusable;
``today`` is the stateful command that starts the day — since ADR-008
it writes the day's plan rather than merely printing it, which is what
gives every item an id you can close.

Usage:
    life-os today --goal "grow the store"
    life-os today                      # reuses the goals you last planned with
    life-os today --replan --goal "..."
    life-os tasks --goal "grow the store" --goal "get in shape"
    life-os profit add 250 --note "Product sale"
    life-os profit report
    life-os goals plan --title "Launch Life OS" --start 2026-09-01
    life-os review log --priority "..."
    life-os open
    life-os done 7
    life-os drop 3
"""

import argparse
import sys
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from life_os import day as day_module
from life_os.commitments import (
    CARRY_WARNING_THRESHOLD,
    STALE_AFTER_DAYS,
    Commitment,
    CommitmentStatus,
    close_by_id,
    close_by_title,
    match_key,
    next_id,
    open_items,
    record_misses,
    stale_items,
)
from life_os.day import DayPlan, ItemStatus, PlanItem
from life_os.goals import Goal, current_milestone, generate_milestones
from life_os.review import (
    DailyReview,
    latest_review_before,
    summarize_week,
    upsert_review,
)
from life_os.storage import (
    DEFAULT_STATE_PATH,
    AppState,
    StorageError,
    load_state,
    save_state,
)
from life_os.tasks import PLAN_CATEGORIES, Category, Task, generate_tasks, normalize_goals

REVIEW_WINDOW_DAYS = 7

#: How a closed plan item is annotated in a listing.
_STATUS_NOTE = {
    ItemStatus.DONE: "  (done)",
    ItemStatus.DROPPED: "  (dropped)",
}

#: `done` and `drop` map onto both lists; these keep the pairing in one place.
_ITEM_STATUS_FOR = {
    CommitmentStatus.DONE: ItemStatus.DONE,
    CommitmentStatus.DROPPED: ItemStatus.DROPPED,
}


def _amount_arg(value: str) -> Decimal:
    """Parse a CLI money argument into a ``Decimal``.

    ``type=Decimal`` alone is not enough: ``Decimal("abc")`` raises
    ``InvalidOperation``, which is an ``ArithmeticError`` and not one
    of the exceptions argparse converts into a usage error, so the
    user would get a raw traceback. ``Decimal("NaN")`` is worse — it
    parses cleanly and poisons every total it touches.
    """
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not a valid amount") from exc

    if not parsed.is_finite():
        raise argparse.ArgumentTypeError(f"{value!r} is not a finite amount")

    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="life-os",
        description="A personal operating system for goals, execution, and review.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help=f"where Life OS stores its data (default: {DEFAULT_STATE_PATH})",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    today_cmd = subcommands.add_parser(
        "today", help="carried work, today's plan with ids, and your stated priority"
    )
    today_cmd.add_argument(
        "--goal",
        action="append",
        default=[],
        metavar="GOAL",
        help=(
            "an active goal (repeat for multiple goals; "
            "defaults to the goals you last planned with)"
        ),
    )
    today_cmd.add_argument(
        "--replan",
        action="store_true",
        help="rebuild today's plan from the given goals, keeping work already closed",
    )

    tasks_cmd = subcommands.add_parser("tasks", help="generate today's task plan")
    tasks_cmd.add_argument(
        "--goal",
        action="append",
        required=True,
        metavar="GOAL",
        help="an active goal (repeat for multiple goals)",
    )

    profit_cmd = subcommands.add_parser("profit", help="track income")
    profit_sub = profit_cmd.add_subparsers(dest="profit_command", required=True)

    add_cmd = profit_sub.add_parser("add", help="log an income entry")
    add_cmd.add_argument("amount", type=_amount_arg, help="amount earned")
    add_cmd.add_argument("--note", default="", help="what it was for")

    profit_sub.add_parser("report", help="show logged profit")

    goals_cmd = subcommands.add_parser("goals", help="plan a goal")
    goals_sub = goals_cmd.add_subparsers(dest="goals_command", required=True)

    plan_cmd = goals_sub.add_parser("plan", help="break a goal into weekly milestones")
    plan_cmd.add_argument("--title", required=True, help="what the goal is")
    plan_cmd.add_argument("--category", default="business", help="goal category")
    plan_cmd.add_argument(
        "--start",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="start date (default: today)",
    )
    plan_cmd.add_argument("--days", type=int, default=90, help="goal length in days")

    review_cmd = subcommands.add_parser("review", help="close out the day")
    review_sub = review_cmd.add_subparsers(dest="review_command", required=True)

    log_cmd = review_sub.add_parser("log", help="log an end-of-day review")
    log_cmd.add_argument(
        "--done",
        action="append",
        default=[],
        metavar="TASK",
        help="a task you completed (added to whatever today's plan already records)",
    )
    log_cmd.add_argument(
        "--missed",
        action="append",
        default=[],
        metavar="TASK",
        help="a task you did not finish (added to today's still-open plan items)",
    )
    log_cmd.add_argument("--priority", required=True, help="tomorrow's single most important task")
    log_cmd.add_argument("--note", default="", help="anything worth remembering")
    log_cmd.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="review date (default: today)",
    )

    review_sub.add_parser("week", help="show the last 7 days of reviews")

    subcommands.add_parser("open", help="list everything you still owe")

    done_cmd = subcommands.add_parser("done", help="close a plan item or an open commitment")
    done_cmd.add_argument("id", type=int, metavar="ID", help="the id from `today` or `open`")

    drop_cmd = subcommands.add_parser("drop", help="deliberately abandon a plan item or commitment")
    drop_cmd.add_argument("id", type=int, metavar="ID", help="the id from `today` or `open`")

    return parser


def _next_shared_id(state: AppState) -> int:
    """The next id in the space plan items and commitments share.

    One space so ``life-os done 4`` never has to ask which list the 4
    came from (ADR-008). Day plans are retained rather than pruned,
    which is what keeps this monotonic.
    """
    return max(next_id(state.commitments), day_module.max_item_id(state.day_plans) + 1)


def _still_open(plan: DayPlan | None, commitments: Iterable[Commitment]) -> int:
    """How much is outstanding, counted the way `open` displays it.

    Adding today's raw open items to the ledger double-counts every
    generated item that is already an open commitment — and on a day
    where the whole plan is carried work, that is every item on it.
    `done` and `drop` have to agree with `open`, or closing one thing
    appears to leave more behind than you started with.
    """
    outstanding = open_items(commitments)
    if plan is None:
        return len(outstanding)

    owed = {c.key for c in outstanding}
    return len(outstanding) + len(day_module.without_owed(plan, owed).open_items)


def _with_plan(state: AppState, plan: DayPlan) -> AppState:
    """State with ``plan`` stored, replacing any plan for its date."""
    return AppState(
        profit=state.profit,
        reviews=state.reviews,
        commitments=state.commitments,
        day_plans=day_module.upsert_plan(state.day_plans, plan),
    )


def _agree_with_review(plan: DayPlan, state: AppState, day: date):
    """Start a new plan from what a review for that date already says.

    Normally the plan comes first and the review reads it. The reverse
    order is possible — a review logged before the day was ever planned,
    which is every day in a state file written before ADR-008 — and
    without this the fresh plan would show that work as still open. The
    next `review log` would then replace an accurate review with an
    empty one and open commitments for work already reported done.

    Uses the same title matching as everything else, so a review entry
    typed by hand still settles the item it names.
    """
    review = next((r for r in state.reviews if r.review_date == day), None)
    if review is None:
        return plan, ()

    return day_module.close_items_by_title(plan, [t.title for t in review.completed], on=day)


def _print_plan(plan) -> None:
    """Render a pure ``DailyPlan`` from ``generate_tasks`` (no ids)."""
    for label, tasks in (
        ("REVENUE", plan.revenue),
        ("SKILL", plan.skill),
        ("MAINTENANCE", plan.maintenance),
    ):
        print(f"\n{label}")
        if not tasks:
            print("  (none)")
        for task in tasks:
            print(f"  - {task.title}")


def _print_item(item: PlanItem) -> None:
    print(f"  [{item.id}] {item.title}{_STATUS_NOTE.get(item.status, '')}")


def _print_day_plan(plan: DayPlan) -> None:
    """Render a persisted ``DayPlan``: ids, titles, and closed status."""
    for category in PLAN_CATEGORIES:
        items = plan.items_for(category)
        print(f"\n{category.value.upper()}")
        if not items:
            print("  (none)")
        for item in items:
            _print_item(item)


def _print_commitments(
    commitments: tuple[Commitment, ...], today: date, *, header: bool = True
) -> None:
    """Render what you still owe, oldest first, staleness inline.

    One list with one count rather than separate stale and fresh
    blocks: two counts that have to be added together is a worse
    answer to "how much do I owe" than one number.
    """
    if not commitments:
        return

    stale = {c.id for c in stale_items(commitments, today)}

    if len(commitments) > CARRY_WARNING_THRESHOLD:
        print(f"!  {len(commitments)} open commitments - you are behind, not planning fresh.")
        print(
            f"!  More than {CARRY_WARNING_THRESHOLD} open is the signal to cut scope, "
            "not to add a goal."
        )
        print()

    if header:
        print(f"CARRYING {len(commitments)} open commitment(s)")
    for c in commitments:
        age = c.age_days(today)
        days = "day" if age == 1 else "days"
        mark = f"  * stale {STALE_AFTER_DAYS}+ days, finish it or drop it" if c.id in stale else ""
        print(f"  [{c.id}] {c.title}  (carried {age} {days}){mark}")


def _run_tasks(args) -> int:
    plan = generate_tasks(args.goal)

    print("Today's plan")
    print("=" * 40)
    _print_plan(plan)
    print("\nCarried work is not shown here - run: life-os today")
    return 0


def _run_today(args) -> int:
    """The stateful view of the loop: what you owe, what you planned,
    and what you said mattered most.

    Since ADR-008 this also *writes*. The first run of a day builds the
    plan and gives every item an id; later runs show that same plan
    with whatever you have closed since.
    """
    state = load_state(args.state_file)
    today = date.today()

    existing = day_module.plan_for(state.day_plans, today)
    remembered = day_module.latest_goals(state.day_plans)
    goals = args.goal or list(remembered)
    note: str | None = None

    if existing is None:
        plan = day_module.build_plan(today, goals, first_id=_next_shared_id(state))
        plan, seeded = _agree_with_review(plan, state, today)
        state = _with_plan(state, plan)
        save_state(state, args.state_file)
        if seeded:
            note = f"{len(seeded)} item(s) start done: you already logged them in today's review."
        elif not args.goal and remembered:
            note = "Planned from the goals you last used. Override with --goal."
    elif args.replan:
        plan = day_module.replan(existing, goals, first_id=_next_shared_id(state))
        plan, _ = _agree_with_review(plan, state, today)
        state = _with_plan(state, plan)
        save_state(state, args.state_file)
        note = "Replanned today. Work you had already closed was kept."
    else:
        plan = existing
        given = tuple(normalize_goals(args.goal)) if args.goal else ()
        if given and given != plan.goals:
            note = (
                "Today's plan was already built from: "
                + ", ".join(plan.goals)
                + ".\n  Rebuild it from the goals you just gave with: life-os today --replan"
            )

    print(f"{today:%A, %B %d}")
    print("=" * 46)

    carried = open_items(state.commitments)
    _print_commitments(carried, today)

    # What is already owed is shown once, in the carried list, where it
    # has an age. The stored plan keeps every item either way.
    visible = day_module.without_owed(plan, {c.key for c in carried})

    print("\nTODAY'S PLAN")
    if not plan.items:
        print("  (no active goals - add them with --goal)")
    elif not visible.items:
        print("  (everything planned today is already in the carried list)")
    else:
        _print_day_plan(visible)

    if note:
        print(f"\n  {note}")

    last = latest_review_before(state.reviews, today)
    if last is not None:
        print(f"\nYou said the priority was: {last.top_priority_tomorrow}")

    still_open = visible.open_items
    if visible.items:
        rate = visible.completion_rate * 100
        dropped = len(visible.dropped_items)
        tail = f", {dropped} dropped" if dropped else ""
        print(
            f"\n{len(visible.done_items)} of {len(visible.done_items) + len(still_open)} done"
            f"{tail}  ({rate:.0f}%)"
        )
        print("Close one with: life-os done <id>    Abandon one with: life-os drop <id>")

    total = len(carried) + len(still_open)
    print(f"\n{total} things on the table today.")
    return 0


def _run_profit(args) -> int:
    state = load_state(args.state_file)

    if args.profit_command == "add":
        entry = state.profit.add_profit(args.amount, args.note, now=datetime.now())
        save_state(state, args.state_file)
        label = entry.note or "no note"
        print(f"Logged ${entry.amount:,.2f} - {label}")
        print(f"Total logged: ${state.profit.total:,.2f}")
        return 0

    # report
    if not state.profit.entries:
        print("No profit logged yet.")
        print('Add one with: life-os profit add 250 --note "Product sale"')
        return 0

    print("Profit log")
    print("=" * 40)
    for entry in state.profit.entries:
        stamp = entry.timestamp.strftime("%Y-%m-%d %H:%M")
        print(f"  {stamp}  ${entry.amount:>10,.2f}  {entry.note or '-'}")
    print("=" * 40)
    print(f"Total: ${state.profit.total:,.2f} across {len(state.profit.entries)} entries")
    return 0


def _run_goals(args) -> int:
    start = args.start or date.today()
    goal = Goal(
        title=args.title,
        category=args.category,
        start_date=start,
        duration_days=args.days,
    )
    milestones = generate_milestones(goal)
    active = current_milestone(goal, date.today())

    print(f"{goal.title}  [{goal.category}]")
    print(f"{goal.start_date} to {goal.end_date}  ({goal.duration_days} days)")
    print("=" * 46)
    for milestone in milestones:
        marker = " <- current" if active and milestone.week_number == active.week_number else ""
        print(
            f"  Week {milestone.week_number:>2}  "
            f"{milestone.start_date} to {milestone.end_date}{marker}"
        )
    return 0


def _merge_titles(explicit: list[str], derived: tuple[str, ...]) -> list[str]:
    """Explicit titles first, then derived ones not already named.

    Matching is by ``match_key``, so retyping a plan item with
    different capitalisation adds nothing rather than duplicating it.
    """
    merged: list[str] = []
    seen: set[str] = set()

    for title in list(explicit) + list(derived):
        key = match_key(title)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(title)

    return merged


def _run_review(args) -> int:
    state = load_state(args.state_file)

    if args.review_command == "log":
        review_date = args.date or date.today()
        plan = day_module.plan_for(state.day_plans, review_date)
        day_plans = state.day_plans
        categories: dict[str, Category] = {}

        done_titles = list(args.done)
        missed_titles = list(args.missed)
        counted = plan

        if plan is not None:
            # An explicit --done settles the plan item it names before
            # the day's outcome is read, so the two cannot disagree.
            plan, _ = day_module.close_items_by_title(plan, args.done, on=review_date)
            day_plans = day_module.upsert_plan(day_plans, plan)
            categories = {item.key: item.category for item in plan.items}

            # Count the day the user was actually shown. `today` and
            # `open` hide an open plan item that is already an open
            # commitment, because the carried copy is the one with an
            # age. Reading the raw plan here would record that same
            # obligation as missed on a second day, double-count it in
            # `review week`, and report a completion rate that
            # contradicts the screen. The stored plan keeps every item
            # either way; this is the view, not the data.
            #
            # Strictly *before* the review date, and that matters: a
            # commitment opened on this date was opened by an earlier
            # run of this same review. Excluding those would let a
            # correction shrink its own denominator — log 1 of 3, fix
            # it, and the day silently becomes 2 of 2. Only work
            # carried in from a previous day is already accounted for.
            # `latest_review_before` compares strictly for the same
            # kind of reason (ADR-006).
            owed = {c.key for c in open_items(state.commitments) if c.opened_on < review_date}
            counted = day_module.without_owed(plan, owed)

            derived_done, derived_missed = day_module.outcome(counted)
            done_titles = _merge_titles(args.done, derived_done)
            missed_titles = _merge_titles(args.missed, derived_missed)

            # Anything reported done wins over a stale open item.
            done_keys = {match_key(t) for t in done_titles}
            missed_titles = [t for t in missed_titles if match_key(t) not in done_keys]

        def _as_task(title: str) -> Task:
            category = categories.get(match_key(title), Category.UNSPECIFIED)
            return Task(title=title, category=category)

        review = DailyReview(
            review_date=review_date,
            completed=[_as_task(t) for t in done_titles],
            incomplete=[_as_task(t) for t in missed_titles],
            top_priority_tomorrow=args.priority,
            note=args.note,
        )
        reviews, replaced = upsert_review(state.reviews, review)

        # Close first, then open: work reported done settles the
        # commitment it belonged to before today's misses are recorded.
        ledger, closed = close_by_title(state.commitments, done_titles, on=review.review_date)
        ledger, opened = record_misses(
            ledger,
            missed_titles,
            on=review.review_date,
            first_id=_next_shared_id(state),
        )

        save_state(
            AppState(
                profit=state.profit,
                reviews=reviews,
                commitments=ledger,
                day_plans=day_plans,
            ),
            args.state_file,
        )

        rate = review.completion_rate * 100
        print(f"Review logged for {review.review_date}")
        if replaced is not None:
            was = replaced.completion_rate * 100
            print(
                f"  Replaced the previous review for this date "
                f"(was {len(replaced.completed)}/{replaced.total_tasks}, {was:.0f}%)."
            )
        if counted is not None:
            dropped = len(counted.dropped_items)
            tail = f", {dropped} dropped and not counted" if dropped else ""
            print(f"  Read from today's plan: {len(counted.done_items)} done{tail}.")
        print(f"  Completed: {len(review.completed)}/{review.total_tasks}  ({rate:.0f}%)")

        if closed:
            print(f"\n  Closed {len(closed)} commitment(s):")
            for c in closed:
                age = c.age_days(review.review_date)
                print(f"    [{c.id}] {c.title}  (carried {age} days)")

        if opened:
            print(f"\n  Opened {len(opened)} new commitment(s):")
            for c in opened:
                print(f"    [{c.id}] {c.title}")

        outstanding = open_items(ledger)
        if outstanding:
            print(f"\n  {len(outstanding)} still open. See them with: life-os open")

        print(f"\n  Tomorrow's #1: {review.top_priority_tomorrow}")
        return 0

    # week
    cutoff = date.today() - timedelta(days=REVIEW_WINDOW_DAYS - 1)
    recent = sorted(
        (r for r in state.reviews if r.review_date >= cutoff),
        key=lambda r: r.review_date,
    )

    if not recent:
        print(f"No reviews logged in the last {REVIEW_WINDOW_DAYS} days.")
        print('Log one with: life-os review log --priority "..."')
        return 0

    summary = summarize_week(recent)

    print(f"Last {REVIEW_WINDOW_DAYS} days")
    print("=" * 46)
    for review in recent:
        rate = review.completion_rate * 100
        print(
            f"  {review.review_date}  "
            f"{len(review.completed)}/{review.total_tasks} done  ({rate:>3.0f}%)"
        )
    print("=" * 46)
    print(
        f"  {summary.reviews_logged} reviews  |  "
        f"{summary.tasks_completed} completed  |  "
        f"{summary.tasks_missed} missed  |  "
        f"{summary.completion_rate * 100:.0f}% completion"
    )

    outstanding = open_items(state.commitments)
    if outstanding:
        print(f"\n  {len(outstanding)} still open. See them with: life-os open")
    print(f"\n  Next up: {recent[-1].top_priority_tomorrow}")
    return 0


def _run_open(args) -> int:
    state = load_state(args.state_file)
    today = date.today()

    outstanding = open_items(state.commitments)
    plan = day_module.plan_for(state.day_plans, today)
    owed = {c.key for c in outstanding}
    plan_open = day_module.without_owed(plan, owed).open_items if plan is not None else ()

    if not outstanding and not plan_open:
        if plan is not None and plan.items:
            print("Today's plan is clear and nothing is carried over.")
        else:
            print("Nothing outstanding. Everything you logged as missed has been closed.")
        return 0

    total = len(outstanding) + len(plan_open)
    print(f"Open ({total})")
    print("=" * 46)

    if plan_open:
        print(f"TODAY'S PLAN - {len(plan_open)} open")
        for item in plan_open:
            _print_item(item)
        if outstanding:
            print()

    _print_commitments(outstanding, today)

    print("\nClose one with: life-os done <id>    Abandon one with: life-os drop <id>")
    return 0


def _close_commitment(args, status: CommitmentStatus, verb: str) -> int:
    state = load_state(args.state_file)
    today = date.today()

    plan = day_module.plan_for(state.day_plans, today)

    if plan is not None and plan.find(args.id) is not None:
        new_plan, closed_item = day_module.close_item(
            plan, args.id, on=today, status=_ITEM_STATUS_FOR[status]
        )
        state = _with_plan(state, new_plan)
        save_state(state, args.state_file)

        print(f"{verb} [{closed_item.id}] {closed_item.title}")
        remaining = _still_open(new_plan, state.commitments)
        print(f"{remaining} still open." if remaining else "Nothing left outstanding.")
        return 0

    # Not on today's plan. An id from an earlier day is a likely typo
    # worth naming, rather than reporting it as an unknown commitment.
    if any(p.find(args.id) is not None for p in state.day_plans):
        raise ValueError(
            f"Plan item {args.id} belongs to an earlier day and can no longer be closed. "
            "Run `life-os today` for today's ids."
        )

    ledger, closed = close_by_id(state.commitments, args.id, on=today, status=status)
    save_state(
        AppState(
            profit=state.profit,
            reviews=state.reviews,
            commitments=ledger,
            day_plans=state.day_plans,
        ),
        args.state_file,
    )

    age = closed.age_days(today)
    days = "day" if age == 1 else "days"
    print(f"{verb} [{closed.id}] {closed.title}  (carried {age} {days})")

    remaining = _still_open(plan, ledger)
    print(f"{remaining} still open." if remaining else "Nothing left outstanding.")
    return 0


def _run_done(args) -> int:
    return _close_commitment(args, CommitmentStatus.DONE, "Done:")


def _run_drop(args) -> int:
    return _close_commitment(args, CommitmentStatus.DROPPED, "Dropped:")


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "today": _run_today,
        "tasks": _run_tasks,
        "open": _run_open,
        "done": _run_done,
        "drop": _run_drop,
        "profit": _run_profit,
        "goals": _run_goals,
        "review": _run_review,
    }

    try:
        return handlers[args.command](args)
    except (ValueError, StorageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        # Backstop. storage.py wraps its own filesystem failures, but a
        # raw OSError from anywhere else should still be a clean error
        # rather than a traceback in someone's terminal.
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
