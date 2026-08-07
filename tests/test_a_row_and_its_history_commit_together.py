"""A food row and its `created` event are one transaction, or neither happened.

`add_food_entry` commits the row (db/queries.py:726) and the caller then
commits the ledger event separately. Between those two commits the process can
die — a Render deploy restart, an OOM, a dropped connection — and what survives
is a food row with no history at all:

  * `ledger_undo.build_plan` cannot invert it, so "undo that" reaches PAST it
    to a row the user never mentioned;
  * the turn↔operation join (I16) is missing the operation entirely, so the
    turn reads as a reply that claimed a log and did not make one.

Both are silent. Nothing in the schema says the event is owed.

The window is small and the failure is real: two commits where one would do.
These tests pin that the row and its history share a transaction, in both
directions — the event is written, and a failure to write it does not leave a
half-logged day behind.
"""
import json

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import FoodEntry, LedgerEvent


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    from api import quick_log
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    monkeypatch.setattr(quick_log, "AsyncSessionLocal", factory)
    return factory


@pytest.mark.asyncio
async def test_the_row_and_its_event_are_written_in_one_transaction(
    db, make_user,
):
    """The happy path still produces exactly one row and one event — the
    refactor must not cost the history it exists to guarantee."""
    from db.queries import add_food_entry, get_or_create_today_log

    user = await make_user(telegram_id="atomic:happy")
    log = await get_or_create_today_log(db, user.id, "UTC")

    entry = await add_food_entry(
        db, daily_log_id=log.id, parsed_food_name="Lentil soup",
        raw_input="Lentil soup", calories=180, protein=12, carbs=30, fats=2,
        source_type="ios", ledger_source="quick_log:ios", user_id=user.id,
    )

    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Lentil soup")
    )).scalars().all()
    events = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.entry_id == entry.id,
                                  LedgerEvent.domain == "food")
    )).scalars().all()

    assert len(rows) == 1
    assert len(events) == 1, (
        "the row committed without its created event — history is owed and "
        "nothing in the schema says so"
    )
    assert events[0].event_type == "created"
    assert events[0].source == "quick_log:ios"


@pytest.mark.asyncio
async def test_a_failed_history_write_does_not_leave_an_orphan_row(
    db, make_user, monkeypatch,
):
    """The crash window, made deterministic.

    If the event cannot be written, the row must not be left behind on its own.
    An orphan food row is worse than a failed request: the request is visible
    and retryable, the orphan is silent and breaks undo."""
    from db import queries as Q

    user = await make_user(telegram_id="atomic:crash")
    log = await Q.get_or_create_today_log(db, user.id, "UTC")

    async def _explode(*a, **kw):
        raise RuntimeError("ledger write died mid-transaction")

    monkeypatch.setattr(Q, "record_ledger_event", _explode)

    with pytest.raises(RuntimeError):
        await Q.add_food_entry(
            db, daily_log_id=log.id, parsed_food_name="Ghost toast",
            raw_input="Ghost toast", calories=90, protein=3, carbs=17, fats=1,
            source_type="ios", ledger_source="quick_log:ios", user_id=user.id,
        )

    await db.rollback()
    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Ghost toast")
    )).scalars().all()
    assert rows == [], (
        f"{len(rows)} orphan food row(s) survived a failed history write — "
        "invisible to ledger_undo and missing from the turn join"
    )


@pytest.mark.asyncio
async def test_the_quick_log_endpoint_still_writes_exactly_one_event(
    patched_session_local, db, make_user,
):
    """The endpoint must not double-record now that the helper owns the event —
    the exact defect the 2026-07-30 master audit found on the exercise side,
    where two writers produced two `created` events 0s apart."""
    from api.quick_log import FoodLogBody, log_food_entry

    user = await make_user(telegram_id="ios:one-event")
    await log_food_entry(
        FoodLogBody(food_name="Yogurt", calories=120, protein=18, carbs=8, fats=0),
        identity="ios:one-event",
    )

    events = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.user_id == user.id)
    )).scalars().all()
    assert len(events) == 1, (
        f"{len(events)} created events for one tap — two writers again"
    )
    assert events[0].turn_id, "the event still carries its turn"


