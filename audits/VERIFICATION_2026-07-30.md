# Post-deploy verification — 2026-07-30 ~16:05 UTC

Deploy of `7cea41e` confirmed in production. Evidence labels move as follows
(per the master directive §2 — nothing marked CLOSED without a production window).

## Structural — verified directly, label `DEPLOYED` + repairs confirmed

| Item | Query result |
|---|---|
| `alembic_version` | `pendinguniq001` — both new migrations ran via preDeploy |
| Indexes | all 3 live: `ix_conversation_logs_turn_id`, `uq_ledger_events_created_entry`, `uq_pending_open_per_user_kind` |
| `fitness`-domain created events | **0** (target 0 — re-domain/dedupe repairs applied) |
| Duplicate (domain, entry_id) created groups | **0** (target 0) |
| Stacked open pendings per (user, kind, purpose) | **0** (target 0) |
| Historic `turn_id` backfill | **2,241** rows joined (`ios:ios:%` as designed) |

Invariants **I2 and I3 are now enforced by the database in production** — a duplicate operation
or stacked pending is rejected at commit, not cleaned up after.

## Behavioural — label `DEPLOYED`, awaiting traffic for `CLOSED`

`7cea41e` contains everything from the 07-30 merge train: the gate fix (`15f961a`), `KEEP_AS_READ`,
`[TURN OBLIGATIONS]` + the five state blocks, the provenance fix, the build stamp, the one-writer
ledger fix, and the turn-id unification. One post-deploy turn exists so far (15:59, a no-reasoning
surface). Closure queries — run after ~24h of traffic:

1. Build stamp: `reasoning_json->'build'->>'sha'` non-null on chat turns; record the SHA.
2. Punctuation admits: 0 turns `owner=gate_regex` with emoji/smart-punct-only evidence.
3. New `ios:ios:%` turn_ids: 0; `conversation_logs ⋈ ledger_events ON turn_id` returns rows.
4. `ledger_dup_blocked` / stacked-pending IntegrityErrors: 0 in steady state (the guard firing
   means a duplicate writer returned).
5. `interpreter_none` re-baseline; premise confirmations settle in-lane, any language (the state
   blocks now ride every legacy pass).
6. Latency p50 vs 7.1s baseline.

Then the directive's 7-day audit window begins. Remaining implementation: Phase 3 remainder
(tool-result strings out of the visible reply), Phase 4 (ask/write join), Phase 5 (replay corpus),
Phase 6 (out-of-pipeline writers) — see the approved plan and `project-arnie-hardening-phases-0730`.

## Re-checked 2026-07-30 ~17:12 UTC — still time-gated, not yet a regression

`alembic_version` unchanged (`pendinguniq001`). Two turns total since the prior check, both
`source_type=proactive`, both `reasoning_json = ''` (empty, not merely missing `build`) — the known
I1 gap (proactive writes no turn/reasoning) confirmed independently rather than assumed. Zero real
chat (`ios`) turns since the last one before this deploy (13:58 UTC) — closure query 1 (build-stamp
SHA) currently reads null on every row in the table, historic and post-deploy alike, because no real
chat turn has run the deployed code yet, not because the stamp is broken. ~1h of elapsed time, not
~24h; **the closure pass should not be attempted yet** — running it now would read as failure on
every query for lack of a denominator, not as evidence of one.

**HealthKit snapshot day-boundary defect found and fixed** (`566ee40`, this pass, not yet deployed):
both `/health/apple` (legacy Shortcuts webhook) and `POST /api/v1/health/snapshot` (native) defaulted
an omitted sync date to `date.today()` — the server's UTC day — instead of the user's logging day.
Same rollover-boundary class as the tracked midnight-rollover bug (I14), and the same class the
07-24 phantom-workout fix addressed for the workout batch on this same endpoint without carrying it
up to the snapshot date those workouts fall back to. Both sites now use `_user_today`. No prior test
covered either endpoint's date handling; both are covered now.
