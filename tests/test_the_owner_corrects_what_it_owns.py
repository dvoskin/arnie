"""⭐ B-1.8b — THE CANONICAL OWNER CORRECTS WHAT IT OWNS.

The first path ever to exercise `MutationAuthority.CANONICAL_OWNER` — permitted
by the ownership firewall since the salmon-overwrote-chicken incident, and
never called until now. The firewall is UNTOUCHED: legacy's
INFERRED_INTERPRETATION is still refused on the same row, in the same test.

    "actually 3 eggs" on a canonical 2-egg row
        -> bind (ledger names canonical:create) -> repair (ratio 1.5)
        -> merge (omitted size PRESERVED) -> write (one transaction:
           row + totals + `updated` event with the before-state)
        -> never legacy; refusals PROPAGATE.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from core.canonical_correction import (CORRECTION_SOURCE, CorrectionRefused,
                                       NotACanonicalRow, correct_quantity)


async def _canonical_meal(db, user, *, name="Egg", quantity="2 large eggs",
                          calories=180.0, protein=12.6, receipt=None):
    """A canonically owned row, written the way settlement writes it — through
    the writer, so its `created` event names canonical:create."""
    from core.canonical_writer import (CanonicalEvent, DirectOperation,
                                       ResolvedFood, ResolvedMeal,
                                       ResolutionStatus, write_canonical_meal)
    from db.models import FoodEntry
    from sqlalchemy import select

    attributes = {"pricing": receipt} if receipt else {}
    meal = ResolvedMeal(
        operation_id=f"b18b_{name}_{quantity}", revision=0, user_id=user.id,
        logging_day=dt.date(2026, 8, 17), user_timezone="America/New_York",
        items=(ResolvedFood(
            event=CanonicalEvent(id="e", domain="food", surface_text=name,
                                 resolution_status=ResolutionStatus.RESOLVED),
            calories=calories, protein=protein, carbs=1.6, fats=13.2,
            fiber=0.0, sugar=0.4, sodium=190.0,
            quantity_text=quantity, attributes=attributes),))
    await write_canonical_meal(db, operation=DirectOperation(meal),
                               resolved_meal=meal)
    await db.commit()
    return (await db.execute(select(FoodEntry).where(
        FoodEntry.parsed_food_name == name).order_by(FoodEntry.id.desc())
    )).scalars().first()


@pytest.mark.asyncio
async def test_the_owner_corrects_and_the_receipt_moves(db, make_user):
    """The headline: 2 large eggs -> "actually 3 eggs". Macros × 1.5, size
    PRESERVED in the stored quantity, receipt factor and mass move, totals
    recomputed, `updated` event written under canonical:correction with the
    full before-state — one transaction."""
    from db.models import DailyLog, FoodEntry, LedgerEvent
    from sqlalchemy import select

    user = await make_user()
    row = await _canonical_meal(db, user, receipt={
        "rung": "artifact", "evidence_id": "usda:173423",
        "basis": "per_100g", "scaling_factor": 0.92,
        "resolved_grams": 92.0, "source_amount": 100.0, "source_unit": "g"})
    assert row.scaling_factor == pytest.approx(0.92)

    result = await correct_quantity(db, user=user, entry_id=row.id,
                                    new_quantity_text="3 eggs")
    assert result.ratio == pytest.approx(1.5)
    assert result.method == "count_ratio"

    fresh = await db.get(FoodEntry, row.id)
    await db.refresh(fresh)
    assert fresh.calories == pytest.approx(270.0)
    assert fresh.protein == pytest.approx(18.9)
    assert fresh.sodium == pytest.approx(285.0)
    # ⛔⛔ THE FIELD-MERGE CONTRACT: omitted size is PRESERVED.
    assert fresh.quantity == "3 large eggs", fresh.quantity
    # The receipt moved WITH the correction; the evidence did not change.
    assert fresh.scaling_factor == pytest.approx(1.38)
    assert fresh.resolved_grams == pytest.approx(138.0)
    assert fresh.nutrition_evidence_id == "usda:173423"
    assert fresh.pricing_rung == "artifact"

    # Totals recomputed on the day.
    log = await db.get(DailyLog, fresh.daily_log_id)
    await db.refresh(log)
    assert log.total_calories == pytest.approx(270.0)

    # The `updated` event, under the correction lane, carrying the before.
    events = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row.id,
        LedgerEvent.event_type == "updated"))).scalars().all()
    assert len(events) == 1
    assert events[0].source == CORRECTION_SOURCE
    payload = json.loads(events[0].payload_json)
    assert payload["before"]["calories"] == pytest.approx(180.0)
    assert payload["changes"]["quantity"] == "3 large eggs"


@pytest.mark.asyncio
async def test_a_stated_size_replaces_and_a_conflict_refuses(db, make_user):
    """stated -> replace: 2 large -> "3 large eggs" keeps large. conflicting
    -> refuse: 2 large -> "3 medium eggs" is semantic repair, and it PROPAGATES
    as CorrectionRefused rather than writing anything."""
    from db.models import FoodEntry

    user = await make_user()
    row = await _canonical_meal(db, user)
    before = row.calories

    with pytest.raises(CorrectionRefused, match="semantic repair"):
        await correct_quantity(db, user=user, entry_id=row.id,
                               new_quantity_text="3 medium eggs")
    fresh = await db.get(FoodEntry, row.id)
    await db.refresh(fresh)
    assert fresh.calories == pytest.approx(before), (
        "a refused correction wrote something")
    assert fresh.quantity == "2 large eggs"


@pytest.mark.asyncio
async def test_a_legacy_row_is_not_this_slice(db, make_user):
    """A row legacy created keeps its legacy correction path, untouched —
    NotACanonicalRow is ROUTING, not a refusal."""
    from db.queries import add_food_entry, get_or_create_log_for_date

    user = await make_user()
    log = await get_or_create_log_for_date(db, user.id, dt.date(2026, 8, 17))
    legacy = await add_food_entry(db, log.id, ledger_source="legacy:ios",
                                  user_id=user.id, parsed_food_name="Toast",
                                  quantity="2 slices", calories=160.0)
    with pytest.raises(NotACanonicalRow):
        await correct_quantity(db, user=user, entry_id=legacy.id,
                               new_quantity_text="3 slices")


@pytest.mark.asyncio
async def test_the_firewall_still_refuses_legacy_on_the_same_row(db, make_user):
    """⛔⛔ THE FIREWALL IS UNTOUCHED. The very row the owner just corrected
    still refuses INFERRED_INTERPRETATION — the salmon authority — with a
    mutation_rejected event. B-1.8b exercised the reserved authority; it did
    not widen who may write."""
    from db.models import LedgerEvent
    from db.queries import (CrossOwnerMutation, MutationAuthority,
                            update_food_entry)
    from sqlalchemy import select

    user = await make_user()
    row = await _canonical_meal(db, user)
    await correct_quantity(db, user=user, entry_id=row.id,
                           new_quantity_text="3 eggs")

    with pytest.raises(CrossOwnerMutation):
        await update_food_entry(
            db, row.id, user.id, ledger_source="structured_food:v2",
            authority=MutationAuthority.INFERRED_INTERPRETATION,
            calories=999.0)
    rejected = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row.id,
        LedgerEvent.event_type == "mutation_rejected"))).scalars().all()
    assert len(rejected) == 1


@pytest.mark.asyncio
async def test_a_correction_never_touches_a_provider(db, make_user, monkeypatch):
    """The crucial proof, per the GO ruling: "2 eggs -> 3 eggs" reprices from
    the row — USDA, OFF and the artifact are poisoned throughout."""
    import api.usda as usda
    import skills.nutrition.off as off_mod

    async def _boom(*a, **kw):                            # pragma: no cover
        raise AssertionError("a correction reached a provider")
    monkeypatch.setattr(usda, "search_food", _boom)
    monkeypatch.setattr(usda, "food_portions", _boom)
    monkeypatch.setattr(off_mod, "_get_json", _boom)
    monkeypatch.setattr("skills.nutrition.pricing_artifact.evidence_for",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("a correction reached the artifact")))

    user = await make_user()
    row = await _canonical_meal(db, user, quantity="2 eggs")
    result = await correct_quantity(db, user=user, entry_id=row.id,
                                    new_quantity_text="3 eggs")
    assert result.changes["calories"] == pytest.approx(270.0)


@pytest.mark.asyncio
async def test_two_corrections_chain_from_the_rows_own_history(db, make_user):
    """2 -> 3 -> 4 eggs: the second correction reads the FIRST's written
    state (quantity "3 large eggs", moved receipt), and lands within storage
    rounding of 2 -> 4 direct."""
    from db.models import FoodEntry

    user = await make_user()
    row = await _canonical_meal(db, user, receipt={
        "rung": "artifact", "evidence_id": "usda:173423",
        "basis": "per_100g", "scaling_factor": 0.92, "resolved_grams": 92.0})
    await correct_quantity(db, user=user, entry_id=row.id,
                           new_quantity_text="3 eggs")
    await correct_quantity(db, user=user, entry_id=row.id,
                           new_quantity_text="4 eggs")
    fresh = await db.get(FoodEntry, row.id)
    await db.refresh(fresh)
    assert fresh.quantity == "4 large eggs"
    assert fresh.calories == pytest.approx(360.0, abs=0.05)
    assert fresh.scaling_factor == pytest.approx(1.84, abs=1e-5)


# ── THE ROUTE: the native stage sends a canonical correction to the owner ───

def test_the_correction_route_is_narrow():
    """Exactly ONE update_food_entry with a quantity, nothing else. Mixed
    turns, multi-row corrections, renames and day-moves are not this slice."""
    from core.turns.stages.execute_native import _correction_input

    one = [{"name": "update_food_entry",
            "input": {"entry_id": 7, "quantity": "3 eggs"}}]
    assert _correction_input(one) == {"entry_id": 7, "quantity": "3 eggs"}
    assert _correction_input([]) is None
    assert _correction_input(one + [{"name": "log_food", "input": {}}]) is None
    assert _correction_input([{"name": "log_food",
                               "input": {"entry_id": 7}}]) is None
    assert _correction_input([{"name": "update_food_entry",
                               "input": {"quantity": "3"}}]) is None


def test_the_stage_still_holds_no_except_handler():
    """A8, re-asserted for the branch this slice added: the correction path
    RAISES through `run` — a handler here is how a canonical refusal reaches
    the legacy executor."""
    import ast
    import inspect

    from core.turns.stages.execute_native import NativeExecutionStage

    tree = ast.parse(inspect.getsource(NativeExecutionStage.run).lstrip())
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
    assert not handlers, "an except handler entered NativeExecutionStage.run"


# ── EXACTLY ONCE, IN ONE TRANSACTION (B-1.8b.1) ─────────────────────────────
#
# ⛔⛔ THE FIRST CUT WIRED THE PRE-COMMIT CLAIM — claim_processed_turn commits
# the claim BEFORE the write, the lifecycle canonical settlement deliberately
# abandoned. Danny stopped it. The corrected shape reserves the claim FLUSHED
# inside the correction's own transaction and completes it immediately before
# the ONE commit. Three tests, not one: replay is the easy half; the two crash
# windows are what distinguish exactly-once from merely-deduped-when-lucky.

class _Req:
    def __init__(self, text, turn_id="ios:corr-1"):
        self.text, self.turn_id = text, turn_id
        self.metadata = {}


class _Validation:
    def __init__(self, ops):
        self.approved_operations = ops


# ⛔⛔ THE TWO CRASH-WINDOW TESTS ARE POSTGRES-ONLY, AND THAT IS A FINDING, NOT
# A DODGE. Isolated 2026-08-18: `claim_request(commit=False)` reserves under a
# SAVEPOINT; on aiosqlite the pysqlite driver COMMITS THE OUTER TRANSACTION when
# that savepoint releases (the repo's conftest already documents this for the
# crash tests), so a rollback leaves the claim durable — the exact defect these
# tests exist to catch, but manufactured by the test engine. On Postgres the
# same code rolls the claim back to zero.
#
# ⛔⛔ THE GUARANTEE, STATED PRECISELY *(Danny)* — THIS IS NOT DUAL-ENGINE
# TRANSACTIONAL PARITY:
#
#     Production Postgres PROVES atomic correction + claim behaviour.
#     SQLite is NOT AN AUTHORITATIVE INSTRUMENT for this crash boundary.
#
# Do NOT "fix" this skip by making these tests run on the sqlite fixture: they
# would go RED for a reason that is the driver's, not the code's, and the next
# person would then loosen an assertion to make them green — a false result
# either way. The skip IS the correct statement of what sqlite can measure.
_PG = __import__("os").getenv("TEST_POSTGRES_URL")
_needs_pg = pytest.mark.skipif(
    not _PG, reason="transaction-boundary proof: needs a real Postgres "
                    "(TEST_POSTGRES_URL). SQLite is NOT an authoritative "
                    "instrument here — pysqlite commits the outer transaction "
                    "on savepoint release, so it would report a durable claim "
                    "the production engine does not keep. Do not un-skip.")


@pytest.fixture
async def pg_db():
    """A real Postgres session, One-Clock pinned, schema built by the MODELS
    (this file proves lifecycle, not schema — the migrations gate does that)."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from db.database import Base, make_engine
    url = _PG.replace("+asyncpg", "+psycopg")
    engine = make_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _pg_user(pg_db):
    from db.models import User
    u = User(telegram_id="pg-corr", name="pg")
    pg_db.add(u); await pg_db.commit()
    return u


