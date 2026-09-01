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

## Open threads

- **Task generation vs. the PRD.** The PRD specifies 9 tasks per day
  (3 revenue / 3 skill / 3 maintenance). `generate_tasks` produces one task
  per category per goal, capped at 3 — so a single active goal yields 3
  tasks, not 9. The printed playbook resolves this by giving the user 9
  blank slots to fill. Closing the gap in software is a product decision
  (templates? require three goals?), not a bug fix.
- **No presentation layer beyond the CLI.** The domain modules would
  support a web UI or API unchanged; nothing has been built.
- **The AI layer is unstarted.** The intended shape is generating tasks
  from goal context and surfacing execution patterns across reviews —
  reading the same domain modules, not replacing their logic.
