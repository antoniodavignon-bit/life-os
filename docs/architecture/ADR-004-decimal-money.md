# ADR-004: Represent Money as Decimal

- Status: Accepted
- Date: 2026-09-04
- Decision: Profit amounts are `Decimal`, quantized to cents, and persist as strings

## Context

`ProfitTracker` stored amounts as `float`. Binary floating point cannot
represent most decimal fractions exactly — `0.1` is stored as
`0.1000000000000000055511151231257827` — so sums accumulate error:

```python
>>> 0.1 + 0.2
0.30000000000000004
```

The error is tiny per entry and invisible in `f"${x:,.2f}"` output,
which is precisely what makes it dangerous. It compounds silently in
the running total, and the display layer hides it until the number is
compared against something real — a bank statement, an invoice, a tax
filing.

The state file made it worse. Amounts were written as JSON floats, so
every save/load cycle re-parsed a binary approximation. Life OS is
small, but this is the module holding someone's income records. "Off
by a fraction of a cent" is the wrong default there.

Three related holes made the same class of bug reachable from other
directions:

- `ProfitTracker.entries` was a public mutable list, so
  `tracker.entries.append(...)` wrote straight past every check in
  `add_profit`.
- `storage._entry_from_dict` only cast to `float`. ADR-003 sells a
  hand-editable state file as a feature, so a negative amount typed
  into `state.json` loaded cleanly — rejected at the CLI, accepted
  from disk.
- The CLI parsed the amount with `type=float`, which happily accepts
  `nan` and `inf`. A single `NaN` entry makes every subsequent total
  `NaN` forever.

## Decision

1. **`Decimal` everywhere money is represented.** `ProfitEntry.amount`,
   `ProfitTracker.total`, and the CLI argument type.
2. **Quantize to cents on construction**, `ROUND_HALF_UP`. An amount
   finer than a cent is not a currency amount. An amount that rounds
   away to `0.00` is not positive money and is refused.
3. **Persist as strings.** `str(Decimal("0.10"))` round-trips exactly;
   a JSON float would silently undo the whole decision on the next
   load. This is schema version 3.
4. **Validate on the type, not the method.** `ProfitEntry.__post_init__`
   enforces positive, finite, cent-precision amounts, so the CLI, a
   test, and the state-file deserializer are all held to the same rule
   by construction rather than by three copies of the same check.
5. **`ProfitTracker.entries` returns an immutable snapshot.** The only
   way to add an entry is `add_profit`.
6. **Floats are tolerated at the boundary, not internally.** A `float`
   passed in is routed through `str()` first — `Decimal(str(0.1))` is
   `Decimal("0.1")`, the number the caller meant — rather than
   `Decimal(0.1)`, which is the binary artifact.

## Backward compatibility

Version 1 and 2 files hold JSON floats. They load: the raw value is
handed to `ProfitEntry`, which converts through `str()` and quantizes,
so `0.1` on disk becomes exactly `Decimal("0.10")`. The next save
writes version 3 with string amounts. No migration script, no data
loss, and a v3 file is still rejected loudly by older builds — the
guarantee ADR-003 and the version-2 bump established.

## Consequences

**Positive**
- Totals are exact. `0.10 × 10` is `1.00`, not `0.9999999999999999`.
- Invalid money cannot enter the system from any direction, including
  a hand-edited state file.
- `NaN` and `inf` are rejected at the CLI boundary with a usage error
  rather than a traceback or a poisoned total.

**Costs**
- `Decimal` is slower than `float`. Irrelevant at this data volume.
- Callers must not do arithmetic mixing `Decimal` and `float`; Python
  raises `TypeError` rather than silently coercing, which is the
  behavior we want.
- One more schema version to keep supported.

## Follow-ups

- Currency is implicit (single-currency, single-user). If Life OS ever
  logs income in more than one currency, the amount needs a currency
  code beside it — a `Money` value type, not a bare `Decimal`.
- `ProfitTracker.total_between` exists but the CLI does not expose a
  date-ranged report yet.
