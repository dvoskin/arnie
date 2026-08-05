# Pending operations and the commit boundary — migration note

**Additive. Deployable while production keeps running unchanged.** Nothing is
renamed, dropped or backfilled, and no live path reads or writes the new
tables yet.

## What the migration adds

`mealcommit001` creates two tables.

**`pending_operations`** — the durable operation record. `status` holds the
full lifecycle; `storage_status` is a projection for cheap open/closed queries.
Five operation states project onto `active`, so **`status` is never
reconstructed from `storage_status`** — they are separate columns for that
reason.

**`meal_commits`** — the authoritative result, with
`UNIQUE (operation_id, operation_revision)`. That constraint is the whole
point: an application-level `if not already_committed(key)` cannot arbitrate
concurrent workers, because both read "not committed" and both write.

## Rollback

```sql
-- Both tables are unreferenced by any live path.
DROP TABLE meal_commits;
DROP TABLE pending_operations;
```

or `alembic downgrade metrics001`. No data migrates back because none moves
forward: the legacy pending path is untouched and remains authoritative.

Flags are the faster lever and need no deploy — all four default **off**:

```
PENDING_OPERATION_PERSIST_SHADOW=false
PENDING_OPERATION_READ_SHADOW=false
COMMIT_COORDINATOR_SHADOW=false
COMMIT_COORDINATOR_ENFORCE=false
```

Separate on purpose: a problem in persistence must not force disabling commit
enforcement, and vice versa.

## Deploy order

1. `alembic upgrade heads` — tables appear, nothing uses them.
2. Enable `PENDING_OPERATION_PERSIST_SHADOW`; watch `pending_persist_shadow`.
3. Enable `COMMIT_COORDINATOR_SHADOW`; watch `commit_shadow` for mismatches.
4. Only then consider `COMMIT_COORDINATOR_ENFORCE`.

Step 4 is the first that changes behaviour. Everything before it is
observation.

## What is NOT done

Stated explicitly because the directive asks for it and because overstating
here is the expensive kind of error:

- the 30 production mutation sites are **not** consolidated
- typed clarification is **not** authoritative
- the legacy lane is **not** deleted
- `commit_or_load_existing()` does **not** yet write food rows — the claim and
  result persistence are proven, the ledger write is still the legacy path's
- no production traffic touches either table

## Verified

- `UNIQUE (operation_id, operation_revision)` refuses a duplicate **at the
  database**, proven with two sessions
- a duplicate receives the **original** result, not `None`
- a claim with no recorded result reports `None` so a retry can tell the first
  attempt did not finish
- a stale revision write is refused and reports the current revision
- revision 2 cannot overwrite revision 3
- malformed payloads fail closed and emit telemetry
- migration DDL and ORM model agree, checked by test