# ── the gap these tests could not see (P1, 2026-08-07) ──────────────────────
#
# Everything above was GREEN while the chat lane — the path carrying most
# production food — wrote its row and its event in TWO commits, with the
# second wrapped in a bare `except` that logged and continued. Nothing here
# could tell: every test calls `add_food_entry` DIRECTLY and passes
# `ledger_source` itself, so all of it proves the helper honours the argument
# and none of it proves a caller supplies one.
#
# That is the same shape as the fixture that made `preparation` unreachable
# and the seam test that verified a mechanism instead of its callers: the
# assertion was about a function, never about the system. These two gates ask
# the question the file's title claims to answer.

def _production_sources():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", ".venv/", "alembic/", "scripts/")) \
                or rel.startswith("simulate") or rel.startswith("test_"):
            continue
        yield rel, path


def test_every_food_writer_names_its_ledger_source():
    """A row written with no `ledger_source` gets NO event at all — the branch
    in `add_food_entry` is `if ledger_source is not None`. So an omitted
    argument is not a missing label, it is missing history, and it is silent.

    AST, not substring: the question is whether the KEYWORD is passed at the
    call site, which no amount of text matching answers.
    """
    import ast

    offenders = []
    for rel, path in _production_sources():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:                              # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", "") or getattr(node.func, "id", "")
            if name != "add_food_entry":
                continue
            if not any(kw.arg == "ledger_source" for kw in node.keywords):
                offenders.append(f"{rel}:{node.lineno}")

    assert not offenders, (
        f"{offenders} write a food row without naming a ledger_source — the "
        f"row commits and no created event is ever written, so ledger_undo "
        f"reaches past it to a row the user did not mention")


def test_no_caller_writes_a_food_created_event_of_its_own():
    """ONE WRITER FOR HISTORY, and it is the one inside the row's transaction.

    A caller appending its own `created` event is the two-commit shape by
    another name, and it is how the chat lane drifted from the canonical
    writer while every test here stayed green.
    """
    import ast

    offenders = []
    for rel, path in _production_sources():
        if rel == "db/queries.py":                       # the one writer
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:                              # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", "") or getattr(node.func, "id", "")
            if name != "record_ledger_event":
                continue
            args = [a for a in node.args if isinstance(a, ast.Constant)]
            kwargs = {kw.arg: kw.value for kw in node.keywords}
            event_type = next((a.value for a in args
                               if a.value in ("created",)), None)
            if event_type is None:
                node_et = kwargs.get("event_type")
                event_type = getattr(node_et, "value", None)
            domain = getattr(kwargs.get("domain"), "value", None)
            if event_type == "created" and domain == "food":
                offenders.append(f"{rel}:{node.lineno}")

    assert not offenders, (
        f"{offenders} append a food `created` event outside the row's "
        f"transaction — two commits where one would do")


@pytest.mark.asyncio
async def test_facts_the_row_cannot_hold_still_reach_the_event(db, make_user):
    """`ledger_extra`, and why it had to exist.

    The chat lane's payload carried `basis` and `resolution` — the resolution
    the row was written FROM, which no column records and which the correction
    path is the only reader of. Folding the event into the row's transaction
    would have dropped both, so the writer widened rather than the caller
    keeping its own event.
    """
    from sqlalchemy import select as _select

    from db.queries import add_food_entry, get_or_create_today_log

    user = await make_user(telegram_id="atomic:extra")
    log = await get_or_create_today_log(db, user.id, "UTC")

    entry = await add_food_entry(
        db, daily_log_id=log.id, parsed_food_name="Chicken breast",
        raw_input="chicken breast", calories=165, protein=31, carbs=0, fats=4,
        source_type="telegram", ledger_source="legacy:telegram", user_id=user.id,
        ledger_extra={"basis": "usda:171077", "resolution": {"per100g": 165},
                      "dropped": None},
    )

    event = (await db.execute(
        _select(LedgerEvent).where(LedgerEvent.entry_id == entry.id))
    ).scalars().one()
    payload = json.loads(event.payload_json or "{}")

    assert payload["basis"] == "usda:171077"
    assert payload["resolution"] == {"per100g": 165}
    # The row-derived base is still there — `ledger_extra` widens, never replaces.
    assert payload["food_name"] == "Chicken breast"
    assert payload["calories"] == 165
    assert "dropped" not in payload, (
        "a None extra was written as a null instead of being omitted")
    # The event comes back on the entry, which is what let the chat lane stop
    # writing its own just to learn the undo token.
    assert entry.ledger_event_id == event.id
