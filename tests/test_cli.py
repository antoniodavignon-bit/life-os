import json
import re
from datetime import date, timedelta

import pytest

from life_os.cli import main
from life_os.commitments import CARRY_WARNING_THRESHOLD, STALE_AFTER_DAYS
from life_os.day import build_plan
from life_os.profit import ProfitTracker
from life_os.storage import AppState, load_state, save_state


def _run(capsys, argv):
    """Run the CLI and return (exit_code, stdout, stderr)."""
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_tasks_prints_all_three_categories(capsys):
    code, out, _ = _run(capsys, ["tasks", "--goal", "grow the store"])

    assert code == 0
    assert "REVENUE" in out
    assert "SKILL" in out
    assert "MAINTENANCE" in out
    assert "grow the store" in out


def test_profit_report_is_friendly_on_first_run(tmp_path, capsys):
    state = tmp_path / "state.json"

    code, out, _ = _run(capsys, ["--state-file", str(state), "profit", "report"])

    assert code == 0
    assert "No profit logged yet" in out


def test_profit_add_persists_across_invocations(tmp_path, capsys):
    state = tmp_path / "state.json"

    code, _, _ = _run(
        capsys,
        ["--state-file", str(state), "profit", "add", "250", "--note", "Sale"],
    )
    assert code == 0

    code, _, _ = _run(capsys, ["--state-file", str(state), "profit", "add", "100"])
    assert code == 0

    # A completely separate invocation must see both entries.
    code, out, _ = _run(capsys, ["--state-file", str(state), "profit", "report"])

    assert code == 0
    assert "350.00" in out
    assert "Sale" in out
    assert "2 entries" in out


def test_profit_add_rejects_negative_amount_with_exit_code_1(tmp_path, capsys):
    state = tmp_path / "state.json"

    code, _, err = _run(capsys, ["--state-file", str(state), "profit", "add", "-50"])

    assert code == 1
    assert "error:" in err


def test_corrupt_state_file_reports_error_not_traceback(tmp_path, capsys):
    state = tmp_path / "state.json"
    state.write_text("{broken", encoding="utf-8")

    code, _, err = _run(capsys, ["--state-file", str(state), "profit", "report"])

    assert code == 1
    assert "error:" in err


def test_goals_plan_lists_weekly_milestones(capsys):
    code, out, _ = _run(
        capsys,
        ["goals", "plan", "--title", "Launch Life OS", "--start", "2026-09-01"],
    )

    assert code == 0
    assert "Launch Life OS" in out
    assert "Week  1" in out
    assert "Week 13" in out


def test_goals_plan_rejects_zero_day_goal(capsys):
    code, _, err = _run(
        capsys,
        ["goals", "plan", "--title", "Bad", "--start", "2026-09-01", "--days", "0"],
    )

    assert code == 1
    assert "error:" in err


def test_missing_subcommand_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])

    assert exc.value.code != 0


def test_review_log_records_and_reports_carry_forward(tmp_path, capsys):
    state = tmp_path / "state.json"

    code, out, _ = _run(
        capsys,
        [
            "--state-file",
            str(state),
            "review",
            "log",
            "--done",
            "posted content",
            "--done",
            "called supplier",
            "--missed",
            "wrote email sequence",
            "--priority",
            "ship the landing page",
        ],
    )

    assert code == 0
    assert "2/3" in out
    assert "67%" in out
    assert "wrote email sequence" in out
    assert "ship the landing page" in out


def test_review_log_requires_a_priority(tmp_path, capsys):
    state = tmp_path / "state.json"

    with pytest.raises(SystemExit):
        main(["--state-file", str(state), "review", "log", "--done", "something"])


def test_review_log_rejects_an_empty_priority(tmp_path, capsys):
    state = tmp_path / "state.json"

    code, _, err = _run(
        capsys,
        ["--state-file", str(state), "review", "log", "--priority", "   "],
    )

    assert code == 1
    assert "error:" in err


def test_review_week_is_friendly_when_nothing_logged(tmp_path, capsys):
    state = tmp_path / "state.json"

    code, out, _ = _run(capsys, ["--state-file", str(state), "review", "week"])

    assert code == 0
    assert "No reviews logged" in out


def test_review_week_aggregates_across_invocations(tmp_path, capsys):
    state = tmp_path / "state.json"

    _run(
        capsys,
        [
            "--state-file",
            str(state),
            "review",
            "log",
            "--done",
            "a",
            "--done",
            "b",
            "--missed",
            "c",
            "--priority",
            "first priority",
            "--date",
            str(date.today() - timedelta(days=1)),
        ],
    )
    _run(
        capsys,
        [
            "--state-file",
            str(state),
            "review",
            "log",
            "--done",
            "d",
            "--missed",
            "e",
            "--priority",
            "second priority",
        ],
    )

    code, out, _ = _run(capsys, ["--state-file", str(state), "review", "week"])

    assert code == 0
    assert "2 reviews" in out
    assert "3 completed" in out
    assert "2 missed" in out
    assert "second priority" in out


