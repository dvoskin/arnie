# CF24 closure record — memory write authority

*Danny's directive, 2026-08-25. This file is the record the directive asks for.
It is not a plan; `docs/CANONICAL_MIGRATION_DIRECTIVE.md` remains the
sequencing authority.*

## 1. Instrument fault guard — FROZEN at `3b5adef`

`scripts/measure_settlement_coverage.py`

| requirement | how it is met |
|---|---|
| any DB query failure invalidates the run | `_DbFaultWatch` listens on `handle_error` at the **DBAPI layer**; `main()` returns 2 |
| no ownership rate prints after a transaction fault | `render()` is **never reached** — not a smaller rate, not a flagged rate. A flagged number still gets quoted as a number |
| unknown/error never collapses into unsupported/zero | the run is invalidated **wholesale**, so no verdict is published at all — strictly stronger than declining to score the faulted item |
| the real `measure()` wire is proven, not a fixture | `test_the_REAL_measure_attaches_the_watch_to_its_OWN_engine` builds a scratch schema with `settled_by_operation_id` **dropped** and drives the real `measure()` |

⛔⛔⛔ **WHY THE WIRE TEST MAY NOT BE REPLACED BY FIXTURE-ONLY PROOF.** Mutation
G3 deleted `.attach(engine)` from `measure()` and every other test in the file
stayed GREEN — they attach the watch themselves or monkeypatch `measure` away.
A guard only the tests install is a guard production does not have, which is
exactly the shape of CF23's inert predicate. A structural assertion that the
source contains `attach` would be the M5 grep trap: the identifier survives in
the comment above the call.

Guard mutations **5 RED / 0 GREEN / 0 INVALID** (G1 stop refusing · G2 flag
instead of withhold · G3 never attach · G4 swallow the fault · G5 exit 0).

**The incident this exists for.** 2026-08-25: production had not run
`memtrust001`, the first memory read raised `UndefinedColumn`, the transaction
ABORTED, every later query raised `InFailedSqlTransaction` and returned
nothing — and the process **exited 0 printing `C OWNERSHIP RATE 9.0%`** after
52,680 lines of cascade. ⭐⭐⭐ *A zero from an aborted transaction is
byte-identical to a genuine refusal.*

## 2. Production migration state

- `memtrust001` **applied** (prod head, ahead of code, per the migrate-ahead order)
- schema **24/24 in sync** with the model; `ix_ufm_settled_operation` present
- **838 historical memory rows untouched**
- **0 trusted canonical linkages initially, by design**
- **no historical rewrite or backfill performed**

Pre-flight before applying: no positional `SELECT *` consumer of
`user_food_matches` on the serving path, and the deployed CF23 models do not
reference the new columns — so four nullable columns plus an index are
invisible to running code.

## 3. Writer closure

| requirement | proof |
|---|---|
| serving metadata grafts only when source identity matches stored authority | `_proves_same_authority`; `test_a_DIFFERENT_source_cannot_graft_its_serving` |
| ordinary cache writes may not overwrite authoritative nutrition | `test_an_ordinary_lookup_cannot_rewrite_stored_nutrition` |
| trusted nutrition only from an authoritative canonical settlement | `remember_canonical_settlement`, hooked after `commit_or_load_existing` |
| trust is structural linkage, never `origin_tier` text | `memory_nutrition_is_trusted` **resolves** against `meal_commits` |
| public `upsert_user_food_match` cannot mint trust | `test_the_public_writer_still_cannot_mint_trust` |

## 5. Replay safety twins — 12 passed

| twin | test |
|---|---|
| mismatched FDC/source identity → graft refused | `test_a_DIFFERENT_source_cannot_graft_its_serving` |
| same identity → graft allowed | `test_the_SAME_source_may_graft_its_serving` |
| identity that cannot be proven → graft refused | `test_identity_that_cannot_be_PROVEN_does_not_graft` |
| untrusted historical wrong nutrition stays non-authoritative | `test_an_untrusted_row_cannot_be_upgraded_by_use_or_confirmation` |
| settlement replaces evidence-owned nutrition **atomically** | `test_an_untrusted_wrong_row_is_REPLACED_atomically` |
| tampered / missing linkage → memory abstains | `test_a_stamp_pointing_at_NO_settlement_is_refused`, `test_a_stamp_naming_a_settlement_that_does_not_exist_is_refused` |
| canonical **and** legacy obey the same predicate | `test_legacy_does_not_price_from_untrusted_memory` (behavioural, drives `fetch_candidates`) |
| a resolvable settlement still needs basis + evidence | `test_a_RESOLVABLE_settlement_still_needs_its_basis_and_evidence` |

## 6. Measurement — CF24 ownership delta

| predicate | A routing | B support | **C ownership** | supported rungs |
|---|---|---|---|---|
| `b110a18` — CF23, deployed | 83.3% | 10.8% | **9.0%** | `{artifact: 20}` |
| `3b5adef` — CF24 | 83.3% | 10.8% | **9.0%** | `{artifact: 20}` |

Same frozen `p16b_0817` (361 rows / 232 meals, no drift), same migrated
production database, both runs clean (44 lines, exit 0, zero faults).

- correctness improvement: **YES**
- immediate ownership uplift: **0.0 pp** on the frozen corpus
- purpose: **safe future accumulation of trusted memory**
- **9.0% is the current comparable baseline**
- the prior **11.3% predates P17g, CF20, CF21, CF22, CF23 and CF24** and is not
  a valid before/after baseline for this tranche
- **no further memory archaeology is authorized by this tranche**

All 20 supported meals come from the **artifact** rung in both runs — **zero
from memory**. Memory already contributed nothing under CF23, so tightening
memory trust could not take anything away, and has not added anything yet
because the producer has never run in production.

## 8. Coverage rule going forward

- Do **not** chase canonical ownership as an isolated number.
- Measure **real-meal completion** before and after each product tranche.
- Build evidence producers only when they unblock **actual corpus meals**.
- The **40% rollout gate is fixed**; it rises through real capability, never
  through relaxed authority.

## STOP CONDITION

CF24 may interrupt the roadmap only until writer identity safety + trusted
producer + production canary + clean measurement are closed. After that: **no
generalized memory cleanup, heuristic trust restoration, or historical backfill
tranche** unless a new production correctness incident proves it necessary.

Then: **OILS → MATERIALITY → COMPOSITION → CLARIFICATION → MULTI-FOOD → VOICE**.
