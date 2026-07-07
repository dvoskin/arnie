"""Concurrency / duplicate tolerance for daily_logs + health_snapshots.

These pin the "one row per (user, date)" invariant and the guards that keep a
concurrent check-then-insert (chat + native_data + quick_log + water all create
"today's log" on launch) from either double-writing or 500-ing a coaching turn:

  • get_or_create_log_for_date / get_or_create_today_log are IDEMPOTENT — a
    second call for the same (user, date) returns the SAME row, never a dup.
  • The uq_daily_log_user_date unique constraint is enforced (SQLite too), so a
    raw second insert raises IntegrityError; the get_or_create refetch path takes
    the existing winner instead of creating a duplicate.
  • get_today_log is duplicate-tolerant — it orders by id and returns the oldest,
    so a legacy dup never raises MultipleResultsFound (incident 2026-06-20).
  • upsert_health_snapshot upserts in place (one row) and NEVER downgrades a
    richer `source` label: a whoop row stays "whoop" when apple_health writes to
    it, contested metrics from the lower-ranked source fill gaps only, and a row
    carrying whoop-only metrics (recovery/strain) auto-promotes to "whoop".
"""
from datetime import date

import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from db.models import DailyLog, HealthSnapshot
from db.queries import (
    get_or_create_log_for_date,
    get_or_create_today_log,
    get_today_log,
    upsert_health_snapshot,
    _source_rank,
)


# ── daily_logs: get-or-create idempotency + unique constraint ─────────────────

async def test_get_or_create_log_for_date_is_idempotent(db, make_user):
    user = await make_user()
    d = date(2026, 3, 8)
    a = await get_or_create_log_for_date(db, user.id, d)
    b = await get_or_create_log_for_date(db, user.id, d)
    assert a.id == b.id
    count = await db.scalar(
        select(func.count(DailyLog.id))
        .where(DailyLog.user_id == user.id, DailyLog.date == d)
    )
    assert count == 1


async def test_get_or_create_today_log_is_idempotent(db, make_user):
    user = await make_user(timezone="UTC")
    a = await get_or_create_today_log(db, user.id, "UTC")
    b = await get_or_create_today_log(db, user.id, "UTC")
    assert a.id == b.id
    count = await db.scalar(
        select(func.count(DailyLog.id)).where(DailyLog.user_id == user.id)
    )
    assert count == 1


async def test_unique_constraint_blocks_duplicate_daily_log(db, make_user):
    """SQLite enforces uq_daily_log_user_date — a raw second insert for the same
    (user, date) raises IntegrityError. This is the constraint the get_or_create
    refetch path relies on to collapse a create race."""
    user = await make_user()
    d = date(2026, 3, 8)
    await get_or_create_log_for_date(db, user.id, d)  # first row
    db.add(DailyLog(user_id=user.id, date=d))         # attempt a duplicate
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_get_today_log_tolerates_no_duplicate_and_returns_row(db, make_user):
    """With the constraint in force a duplicate is unreachable, so the reachable
    behavior to pin is: after a create race, a second get returns the SAME row
    (constraint + refetch path), never raising."""
    user = await make_user(timezone="UTC")
    created = await get_or_create_today_log(db, user.id, "UTC")
    fetched = await get_today_log(db, user.id, "UTC")
    assert fetched is not None
    assert fetched.id == created.id
    # Ordered-by-id fetch means even a hypothetical legacy dup returns the oldest
    # without raising MultipleResultsFound; here there is exactly one row.
    count = await db.scalar(
        select(func.count(DailyLog.id)).where(DailyLog.user_id == user.id)
    )
    assert count == 1


async def test_get_today_log_returns_none_when_no_log(db, make_user):
    user = await make_user(timezone="UTC")
    assert await get_today_log(db, user.id, "UTC") is None


# ── health_snapshots: source-rank + in-place upsert ───────────────────────────

def test_source_rank_ordering():
    """Pin the rank ladder the merge logic keys on."""
    assert _source_rank("whoop") == 2
    assert _source_rank("apple_health") == 1
    assert _source_rank(None) == 0
    assert _source_rank("garbage") == 0
    assert _source_rank("whoop") > _source_rank("apple_health") > _source_rank(None)


async def test_upsert_health_snapshot_creates_then_updates_in_place(db, make_user):
    user = await make_user()
    d = date(2026, 7, 1)
    first = await upsert_health_snapshot(db, user.id, d, source="apple_health",
                                         steps=5000)
    assert first.steps == 5000
    second = await upsert_health_snapshot(db, user.id, d, source="apple_health",
                                          steps=8000, sleep_hours=7.5)
    assert second.id == first.id          # same row, updated in place
    assert second.steps == 8000
    assert second.sleep_hours == 7.5
    count = await db.scalar(
        select(func.count(HealthSnapshot.id)).where(HealthSnapshot.user_id == user.id)
    )
    assert count == 1


async def test_upsert_never_downgrades_richer_source(db, make_user):
    """An apple_health update must NOT clobber a whoop source label, and a
    contested metric (hrv) from the lower-ranked source must not overwrite the
    whoop value — but apple-only fields (steps) still merge, and gaps still fill."""
    user = await make_user()
    d = date(2026, 7, 2)
    whoop = await upsert_health_snapshot(db, user.id, d, source="whoop",
                                         recovery_score=55, hrv=90.0)
    apple = await upsert_health_snapshot(db, user.id, d, source="apple_health",
                                         steps=8000, hrv=42.0,
                                         resting_calories=200.0)
    assert apple.id == whoop.id
    assert apple.source == "whoop"          # label never ranks down
    assert apple.hrv == 90.0                # contested metric keeps the whoop value
    assert apple.steps == 8000              # apple-only field merges
    assert apple.resting_calories == 200.0  # contested but was a GAP → filled
    assert apple.recovery_score == 55       # untouched whoop metric


async def test_upsert_promotes_label_to_whoop_on_whoop_only_metric(db, make_user):
    """A later write carrying a whoop-only metric (recovery_score) promotes an
    apple_health row's label to 'whoop' even though the write's own source label
    said apple_health — recovery/strain can't come from Apple Health."""
    user = await make_user()
    d = date(2026, 7, 3)
    created = await upsert_health_snapshot(db, user.id, d, source="apple_health",
                                           steps=1000)
    assert created.source == "apple_health"
    updated = await upsert_health_snapshot(db, user.id, d, source="apple_health",
                                           recovery_score=88)
    assert updated.id == created.id
    assert updated.source == "whoop"
    assert updated.recovery_score == 88


async def test_upsert_apple_first_then_whoop_upgrades_label(db, make_user):
    user = await make_user()
    d = date(2026, 7, 4)
    a = await upsert_health_snapshot(db, user.id, d, source="apple_health", steps=5000)
    assert a.source == "apple_health"
    b = await upsert_health_snapshot(db, user.id, d, source="whoop", recovery_score=70)
    assert b.id == a.id
    assert b.source == "whoop"       # richer source label takes over
    assert b.steps == 5000           # apple's earlier field preserved
