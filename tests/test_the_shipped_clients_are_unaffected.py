"""Deploy safety: a client that sends no Idempotency-Key sees no change.

B2 put an idempotency claim on ~20 routes that did not have one. Every shipped
iOS build and the entire web dashboard send NO `Idempotency-Key` header, so
the question that decides whether this is safe to deploy is not "does dedup
work" — it is "does a KEYLESS request still behave exactly as it did".

`claim_request` returns an empty claim when there is no client key: no dedup,
no stored result, and `claim.record_id is None` so nothing is threaded into
the domain write. That is deliberate (only the client can tell a retry from a
second helping, and dropping food the user really ate is the worse failure),
but it is load-bearing for the rollout and was never asserted as such.

The failures this rules out, all of which would be silent in staging and
obvious in production:

  * a keyless double-tap starts 409ing, so the second glass of water is
    refused as a "duplicate"
  * a keyless request writes only once where it used to write twice, quietly
    dropping a real second helping
  * the response loses a field an old build decodes as required
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import FoodEntry, IdempotencyRecord, WaterEntry

TOKEN = "tok-compat"


@pytest_asyncio.fixture
async def wired(monkeypatch, engine, db, make_user):
    import api.app as A
    from api import exercise_edit, food_edit, quick_log, water
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    for mod in (A, quick_log, water, food_edit, exercise_edit):
        monkeypatch.setattr(mod, "AsyncSessionLocal", factory)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(A, "_send_dashboard_notification", _noop)
    monkeypatch.setattr(A, "resolve_send_target", _noop)

    user = await make_user(telegram_id="ios:compat")
    user.webhook_token = TOKEN
    await db.commit()
    return user


# ── no key → no claim row, no dedup ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_keyless_write_takes_no_claim_at_all(wired, db):
    """No key, no bookkeeping row. If this starts creating claims, every
    keyless retry becomes a 409 for a user who did nothing wrong."""
    from api.water import WaterLogBody, log_water

    await log_water(WaterLogBody(amount_ml=500), identity="ios:compat")

    claims = (await db.execute(select(IdempotencyRecord))).scalars().all()
    assert claims == [], (
        f"a keyless request created {len(claims)} idempotency claim(s) — "
        f"shipped clients send no key and would start colliding with "
        f"themselves")


@pytest.mark.asyncio
async def test_two_keyless_pours_are_both_written(wired, db):
    """The user drank twice. Only the CLIENT can tell that from a retry, and
    it is not telling us — so both land, exactly as before B2."""
    from api.water import WaterLogBody, log_water

    await log_water(WaterLogBody(amount_ml=500), identity="ios:compat")
    await log_water(WaterLogBody(amount_ml=500), identity="ios:compat")

    rows = (await db.execute(
        select(WaterEntry).where(WaterEntry.user_id == wired.id)
    )).scalars().all()
    assert len(rows) == 2, (
        f"two keyless pours wrote {len(rows)} row(s) — a real second glass "
        f"was silently dropped as a duplicate")


@pytest.mark.asyncio
async def test_two_keyless_dashboard_logs_are_both_written(wired, db):
    """The web dashboard sends no header and is not going to start today."""
    import api.app as A

    body = A.FoodLogBody(name="Toast", calories=150, protein=5, carbs=25,
                         fats=3)
    await A.api_log_food(body, token=TOKEN)
    await A.api_log_food(body, token=TOKEN)

    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Toast")
    )).scalars().all()
    assert len(rows) == 2, (
        f"two keyless dashboard logs wrote {len(rows)} row(s)")


@pytest.mark.asyncio
async def test_a_keyless_edit_never_409s(wired, db):
    """A keyless retry of an edit must apply, not be refused. This is the one
    that would surface as "the app says my correction failed"."""
    from api.food_edit import FoodUpdateBody, update_food
    from api.quick_log import FoodLogBody, log_food_entry

    logged = await log_food_entry(
        FoodLogBody(food_name="Soup", calories=200, protein=8, carbs=20,
                    fats=6),
        identity="ios:compat")

    for kcal in (250, 300):
        out = await update_food(logged["entry_id"],
                                FoodUpdateBody(calories=kcal),
                                identity="ios:compat")
        assert out["status"] == "ok"

    row = await db.get(FoodEntry, logged["entry_id"])
    await db.refresh(row)
    assert row.calories == 300, "the second keyless edit did not apply"


# ── the write still lands, and is still traceable ───────────────────────────


@pytest.mark.asyncio
async def test_a_keyless_write_is_still_traceable(wired, db):
    """The half B2 must NOT give up on a keyless client: no dedup, but the
    event still carries a turn id from the documented hash fallback."""
    from db.models import LedgerEvent

    from api.water import WaterLogBody, log_water

    await log_water(WaterLogBody(amount_ml=330), identity="ios:compat")

    ev = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.user_id == wired.id)
    )).scalars().first()
    assert ev is not None and ev.turn_id, (
        "traceability must not depend on the client sending a header")
    assert ev.turn_id.startswith("ios:h:")


# ── responses only GAIN fields ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_response_field_was_removed(wired, db):
    """Old builds decode a fixed set of keys. Adding `turn_id` is safe
    (Codable ignores unknown keys); REMOVING one is not."""
    import api.app as A

    from api.water import WaterLogBody, log_water

    pour = await log_water(WaterLogBody(amount_ml=500), identity="ios:compat")
    assert {"ok", "entry_id", "daily_log_id", "total_water_ml"} <= set(pour)

    dash = await A.api_log_food(
        A.FoodLogBody(name="Eggs", calories=140, protein=12, carbs=1, fats=10),
        token=TOKEN)
    assert {"status", "id"} <= set(dash)

    weight = await A.api_log_weight(A.WeightLogBody(weight=180.0), token=TOKEN)
    assert {"status", "id", "weight_lbs", "weight_kg"} <= set(weight)
