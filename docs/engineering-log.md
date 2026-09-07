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

## Mission 006 — Close the Loop

**Problem.** `carry_forward()` had existed since Mission 001 and the CLI
printed its result from Mission 003, but `_run_tasks` never loaded
state. Yesterday's unfinished work was displayed once, at review time,
and then dropped. The README said Life OS "carries unfinished work
forward." It displayed it.

For a repository whose argument is that its documentation and its code
agree, that was the most expensive kind of gap.

**What was built.**

- `latest_review_before`, `carried_forward`, and a `CarryForward` value
  type in `review.py` (`ADR-006`)
- `upsert_review` — one review per date
- `life-os today` — carried work, the plan, and yesterday's priority
- `review log` corrects instead of duplicating, and says what it
  replaced
- `DailyReview` and `AppState` hold tuples
- `save_state` wraps filesystem failures as `StorageError`
- 24 new tests (77 → 101)

**Decision: `tasks` stays pure; `today` owns state.** The obvious fix
was to make `life-os tasks` load state. It was rejected. `tasks` has a
clean contract — generate a plan from these goals — and it is the
function a future API or AI planning layer will call. Adding
persistence changes what it means and makes the pure generator harder
to reuse.

That drew a line the codebase did not previously have: domain modules
are pure, `storage.py` is the only filesystem boundary, and within the
CLI only commands that are *about* history load state. `tasks` prints a
pointer to `today` so nobody concludes their carried work vanished.

**Decision: carried work is exempt from the goal limit, but warns.** A
carried task is work already committed to, not a new front being
opened. Counting it against `MAX_ACTIVE_GOALS` would mean a bad day
mechanically shrinks the next day's capacity — the system would punish
you for a rough Tuesday, which inverts what it is for.

The counter-argument is real: without a ceiling, a bad week compounds
into an eleven-item day and ADR-005's limit means nothing. So the
exemption ships with a pressure valve. Above three carried tasks,
`today` says plainly that you are behind rather than planning fresh,
and that the signal is to cut scope rather than add a goal. The
overload is surfaced, not absorbed — a number the user can see beats a
limit that silently rearranges their day.

**Decision: strictly before, not on-or-before.** `latest_review_before`
uses a strict date comparison. Log a review this morning, plan again
this afternoon, and a non-strict comparison would make the day inherit
its own misses and show work already accounted for. One character of
difference; a confusing bug either way.

**Decision: announce the correction, don't gate it.** `upsert_review`
replaces the review for a date and returns what it displaced, so the
CLI can report it. No `--force` flag — you are deliberately re-running
the command to fix a typo, and friction there is only friction.
Announcing loudly is the right guard; blocking is not.

**Smaller things closed in passing.** `DailyReview` and `AppState` both
held mutable lists behind `frozen=True`, which is a promise neither
could keep; both now hold tuples and coerce at the boundary.
`save_state` raised bare `OSError` on an unwritable path, so a
read-only directory produced a traceback rather than an error message —
it now wraps as `StorageError`, matching how `load_state` already
handled corrupt files, with a backstop in `main()`.

**No schema change.** Carry-forward and upsert read existing version 3
data. Nothing about the file format needed to move.

**Result.** 101 tests. `life-os today` runs the loop the README has
been describing since Mission 002.

---

## Mission 007 — The Commitment Ledger

**Problem.** Mission 006 made unfinished work reach the next day's plan
by re-reading the last review's `incomplete` list — a list of `Task`
values. That closed the loop but could not answer four questions: how
long have I been carrying this, is this the thing I missed on Monday,
did I ever do it, and am I allowed to decide it no longer matters.

The last one is the real cost. A tracker offering no way to deliberately
abandon something quietly pressures you into lying to it.

**What was built.**

- `commitments.py` — `Commitment` as an entity with identity, a status
  lifecycle, age, and staleness (`ADR-007`)
- Pure ledger functions: `record_misses`, `close_by_title`,
  `close_by_id`, `open_items`, `stale_items`
- `life-os open`, `life-os done <id>`, `life-os drop <id>`
- `review log` closes matching commitments and opens new ones
- Schema 3 → 4, seeding the ledger on upgrade
- `CarryForward`, `carried_forward`, and `carry_forward` deleted
- 48 new tests (101 → 149)

