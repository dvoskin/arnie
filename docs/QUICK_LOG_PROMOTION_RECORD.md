# Quick-log promotion — production verification record

**Status: INCOMPLETE — awaiting the promoted build in production.**

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
| 1 | promoted build is live | `/health` → `commit` == the promoted sha | ☐ pending |
| 2 | production reports the promoted state | `/health` → `food_pipeline.QUICK_LOG_FOOD_WRITER == "canonical"` | ☐ pending |
| 3 | corpus runs against the deployed sha | `python scripts/parity_corpus.py --promoted` | ☐ pending |
| 4 | canonical writes are visible | `event=canonical_meal_written` lines > 0 in `/admin/food-traces` | ☐ pending |
| 5 | duplicate returns the ORIGINAL ids | corpus case `DUPLICATE of cp-02`: same `entry_id` AND `daily_log_id` as cp-02 | ☐ pending |
| 6 | the ledger shows the canonical lane | `SELECT count(*) FROM ledger_events WHERE source = 'canonical:create'` > 0 | ☐ pending |
| 7 | one row per non-replayed tap | food rows for the test user == non-replay corpus cases (9) | ☐ pending |
| 8 | nutrition provenance persisted | `meal_commits.result_payload` → `committed_items[].nutrition_provenance == "client_estimated"` | ☐ pending |
| 9 | latency impact | tap p50/p95 before vs after, from `turn_metrics` where `command='log_food'` | ☐ pending |

Steps 3–5 are one command; 6–8 are one SQL read; step 9 is a comparison
against the pre-promotion window.

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

## Rollback

The promotion is a code path, not a migration: reverting the commit restores
the legacy writer. `mealcommit001` is additive and already applied, so no
schema change is involved either way. No flag gates the promoted path — that
is deliberate (a rollout flag surviving past rollout is the clutter the
cleanup directive names), and the rollback is therefore a revert, not a toggle.
