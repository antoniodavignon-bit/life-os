import pytest

from life_os.cli import main


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

    code, _, _ = _run(capsys, ["--state-file", str(state), "profit", "add", "250", "--note", "Sale"])
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
