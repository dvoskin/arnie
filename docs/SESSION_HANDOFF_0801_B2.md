# B2 — mutation contract. Session handoff, 2026-08-01

Branch `dvoskin/b2-mutation-contract`, from `origin/main` @ `fca59a4`.
Full suite green at every commit.

    UNKNOWN mutation surfaces: 0
    class A 29/29 · class B 29/29 · class C 17/17
    python scripts/mutation_inventory.py --check --strict   → pass (CI gate)

**B2 is closed.** Not deployed — deploys are manual.

## What changed about B2 itself

The old measure was **"3 of 60 user-visible mutations on the contract"**. It
counted conformance to ONE contract — the food-logging architecture — and the
only way to move it was to bolt an idempotency claim and a ledger event onto 57
routes, most of which should have neither. A claim on a last-write-wins
settings PATCH buys nothing. A ledger event for a device token records
something no one will ever undo.

B2 is now measured as **zero UNKNOWN mutation surfaces**: every route declares
the contract it owes, including — explicitly, with a stated reason — the policy
"idempotency not required, this operation is naturally idempotent". A declared
"not required" is a decision on the record. An absent declaration is the thing
B2 exists to eliminate.

    UNKNOWN mutation surfaces: 0
    every route satisfies the contract it declares

## The pieces

**`core/mutation_policy.py`** — the declaration. All 75 mutating routes, each
with class, auth, idempotency policy, transaction owner, ledger behaviour,
replay behaviour, rollback behaviour, owner, and a rationale where the policy
is anything other than "take a claim".

| class | count | required guarantees |
|---|---|---|
| A — the user's logged health history | 29 | turn id, claim, ledger event in the write's own transaction, trace, durable result, concurrency test |
| B — user-scoped state, naturally idempotent | 29 | authenticated, turn id, trace, audit trail |
| C — operational / auth / transport | 17 | authorized, logged |

Transport routes (`/webhook/{token}`, `/imessage`) deliberately carry no
contract of their own: the chat lane they hand off to owns it, and a second
contract at the edge is a second place to get it wrong.

**`scripts/mutation_inventory.py`** — joins DECLARED intent against OBSERVED
source and fails on the gap. Neither half is trusted alone: a declaration with
no implementation is a wish, an implementation with no declaration is an
accident nobody reviewed. `--json` emits all thirteen fields per route.

**`core/mutation_contract.py`** — ONE implementation of the shape, so 43 routes
adopted it rather than copying a forty-line block. It owns the turn id, the
ambient `CURRENT_TURN_ID` (reset in `finally`), the trace and its persistence
(which is what carries build attribution), and the claim when `claim=True`. The
caller still passes `ledger_source=` and `claim_id=turn.claim_id` INTO the
domain write, because that is what puts the row, its event and the claim in one
transaction — and a helper that owned the write would be the thing these routes
are trying to stop having.

**The gate, wired into `.github/workflows/ci.yml` as `--check --strict`.** Fails
on an undeclared route, a stale declaration, a route regressing from compliant,
and any route short of its class's guarantees. It was ratcheted against
`docs/mutation_baseline.json` while 24 Class A routes were open — a gate that is
red the day it lands teaches everyone to ignore it — and the ratchet came off
once every class closed.

## Migrated this session (all 75 routes)

Class A: the iOS water lane, the iOS food and exercise editors, all ten
dashboard write surfaces, both HealthKit imports, `/health/apple`, the Whoop
sync, `/api/v1/ledger/undo`, and the four chat routes.
Class B: 29 settings / profile / device / group / integration routes.
Class C: 17 admin, auth and transport routes.

All ten required properties are proven for the Class A edit/delete routes in
`tests/test_class_a_update_delete_properties.py`: repeated identical request ·
same key different payload · crash before commit · crash after commit · two
concurrent workers · deleting an already deleted row · retry reconstruction
from durable history · exactly one ledger effect · correct undo · canonical
turn + build attribution.

## Bugs found and fixed on the way — read these

1. **Undo after a tap-logged pour deleted the user's previous MEAL.** Water
   wrote no ledger event; `ledger_undo` takes the last event unconditionally,
   so it reached past the pour to the food logged before it. Silent data loss
   from the primary iOS surface. This is why the scorecard's "completeness, not
   data loss" framing was wrong. Pinned by
   `test_undo_after_a_pour_takes_back_the_pour_not_the_meal` (fails on parent
   by planning `delete_food_entry`).

