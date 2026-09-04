import pytest

from life_os.tasks import (
    MAX_ACTIVE_GOALS,
    Category,
    DailyPlan,
    Task,
    generate_tasks,
    normalize_goals,
)


def test_generate_tasks_returns_a_daily_plan():
    goals = [
        "business growth",
        "physical fitness",
        "skill development",
    ]

    plan = generate_tasks(goals)

    assert isinstance(plan, DailyPlan)
    assert len(plan.revenue) == 3
    assert len(plan.skill) == 3
    assert len(plan.maintenance) == 3
    assert plan.total_tasks == 9


def test_every_generated_task_carries_a_real_category():
    plan = generate_tasks(["grow the store"])

    assert [t.category for t in plan.revenue] == [Category.REVENUE]
    assert [t.category for t in plan.skill] == [Category.SKILL]
    assert [t.category for t in plan.maintenance] == [Category.MAINTENANCE]


def test_every_generated_task_names_its_goal():
    plan = generate_tasks(["grow the store"])

    assert all("grow the store" in task.title for task in plan.all_tasks)


def test_no_active_goals_yields_an_empty_plan():
    """An empty day is a real outcome, not an error (ADR-002, rule 5)."""
    plan = generate_tasks([])

    assert plan.total_tasks == 0
    assert plan.revenue == ()


def test_more_goals_than_the_daily_maximum_is_refused_not_truncated():
    """The old behavior sliced to three and said nothing, so a fourth
    goal produced no tasks and no warning."""
    too_many = [f"goal {i}" for i in range(MAX_ACTIVE_GOALS + 1)]

    with pytest.raises(ValueError, match="exceeds the daily maximum"):
        generate_tasks(too_many)


def test_exactly_the_daily_maximum_is_allowed():
    plan = generate_tasks([f"goal {i}" for i in range(MAX_ACTIVE_GOALS)])

    assert len(plan.revenue) == MAX_ACTIVE_GOALS


def test_duplicate_goals_collapse_before_the_limit_applies():
    """Four entries, two distinct goals: a plan, not a rejection."""
    plan = generate_tasks(
        ["Grow the store", "grow the store", "  GROW THE STORE  ", "get in shape"]
    )

    assert [t.title for t in plan.revenue] == [
        "Execute a direct revenue action for: Grow the store",
        "Execute a direct revenue action for: get in shape",
    ]


def test_blank_goals_are_dropped_rather_than_planned_around():
    plan = generate_tasks(["", "   ", "ship the product"])

    assert len(plan.revenue) == 1


def test_normalize_goals_collapses_internal_whitespace():
    assert normalize_goals(["grow   the\tstore"]) == ["grow the store"]


def test_normalize_goals_rejects_non_string_input():
    with pytest.raises(ValueError, match="must be strings"):
        normalize_goals([None])


def test_task_rejects_an_empty_title():
    with pytest.raises(ValueError, match="title must not be empty"):
        Task(title="   ", category=Category.REVENUE)


def test_task_rejects_an_unknown_category():
    """A typo used to become a permanent, silently valid category."""
    with pytest.raises(ValueError, match="Unknown task category"):
        Task(title="post content", category="revenu")


def test_task_accepts_a_category_string_and_normalizes_it():
    task = Task(title="  post content  ", category="revenue")

    assert task.category is Category.REVENUE
    assert task.title == "post content"


def test_plan_is_immutable():
    plan = generate_tasks(["grow the store"])

    with pytest.raises(AttributeError):
        plan.revenue.append(Task(title="sneak this in", category=Category.REVENUE))


def test_tasks_for_filters_by_category():
    plan = generate_tasks(["grow the store", "get in shape"])

    assert len(plan.tasks_for(Category.SKILL)) == 2
    assert plan.tasks_for(Category.UNSPECIFIED) == ()
