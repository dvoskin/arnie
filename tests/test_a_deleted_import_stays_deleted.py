"""A health import the user deleted must not come back on the next sync.

The health-import routes are Class A but declare `natural` idempotency rather
than an idempotency claim: every sample carries a stable identity the write
upserts on (a workout's `source_ref`, a weigh-in's local day), and HealthKit
and Whoop redeliver the same samples on EVERY sync. Duplicate delivery is the
normal case here, not the exceptional one, so a claim would deduplicate what
the upsert already collapses.

That makes the tombstone the property that actually matters. Replace-on-sync
means the importer rewrites the day from whatever the device sent — so a
workout the user deleted is, from the device's point of view, still there and
gets re-inserted. `HealthImportTombstone` is what stops that, and
`dead_code_report.jsonl` recorded it as `test_call_files: 0,
test_runtime_hit: false`: the mechanism existed and nothing had ever
exercised it, on either the Apple or the Whoop path.

Deleting a workout and watching it reappear is silent, repeating, and
un-fixable by the user — they delete it again, and it comes back again.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import ExerciseEntry, HealthImportTombstone

REF = "apple:WORKOUT-ABC-123"


@pytest_asyncio.fixture
async def patched(monkeypatch, engine):
    import api.app as A
    import api.health_sync as HS
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    monkeypatch.setattr(HS, "AsyncSessionLocal", factory)
    monkeypatch.setattr(A, "AsyncSessionLocal", factory)
    return factory


def _workout(ref=REF, name="Running", minutes=30):
    """One HealthKit workout, in the shape `_process_apple_workouts` norms."""
    return {
        "uuid": ref.split(":", 1)[1],
        "type": name,
        "start": "2026-07-15T12:00:00+00:00",
        "end": "2026-07-15T12:30:00+00:00",
        "duration_minutes": minutes,
        "calories": 300,
    }


async def _sync(db, user, workouts):
    from api.app import _process_apple_workouts
    await _process_apple_workouts(db, user, workouts)


async def _entries(db, user_id):
    return (await db.execute(
        select(ExerciseEntry)
        .join(ExerciseEntry.daily_log)
        .where(ExerciseEntry.source_type == "apple_health")
    )).scalars().all()


# ── the round trip ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_resync_of_the_same_workout_does_not_duplicate_it(
    patched, db, make_user,
):
    """The natural idempotency the policy declares instead of a claim."""
    user = await make_user(telegram_id="hk:dup")

    await _sync(db, user, [_workout()])
    first = await _entries(db, user.id)
    await _sync(db, user, [_workout()])
    second = await _entries(db, user.id)

    assert len(first) == 1, f"the first sync wrote {len(first)} rows"
    assert len(second) == 1, (
        f"re-syncing the same workout wrote {len(second)} rows — the import "
        f"is not naturally idempotent, so declaring it so is wrong")


@pytest.mark.asyncio
async def test_a_deleted_workout_does_not_return_on_the_next_sync(
    patched, db, make_user,
):
    """THE property. The device still reports the workout on every sync; only
    the tombstone tells the importer the user does not want it."""
    from db.queries import delete_exercise_entry

    user = await make_user(telegram_id="hk:tombstone")

    await _sync(db, user, [_workout()])
    rows = await _entries(db, user.id)
    assert len(rows) == 1
    entry_id = rows[0].id
    assert rows[0].source_ref, (
        "the imported row carries no source_ref, so a delete has nothing to "
        "tombstone and can never be made to stick")

    assert await delete_exercise_entry(db, entry_id, user.id,
                                       ledger_source="ios_edit")
    assert await _entries(db, user.id) == []

    # The device has no idea the user deleted anything — it sends the same set.
    await _sync(db, user, [_workout()])

    assert await _entries(db, user.id) == [], (
        "the deleted workout came back on the next sync — the user deletes it "
        "again, and it returns again")


@pytest.mark.asyncio
async def test_deleting_an_imported_row_writes_a_tombstone(
    patched, db, make_user,
):
    """The mechanism, pinned directly: if the tombstone stops being written,
    every other test here still passes for a while and the protection is gone.
    """
    from db.queries import delete_exercise_entry

    user = await make_user(telegram_id="hk:tomb-row")
    await _sync(db, user, [_workout()])
    rows = await _entries(db, user.id)
    await delete_exercise_entry(db, rows[0].id, user.id,
                                ledger_source="ios_edit")

    tombs = (await db.execute(
        select(HealthImportTombstone).where(
            HealthImportTombstone.user_id == user.id)
    )).scalars().all()
    assert len(tombs) == 1, "the delete left no tombstone"
    assert tombs[0].source_ref == rows[0].source_ref


@pytest.mark.asyncio
async def test_a_tombstone_does_not_block_a_different_workout(
    patched, db, make_user,
):
    """Over-blocking is the opposite failure: a tombstone must silence ONE
    import, not the whole day."""
    from db.queries import delete_exercise_entry

    user = await make_user(telegram_id="hk:tomb-scope")
    other = _workout(ref="apple:WORKOUT-OTHER", name="Cycling")

    await _sync(db, user, [_workout(), other])
    rows = await _entries(db, user.id)
    assert len(rows) == 2

    doomed = next(r for r in rows if (r.source_ref or "").endswith("ABC-123"))
    await delete_exercise_entry(db, doomed.id, user.id,
                                ledger_source="ios_edit")

    await _sync(db, user, [_workout(), other])
    remaining = await _entries(db, user.id)
    assert len(remaining) == 1, (
        f"the tombstone silenced {2 - len(remaining)} workouts; it must "
        f"silence exactly the one that was deleted")
    assert (remaining[0].source_ref or "").endswith("OTHER")


# ── the sync is a turn ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_snapshot_sync_records_one_audit_event_on_its_turn(
    patched, db, make_user,
):
    """One event per sync, not one per imported row — a 730-sample backfill
    would otherwise bury a day's real logging under its own bookkeeping."""
    from api.health_sync import HealthSnapshotBody, post_snapshot
    from db.models import LedgerEvent

    user = await make_user(telegram_id="hk:turn")
    out = await post_snapshot(
        HealthSnapshotBody(date="2026-07-15", steps=8000),
        identity="hk:turn", client_request_id="SNAP-1")

    assert out["turn_id"] == "healthkit:SNAP-1"
    events = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.user_id == user.id,
                                  LedgerEvent.domain == "health_import")
    )).scalars().all()
    assert len(events) == 1
    assert events[0].turn_id == "healthkit:SNAP-1", (
        "the import event cannot be joined to the sync that caused it")


