"""⛔⛔⛔ A DEAD TRANSACTION MUST NOT BE ABLE TO PUBLISH A SCALAR.

2026-08-25, the first CF24 re-measure. Production had not yet run
`memtrust001`, so the very first memory read raised `UndefinedColumn`. That
ABORTED the transaction; every query after it raised `InFailedSqlTransaction`
and returned nothing. The process exited **0** and printed
`C OWNERSHIP RATE 9.0%` — a number produced by a session that had been dead
for 52,680 lines of cascade.

⭐⭐⭐ A ZERO FROM AN ABORTED TRANSACTION IS BYTE-IDENTICAL TO A GENUINE
REFUSAL. This is the same "unknown became zero" class the project keeps
catching — [[feedback_arnie_absence_is_not_a_negative]] — except here the
instrument itself was the one converting the unknown, and its exit code said
everything was fine.

So: if ANY database query faults, the run exits non-zero and prints NO
ownership rate. Not a smaller rate, not a flagged rate — none.
"""
from __future__ import annotations

import pytest

from scripts.measure_settlement_coverage import _FAULT_WATCH, main, render


@pytest.mark.asyncio
async def test_a_swallowed_query_error_is_still_recorded():
    """⛔ THE LISTENER SITS AT THE DBAPI LAYER, WHICH IS THE ONLY PLACE IT CAN
    SEE THIS. A caller with a bare `except` eats the exception and returns a
    default; the report is then built from defaults with nothing to show a
    reader anything went wrong. The fault has to be recorded where it is
    raised, not where it is handled."""
    import os

    from sqlalchemy import text

    from db.database import make_engine

    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("needs TEST_POSTGRES_URL")

    _FAULT_WATCH.reset()
    engine = make_engine(url)
    _FAULT_WATCH.attach(engine)
    async with engine.connect() as conn:
        try:
            await conn.execute(text("SELECT column_that_does_not_exist"))
        except Exception:          # noqa: BLE001 — exactly the swallow we fear
            pass
    await engine.dispose()

    assert _FAULT_WATCH.faults, (
        "a query faulted and the watch recorded nothing — a run can still "
        "publish a rate computed from a poisoned session")
    assert "column_that_does_not_exist" in _FAULT_WATCH.faults[0]


def test_a_faulted_run_prints_no_rate_and_exits_nonzero(monkeypatch, capsys):
    """⛔⛔⛔ THE WHOLE POINT. `render()` must never be reached."""
    import scripts.measure_settlement_coverage as M

    _FAULT_WATCH.reset()

    async def _fake_measure(**_kw):
        _FAULT_WATCH.faults.append(
            "UndefinedColumn: column user_food_matches."
            "settled_by_operation_id does not exist")
        return _healthy_report()

    monkeypatch.setattr(M, "measure", _fake_measure)
    monkeypatch.setattr("sys.argv", ["measure_settlement_coverage"])

    rc = main()
    out = capsys.readouterr().out + capsys.readouterr().err

    assert rc != 0, "a poisoned run exited 0 — that is how 9.0% got published"
    assert "OWNERSHIP RATE" not in out, (
        "a rate was printed from a run whose queries faulted; a flagged "
        "number still gets read as a number")
    assert "9.0" not in out


def test_a_clean_run_still_publishes(monkeypatch, capsys):
    """⭐ THE NEGATIVE INVARIANT. Fail-closed must not mean fail-always, or
    this test suite would pass against an instrument that never reports
    anything — which is its own way of publishing nothing forever."""
    import scripts.measure_settlement_coverage as M

    _FAULT_WATCH.reset()

    async def _fake_measure(**_kw):
        return _healthy_report()

    monkeypatch.setattr(M, "measure", _fake_measure)
    monkeypatch.setattr("sys.argv", ["measure_settlement_coverage"])

    rc = main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "OWNERSHIP RATE" in out, (
        "a clean run published nothing — the guard cannot tell a healthy run "
        "from a poisoned one")