**Decision: a type was carrying two meanings.** `Task` is a value
object, correctly — today's generated revenue task is not yesterday's
instance of it, and asking whether they are "the same" is meaningless.
An unfinished obligation is not a value: it persists, it ages, it ends.
Using one type for both is the same mistake ADR-005 caught in a *field*,
one level up.

**Decision: integer ids, not UUIDs or content hashes.** A UUID is
unusable at a terminal. A content hash of title and date — the original
plan for this mission — is attractive because re-missing the same title
on the same day would be idempotent for free. But `record_misses` needs
a title lookup regardless, to decide whether a miss continues an open
commitment. The hash buys nothing already unpaid for, while adding a
collision risk to document and guard. `max(existing) + 1` has no
collisions by construction, and `life-os done 7` is a better thing to
type.

**Decision: a repeated miss ages one commitment.** Missing the same
thing four days running is one commitment aged four days, not four
commitments aged zero. `opened_on` keeps pointing at the day the
obligation first appeared, which is the entire reason the age means
anything. Missing something again *after* closing it opens a new
commitment — doing a thing and later failing to do it again is a new
obligation, and keeping both keeps the history honest.

**Decision: delete Mission 006's carry rather than keep both.**
`CarryForward` and `carried_forward` were written two commits earlier.
Display-only carry was the right minimum to make the loop close and is
the wrong maximum now. Two carry mechanisms in one codebase is worse
than either alone: they drift, and the next reader cannot tell which is
authoritative.

**Behavior change worth naming.** The ledger answers "what do I owe",
not "what did I inherit". Mission 006 compared review dates strictly
before today so a review logged this morning could not appear in this
afternoon's plan — necessary then, because inheriting your own day was a
display artifact of deriving carry from "the last review". The ledger
has no such artifact, so a commitment opened this morning is shown this
afternoon, aged zero days. `latest_review_before` keeps its strict
comparison because it answers a different question: `--priority` states
*tomorrow's* priority, so the relevant statement is from the last day
you closed out.

**Migration.** A pre-v4 file has its ledger seeded from the most recent
review's incomplete tasks only, dated to that review. Walking all of
history would resurrect months of dead items on first run, which is
worse than starting slightly light. An empty ledger written at v4 is not
reseeded, so dropping your last open item stays dropped. Verified
end-to-end against a real v3 file.

**Result.** 149 tests. Nine days of missing the same thing is one
commitment, nine days old, flagged stale, closable or droppable by id.

---

## Mission 008 — The Day Plan

**Problem.** Life OS could describe a day and record a day, but not run
one. `life-os today` generated nine tasks and printed them; nothing
recorded them. Finishing three of those tasks at 11am could not be
stated, because `done <id>` closes commitments and a generated task has
no id.

The tell, from a real terminal, two commands apart:

```
$ today
... 9 items, no ids ...
$ owe
Nothing outstanding.
```

Nine things to do and nothing outstanding. Both true under the old
model, which is how you know the model was missing a concept rather
than a feature.

**Decision: a day plan is an entity; a plan item is not a commitment.**
The shortcut was to write the nine generated tasks into the commitment
ledger and inherit ids, `open`, and `done <id>` for free. Rejected. A
`Commitment` is an obligation you *failed* to meet — that is what makes
`opened_on` mean anything and what `CARRY_WARNING_THRESHOLD` counts.
Nine fresh items every morning would mean owing work you had not yet
had a chance to do, and the "you are behind" warning, which fires above
three, would fire every single day. A warning that is always on is not
a warning. So `day.py` holds the middle of the loop, and unfinished
items become commitments at review time exactly as before.

**Decision: one id space, two collections.** `life-os done 4` must mean
one thing. Two id spaces would have been cheaper to build and worse to
type at. Day plans are retained rather than pruned, which is what keeps
the allocator monotonic without a stored counter.

**Two bugs the fixtures did not catch.** Both surfaced on the first run
against a copy of the real state file, and neither was visible in 218
passing tests.