2. **The inventory was hiding three user-data writes.** `NON_USER_STATE`
   matched path FRAGMENTS, so `"/health"` swallowed `/api/v1/health/snapshot`,
   `/api/v1/health/weights` and `/health/apple` — all of which record body
   weight. The true baseline was 61 user-visible mutations, not 60. Routes also
   reported without their router prefix, so every `@router.post("")` handler
   showed as `""`.

3. **`record_surface_mutation` overwrote a canonical turn id** with a synthetic
   one built from `(surface, event_type, entry_id)` — stable, not unique, so
   every edit of entry 41 shared `ios_edit:updated:41`. As each surface moved
   onto the contract it would have looked migrated while its events stayed
   unjoinable. It also never restored the contextvar, so the synthetic id
   stamped every later write in the same request. Fixed at the root, which
   reaches every remaining unmigrated surface that records history this way.

4. **Reconciliation didn't know the edit commands.** `_COMMAND_DOMAIN` mapped
   only the three original log commands, so a claim left in progress on any
   edit or delete could not be resolved from the ledger and fell through to the
   staleness timer — which answers "is the original process probably dead", a
   different question from "did its work commit". Now per command, with the
   event types that prove ITS write landed: a delete must NOT accept a
   `created` event, or the original log of a row would stand as evidence that a
   later delete of it committed.

5. **Nearly shipped: moving the deleted event into the write dropped
   `daily_log_id` from its payload.** `restore` rebuilds from the payload
   alone, so a food deleted from Tuesday would have come back on whatever day
   the restore ran. Caught by the existing
   `test_rest_delete_leaves_a_restorable_event`.

6. **`POST /api/exercise/log` HAS NEVER WORKED.** It passed
   `parsed_exercise_name=` and `weight_kg=` to `add_exercise_entry`, which
   forwards `**kwargs` to the `ExerciseEntry` constructor — whose columns are
   `exercise_name` and `weight`. Every call raised TypeError; the dashboard's
   "log exercise" button 500s and has for as long as the kwargs have been
   wrong. Nothing caught it because nothing called it: no test, and a route
   that always fails looks exactly like a route nobody uses. Found only
   because the Class A `concurrency_test` requirement forced a test to exist —
   which is the argument for that requirement in its own right.

7. **The HealthKit delete-tombstone had ZERO coverage.**
   `dead_code_report.jsonl` recorded `HealthImportTombstone` as
   `test_call_files: 0, test_runtime_hit: false`. It is the property that
   matters most on the import routes: replace-on-sync rewrites the day from
   whatever the device sent, and the device has no idea the user deleted
   anything, so without the tombstone a deleted workout returns on every sync
   — silent, repeating, and un-fixable by the user. Now pinned end to end and
   verified to have teeth (disabling the filter fails exactly those tests).

8. **Two declarations were wrong and the code corrected them.**
   `/api/v1/health/weights` declared `natural` idempotency until a concurrency
   test wrote two rows for one day. The chat routes declared `claim_required`
   and "ProcessedTurn returns the original reply" until reading
   `claim_processed_turn` showed it returns a BOOL scoped to the food commit —
   the reply is regenerated, and there is no stored result to hand back. That
   is what declaring intent separately from observing reality is for.

## What is left

**Nothing in B2.** `--check --strict` passes: 0 UNKNOWN, A 29/29, B 29/29,
C 17/17, and it is what CI runs, so a route that stops satisfying its declared
contract now blocks the merge.

Carried forward, declared rather than hidden:

1. **The weight-backfill race.** Two CONCURRENT `/api/v1/health/weights` syncs
   with DIFFERENT keys can both insert for one local day — the per-day dedup is
   a read-then-write with no uniqueness constraint. The claim closes the common
   case (a retried sync). Recorded as a `strict=True` xfail in
   `tests/test_a_deleted_import_stays_deleted.py`, so when the constraint lands
   it fails as XPASS and forces the policy note to be corrected. Root fix: a
   unique constraint on (user, source, logging day), needing a stored day
   column and a migration.
2. **`turn.complete()` call sites.** `/api/v1/ledger/undo` and
   `/api/v1/health/weights` complete their claim in a SECOND commit, because
   the executor and the import loop own their transactions. That leaves the
   crash window the in-transaction `claim_id=` closes. Documented on
   `MutationTurn.complete`; reconciliation (`committed_result`) recovers the
   commands listed in `_COMMAND_DOMAIN`.