def test_review_week_ignores_reviews_older_than_the_window(tmp_path, capsys):
    state = tmp_path / "state.json"
    old = (date.today() - timedelta(days=30)).isoformat()

    _run(
        capsys,
        [
            "--state-file",
            str(state),
            "review",
            "log",
            "--done",
            "ancient task",
            "--priority",
            "old priority",
            "--date",
            old,
        ],
    )

    code, out, _ = _run(capsys, ["--state-file", str(state), "review", "week"])

    assert code == 0
    assert "No reviews logged" in out
    assert "ancient task" not in out


def test_tasks_refuses_more_goals_than_the_daily_maximum(capsys):
    code, _, err = _run(
        capsys,
        ["tasks", "--goal", "a", "--goal", "b", "--goal", "c", "--goal", "d"],
    )

    assert code == 1
    assert "exceeds the daily maximum" in err


def test_profit_totals_stay_exact_across_the_cli(tmp_path, capsys):
    state = tmp_path / "state.json"
    for _ in range(3):
        _run(capsys, ["--state-file", str(state), "profit", "add", "0.10"])

    code, out, _ = _run(capsys, ["--state-file", str(state), "profit", "report"])

    assert code == 0
    assert "Total: $0.30" in out


def test_profit_add_rejects_a_non_numeric_amount(tmp_path, capsys):
    state = tmp_path / "state.json"

    with pytest.raises(SystemExit) as exc:
        _run(capsys, ["--state-file", str(state), "profit", "add", "lots"])

    assert exc.value.code == 2


def test_profit_add_rejects_nan(tmp_path, capsys):
    """Decimal('NaN') parses cleanly and poisons every total it enters."""
    state = tmp_path / "state.json"

    with pytest.raises(SystemExit) as exc:
        _run(capsys, ["--state-file", str(state), "profit", "add", "NaN"])

    assert exc.value.code == 2


def test_review_log_twice_in_a_day_corrects_instead_of_double_counting(tmp_path, capsys):
    """A day has one review. Appending a second reported a completion
    rate that was arithmetically fine and factually wrong."""
    state = tmp_path / "state.json"
    base = ["--state-file", str(state), "review", "log"]

    _run(capsys, [*base, "--done", "a", "--missed", "b", "--priority", "first"])
    code, out, _ = _run(capsys, [*base, "--done", "a", "--done", "b", "--priority", "corrected"])

    assert code == 0
    assert "Replaced the previous review for this date" in out
    assert "1/2" in out

    code, out, _ = _run(capsys, ["--state-file", str(state), "review", "week"])

    assert "1 reviews" in out
    assert "2 completed" in out
    assert "0 missed" in out
    assert "corrected" in out


def test_today_carries_yesterdays_misses_into_the_plan(tmp_path, capsys):
    state = tmp_path / "state.json"
    _run(
        capsys,
        [
            "--state-file",
            str(state),
            "review",
            "log",
            "--done",
            "posted content",
            "--missed",
            "wrote the email sequence",
            "--priority",
            "ship the landing page",
            "--date",
            str(date.today() - timedelta(days=1)),
        ],
    )

    code, out, _ = _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    assert code == 0
    assert "CARRYING 1 open commitment(s)" in out
    assert "wrote the email sequence" in out
    assert "Execute a direct revenue action for: grow the store" in out
    assert "ship the landing page" in out
    assert "4 things on the table today" in out


def test_a_commitment_opened_today_is_shown_as_open_the_same_day(tmp_path, capsys):
    """The ledger answers "what do I still owe", not "what did I
    inherit" - so work missed this morning is open this afternoon
    (ADR-007). Mission 006's strict carry could not express this."""
    state = tmp_path / "state.json"
    _run(
        capsys,
        [
            "--state-file",
            str(state),
            "review",
            "log",
            "--missed",
            "todays own miss",
            "--priority",
            "keep going",
        ],
    )

    code, out, _ = _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    assert code == 0
    assert "todays own miss" in out
    assert "carried 0 days" in out


def test_today_warns_when_the_carried_pile_is_too_big(tmp_path, capsys):
    state = tmp_path / "state.json"
    missed = []
    for i in range(CARRY_WARNING_THRESHOLD + 1):
        missed += ["--missed", f"missed {i}"]

    _run(
        capsys,
        [
            "--state-file",
            str(state),
            "review",
            "log",
            *missed,
            "--priority",
            "dig out",
            "--date",
            str(date.today() - timedelta(days=1)),
        ],
    )

    code, out, _ = _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    assert code == 0
    assert "you are behind, not planning fresh" in out


