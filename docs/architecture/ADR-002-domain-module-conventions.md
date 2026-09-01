# ADR-002: Domain Module Conventions

- Status: Accepted
- Date: 2026-09-01
- Decision: Standardize how `src/life_os/` domain modules are written

## Context

The four PRD modules now exist as code:

| Module | File | PRD module |
|--------|------|------------|
| Task Engine | `tasks.py` | 1 |
| Goal System | `goals.py` | 2 |
| Profit Tracker | `profit.py` | 3 |
| Review System | `review.py` | 4 |

Two of these were ported from standalone scripts in
`Automation_Scripts/`. Those scripts mixed domain logic with terminal
output (`print()` with emoji), called `datetime.now()` internally, and
executed demo data at import time — none of which can be tested or
reused by a future UI, CLI, or AI layer.

Rather than rediscover the same conventions for each new module, they
are fixed here.

## Decision

Domain modules under `src/life_os/` follow these rules:

1. **Dataclasses for domain types.** `@dataclass(frozen=True)` by
   default; mutable only where the type genuinely accumulates state
   (e.g. `ProfitTracker.entries`).
2. **No I/O in domain logic.** No `print()`, no file access, no network.
   Formatting and presentation belong to a caller (future CLI/UI).
3. **Injectable clock.** Anything time-dependent takes the date or
   time as a parameter (`now=`, `today=`), defaulting to the real
   clock only at the boundary. This keeps behavior deterministic
   under test.
4. **Validate at construction.** Invalid domain state raises
   `ValueError` immediately (`__post_init__` or the mutating method)
   rather than propagating bad data — e.g. non-positive profit
   amounts, zero-day goals, empty next-day priority.
5. **Degrade cleanly on empty input.** Empty collections return a
   zeroed result, not an exception — an empty day or week is a real
   outcome, not an error. (`completion_rate` on zero tasks returns
   `0.0`; `summarize_week([])` returns a zeroed summary.)
6. **Return copies, not internals.** Functions returning collections
   return new lists so callers cannot mutate stored state.
7. **Every module ships with tests**, covering the happy path, at
   least one invalid input, and at least one boundary/empty case.

## Consequences

**Positive**
- Every module is unit-testable without mocks, fixtures, or fake clocks.
- A future CLI, API, or AI planning layer can consume these modules
  without inheriting terminal-output assumptions.
- Deterministic tests — no flakiness from real timestamps.

**Costs**
- Slightly more verbose than the original scripts (explicit date
  parameters, separate presentation).
- Callers must handle formatting themselves; there is currently no
  presentation layer, so scripts using these modules will need one.

## Follow-ups

- The original `Automation_Scripts/*.py` remain in git history but are
  superseded by `src/life_os/`; a CLI entry point should replace their
  runnable behavior.
