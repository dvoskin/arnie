"""Source-aware weight dedup — the WEIGHT half of the logging-discipline fix.

Regression target (Danny 2026-06-27): a single morning produced FOUR body_metrics
rows oscillating 84.73 / 85.28 kg — a manual chat weigh-in (context='morning_fasted')
plus a passive non-manual write ~9 min later, ~0.55 kg apart, which the old
<0.06 kg / 30-min fold couldn't merge. Rows stacked; the dashboard headlined the
latest (passive) value; the user's deliberate number was buried; re-stating it
("188 actually") wrote two MORE rows.

The fix: add_body_metric collapses by (user, local calendar day, source). manual
and apple_health are SEPARATE rows (never folded into each other); a repeat write
from the same source on the same day UPDATES that source's row in place; manual
always owns users.current_weight_kg, and an apple_health write may set it only
when no manual reading exists for the day.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, func

from db.models import BodyMetric, User
from db.queries import add_body_metric

pytestmark = pytest.mark.asyncio


async def _rows(db, user_id):
    res = await db.execute(
        select(BodyMetric).where(BodyMetric.user_id == user_id)
        .order_by(BodyMetric.timestamp)
    )
    return res.scalars().all()


async def _count(db, user_id):
    res = await db.execute(
        select(func.count()).select_from(BodyMetric)
        .where(BodyMetric.user_id == user_id)
    )
    return res.scalar_one()


async def test_manual_plus_apple_health_same_morning_two_rows_manual_headline(db, make_user):
    """The exact bug: manual weigh-in + passive HealthKit sync the same morning,
    ~0.55 kg apart → exactly TWO rows (one per source), NOT four. The headline
    (current_weight_kg) is the user's MANUAL number, not the passive one."""
    user = await make_user(timezone="America/New_York")

    # Manual weigh-in (the gold-standard morning reading).
    await add_body_metric(db, user.id, 84.73, source="manual",
                          context="morning_fasted")
    # Passive HealthKit reading ~0.55 kg off — escapes the old <0.06 kg fold.
    await add_body_metric(db, user.id, 85.28, source="apple_health")

    rows = await _rows(db, user.id)
    assert len(rows) == 2, "manual + apple_health must be two parallel rows, not a stack"
    sources = sorted((r.source or "manual") for r in rows)
    assert sources == ["apple_health", "manual"]

    # Headline is the user's deliberate number, never clobbered by the passive one.
    await db.refresh(user)
    assert user.current_weight_kg == 84.73


async def test_second_apple_health_same_day_folds_idempotent(db, make_user):
    """A HealthKit re-deliver (or a corrected sync) the same day UPDATES the one
    apple_health row in place — idempotent, no second passive row stacks."""
    user = await make_user(timezone="America/New_York")

    m1 = await add_body_metric(db, user.id, 85.28, source="apple_health")
    m2 = await add_body_metric(db, user.id, 85.10, source="apple_health")

    assert m1.id == m2.id, "same-source same-day write must update, not insert"
    rows = await _rows(db, user.id)
    assert len(rows) == 1
    assert rows[0].weight_kg == 85.10  # latest apple_health value retained


async def test_manual_correction_same_day_updates_no_stack(db, make_user):
    """A manual correction ('188 actually') the same day updates the manual row
    in place rather than stacking a third reading."""
    user = await make_user(timezone="America/New_York")

    m1 = await add_body_metric(db, user.id, 84.73, source="manual",
                               context="morning_fasted")
    # "188 actually" → ~85.28 kg, a deliberate correction.
    m2 = await add_body_metric(db, user.id, 85.28, source="manual")

    assert m1.id == m2.id, "manual correction must update the same row"
    rows = await _rows(db, user.id)
    assert len(rows) == 1
    assert rows[0].weight_kg == 85.28
    # Context from the first write survives when the correction doesn't supply one.
    assert rows[0].context == "morning_fasted"

    await db.refresh(user)
    assert user.current_weight_kg == 85.28


async def test_apple_health_never_overwrites_manual_headline(db, make_user):
    """Order-independent: even when the passive sync lands AFTER the manual one,
    it must not become the headline. current_weight_kg stays the manual value."""
    user = await make_user(timezone="America/New_York")

    await add_body_metric(db, user.id, 84.73, source="manual",
                          context="morning_fasted")
    await db.refresh(user)
    assert user.current_weight_kg == 84.73

    # Later passive reading — must NOT clobber the deliberate headline.
    await add_body_metric(db, user.id, 85.28, source="apple_health")
    await db.refresh(user)
    assert user.current_weight_kg == 84.73, "apple_health must not overwrite a manual headline"

    # And the manual row itself is intact (value + count).
    rows = await _rows(db, user.id)
    manual_rows = [r for r in rows if (r.source or "manual") == "manual"]
    assert len(manual_rows) == 1
    assert manual_rows[0].weight_kg == 84.73