def test_today_does_not_warn_at_the_threshold(tmp_path, capsys):
    state = tmp_path / "state.json"
    missed = []
    for i in range(CARRY_WARNING_THRESHOLD):
        missed += ["--missed", f"missed {i}"]

    _run(
        capsys,
        [
            "--state-file",
            str(state),
            "review",
            "log",
            *missed,
            "--priority",
            "steady",
            "--date",
            str(date.today() - timedelta(days=1)),
        ],
    )

    _, out, _ = _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    assert "you are behind" not in out
    assert f"CARRYING {CARRY_WARNING_THRESHOLD} open commitment(s)" in out


def test_today_is_friendly_on_a_first_run(tmp_path, capsys):
    state = tmp_path / "state.json"

    code, out, _ = _run(capsys, ["--state-file", str(state), "today"])

    assert code == 0
    assert "CARRYING" not in out
    assert "no active goals" in out


def test_carried_work_does_not_count_against_the_goal_limit(tmp_path, capsys):
    """Finishing badly must not shrink tomorrow's capacity (ADR-006)."""
    state = tmp_path / "state.json"
    missed = []
    for i in range(5):
        missed += ["--missed", f"missed {i}"]

    _run(
        capsys,
        [
            "--state-file",
            str(state),
            "review",
            "log",
            *missed,
            "--priority",
            "dig out",
            "--date",
            str(date.today() - timedelta(days=1)),
        ],
    )

    code, out, _ = _run(
        capsys,
        ["--state-file", str(state), "today", "--goal", "a", "--goal", "b", "--goal", "c"],
    )

    assert code == 0
    assert "exceeds the daily maximum" not in out


def test_tasks_points_at_today_for_carried_work(capsys):
    code, out, _ = _run(capsys, ["tasks", "--goal", "grow the store"])

    assert code == 0
    assert "life-os today" in out


def test_unwritable_state_file_reports_an_error_not_a_traceback(tmp_path, capsys):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("i am a file", encoding="utf-8")

    code, _, err = _run(
        capsys, ["--state-file", str(blocker / "state.json"), "profit", "add", "50"]
    )

    assert code == 1
    assert "Could not write state file" in err


def _miss(capsys, state, titles, days_ago=1):
    argv = ["--state-file", str(state), "review", "log"]
    for t in titles:
        argv += ["--missed", t]
    argv += ["--priority", "keep going", "--date", str(date.today() - timedelta(days=days_ago))]
    return _run(capsys, argv)


def test_open_is_friendly_when_nothing_is_outstanding(tmp_path, capsys):
    code, out, _ = _run(capsys, ["--state-file", str(tmp_path / "s.json"), "open"])

    assert code == 0
    assert "Nothing outstanding" in out


def test_open_lists_commitments_with_ids_and_ages(tmp_path, capsys):
    state = tmp_path / "s.json"
    _miss(capsys, state, ["call the supplier", "post content"], days_ago=3)

    code, out, _ = _run(capsys, ["--state-file", str(state), "open"])

    assert code == 0
    assert "[1] call the supplier" in out
    assert "[2] post content" in out
    assert "carried 3 days" in out
    assert "life-os done <id>" in out


def test_done_closes_a_commitment_and_it_stays_closed(tmp_path, capsys):
    state = tmp_path / "s.json"
    _miss(capsys, state, ["call the supplier", "post content"])

    code, out, _ = _run(capsys, ["--state-file", str(state), "done", "1"])
    assert code == 0
    assert "Done: [1] call the supplier" in out
    assert "1 still open" in out

    _, out, _ = _run(capsys, ["--state-file", str(state), "open"])
    assert "call the supplier" not in out
    assert "[2] post content" in out


def test_drop_is_a_real_outcome(tmp_path, capsys):
    state = tmp_path / "s.json"
    _miss(capsys, state, ["a thing i no longer care about"])

    code, out, _ = _run(capsys, ["--state-file", str(state), "drop", "1"])

    assert code == 0
    assert "Dropped: [1]" in out
    assert "Nothing left outstanding" in out


def test_closing_an_unknown_id_is_an_error_not_a_silent_no_op(tmp_path, capsys):
    state = tmp_path / "s.json"
    _miss(capsys, state, ["a"])

    code, _, err = _run(capsys, ["--state-file", str(state), "done", "99"])

    assert code == 1
    assert "No commitment with id 99" in err


