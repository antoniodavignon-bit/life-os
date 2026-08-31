from life_os.tasks import DailyPlan, generate_tasks


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