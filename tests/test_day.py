from datetime import date

import pytest

from life_os.day import (
    DayPlan,
    ItemStatus,
    PlanItem,
    build_plan,
    close_item,
    close_items_by_title,
    latest_goals,
    latest_plan,
    max_item_id,
    outcome,
    plan_for,
    replan,
    upsert_plan,
)
from life_os.tasks import Category

DAY = date(2026, 9, 7)


def _plan(goals=("grow the store",), first_id=1, plan_date=DAY):
    return build_plan(plan_date, list(goals), first_id=first_id)


# --- build_plan -------------------------------------------------------


def test_build_plan_numbers_items_in_display_order():
    plan = _plan()

    assert [i.id for i in plan.items] == [1, 2, 3]
    assert [i.category for i in plan.items] == [
        Category.REVENUE,
        Category.SKILL,
        Category.MAINTENANCE,
    ]


def test_build_plan_starts_at_the_id_it_is_given():
    """Ids come from the space shared with commitments, so the plan
    must not assume it starts at 1."""
    plan = _plan(first_id=12)

    assert [i.id for i in plan.items] == [12, 13, 14]


def test_build_plan_records_the_goals_it_came_from():
    plan = _plan(goals=("  grow  the store ", "get in shape"))

    assert plan.goals == ("grow the store", "get in shape")


def test_build_plan_with_no_goals_is_an_empty_plan_not_an_error():
    plan = build_plan(DAY, [], first_id=1)

    assert plan.items == ()
    assert plan.total_items == 0


def test_build_plan_refuses_more_goals_than_the_daily_maximum():
    with pytest.raises(ValueError, match="exceeds the daily maximum"):
        build_plan(DAY, ["a", "b", "c", "d"], first_id=1)


def test_build_plan_rejects_a_non_positive_first_id():
    with pytest.raises(ValueError, match="first_id"):
        build_plan(DAY, ["a"], first_id=0)


# --- PlanItem ---------------------------------------------------------


@pytest.mark.parametrize("bad_id", [0, -1, True, "3"])
def test_plan_item_rejects_an_invalid_id(bad_id):
    with pytest.raises(ValueError, match="id must be a positive integer"):
        PlanItem(id=bad_id, title="x", category=Category.REVENUE)


def test_plan_item_rejects_an_empty_title():
    with pytest.raises(ValueError, match="title must not be empty"):
        PlanItem(id=1, title="   ", category=Category.REVENUE)


def test_plan_item_rejects_an_unknown_category():
    with pytest.raises(ValueError, match="Unknown task category"):
        PlanItem(id=1, title="x", category="urgent")


def test_plan_item_rejects_an_unknown_status():
    with pytest.raises(ValueError, match="Unknown plan item status"):
        PlanItem(id=1, title="x", category=Category.REVENUE, status="finished")


def test_an_open_item_cannot_carry_a_closing_date():
    with pytest.raises(ValueError, match="open plan item cannot have"):
        PlanItem(id=1, title="x", category=Category.REVENUE, closed_on=DAY)


def test_a_closed_item_must_carry_a_closing_date():
    with pytest.raises(ValueError, match="must have a closed_on date"):
        PlanItem(id=1, title="x", category=Category.REVENUE, status=ItemStatus.DONE)


def test_closing_an_item_twice_is_an_error():
    item = PlanItem(id=1, title="x", category=Category.REVENUE).closed(ItemStatus.DONE, DAY)

    with pytest.raises(ValueError, match="already done"):
        item.closed(ItemStatus.DONE, DAY)


def test_closing_to_open_is_not_a_closure():
    item = PlanItem(id=1, title="x", category=Category.REVENUE)

    with pytest.raises(ValueError, match="terminal status"):
        item.closed(ItemStatus.OPEN, DAY)


# --- DayPlan ----------------------------------------------------------