def test_closing_the_same_commitment_twice_is_an_error(tmp_path, capsys):
    state = tmp_path / "s.json"
    _miss(capsys, state, ["a"])
    _run(capsys, ["--state-file", str(state), "done", "1"])

    code, _, err = _run(capsys, ["--state-file", str(state), "done", "1"])

    assert code == 1
    assert "already done" in err


def test_missing_the_same_thing_daily_ages_one_commitment(tmp_path, capsys):
    """The whole point of the ledger: four days of the same miss is one
    commitment aged four days, not four items aged zero."""
    state = tmp_path / "s.json"
    for days_ago in (4, 3, 2, 1):
        _miss(capsys, state, ["call the supplier"], days_ago=days_ago)

    code, out, _ = _run(capsys, ["--state-file", str(state), "open"])

    assert code == 0
    # `open` covers today's plan as well as the ledger since ADR-008,
    # so the header counts both rather than naming only commitments.
    assert "Open (1)" in out
    assert "CARRYING 1 open commitment(s)" in out
    assert "carried 4 days" in out


def test_review_log_done_closes_the_matching_commitment(tmp_path, capsys):
    state = tmp_path / "s.json"
    _miss(capsys, state, ["wrote the email sequence"], days_ago=2)

    code, out, _ = _run(
        capsys,
        [
            "--state-file",
            str(state),
            "review",
            "log",
            "--done",
            "Wrote The Email Sequence",
            "--priority",
            "next thing",
        ],
    )

    assert code == 0
    assert "Closed 1 commitment(s)" in out
    assert "[1] wrote the email sequence" in out

    _, out, _ = _run(capsys, ["--state-file", str(state), "open"])
    assert "Nothing outstanding" in out


def test_review_log_reports_newly_opened_commitments(tmp_path, capsys):
    state = tmp_path / "s.json"

    code, out, _ = _miss(capsys, state, ["shot the reel"])

    assert code == 0
    assert "Opened 1 new commitment(s)" in out
    assert "[1] shot the reel" in out
    assert "1 still open" in out


def test_a_stale_commitment_is_flagged_in_today(tmp_path, capsys):
    state = tmp_path / "s.json"
    _miss(capsys, state, ["ancient obligation"], days_ago=STALE_AFTER_DAYS + 2)

    code, out, _ = _run(capsys, ["--state-file", str(state), "today"])

    assert code == 0
    assert "stale" in out
    assert "finish it or drop it" in out


def test_a_fresh_commitment_is_not_flagged_stale(tmp_path, capsys):
    state = tmp_path / "s.json"
    _miss(capsys, state, ["recent obligation"], days_ago=STALE_AFTER_DAYS - 1)

    _, out, _ = _run(capsys, ["--state-file", str(state), "today"])

    assert "stale" not in out
    assert "recent obligation" in out


def test_a_version_3_state_file_upgrades_and_still_shows_carried_work(tmp_path, capsys):
    """Upgrading must not lose what the old build was carrying."""
    state = tmp_path / "s.json"
    state.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "profit_entries": [],
                "reviews": [
                    {
                        "review_date": str(date.today() - timedelta(days=2)),
                        "completed": [],
                        "incomplete": [
                            {"title": "carried from the old build", "category": "unspecified"}
                        ],
                        "top_priority_tomorrow": "ship it",
                        "note": "",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    code, out, _ = _run(capsys, ["--state-file", str(state), "today"])

    assert code == 0
    assert "carried from the old build" in out
    assert "carried 2 days" in out
    assert "ship it" in out


# --- the day plan (ADR-008) ------------------------------------------


def _seed_earlier_plan(state_path, goals, days_ago=1, first_id=1):
    """Store a plan dated in the past.

    `today` has no --date flag by design, so exercising anything that
    reads across days means putting the earlier day there directly.
    """
    plan = build_plan(date.today() - timedelta(days=days_ago), list(goals), first_id=first_id)
    save_state(AppState(profit=ProfitTracker(), day_plans=(plan,)), state_path)
    return plan


def test_today_gives_every_planned_item_an_id(tmp_path, capsys):
    state = tmp_path / "s.json"

    code, out, _ = _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    assert code == 0
    for expected in ("[1]", "[2]", "[3]"):
        assert expected in out
    assert "0 of 3 done" in out


def test_running_today_twice_shows_the_same_plan_not_a_new_one(tmp_path, capsys):
    """The plan for a date is generated once. Re-running is a read."""
    state = tmp_path / "s.json"
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    code, out, _ = _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    assert code == 0
    assert "[4]" not in out
    assert len(load_state(state).day_plans) == 1


def test_done_closes_a_plan_item_and_it_stays_closed(tmp_path, capsys):
    state = tmp_path / "s.json"
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    code, out, _ = _run(capsys, ["--state-file", str(state), "done", "1"])
    assert code == 0
    assert "Done: [1]" in out
    assert "2 still open" in out

    code, out, _ = _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])
    assert "(done)" in out
    assert "1 of 3 done" in out


