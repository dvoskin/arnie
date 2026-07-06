"""Batch prefetch helpers must be behavior-identical to their per-user twins.

The scheduler tick used to run 2 routing queries + 1 today-log query per user
(a query storm at :00/:30 as users grow). batch_send_targets / batch_today_logs
replace them with set queries; these tests pin equivalence so the two paths
can never drift."""
import pytest

from db.queries import (
    batch_send_targets, batch_today_logs, get_or_create_today_log,
    get_or_create_user, get_today_log, log_conversation, resolve_send_target,
)


@pytest.mark.asyncio
async def test_batch_send_targets_matches_per_user(db, make_user):
    # Gi-shape: canonical im:, linked tg + ios, stale pref, iOS activity.
    gi = await make_user(telegram_id="im:+15550000001", name="GiShape",
                         channel_preference="telegram")
    tg = await get_or_create_user(db, "700000001")
    ios = await get_or_create_user(db, "ios:BATCH-GI")
    tg.linked_to_user_id = gi.id
    ios.linked_to_user_id = gi.id
    await db.commit()
    await log_conversation(db, gi.id, "hey from ios", "hey",
                           source_type="ios", platform="ios")

    # Fresh user, pref only.
    fresh = await make_user(telegram_id="700000002", name="Fresh",
                            channel_preference="imessage")
    im = await get_or_create_user(db, "im:+15550000002")
    im.linked_to_user_id = fresh.id
    await db.commit()

    # Solo user, nothing at all.
    solo = await make_user(telegram_id="700000003", name="Solo")

    canonicals = [gi, fresh, solo]
    batch = await batch_send_targets(db, canonicals)
    for u in canonicals:
        assert batch[u.id] == await resolve_send_target(db, u), u.name
    assert batch[gi.id] == "ios:BATCH-GI"          # activity wins over stale pref
    assert batch[fresh.id] == "im:+15550000002"    # pref for the quiet user
    assert batch[solo.id] == "700000003"           # canonical fallback


@pytest.mark.asyncio
async def test_batch_today_logs_matches_per_user(db, make_user):
    ny = await make_user(telegram_id="800000001", name="NY",
                         timezone="America/New_York")
    utc = await make_user(telegram_id="800000002", name="Utc")   # tz default
    empty = await make_user(telegram_id="800000003", name="NoLog",
                            timezone="America/New_York")

    await get_or_create_today_log(db, ny.id, "America/New_York")
    await get_or_create_today_log(db, utc.id, "UTC")

    batch = await batch_today_logs(db, [ny, utc, empty])
    for u, tz in ((ny, "America/New_York"), (utc, "UTC"),
                  (empty, "America/New_York")):
        single = await get_today_log(db, u.id, tz)
        got = batch[u.id]
        assert (got.id if got else None) == (single.id if single else None), u.name
    # Every input user gets an entry, even the log-less one (None ≠ missing).
    assert empty.id in batch and batch[empty.id] is None


@pytest.mark.asyncio
async def test_batch_helpers_empty_input(db):
    assert await batch_send_targets(db, []) == {}
    assert await batch_today_logs(db, []) == {}
