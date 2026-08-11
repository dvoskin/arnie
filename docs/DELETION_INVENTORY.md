# Deletion inventory — the cleanup scoreboard


> **Current as of 2026-08-09** (reconciled against `870b6ea`). The batching
> rule is unchanged: promotion and predecessor deletion happen in a single
> event after B-2 (directive, "One promotion event"), so production users cross
> the boundary once instead of five times. C8/C9 remain frozen, and the legacy
> lane is explicitly a frozen compatibility lane — P0/P1, security and
> migration-compatibility fixes only.
>
> **TWO THINGS HAVE ACTUALLY GONE SINCE, and this box previously said nothing
> had.** The scoreboard is only useful if it moves.
>
> 1. ✅ **`skills/nutrition/preparation_materiality.py` — DELETED** (`1e70d88`,
>    confirmed absent from the tree). It was listed below as "newly owed" for
>    its token-matching-against-provider-descriptions, which is regex identity
>    and prohibited by B-1.5E. It was replaced by the semantic evidence layer,
>    not refined — which is the disposition the directive requires for
>    superseded design.
> 2. ◐ **`handlers.tool_executor._analyze_food` — DECOUPLED, not deleted**
>    (`e162e36`, audited in `2a88560`). The canonical settle path no longer
>    imports or calls it; `core/canonical_pricing.py` prices instead. State the
>    difference precisely, because "the seam is CUT" reads as a deletion and is
>    not one: the function is alive and still serves the legacy lane and the
>    ordinary `log_food` dispatcher, and the canonical **ask** path still
>    reaches it. Full deletion is owed at the promotion event like everything
>    else here.
>
> **Owed at the promotion event, beyond the table below:** the legacy quantity
> producer, answer reconstruction, prose-derived options, `_analyze_food`
> itself, iOS `QuickReplyEngine.swift` (already absent from the B-1b branch)
> and the parked `replyChipBar` (defined, uncalled).
>
> **Owed at commit 2 (imminent, not the promotion event):**
> `skills/nutrition/preparation_materiality.py` — its token matching against
> provider descriptions is the regex identity B-1.5E prohibits. It is DELETED
> behind the `unresolved_when` hook, not refined.

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

## Owed per language before Tier 1 commands may run (B-1)

`parse_command` is a locale-specific lexicon, not a universal parser, and it
returns `NONE` for every locale but English. That is a deliberate, enforced
restriction — not a gap to be closed by widening the English regexes. Each
language earns its Tier 1 the same way:

| step | what it means |
|---|---|
| locale lexicon | cancel / skip / estimate / restart / keep-as-read, in that language's normalized forms, owned and tested per locale — never one universal regex |
| field-parser fixtures | number words and unit words (`seis onzas`, `шесть унций`) belong to the NARROW quantity parser, not to the command layer |
| classifier corpus | Tier 2's training/eval set for that language (B-1.8) |
| adversarial destructive-command tests | the negation and near-miss cases, per language: the failure that matters is a phantom cancel, not a missed one |
| production measurement | cancel rate, repair rate and abandonment for that locale before widening |

Until then, non-English answers reach the field parser and then repair. That
is the correct behaviour, not a degraded one.

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

## Owed at the promotion boundary — the added-fat phrase tables (B-1.6c)

**NOT deleted, and deliberately so.** `core/portions.py` holds a phrase table
that decides added fat from RAW TEXT, which is a SECOND SEMANTIC OWNER for a
question B-1.6 now models as registered fields:

```text
_ADDED_FAT_CAL         "in butter" 100 · "with ranch" 145 · "alfredo" 180
_ADDED_FAT_NEGATIONS   "no dressing", "without", "plain", ...
added_fat_calories()   the calories a named fat contributes
mentions_fat()         whether the text ADDRESSED fat at all
```

Legacy and non-eligible turns still depend on them, so deleting now would
change behaviour no part of B-1.6 asked to change. What is established today
is the narrower, checkable claim: **canonical cannot reach them.**

Proven by POISON, not by grep — an import gate shows a module is not NAMED,
not that it is not REACHED. All four are replaced with objects that raise (the
tables too, on membership/iteration/indexing/`get`/`items`/`len`, so a caller
that inlined a lookup cannot sail past a patched function), and canonical
pricing is required to complete on the SAME rung with the SAME numbers. See
`tests/test_canonical_settles_with_the_phrase_tables_poisoned.py`.

**The seam test fails if nothing outside `portions.py` calls them.** That is
intentional: at that point they are dead code and belong in this document's
done column rather than guarded by a test protecting nothing.

**Ranges are why this matters.** One tablespoon of "added fat" spans 60–180
kcal across that table (marinade 60, teriyaki 70, mayo 90, butter 100, oil 120,
ranch 145, alfredo 180), and the table fuses presence, identity, quantity and
pricing into a single phrase lookup. B-1.6d — pricing added fat as a real
canonical component — is BLOCKED until interpretation carries a fat IDENTITY:
measured across 12 production operations, the staged item holds
`food/amount/unit/calories/protein/carbs/fats/entity_id/basis/meal/branded`
and nothing naming a cooking fat. Defaulting to "oil" would price butter 20%
high and alfredo 33% low — the same heuristic under a typed interface.