def test_drop_is_a_real_outcome_for_a_plan_item_too(tmp_path, capsys):
    state = tmp_path / "s.json"
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    code, out, _ = _run(capsys, ["--state-file", str(state), "drop", "2"])

    assert code == 0
    assert "Dropped: [2]" in out

    _, out, _ = _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])
    assert "(dropped)" in out
    assert "1 dropped" in out


def test_closing_an_unknown_plan_id_is_an_error(tmp_path, capsys):
    state = tmp_path / "s.json"
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    code, _, err = _run(capsys, ["--state-file", str(state), "done", "99"])

    assert code == 1
    assert "99" in err


def test_an_id_from_an_earlier_day_says_so_rather_than_reporting_it_unknown(tmp_path, capsys):
    state = tmp_path / "s.json"
    _seed_earlier_plan(state, ["yesterday's goal"])

    _run(capsys, ["--state-file", str(state), "today", "--goal", "today's goal"])
    code, _, err = _run(capsys, ["--state-file", str(state), "done", "1"])

    assert code == 1
    assert "earlier day" in err


def test_today_reuses_the_goals_you_last_planned_with(tmp_path, capsys):
    """The whole reason the shell alias existed."""
    state = tmp_path / "s.json"
    _seed_earlier_plan(state, ["Maestro University"])

    code, out, _ = _run(capsys, ["--state-file", str(state), "today"])

    assert code == 0
    assert "Maestro University" in out
    assert "goals you last used" in out


def test_today_is_still_friendly_with_no_goals_anywhere(tmp_path, capsys):
    state = tmp_path / "s.json"

    code, out, _ = _run(capsys, ["--state-file", str(state), "today"])

    assert code == 0
    assert "no active goals" in out


def test_today_refuses_more_goals_than_the_daily_maximum(tmp_path, capsys):
    state = tmp_path / "s.json"

    code, _, err = _run(
        capsys,
        ["--state-file", str(state), "today"]
        + [arg for goal in ("a", "b", "c", "d") for arg in ("--goal", goal)],
    )

    assert code == 1
    assert "daily maximum" in err


def test_different_goals_point_at_replan_rather_than_silently_rebuilding(tmp_path, capsys):
    state = tmp_path / "s.json"
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    code, out, _ = _run(capsys, ["--state-file", str(state), "today", "--goal", "get in shape"])

    assert code == 0
    assert "--replan" in out
    assert "grow the store" in out


def test_replan_keeps_work_already_closed(tmp_path, capsys):
    state = tmp_path / "s.json"
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])
    _run(capsys, ["--state-file", str(state), "done", "1"])

    code, out, _ = _run(
        capsys,
        [
            "--state-file",
            str(state),
            "today",
            "--replan",
            "--goal",
            "grow the store",
            "--goal",
            "get in shape",
        ],
    )

    assert code == 0
    assert "Replanned today" in out
    assert "(done)" in out
    assert load_state(state).day_plans[0].find(1).status.value == "done"


def test_open_lists_todays_plan_alongside_carried_commitments(tmp_path, capsys):
    state = tmp_path / "s.json"
    _miss(capsys, state, ["call the supplier"], days_ago=2)
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    code, out, _ = _run(capsys, ["--state-file", str(state), "open"])

    assert code == 0
    assert "TODAY'S PLAN - 3 open" in out
    assert "CARRYING 1 open commitment(s)" in out
    assert "Open (4)" in out


def test_open_says_the_day_is_clear_rather_than_that_nothing_was_missed(tmp_path, capsys):
    state = tmp_path / "s.json"
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])
    for item_id in ("1", "2", "3"):
        _run(capsys, ["--state-file", str(state), "done", item_id])

    code, out, _ = _run(capsys, ["--state-file", str(state), "open"])

    assert code == 0
    assert "Today's plan is clear" in out


def test_review_log_reads_the_day_instead_of_asking_for_it(tmp_path, capsys):
    """One required argument on a planned day."""
    state = tmp_path / "s.json"
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])
    _run(capsys, ["--state-file", str(state), "done", "1"])

    code, out, _ = _run(
        capsys, ["--state-file", str(state), "review", "log", "--priority", "ship it"]
    )

    assert code == 0
    assert "Read from today's plan: 1 done" in out
    assert "Completed: 1/3" in out
    assert "Opened 2 new commitment(s)" in out


