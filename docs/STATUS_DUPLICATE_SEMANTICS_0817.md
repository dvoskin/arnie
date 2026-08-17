# Status — duplicate-turn semantics · 2026-08-17

**For team review. Summary only; the working record is
`docs/HANDOVER_DUPLICATE_TURN_0816.md`.**

| | |
|---|---|
| Deployed | `29ba0e1` on `main`, live and confirmed via `/health` |
| Verified | In production, user 26, iOS — **both settlement branches** (13:10 legacy, 13:26–13:37 canonical) |
| Cohort | 1 user (26), iOS only — unchanged |
| Tests | 9428, dual-engine, **both engines collected identically**: Postgres 9399 passed / 0 failed · SQLite 9317 passed / 0 failed |

**Duplicate semantics are closed.** ⛔ **But `main` CI is RED at `29ba0e1` and `7059fbc`** — see the open list; the freeze commit is the fix.

---

## What was wrong

Two user-visible defects, both on repeated food messages.

**1. A duplicate read as an outage.** Re-sending the same food answered
*"Something went sideways on my end. Resend that and I'll catch it."* — an
instruction to retry the one thing that cannot succeed. The meal was already on
the board; nothing had failed.

**2. A re-cased message slipped the duplicate guard.** The idempotency key
fingerprinted the model's plan verbatim, so `"White Rice"` and `"White rice"`
hashed differently. The second send took its own claim, the executor ran, a
downstream guard blocked the write, and the user got a *different* broken reply:
*"Lost the thread there. Try one more time."*

Neither produced a double row — data integrity held throughout — but both told
the user the product was broken when it was not.

## What shipped

**`eedacfd` — the duplicate's reply was the coordinator's failure floor.**
`TurnCoordinator.run` catches every exception and fills `state.response` from
`Finalizer.recover()` (the `llm_error` recovery line) *before* the entrypoint
absorbs the duplicate. The entrypoint's replacement was guarded by
`if not response.bubbles`, which was never true. It now discards a response that
`is_recovery_text`, so a duplicate answers *"Already logged that one."*

**`29ba0e1` — canonical owns what a duplicate is (A12).** The two settlement
owners disagreed, and the migration was the one that had moved:

```
legacy branch     one row, two refusals   (claim on user + text + plan, 60 min)
canonical branch  three rows              (operation id was the TURN id, so a
                                           retyped message is a new operation)
```

Promoting a user from legacy to canonical silently changed what happens when
they send the same thing twice — a user invariant, not an implementation detail.
Canonical now decides it, using the primitives it already had:

```
identity   the user's MESSAGE, normalised for case and whitespace
           (never the turn id, never the model's plan)
revision   which occurrence of that meal this is
window     60 minutes — legacy's, unchanged
```

`meal_commits` is already unique on `(operation_id, revision)`, so this needed no
second claim, no new table, and nothing imported from legacy. Keying on the
message also closes defect 2 at the canonical boundary; `_fingerprint_token`
closes it at the legacy boundary.

## Evidence

Three sends before and after, 28 minutes apart on the same account:

| | baseline `8f5501d` | verified `29ba0e1` |
|---|---|---|
| send 1 | logs, one row | logs, one row |
| send 2, same text | "Something went sideways…" | **"Already logged that one."** |
| send 3, re-cased | "Lost the thread there…" | **"Already logged that one."** |
| idempotency claims taken | **two** | **one** |
| food rows written | 1 | 1 |
| recovery bubbles shown | 2 | **0** |

The claim count is the load-bearing number: one claim instead of two is the
direct evidence that the re-cased plan now collides rather than minting its own
key. Reply text alone could have changed for other reasons.

Also verified: one `created` food ledger event per row, and a `Clear my day` in
the same window wrote its `deleted` event correctly.

### The canonical branch, verified separately

The run above routed to the legacy branch (`coverage_for` called the food
unsupported), so a second run was driven on a food that demonstrably settles
canonically for this account:

```
13:26:34  '150g of fried chicken'  ->  logged 328 cal, row #3017
13:37:35  '150g of fried chicken'  ->  "Already logged that one."
13:37:52  '150G of Fried Chicken'  ->  "Already logged that one."
```

Here the load-bearing observable is the **operation id shape**:

```
before A12   general:26:ios:<UUID>            the TURN id
after  A12   general:26:meal:9303ac8deca72cd7 the MESSAGE identity   <- observed
```

One `meal_commits` row at `revision 0`, a `created food canonical:create` ledger
event, and — the A2/A8 half — **zero `processed_turns` claims in the window**. The
canonical branch refused both duplicates using only its own claim and borrowed
nothing from legacy, which was the design constraint.

**Offline, through the real turn against a live model, on both branches** —
`scripts/reproduce_the_duplicate_turn_reply.py`, three sends including a re-cased
one: one row, two "Already logged that one." on each branch. Canonical wrote
three rows before this change.

