"""Group leaderboard — on-read momentum, consistency over intensity."""
from datetime import date, timedelta

import pytest

from db.models import DailyLog, Group, GroupMember

pytestmark = pytest.mark.asyncio


async def _seed_group(db, make_user):
    g = Group(name="Beta Insiders", description="x")
    db.add(g)
    await db.flush()
    users = []
    for i, (tid, name) in enumerate((("801", "Danny"), ("802", "Anna"),
                                     ("803", "Ghost"))):
        u = await make_user(telegram_id=tid, name=name)
        db.add(GroupMember(group_id=g.id, user_id=u.id))
        users.append(u)
    await db.commit()
    return g, users


async def test_momentum_ranks_consistency_over_intensity(db, make_user):
    g, (danny, anna, ghost) = await _seed_group(db, make_user)
    today = date.today()
    # Danny: 7 logged days, 2 workouts. Anna: 2 logged days, 2 workouts.
    for i in range(7):
        db.add(DailyLog(user_id=danny.id, date=today - timedelta(days=i),
                        total_calories=1800, workout_completed=(i < 2)))
    for i in range(2):
        db.add(DailyLog(user_id=anna.id, date=today - timedelta(days=i),
                        total_calories=1500, workout_completed=True))
    await db.commit()

    from api.groups import compute_leaderboard
    out = await compute_leaderboard(db, g.id, danny.id)

    ranks = [(e["name"], e["rank"], e["momentum"]) for e in out["entries"]]
    assert ranks[0][0] == "Danny", ranks       # 7d consistency wins
    assert out["entries"][0]["you"] is True
    # zero-momentum members never show — not even the requester
    assert all(e["momentum"] > 0 for e in out["entries"])
    assert "Ghost" not in [e["name"] for e in out["entries"]]
    assert out["entries"][0]["streak"] >= 7 - 1


async def test_windows_30d_and_all_time(db, make_user):
    g, (danny, anna, _) = await _seed_group(db, make_user)
    today = date.today()
    # Danny: 3 recent days. Anna: 20 days, all older than a week.
    for i in range(3):
        db.add(DailyLog(user_id=danny.id, date=today - timedelta(days=i),
                        total_calories=1800))
    for i in range(8, 28):
        db.add(DailyLog(user_id=anna.id, date=today - timedelta(days=i),
                        total_calories=1500, workout_completed=True))
    await db.commit()

    from api.groups import compute_leaderboard
    week = await compute_leaderboard(db, g.id, danny.id, window_days=7)
    assert week["window"] == "7d"
    assert week["entries"][0]["name"] == "Danny"      # Anna invisible this week

    month = await compute_leaderboard(db, g.id, danny.id, window_days=30)
    assert month["window"] == "30d"
    assert month["entries"][0]["name"] == "Anna"      # her 20 days dominate

    alltime = await compute_leaderboard(db, g.id, danny.id, window_days=None)
    assert alltime["window"] == "all"
    assert alltime["entries"][0]["name"] == "Anna"
    assert alltime["entries"][0]["log_days"] == 20


async def test_ensure_default_groups_auto_enrolls_canonical(db, make_user):
    """Telegram-era actives were invisible on the board — every canonical
    onboarded user belongs to Beta Insiders by default; linked identities and
    un-onboarded users don't."""
    from api.groups import ensure_default_groups
    from db.models import GroupMember, Group
    from sqlalchemy import select

    u1 = await make_user(telegram_id="901", name="Denys")
    u2 = await make_user(telegram_id="902", name="Ghosty", onboarded=False)
    u3 = await make_user(telegram_id="903", name="LinkedTwin",
                         linked_to_user_id=1)
    await ensure_default_groups(db)

    insiders = (await db.execute(
        select(Group).where(Group.name == "Beta Insiders"))).scalar_one()
    members = set((await db.execute(
        select(GroupMember.user_id)
        .where(GroupMember.group_id == insiders.id))).scalars().all())
    assert u1.id in members
    assert u2.id not in members
    assert u3.id not in members