def test_a_dropped_item_is_neither_completed_nor_reopened_as_a_commitment(tmp_path, capsys):
    """Recording a dropped item as missed would reopen it that night
    and quietly overturn the decision to drop it."""
    state = tmp_path / "s.json"
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])
    _run(capsys, ["--state-file", str(state), "drop", "2"])

    code, out, _ = _run(
        capsys, ["--state-file", str(state), "review", "log", "--priority", "ship it"]
    )

    assert code == 0
    assert "1 dropped and not counted" in out
    assert "Completed: 0/2" in out
    assert "Opened 2 new commitment(s)" in out

    titles = [c.title for c in load_state(state).commitments]
    assert "Improve a skill related to: grow the store" not in titles


def test_correcting_a_review_does_not_require_retyping_the_day(tmp_path, capsys):
    """The trap ADR-008 closes: upsert_review replaces, so before the
    plan was the source of truth a one-item fix meant retyping all of
    them."""
    state = tmp_path / "s.json"
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])
    _run(capsys, ["--state-file", str(state), "done", "1"])
    _run(capsys, ["--state-file", str(state), "review", "log", "--priority", "ship it"])

    _run(capsys, ["--state-file", str(state), "done", "2"])
    code, out, _ = _run(
        capsys, ["--state-file", str(state), "review", "log", "--priority", "ship it"]
    )

    assert code == 0
    assert "Replaced the previous review" in out
    assert "Completed: 2/3" in out
    # The commitment opened by the first review is settled by the second.
    assert "Closed 1 commitment(s)" in out


def test_an_explicit_done_also_settles_the_plan_item_it_names(tmp_path, capsys):
    state = tmp_path / "s.json"
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    code, out, _ = _run(
        capsys,
        [
            "--state-file",
            str(state),
            "review",
            "log",
            "--done",
            "execute a direct revenue action for: grow the store",
            "--priority",
            "ship it",
        ],
    )

    assert code == 0
    assert "Completed: 1/3" in out
    assert load_state(state).day_plans[0].find(1).status.value == "done"


def test_work_reported_done_is_never_also_recorded_as_missed(tmp_path, capsys):
    state = tmp_path / "s.json"
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    _run(
        capsys,
        [
            "--state-file",
            str(state),
            "review",
            "log",
            "--done",
            "Execute a direct revenue action for: grow the store",
            "--priority",
            "ship it",
        ],
    )

    review = load_state(state).reviews[0]
    done = {t.title for t in review.completed}
    missed = {t.title for t in review.incomplete}
    assert not done & missed


def test_a_review_read_from_the_plan_records_real_categories(tmp_path, capsys):
    """Typed titles are honestly UNSPECIFIED; items the plan generated
    are not, and pretending otherwise threw away what it knew."""
    state = tmp_path / "s.json"
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])
    _run(capsys, ["--state-file", str(state), "done", "1"])
    _run(capsys, ["--state-file", str(state), "review", "log", "--priority", "ship it"])

    review = load_state(state).reviews[0]

    assert [t.category.value for t in review.completed] == ["revenue"]
    assert sorted(t.category.value for t in review.incomplete) == ["maintenance", "skill"]


def test_review_log_for_an_unplanned_date_still_works_from_flags_alone(tmp_path, capsys):
    """Days before ADR-008, and any day planned outside Life OS."""
    state = tmp_path / "s.json"
    yesterday = date.today() - timedelta(days=1)

    code, out, _ = _run(
        capsys,
        [
            "--state-file",
            str(state),
            "review",
            "log",
            "--date",
            yesterday.isoformat(),
            "--done",
            "shipped the thing",
            "--missed",
            "called the supplier",
            "--priority",
            "ship it",
        ],
    )

    assert code == 0
    assert "Read from today's plan" not in out
    assert "Completed: 1/2" in out


def test_plan_items_and_commitments_never_share_an_id(tmp_path, capsys):
    """`life-os done 4` must mean exactly one thing."""
    state = tmp_path / "s.json"
    _miss(capsys, state, ["call the supplier", "email the landlord"], days_ago=3)

    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    loaded = load_state(state)
    commitment_ids = {c.id for c in loaded.commitments}
    item_ids = {i.id for p in loaded.day_plans for i in p.items}

    assert commitment_ids == {1, 2}
    assert item_ids == {3, 4, 5}
    assert not commitment_ids & item_ids


def test_done_resolves_a_commitment_when_the_id_is_not_on_todays_plan(tmp_path, capsys):
    state = tmp_path / "s.json"
    _miss(capsys, state, ["call the supplier"], days_ago=2)
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    code, out, _ = _run(capsys, ["--state-file", str(state), "done", "1"])

    assert code == 0
    assert "call the supplier" in out
    assert "carried 2 days" in out
    assert "3 still open" in out


