# One clock

**Tracked migration item. Unify every freshness comparison on one authoritative
clock source. This gates removal of the legacy lane.**

## The invariant

> A stored timestamp and the clock it is compared against are the same clock.

Nothing enforced that. The system has had **two** clocks since it was written,
and they agreed only because production happens to run in UTC.

## What was actually wrong

43 columns are naive `DateTime` filled by the **database** —
`server_default=func.now()`. Every freshness rule is judged in **Python**
against `datetime.utcnow()`. Postgres `now()` returns a `timestamptz`; storing
it in a `timestamp without time zone` converts it through the **session's**
`TimeZone`. So the gap between the two clocks is whatever the database server's
timezone happens to be — an ambient default, settable per-server, per-database,
per-role, or by a client `PGTZ`, and recorded nowhere in this repository.

Both directions fail **silently**, which is why nothing caught it:

| server | stored time reads as | consequence |
|---|---|---|
| **west of UTC** (e.g. `America/New_York`) | ~4 hours **old** | `STALE_CLAIM_SECONDS = 90` is passed instantly, so every duplicate delivery "takes over" a claim that is still running and the meal is **written twice**. Idempotency reports success, twice. |
| **east of UTC** (e.g. `Europe/Berlin`) | in the **future** | the age is negative, never reaches the threshold, every retry raises `IdempotencyInProgress`, and the key **wedges permanently**. |

Worse, four columns are written by the **database clock on INSERT** and by
`datetime.utcnow()` **on UPDATE**:

| column | Python writer |
|---|---|
| `idempotency_records.created_at` | `core/idempotency.py:301` — the takeover itself |
| `pending_questions.last_asked_at` | `db/queries.py:2110` |
| `device_tokens.last_seen_at` | `db/queries.py:174` |
| `user_food_matches.last_used` | `db/queries.py:3216` |

On a non-UTC server one column then holds a **mix** of local-time and UTC
values, with nothing recording which row is which. That is not repairable after
the fact.

### How it was found

Not by reading. `tests/test_two_connections_one_meal.py` was run against a
Homebrew Postgres (default `America/New_York`) while proving the commit
boundary, and three callers were all granted the same idempotency key, logging
`event=idempotency_takeover age_s=14400` — exactly the EDT offset.

Production and CI are both UTC (verified 2026-08-04: `SHOW timezone` = `UTC`,
`now()::timestamp - (now() at time zone 'utc')` = `0.0s`), so it does not
manifest there. **That is what made it dangerous**: a correctness property held
by luck of deployment, which would fail silently after a restore, a provider
move, or a `SET timezone` in a dashboard.

## Step 1 — landed: the timezone axis is removed

The contract is binary, and it is enforced rather than attempted:

> **UTC confirmed → the connection may be used. Not confirmed → nothing gets it.**

`db/database.py`:

* **`make_engine(url, **kw)`** — the one way to build an engine. Production,
  tests and scripts all use it, so the guarantee cannot be missed by
  construction.
* **`pin_session_utc(engine)`** attaches a `connect` listener that sets the
  session to UTC, commits, and **reads it back**. Any failure, or any answer
  that is not UTC, raises `SessionTimezoneNotPinned` — so the connection never
  enters the pool.
* **A global `engine_connect` guard** refuses any Postgres engine that was
  never pinned. It is an in-process attribute check, not a query, so it costs
  nothing per checkout.
* **A startup check** in `api/app.py` proves at boot that this deployment's
  sessions are UTC, and is **fatal** if not. The per-connection read-back would
  otherwise surface the problem one request at a time; a misconfigured
  deployment should fail its health check instead of serving traffic that
  quietly mis-ages every claim.

Three things that were wrong in the first attempt and are worth not repeating:

* **Logging is not enforcement.** The first version logged the failure and
  returned, which handed the application the exact connection the check exists
  to reject. A driver error, a permission restriction or an unexpected cursor
  would have been recorded and the unreliable connection used anyway.
* **The commit is load-bearing.** `SET` is transactional and the pool rolls
  back every connection it hands out, so `SET TimeZone='UTC'` alone runs,
  raises nothing, and is silently reverted — a fix that reads as correct and
  does nothing. Verified both ways.
* **Driver detection must key on the dialect.** The first version matched
  substrings like `"psycopg"` against `type(dbapi_conn).__module__`, which is
  implementation detail: SQLAlchemy hands the sync `connect` event an *adapter
  proxy* for async drivers, so a renamed or unanticipated adapter matches
  nothing and the listener does nothing at all. `dialect.name == "postgresql"`
  is public API and identical for psycopg, psycopg2, asyncpg and pg8000.
  (Only psycopg is in use in production and CI.)

The global reach is deliberate but narrow: the factory *applies* the setting
only to engines it is given, while the global piece only *refuses* — so this
module never silently forces a session setting on somebody else's database.

