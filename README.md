# Life OS

[![tests](https://github.com/antoniodavignon-bit/life-os/actions/workflows/tests.yml/badge.svg)](https://github.com/antoniodavignon-bit/life-os/actions/workflows/tests.yml)

A personal operating system for goals, execution, income, and review.

Life OS turns ambition into a repeatable structure. Instead of relying on
motivation, it generates a daily task plan from your active goals, breaks
90-day goals into weekly milestones, tracks income, and closes the loop
with an end-of-day review that carries unfinished work forward.

**Plan → Execute → Track → Review → Repeat.**

## Quickstart

```bash
git clone https://github.com/antoniodavignon-bit/life-os.git
cd life-os
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Generate today's plan from your active goals:

```bash
$ life-os tasks --goal "grow the store" --goal "get in shape"
Today's plan
========================================

REVENUE
  - Execute a direct revenue action for: grow the store
  - Execute a direct revenue action for: get in shape

SKILL
  - Improve a skill related to: grow the store
  ...
```

Log income (persists between runs):

```bash
$ life-os profit add 250 --note "Gumroad sale"
Logged $250.00 - Gumroad sale
Total logged: $250.00

$ life-os profit report
Profit log
========================================
  2026-09-01 22:05  $    250.00  Gumroad sale
========================================
Total: $250.00 across 1 entries
```

Break a 90-day goal into weekly milestones:

```bash
$ life-os goals plan --title "Launch Life OS" --start 2026-09-01
Launch Life OS  [business]
2026-09-01 to 2026-11-29  (90 days)
==============================================
  Week  1  2026-09-01 to 2026-09-07 <- current
  Week  2  2026-09-08 to 2026-09-14
  ...
```

Close out the day and carry unfinished work forward:

```bash
$ life-os review log \
    --done "posted content" --done "called supplier" \
    --missed "wrote email sequence" \
    --priority "ship the landing page"
Review logged for 2026-09-01
  Completed: 2/3  (67%)

  Carrying forward to tomorrow (1):
    - wrote email sequence

  Tomorrow's #1: ship the landing page

$ life-os review week
Last 7 days
==============================================
  2026-09-01  2/3 done  ( 67%)
  2026-09-02  1/2 done  ( 50%)
==============================================
  2 reviews  |  3 completed  |  2 missed  |  60% completion
```

Data lives in `~/.life-os/state.json` by default; override with
`--state-file`.

## Modules

| Module | File | What it does |
|---|---|---|
| Task Engine | `src/life_os/tasks.py` | Generates a daily plan: revenue, skill, and maintenance tasks from active goals |
| Goal System | `src/life_os/goals.py` | Breaks a 90-day goal into weekly milestones; reports the current week |
| Profit Tracker | `src/life_os/profit.py` | Logs income entries, running totals, date-range summaries |
| Review System | `src/life_os/review.py` | End-of-day review, carry-forward of unfinished tasks, weekly stats |
| Persistence | `src/life_os/storage.py` | Atomic JSON state file — the only module that touches disk |
| CLI | `src/life_os/cli.py` | Presentation layer; all terminal output lives here |

## Architecture

```
src/life_os/     Domain modules (pure logic, no I/O) + storage + CLI
tests/           Automated tests, one module per file
docs/            Product and engineering documentation
  architecture/  Architecture Decision Records
```

Design rules, enforced across every module and documented in
[ADR-002](docs/architecture/ADR-002-domain-module-conventions.md):

- Frozen dataclasses for domain types
- **No I/O in domain logic** — no `print()`, no file access
- Injectable clock (`now=`, `today=`) so behavior is deterministic in tests
- Validation at construction: invalid state raises immediately
- Empty input degrades cleanly to zeroed results, never an exception
- Return copies, never internal state
- Every module ships with tests covering happy path, invalid input, and boundaries

### Decision records

- [ADR-001 — Project structure](docs/architecture/ADR-001-project-structure.md)
- [ADR-002 — Domain module conventions](docs/architecture/ADR-002-domain-module-conventions.md)
- [ADR-003 — JSON file persistence](docs/architecture/ADR-003-json-file-persistence.md)

The [engineering log](docs/engineering-log.md) records how each mission was
built and why the trade-offs were made.

## Testing

```bash
pytest -v          # 44 tests
ruff check src tests
ruff format --check src tests
```

CI runs lint, format check, and the full test suite across Python 3.11,
3.12, and 3.13 on every push and on pull requests into `main`
(`.github/workflows/tests.yml`).

## Roadmap

Life OS follows a mission-based development model — each mission is a
scoped, shippable unit of work.

- **Mission 001 — Core Foundation** ✅ src-layout package, all four PRD
  modules, pytest, CI, ADR process
- **Mission 002 — Usable System** ✅ persistence + CLI entry point
- **Mission 003 — Closed Loop** ✅ daily reviews in the CLI, carry-forward
  tasks, weekly completion rates, versioned state migration
- **Mission 004 — Portfolio Ready** ✅ ruff lint + format in CI, Python
  3.11-3.13 test matrix, MIT license, engineering log
- **Future — AI assistant layer** — generate tasks from goal context,
  surface execution patterns, answer "what should I do next?"

### State file versioning

The state file carries a `schema_version`. Version 1 (profit only)
upgrades cleanly to version 2 (adds reviews) on read. A version this
build does not recognize is rejected rather than partially read — a
file written by a newer build must never be silently loaded and saved
back with fields dropped.

## License

[MIT](LICENSE)