The first: `record_misses` allocated from the ledger alone. On a
planned day the first miss was handed id 1 — already a plan item — so
`done 1` had two answers and the commitment was unreachable by id. One
id space means *every* allocator has to know about it. It now takes a
`first_id` floor.

The second: generated titles repeat verbatim, so the day after missing
"Improve a skill related to: X" the plan generates that exact string
again while the commitment is still open. The same obligation appeared
twice in one screen and in every count. The carried copy wins, because
it is the one with an age; `today` and `open` now hide an open plan
item that duplicates an open commitment, while always showing closed
ones. The stored plan is untouched — this is a view decision, and
hiding recorded work to tidy a list would be a data decision.

The general lesson is the one this repo keeps relearning: fixtures
agree with the assumptions that built them. The real file did not.

**Decision: `review log` reads the day instead of asking for it.**
Items closed done are completed, items still open are incomplete, and
dropped items are *neither* — recording a dropped item as missed would
reopen it as a commitment that night and silently overturn the decision
to drop it. `--done` and `--missed` survive as additions, and an
explicit `--done` settles the plan item it names so the two cannot
disagree. `--priority` stays required: it is the one thing the system
genuinely cannot infer.

This also repaired the correction path. `upsert_review` replaces a
review, so before the plan was authoritative, fixing one entry meant
retyping the other eight or silently losing them.

**Reviews got their categories back.** Titles typed by hand are
honestly `UNSPECIFIED`, but items the plan generated are not. The
review now stamps the real category when the title came from the plan,
which is data the system always had and used to throw away.

**Goal persistence, folded in.** `DayPlan` records the goals it was
generated from, so `today` with no `--goal` reuses the last plan's
goals. A dedicated `goals add`/`list`/`archive` surface was considered
and deferred: the plan already has to record its goals to be
reproducible, and a second store of active goals is a second thing to
keep in sync. `MAX_ACTIVE_GOALS` now limits something real instead of
the length of an argument list.

**Migration.** A pre-v5 file simply has no day plans. Unlike the v4
commitment migration there is nothing to seed from — no earlier version
ever recorded which of a day's items you closed, and reconstructing it
from reviews would invent per-item history the user never stated. The
seam that *does* need handling is the reverse order: every day in an
old file has a review and no plan, so a plan built for such a date
starts from what that review already recorded. Without it the first
`today` after upgrading would show work already reported done as still
open, and the next `review log` would replace an accurate review with
an empty one. Verified end-to-end against a real v4 file.

**Result.** 231 tests. Finish something at 11am, `life-os done 4`, and
the system knows — and closing out the day takes one required argument.

---

## Open threads

- **Correcting a review does not retract its commitments.**
  `upsert_review` replaces the review, but commitments opened by the
  version it replaced stay open. Fixing this needs a link from
  commitment to source review — a further data-model change.
- **Title matching is textual.** Rewording a commitment opens a second
  one. `life-os done <id>` is the escape hatch, which is why it exists
  alongside title matching.
- **Nothing prunes closed commitments.** The ledger only grows. Fine at
  personal scale; revisit if `open` ever gets slow to read.
- **Task generation vs. the PRD.** The PRD specifies 9 tasks per day
  (3 revenue / 3 skill / 3 maintenance). `generate_tasks` produces one
  task per category per goal, so a single active goal yields 3 tasks,
  not 9. Closing the gap is a product decision — templates per
  category, or requiring three active goals — not a bug fix.
- **Nothing prunes day plans.** State grows by nine items a day, and
  the id allocator's monotonicity currently depends on that. Pruning
  needs a stored high-water mark first.
- **A dropped plan item is invisible in `review week`.** It is excluded
  from the review entirely, so a day spent deliberately cutting scope
  reads the same as a day spent doing nothing.
- **No presentation layer beyond the CLI.** The domain modules would
  support a web UI or API unchanged; nothing has been built.
- **The AI layer is unstarted.** The intended shape is generating tasks
  from goal context and surfacing execution patterns across reviews and
  the commitment ledger — reading the same domain modules, not replacing
  their logic. The ledger is the richest signal it would have: what gets
  finished, what gets dropped, and how long things sit.
