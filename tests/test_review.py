from datetime import date

import pytest

from life_os.review import DailyReview, carry_forward, summarize_week
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


def test_carry_forward_returns_incomplete_tasks():
    missed = [_task("call supplier"), _task("post content")]
    review = _review(completed=[_task("done")], incomplete=missed)

    assert carry_forward(review) == missed


def test_carry_forward_returns_a_copy_not_the_original_list():
    missed = [_task("call supplier")]
    review = _review(completed=[], incomplete=missed)

    result = carry_forward(review)
    result.append(_task("injected"))

    assert len(review.incomplete) == 1


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
