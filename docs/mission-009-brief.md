# Mission 009 Brief — Record the Work, Not Just the Slot

- Status: Proposed, not started
- Written: 2026-09-07, after Mission 008 shipped
- Author's note: this is a brief, not an ADR. It states a problem and a
  proposed shape. The decisions below are recommendations with their
  reasoning exposed, not settled choices — the ADR gets written when the
  mission is built.

## The problem

Mission 008 made the day recordable. It did not make the *work*
recordable.

Every item on a day plan is generated from a template:

```
[1] Execute a direct revenue action for: Digital Dashers 2
[4] Improve a skill related to: Maestro Community
```

Closing `[1]` records that a revenue slot for Digital Dashers 2 was
filled. It does not record that you called a supplier, fixed a broken
checkout, or shipped twelve orders. The title is a category with a goal
name interpolated into it — it was never a description of work.

Two consequences:

1. **Nothing you actually did is written down.** `review week` can say
   you completed 4 of 9 on Monday. It cannot say what any of the four
   were. A year of use produces a completion-rate time series and no
   history.
2. **Work outside the templates is invisible.** There is no way to put
   "call the supplier" on today's plan. It can only enter the system by
   being *missed* — typed into `review log --missed` at night, where it
   becomes a commitment. The only path from real work to the ledger runs
   through failure.

The second one is the sharper problem. A user who does something not on
the plan gets no credit for it and leaves no trace of it.

## What exists to build on

- `PlanItem` (`day.py`) — entity with id, title, category, status,
  `closed_on`. Adding a field is cheap.
- `Category` — closed set: `REVENUE`, `SKILL`, `MAINTENANCE`,
  `UNSPECIFIED`. `UNSPECIFIED` already exists for hand-typed work and is
  the honest category for anything the user writes themselves (ADR-005).
- `record_misses` — opens commitments by title. An unfinished ad-hoc
  item would flow into the ledger through this path with no change, and
  title matching works *better* on user-written titles than on templates.
- `close_item` / `close_items_by_title` — already close anything on the
  plan by id or title.

## Proposed scope

### 1. `life-os add "<title>" [--category revenue|skill|maintenance]`

Puts a user-written item on today's plan. Draws an id from the shared
space (ADR-008), appends to today's plan, saves.

Defaults to `UNSPECIFIED` — Life OS was not told what kind of work it
was, and guessing would put a fabricated category into the state file.
The flag is there for users who want their ad-hoc work to sit in a
category alongside the generated items.

Everything downstream works unchanged: it shows in `today` and `open`,
closes with `done`/`drop`, counts in the completion rate, and becomes a
commitment if missed.

### 2. `life-os done <id> --note "<what you actually did>"`

Attaches a note to the closure. This is the answer for generated items,
which are going to keep existing: the template says the slot, the note
says the work.

`drop <id> --note "..."` should take one too — *why* something was
dropped is at least as worth keeping as why it was done.

### 3. A way to read it back

Notes are worthless if nothing displays them. Minimum: a `life-os day
[--date YYYY-MM-DD]` command that prints one day's plan with notes and
statuses. `review week` staying a numbers view is fine; the day view is
where the narrative lives.

## Design decisions to make

**A `source` field on `PlanItem` is probably required, not optional.**
`replan` rebuilds a day from goals and keeps existing items by title
match. An ad-hoc item's title is in no template, so on the current code
path an *open* ad-hoc item would be discarded by a replan while a closed
one survives. Losing user-typed work because they changed a goal at noon
is unacceptable. The fix is a field distinguishing `generated` from
`added`, with added items always surviving a rebuild. That field also
gives the display something honest to group on.

**Where notes live.** Recommend: on `PlanItem` only. Do not extend
`Task` — it is the pure value type `generate_tasks` returns, used by
anything that plans without state, and adding a note field to it would
push presentation data into the purest module in the codebase (ADR-002).
`DailyReview` keeps storing titles; the day plan is where the detail
lives, and the day view reads the plan.

**Whether ad-hoc items count toward the completion rate.** Recommend
yes. Adding something to today's plan is committing to it, and a
denominator you can pad by not adding work is a worse number than one
that can go down. Worth arguing.

**Whether `add` should be capped.** `MAX_ACTIVE_GOALS` limits goals, not
items. `CARRY_WARNING_THRESHOLD` warns on carried work. Neither covers
"added eleven things today." Probably needs no cap — it is self-inflicted
and visible — but it should be a deliberate decision rather than an
oversight.

**Schema v6.** Both a note and a source field change `PlanItem`
serialization. A v5 file upgrades trivially: missing note is empty,
missing source is `generated`, since every item written by v5 was.

## Explicitly out of scope

- **Whether templates should exist at all.** The deeper question under
  this mission is whether generating nine near-identical strings from
  three goal names is the right daily plan. It interacts with the
  standing PRD gap (9 tasks/day vs 3 per goal). Do not settle it here —
  notes and ad-hoc items make the current design livable either way, and
  changing generation is its own mission.
- **Pruning day plans.** Still open, still real (state grows ~9 items a
  day, and the id allocator's monotonicity depends on retention). It is
  the safer mission and the less valuable one.
- **Editing a note after the fact.** Re-closing is already an error. A
  `note` command that amends a closed item is a fair follow-up, not part
  of the first cut.

## Test surface worth writing

- An added item survives a `--replan` while open (the trap above).
- An added item that goes unfinished opens a commitment with its own
  title, not a template's.
- A note round-trips through the state file and shows in the day view.
- A dropped item's note is kept — dropping is a decision, and the reason
  is the decision (ADR-007, ADR-008).
- A v5 file loads with empty notes and every item marked `generated`.
- `add` with an empty or whitespace title is refused at construction,
  like every other title in the codebase.

## Why this over pruning

Pruning fixes a cost that has not been paid yet: at nine items a day the
state file takes years to become a problem. This mission fixes something
false today — a system that claims to track execution while recording
only which of nine slots got filled.

For a portfolio repo, "what did I actually do" is also the more
interesting question to have an answer to.
