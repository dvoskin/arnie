"""⭐ P17f — THE FROZEN STORAGE INVARIANT, AS TESTS.

    EVIDENCE ROWS ARE IMMUTABLE SNAPSHOTS.
    CANONICAL MEAL ROWS REFERENCE THEM.
    ACQUISITION MAY ADD EVIDENCE; SETTLEMENT MAY ONLY READ EVIDENCE.

OFF is mutable, so the persisted object is the exact evidence Arnie USED, never
"whatever OFF currently says about this barcode". Tomorrow's edit INSERTS a new
snapshot; yesterday's meals keep pointing at yesterday's facts.
"""
from __future__ import annotations

import pytest

from skills.nutrition.product_store import (append_product_evidence,
                                            canonical_code,
                                            latest_product_evidence,
                                            load_product_evidence)

#: The probed live envelope shape (P17d.0), verbatim fields.
RECORD = {
    "code": "70004199", "product_name": "Barebell salty peanut protein bar",
    "brands": "Barebell", "serving_size": "55.0g", "serving_quantity": 55,
    "serving_quantity_unit": "g", "rev": 1, "last_modified_t": 1724712330,
    "nutrition_data_per": "100g",
    "nutriments": {"energy-kcal_100g": 200, "proteins_100g": 20,
                   "carbohydrates_100g": 18, "fat_100g": 7.3,
                   "energy-kcal_serving": 110, "proteins_serving": 11,
                   "carbohydrates_serving": 9.9, "fat_serving": 4},
}


@pytest.mark.asyncio
async def test_the_round_trip_is_structurally_identical(db):
    """P17f.2 — persist then load must hand pricing the SAME input the producer
    built at acquisition, including the package relation."""
    from skills.nutrition.off import product_evidence_from_off

    row = await append_product_evidence(db, record=RECORD, serving_unit="bar")
    loaded = await load_product_evidence(db, row.id)
    direct = product_evidence_from_off(RECORD, serving_unit="bar")

    for field in ("identifier", "per_serving", "per100g", "serving_grams",
                  "serving_unit", "package_unit", "servings_per_package"):
        assert getattr(loaded, field) == getattr(direct, field), field


@pytest.mark.asyncio
async def test_the_loaded_snapshot_prices_a_count_of_bars(db):
    """The whole point, end to end through the store: 2 bars from the persisted
    snapshot = 2 x the label's serving, rung PRODUCT, zero fetches."""
    from core.canonical_pricing import Rung, price
    from skills.nutrition.models import COUNT_BASIS_UNIT, NormalizedQuantity

    row = await append_product_evidence(db, record=RECORD, serving_unit="bar")
    evidence = await load_product_evidence(db, row.id)
    priced = price(entity="Barebells bar",
                   consumed=NormalizedQuantity(
                       amount=2, unit="bar", count=2.0, unit_label="bar",
                       count_basis=COUNT_BASIS_UNIT),
                   product=evidence)
    assert priced.rung is Rung.PRODUCT
    assert priced.calories == pytest.approx(220.0)


@pytest.mark.asyncio
async def test_same_facts_are_one_snapshot_and_changed_facts_are_two(db):
    """⛔⛔ APPEND-ONLY, BOTH HALVES. Re-acquiring identical facts is idempotent
    — same row. A provider EDIT inserts a NEW snapshot and leaves the old row
    byte-identical, because meals already committed reference it."""
    first = await append_product_evidence(db, record=RECORD, serving_unit="bar")
    again = await append_product_evidence(db, record=RECORD, serving_unit="bar")
    assert again.id == first.id

    edited = dict(RECORD, rev=2, last_modified_t=1800000000)
    edited["nutriments"] = dict(RECORD["nutriments"],
                                **{"energy-kcal_serving": 115,
                                   "energy-kcal_100g": 209})
    second = await append_product_evidence(db, record=edited,
                                           serving_unit="bar")
    assert second.id != first.id

    old = await load_product_evidence(db, first.id)
    assert old.per_serving["calories"] == pytest.approx(110.0), (
        "the provider edit rewrote a committed snapshot — a meal that priced "
        "from rev 1 would silently reprice from rev 2")
    assert (await load_product_evidence(db, second.id)) \
        .per_serving["calories"] == pytest.approx(115.0)


