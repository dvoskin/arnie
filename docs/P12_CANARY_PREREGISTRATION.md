# P12 — THE GENERAL SETTLEMENT CANARY, PRE-REGISTERED BEFORE IT RUNS

*(2026-08-16. Written BEFORE any production change, so that what is observed
afterwards is compared against a prediction rather than explained by one.)*

⭐ **A9's RULE APPLIES TO THE WHOLE CANARY, NOT ONLY TO IDENTITIES.** Predictions
go down first; the run either matches them or does not. A number that agrees
with expectation after the fact is not evidence — banana 210 = 2×105.

## ⛔⛔ WHAT REQUIRES DANNY'S HANDS, AND WHY I HAVE NOT DONE IT

```text
1  merge the branch to main          main AUTO-DEPLOYS
2  set the production environment    I have no access, and should not
```

Neither is a step I take unasked. The merge is outward-facing and deploys on
contact; the env vars decide whether a real user's food is settled by new code.

⭐ **THE DEPLOY ITSELF IS INERT.** Every gate is fail-closed and unset:

```text
GENERAL_SETTLEMENT_ALLOWLIST   unset -> settlement_cohort() is False for EVERYONE
TURN_COORDINATOR_MODE          legacy_only in production -> no stage runs at all
TURN_COORDINATOR_LANES         unset -> _enabled_lanes() is EMPTY -> nothing enabled
```

So merging changes nobody's behaviour until all three move. That is the
property to verify FIRST, and it is the one thing the merge alone can prove.

## THE SEQUENCE, AND ITS PREDICTIONS

**STEP 0 — merge, deploy, change nothing else.**

```text
PREDICTED   settled_by shows NO `general_settlement_owner` for at least 24h
            coverage A/B/C unchanged within normal drift
            no change in turn failures or latency
FALSIFIED BY  a single general-settled meal, which would mean a gate is open
              that this document says is closed
```

**STEP 1 — one user, all four gates, watched.**

```bash
TURN_COORDINATOR_MODE=new_execute
TURN_COORDINATOR_LANES=structured_food
TURN_COORDINATOR_ALLOWLIST=26
GENERAL_SETTLEMENT_ALLOWLIST=26
```

⚠ **ALL FOUR, OR NOTHING HAPPENS.** Measured 2026-08-16: setting three of them
left the turn on the legacy path, writing a row and rendering a card — looking
exactly like a working canonical turn. `TURN_COORDINATOR_LANES` unset is an
EMPTY SET and enables nothing. The proof that the canary is live is a
`general_settlement_owner` row in `settled_by`, never a quiet log.

```text
PREDICTED, for user 26's ordinary food turns
  settled_by            general_settlement_owner > 0 within the first day
  pricing rung          memory dominant, artifact occasional
                        (81 memory : 12 artifact across the fleet's supported
                         meals over 21 days)
  declines              "no local evidence" — the meal goes to LEGACY untouched
                        and still gets logged
  ledger source         canonical:create
  operation id          general:26:<turn_id>
  the card              ABSENT on native turns — a known NativeRenderStage gap
                        (§3a.3), NOT a settlement defect
```

⛔ **THE CARD IS THE REASON THIS IS A CANARY AND NOT A ROLLOUT.** A native turn
renders no card today whoever settles it. One user who knows that can live with
it; a cohort cannot.

## WHAT WOULD STOP THE CANARY IMMEDIATELY

```text
any ExecutionViewMismatch          the mapping failed; the meal rolled back
any SettlementIdempotencyConflict  an operation id was reused across content
a meal logged twice                two settlement owners on one turn
a row with no `pricing` provenance in meal_commits.result_payload
a turn that reports success with no food row
latency regression on settle       assemble() + price() must not retrieve
```

**ROLLBACK IS ONE VARIABLE:**

```bash
GENERAL_SETTLEMENT_ALLOWLIST=      # empty -> settlement_cohort() False
```

Consumption stops on the next turn. Rows already written stay — they are
canonical rows, correctly priced, and nothing about them depends on the flag.

## THE WATCH

```bash
../arnie/.venv/bin/python -m scripts.measure_settlement_coverage --days 21
```

`settled_by` is the adoption signal. ⭐ **AND IT ONLY WORKS BECAUSE THE
INSTRUMENT WAS TAUGHT TO DISAMBIGUATE FIRST**: every canonical lane emits
`canonical:create`, so B-1 and the general owner are indistinguishable by ledger
source. The split comes from `meal_commits.operation_id` —
`chat_quantity:*` vs `general:*`. Without that, the canary would have been
invisible to the very measurement meant to watch it.

## THE BASELINE THIS IS MEASURED AGAINST

```text
21 days to 2026-08-16 · 405 rows · 251 meals · ordinary food-chat denominator

A  routing rate    80.9%
B  support rate    45.8%
C  ownership rate  37.1%
settled_by         legacy_executor 227 · b1_answer_path 24 · general 0
expected rung      memory 81 · artifact 12
declines           "no local evidence" 108 · "no stated quantity" 3
```

⚠ **A IS WRITER-DERIVED** — no per-meal routing record is persisted, so
`canonical:*` counts as structured-route on the strength of its operation id.
This is the number most likely to need revisiting once the canary is live.
