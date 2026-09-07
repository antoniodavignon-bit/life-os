# ADR-008: The Day Plan — Persisting the Day in Flight

- Status: Accepted
- Date: 2026-09-07
- Decision: the generated day becomes a persisted entity with per-item identity; plan items and commitments share one id space; `review log` derives the day's outcome from item state; active goals persist on the plan

## Context

Seven missions in, Life OS could describe a day and record a day, but
not *run* one.

`life-os today` generated nine tasks and printed them. Nothing recorded
them. A user who finished three of those tasks at 11am had no way to
say so: `life-os done <id>` closes commitments, and a generated task
has no id because `Task` is a value, not an entity (ADR-007). The only
place completion could be stated was `review log` at night — by
retyping the task titles from memory.

The observed failure, in the user's own terminal:

```
$ today
... 9 items, no ids ...
$ owe
Nothing outstanding.
```

Nine things to do and nothing outstanding, one command apart. Both
statements are true under the current model, which is the tell that the
model is missing something.

Two consequences followed:

- **`open` was dead weight during the day.** It answers "what did I
  fail to do", which before the first `review log` of the day is
  nothing. At 2pm it could not say where you stood.
- **`review log` demanded the whole day back as arguments.** Nine
  `--done`/`--missed` strings, retyped, after `upsert_review` had
  already made a second run replace the first — so a correction meant
  retyping *everything*, not just the correction.

A third defect sat beside them: **active goals were never stored.**
`today --goal A --goal B --goal C` had to re-declare every goal on every
run, `goals plan` was disconnected from `today` entirely, and
`MAX_ACTIVE_GOALS` capped an argument list rather than anything real.
The user's shell alias existed solely to paper over this.

## Decision

### 1. A day plan is an entity, not a render

`day.py` (Module 6) adds `PlanItem` and `DayPlan`. `today` builds the
plan once for a date, assigns each item an id, and saves it. Re-running
`today` shows the same plan with the same ids rather than generating a
new one.

This is the entity/value line ADR-007 drew, applied one level up. A
`Task` remains a value — the pure output of `generate_tasks`, unchanged
and still scriptable. A `PlanItem` is that value admitted into a
specific day, where it acquires identity, a status, and a closing date.
`generate_tasks` did not change; `day.build_plan` wraps it.

### 2. Plan items are not commitments

The tempting shortcut was to write the nine generated tasks straight
into the commitment ledger and get ids, `open`, and `done <id>` for
free. It was rejected.

A `Commitment` is an obligation you *failed to meet* — that is what
gives `opened_on` meaning, what `STALE_AFTER_DAYS` measures, and what
`CARRY_WARNING_THRESHOLD` counts. Nine fresh plan items every morning
would mean owing work you had not yet had a chance to do, and the
"you are behind, not planning fresh" warning — which fires above three
open items — would fire every single day. A warning that is always on
is not a warning.

So the two stay separate. A plan item that goes unfinished becomes a
commitment at review time, through `record_misses`, exactly as before.
Its title travels; its id does not, because `record_misses` matches by
title so a repeated miss ages one commitment (ADR-007) rather than
opening a new one per day.

### 3. One id space, two collections

`life-os done 4` must mean one thing. Plan items and commitments are
therefore allocated from a single monotonic id space: the next id is
one past the highest in use anywhere, and `done`/`drop` resolve against
today's plan first, then the ledger.

Two id spaces would have been cheaper to implement and worse to type
at — `done 4` would need to ask which 4, or the user would need to know
which list a number came from.

Keeping every day plan in state (rather than only today's) is what
makes the allocator monotonic without a stored counter, and it is
consistent with reviews, which are already retained in full.

**`record_misses` participates in the same allocation.** This was found
by running the mission against a real state file rather than a fixture.
`record_misses` derived ids from the ledger alone, so the first
commitment opened on a planned day was handed id 1 — already in use by
a plan item. `life-os done 1` then had two answers, and the commitment
became unreachable by id. It now takes a `first_id` floor, which the
CLI computes across both collections. One id space means every
allocator has to know about it, not just the one that motivated it.

### 4. Work already owed is listed once

Generated titles repeat word for word: plan for the same goal two days
running and the second day's items are identical strings to the first
day's. So the day a commitment exists for "Improve a skill related to:
X", the freshly generated twin sits beside it in the same output — one
obligation listed twice, inflating every count that touches it.

The carried copy wins, because it is the one with an age. `today` and
`open` hide an *open* plan item whose title matches an open commitment;
closed items are always shown, because they are what the day actually
recorded. This is a view, not a mutation — the stored plan keeps every
item it was built with.

The alternative, excluding owed titles at generation time, was
rejected: it would make the stored plan depend on ledger state at the
moment `today` first ran, so the same day would have a different
recorded plan depending on when you looked at it.

### 5. `review log` reads the day rather than asking for it

When a plan exists for the review date, `--done` and `--missed` become
*additions* to what the plan already knows:

- items closed `done` → completed
- items still open → incomplete
- items closed `dropped` → **neither**

Dropping is a decision, not a failure (ADR-007). Counting a dropped
item as missed would reopen it as a commitment at review time and
silently overturn the decision. Excluding it from the completion rate
too, rather than scoring it as a loss, follows from the same argument.

`--priority` stays required. It is the one thing the system genuinely
cannot infer.

This also repairs the correction path: re-running `review log` re-reads
item state, so fixing one entry no longer means retyping the other
eight.

### 6. Goals persist on the plan

`DayPlan` records the goals it was generated from, so `today` with no
`--goal` reuses the most recent plan's goals. `--goal` remains a
one-off override, and `--replan` rebuilds today from new goals,
carrying the status of any item whose title survives the rebuild.

A dedicated `goals add`/`list`/`archive` surface was considered and
deferred. The day plan already has to record its goals to be
reproducible; deriving persistence from that is a property of a
decision already made, and a second store of active goals would be a
second thing to keep in sync.

## Consequences

**Positive**
- The daily loop closes at the granularity it is lived at. Finish
  something at 11am, `lo done 4`, and the system knows.
- `open` answers "where do I stand" all day, not just after a review.
- `review log` on a planned day needs one required argument.
- `MAX_ACTIVE_GOALS` now limits stored active goals rather than the
  length of an argument list.
- The alias the user wrote to work around goal amnesia is retired.

**Costs**
- A sixth domain module and a fifth schema version.
- **State grows by nine items a day.** Nothing prunes day plans, and
  the id allocator's monotonicity currently depends on that. Pruning
  needs a stored high-water mark first.
- `today` is no longer a pure read. Running it writes state, which
  makes it the command that starts the day rather than one that
  reports on it. `life-os tasks` remains the pure, non-writing view.
- A plan built for a date that already has a review starts from what
  that review recorded, so the two stores cannot disagree. This is the
  upgrade path: every day in a pre-v5 file has a review and no plan.
- Changing goals mid-day requires `--replan` rather than just passing
  different `--goal` flags. Silently rebuilding would discard the
  morning's closed items; refusing outright would break every alias
  that passes `--goal` unconditionally. The flag is the honest middle.

## Follow-ups

- Prune or archive old day plans, with a stored high-water mark so ids
  stay unique once history is dropped.
- A dropped plan item is excluded from the review entirely. It may
  deserve its own line in `review week` — visible decisions rather than
  invisible ones.
- The 9-task PRD gap remains open (ADR-005, engineering log).