@pytest.mark.asyncio
async def test_latest_is_a_query_not_an_overwrite(db):
    await append_product_evidence(db, record=RECORD, serving_unit="bar")
    edited = dict(RECORD, rev=3)
    edited["nutriments"] = dict(RECORD["nutriments"],
                                **{"energy-kcal_serving": 112,
                                   "energy-kcal_100g": 203})
    newest = await append_product_evidence(db, record=edited,
                                           serving_unit="bar")
    latest = await latest_product_evidence(db, "0070004199")
    assert latest.id == newest.id, (
        "latest must be the newest snapshot — and looked up zero-insensitively")


@pytest.mark.asyncio
async def test_an_unknown_snapshot_is_a_declined_rung_not_a_fetch(db):
    assert await load_product_evidence(db, 999999) is None


def test_canonical_code_is_zero_normalized():
    """Codified from the P17d.0 probe: OFF canonicalizes equivalent forms in
    BOTH directions, so two spellings must not become two identities."""
    assert canonical_code("0070004199") == canonical_code("70004199")
    assert canonical_code("049000042566") == canonical_code("0049000042566")
    assert canonical_code("") == ""


@pytest.mark.asyncio
async def test_assemble_loads_the_reference_and_never_fetches(db, make_user):
    """P17f.4 — `assemble()["product"]` is a LOAD of the referenced snapshot.
    No reference -> None (today's fleet). A reference -> the snapshot. And the
    OFF client is poisoned for the duration, proving no path fetches."""
    import skills.nutrition.off as off_mod
    from core.canonical_pricing_inputs import assemble

    user = await make_user()
    row = await append_product_evidence(db, record=RECORD, serving_unit="bar")

    async def _boom(*a, **kw):                            # pragma: no cover
        raise AssertionError("assemble reached the OFF network")
    real = off_mod._get_json
    off_mod._get_json = _boom
    try:
        bare = await assemble(db, user_id=user.id, entity="barebells bar",
                              preparation="", identity="Barebells bar",
                              item={"food_name": "Barebells bar"})
        assert bare["product"] is None

        bound = await assemble(db, user_id=user.id, entity="barebells bar",
                               preparation="", identity="Barebells bar",
                               item={"food_name": "Barebells bar",
                                     "product_evidence_id": row.id})
        assert bound["product"] is not None
        assert bound["product"].identifier == "off:70004199"
    finally:
        off_mod._get_json = real


@pytest.mark.asyncio
async def test_the_canonical_row_carries_the_pricing_receipt(db, make_user):
    """P17f.3 — "which facts did THIS meal use, and how" lands as first-class
    COLUMNS on the row, not payload archaeology. B-1.8 joins on these: load the
    referenced evidence, change the factor, reprice deterministically."""
    from core.canonical_writer import (CanonicalEvent, DirectOperation,
                                       MealCommitResult, ResolvedFood,
                                       ResolvedMeal, ResolutionStatus,
                                       write_canonical_meal)
    import datetime as dt

    from db.models import FoodEntry
    from sqlalchemy import select

    user = await make_user()
    snapshot = await append_product_evidence(db, record=RECORD,
                                             serving_unit="bar")
    meal = ResolvedMeal(
        operation_id="p17f_receipt_1", revision=0, user_id=user.id,
        logging_day=dt.date(2026, 8, 17), user_timezone="America/New_York",
        items=(ResolvedFood(
            event=CanonicalEvent(id="e1", domain="food",
                                 surface_text="Barebells bar",
                                 resolution_status=ResolutionStatus.RESOLVED),
            calories=220.0, protein=22.0,
            attributes={"pricing": {
                "rung": "product",
                "evidence_id": "off:70004199#rev:1@1724712330",
                "basis": "per_serving",
                "conversion_evidence_ids": ["usda:173423"],
                "source_amount": 1.0, "source_unit": "bar",
                "scaling_factor": 2.0,
                "product_evidence_id": snapshot.id,
            }}),))
    result = await write_canonical_meal(db, operation=DirectOperation(meal),
                                      resolved_meal=meal)
    assert isinstance(result, MealCommitResult)

    entry = (await db.execute(select(FoodEntry).where(
        FoodEntry.parsed_food_name == "Barebells bar"))).scalars().first()
    assert entry.pricing_rung == "product"
    assert entry.nutrition_evidence_id == "off:70004199#rev:1@1724712330"
    assert entry.source_basis == "per_serving"
    assert entry.scaling_factor == pytest.approx(2.0)
    assert entry.source_amount == pytest.approx(1.0)
    assert entry.source_unit == "bar"
    assert entry.product_evidence_id == snapshot.id
    import json as _json
    assert _json.loads(entry.conversion_evidence_ids_json) == ["usda:173423"]


