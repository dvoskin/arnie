# Hardening journal — append-only

Base: `origin/main` @ `433cdf3`. Branch: `dvoskin/prod-truth-hardening`.
Worktree: fresh off `origin/main` (the primary `Code Learn/arnie` checkout is
on `feat/coach-card-microviz` with 101 dirty files and was not touched).

---

## 2026-07-31 — entry 1: deployed truth

**Finding — the starting hypothesis was stale.** `/health` reports commit
`433cdf39f2d0`, which is the tip of `origin/main`. The brief's "deployed
`27d6f7b`, main ~8 ahead" was true when written; a deploy has since happened.
**There is no undeployed backend drift.** Full record in
`DEPLOYED_STATE_2026-07-31.md`.

**Finding — configuration drift, HIGH.** `render.yaml` documents
`NUTRITION_RESOLVER_MODE: live` "for ALL users (Danny 2026-07-25)".
Production reports `shadow`, `env_set: true`, and
`resolver_owns_committed_values: false`. Traced through
`skills/nutrition/canary.py:242`: the gate returns `False` at `resolver_mode()
!= MODE_LIVE`, so the nutrition resolver does **not** own committed values in
production and everything gated behind it is inert.
**Decision: did not touch it.** Whether `shadow` is a deliberate rollback or a
promotion that never happened is a fact about intent, not about the repo.
Escalated to Danny.

**Finding — an unknown that no longer has to be.** The applied alembic
revision in production was unreadable from anywhere: `/health` reported the
commit and the flags but not the schema, and `render.yaml`'s
`preDeployCommand: alembic upgrade heads` is documentation — the service is
configured by hand in the Render dashboard and Render never reads that file.
Addressed in entry 3.

**Method note.** No `DATABASE_URL` for production is available in this
environment, so production *data* could not be queried. Every such row in the
report says `unknown` rather than carrying a value inferred from `main`.

---

## 2026-07-31 — entry 2: P0 — a tap is a turn (quick-log)

**Root cause.** `record_ledger_event` (`db/queries.py:3003`) stamps the
canonical turn id by reading the ambient contextvar
`core.turn_identity.CURRENT_TURN_ID`. Every chat surface sets it.
`api/quick_log.py` never did. So every tap-logged ledger event landed with
`turn_id = NULL` — on the primary iOS logging surface. Separately, the three
endpoints had no request identity at all, so a retried delivery wrote the food
twice.

**Evidence (measured, not reasoned).** A probe run against the deployed code
at `433cdf39f2d0`, two identical taps:

```
food rows written by two identical taps : 2
ledger events written                   : 2
turn_id on each event                   : [None, None]
source on each event                    : ['quick_log:ios', 'quick_log:ios']
```

**Fix.**
- `core/idempotency.py` (new) — one claim contract for direct-write surfaces.
  Insert-first, so two racing workers resolve against the unique index rather
  than a select-then-insert window. Conflicting payload under a reused key →
  loud 409. Unfinished claim older than `STALE_CLAIM_SECONDS` (90) is taken
  over, so one crash cannot wedge a key forever.
- `db/models.py` — `IdempotencyRecord`, unique on `key`.
- `alembic/versions/idem001_add_idempotency_records.py` — pure ADD: new table,
  no backfill, no constraint applied to existing rows, so it cannot fail on
  production data. Chains off `pendinguniq001`; `alembic heads` still reports
  exactly one head.
- `api/quick_log.py` — all three handlers mint a turn id via `make_turn_id`,
  bind it for the request in `_turn_scope` (reset in `finally`), take a claim,
  and return the ORIGINAL committed result on replay.

**Decision — an absent key deduplicates nothing.** Only the client can tell a
retry from a second helping. `make_turn_id`'s hour-bucketed hash fallback is
correct for *identity* but wrong for *idempotency*: using it would silently
collapse a genuine second banana logged twenty minutes later. So traceability
is unconditional (the turn id is always minted) and deduplication requires an
explicit `Idempotency-Key`. Dropping food the user really ate is the worse
failure.

**Bug found and fixed during the work.** `Header(None, alias=...)` resolves
only when FastAPI calls the handler; a direct call receives the `FieldInfo`
default. Stringified, that produced a turn id of
`ios:annotation=Union[str, NoneType] required=False…` — worse than the NULL it
replaced, because it is identical for every keyless request, so two unrelated
taps would have collided on one id. `_client_key()` now treats anything that
is not a non-empty string as absent.

