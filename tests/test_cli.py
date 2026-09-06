from datetime import date, timedelta

import pytest

from life_os.cli import main
from life_os.review import CARRY_WARNING_THRESHOLD


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
    assert "CARRIED (1)" in out
    assert "wrote the email sequence" in out
    assert "Execute a direct revenue action for: grow the store" in out
    assert "ship the landing page" in out
    assert "4 things on the table today" in out


def test_today_does_not_inherit_a_review_logged_earlier_the_same_day(tmp_path, capsys):
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
    assert "CARRIED" not in out
    assert "todays own miss" not in out


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
    assert f"CARRIED ({CARRY_WARNING_THRESHOLD})" in out


def test_today_is_friendly_on_a_first_run(tmp_path, capsys):
    state = tmp_path / "state.json"

    code, out, _ = _run(capsys, ["--state-file", str(state), "today"])

    assert code == 0
    assert "CARRIED" not in out
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
