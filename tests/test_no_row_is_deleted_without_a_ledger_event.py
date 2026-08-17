"""A DELETE THE LEDGER NEVER SAW IS A DELETE NOBODY CAN TAKE BACK.

MEASURED IN PRODUCTION 2026-08-07 14:59:07. "Clear my day" removed
`food_entries` 2887-2900 — fourteen rows, four of them `canonical:create` — and
wrote ZERO `deleted` ledger events. Undo was impossible; the canonical lane's
own commits vanished with no trace of what they had been.

THE INSTRUMENT WAS PROVEN BEFORE THE CONCLUSION. 123 food `deleted` events
exist and `delete_food_entry` ran sixteen times in the same seven days, so the
ledger CAN record a food delete. Its silence on the clear path was the clear
path's fact, not the ledger's.

`delete_food_entry` had it right all along: read the payload off the row while
it still exists, delete, recompute, record — one transaction. `reset_today_log`
issued a bulk `delete()` and recorded nothing, which is the same class of defect
as a mutation with a second writer: the row moves and the history does not.

THE RATCHET IS THE POINT. Fixing one caller leaves the next one free to repeat
it, and there is no test that could have caught this one because nothing
asserted the general rule. `test_no_deleter_bypasses_the_ledger` is that rule.
"""
from __future__ import annotations

import ast
import json
import pathlib
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import Base, DailyLog, ExerciseEntry, FoodEntry, LedgerEvent, User


@pytest_asyncio.fixture
async def engine(tmp_path):
    from db.database import make_engine

    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'ledger.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sessions(engine):
    return async_sessionmaker(engine, class_=AsyncSession,
                              expire_on_commit=False)


@pytest_asyncio.fixture
async def a_logged_day(sessions):
    """A user with a real day: two foods and one exercise.

    ⛔⛔ THE DAY IS THE USER'S LOGGING DAY, NOT THE MACHINE'S CALENDAR DATE.
    This built its `DailyLog` with `date.today()` — the date of whatever host
    ran the suite — while `reset_today_log(s, user_id, "UTC")` targets
    `_user_today("UTC")`. The two agree only when the host's local date happens
    to equal the user's, so these four gates went RED whenever the runner sat in
    a timezone behind UTC late in the day, and green again a few hours later.
    Measured 2026-08-17 by holding the commit fixed and varying only `TZ`:

        Pacific/Honolulu  local 08-16 18:57   4 failed
        America/Chicago   local 08-16 23:57   4 failed
        America/New_York  local 08-17 00:57   0 failed
        Europe/London     local 08-17 05:57   0 failed

    ⭐ AND THE COST WAS PAID IN DIAGNOSIS, TWICE. Two handovers wrote these off
    without varying anything: first as "order-dependent, pre-existing", then as
    "not order-dependent, they fail standalone too". Both readings came from a
    single observation of a clock-dependent test. **A failure nobody can
    reproduce on demand gets explained away, and this is the ratchet that
    protects "no delete without a ledger event" — the one gate that must not be
    routinely ignorable.**

    ⚠ ONE RESOLVER, THE SAME ONE PRODUCTION USES, for the same timezone the
    reset is given. Hard-coding a date here would fix today and rot at the next
    rollover change; `LOGGING_DAY_ROLLOVER_HOUR` moves this too, by design.
    """
    from db.queries import _user_today

    async with sessions() as s:
        user = User(telegram_id="clear:1", name="Clear", timezone="UTC")
        s.add(user)
        await s.flush()
        log = DailyLog(user_id=user.id, date=_user_today("UTC"))
        s.add(log)
        await s.flush()
        s.add_all([
            FoodEntry(daily_log_id=log.id, parsed_food_name="Chicken breast",
                      quantity="174g", calories=287.0, protein=36.0,
                      carbs=2.0, fats=14.0, estimated_flag=True),
            FoodEntry(daily_log_id=log.id, parsed_food_name="White rice",
                      quantity="150g", calories=242.0, protein=5.0,
                      carbs=51.0, fats=2.0, estimated_flag=False),
            ExerciseEntry(daily_log_id=log.id, exercise_name="Bench press",
                          sets=3, reps=8),
        ])
        await s.commit()
        return user.id, log.id