@pytest.mark.asyncio
async def test_two_concurrent_snapshot_syncs_do_not_duplicate_the_day(
    patched, db, make_user,
):
    """Replace-on-sync racing itself.

    The importer deletes the day's `apple_health` rows and re-inserts the
    batch. Two syncs interleaving can both delete and both insert, and the
    device retries aggressively on a flaky connection — so this is the case
    the natural-idempotency claim has to survive, not a hypothetical.
    """
    import asyncio

    from api.health_sync import HealthSnapshotBody, post_snapshot

    user = await make_user(telegram_id="hk:race")
    body = HealthSnapshotBody(date="2026-07-15", steps=8000,
                              workouts=[_workout()])

    results = await asyncio.gather(
        post_snapshot(body, identity="hk:race", client_request_id="RACE-S1"),
        post_snapshot(body, identity="hk:race", client_request_id="RACE-S2"),
        return_exceptions=True,
    )

    # THE ROW COUNT IS THE INVARIANT; a losing delivery may fail.
    #
    # The test engine is `sqlite+aiosqlite:///:memory:` behind a StaticPool, so
    # the two sessions share ONE connection and an interleaved delete/insert
    # can poison the loser's session (MissingGreenlet) rather than serialising.
    # That is an artifact of the harness, not of the route — CI runs this suite
    # against a real Postgres for exactly this reason. What must hold on both
    # is that one workout leaves one row.
    rows = await _entries(db, user.id)
    assert len(rows) == 1, (
        f"two concurrent syncs of one workout left {len(rows)} rows "
        f"(results: {results})")