async def _reload(db, entry_id):
    """A fresh SELECT. After a rollback the identity map's objects are expired
    and `db.get()` would lazy-load synchronously (MissingGreenlet under async
    sqlite); a real query is what production readers do anyway."""
    from db.models import FoodEntry
    from sqlalchemy import select
    # ⚠ NO expire_all(): it would re-expire `user`, which the retry hands back
    # to run() — and a sync attribute read on an expired object under async
    # is MissingGreenlet. populate_existing overwrites the identity-map copy.
    return (await db.execute(
        select(FoodEntry).where(FoodEntry.id == entry_id)
        .execution_options(populate_existing=True))).scalar_one()


async def _run(stage, db, user, ops, text, turn_id="ios:corr-1"):
    req = _Req(text, turn_id)
    req.metadata = {"db": db, "user": user, "today_log": None}
    return await stage.run(req, validation=_Validation(ops))


@pytest.mark.asyncio
async def test_1_same_turn_twice_is_one_correction_one_event_one_claim(db, make_user):
    """SAME TURN TWICE -> one effective correction, one canonical:correction
    event, one COMPLETED claim. The replay raises ExactlyOnceRefusal — the
    signal the renderer already answers from — and writes nothing."""
    from core.turns.stages.execute_native import (ExactlyOnceRefusal,
                                                  NativeExecutionStage)
    from db.models import FoodEntry, IdempotencyRecord, LedgerEvent
    from sqlalchemy import select

    user = await make_user()
    row = await _canonical_meal(db, user, quantity="2 eggs")
    ops = [{"name": "update_food_entry",
            "input": {"entry_id": row.id, "quantity": "3 eggs"}}]
    stage = NativeExecutionStage()

    first = await _run(stage, db, user, ops, "actually 3 eggs")
    assert first.calls[0].committed
    with pytest.raises(ExactlyOnceRefusal):
        await _run(stage, db, user, ops, "actually 3 eggs")   # the resend

    fresh = await db.get(FoodEntry, row.id)
    await db.refresh(fresh)
    assert fresh.calories == pytest.approx(270.0), (
        f"the resend compounded: {fresh.calories} — 3 eggs became 4.5")
    events = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row.id, LedgerEvent.event_type == "updated",
        LedgerEvent.source == CORRECTION_SOURCE))).scalars().all()
    assert len(events) == 1
    claims = (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user.id,
        IdempotencyRecord.command == "correction"))).scalars().all()
    assert len(claims) == 1 and claims[0].status == "completed"
    assert claims[0].result_entry_id == row.id


