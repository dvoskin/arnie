"""A crash after the food commits must not let a retry write it again.

The idempotency claim used to be completed by a SEPARATE commit after the
domain write returned:

    claim commits (in_progress) -> food commits -> claim completes

A process dying in the middle of that leaves the meal committed and the claim
unfinished. `STALE_CLAIM_SECONDS` later, a retry takes the stale claim over and
writes the meal a second time — which is precisely the failure the claim exists
to prevent, reached by the one timing where it matters most. A duplicate is
never worse than when the user cannot see it coming.

Closing it did not need a new mechanism, only the right transaction: the claim
is completed alongside the row and its ledger event, so after any crash the
claim is either completed WITH its result, or the row was never written.

These tests inject the crash rather than describing it.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.quick_log import FoodLogBody, log_food_entry
from core import idempotency
from db.models import FoodEntry, IdempotencyRecord


@pytest_asyncio.fixture
async def engine(tmp_path):
    """OVERRIDES conftest's shared :memory: engine, deliberately.

    These tests kill a session mid-transaction and assert what survived. On
    the shared StaticPool connection that question has no honest answer: the
    driver commits the outermost savepoint on release, and the dying session's
    transaction lingers for the next session to trip over. A file database
    through make_engine gives real per-session connections, real WAL, and the
    documented driver-level transaction recipe — the semantics production has.
    """
    from db.database import make_engine
    from db.models import Base

    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'crash.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    from api import quick_log
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    monkeypatch.setattr(quick_log, "AsyncSessionLocal", factory)
    return factory


BODY = FoodLogBody(food_name="Stew", calories=400, protein=30, carbs=30, fats=15)


@pytest.mark.asyncio
async def test_the_claim_is_completed_by_the_write_itself(
    patched_session_local, db, make_user,
):
    """No second commit is involved, so there is no window to crash in."""
    user = await make_user(telegram_id="ios:crash-none")
    resp = await log_food_entry(BODY, identity="ios:crash-none",
                                client_request_id="CRASH-0")

    rec = (await db.execute(select(IdempotencyRecord))).scalars().one()
    assert rec.status == "completed", (
        "the claim was left in_progress — a retry would take it over and write "
        "the meal a second time"
    )
    assert rec.result_entry_id == resp["entry_id"]


@pytest.mark.asyncio
async def test_a_crash_mid_commit_leaves_nothing_and_the_retry_writes_once(
    patched_session_local, db, make_user, monkeypatch,
):
    """PROMOTED SEMANTICS — the invariant got STRONGER, so the test did.

    The legacy shape committed the food row first and completed the claim
    beside it, so "crash after the write" left a committed meal to protect
    from replay. On the canonical spine the claim, the rows, the immutable
    result and the claim completion share ONE transaction: a crash anywhere
    inside leaves NOTHING — no orphan food, no half-truth to reconcile — and
    the retry is a clean first write.

    The crash is injected at the last step (claim completion), the point
    where the legacy shape had already committed food.
    """
    from api import quick_log as QL

    await make_user(telegram_id="ios:crash-after")

    real_complete = QL.complete_claim

    def _die(*a, **kw):
        raise RuntimeError("process died mid-commit")
    monkeypatch.setattr(QL, "complete_claim", _die)

    try:
        await log_food_entry(BODY, identity="ios:crash-after",
                             client_request_id="CRASH-1")
    except RuntimeError:
        pass
    # The test engine is one shared sqlite connection, so the crashed
    # handler's un-rolled-back state can linger on the TEST session's open
    # transaction. In production each request owns its connection and the
    # rollback is real; here it has to be made explicit or the assertions
    # below read fixture residue instead of committed state.
    await db.rollback()

    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Stew")
    )).scalars().all()
    assert rows == [], (
        "a crash mid-commit left food behind — the single-transaction "
        "guarantee is broken and the claim now has something to lie about"
    )
    rec = (await db.execute(select(IdempotencyRecord))).scalars().one()
    assert rec.status == "in_progress", (
        "nothing committed, so the claim must still be open for the retry"
    )

    # The retry: first blocked while the claim looks live, then — once the
    # stale window opens — a clean takeover that writes EXACTLY once.
    monkeypatch.setattr(QL, "complete_claim", real_complete)
    monkeypatch.setattr(idempotency, "STALE_CLAIM_SECONDS", 0)
    retry = await log_food_entry(BODY, identity="ios:crash-after",
                                 client_request_id="CRASH-1")

    # End the fixture session's WAL read snapshot — it predates the retry's
    # commit, and a repeatable read cannot see rows committed after it began.
    await db.rollback()
    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Stew")
    )).scalars().all()
    rec = (await db.execute(select(IdempotencyRecord))).scalars().one()
    assert len(rows) == 1, "the retry wrote twice, or not at all"
    assert retry["entry_id"] == rows[0].id
    assert rec.status == "completed"
    assert rec.result_entry_id == rows[0].id


@pytest.mark.asyncio
async def test_a_stale_takeover_cannot_reach_a_completed_claim(
    patched_session_local, db, make_user, monkeypatch,
):
    """Even with the stale window forced wide open, a completed claim replays
    instead of re-executing."""
    await make_user(telegram_id="ios:crash-stale")
    monkeypatch.setattr(idempotency, "STALE_CLAIM_SECONDS", 0)

    first = await log_food_entry(BODY, identity="ios:crash-stale",
                                 client_request_id="CRASH-2")
    second = await log_food_entry(BODY, identity="ios:crash-stale",
                                  client_request_id="CRASH-2")

    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Stew")
    )).scalars().all()
    assert len(rows) == 1, (
        "a zero-second stale window let the takeover branch re-execute a "
        "COMPLETED claim — completion must be checked before staleness"
    )
    assert second.get("idempotent_replay") is True
    assert second["entry_id"] == first["entry_id"]


# ── reconciliation: a timer must never establish safety ──────────────────────


@pytest.mark.asyncio
async def test_a_stale_claim_reconciles_against_the_ledger_instead_of_rerunning(
    patched_session_local, db, make_user, monkeypatch,
):
    """THE DEPLOY-BOUNDARY CASE, manufactured explicitly.

    The legacy writer could crash between committing the food and completing
    the claim, leaving `in_progress` + a committed row. The canonical spine
    cannot PRODUCE that state any more — one transaction — but the database
    still HOLDS such claims from before the promotion deploys, and the first
    retry that arrives afterwards must reconcile against the ledger rather
    than trust a timer and write the meal again.
    """
    from db.models import DailyLog, LedgerEvent

    user = await make_user(telegram_id="ios:reconcile")
    turn_id = "ios:RECON-1"

    # The pre-promotion partial state, byte for byte: an in_progress claim, a
    # committed food row, and the `created` event that proves the write —
    # stamped with the claim's turn id, which is the join reconciliation uses.
    claim = await idempotency.claim_request(
        db, channel="ios", command="log_food", user_id=user.id,
        client_key="RECON-1", payload=BODY, turn_id=turn_id)
    assert not claim.replay

    log = DailyLog(user_id=user.id, date=__import__("datetime").date.today())
    db.add(log)
    await db.flush()
    row = FoodEntry(daily_log_id=log.id, parsed_food_name="Stew",
                    calories=400, protein=30, carbs=30, fats=15)
    db.add(row)
    await db.flush()
    db.add(LedgerEvent(user_id=user.id, domain="food", event_type="created",
                       entry_id=row.id, daily_log_id=log.id,
                       source="quick_log:ios", turn_id=turn_id))
    await db.commit()

    monkeypatch.setattr(idempotency, "STALE_CLAIM_SECONDS", 0)
    retry = await log_food_entry(BODY, identity="ios:reconcile",
                                 client_request_id="RECON-1")

    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Stew")
    )).scalars().all()
    assert len(rows) == 1, (
        "a stale in_progress claim whose work HAD committed was taken over "
        "and re-executed — the timer answered a question it cannot answer"
    )
    assert retry.get("idempotent_replay") is True
    assert retry["entry_id"] == rows[0].id


@pytest.mark.asyncio
async def test_a_stale_claim_with_nothing_committed_may_still_take_over(
    patched_session_local, db, make_user, monkeypatch,
):
    """The directive's case 2. Reconciliation must not become a deadlock: when
    the original genuinely wrote nothing, the retry has to be able to proceed —
    and produce exactly one row."""
    user = await make_user(telegram_id="ios:takeover")
    from core.idempotency import build_key
    db.add(IdempotencyRecord(
        key=build_key("ios", "log_food", user.id, "TAKEOVER"),
        user_id=user.id, command="log_food", channel="ios",
        turn_id="ios:TAKEOVER", fingerprint=idempotency.fingerprint_of(BODY),
        status="in_progress"))
    await db.commit()
    monkeypatch.setattr(idempotency, "STALE_CLAIM_SECONDS", 0)

    resp = await log_food_entry(BODY, identity="ios:takeover",
                                client_request_id="TAKEOVER")

    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Stew")
    )).scalars().all()
    assert len(rows) == 1
    assert resp["entry_id"] == rows[0].id


@pytest.mark.asyncio
async def test_an_event_without_its_row_fails_loudly(
    patched_session_local, db, make_user, monkeypatch,
):
    """The directive's case 8. A created event whose row is gone is corruption.
    Reporting a replay would hand back an entry id that no longer exists, and
    reporting success would claim a meal that is not on the board."""
    from core.idempotency import build_key, committed_result
    from db.models import LedgerEvent

    user = await make_user(telegram_id="ios:corrupt")
    rec = IdempotencyRecord(
        key=build_key("ios", "log_food", user.id, "CORRUPT"),
        user_id=user.id, command="log_food", channel="ios",
        turn_id="ios:CORRUPT", fingerprint="x", status="in_progress")
    db.add(rec)
    db.add(LedgerEvent(user_id=user.id, domain="food", event_type="created",
                       entry_id=999_999, turn_id="ios:CORRUPT"))
    await db.commit()

    with pytest.raises(idempotency.IdempotencyCorrupt):
        await committed_result(db, rec)


@pytest.mark.asyncio
async def test_weight_is_not_reconciled_by_guesswork(db, make_user):
    """Weight emits no ledger event, so there is nothing to reconcile against.
    It must return None rather than reach for a neighbouring domain's event —
    a wrong reconciliation is worse than none."""
    from core.idempotency import build_key, committed_result
    from db.models import LedgerEvent

    user = await make_user(telegram_id="ios:weight-recon")
    rec = IdempotencyRecord(
        key=build_key("ios", "log_weight", user.id, "W1"), user_id=user.id,
        command="log_weight", channel="ios", turn_id="ios:W1",
        fingerprint="x", status="in_progress")
    db.add(rec)
    db.add(LedgerEvent(user_id=user.id, domain="food", event_type="created",
                       entry_id=1, turn_id="ios:W1"))
    await db.commit()

    assert await committed_result(db, rec) is None


# ── the same guarantee on the other two write surfaces ───────────────────────


@pytest.mark.asyncio
async def test_a_crash_after_an_exercise_commit_does_not_replay_the_set(
    patched_session_local, db, make_user, monkeypatch,
):
    """Directive case 3. Exercise commits its row, its `created` event and its
    claim in one transaction, so the crash window that duplicated a meal cannot
    duplicate a set either."""
    from api import quick_log as QL
    from api.quick_log import ExerciseLogBody, log_exercise_entry
    from db.models import ExerciseEntry

    await make_user(telegram_id="ios:ex-crash")
    monkeypatch.setattr(QL, "complete_claim",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("died")))
    try:
        await log_exercise_entry(
            ExerciseLogBody(exercise_name="Deadlift", sets=3, reps="5,5,5",
                            weight=140.0),
            identity="ios:ex-crash", client_request_id="EX-CRASH")
    except RuntimeError:
        pass

    rec = (await db.execute(select(IdempotencyRecord))).scalars().one()
    rows = (await db.execute(
        select(ExerciseEntry).where(ExerciseEntry.exercise_name == "Deadlift")
    )).scalars().all()

    assert len(rows) == 1
    assert rec.status == "completed", (
        "the set committed but its claim did not — a retry would log it twice"
    )
    assert rec.result_entry_id == rows[0].id


@pytest.mark.asyncio
async def test_a_weight_retry_after_a_crash_returns_the_original(
    patched_session_local, db, make_user, monkeypatch,
):
    """Directive case 4. Weight had no durable result link at all until it
    gained a ledger event; without one there was nothing to reconcile against
    and a retry could only guess."""
    from api import quick_log as QL
    from api.quick_log import WeightLogBody, log_weight
    from db.models import BodyMetric, LedgerEvent

    await make_user(telegram_id="ios:wt-crash")
    monkeypatch.setattr(QL, "complete_claim",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("died")))
    try:
        await log_weight(WeightLogBody(weight_kg=84.2, context="morning"),
                         identity="ios:wt-crash", client_request_id="WT-CRASH")
    except RuntimeError:
        pass

    rec = (await db.execute(select(IdempotencyRecord))).scalars().one()
    metrics = (await db.execute(select(BodyMetric))).scalars().all()
    events = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.domain == "weight")
    )).scalars().all()

    assert len(metrics) == 1
    assert len(events) == 1, "weight must leave an auditable event like food does"
    assert rec.status == "completed"
    assert rec.result_entry_id == metrics[0].id


@pytest.mark.asyncio
async def test_a_weight_correction_keeps_the_reading_it_replaced(
    patched_session_local, db, make_user,
):
    """A same-day re-weigh UPSERTS one row, so the event is the only place the
    prior number survives. Without it a correction is unundoable."""
    from api.quick_log import WeightLogBody, log_weight
    from db.models import LedgerEvent
    import json

    await make_user(telegram_id="ios:wt-correct")
    await log_weight(WeightLogBody(weight_kg=84.2), identity="ios:wt-correct",
                     client_request_id="WT-1")
    await log_weight(WeightLogBody(weight_kg=83.9), identity="ios:wt-correct",
                     client_request_id="WT-2")

    updated = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.domain == "weight",
                                  LedgerEvent.event_type == "updated")
    )).scalars().all()
    assert len(updated) == 1
    payload = json.loads(updated[0].payload_json or "{}")
    assert payload.get("previous_weight_kg") == 84.2, (
        "the replaced reading is gone — a correction cannot be undone"
    )
    assert payload.get("weight_kg") == 83.9


# ── the edges the directive named ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_reused_key_with_a_different_payload_still_conflicts_after_a_crash(
    patched_session_local, db, make_user, monkeypatch,
):
    """Directive case 6. Reconciliation must never paper over a client bug:
    a key replayed with DIFFERENT food is a conflict, not a replay, even when
    the original claim is unfinished and its work committed."""
    from fastapi import HTTPException

    from api import quick_log as QL

    await make_user(telegram_id="ios:conflict-crash")
    monkeypatch.setattr(QL, "complete_claim",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("died")))
    try:
        await log_food_entry(BODY, identity="ios:conflict-crash",
                             client_request_id="SAME")
    except RuntimeError:
        pass

    rec = (await db.execute(select(IdempotencyRecord))).scalars().one()
    rec.status, rec.result_entry_id = "in_progress", None
    await db.commit()
    monkeypatch.setattr(idempotency, "STALE_CLAIM_SECONDS", 0)

    with pytest.raises(HTTPException) as excinfo:
        await log_food_entry(
            FoodLogBody(food_name="Pizza", calories=900, protein=35,
                        carbs=90, fats=40),
            identity="ios:conflict-crash", client_request_id="SAME")

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["error"] == "idempotency_conflict", (
        "a different payload reconciled to the first request's result instead "
        "of failing — the client bug is now invisible AND the answer is wrong"
    )


@pytest.mark.asyncio
async def test_a_completed_claim_missing_its_result_is_rebuilt_from_the_ledger(
    patched_session_local, db, make_user,
):
    """Directive case 7. `entry_id: None` on a replay reads as success while
    telling the client nothing. The ledger still knows which row was written."""
    await make_user(telegram_id="ios:no-result")
    first = await log_food_entry(BODY, identity="ios:no-result",
                                 client_request_id="NORESULT")

    rec = (await db.execute(select(IdempotencyRecord))).scalars().one()
    rec.result_entry_id = None            # completed, but the reference is gone
    rec.result_daily_log_id = None
    await db.commit()

    replay = await log_food_entry(BODY, identity="ios:no-result",
                                  client_request_id="NORESULT")

    assert replay["entry_id"] == first["entry_id"], (
        "the replay could not name the row it was replaying"
    )
    # The heal committed in the HANDLER's session. This session still holds the
    # row it loaded a moment ago, so without expiring it the assertion reads a
    # stale object and reports a failure that did not happen.
    db.expire_all()
    healed = (await db.execute(select(IdempotencyRecord))).scalars().one()
    assert healed.result_entry_id == first["entry_id"], "the claim was not healed"
