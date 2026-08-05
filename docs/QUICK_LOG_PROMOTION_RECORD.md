# Quick-log promotion — production verification record

**Status: COMPLETE — verified against production 2026-08-05.**

Promoted build `a66e9ba8c86a`, test identity `ios:canonical-parity-test-0805` (user 144), day log 479.

## Scope of this record — one migration, one build

TWO STATUSES, kept separate on purpose:

* **Quick-log canonical promotion: COMPLETE, production-verified on
  `a66e9ba8c86a`.** That is the build every ✅ below was measured against.
* **Later heads: test-verified, and smoke-verified only where the log below
  says so.** They change runtime behaviour (provenance typing, outbox
  enqueueing, coordinator sequencing), so "the record is complete" must never
  be read as "the current head is verified."

This record is **immutable evidence for one migration, not a perpetual health
certificate**. Ongoing ownership is protected by the things built for it: C7
(the legacy writer cannot return), `/health`'s `QUICK_LOG_FOOD_WRITER`, and
observable canonical writes. After any later deploy, the minimal smoke is:
`/health` sha + writer state, one keyed tap, duplicate replay identity, stored
provenance, zero duplicate job rows — not a rerun of this corpus.

Migration 2/4 does not begin until this record is complete. That is the point
of the record: "promoted" is a claim about production, and the tests passing is
not evidence about production.

## What is claimed

`POST /api/v1/food` commits through the canonical spine — one transaction
carrying food rows, ledger event, immutable result and idempotency claim
completion — and a duplicate delivery returns the original result rather than
writing again.

## Verification steps, in order

Each has a recorded outcome. An unrecorded step is a failed step.

| # | step | how | outcome |
|---|---|---|---|
| 1 | promoted build is live | `/health` → `commit` | ✅ `a66e9ba8c86a` |
| 2 | production reports the promoted state | `/health` → `food_pipeline.QUICK_LOG_FOOD_WRITER` | ✅ `"canonical"` |
| 3 | corpus runs against the deployed sha | `parity_corpus.py --promoted` | ✅ 10/10 responses as expected |
| 4 | canonical writes are visible | `event=canonical_meal_written` | ✅ **9 lines**, all `lane=canonical:create`, one per non-replayed tap |
| 5 | duplicate returns the ORIGINAL ids | corpus `DUPLICATE of cp-02` | ✅ `entry=2818 log=479`, identical to cp-02; claim row `status=completed entry=2818 log=479` |
| 6 | the ledger shows the canonical lane | `ledger_events` group by source | ✅ **9 `created`, source=`canonical:create`, zero legacy-sourced** |
| 7 | one row per non-replayed tap | `food_entries` for user 144 | ✅ **9 rows** for 10 taps (1 duplicate wrote nothing) |
| 8 | nutrition provenance persisted | `meal_commits.result_payload` | ✅ 9 `meal_commits`, all `committed`, **9/9 `client_estimated`** |
| 9 | latency | `turn_metrics.total_ms`, `command='log_food'` | ✅ n=9, **p50 24ms, p95 87ms** (see caveat) |

### Fidelity across the corpus

Every value survived the boundary unchanged: unicode
(`Гречка с курицей` / `1 порция`), apostrophe (`Trader Joe's Yogurt`),
decimals (`137.5cal 11.3P`), zero-calorie (`Black coffee` 0.0), large values
(1850cal), absent quantity (`None`, not `""`), and the unkeyed tap — which
correctly deduped nothing and took a hash-derived turn id
(`quick_log:144:ios:h:ce5e4f45…`) rather than a client key.

### Step 9 caveat, stated rather than implied

There is **no pre-promotion comparison window**: `turn_metrics` holds no prior
`ios`/`log_food` rows at all, because quick-log had no organic tap traffic
(zero in the 24h before promotion). The canonical numbers are recorded as an
absolute baseline for future comparison, not as a "faster/slower than legacy"
claim — which the data cannot support.

### One payload verbatim (step 8 evidence)

```json
{"schema_version": 1, "result": {"committed_items": [
  {"entry_id": 2817, "nutrition_provenance": "client_estimated",
   "daily_log_id": 479, "name": "Chicken breast", "entity_id": "",
   "quantity": "", "calories": 320.0, "estimated": false}],
 "meal_totals": {"calories": 320.0, "protein": 43.0, ...}}}
```

## Why there is no pre-promotion shadow window

Stated plainly rather than omitted. `CANONICAL_WRITER_SHADOW` was never enabled
in the Render dashboard, so the shadow never ran — and the deployed shadow
builder was independently broken (`Confidence(value=…)`; the field is `score`),
contained by its own exception handler, so with the flag on it would have
logged `outcome=error` on every tap and produced no parity signal at all. That
bug surfaced only because the promotion exercised the builder path directly.

Quick-log also has no organic traffic (zero taps in 24h at the time of
measurement), so the corpus was always going to be deliberate taps rather than
observed usage. Verification therefore moves **after** the promotion deploy,
against the canonical endpoint, with the same 10-case corpus — the evidence is
equivalent, and its absence beforehand is recorded here rather than implied.

The corpus covers: plain, quantity+meal_type, **duplicate delivery**, second
helping (distinct key, same food), zero-calorie, decimal macros, unicode name,
apostrophe in name, large values, and an unkeyed request (which must dedupe
nothing).

## Test-user hygiene

Identity `ios:canonical-parity-test-0805`, minted through the real
`POST /api/v1/auth/session` device path. Namespaced and obvious. No other
user's data is touched by any step here.

## Post-deploy smoke log

APPEND-ONLY, and deliberately not part of the step table above — the table is
evidence for one migration on one build, and folding later runs into it is
exactly how a record becomes the perpetual health certificate this one refuses
to be. Each row is the five-item smoke this document defines, nothing more.

| build | when | sha ✓ | writer ✓ | keyed tap | duplicate identity | provenance | duplicate jobs |
|---|---|---|---|---|---|---|---|
| `998f3f430c8e` | 2026-08-05 | ✅ | ✅ `canonical` | ✅ entry 2835 / log 479, `canonical:create` | ✅ same ids, `idempotent_replay=true`, **1** `meal_commits` row, **1** food row | ✅ `client_estimated` | ✅ none |

## Rollback

The promotion is a code path, not a migration: reverting the commit restores
the legacy writer. `mealcommit001` is additive and already applied, so no
schema change is involved either way. No flag gates the promoted path — that
is deliberate (a rollout flag surviving past rollout is the clutter the
cleanup directive names), and the rollback is therefore a revert, not a toggle.