@_needs_pg
@pytest.mark.asyncio
async def test_2_failure_after_reservation_before_write_rolls_both_back(pg_db, monkeypatch):
    db = pg_db
    """FAILURE AFTER CLAIM RESERVATION, BEFORE THE WRITE COMMITS -> claim and
    mutation roll back TOGETHER, and the retry succeeds. Simulated with a
    refusal (the primitive raises after the claim is reserved) — the same
    unwind a crash would produce."""
    from core.canonical_correction import CorrectionRefused
    from core.turns.stages.execute_native import NativeExecutionStage
    from db.models import FoodEntry, IdempotencyRecord
    from sqlalchemy import select

    user = await _pg_user(db)
    row = await _canonical_meal(db, user, quantity="2 large eggs")
    row_id, user_id = int(row.id), int(user.id)   # ints: survive rollbacks
    stage = NativeExecutionStage()

    bad = [{"name": "update_food_entry",
            "input": {"entry_id": row_id, "quantity": "3 medium eggs"}}]
    with pytest.raises(CorrectionRefused):
        await _run(stage, db, user, bad, "actually 3 medium eggs", "ios:t2")

    await db.rollback()          # clear the failed transaction
    await db.refresh(user)       # `user` is handed to run() again below
    claims = (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user_id))).scalars().all()
    assert claims == [], "the reservation survived a failure before the write"
    fresh = await _reload(db, row_id)
    assert fresh.calories == pytest.approx(180.0) and fresh.quantity == "2 large eggs"

    good = [{"name": "update_food_entry",
             "input": {"entry_id": row_id, "quantity": "3 large eggs"}}]
    result = await _run(stage, db, user, good, "actually 3 large eggs", "ios:t2b")
    assert result.calls[0].committed
    fresh = await _reload(db, row_id)
    assert fresh.calories == pytest.approx(270.0)


