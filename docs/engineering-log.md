# Engineering Log

A running record of how Life OS was built — what changed, why, and what
the trade-offs were. Written for another engineer reading the repo cold.

Development follows a **mission model**: each mission is a scoped,
shippable unit of work, developed on its own branch, verified by CI, and
merged to `main` with a merge commit that marks the boundary.

---

## Mission 001 — Core Foundation

**Problem.** Life OS existed as a folder of markdown product docs plus two
standalone Python scripts. It had been pushed to GitHub from the wrong
working directory, so every file sat nested under a stray `Desktop/life-os/`
path inside the repo. There was no package, no tests, and no way to run
anything as software.

**What was built.**

- A `src/` layout Python package (`ADR-001`)
- The four PRD modules as real domain code:
  `tasks.py`, `goals.py`, `profit.py`, `review.py`
- pytest, with tests for each module
- GitHub Actions running the suite on every push
- The ADR process itself

**Technical problem worth noting.** Two of the four modules were ports of
existing scripts, and those scripts were untestable by construction: they
mixed domain logic with `print()` output, called `datetime.now()` inside
business logic, and executed demo data at import time. Porting them meant
separating three concerns that had been fused — computation, time, and
presentation.

That separation became `ADR-002`, which fixes the conventions every module
follows: frozen dataclasses, no I/O in domain logic, an injectable clock,
validation at construction, clean degradation on empty input, and returning
copies rather than internal state.

**Result.** 18 tests, CI green, `main` carrying a clean package instead of a
misplaced directory tree.

---

## Mission 002 — Usable System

**Problem.** Four well-tested modules that nobody could run. There was no
entry point and no persistence — a profit total that resets when the
process exits is a demo, not a tracker.

**What was built.**

- `storage.py` — atomic JSON persistence, the single filesystem boundary
- `cli.py` — the `life-os` command, with `tasks`, `profit`, and `goals`
- `ADR-003` recording the persistence decision
- A real README

**Decision: JSON file over SQLite.** The data is kilobytes, the tool is
single-user and local, and the development machine is a laptop with limited
RAM. Running a database for this would be disproportionate. JSON is also
inspectable and hand-editable, which matters when the data is someone's own
life and income records.

The costs were accepted explicitly rather than discovered later: the whole
file is rewritten per save, concurrent writers would lose data
(last-writer-wins), and there is no querying. `ADR-003` names the specific
conditions that should trigger a move to SQLite.

**Decision: atomic writes.** Content is written to a temp file in the same
directory and then `os.replace()`d over the target. An interrupted write
cannot leave a half-written state file. For a tool holding someone's income
log, a crash mid-save losing everything would be unacceptable.

**Related principle.** A corrupt state file raises `StorageError` rather
than being silently overwritten with empty state. Silently discarding a
user's data is a data-loss bug wearing the costume of graceful degradation.

**Result.** 34 tests, a working CLI verified end-to-end against the
installed console script — not just in-process.

---

## Mission 003 — Closed Loop

**Problem.** The review module existed but had no way in. Without it the
daily cycle never closed: you could plan and track, but not review, and
unfinished work had nowhere to go.

**What was built.**

- `life-os review log` and `life-os review week`
- Reviews persisted to state
- State schema versioned 1 → 2

**Decision: bump the schema version for an additive change.** Adding
reviews to the state file did not technically require a version bump —
version 1 files load fine under the new code. The bump protects the other
direction. A version 2 file opened by version 1 code would have loaded
happily, ignored the reviews, and destroyed them on the next save. Failing
loudly on an unknown version beats losing data quietly.

`SUPPORTED_VERSIONS` accepts both, so existing state files keep working.
The upgrade path was verified against a real version 1 file, not a
synthetic one.

**Result.** 44 tests. The full cycle — Plan → Execute → Track → Review →
Repeat — runs from the terminal.

---

## Mission 004 — Portfolio Ready

**Problem.** The repository was sound but under-presented: no license, no
linting, tests running on a single Python version, and no record of how any
of it was decided.

**What was built.**

- `ruff` linting and formatting, enforced in CI
- Test matrix across Python 3.11, 3.12, and 3.13
- MIT license
- This log

**Decision: a deliberate lint rule set, not the default.** Enabling ruff
surfaced 17 findings, 13 of which were one rule — `DTZ`, requiring
timezone-aware datetimes. That is a real design question, not noise, and it
deserved an answer rather than a blanket suppression.

The answer: Life OS is a single-user local tool. A naive local timestamp is
exactly what someone means by "I logged this at 2pm." Making datetimes
timezone-aware would change the persisted format for no present benefit. So
`DTZ` is deliberately excluded, with the reasoning written into
`pyproject.toml` and a note on when to revisit — if state ever syncs across
devices or time zones.