@pytest.mark.asyncio
async def test_two_concurrent_weight_backfills_ingest_each_day_once(
    patched, db, make_user,
):
    """A retried sync — the same delivery twice — writes one row per day.

    This route DECLARED `natural` idempotency until this test disproved it:
    the per-day dedup SELECTs the days already covered and then inserts the
    rest, with no constraint behind it, so two concurrent deliveries both read
    an empty set and both insert. It failed here with two rows for one day.
    It now takes an idempotency claim, which closes this — the common case, a
    device retrying on a flaky connection.
    """
    import asyncio

    from api.health_sync import (WeightBackfillBody, WeightSample,
                                 backfill_weights)
    from db.models import BodyMetric

    user = await make_user(telegram_id="hk:wrace")
    samples = [WeightSample(date="2026-07-14T07:00:00+00:00", weight_kg=80.0)]

    results = await asyncio.gather(
        backfill_weights(WeightBackfillBody(weights=samples),
                         identity="hk:wrace", client_request_id="RW-SAME"),
        backfill_weights(WeightBackfillBody(weights=samples),
                         identity="hk:wrace", client_request_id="RW-SAME"),
        return_exceptions=True,
    )
    from fastapi import HTTPException
    for r in results:
        assert isinstance(r, (dict, HTTPException)), f"unhandled: {r!r}"

    rows = (await db.execute(
        select(BodyMetric).where(BodyMetric.user_id == user.id,
                                 BodyMetric.source == "apple_health")
    )).scalars().all()
    assert len(rows) == 1, (
        f"two deliveries of one backfill wrote {len(rows)} rows for one day")


@pytest.mark.xfail(reason="KNOWN, DECLARED: the per-day dedup is a "
                          "read-then-write with no uniqueness constraint, so "
                          "two syncs with DIFFERENT keys submitting "
                          "overlapping history both insert. The claim only "
                          "covers repeated delivery of one sync. Root fix is "
                          "a unique constraint on (user, source, logging day), "
                          "which needs a stored day column and a migration.",
                   strict=True)
@pytest.mark.asyncio
async def test_two_distinct_concurrent_backfills_still_race(
    patched, db, make_user,
):
    """The residual, recorded rather than hidden.

    `strict=True` so that when the constraint lands this test fails as XPASS
    and forces the policy note to be corrected — a known gap that quietly
    fixes itself and stays documented as open is its own kind of wrong.
    """
    import asyncio

    from api.health_sync import (WeightBackfillBody, WeightSample,
                                 backfill_weights)
    from db.models import BodyMetric

    user = await make_user(telegram_id="hk:wrace2")
    samples = [WeightSample(date="2026-07-14T07:00:00+00:00", weight_kg=80.0)]

    await asyncio.gather(
        backfill_weights(WeightBackfillBody(weights=samples),
                         identity="hk:wrace2", client_request_id="RW-A"),
        backfill_weights(WeightBackfillBody(weights=samples),
                         identity="hk:wrace2", client_request_id="RW-B"),
        return_exceptions=True,
    )
    rows = (await db.execute(
        select(BodyMetric).where(BodyMetric.user_id == user.id,
                                 BodyMetric.source == "apple_health")
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_a_weights_backfill_is_idempotent_and_traced(
    patched, db, make_user,
):
    from api.health_sync import WeightBackfillBody, WeightSample, backfill_weights

    await make_user(telegram_id="hk:weights")
    samples = [WeightSample(date="2026-07-14T07:00:00+00:00", weight_kg=80.0),
               WeightSample(date="2026-07-15T07:00:00+00:00", weight_kg=79.8)]

    first = await backfill_weights(WeightBackfillBody(weights=samples),
                                   identity="hk:weights",
                                   client_request_id="W-1")
    second = await backfill_weights(WeightBackfillBody(weights=samples),
                                    identity="hk:weights",
                                    client_request_id="W-2")

    assert first["ingested"] == 2
    assert second["ingested"] == 0, (
        "re-sending the same history ingested it twice — one row per local day "
        "is the natural idempotency this route declares instead of a claim")
    assert first["turn_id"] == "healthkit:W-1"
