from datetime import date

import pytest

from life_os.goals import Goal, current_milestone, generate_milestones


def test_ninety_day_goal_breaks_into_thirteen_weekly_milestones():
    goal = Goal(title="Launch Life OS", category="business", start_date=date(2026, 9, 1))

    milestones = generate_milestones(goal)

    # 90 days = 12 full weeks (84 days) + a final 6-day milestone
    assert len(milestones) == 13
    assert milestones[0].start_date == date(2026, 9, 1)
    assert milestones[-1].end_date == goal.end_date


def test_milestones_are_consecutive_with_no_gaps_or_overlaps():
    goal = Goal(title="Ship product", category="business", start_date=date(2026, 9, 1))

    milestones = generate_milestones(goal)

    for earlier, later in zip(milestones, milestones[1:]):
        assert (later.start_date - earlier.end_date).days == 1


def test_goal_rejects_non_positive_duration():
    with pytest.raises(ValueError):
        Goal(
            title="Bad goal",
            category="business",
            start_date=date(2026, 9, 1),
            duration_days=0,
        )


def test_current_milestone_finds_the_week_containing_a_date():
    goal = Goal(title="Launch Life OS", category="business", start_date=date(2026, 9, 1))

    # Day 10 of the goal falls in week 2 (days 8-14).
    milestone = current_milestone(goal, date(2026, 9, 10))

    assert milestone is not None
    assert milestone.week_number == 2
    assert milestone.contains(date(2026, 9, 10))


def test_current_milestone_returns_none_outside_the_goal_window():
    goal = Goal(title="Launch Life OS", category="business", start_date=date(2026, 9, 1))

    assert current_milestone(goal, date(2026, 8, 31)) is None
    assert current_milestone(goal, date(2027, 1, 1)) is None


def test_short_goal_produces_a_single_partial_milestone():
    goal = Goal(
        title="Sprint week",
        category="business",
        start_date=date(2026, 9, 1),
        duration_days=3,
    )

    milestones = generate_milestones(goal)

    assert len(milestones) == 1
    assert milestones[0].start_date == date(2026, 9, 1)
    assert milestones[0].end_date == date(2026, 9, 3)