async def _events(sessions, user_id, event_type="deleted"):
    async with sessions() as s:
        return (await s.execute(
            select(LedgerEvent)
            .where(LedgerEvent.user_id == user_id,
                   LedgerEvent.event_type == event_type))).scalars().all()


async def _count(sessions, model, log_id):
    async with sessions() as s:
        return (await s.execute(
            select(func.count()).select_from(model)
            .where(model.daily_log_id == log_id))).scalar_one()


# ── the production defect ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clearing_the_day_records_every_deleted_food(sessions,
                                                           a_logged_day):
    """THE DEFECT, exactly as production performed it."""
    user_id, log_id = a_logged_day
    from db.queries import reset_today_log

    async with sessions() as s:
        assert await reset_today_log(s, user_id, "UTC") is True

    assert await _count(sessions, FoodEntry, log_id) == 0, "rows survived"
    events = await _events(sessions, user_id)
    food = [e for e in events if e.domain == "food"]
    assert len(food) == 2, (
        f"{len(food)} deleted events for 2 removed rows — a delete the ledger "
        f"never saw is a delete nobody can take back")


@pytest.mark.asyncio
async def test_the_event_carries_enough_to_rebuild_the_row(sessions,
                                                           a_logged_day):
    """A `deleted` event without the row's state is an audit trail that cannot
    undo anything. `_restore_plan` rebuilds from this payload alone — including
    `daily_log_id`, or a food deleted from Tuesday returns on whatever day the
    restore happens to run."""
    user_id, log_id = a_logged_day
    from db.queries import reset_today_log

    async with sessions() as s:
        await reset_today_log(s, user_id, "UTC")

    events = [e for e in await _events(sessions, user_id) if e.domain == "food"]
    by_name = {}
    for event in events:
        payload = json.loads(event.payload_json or "{}")
        by_name[payload.get("food_name")] = payload
        assert event.entry_id, "the event does not name the row it removed"
        assert payload.get("daily_log_id") == log_id, (
            "without daily_log_id in the PAYLOAD a restore lands on the wrong "
            "day")

    assert set(by_name) == {"Chicken breast", "White rice"}
    assert by_name["Chicken breast"]["calories"] == 287.0
    assert by_name["White rice"]["carbs"] == 51.0


@pytest.mark.asyncio
async def test_exercise_deletes_are_recorded_too(sessions, a_logged_day):
    """The clear wipes both domains. Recording one and not the other would be
    the same defect, half fixed."""
    user_id, _log_id = a_logged_day
    from db.queries import reset_today_log

    async with sessions() as s:
        await reset_today_log(s, user_id, "UTC")

    events = await _events(sessions, user_id)
    assert [e for e in events if e.domain == "exercise"], \
        "exercise rows were deleted with no ledger event"


@pytest.mark.asyncio
async def test_an_empty_day_records_nothing(sessions):
    """No rows removed, no events. A clear that invents history is its own
    defect."""
    async with sessions() as s:
        user = User(telegram_id="clear:2", name="Empty", timezone="UTC")
        s.add(user)
        await s.commit()
        user_id = user.id

    from db.queries import reset_today_log

    async with sessions() as s:
        await reset_today_log(s, user_id, "UTC")
    assert not await _events(sessions, user_id)


@pytest.mark.asyncio
async def test_the_rows_and_the_events_land_together(sessions, a_logged_day):
    """ONE TRANSACTION. The edit surfaces once recorded their event in a
    SECOND commit, so a process dying in between left a changed row whose
    previous values existed nowhere. A clear must not reopen that window."""
    import db.queries as q

    user_id, log_id = a_logged_day
    real_commit = AsyncSession.commit
    commits = []

    async def counting_commit(self):
        commits.append(1)
        return await real_commit(self)

    AsyncSession.commit = counting_commit
    try:
        async with sessions() as s:
            await q.reset_today_log(s, user_id, "UTC")
    finally:
        AsyncSession.commit = real_commit

    assert len(commits) == 1, (
        f"{len(commits)} commits — rows and their history must land together, "
        f"or a crash between them loses the ability to undo")


