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

## 2026-07-31 — entry 5: landed on main, and what CI said about it

Danny: *"I want your updates on main — it's going to get lost in these
branches."* Fair, with 69 remote branches. The work was fast-forwarded onto
`main` rather than left on a feature branch.

**CI was red on the first push, and the reason is worth recording.** The
`test` job compiles the HEAD migration *offline* against Postgres
(`alembic upgrade <range> --sql`). `idem001` called
`sa.inspect(op.get_bind())` unconditionally; offline that bind is a
`MockConnection`, which has no inspection system:

```
sqlalchemy.exc.NoInspectionAvailable: No inspection system is available
for object of type MockConnection
```

The inspect-then-create guard is a repo convention (the SQLite test DB builds
tables from `db/models.py` metadata before migrations run), so it stays — but
online only. A generated SQL script should carry the DDL unconditionally
anyway: there is no database present to ask.

Verified **both** ways this time rather than one: the offline compile emits the
`CREATE TABLE` and all three indexes against Postgres, and the online
upgrade/downgrade round-trip still works on SQLite.

## 2026-07-31 — entry 6: the degraded path

Once iOS sends `Idempotency-Key` the claim runs on every tap, against a table
that exists only if `idem001` has been applied — which this pass established is
**not** guaranteed, because `preDeployCommand` is a Render dashboard setting and
`render.yaml` is never read by Render.

A missing table now degrades to **no deduplication, logged loudly**, instead of
raising. The write and its turn id do not depend on that row. Duplicates become
possible again until the migration runs, which is strictly better than a 500
that loses the meal the user just logged.

**Bug caught by the test, not by reading the code.** The first version of that
soft-fail called `await db.rollback()`, which expires every object loaded in
the session; the next attribute access on `user` then attempted IO from a sync
context and died with `MissingGreenlet`. That is precisely the trap
`record_ledger_event` documents in its own comment — the soft-fail reintroduced
the poisoning it existed to prevent. `begin_nested()` already releases the
savepoint; no session-level rollback belongs there.

## 2026-07-31 — entry 7: the iOS half (arnie-ios)

`feat/badges-v2` @ `86a9f6e`, pushed. The branch was **local-only** until now —
no remote counterpart — so it was backed up as part of landing this.

- `Endpoint` grows a `headers` dictionary; `APIClient` applies it after the
  built-ins.
- The three quick-log routes mint an `Idempotency-Key` once per Endpoint value.

**Why once-per-Endpoint is the correct scope:** `APIClient.request` re-`perform`s
the *same* endpoint value after a 401 re-sign-in. A key minted per *send* would
mean the app's own recovery path logged the user twice. Pinned by
`theFourOhOneRetrySendsTheSameKey`, with its mirror
`twoSeparateLogsGetDifferentKeys` — a key stable across genuine actions would be
worse than none, silently swallowing the second helping.

`URLProtocolStub` now records requests, so tests assert on what actually went
over the wire rather than only on what came back.

**Read the build output, do not trust the exit code.** The first
`xcodebuild test` run returned exit 0 while reporting `** TEST FAILED **` —
three compile errors (Swift Testing's `Comment` takes a string *literal*; I had
used `+` concatenation). Confirmed green only after reading the log:
`✔ Test run with 4 tests in 1 suite passed`.

## Deploy order (both halves are coupled)

1. Deploy `arnie` main, **with `alembic upgrade heads` actually run** — confirm
   via `/health` → `schema.in_sync: true`.
2. Then ship the iOS build.

Reversed, the header arrives before the table exists; the server degrades
safely (entry 6) but the protection simply is not there.

## 2026-07-31 — entry 8: a red CI I could not reproduce

`08ce423` — a commit that adds ONE file under `scripts/` and nothing else —
came back red. `c52f1f4`, its parent and the commit carrying every functional
change in this pass, is green and DEPLOYABLE.

**Which step failed, established without the log** (the repo is public, so
check-runs and per-step results are readable unauthenticated; job *logs* are
not — 403):

| step | result |
|---|---|
| 6. Byte-compile | pass |
| 7. Alembic — one head + offline Postgres compile | **pass** |
| 8. Run tests | **FAIL** |

Step 7 passing is worth stating on its own: the offline-compile fix from
entry 5 is confirmed in CI, not just locally.

**Six local runs, none of which reproduced it:**

| run | order | env | result |
|---|---|---|---|
| 1 | deterministic (`-p no:randomly`) | plain | 0 failures |
| 2-3 | shuffled | plain | 0 failures |
| 4-6 | shuffled | `LINKING_ENABLED=true`, `PROACTIVE_MESSAGING_ENABLED=false` (CI's) | 0 failures |

Ruled out along the way, each by direct test rather than reasoning:

* the four tests that reference `scripts/` — pass
* `test_turn_ownership_invariant.py`, the only test that walks the repo tree,
  and the one thing that had not been run since the file was added — passes
* **dependency drift** — all 26 requirements are exact pins, so CI installs
  what this venv has
* **the shuffle not actually running** — `pytest-randomly 4.1.0` is installed
  and loaded, matching the pin, so runs 2-6 were genuinely shuffled

What remains different from CI: Ubuntu x86_64 vs macOS arm64, and network
behaviour.

**Not called flaky.** Six clean runs is evidence against reproducibility, not
evidence of correctness, and "probably unrelated" is the exact species of
claim this pass exists to distrust. It is recorded as OPEN.

**What would close it:** the failing test name from the Actions page, or `gh`
installed and authenticated — then the log gives both the test and the
`--randomly-seed`, and the ordering reproduces exactly. A missing `gh` cost a
detour three times today (PR #67's disposition, this, and reading check status
at all).

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