**Tests** — `tests/test_a_tap_is_a_turn.py`, 8 tests.
Verified failing-first against the deployed code:
`test_a_keyless_tap_still_produces_a_traceable_event` fails with
`AssertionError: assert None is not None` on `433cdf3` — a behavioural
failure, not a signature error. The other 6 behavioural tests fail on the
pre-fix signature.
`test_the_database_rejects_a_duplicate_claim` pins the unique index directly,
because every other test here would still pass if that constraint were
dropped.

**Known limit, stated rather than hidden.** The concurrency test exercises
async interleaving on ONE connection: the test engine is
`sqlite+aiosqlite:///:memory:`, which SQLAlchemy backs with a StaticPool, so
two sessions share a connection and cannot truly race at the storage layer.
The cross-process guarantee rests on the unique index, which is pinned
separately. A genuine multi-worker race test needs a Postgres-backed fixture
and is **not** covered here.

---

## 2026-07-31 — entry 3: PR 1 — the schema stops being invisible

`/health` now reports which migration the live **database** is on, alongside
the commit and flags:

```json
"schema": {"applied": "...", "expected": "idem001", "in_sync": true}
```

- `api/diagnostics.schema_summary()` reads `alembic_version` from the live DB.
- `_expected_head()` reads the head from the shipped script directory, resolved
  from `__file__` rather than the working directory, and caches it.
- Never raises: an unmigrated database has no `alembic_version` table, which is
  an answer, not a crash. `in_sync` is **absent** when `applied` is unknown —
  a missing answer must not read as a passing one.

**Tests** — `tests/test_health_reports_the_schema_revision.py`, 4 tests,
including the deploy this is meant to stop (code ahead of schema → `in_sync:
false`) and the foreign-CWD case.

---

## 2026-07-31 — entry 4: branch disposition

Full table in `BRANCH_DISPOSITION_2026-07-31.md`.

**PR #67 — close, extract nothing.** `git cherry` reports 3 of 4 commits
"missing", which is wrong in the way that matters: each was then checked for
its own distinguishing content in main and all four are shipped
(`api/undo.py` byte-identical; `_debounce_seconds` at `api/chat.py:51`;
`"MID-SENTENCE"` at `clarify_policy.py:260`; `"ONE DAY, ONE SOURCE"` at
`conversation.py:2270`). Merging it would revert 168 commits of live behaviour.

**Composites — genuinely open.** `skills/nutrition/composites.py` does not
exist on main, yet `authority.py:439` ships the label "Estimated from its
components" and `tool_executor.py:1283` calls it out as prose asserting an
action nobody performed. Recommend extracting
`claude/open-issues-composites-stall-usda-1ipqnu` (it carries
`tests/gold/usda_component_rows.py`, the ground truth the 07-30 audit said was
missing) onto a fresh branch, plus the shadow wiring from the sibling branch.
**Deferred deliberately** — P2 work, and building it while the resolver is in
`shadow` would be building on an inert foundation.

---

## Remaining risks

1. **`NUTRITION_RESOLVER_MODE=shadow` in production, `live` in the docs.**
   Unresolved and not mine to resolve. Until answered, the deployed nutrition
   behaviour is the legacy path, and any Phase 5 work assuming resolver
   ownership is building on nothing.
2. **Production data was never inspected.** No `DATABASE_URL`. The historical
   `turn_id IS NULL` population in `ledger_events` is unmeasured, so the size
   of the backfill (if one is wanted) is unknown.
3. **The fix is forward-only.** Existing NULL-`turn_id` tap-log events stay
   NULL. No backfill is possible: the turn ids were never minted, so there is
   nothing to recover them from. New writes are correct from deploy onward.
4. **iOS does not send `Idempotency-Key` yet.** Server-side is backward
   compatible (keyless taps still work and are now traceable), but the
   duplicate-write protection does not engage until the client sends the
   header. **The client change is required to close the duplicate gap** and is
   not in this pass.
5. **Multi-worker concurrency is unproven by test.** See entry 2. The
   constraint is the guarantee; no Postgres-backed race test exists.
6. **Phases 4-9 are untouched** — transaction ownership/outbox, clarification
   state machine, replay framework, tracing/metrics, latency budgets, rollout
   controls. The existing helpers still commit independently
   (`add_food_entry` commits, then `record_ledger_event` commits), which is
   the Phase 4 gap and was out of scope for a P0 pass.