@_needs_pg
@pytest.mark.asyncio
async def test_3_failure_after_mutation_staged_before_commit_leaves_nothing_durable(
        pg_db, monkeypatch):
    db = pg_db
    """FAILURE AFTER THE ROW MUTATION IS STAGED, BEFORE COMMIT -> no durable
    changed row, no durable ledger event, no durable completed claim; the retry
    succeeds. The crash is injected INSIDE update_food_entry, after the row
    and the event are staged and the claim is completed, at the commit itself.
    """
    from core.turns.stages.execute_native import NativeExecutionStage
    from db.models import FoodEntry, IdempotencyRecord, LedgerEvent
    from sqlalchemy import select
    import db.queries as queries

    user = await _pg_user(db)
    row = await _canonical_meal(db, user, quantity="2 eggs")
    row_id, user_id = int(row.id), int(user.id)   # ints: survive rollbacks
    stage = NativeExecutionStage()
    ops = [{"name": "update_food_entry",
            "input": {"entry_id": row_id, "quantity": "3 eggs"}}]

    real_complete = queries._complete_claim_in_txn
    async def _crash_at_commit(db_, claim_id, entry_id, daily_log_id):
        await real_complete(db_, claim_id, entry_id, daily_log_id)
        # Everything is staged: row mutated, event recorded, claim completed.
        # The process dies before `db.commit()`.
        await db_.rollback()
        raise RuntimeError("simulated crash before commit")
    monkeypatch.setattr(queries, "_complete_claim_in_txn", _crash_at_commit)

    with pytest.raises(RuntimeError, match="simulated crash"):
        await _run(stage, db, user, ops, "actually 3 eggs", "ios:t3")
    monkeypatch.setattr(queries, "_complete_claim_in_txn", real_complete)
    await db.rollback()          # clear the failed transaction
    await db.refresh(user)       # `user` is handed to run() again below

    fresh = await _reload(db, row_id)
    assert fresh.calories == pytest.approx(180.0), "the row change survived the crash"
    events = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row_id, LedgerEvent.event_type == "updated"
    ))).scalars().all()
    assert events == [], "the ledger event survived the crash"
    claims = (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user_id))).scalars().all()
    assert not any(c.status == "completed" for c in claims), (
        "a completed claim survived a crash whose work did not")

    # The retry — same turn — succeeds: nothing durable blocked it.
    result = await _run(stage, db, user, ops, "actually 3 eggs", "ios:t3")
    assert result.calls[0].committed
    fresh = await _reload(db, row_id)
    assert fresh.calories == pytest.approx(270.0)
