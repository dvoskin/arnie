"""Field-level source precedence in the daily health-snapshot merge.

One merged snapshot per (user, day) means Whoop and Apple Health write the same
row. The source LABEL was already rank-protected; the field VALUES were not —
so the day's energy bounced between Whoop's active+resting and Apple's
active-only read on every alternate sync (Danny 2026-07-03: 1,440 ↔ 230 kcal).

Contract: a lower-ranked source (Apple) may FILL a gap on a Whoop-owned row but
never REPLACE a contested value; Whoop always overwrites; Apple-only fields
(steps) merge regardless.
"""
from datetime import date

import pytest

from db.queries import upsert_health_snapshot


TODAY = date(2026, 7, 3)


@pytest.mark.asyncio
async def test_apple_cannot_clobber_whoop_energy(make_user, db):
    user = await make_user()
    # Whoop lands first with the full energy picture.
    await upsert_health_snapshot(db, user.id, TODAY, source="whoop",
                                 active_calories=440, resting_calories=1000,
                                 hrv=74, recovery_score=78)
    # Apple Health syncs later with its watch-less, active-only view + steps.
    snap = await upsert_health_snapshot(db, user.id, TODAY, source="apple_health",
                                        active_calories=230, steps=8412)
    assert snap.source == "whoop"
    assert snap.active_calories == 440      # NOT clobbered down to 230
    assert snap.resting_calories == 1000
    assert snap.steps == 8412               # Apple-only field still merges
    assert snap.recovery_score == 78


@pytest.mark.asyncio
async def test_apple_fills_gaps_on_whoop_row(make_user, db):
    user = await make_user()
    # Whoop knows recovery/strain but sent no resting HR this morning.
    await upsert_health_snapshot(db, user.id, TODAY, source="whoop",
                                 recovery_score=80, strain=9.5)
    snap = await upsert_health_snapshot(db, user.id, TODAY, source="apple_health",
                                        resting_hr=52, active_calories=230)
    assert snap.resting_hr == 52            # gap-filled
    assert snap.active_calories == 230      # was empty → Apple may fill it


@pytest.mark.asyncio
async def test_whoop_still_overwrites_apple(make_user, db):
    user = await make_user()
    # Apple lands first (e.g. fresh install before Whoop OAuth).
    await upsert_health_snapshot(db, user.id, TODAY, source="apple_health",
                                 active_calories=230, steps=5000)
    snap = await upsert_health_snapshot(db, user.id, TODAY, source="whoop",
                                        active_calories=440, resting_calories=1000,
                                        recovery_score=78)
    assert snap.source == "whoop"
    assert snap.active_calories == 440      # higher rank replaces freely
    assert snap.resting_calories == 1000
    assert snap.steps == 5000               # Apple's steps survive