def test_a_day_plan_rejects_duplicate_ids():
    item = PlanItem(id=1, title="x", category=Category.REVENUE)
    other = PlanItem(id=1, title="y", category=Category.SKILL)

    with pytest.raises(ValueError, match="must be unique"):
        DayPlan(plan_date=DAY, goals=(), items=(item, other))


def test_a_day_plan_rejects_a_non_date():
    with pytest.raises(ValueError, match="plan_date must be a date"):
        DayPlan(plan_date="2026-09-07", goals=(), items=())


def test_lists_passed_in_become_tuples():
    plan = DayPlan(plan_date=DAY, goals=["a"], items=[])

    assert isinstance(plan.goals, tuple)
    assert isinstance(plan.items, tuple)


# --- status and completion -------------------------------------------


def test_completion_rate_ignores_dropped_items():
    """Deciding something no longer matters is not a loss, and not a
    win. Three items, one done, one dropped, one open is 50%."""
    plan = _plan()
    plan, _ = close_item(plan, 1, on=DAY, status=ItemStatus.DONE)
    plan, _ = close_item(plan, 2, on=DAY, status=ItemStatus.DROPPED)

    assert plan.completion_rate == pytest.approx(0.5)


def test_a_plan_of_only_dropped_items_scores_zero_rather_than_dividing_by_zero():
    plan = _plan()
    for item_id in (1, 2, 3):
        plan, _ = close_item(plan, item_id, on=DAY, status=ItemStatus.DROPPED)

    assert plan.completion_rate == 0.0


def test_an_empty_plan_scores_zero():
    assert build_plan(DAY, [], first_id=1).completion_rate == 0.0


# --- close_item -------------------------------------------------------


def test_close_item_closes_only_its_target():
    plan = _plan()
    updated, closed = close_item(plan, 2, on=DAY)

    assert closed.id == 2
    assert closed.status is ItemStatus.DONE
    assert [i.id for i in updated.open_items] == [1, 3]


def test_close_item_rejects_an_unknown_id():
    with pytest.raises(ValueError, match="No plan item with id 99"):
        close_item(_plan(), 99, on=DAY)


def test_close_item_rejects_an_already_closed_item():
    plan, _ = close_item(_plan(), 1, on=DAY)

    with pytest.raises(ValueError, match="already done"):
        close_item(plan, 1, on=DAY)


def test_closing_does_not_mutate_the_plan_it_was_given():
    plan = _plan()
    close_item(plan, 1, on=DAY)

    assert plan.items[0].is_open


# --- close_items_by_title --------------------------------------------


def test_close_by_title_is_case_and_whitespace_insensitive():
    plan = _plan()
    target = plan.items[0].title

    updated, closed = close_items_by_title(plan, [f"  {target.upper()}  "], on=DAY)

    assert [c.id for c in closed] == [1]
    assert updated.find(1).status is ItemStatus.DONE


def test_close_by_title_ignores_titles_that_match_nothing():
    """Reporting work that was never on the plan is the normal case."""
    plan = _plan()
    updated, closed = close_items_by_title(plan, ["took the bins out"], on=DAY)

    assert closed == ()
    assert updated == plan


def test_close_by_title_ignores_blank_titles():
    plan = _plan()
    updated, closed = close_items_by_title(plan, ["", "   "], on=DAY)

    assert closed == ()
    assert updated == plan


# --- outcome ----------------------------------------------------------


def test_outcome_splits_done_from_open_and_excludes_dropped():
    plan = _plan()
    plan, _ = close_item(plan, 1, on=DAY, status=ItemStatus.DONE)
    plan, _ = close_item(plan, 2, on=DAY, status=ItemStatus.DROPPED)

    done, missed = outcome(plan)

    assert done == (plan.items[0].title,)
    assert missed == (plan.items[2].title,)
    assert plan.items[1].title not in done + missed


# --- collection helpers ----------------------------------------------


def test_max_item_id_spans_every_plan():
    plans = (_plan(first_id=1), _plan(first_id=40, plan_date=date(2026, 9, 8)))

    assert max_item_id(plans) == 42


