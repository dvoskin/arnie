# Deletion inventory — the cleanup scoreboard

**Deletion belongs to each migration step, not to the end of the project.**
Every promoted owner removes its legacy implementation in the same slice, or
the new architecture becomes an additional layer coexisting with the old one —
and two live systems diverge one special-case fix at a time.

Enforced, not aspirational: C4 counts direct food writers and only goes down;
C7 forbids a promoted owner's legacy imports by name; the drift test keeps this
document and the ratchets in agreement. Status here is the human-readable view
of those gates.

## Legacy writers (C4 scoreboard: 3 remain)

| owner | replacement | status | deletion gate | dependents |
|---|---|---|---|---|
| ~~`api/quick_log.py` direct `add_food_entry`~~ | canonical spine (`ResolvedMeal → commit_or_load_existing → write_canonical_meal`) | **DELETED** at promotion (Phase 1 step 1) | — | C7 forbids its return |
| `api/app.py:3921` (dashboard food edit) | canonical spine, `MealIntent.CORRECTION` | legacy | shadow → parity → promote → delete | also the last caller of `add_food_entry(claim_id=)` — that branch dies with it |
| `handlers/tool_executor.py:3844` (chat log_food) | canonical spine via pending operation | legacy | the big one: clarification + held state must land on `PendingOperation` first | `_undeferred`, `deferred_calls`, `staged_items` |
| `handlers/tool_executor.py:4886` (chat food re-log) | canonical spine | legacy | with its sibling above | — |

## Pending-state handlers

| item | replacement | status | deletion gate |
|---|---|---|---|
| `conversation.payload_json` pending payloads | `pending_operations` rows (`core/pending_repository.py`) | shadow flags exist, unwired | chat-lane migration |
| `core/pending_store.py` | adopted as the lifecycle owner (355 lines, tested, atomic `claim()`) | to adopt, not delete | chat-lane migration |

## Shadow / rollout infrastructure (dies owner by owner)

| item | scope | delete when |
|---|---|---|
| `core/canonical_shadow.compare_with_legacy` | generic, next lanes need it | last owner promoted |
| `scripts/parity_corpus.py` | quick_log-specific corpus | after post-deploy verification of the promoted endpoint; rebuild per lane |
| `CANONICAL_WRITER_SHADOW` flag | gates shadows only — the promoted quick_log path runs unconditionally | last owner promoted |
| `PENDING_OPERATION_PERSIST_SHADOW`, `PENDING_OPERATION_READ_SHADOW`, `COMMIT_COORDINATOR_SHADOW`, `COMMIT_COORDINATOR_ENFORCE` | chat-lane rollout | chat lane fully canonical |
| `FOOD_PARTIAL_COMMIT` | legacy lane behaviour flag | legacy chat writer deleted |

## Tests

| class | policy | state |
|---|---|---|
| canonical contract (`test_canonical_*`, `test_the_canonical_invariants`, `test_two_connections_*`, coordinator/boundary suites) | keep forever | green |
| legacy-mechanism tests | rewritten to outcome-invariants at promotion — `test_a_crash_cannot_replay_the_meal.py` now asserts crash-leaves-nothing + retry-writes-once instead of the old food-first-claim-later shape | done for quick_log |
| shadow-builder tests | deleted with the builder (`test_a_failure_while_BUILDING_the_shadow_is_contained`) | done |
| parity tests (`test_the_first_migration_0805.py` shadow half) | delete when `compare_with_legacy` goes | pending |

## Known dead weight, tracked not yet deletable

| item | why it still exists |
|---|---|
| `add_food_entry(claim_id=)` branch | `api/app.py` dashboard edit still passes it |
| `add_food_entry(commit=True)` self-committing default | the 3 remaining legacy writers rely on it |
| legacy per-row briefing invalidation inside `add_food_entry` | same |
| six raw-`psycopg` audit scripts on the app clock | read-only; folded into one-clock step 2's cleanup note |

## Fixture debt discovered during the quick_log slice

The shared `:memory:`/StaticPool test engine cannot express crash or
concurrency semantics: the driver commits the outermost savepoint on release,
and a dying session's transaction lingers on the shared connection. Resolution:
the shared fixture stays bare for the 7,500 logical tests; crash/boundary
suites override `engine` with a `make_engine` WAL file database; concurrency
truth lives in the Postgres suites. `make_engine` carries the documented
driver-level transaction recipe (deferred BEGIN — IMMEDIATE was measured and
self-deadlocks nested sessions).