**Mutation-checked.** Nine mutations across the two commits, each turning the
suite red with the correct failure name: reverting the recovery-text guard;
deleting the duplicate's reply; deleting reply and return together; identity
reverting to the turn id; `meal_surface` no longer lowercasing; the window
collapsing to zero; the window never expiring; the stage swallowing the signal;
the legacy fingerprint no longer normalising.

## Two process findings worth the team's attention

**A green test whose fixture supplied the deciding value.** The first duplicate
test stubbed the entire coordinator and passed `response=None` by hand, so the
failure floor never ran — the one field that decided the production outcome was
the one the test invented. The replacement drives the real coordinator and real
finaliser and stubs only the stage that genuinely raises. One of the new tests
was itself vacuous until it was driven over a floor returning `None`.

**Four "pre-existing" test failures were a clock.** Recorded once as
"order-dependent, pre-existing" and once as "they fail standalone too". Neither
reading varied anything. Holding the commit fixed and varying only `TZ`:

```
Pacific/Honolulu  local 08-16 18:57   4 failed
America/Chicago   local 08-16 23:57   4 failed
America/New_York  local 08-17 00:57   0 failed
Europe/London     local 08-17 05:57   0 failed
```

The fixture built its `DailyLog` from the *host's* calendar date while the code
under test resolved the *user's* logging day. Fixed to use the same resolver
production uses; green across 15 timezone × rollover-hour combinations. This was
the ratchet protecting "no row is deleted without a ledger event" — it had become
routinely ignorable, which is how it survived two sessions.

**A latency reading is not a layer fingerprint.** The investigation was sent down
the wrong path by a 6 ms duplicate, read as proof that a different layer caught
it. The successful send of the verified replay settled it: 112 ms,
`{"pricing.memory": 10, "pricing.fetch_candidates": 10, "tools": 57}`, **no `llm`
leaf, and it wrote a row.** A food already in memory needs no model call; the
6 ms duplicates inherited that fast path. The answer was in the stages of the
turn that *worked*, not the one that failed.

The canonical run then closed it in the opposite direction from where it started.
Send 1 there — a successful log that wrote row `#3017` — recorded **29 ms with
`stages={}`**, because the `pricing.*` and `tools` leaves are legacy-executor
instrumentation the canonical writer does not emit. On the canonical path a turn
that succeeded is **indistinguishable by latency and stages from a refused
duplicate**. It was never a layer fingerprint, and there it cannot be one even in
principle.

## Open, and deliberately not closed here

- **`turn_metrics.outcome` cannot report a native failure.** `_rt.done()` runs in
  the `finally` around `coordinator.run`, which never raises; `raise state.error`
  happens after the trace closed. Deferred on purpose — changing it mid-canary
  would alter the measurement contract.
- **6 of 88 `meal_commits` rows for user 26 have `created_at IS NULL`**, despite
  `server_default=func.now()`. A12 reads `created_at` to decide the window and
  fails closed on an unstamped row, so behaviour is safe; the NULLs still should
  not exist and have the shape of the `_migrate` Postgres gap.
- **Whether a day-clear should drop that day's claims** is a product decision,
  still unmade. The window is unchanged at 60 minutes.
- ⛔ **THE "NO CI HAS EVER RUN" NOTE WAS FALSE, AND IT WAS LOAD-BEARING.**
  `.github/workflows/ci.yml` runs the suite on every push to `main`, against a
  REAL Postgres service. Verified 2026-08-17 via the check-runs API: `eedacfd`
  `test` = success, `29ba0e1` `test` = **failure**, `7059fbc` `test` = **failure**.
  So `main` has been red since the A12 push, and every "every green is local"
  statement in this session inherited a belief nobody had checked.
- ⚠ **The cause is the directive staleness gate, and the arithmetic matches CI
  exactly**: `eedacfd` code 08-16 vs stamp 08-14 = lag 2 (passes at MAX_LAG_DAYS=2);
  `29ba0e1` code 08-17 vs stamp 08-14 = lag 3 (fails). The freeze commit reconciles
  the directive and stamps 08-17, which is the fix.
- ⚠ A second workflow, `eval.yml` (`battery`), failed on `eedacfd` and is
  unexamined.
- ⛔ **The card is still absent on native turns**, which remains the blocker on
  widening past user 26.

## Next

```
1  freeze general-settlement backend hardening
2  oils
```

Also surfaced while picking the canonical test food, and worth knowing before
coverage is widened: **`ground turkey` declines canonical settlement despite a
`user_food_matches` row with `confidence='exact'`.** `_memory` applies the
ambiguous-address quarantine (`_address_has_one_authority`) — that surface key
binds to more than one source record, so MEMORY abstains, and with no artifact
row the predicate returns `Unsupported`. Working as designed, and a reminder that
"the user has logged this before" is not the same fact as "canonical can price
it". Coverage widens by landing evidence, not by loosening the predicate.