@pytest.mark.asyncio
async def test_an_unreceipted_row_stays_null_not_defaulted(db, make_user):
    """⛔ A caller that recorded no pricing must not look like one that did —
    legacy and estimate rows keep NULL receipts, never empty-string ones."""
    from core.canonical_writer import (CanonicalEvent, DirectOperation,
                                       ResolvedFood, ResolvedMeal,
                                       ResolutionStatus, write_canonical_meal)
    import datetime as dt

    from db.models import FoodEntry
    from sqlalchemy import select

    user = await make_user()
    meal = ResolvedMeal(
        operation_id="p17f_receipt_2", revision=0, user_id=user.id,
        logging_day=dt.date(2026, 8, 17), user_timezone="America/New_York",
        items=(ResolvedFood(
            event=CanonicalEvent(id="e2", domain="food",
                                 surface_text="Plain chicken",
                                 resolution_status=ResolutionStatus.RESOLVED),
            calories=320.0),))
    await write_canonical_meal(db, operation=DirectOperation(meal),
                              resolved_meal=meal)
    entry = (await db.execute(select(FoodEntry).where(
        FoodEntry.parsed_food_name == "Plain chicken"))).scalars().first()
    for column in ("pricing_rung", "nutrition_evidence_id", "source_basis",
                   "scaling_factor", "product_evidence_id"):
        assert getattr(entry, column) is None, column


@pytest.mark.asyncio
async def test_a_rev_bump_with_identical_facts_is_a_new_snapshot(db):
    """⛔ THE FOUR-PART IDENTITY, VISIBLE. provider + code + provider REVISION +
    fingerprint. A metadata-only provider edit — rev moves, nutrition does not —
    is a NEW snapshot by the explicit key, not a hash coincidence: two
    independently versioned observations of the same facts are two pieces of
    evidence."""
    first = await append_product_evidence(db, record=RECORD, serving_unit="bar")
    rev_bumped = dict(RECORD, rev=2)          # same facts, new provider version
    second = await append_product_evidence(db, record=rev_bumped,
                                           serving_unit="bar")
    assert second.id != first.id
    assert first.source_fingerprint == second.source_fingerprint, (
        "identical facts must fingerprint identically — the revision is its "
        "own axis, not an input to the hash")
    assert (first.provider_revision, second.provider_revision) == ("1", "2")


@pytest.mark.asyncio
async def test_referenced_evidence_cannot_be_deleted():
    """⛔⛔ APPEND-ONLY IS A DATABASE GUARANTEE, NOT A HABIT. A meal from six
    months ago must not be able to LOSE the evidence it cites — FK RESTRICT,
    enforced by the engine, proven here with sqlite's FK pragma ON (the
    conftest engine leaves it off, as sqlite does by default)."""
    import datetime as dt

    from sqlalchemy import delete, event, select
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                        create_async_engine)

    from db.database import Base, _migrate
    from db.models import (DailyLog, FoodEntry, ProductEvidenceRecord, User)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    Session = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    try:
        async with Session() as db:
            user = User(telegram_id="fk_restrict_test", name="fk")
            db.add(user); await db.flush()
            row = await append_product_evidence(db, record=RECORD,
                                                serving_unit="bar")
            log = DailyLog(user_id=user.id, date=dt.date(2026, 8, 17))
            db.add(log); await db.flush()
            db.add(FoodEntry(daily_log_id=log.id,
                             parsed_food_name="Barebells bar",
                             calories=220.0, product_evidence_id=row.id))
            await db.commit()

            with pytest.raises(IntegrityError):
                await db.execute(delete(ProductEvidenceRecord)
                                 .where(ProductEvidenceRecord.id == row.id))
                await db.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_revisionless_provider_still_participates_in_identity(db):
    """⛔ THE NULL HOLE, PINNED *(Danny, review)*. Postgres and SQLite both
    admit unlimited duplicates through a UNIQUE constraint when a component is
    NULL — so a revision-less record must land as '' and dedupe like any other,
    not slip past identity through a NULL."""
    bare = {k: v for k, v in RECORD.items() if k != "rev"}
    first = await append_product_evidence(db, record=bare, serving_unit="bar")
    again = await append_product_evidence(db, record=bare, serving_unit="bar")
    assert first.provider_revision == "" and again.id == first.id
