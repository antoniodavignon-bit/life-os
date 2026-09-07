from datetime import date, timedelta

import pytest

from life_os.commitments import (
    STALE_AFTER_DAYS,
    Commitment,
    CommitmentStatus,
    close_by_id,
    close_by_title,
    find,
    match_key,
    next_id,
    normalize_title,
    open_items,
    record_misses,
    stale_items,
)

MONDAY = date(2026, 9, 7)
TUESDAY = date(2026, 9, 8)


def _open(id: int, title: str, day: date = MONDAY) -> Commitment:
    return Commitment(id=id, title=title, opened_on=day)


def test_a_commitment_starts_open_with_no_closing_date():
    commitment = _open(1, "call the supplier")

    assert commitment.is_open
    assert commitment.status is CommitmentStatus.OPEN
    assert commitment.closed_on is None


def test_title_is_normalized_but_keeps_its_spelling():
    commitment = _open(1, "  Call   the\tsupplier  ")

    assert commitment.title == "Call the supplier"
    assert commitment.key == "call the supplier"


def test_commitment_rejects_an_invalid_id():
    for bad in (0, -1, "1", True):
        with pytest.raises(ValueError, match="positive integer"):
            Commitment(id=bad, title="a", opened_on=MONDAY)


def test_commitment_rejects_an_empty_title():
    with pytest.raises(ValueError, match="title must not be empty"):
        _open(1, "   ")


def test_commitment_rejects_an_unknown_status():
    with pytest.raises(ValueError, match="Unknown commitment status"):
        Commitment(id=1, title="a", opened_on=MONDAY, status="finished", closed_on=MONDAY)


def test_an_open_commitment_cannot_carry_a_closing_date():
    with pytest.raises(ValueError, match="cannot have a closed_on"):
        Commitment(id=1, title="a", opened_on=MONDAY, closed_on=TUESDAY)


def test_a_closed_commitment_must_carry_a_closing_date():
    with pytest.raises(ValueError, match="must have a closed_on"):
        Commitment(id=1, title="a", opened_on=MONDAY, status=CommitmentStatus.DONE)


def test_a_commitment_cannot_close_before_it_opened():
    with pytest.raises(ValueError, match="cannot precede opened_on"):
        Commitment(
            id=1,
            title="a",
            opened_on=TUESDAY,
            status=CommitmentStatus.DONE,
            closed_on=MONDAY,
        )


def test_age_counts_from_the_day_it_opened():
    commitment = _open(1, "call the supplier")

    assert commitment.age_days(MONDAY) == 0
    assert commitment.age_days(date(2026, 9, 13)) == 6


def test_age_stops_moving_once_closed():
    closed = _open(1, "call the supplier").closed(CommitmentStatus.DONE, TUESDAY)

    assert closed.age_days(date(2027, 1, 1)) == 1


def test_stale_only_at_or_past_the_threshold():
    commitment = _open(1, "call the supplier")
    just_under = MONDAY + timedelta(days=STALE_AFTER_DAYS - 1)
    at_threshold = MONDAY + timedelta(days=STALE_AFTER_DAYS)

    assert not commitment.is_stale(just_under)
    assert commitment.is_stale(at_threshold)


def test_a_closed_commitment_is_never_stale():
    closed = _open(1, "call the supplier").closed(CommitmentStatus.DROPPED, TUESDAY)

    assert not closed.is_stale(date(2027, 1, 1))


def test_closing_an_already_closed_commitment_raises():
    closed = _open(1, "a").closed(CommitmentStatus.DONE, TUESDAY)

    with pytest.raises(ValueError, match="already done"):
        closed.closed(CommitmentStatus.DROPPED, TUESDAY)


def test_closing_requires_a_terminal_status():
    with pytest.raises(ValueError, match="terminal status"):
        _open(1, "a").closed(CommitmentStatus.OPEN, TUESDAY)


def test_dropped_is_a_real_outcome_not_a_failure():
    dropped = _open(1, "a").closed(CommitmentStatus.DROPPED, TUESDAY)

    assert not dropped.is_open
    assert dropped.status is CommitmentStatus.DROPPED
    assert dropped.closed_on == TUESDAY


def test_next_id_never_reuses_a_closed_commitments_id():
    ledger = (
        _open(1, "a").closed(CommitmentStatus.DONE, TUESDAY),
        _open(2, "b").closed(CommitmentStatus.DROPPED, TUESDAY),
    )

    assert next_id(ledger) == 3


def test_next_id_starts_at_one_on_an_empty_ledger():
    assert next_id(()) == 1


def test_find_returns_none_for_an_unknown_id():
    assert find((_open(1, "a"),), 9) is None


def test_record_misses_opens_one_commitment_per_title():
    ledger, opened = record_misses((), ["call the supplier", "post content"], on=MONDAY)

    assert len(ledger) == 2
    assert [c.id for c in opened] == [1, 2]
    assert all(c.opened_on == MONDAY for c in opened)


def test_missing_the_same_thing_again_ages_one_commitment_rather_than_duplicating():
    """Four days of missing the same thing is one commitment aged four
    days, not four commitments aged zero."""
    ledger, _ = record_misses((), ["call the supplier"], on=MONDAY)
    ledger, opened = record_misses(ledger, ["Call The Supplier"], on=TUESDAY)

    assert opened == ()
    assert len(ledger) == 1
    assert ledger[0].opened_on == MONDAY
    assert ledger[0].age_days(TUESDAY) == 1


