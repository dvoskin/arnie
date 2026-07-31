# Gap register — 2026-07-31

Baseline: deployed `433cdf39f2d0` (= `origin/main` tip).
`deployed?` means the gap is live for users, not merely present on a branch.

---

## Closed in this pass

### G1 — tap-logged writes have no turn identity — **SEV: HIGH**

| | |
|---|---|
| Affected | every iOS user who logs by tapping (the primary iOS logging surface) |
| Deployed? | **yes**, on `433cdf3` |
| Root cause | `record_ledger_event` (`db/queries.py:3003`) reads the turn id from the ambient `CURRENT_TURN_ID` contextvar; `api/quick_log.py` never set it |
| Evidence | probe on deployed code: `turn_id on each event: [None, None]` |
| Data-integrity risk | events unattributable to a request; the I16 turn↔operation join (measured 461/495 = 93%) is broken for exactly this surface, and `ledger_undo` reasons over events |
| Latency risk | none |
| Fix | `_turn_scope()` binds `make_turn_id(...)` for the request in all three handlers |
| Owner | `api/quick_log.py` |
| Test | `test_a_keyless_tap_still_produces_a_traceable_event` — fails on `433cdf3` with `assert None is not None` |

### G2 — a retried tap writes the food twice — **SEV: HIGH**

| | |
|---|---|
| Affected | any iOS user on a flaky network, or who double-taps |
| Deployed? | **yes** |
| Root cause | no request identity on the three quick-log endpoints; nothing distinguishes a retry from a second helping |
| Evidence | probe: two identical taps → `food rows written: 2` |
| Data-integrity risk | **user data corruption** — the day's totals count food eaten once, twice. Silent; the user sees an inflated day and no error |
| Latency risk | none |
| Fix | `core/idempotency.py` claim contract + `idempotency_records` unique index (`idem001`) |
| Owner | `core/idempotency.py`, `api/quick_log.py` |
| Test | `test_the_same_tap_delivered_twice_commits_one_food_row`, `test_the_database_rejects_a_duplicate_claim` |
| **Caveat** | **not fully closed until iOS sends `Idempotency-Key`.** Server-side is ready and backward compatible; the client change is required and is not in this pass |

### G3 — the applied migration was unknowable from outside — **SEV: MEDIUM**

| | |
|---|---|
| Affected | every deploy |
| Deployed? | **yes** |
| Root cause | `/health` reported commit + flags but not schema; `render.yaml`'s `preDeployCommand` is documentation only (service is dashboard-configured, Render never reads the file) |
| Evidence | `/health` response on `433cdf3` contains no schema field |
| Data-integrity risk | a deploy whose pre-deploy migration did not run looks healthy until the first write to a missing column |
| Fix | `schema_summary()` → `"schema": {applied, expected, in_sync}` on `/health` |
| Owner | `api/diagnostics.py`, `api/app.py` |
| Test | `tests/test_health_reports_the_schema_revision.py` (4) |

---

## Open — escalated, not actioned

### G4 — the nutrition resolver is off in production, on in the docs — **SEV: HIGH**

| | |
|---|---|
| Affected | all users' committed nutrition values |
| Deployed? | **yes** — `/health`: `NUTRITION_RESOLVER_MODE: shadow`, `env_set: true`, `resolver_owns_committed_values: false` |
| Root cause | **unknown, and deliberately not guessed.** `render.yaml` says `live` "for ALL users (Danny 2026-07-25)"; production says `shadow`. Either a rollback the comment outlived, or a promotion that never happened |
| Evidence | `/health`; gate logic at `skills/nutrition/canary.py:242` returns `False` for any mode ≠ `live` |
| Risk | every behaviour gated on resolver ownership is inert, including the source/confidence tracking Phase 5 builds on. Composite work would be built on nothing |
| Recommended | **Danny decides.** Flipping a resolver that owns committed nutrition values is not a change to make from a repo reading |
| Test | n/a — a configuration question |

### G5 — helpers commit independently (no transaction ownership) — **SEV: MEDIUM**

`add_food_entry` commits, then `record_ledger_event` commits separately. A
crash between them leaves a domain row with no ledger event. This is the
Phase 4 gap; it predates this pass and was left alone because restructuring
those helpers touches the chat path too and does not belong in a P0 change.
**Test required before fixing:** a crash-injection test proving the row and
its event commit together.

### G6 — historical NULL `turn_id` events cannot be backfilled — **SEV: LOW**

The fix is forward-only. The ids were never minted, so nothing can recover
them. Population size is **unmeasured** (no production `DATABASE_URL`).

---

## Architecture assessment

Scored for the **deployed** system. "Projected" = after this pass lands **and**
iOS sends `Idempotency-Key`; it does not assume Phases 4-9.

| Dimension | Deployed | Projected | Note |
|---|---:|---:|---|
| Correctness | 7 | 8 | core lanes sound; quick-log was the hole |
| Data integrity | 4 | 8 | duplicate food rows were reachable from the main iOS surface |
| Idempotency | 3 | 8 | several partial schemes, none covering direct writes; now one contract, DB-enforced |
| Observability | 5 | 7 | good flag reporting; schema was invisible, tracing still absent |
| Recoverability | 4 | 6 | stale-claim takeover added; no failed-turn recovery yet |
| Latency | 6 | 6 | untouched; +54% p50 regression flag from 07-30 still unexplained |
| Food interpretation | 7 | 7 | untouched |
| Nutrition resolution | 5 | 5 | **capped by G4** — resolver inert in production |
| Clarification handling | 6 | 6 | DB-enforced single open pending (`pendinguniq001`); still not a state machine |
| Cross-channel consistency | 5 | 7 | quick-log now shares turn identity with chat |
| Rollout safety | 6 | 7 | flags + canary exist and are reported; `/health` now includes schema |
| Test quality | 6 | 8 | failing-first verified against deployed code; multi-worker race still unproven |
| Documentation accuracy | 4 | 7 | `render.yaml` actively wrong on G4; deployed-state report added |

**Deployed mean ≈ 5.2 → projected ≈ 7.0.**

The two scores that do not move are the honest ones: **nutrition resolution**
is capped until G4 is answered, and **latency** because nothing in this pass
touched it and the 07-30 p50 regression remains unexplained.
