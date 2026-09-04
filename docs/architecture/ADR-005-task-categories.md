# ADR-005: Task Categories Are a Closed Set

- Status: Accepted
- Date: 2026-09-04
- Decision: `Task.category` is a `Category` enum; `generate_tasks` refuses excess goals rather than truncating

## Context

`tasks.py` was the first module written and the only one that never
came back into line with ADR-002, the conventions it helped produce.
Three problems, all of the same shape — the module accepted input it
should have refused:

**1. `category` was a free-form string.** `tasks.py` wrote `"revenue"`,
`"skill"`, `"maintenance"`. `cli.py` wrote `"completed"` and
`"carried"`. `storage.py` round-tripped whatever it was handed. Nothing
validated any of it, so `"revenu"` was as valid as `"revenue"`, and
once written to `state.json` it stayed valid forever. A typo became
permanent data.

The CLI's values exposed a second, deeper confusion:
`"completed"`/`"carried"` describe *where a task ended up*, not *what
kind of work it was* — and the outcome was already encoded by which
list of `DailyReview` the task sat in. The field was carrying two
different meanings depending on who constructed it.

**2. `Task` had no validation at all.** Every other domain type
validates in `__post_init__` (ADR-002, rule 4). `Task` accepted an
empty title.

**3. `generate_tasks` truncated silently.** It built one task per
category per goal and then returned `revenue_tasks[:3]`. Supply four
goals and the fourth contributed nothing — no tasks, no warning, no
error. This is the exact silent data loss that ADR-002 and ADR-003
were written to prevent, sitting in the module those ADRs came from.

The module also had one test while `storage.py` had twelve.

## Decision

1. **`Category` is a `StrEnum`** with four members: `REVENUE`, `SKILL`,
   `MAINTENANCE`, and `UNSPECIFIED`. A `StrEnum` so members serialize
   as plain JSON strings, keeping the state file readable and
   hand-editable per ADR-003.
2. **`UNSPECIFIED` is an honest unknown, not a fourth work type.** It
   covers tasks the user typed by hand at review time, where Life OS
   was never told what kind of work they were. The review outcome is
   expressed by `DailyReview.completed` vs `.incomplete` and nowhere
   else.
3. **`Task` validates at construction.** Empty titles raise; unknown
   categories raise; a category given as a string is normalized to the
   enum so a `Task` built from raw JSON is indistinguishable from one
   built in code.
4. **More than `MAX_ACTIVE_GOALS` (3) distinct goals raises
   `ValueError`.** Refusing is both the correct engineering answer —
   fail loudly rather than drop input — and the correct product
   answer: a day with five top priorities has none.
5. **Goals are normalized before the limit applies:** trimmed, blanks
   dropped, de-duplicated case-insensitively, preserving the first
   spelling the user gave. Four entries naming two distinct goals
   produce a plan, not a rejection.
6. **`DailyPlan` fields are tuples.** A frozen dataclass wrapping
   mutable lists is a promise it cannot keep.
7. **An empty goal list still yields an empty plan** rather than
   raising (ADR-002, rule 5). A day with nothing active is a real
   outcome.

## Backward compatibility

State files written before this ADR contain review tasks with category
`"completed"` or `"carried"`. `storage.LEGACY_CATEGORY_ALIASES` maps
both to `Category.UNSPECIFIED` on load. Any *other* unrecognized
category is rejected as a malformed file rather than silently
accepted — the alias table is a migration, not a permissive fallback.

## Consequences

**Positive**
- A mistyped category is impossible to persist.
- `tasks.py` now satisfies the conventions it originally motivated.
- Duplicate and blank goals no longer inflate the plan.

**Costs**
- Refusing a fourth goal is a behavior change a user can hit at the
  terminal. It is a clear error with a clear instruction, which is the
  point, but it is not silent as before.
- `MAX_ACTIVE_GOALS = 3` is a product opinion baked into the domain.
  It is a named constant so the argument happens in one place.

## Follow-ups

- **The 9-task PRD gap remains open.** The PRD specifies 9 tasks per
  day (3 per category); one goal still yields 3 total. Closing it means
  either task templates per category or requiring three active goals —
  a product decision, not a bug fix. Tracked in the engineering log.
- `DailyReview` still holds mutable lists behind `frozen=True`; the
  same tuple treatment applies and is queued behind the carry-forward
  work.