Proof: `tests/test_one_clock.py` sets the **database's** default timezone away
from UTC and requires a fresh connection to still be UTC — written that way so
it stays meaningful on CI, where the server is already UTC and a bare
"is it UTC?" assertion would pass without touching the mechanism. It also
covers the refusal paths, including that a rejected connection is re-checked on
every attempt rather than pooled and handed out again. Mutation checked:
reverting to log-and-continue, dropping the read-back, or removing the
unpinned-engine guard each turns the matching test red.

### Operational reach — exercise before rollout

The global refusal means **every** Postgres engine in a process that imports
`db.database` must be pinned. That is the correct failure mode, but it has to
be walked, not assumed. It was:

| entry point | state |
|---|---|
| `api/app.py` (the app engine) | pinned; startup check is fatal |
| `alembic/env.py` | **was broken — fixed.** It imports `db.models`, which registers the guard, then builds its own *synchronous* engine via `engine_from_config`. `alembic upgrade heads` runs pre-deploy, so **every deploy would have failed.** Verified end to end: the full chain now runs clean on a fresh database to head `mealcommit001`, 41 tables. |
| `scripts/fix_alembic_orphan_d4.py` | imports `db.database`, so it *would* have been refused — pinned |
| `scripts/backfill_processing_level.py` | does not import `db.database`, so nothing refused it; it would have run **unpinned**, the quieter half of the same defect — pinned |
| `simulate_*.py`, `scripts/repro_*.py` | sqlite only; unaffected |

`tests/test_one_clock.py::test_alembic_can_still_reach_a_postgres_database`
runs `alembic` as a **subprocess**, the way the deploy does, so this cannot
silently break again. Mutation checked: removing the pin from `env.py` turns it
red.

**Known bounded gap.** Six scripts connect with raw `psycopg.connect()` and so
bypass both the factory and the guard: `scripts/knowledge_audit.py`,
`logging_audit.py`, `extract_replay_corpus.py`, `audit_food_damage.py`,
`verify_db_restore.py`, `latency_report.py`. All are read-only audit and report
tools — on a non-UTC server they would *report* offset ages (`latency_report`
most visibly), but they write nothing, so no data is at risk. Fold them into
step 2 rather than pinning six call sites piecemeal.

## Step 2 — done: the database clock is the one clock

**The choice was measured, not preferred.** Every freshness comparison in the
codebase read a timestamp the DATABASE wrote (`server_default=func.now()`) and
compared it against `datetime.utcnow()` — all cross-domain, and the values live
in the database. So the database is the only clock that makes both sides of
every comparison agree by construction. (Option (a) from the original plan, by
mechanism rather than by rewrite.)

**The mechanism is arithmetic, not I/O** — `core/clock.py`:

    clock.now() == datetime.utcnow() + (db_now − app_now)

* the offset is measured at boot (`api/app.py` startup, after the UTC check)
  and re-measured every 15 minutes by the scheduler (`clock_resync`), because a
  host whose NTP has failed drifts without bound and a single boot-time
  measurement cannot see it;
* the round trip straddles the reading, so the midpoint is the comparison
  point — otherwise the query's own latency reads as drift;
* before the first sync the offset is **zero** and `clock.now()` is exactly
  `utcnow()`: a deployment that never syncs is no worse than before this
  module existed, which is what made it adoptable without a flag;
* a failed sync keeps the previous offset (a stale correction is closer than
  none) and never raises;
* skew ≥ 5s logs `event=clock_sync outcome=skewed` at error level — that is
  NTP failing, and it is worth knowing before the 90-second staleness
  threshold starts lying. **The measurement is the point as much as the
  correction**: a drifting host was previously silent.

**Converted: 25 comparison sites** (the original inventory said 17; the sweep
that ran with a broader pattern found 26, the extra nine being
`cutoff = utcnow() − timedelta(...)` values passed into SQL `WHERE` clauses).
The 26th stays on the application clock **by design**:
`bot/telegram_handler.py` compares `whoop_token_expires_at`, which the app
computed from the OAuth `expires_in` — same-domain already. The rule is
"compare with the clock that wrote it", and it cuts both ways.

**Enforced, not remembered** — `tests/test_one_clock_step2_0805.py`:

* a ratchet fails on any NEW `utcnow()` freshness comparison in production
  code (the by-design exception is named, and goes stale loudly if removed);
* the idempotency claim — the tightest threshold, and the one that decides
  whether a meal is written twice — is pinned to `clock.now()` by its own test;
* unmeasured is reported as `None`, never as `0.000` — a health surface
  printing zero for "never measured" claims a guarantee nobody checked.

Mutation-checked: a synthetic new `utcnow()` comparison, reverting idempotency
to the app clock, and making `clock.now()` ignore the offset each turn the
matching test red.

**Remaining, folded here from step 1's known gap:** six read-only audit scripts
use raw `psycopg.connect()` and report ages on the app clock. They write
nothing; converting them is cleanup, not correctness.

## The gate

The legacy lane must not be removed while two clock sources remain. The
canonical lane's commit boundary depends on claim freshness being judged
correctly; if a claim's age can be wrong, "commits at most once" is not a
guarantee, it is a coincidence — which is exactly the property this whole
migration exists to replace.