The remaining findings were real and were fixed.

---

## Mission 005 — Task and Profit Hardening

**Problem.** Four merged missions had built the structure. A review of
the codebase against its own ADRs found the oldest module had never
come back into line with them, and the module holding real money was
using the wrong numeric type.

**What was built.**

- `Category` enum replacing free-form category strings (`ADR-005`)
- `Task` validation at construction
- `generate_tasks` refusing excess goals instead of truncating
- Goal normalization: trim, drop blanks, de-duplicate
- `Decimal` money, quantized to cents, persisted as strings (`ADR-004`)
- `ProfitTracker.entries` encapsulated behind an immutable snapshot
- Deserializer validation, so the state file is held to the domain rules
- State schema versioned 2 → 3
- 33 new tests (44 → 77); `tasks.py` went from 1 test to 15

**Decision: refuse a fourth goal rather than drop it.** `generate_tasks`
ended with `revenue_tasks[:3]`. Four goals in, three goals' worth of
tasks out, no warning. That is the same silent data loss ADR-002 and
ADR-003 were written to prevent, sitting in the module those ADRs came
from — the truncation was written before the conventions existed and
never revisited.

Raising is also the better product answer. A day with five top
priorities has none. The error names the limit and says what to do.
The cost is a behavior change a user can hit at the terminal, which is
why goals are normalized first: four entries naming two distinct goals
produce a plan, not a rejection.

**Decision: `Decimal` for money, strings on disk.** `0.1 + 0.2` is
`0.30000000000000004`. The error is invisible behind `f"${x:,.2f}"`,
which is what makes it dangerous — it compounds in the running total
and only surfaces when the number meets a bank statement. Persisting
as JSON floats made every save/load re-parse an approximation, so the
fix had to reach the state file, not just the domain type. `ADR-004`
records the full reasoning, including why floats are still accepted at
the boundary (routed through `str()`) but never used internally.

**Decision: validate on the type, not the method.** The old code
checked `amount > 0` inside `add_profit`. That left two other doors
open: `tracker.entries.append(...)` on the public list, and
`storage._entry_from_dict`, which only cast to `float`. ADR-003 sells
a hand-editable state file as a feature — which only holds if
hand-edited nonsense is rejected on the way back in. Moving validation
into `ProfitEntry.__post_init__` closes all three doors with one rule
instead of three copies of it.

**Smaller thing worth noting.** The CLI parsed the amount with
`type=float`, which accepts `nan` and `inf`. One `NaN` entry makes
every subsequent total `NaN` permanently. `Decimal("NaN")` parses just
as cleanly, so switching type alone would not have fixed it — the
argument parser now rejects non-finite values explicitly.

**Backward compatibility.** Version 1 and 2 files load unchanged:
float amounts convert through `str()` to exact cents, and the
pre-ADR-005 review categories `"completed"`/`"carried"` map to
`Category.UNSPECIFIED`. Any other unknown category is rejected — the
alias table is a migration, not a permissive fallback. Verified
end-to-end against a real version 2 file, not a synthetic one.

**Result.** 77 tests, ruff clean, CLI verified against a legacy state
file through the installed console script.

---

## Open threads

- **Carry-forward does not carry forward.** `carry_forward()` returns
  the incomplete tasks and the CLI prints them at review time, but
  `life-os tasks` never loads state — it plans from `--goal` arguments
  alone. Unfinished work is displayed and then dropped. The README
  claims the loop closes; in software it does not. This is the largest
  gap between the documentation and the code and is the next mission.
- **Reviews have no uniqueness on date.** `review log` twice in one day
  appends two reviews, and `review week` double-counts them. Needs an
  upsert keyed on `review_date`.
- **Task generation vs. the PRD.** The PRD specifies 9 tasks per day
  (3 revenue / 3 skill / 3 maintenance). `generate_tasks` produces one
  task per category per goal, so a single active goal yields 3 tasks,
  not 9. Closing the gap is a product decision — templates per
  category, or requiring three active goals — not a bug fix.
- **`frozen=True` over mutable lists.** `DailyReview` and `AppState`
  still hold lists behind frozen dataclasses, so the immutability is
  nominal. `DailyPlan` was converted to tuples in Mission 005; the same
  treatment is queued behind the carry-forward work.
- **`cli.main()` does not catch `OSError`.** An unwritable or
  permission-denied state file prints a raw traceback instead of a
  clean error. `load_state` now wraps read errors as `StorageError`;
  the write path does not.
- **No presentation layer beyond the CLI.** The domain modules would
  support a web UI or API unchanged; nothing has been built.
- **The AI layer is unstarted.** The intended shape is generating tasks
  from goal context and surfacing execution patterns across reviews —
  reading the same domain modules, not replacing their logic.