def test_max_item_id_of_nothing_is_zero():
    assert max_item_id(()) == 0


def test_plan_for_finds_by_date_and_returns_none_otherwise():
    plan = _plan()

    assert plan_for((plan,), DAY) is plan
    assert plan_for((plan,), date(2026, 9, 8)) is None


def test_upsert_plan_replaces_the_plan_for_a_date_and_sorts():
    earlier = _plan(plan_date=date(2026, 9, 6))
    first = _plan()
    replacement = _plan(goals=("something else",), first_id=50)

    plans = upsert_plan(upsert_plan((), first), earlier)
    plans = upsert_plan(plans, replacement)

    assert [p.plan_date for p in plans] == [date(2026, 9, 6), DAY]
    assert plan_for(plans, DAY).goals == ("something else",)


def test_latest_plan_and_goals_read_the_most_recent_day():
    older = build_plan(date(2026, 9, 1), ["old goal"], first_id=1)
    newer = build_plan(date(2026, 9, 7), ["new goal"], first_id=10)

    plans = (newer, older)  # deliberately out of order

    assert latest_plan(plans) is newer
    assert latest_goals(plans) == ("new goal",)


def test_latest_goals_of_nothing_is_empty():
    assert latest_goals(()) == ()
    assert latest_plan(()) is None


# --- replan -----------------------------------------------------------


def test_replan_keeps_work_already_closed():
    """A goal change at noon must not erase the morning."""
    plan = _plan(goals=("grow the store",))
    plan, closed = close_item(plan, 1, on=DAY)

    rebuilt = replan(plan, ["grow the store", "get in shape"], first_id=max_item_id((plan,)) + 1)

    survivor = rebuilt.find(1)
    assert survivor is not None
    assert survivor.status is ItemStatus.DONE
    assert survivor.title == closed.title


def test_replan_gives_genuinely_new_work_fresh_ids():
    plan = _plan(goals=("grow the store",))

    rebuilt = replan(plan, ["get in shape"], first_id=4)

    assert len(rebuilt.items) == 3
    assert [i.id for i in rebuilt.items] == [4, 5, 6]
    assert rebuilt.goals == ("get in shape",)


def test_replan_retains_closed_work_whose_goal_went_away():
    """Recorded work is history. Tidying the list must not delete it."""
    plan = _plan(goals=("grow the store",))
    plan, closed = close_item(plan, 1, on=DAY)

    rebuilt = replan(plan, ["get in shape"], first_id=4)

    assert closed.title in [i.title for i in rebuilt.items]
    assert rebuilt.find(1).status is ItemStatus.DONE


def test_replan_discards_open_work_whose_goal_went_away():
    """The mirror of the rule above: nothing was recorded, so there is
    no history to protect and the stale item should not linger."""
    plan = _plan(goals=("grow the store",))
    old_titles = {i.title for i in plan.items}

    rebuilt = replan(plan, ["get in shape"], first_id=4)

    assert not old_titles & {i.title for i in rebuilt.items}


# --- without_owed -----------------------------------------------------


def test_without_owed_hides_open_items_already_carried():
    from life_os.day import without_owed

    plan = _plan()
    owed = plan.items[0].key

    visible = without_owed(plan, {owed})

    assert len(visible.items) == 2
    assert plan.items[0].title not in [i.title for i in visible.items]


def test_without_owed_keeps_closed_items_whatever_is_owed():
    """Closed items are what the day recorded. Tidying the list must
    not erase them."""
    from life_os.day import without_owed

    plan = _plan()
    plan, closed = close_item(plan, 1, on=DAY)

    visible = without_owed(plan, {closed.key})

    assert closed.title in [i.title for i in visible.items]


def test_without_owed_leaves_the_stored_plan_alone():
    from life_os.day import without_owed

    plan = _plan()
    without_owed(plan, {i.key for i in plan.items})

    assert len(plan.items) == 3