def test_record_misses_ignores_blank_titles():
    ledger, opened = record_misses((), ["", "   ", "real one"], on=MONDAY)

    assert len(ledger) == 1
    assert opened[0].title == "real one"


def test_record_misses_deduplicates_within_a_single_call():
    ledger, opened = record_misses((), ["post content", "Post Content"], on=MONDAY)

    assert len(ledger) == 1
    assert len(opened) == 1


def test_missing_something_again_after_finishing_it_opens_a_new_commitment():
    """Doing a thing and then failing to do it again later is a new
    obligation, and the ledger keeps both so the history stays honest."""
    ledger, _ = record_misses((), ["post content"], on=MONDAY)
    ledger, _ = close_by_title(ledger, ["post content"], on=MONDAY)
    ledger, opened = record_misses(ledger, ["post content"], on=TUESDAY)

    assert len(ledger) == 2
    assert opened[0].id == 2
    assert opened[0].opened_on == TUESDAY
    assert len(open_items(ledger)) == 1


def test_record_misses_does_not_mutate_the_ledger_it_was_given():
    original = [_open(1, "a")]

    record_misses(original, ["b"], on=TUESDAY)

    assert len(original) == 1


def test_close_by_title_closes_a_matching_open_commitment():
    ledger, _ = record_misses((), ["call the supplier", "post content"], on=MONDAY)

    ledger, closed = close_by_title(ledger, ["Call the supplier"], on=TUESDAY)

    assert [c.title for c in closed] == ["call the supplier"]
    assert closed[0].status is CommitmentStatus.DONE
    assert closed[0].closed_on == TUESDAY
    assert [c.title for c in open_items(ledger)] == ["post content"]


def test_close_by_title_ignores_titles_that_match_nothing():
    """Reporting work that was never a carried commitment is normal."""
    ledger, _ = record_misses((), ["call the supplier"], on=MONDAY)

    ledger, closed = close_by_title(ledger, ["something else entirely"], on=TUESDAY)

    assert closed == ()
    assert len(open_items(ledger)) == 1


def test_close_by_title_with_no_titles_is_a_no_op():
    ledger, _ = record_misses((), ["a"], on=MONDAY)

    same, closed = close_by_title(ledger, [], on=TUESDAY)

    assert same == ledger
    assert closed == ()


def test_close_by_id_closes_exactly_that_commitment():
    ledger, _ = record_misses((), ["a", "b"], on=MONDAY)

    ledger, closed = close_by_id(ledger, 2, on=TUESDAY, status=CommitmentStatus.DROPPED)

    assert closed.id == 2
    assert closed.status is CommitmentStatus.DROPPED
    assert [c.id for c in open_items(ledger)] == [1]


def test_close_by_id_rejects_an_unknown_id():
    with pytest.raises(ValueError, match="No commitment with id 9"):
        close_by_id((_open(1, "a"),), 9, on=TUESDAY)


def test_close_by_id_rejects_an_already_closed_commitment():
    ledger, _ = record_misses((), ["a"], on=MONDAY)
    ledger, _ = close_by_id(ledger, 1, on=TUESDAY)

    with pytest.raises(ValueError, match="already done"):
        close_by_id(ledger, 1, on=TUESDAY)


def test_open_items_are_oldest_first_and_exclude_closed_work():
    ledger, _ = record_misses((), ["first"], on=MONDAY)
    ledger, _ = record_misses(ledger, ["second"], on=TUESDAY)
    ledger, _ = close_by_title(ledger, ["first"], on=TUESDAY)

    assert [c.title for c in open_items(ledger)] == ["second"]


def test_stale_items_reports_only_the_old_open_ones_oldest_first():
    old = date(2026, 9, 1)
    ledger, _ = record_misses((), ["ancient"], on=old)
    ledger, _ = record_misses(ledger, ["recent"], on=date(2026, 9, 14))

    stale = stale_items(ledger, date(2026, 9, 15))

    assert [c.title for c in stale] == ["ancient"]


def test_an_empty_ledger_degrades_cleanly():
    assert open_items(()) == ()
    assert stale_items((), MONDAY) == ()
    assert record_misses((), [], on=MONDAY) == ((), ())


def test_match_key_and_normalize_title_agree_on_whitespace():
    assert normalize_title(" a   b ") == "a b"
    assert match_key(" A   B ") == "a b"


def test_record_misses_respects_an_id_floor():
    """Commitments share an id space with day plan items (ADR-008), and
    the ledger cannot see the ids a plan has handed out."""
    ledger, opened = record_misses((), ["call the supplier"], on=date(2026, 9, 7), first_id=10)

    assert [c.id for c in opened] == [10]
    assert [c.id for c in ledger] == [10]


def test_the_floor_never_lowers_ids_below_the_ledger():
    ledger, _ = record_misses((), ["first"], on=date(2026, 9, 7))
    ledger, opened = record_misses(ledger, ["second"], on=date(2026, 9, 7), first_id=1)

    assert [c.id for c in opened] == [2]


def test_successive_misses_under_a_floor_keep_climbing():
    _, opened = record_misses(
        (), ["one", "two", "three"], on=date(2026, 9, 7), first_id=7
    )

    assert [c.id for c in opened] == [7, 8, 9]


def test_omitting_the_floor_keeps_the_ledger_only_behaviour():
    ledger, _ = record_misses((), ["first"], on=date(2026, 9, 7))
    _, opened = record_misses(ledger, ["second"], on=date(2026, 9, 7))

    assert [c.id for c in opened] == [2]
