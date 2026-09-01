# ADR-003: Single JSON File for Persistence

- Status: Accepted
- Date: 2026-09-01
- Decision: Persist state to one JSON file, written atomically

## Context

The domain modules held no state between runs. A profit tracker whose
total resets when the process exits is a demo, not a tracker — so
Life OS needed persistence before a CLI was worth building.

Constraints that shaped the choice:

- Development happens on a MacBook Air with limited RAM. Running a
  database server for a single-user personal tool is disproportionate.
- ADR-002 forbids I/O inside domain logic, so persistence has to live
  in its own layer regardless of the backing store.
- The data is small: a few thousand profit entries and daily reviews
  over a year, measured in kilobytes.
- A user should be able to open, inspect, back up, or hand-edit their
  own data. It is *their* life data, not an opaque blob.

Options considered:

| Option | Why not (for now) |
|---|---|
| SQLite | Real option, and the likely successor. Adds schema migrations and a query layer before there is any query pressure. |
| Postgres/server DB | Disproportionate infrastructure for a single-user local tool. |
| One file per record | More filesystem churn, no benefit at this data size. |
| **Single JSON file** | **Chosen.** Human-readable, zero dependencies, trivially backed up. |

## Decision

State lives in a single JSON file, `~/.life-os/state.json` by default,
overridable via `--state-file`.

- **`storage.py` is the only module that touches the filesystem.**
- **Writes are atomic.** Content is written to a temp file in the same
  directory, then `os.replace()`d over the target. An interrupted write
  cannot leave a half-written state file, and a crash loses at most the
  in-flight change, never the existing data.
- **A missing file is not an error.** First run yields empty state.
- **A corrupt or unknown-version file raises `StorageError`.** It is
  never silently overwritten — losing a user's logged income to a parse
  error would be a data-loss bug, not graceful degradation.
- **The file carries `schema_version`.** Reading a version this build
  does not understand fails loudly, giving a future migration a hook.

## Consequences

**Positive**
- No dependencies, no server, no migration tooling at this stage.
- Users can read, back up, diff, or hand-edit their own data.
- Atomic writes make the common crash case safe.

**Costs**
- The whole file is rewritten on every save. Fine at kilobytes;
  it will not be at tens of megabytes.
- No concurrent-writer safety. Two Life OS processes writing at once
  can lose one side's change (last writer wins). Acceptable for a
  single-user CLI; not acceptable if this grows a daemon or web UI.
- No querying — reads load everything into memory.

## When to revisit

Move to SQLite when any of these becomes true:

- The state file exceeds roughly 5 MB, or saves become perceptibly slow.
- More than one process needs to write concurrently (daemon, web UI,
  scheduled automation).
- Reporting needs real queries — date-range aggregation across a large
  history, joins between goals, tasks, and reviews.

The `schema_version` field and the fact that `storage.py` is the sole
I/O boundary are what make that migration a contained change.
