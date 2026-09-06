# ADR-006: Carry-Forward Semantics and Where State Enters the CLI

- Status: Accepted
- Date: 2026-09-06
- Decision: `tasks` stays pure and `today` owns persisted state; carried work is exempt from the goal limit but warns above a threshold; a date has exactly one review

## Context

`carry_forward()` had existed since Mission 001 and `life-os review log`
printed its result from Mission 003. But `_run_tasks` never loaded
state — it planned from `--goal` arguments and nothing else. Yesterday's
unfinished work was displayed once, at review time, and then dropped.

The README said Life OS "carries unfinished work forward." It displayed
it. For a repository whose whole argument is that documentation and
code agree, that was the most expensive kind of gap.

Two smaller defects sat next to it:

- **Reviews were append-only with no key on date.** Running
  `review log` twice in one day stored two reviews, and
  `summarize_week` counted the day twice. The resulting completion rate
  was arithmetically correct and factually wrong.
- **Nothing decided what carried work means for capacity.** ADR-005
  established `MAX_ACTIVE_GOALS = 3` and made exceeding it an error. If
  carried tasks were simply added to a plan, the ceiling that ADR
  introduced would be silently uncapped.

## Decision

### 1. `tasks` stays pure; `today` is the stateful command

The obvious fix — make `life-os tasks` load state — was rejected.
`tasks` has a clean contract: *generate a plan from these goals*. It is
pure, deterministic, scriptable, and it is the function a future API or
AI planning layer will call. Adding persistence changes what it means
and makes the pure generator harder to reuse.

Instead `life-os today` is the stateful view that closes the loop:
carried work, today's plan, and the priority you stated yesterday.
`tasks` prints a pointer to it so nobody concludes their carried work
has vanished.

This draws a line the codebase did not previously have: **domain
modules are pure, `storage.py` is the only filesystem boundary, and
within the CLI only commands that are *about* history load state.**

### 2. Carry-forward selection is domain logic, not presentation

`review.py` gains `latest_review_before`, `carried_forward`, and a
`CarryForward` value type. Deciding *which* review a day inherits from,
and whether the inherited pile is too big, is reasoning about the
domain. Only the wording of the warning belongs to the CLI, which is
the ADR-002 line held exactly where ADR-002 puts it.

`latest_review_before` compares **strictly** before the given day. Log a
review this morning, plan again this afternoon, and without strictness
the day would inherit its own misses and show work already accounted
for.

### 3. Carried work does not count against `MAX_ACTIVE_GOALS`

A carried task is work already committed to, not a new front being
opened. Counting it would mean a bad day mechanically shrinks the next
day's capacity — the system would punish you for a rough Tuesday, which
inverts what it is for.

The honest counter-argument: without a ceiling, a bad week compounds
into an eleven-item day and the limit ADR-005 introduced means nothing.

So the exemption comes with a pressure valve. Above
`CARRY_WARNING_THRESHOLD` (3) carried tasks, `today` says plainly that
you are behind rather than planning fresh, and that the signal is to
cut scope rather than add a goal. **The overload is surfaced, not
absorbed.** A number the user can see is worth more than a limit that
silently rearranges their day.

### 4. A date has exactly one review

`upsert_review` replaces any existing review for the same date and
reports what it displaced, so the CLI can announce the correction. No
`--force` flag: you are deliberately re-running the command to fix a
typo, and friction there is only friction. Announcing loudly is the
right guard; blocking is not.

Reviews are returned sorted by date, so callers get a stable order
regardless of the sequence entries arrived in.

## Consequences

**Positive**
- The documented loop is the implemented loop. Unfinished work reaches
  the next day's plan.
- The weekly completion rate counts each day once.
- `tasks` remains a pure function a future API or AI layer can call
  unchanged.
- The immutability claims in `DailyReview` and `AppState` became real
  in the same pass — both held mutable lists behind `frozen=True`.

**Costs**
- Two commands now overlap in what they show. `today` is the one to
  run; `tasks` is the primitive underneath it. The pointer line in
  `tasks` is doing real work and should not be removed.
- `CARRY_WARNING_THRESHOLD` is a second product opinion baked into the
  domain, alongside `MAX_ACTIVE_GOALS`. Named constant, one place to
  argue about it.
- Carry-forward always looks at the single most recent prior review. A
  task missed on Monday and not re-logged on Tuesday stops being
  carried — the chain is one link long.

## Follow-ups

- **Carried work is displayed, not tracked.** `today` shows it; nothing
  records whether you did it. Closing that means carried tasks become
  first-class entries with identity, which is a data-model change, not
  a display change.
- **No aging-out.** A task carried for two weeks looks exactly like one
  carried since yesterday. A staleness prompt — "carried 6 days, commit
  or kill it" — was considered and deferred.
- **The 9-task PRD gap remains open** (see ADR-005 and the engineering
  log).