def test_a_plan_agrees_with_a_review_already_logged_for_that_day(tmp_path, capsys):
    """The upgrade seam: every day in a pre-ADR-008 state file has a
    review but no plan. Planning that day must not show work already
    reported done as still open, or the next review would replace an
    accurate record with an empty one."""
    state = tmp_path / "s.json"
    _run(
        capsys,
        [
            "--state-file",
            str(state),
            "review",
            "log",
            "--done",
            "Execute a direct revenue action for: grow the store",
            "--priority",
            "ship it",
        ],
    )

    code, out, _ = _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    assert code == 0
    assert "(done)" in out
    assert "1 of 3 done" in out
    assert "already logged them" in out


def test_re_reviewing_after_that_does_not_lose_the_work(tmp_path, capsys):
    state = tmp_path / "s.json"
    _run(
        capsys,
        [
            "--state-file",
            str(state),
            "review",
            "log",
            "--done",
            "Execute a direct revenue action for: grow the store",
            "--priority",
            "ship it",
        ],
    )
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    code, out, _ = _run(
        capsys, ["--state-file", str(state), "review", "log", "--priority", "ship it"]
    )

    assert code == 0
    assert "Completed: 1/3" in out
    titles = {t.title for t in load_state(state).reviews[0].completed}
    assert "Execute a direct revenue action for: grow the store" in titles


def test_a_commitment_opened_at_review_never_reuses_a_plan_item_id(tmp_path, capsys):
    """Caught against real data. `record_misses` allocated from the
    ledger alone, so the first miss of a planned day was handed id 1 —
    already in use by a plan item. `life-os done 1` then had two
    answers and the commitment became unreachable by id."""
    state = tmp_path / "s.json"
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    _run(capsys, ["--state-file", str(state), "review", "log", "--priority", "ship it"])

    loaded = load_state(state)
    item_ids = {i.id for p in loaded.day_plans for i in p.items}
    commitment_ids = {c.id for c in loaded.commitments}

    assert item_ids == {1, 2, 3}
    assert commitment_ids == {4, 5, 6}
    assert not item_ids & commitment_ids


def test_work_already_carried_is_not_listed_twice(tmp_path, capsys):
    """Generated titles repeat word for word. Yesterday's miss and
    today's fresh item are one obligation, and the carried list is
    where it belongs because that is the copy with an age."""
    state = tmp_path / "s.json"
    title = "Execute a direct revenue action for: grow the store"
    _miss(capsys, state, [title], days_ago=2)

    code, out, _ = _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    assert code == 0
    assert out.count(title) == 1
    assert "carried 2 days" in out
    # Two fresh items plus one carried commitment, not four things.
    assert "3 things on the table today." in out


def test_owe_does_not_list_carried_work_twice_either(tmp_path, capsys):
    state = tmp_path / "s.json"
    title = "Improve a skill related to: grow the store"
    _miss(capsys, state, [title], days_ago=1)
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    code, out, _ = _run(capsys, ["--state-file", str(state), "open"])

    assert code == 0
    assert out.count(title) == 1
    assert "Open (3)" in out


def test_a_shadowed_item_is_still_stored_on_the_plan(tmp_path, capsys):
    """Hiding it is a view decision; the day's record keeps everything."""
    state = tmp_path / "s.json"
    title = "Improve a skill related to: grow the store"
    _miss(capsys, state, [title], days_ago=1)
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    stored = load_state(state).day_plans[0]

    assert len(stored.items) == 3
    assert title in [i.title for i in stored.items]


def test_the_logged_count_matches_the_count_today_displayed(tmp_path, capsys):
    """Found on real data. `today` hides an open plan item that is
    already a carried commitment, but `review log` read the raw plan and
    counted it anyway — so the screen said 0 of 4 and the review logged
    1 of 10. A rate that contradicts the screen is the ADR-006 defect
    again: arithmetically fine, factually wrong."""
    state = tmp_path / "s.json"
    carried = "Execute a direct revenue action for: grow the store"
    _miss(capsys, state, [carried], days_ago=1)

    _, plan_out, _ = _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])
    assert "0 of 2 done" in plan_out

    code, out, _ = _run(
        capsys, ["--state-file", str(state), "review", "log", "--priority", "ship it"]
    )

    assert code == 0
    assert "Completed: 0/2" in out


