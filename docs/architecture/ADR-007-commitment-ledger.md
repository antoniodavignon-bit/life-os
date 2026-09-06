# ADR-007: Unfinished Work Is an Entity, Not a Repeated Task

- Status: Accepted
- Date: 2026-09-06
- Decision: Introduce a `Commitment` ledger with integer identity, a status lifecycle, age, and staleness; retire Mission 006's display-only carry

## Context

Mission 006 made unfinished work reach the next day's plan. It did so by
re-reading the most recent review's `incomplete` list — a list of
`Task` values.

`Task` is a value object, correctly. Today's "Execute a direct revenue
action for: grow the store" is not yesterday's instance of that task; it
is a fresh one from the same template, and asking whether they are "the
same task" is meaningless.

An unfinished obligation is not a value. It persists, it ages, and it
ends. Representing both with `Task` meant Life OS could not answer:

- **How long have I been carrying this?** No `opened_on`, so no age.
- **Is this the thing I missed on Monday?** Two identical titles on
  two different days were unrelated values, so the carry chain was one
  link long — miss something Monday, forget to re-log it Tuesday, and
  it silently stopped existing.
- **Did I ever do it?** Nothing recorded closure. A task appeared in
  `incomplete` or it didn't.
- **Am I allowed to decide it no longer matters?** There was no way to
  say so. The only exit was to stop typing it, which is indistinguishable
  from forgetting.

That last one is the real cost. A tracker that offers no way to
deliberately abandon something quietly pressures you into lying to it.

This is the same class of mistake ADR-005 already caught once. There it
was a *field* carrying two meanings depending on who constructed it.
Here it is a *type*.

## Decision

### 1. `Commitment` is an entity with its own module

`commitments.py` holds `Commitment` — id, title, `opened_on`, status,
`closed_on` — plus pure ledger functions (`record_misses`,
`close_by_title`, `close_by_id`, `open_items`, `stale_items`). Tasks
stay values in `tasks.py`. Reviews record what happened on one day;
the ledger tracks obligations that outlive the day.

### 2. Identity is a small integer, not a UUID or a content hash

Both alternatives were considered and rejected.

A **UUID** is unusable at a terminal — nobody types
`life-os done 3f2b91c4-...`. A **content hash of title and date**
was the original plan for this mission, and it is attractive because
re-missing the same title on the same day would be idempotent for free.
But `record_misses` needs a title lookup regardless, to decide whether a
miss continues an existing commitment or opens a new one. So the hash
buys nothing that isn't already paid for, while adding a collision risk
to document and guard.

An **integer from `max(existing) + 1`** has no collisions by
construction, is trivially testable, and `life-os done 7` is a better
thing to type. Ids are never reused: commitments are closed, never
deleted, so the maximum only grows.

### 3. A miss continues an open commitment; it does not open a second

`record_misses` matches on a case- and whitespace-insensitive title key.
Missing the same thing four days running is **one commitment aged four
days**, not four commitments aged zero. `opened_on` keeps pointing at
the day the obligation first appeared, which is the whole reason the age
is meaningful.

Missing something again *after* closing it opens a new commitment. Doing
a thing and later failing to do it again is a new obligation, not a
reopening — and the ledger keeps both, so the history stays honest.

### 4. `DROPPED` is a first-class outcome

Not a failure state. Deciding something no longer matters is a real
decision and deserves a real verb (`life-os drop 3`). Age freezes at
`closed_on`, so a finished commitment's age stops moving.

### 5. Stale after 7 days

A full week of carrying something without finishing it. Long enough that
an ordinarily busy stretch does not generate noise; short enough that
nothing rots quietly for a month. `today` and `open` mark stale items
inline rather than in a separate block — two counts a reader has to add
together is a worse answer to "how much do I owe" than one number.

### 6. The ledger answers "what do I owe", not "what did I inherit"

This is a deliberate behavior change from Mission 006. `carried_forward`
compared review dates **strictly before** today, so a review logged this
morning could not appear in this afternoon's plan — necessary, because
carry was derived from "the last review" and inheriting your own day was
a display artifact.

The ledger has no such artifact. A commitment opened this morning is
work you owe this afternoon, and `today` shows it, aged zero days.

`latest_review_before` keeps its strict comparison, because it answers a
different question: `--priority` states *tomorrow's* top priority, so
the relevant statement is the one from the last day you closed out, not
one you set this morning for tomorrow.

### 7. Mission 006's carry mechanism is removed, not kept alongside

`CarryForward`, `carried_forward`, and `carry_forward` are deleted.
Mission 006's display-only carry was the right minimum to make the loop
close and is the wrong maximum now. Two carry mechanisms in one codebase
is worse than either alone — they drift, and the next reader cannot tell
which is authoritative.

## Schema version 4

`commitments` joins the state file. A file written before v4 has no
`commitments` key, and the ledger is **seeded from the most recent
review's incomplete tasks only**, with `opened_on` set to that review's
date — exactly the work the old build would have been carrying.

Walking every review in history was rejected: it would resurrect months
of long-dead items on the first run after upgrading, which is worse than
starting slightly light. An empty ledger explicitly written at v4 is not
reseeded, so dropping your last open item stays dropped.

## Consequences

**Positive**
- Carried work has an age, a chain longer than one link, and two ways to
  end.
- The two threads deferred in ADR-006 — aging-out and the one-link chain
  — both fall out of the data model rather than needing features.
- `life-os open` gives a standing answer to "what do I owe" that no
  command previously could.

**Costs**
- A fifth domain module and a fourth schema version. The ledger only
  grows; nothing prunes closed commitments.
- Title matching is textual. Rewording a commitment ("call supplier" vs
  "call the supplier") opens a second one. `life-os done <id>` is the
  escape hatch, which is why it exists alongside title matching.
- **Correcting a review does not retract commitments opened by the
  version it replaced.** `upsert_review` replaces the review; the ledger
  keeps what the earlier version opened. Fixing that needs a link from
  commitment to source review, which is a further data-model change.

## Follow-ups

- Link commitments to the review that opened them, so a corrected review
  can retract them.
- Nothing prunes or archives closed commitments. Fine at personal scale;
  revisit if `open` ever gets slow to read.
- The 9-task PRD gap remains open (ADR-005, engineering log).
