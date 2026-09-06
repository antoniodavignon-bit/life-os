from datetime import date

import pytest

from life_os.review import (
    DailyReview,
    latest_review_before,
    summarize_week,
    upsert_review,
)
from life_os.tasks import Task


def _task(title: str, category: str = "revenue") -> Task:
    return Task(title=title, category=category)


def _review(completed: list[Task], incomplete: list[Task], day: int = 1) -> DailyReview:
    return DailyReview(
        review_date=date(2026, 9, day),
        completed=completed,
        incomplete=incomplete,
        top_priority_tomorrow="Ship the landing page",
    )


def test_completion_rate_reflects_completed_share():
    review = _review(
        completed=[_task("a"), _task("b"), _task("c")],
        incomplete=[_task("d")],
    )

    assert review.total_tasks == 4
    assert review.completion_rate == pytest.approx(0.75)


def test_completion_rate_is_zero_for_a_day_with_no_tasks():
    review = _review(completed=[], incomplete=[])

    assert review.total_tasks == 0
    assert review.completion_rate == 0.0


def test_review_requires_a_top_priority_for_tomorrow():
    with pytest.raises(ValueError):
        DailyReview(
            review_date=date(2026, 9, 1),
            completed=[],
            incomplete=[],
            top_priority_tomorrow="   ",
        )


def test_summarize_week_aggregates_across_reviews():
    reviews = [
        _review(completed=[_task("a"), _task("b")], incomplete=[_task("c")], day=1),
        _review(completed=[_task("d")], incomplete=[_task("e")], day=2),
    ]

    summary = summarize_week(reviews)

    assert summary.reviews_logged == 2
    assert summary.tasks_completed == 3
    assert summary.tasks_missed == 2
    assert summary.completion_rate == pytest.approx(0.6)


def test_summarize_week_handles_an_empty_week():
    summary = summarize_week([])

    assert summary.reviews_logged == 0
    assert summary.tasks_completed == 0
    assert summary.tasks_missed == 0
    assert summary.completion_rate == 0.0


def _dated(day: int, missed: int = 1, priority: str = "Ship the landing page") -> DailyReview:
    return DailyReview(
        review_date=date(2026, 9, day),
        completed=[_task("done")],
        incomplete=[_task(f"missed {i} on day {day}") for i in range(missed)],
        top_priority_tomorrow=priority,
    )


def test_latest_review_before_picks_the_most_recent_earlier_review():
    reviews = [_dated(1), _dated(3), _dated(2)]

    assert latest_review_before(reviews, date(2026, 9, 5)).review_date == date(2026, 9, 3)


def test_latest_review_before_is_strict_so_a_day_never_inherits_itself():
    """Log this morning, plan again this afternoon: today's own misses
    must not come back as carried work."""
    reviews = [_dated(1), _dated(4)]

    assert latest_review_before(reviews, date(2026, 9, 4)).review_date == date(2026, 9, 1)


def test_latest_review_before_returns_none_with_no_earlier_review():
    assert latest_review_before([_dated(5)], date(2026, 9, 2)) is None
    assert latest_review_before([], date(2026, 9, 2)) is None


def test_upsert_adds_a_review_for_a_new_date():
    reviews, replaced = upsert_review([_dated(1)], _dated(2))

    assert [r.review_date.day for r in reviews] == [1, 2]
    assert replaced is None


def test_upsert_replaces_the_review_for_an_existing_date():
    """Logging twice in a day used to double-count that day in the
    weekly summary."""
    original = _dated(2, priority="Old priority")
    correction = _dated(2, missed=3, priority="Corrected priority")

    reviews, replaced = upsert_review([_dated(1), original], correction)

    assert len(reviews) == 2
    assert reviews[1].top_priority_tomorrow == "Corrected priority"
    assert replaced is original


def test_upsert_returns_reviews_sorted_by_date():
    reviews, _ = upsert_review([_dated(5), _dated(1)], _dated(3))

    assert [r.review_date.day for r in reviews] == [1, 3, 5]


def test_upsert_does_not_mutate_the_list_it_was_given():
    original = [_dated(1)]

    upsert_review(original, _dated(2))

    assert len(original) == 1


def test_a_week_of_upserted_reviews_counts_each_day_once():
    reviews: list[DailyReview] = []
    for _ in range(3):
        reviews, _ = upsert_review(reviews, _dated(1, missed=2))

    assert summarize_week(reviews).reviews_logged == 1
