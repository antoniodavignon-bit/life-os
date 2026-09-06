"""Command-line interface for Life OS.

This is the presentation layer ADR-002 keeps out of the domain modules:
all formatting, argument parsing, and terminal output lives here, so
`tasks`, `goals`, `profit`, and `review` stay pure and testable.

Only the commands that need persisted state load it (ADR-006).
``tasks`` stays a pure generator so it remains scriptable and reusable;
``today`` is the stateful command that closes the loop.

Usage:
    life-os today --goal "grow the store"
    life-os tasks --goal "grow the store" --goal "get in shape"
    life-os profit add 250 --note "Product sale"
    life-os profit report
    life-os goals plan --title "Launch Life OS" --start 2026-09-01
    life-os review log --done "..." --missed "..." --priority "..."
"""

import argparse
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from life_os.goals import Goal, current_milestone, generate_milestones
from life_os.review import (
    CARRY_WARNING_THRESHOLD,
    CarryForward,
    DailyReview,
    carried_forward,
    carry_forward,
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
from life_os.tasks import Category, Task, generate_tasks

REVIEW_WINDOW_DAYS = 7


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
        "today", help="carried work, today's plan, and your stated priority"
    )
    today_cmd.add_argument(
        "--goal",
        action="append",
        default=[],
        metavar="GOAL",
        help="an active goal (repeat for multiple goals)",
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
        "--done", action="append", default=[], metavar="TASK", help="a task you completed"
    )
    log_cmd.add_argument(
        "--missed", action="append", default=[], metavar="TASK", help="a task you did not finish"
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

    return parser


def _print_plan(plan) -> None:
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


def _print_carry(carry: CarryForward) -> None:
    """Render inherited work, loudly when there is too much of it."""
    if carry.is_empty:
        return

    if carry.is_overloaded:
        print(
            f"!  Carrying {carry.count} tasks from {carry.source_date} - "
            "you are behind, not planning fresh."
        )
        print(
            f"!  More than {CARRY_WARNING_THRESHOLD} carried is the signal to cut scope, "
            "not to add a goal."
        )
        print()

    print(f"CARRIED ({carry.count}) from {carry.source_date}")
    for task in carry.tasks:
        print(f"  - {task.title}")


def _run_tasks(args) -> int:
    plan = generate_tasks(args.goal)

    print("Today's plan")
    print("=" * 40)
    _print_plan(plan)
    print("\nCarried work is not shown here - run: life-os today")
    return 0


def _run_today(args) -> int:
    """The stateful view of the loop: what you owe, what you planned,
    and what you said mattered most."""
    state = load_state(args.state_file)
    today = date.today()

    carry = carried_forward(state.reviews, today)
    plan = generate_tasks(args.goal)

    print(f"{today:%A, %B %d}")
    print("=" * 46)

    _print_carry(carry)

    print("\nTODAY'S PLAN")
    if not args.goal:
        print("  (no active goals - add them with --goal)")
    _print_plan(plan)

    last = latest_review_before(state.reviews, today)
    if last is not None:
        print(f"\nYou said the priority was: {last.top_priority_tomorrow}")

    total = carry.count + plan.total_tasks
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


def _run_review(args) -> int:
    state = load_state(args.state_file)

    if args.review_command == "log":
        review = DailyReview(
            review_date=args.date or date.today(),
            completed=[Task(title=t, category=Category.UNSPECIFIED) for t in args.done],
            incomplete=[Task(title=t, category=Category.UNSPECIFIED) for t in args.missed],
            top_priority_tomorrow=args.priority,
            note=args.note,
        )
        reviews, replaced = upsert_review(state.reviews, review)
        save_state(AppState(profit=state.profit, reviews=reviews), args.state_file)

        rate = review.completion_rate * 100
        print(f"Review logged for {review.review_date}")
        if replaced is not None:
            was = replaced.completion_rate * 100
            print(
                f"  Replaced the previous review for this date "
                f"(was {len(replaced.completed)}/{replaced.total_tasks}, {was:.0f}%)."
            )
        print(f"  Completed: {len(review.completed)}/{review.total_tasks}  ({rate:.0f}%)")

        carried = carry_forward(review)
        if carried:
            print(f"\n  Carrying forward to tomorrow ({len(carried)}):")
            for task in carried:
                print(f"    - {task.title}")

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
        print('Log one with: life-os review log --done "..." --priority "..."')
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

    latest = recent[-1]
    carried = carry_forward(latest)
    if carried:
        print(f"\n  Still carrying forward from {latest.review_date}:")
        for task in carried:
            print(f"    - {task.title}")
    print(f"\n  Next up: {latest.top_priority_tomorrow}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "today": _run_today,
        "tasks": _run_tasks,
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