async def test_apple_health_sets_headline_when_no_manual(db, make_user):
    """With no manual reading for the day, a passive HealthKit sync IS allowed to
    set current_weight_kg — otherwise HealthKit-only users would never get a
    headline."""
    user = await make_user(timezone="America/New_York")

    await add_body_metric(db, user.id, 85.28, source="apple_health")
    await db.refresh(user)
    assert user.current_weight_kg == 85.28


async def test_full_oscillation_scenario_stays_two_rows(db, make_user):
    """End-to-end replay of the incident: manual, then passive, then a manual
    re-state, then another passive re-deliver — all one morning. The old code
    produced four-plus rows; the fix keeps it at exactly two (one per source),
    headlined by the manual number."""
    user = await make_user(timezone="America/New_York")

    await add_body_metric(db, user.id, 84.73, source="manual", context="morning_fasted")
    await add_body_metric(db, user.id, 85.28, source="apple_health")
    await add_body_metric(db, user.id, 85.28, source="manual")        # "188 actually"
    await add_body_metric(db, user.id, 85.10, source="apple_health")  # HealthKit re-deliver

    assert await _count(db, user.id) == 2
    rows = await _rows(db, user.id)
    by_source = {(r.source or "manual"): r.weight_kg for r in rows}
    assert by_source == {"manual": 85.28, "apple_health": 85.10}

    await db.refresh(user)
    assert user.current_weight_kg == 85.28  # the user's corrected manual number


async def test_different_days_do_not_collapse(db, make_user):
    """Same source, DIFFERENT calendar days must remain separate rows — the
    collapse is per-day, it doesn't merge a weigh-in across mornings."""
    user = await make_user(timezone="America/New_York")

    # Yesterday's manual reading, backdated well clear of the rollover window.
    await add_body_metric(db, user.id, 86.00, source="manual")
    rows = await _rows(db, user.id)
    assert len(rows) == 1
    rows[0].timestamp = datetime.utcnow() - timedelta(days=1)
    await db.commit()

    # Today's manual reading — a new day, so a new row (no collapse into yesterday).
    await add_body_metric(db, user.id, 85.50, source="manual")

    assert await _count(db, user.id) == 2


async def test_weight_block_headlines_manual(db, make_user):
    """The Today-screen weight block must headline the manual reading and plot
    one point per day, even when a passive sync shares the morning."""
    from api.native_data import _weight_block

    user = await make_user(timezone="America/New_York")
    await add_body_metric(db, user.id, 84.73, source="manual", context="morning_fasted")
    await add_body_metric(db, user.id, 85.28, source="apple_health")

    weights = await _rows(db, user.id)
    block = _weight_block(weights, user)

    # One point for the shared day, headlined by the manual value (84.73 kg).
    assert len(block["recent"]) == 1
    assert block["latest"]["kg"] == 84.7
    assert block["recent"][-1]["kg"] == 84.7


async def test_backfill_past_weigh_in_separate_day_does_not_move_current(db, make_user):
    """A retroactive weigh-in (when=<past>) writes a SEPARATE row on that day and
    feeds the trend, but must NOT overwrite the user's CURRENT weight — and a
    re-backfill of the same past day updates in place (no duplicate)."""
    from db.queries import _logging_day_of

    user = await make_user(timezone="America/New_York")
    # live weigh-in today → owns current_weight_kg
    await add_body_metric(db, user.id, 84.5, source="manual", context="morning_fasted")
    await db.refresh(user)
    assert round(user.current_weight_kg, 1) == 84.5

    # backfill 3 days ago — a different logging day
    past = datetime.utcnow() - timedelta(days=3)
    await add_body_metric(db, user.id, 86.2, source="manual", when=past)
    await db.refresh(user)
    assert await _count(db, user.id) == 2                       # separate row
    assert round(user.current_weight_kg, 1) == 84.5            # current UNCHANGED
    rows = await _rows(db, user.id)
    assert len({_logging_day_of(r.timestamp, "America/New_York") for r in rows}) == 2

    # re-backfill the SAME past day → update in place, no new row
    await add_body_metric(db, user.id, 86.0, source="manual", when=past)
    assert await _count(db, user.id) == 2