@pytest.mark.asyncio
async def test_the_REAL_measure_attaches_the_watch_to_its_OWN_engine():
    """⛔⛔⛔ THE WIRE, AND MUTATION G3 IS WHY THIS EXISTS.

    Deleting `.attach(engine)` from `measure()` left every other test in this
    file GREEN — because they attach the watch themselves or monkeypatch
    `measure` away. A guard that only the tests install is a guard production
    does not have, which is the same shape as CF23's inert predicate.

    So this reproduces 2026-08-25 exactly: a schema MISSING
    `settled_by_operation_id`, the real `measure()`, and one frozen row to
    make it reach the memory rung. Asserting structurally that the source
    contains `attach` would be the M5 grep trap — the identifier survives in
    the comment above the call.
    """
    import os

    import psycopg
    from sqlalchemy.engine import make_url

    import scripts.measure_settlement_coverage as M

    if not os.getenv("TEST_POSTGRES_URL"):
        pytest.skip("needs TEST_POSTGRES_URL")

    # ⛔ DERIVE THE CONNECTION, NEVER REBUILD IT FROM `getpass.getuser()`.
    # The first version assumed local peer auth and died in CI with
    # `fe_sendauth: no password supplied` — a laptop-only credential
    # assumption that the laptop cannot see.
    db_name = "arnie_guard_probe"
    base = make_url(os.environ["TEST_POSTGRES_URL"])
    admin_url = base.set(database="postgres").render_as_string(
        hide_password=False).replace("postgresql+psycopg://", "postgresql://")
    url = base.set(database=db_name).render_as_string(hide_password=False)

    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
    admin.execute(f'CREATE DATABASE "{db_name}"')
    admin.close()

    try:
        from sqlalchemy import text as _t

        # `make_engine`, not `create_engine` — db/database.py refuses an
        # unpinned Postgres engine, and that guard is right.
        from db.database import make_engine
        from db.models import Base
        builder = make_engine(url)
        async with builder.begin() as c:
            await c.run_sync(Base.metadata.create_all)
            # the exact 2026-08-25 production shape: code ahead of schema
            await c.execute(_t("ALTER TABLE user_food_matches "
                               "DROP COLUMN settled_by_operation_id"))
        await builder.dispose()

        _FAULT_WATCH.reset()
        M._database_url = lambda: url                      # noqa: SLF001
        await M.measure(days=30, limit=10, population={
            "name": "guardprobe", "frozen_at": "test", "entry_ids": [1],
            "rows": [{"entry_id": 1, "turn_id": "t:guard", "user_id": 1,
                      "source": "structured_food:food_interpreter_v2",
                      "food_name": "chicken breast", "quantity": "150 g"}]})

        assert _FAULT_WATCH.faults, (
            "the real measure() ran against a schema missing "
            "settled_by_operation_id and recorded NO fault — it is not "
            "attaching the watch to the engine it actually uses")
        assert any("settled_by_operation_id" in f for f in _FAULT_WATCH.faults)
    finally:
        admin = psycopg.connect(admin_url, autocommit=True)
        admin.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        admin.close()


def test_the_probe_connection_carries_the_credential_it_was_given():
    """⛔⛔ THE BUG CI CAUGHT AND THE LAPTOP STRUCTURALLY COULD NOT.

    The first wire test built its admin connection from `getpass.getuser()`
    against `localhost` with no password. That works on a laptop with peer
    auth and dies in CI with `fe_sendauth: no password supplied`. A local
    environment cannot observe a credential assumption it happens to satisfy.

    ⭐ So the derivation is pinned as a pure function against a
    PASSWORD-BEARING url — the shape the developer machine never produces.
    """
    from sqlalchemy.engine import make_url

    base = make_url("postgresql+psycopg://ci_user:s3cret@db.internal:6543/arnie_test")
    admin = base.set(database="postgres").render_as_string(hide_password=False)
    probe = base.set(database="arnie_guard_probe").render_as_string(
        hide_password=False)

    for rendered in (admin, probe):
        assert "s3cret" in rendered, (
            "the password was dropped deriving the probe connection — this is "
            "the fe_sendauth failure that took CI #1555 red")
        assert "ci_user" in rendered and "db.internal:6543" in rendered, (
            "host/user were rebuilt rather than carried over")
    assert admin.endswith("/postgres")
    assert probe.endswith("/arnie_guard_probe")


def _healthy_report() -> dict:
    return {
        "rows": 361, "meals": 232, "window_days": 30,
        "predicate_commit": "test", "population": {"frozen": True,
                                                   "name": "p16b_0817"},
        "A_routing_rate_pct": 83.3,
        "B_support_rate_within_structured_pct": 10.8,
        "C_ownership_rate_pct": 9.0,
        "_selected_entry_ids": [],
        # the rest are only what `render` dereferences; the three rates above
        # are the subject of this file
        "supported_structured_meals": 20, "structured_meals": 185,
        "legacy_meals": 37, "not_a_chat_turn_meals_EXCLUDED": 10,
        "unrecognised_writer_meals": 0, "expected_rung_of_supported": {},
        "why_structured_meals_decline": {}, "limits": [],
    }