# ── the ratchet ─────────────────────────────────────────────────────────────

#: Deleters allowed to remove food or exercise rows WITHOUT a paired event.
#:
#: `reset_all_user_data` is a full account wipe: the ledger rows go with it, so
#: an event describing a deletion would be written into a table that is being
#: emptied in the same transaction. It is the one honest exception, and it is
#: named here rather than inferred.
_MAY_DELETE_UNLEDGERED = {
    # A full account wipe. The ledger rows go with it, so an event describing
    # the deletion would be written into a table emptied in the same
    # transaction.
    "reset_all_user_data",
    # MOVES food and exercise rows to another user (account linking) and then
    # deletes the EMPTIED DailyLog. No food row is deleted, so no `deleted`
    # event is owed — named here rather than excluded by a cleverer rule,
    # because the next reader deserves the reason.
    "migrate_user_data",
}

_ROW_MODELS = {"FoodEntry", "ExerciseEntry"}


def _deleting_functions():
    """Every function that issues a delete against a food or exercise row."""
    root = pathlib.Path(__file__).resolve().parent.parent
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", ".venv/", "alembic/", "scripts/")):
            continue
        # Root-level simulation and dev harnesses are not production writers;
        # they build and tear down their own fixtures.
        if "/" not in rel and rel.startswith(("simulate_", "test_")):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:                       # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            deletes = False
            for inner in ast.walk(node):
                # `delete(FoodEntry)` — the bulk Core form that started this.
                if (isinstance(inner, ast.Call)
                        and getattr(inner.func, "id", "") == "delete"
                        and any(getattr(a, "id", "") in _ROW_MODELS
                                for a in inner.args)):
                    deletes = True
                # `db.delete(entry)` — the ORM form. The target is a variable,
                # so it cannot be resolved statically; the function is judged a
                # row-deleter only if it also NAMES a row model, which keeps
                # `delete_user_food_match` (a memory match, not a row) out.
                if (isinstance(inner, ast.Call)
                        and getattr(inner.func, "attr", "") == "delete"
                        and getattr(getattr(inner.func, "value", None),
                                    "id", "") == "db"):
                    deletes = True
            names_a_row = any(getattr(n, "id", "") in _ROW_MODELS
                              for n in ast.walk(node) if isinstance(n, ast.Name))
            if deletes and names_a_row:
                yield rel, node


def test_no_deleter_bypasses_the_ledger():
    """THE GENERAL RULE, which is why this file exists.

    Fixing `reset_today_log` alone leaves the next deleter free to repeat it,
    and nothing would catch that either — there was no test asserting the rule,
    only tests asserting particular callers. A function that removes a food or
    exercise row must record it, or be named in `_MAY_DELETE_UNLEDGERED` with a
    reason.
    """
    offenders = []
    for rel, node in _deleting_functions():
        if node.name in _MAY_DELETE_UNLEDGERED:
            continue
        records = any(
            getattr(inner.func, "id", "") == "record_ledger_event"
            or getattr(inner.func, "attr", "") == "record_ledger_event"
            for inner in ast.walk(node) if isinstance(inner, ast.Call))
        if not records:
            offenders.append(f"{rel}:{node.lineno} {node.name}")
    assert not offenders, (
        "these delete food or exercise rows without recording a ledger "
        f"event: {offenders} — a delete the ledger never saw is a delete "
        f"nobody can take back (production, 2026-08-07: 14 rows, 4 canonical)")


def test_the_ratchet_can_see_the_functions_it_judges():
    """VERIFY THE INSTRUMENT. A scan that matched nothing would pass forever
    and prove nothing — the exact failure this migration keeps finding."""
    found = {node.name for _rel, node in _deleting_functions()}
    assert "reset_today_log" in found, (
        "the ratchet cannot see the function that caused this defect")
    assert "delete_food_entry" in found, (
        "the ratchet cannot see the deleter that was already correct")
    assert len(found) >= 3, f"only {len(found)} deleters found: {sorted(found)}"