3. **A pre-existing suite flake**, not from this work:
   `test_ask_authority::test_the_lane_is_never_lost_to_a_failing_model` fails
   intermittently under shuffle (a `food_relevance` cache leak) and passes
   deterministically. Worth its own session.
4. **NOT DEPLOYED.** Deploys are manual. Run `python scripts/release_check.py`
   first.

## Adding a route after this

Put a line in `core/mutation_policy.py` naming its class and policy. CI fails
otherwise — that is the gate, and it is the whole reason the count stays at
zero as the codebase grows.

For a Class A route, `core.mutation_contract.mutation_turn` is the one
implementation of the shape; pass `ledger_source=` and `claim_id=turn.claim_id`
into the domain write so the row, its event and the claim land in one
transaction. Do not re-declare `_turn_scope` / `_client_key` — the contextvar
leak and the keyless-collision trap are both real past incidents.

## Gotchas for whoever picks this up

- `_turn_scope`, `_client_key` and `_claim_failed` live in `api/quick_log.py`
  and are **imported**, not re-declared.
- Re-run `--write-baseline` after any deliberate status change.
- The concurrency-test observation is coarse: a handler name counts if it
  appears in a test module that also uses `asyncio.gather`. It is evidence a
  concurrency test exists, not proof it is a good one.
- The inventory credits named helpers (`mutation_turn`, `run_turn`,
  `execute_tool_calls`, `turn.audit`) for guarantees that live below the
  handler. Each was VERIFIED before being credited, and the verification is
  written next to the marker. Do not add one without doing the same.

---

## Getting this to main safely

**What makes this lower-risk than its size suggests (40 files, +5.9k lines):**

- **No schema change.** `git diff origin/main..HEAD` touches no `db/models.py`
  and adds no migration; `alembic heads` is a single `metrics001`. Nothing has
  to run before the code, so there is no migration/deploy ordering to get
  wrong — which is the failure mode that bit the turn-footer deploy.
- **Shipped clients send no `Idempotency-Key`, and a keyless request behaves
  exactly as it did.** `claim_request` returns an empty claim with no key: no
  dedup, no claim row, nothing threaded into the write. That is the whole
  backward-compatibility argument, so it is now asserted rather than reasoned
  about — `tests/test_the_shipped_clients_are_unaffected.py` pins that a
  keyless write takes no claim, two keyless pours both land, a keyless edit
  never 409s, the write is still traceable via the hash fallback, and no
  response field was removed (only `turn_id` added, which Codable ignores).
- **The dedup only switches on when a client opts in** by sending the header.
  iOS and the dashboard have to be changed deliberately for behaviour to
  change at all.
- **Roughly 2,000 of those lines are tests.**

**Order of operations:**

1. Open the PR. `--check --strict` runs in CI *before* the suite, so a policy
   violation fails fast and cheap.
2. **Read the CI run, do not just look at the tick.** CI runs against real
   Postgres; this branch's concurrency tests were written on sqlite behind a
   StaticPool, where two sessions share one connection. The row/event
   invariants must hold on both, but the LOSING delivery's failure mode
   legitimately differs (409 vs a driver error), and Postgres is the backend
   that decides it.
3. Merge to main. **Merging is not deploying** — deploys are manual in Render.
4. `python scripts/release_check.py <sha>` before deploying, then `/health`
   after.

**Deploy this on its own.** Production is on `fca59a4`; main is already ~13
commits ahead from the nutrition V2 merge (`eef4953`), which is itself
undeployed. Shipping both at once means any regression has two candidate
causes and the bisect is over a merge commit. The nutrition work is flag-gated
(`NUTRITION_ACCURACY_V2` default off) and this is not, so ship them
separately in whichever order — just not together.

**What to watch after deploy:**

- `event=idempotency_unavailable` in the logs. `claim_request` degrades to NO
  duplicate protection if the `idempotency_records` table is missing, rather
  than failing the user's write. It is present (`idem001`), but many more
  routes take claims now, so this line firing means the degradation is live
  and silent.
- `event=idempotency_conflict` / `request_in_progress` (409s). Should be ~zero
  until a client starts sending the header. A spike means a client is reusing
  one key across different payloads.
- `POST /api/exercise/log` should stop 500ing. It has never worked; if it is
  still erroring, the fix did not reach production.

**If it goes wrong:** nothing here is a data migration, so a revert is a
straight redeploy of the previous SHA. The ledger events and idempotency rows
written in the meantime are additive and harmless to leave behind.