def test_work_carried_in_is_not_recorded_as_missed_a_second_time(tmp_path, capsys):
    """One obligation, one commitment (ADR-007). The review must not
    re-report it every day it stays open, or `review week` counts the
    same miss repeatedly."""
    state = tmp_path / "s.json"
    carried = "Improve a skill related to: grow the store"
    _miss(capsys, state, [carried], days_ago=2)

    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])
    _run(capsys, ["--state-file", str(state), "review", "log", "--priority", "ship it"])

    loaded = load_state(state)
    today_review = max(loaded.reviews, key=lambda r: r.review_date)
    assert carried not in [t.title for t in today_review.incomplete]

    # The ledger still holds it, still aging, still one entry.
    matching = [c for c in loaded.commitments if c.title == carried]
    assert len(matching) == 1
    assert matching[0].is_open


def test_carried_work_reported_done_still_counts_and_closes(tmp_path, capsys):
    """Hiding it from the count must not hide it from credit."""
    state = tmp_path / "s.json"
    carried = "Execute a direct revenue action for: grow the store"
    _miss(capsys, state, [carried], days_ago=1)
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    code, out, _ = _run(
        capsys,
        ["--state-file", str(state), "review", "log", "--done", carried, "--priority", "ship it"],
    )

    assert code == 0
    assert "Closed 1 commitment(s)" in out
    assert "Completed: 1/3" in out


def test_correcting_a_review_does_not_shrink_its_own_denominator(tmp_path, capsys):
    """The reason the filter compares strictly before the review date.
    A commitment opened on this date was opened by an earlier run of
    this same review; excluding those would let a correction turn
    1 of 3 into 2 of 2."""
    state = tmp_path / "s.json"
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])
    _run(capsys, ["--state-file", str(state), "done", "1"])
    _, first, _ = _run(
        capsys, ["--state-file", str(state), "review", "log", "--priority", "ship it"]
    )
    assert "Completed: 1/3" in first

    _run(capsys, ["--state-file", str(state), "done", "2"])
    code, out, _ = _run(
        capsys, ["--state-file", str(state), "review", "log", "--priority", "ship it"]
    )

    assert code == 0
    assert "Completed: 2/3" in out


def _count_after(out: str) -> int:
    """The N from "N still open." / 0 for "Nothing left outstanding.\""""
    if "Nothing left outstanding." in out:
        return 0
    return int(re.search(r"(\d+) still open\.", out).group(1))


def _count_listed(out: str) -> int:
    """The N from `open`'s "Open (N)" header / 0 when it reports clear."""
    match = re.search(r"Open \((\d+)\)", out)
    return int(match.group(1)) if match else 0


def test_closing_something_reports_the_same_count_open_does(tmp_path, capsys):
    """`drop` reported "17 still open" on a day with 9 commitments,
    because it added today's raw plan items to the ledger and every one
    of them was already a carried commitment. The number a command
    prints after acting has to be the number `open` would show — that
    agreement is the contract, whatever the number happens to be."""
    state = tmp_path / "s.json"
    _miss(
        capsys,
        state,
        [
            "Execute a direct revenue action for: grow the store",
            "Improve a skill related to: grow the store",
        ],
        days_ago=1,
    )
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    _, dropped, _ = _run(capsys, ["--state-file", str(state), "drop", "1"])
    _, listed, _ = _run(capsys, ["--state-file", str(state), "open"])

    assert _count_after(dropped) == _count_listed(listed)


def test_closing_a_plan_item_counts_the_same_way(tmp_path, capsys):
    state = tmp_path / "s.json"
    _miss(capsys, state, ["Improve a skill related to: grow the store"], days_ago=1)
    _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])

    _, done_out, _ = _run(capsys, ["--state-file", str(state), "done", "2"])
    _, listed, _ = _run(capsys, ["--state-file", str(state), "open"])

    assert _count_after(done_out) == _count_listed(listed)


def test_the_two_agree_on_a_day_that_is_entirely_carried_work(tmp_path, capsys):
    """Antonio's actual case: every generated item shadowed, so the raw
    plan added a full nine to every count."""
    state = tmp_path / "s.json"
    _miss(
        capsys,
        state,
        [
            "Execute a direct revenue action for: grow the store",
            "Improve a skill related to: grow the store",
            "Stabilize your environment for: grow the store",
        ],
        days_ago=1,
    )
    _, plan_out, _ = _run(capsys, ["--state-file", str(state), "today", "--goal", "grow the store"])
    assert "already in the carried list" in plan_out

    _, dropped, _ = _run(capsys, ["--state-file", str(state), "drop", "2"])
    _, listed, _ = _run(capsys, ["--state-file", str(state), "open"])

    # Two commitments left, plus the plan item the drop un-shadowed.
    # Before the fix this printed 5: the ledger plus all three raw
    # plan items, every one of them already counted as a commitment.
    assert _count_after(dropped) == _count_listed(listed) == 3
