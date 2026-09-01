"""Command-line interface for Life OS.

This is the presentation layer ADR-002 keeps out of the domain modules:
all formatting, argument parsing, and terminal output lives here, so
`tasks`, `goals`, `profit`, and `review` stay pure and testable.

Usage:
    life-os tasks --goal "grow the store" --goal "get in shape"
    life-os profit add 250 --note "Product sale"
    life-os profit report
    life-os goals plan --title "Launch Life OS" --start 2026-09-01
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from life_os.goals import Goal, current_milestone, generate_milestones
from life_os.storage import (
    DEFAULT_STATE_PATH,
    StorageError,
    load_state,
    save_state,
)
from life_os.tasks import generate_tasks


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
    add_cmd.add_argument("amount", type=float, help="amount earned")
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

    return parser


def _run_tasks(args) -> int:
    plan = generate_tasks(args.goal)

    print("Today's plan")
    print("=" * 40)
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
        print(f"Add one with: life-os profit add 250 --note \"Product sale\"")
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


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "tasks": _run_tasks,
        "profit": _run_profit,
        "goals": _run_goals,
    }

    try:
        return handlers[args.command](args)
    except (ValueError, StorageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
