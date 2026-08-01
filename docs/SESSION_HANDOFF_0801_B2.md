# B2 — mutation contract. Session handoff, 2026-08-01

Branch `dvoskin/b2-mutation-contract`, from `origin/main` @ `fca59a4`.
Full suite green at every commit. `python scripts/mutation_inventory.py --check`
passes; `--check --strict` is the exit criterion and still fails.

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

    UNKNOWN mutation surfaces: 0        ← achieved
    Class A routes short of contract: 20 ← the remaining work

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

**The gate, wired into `.github/workflows/ci.yml`.** Fails on an undeclared
route, a stale declaration, and any route regressing from compliant. Class A
gaps are **ratcheted** against `docs/mutation_baseline.json` rather than
enforced outright — 20 are open, and a gate that is red the day it lands
teaches everyone to ignore it. New Class A gaps fail immediately; the recorded
list may only shrink. `--check --strict` drops the ratchet and is the B2 exit
criterion.

## Migrated this session (Class A, fully compliant)

`/api/v1/water` POST · `/api/v1/water/{id}` PATCH+DELETE ·
`/api/v1/food/{id}` PATCH+DELETE · `/api/v1/exercise/{id}` PATCH+DELETE
(joining the three `quick_log` routes that were already done).

All ten required properties are proven for these in
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

## What is left

Run `python scripts/mutation_inventory.py` for the live list. In the priority
order Danny set:

1. **Dashboard edits** (`/api/food|exercise|water/{id}`, `/api/*/log`,
   `/api/weight/log`) — Class A, token-auth twins of the iOS routes already
   done. Same data, same contract owed. Largest single block.
2. **Health-import reconciliation** (`/api/v1/health/snapshot|weights`,
   `/health/apple`, `/api/whoop/sync/{token}`) — declared naturally idempotent
   on `source_ref`, so the property that needs proving is the **tombstone**:
   a user's delete must survive the next sync or the row resurrects.
   `HealthImportTombstone` exists; it is untested from these routes.
3. **`/api/v1/ledger/undo`** — Class A, currently zero guarantees. Undoing
   twice must not undo two things.
4. **Chat lane** (`/api/v1/chat`, `/photo`, `/voice`, `/api/chat/{token}`) —
   has turn id + claim, needs the trace and durable result. Its ledger events
   are written by the executor per operation, so `ledger_event` reads as
   unknown from a static read of the handler; verify before "fixing" it.
5. **Class B: 0 of 29 compliant.** They mostly need a `RequestTrace` and a
   canonical turn id — cheap and mechanical, no claim required. Goal/target
   changes (`/api/v1/targets`, `/auto-targets`) matter most: they steer every
   later coaching decision, so the audit trail is the point.
6. **Class C: 7 of 17.** Six admin routes lack an audit log line; the auth
   routes lack one too.

## Gotchas for whoever picks this up

- `_turn_scope`, `_client_key` and `_claim_failed` live in `api/quick_log.py`
  and are **imported**, not re-declared. The contextvar leak and the
  keyless-collision trap are real past incidents; a second copy of either is a
  second chance to reintroduce them.
- Adding a route without a line in `core/mutation_policy.py` fails CI. That is
  the point.
- Re-run `--write-baseline` after closing gaps so the ratchet tightens.
- The concurrency-test observation is coarse: a handler name counts if it
  appears in a test module that also uses `asyncio.gather`. It is evidence a
  concurrency test exists, not proof it is a good one.
