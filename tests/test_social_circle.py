"""
Social circle — friend graph + leaderboard.

Covers the opt-in code mint, the add-by-code state machine (ok/already/self/
not_found), bidirectional edges, canonical resolution through a linked identity,
and the build_circle ranking/stats/streak math + empty state.
"""
from datetime import timedelta

import pytest

from db.models import DailyLog
from db.queries import (
    add_friend_by_code,
    get_friends,
    get_or_create_friend_code,
    remove_friend,
)
from core.social import build_circle, render_circle_text, _user_today


async def _add_day(db, user, days_ago=0, calories=0, protein=0, workout=False):
    today = _user_today(user.timezone or "UTC")
    db.add(DailyLog(
        user_id=user.id,
        date=today - timedelta(days=days_ago),
        total_calories=calories,
        total_protein=protein,
        workout_completed=workout,
    ))
    await db.commit()


# ── friend code (opt-in) ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_friend_code_is_stable_and_opt_in(db, make_user):
    u = await make_user(telegram_id="1", name="Ann")
    assert u.friend_code is None  # no code until they ask — invisible/unaddable

    code1 = await get_or_create_friend_code(db, u)
    assert code1 and len(code1) == 6
    code2 = await get_or_create_friend_code(db, u)
    assert code1 == code2  # stable across calls — it's a permanent handle


# ── add by code ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_friend_is_bidirectional(db, make_user):
    a = await make_user(telegram_id="1", name="Ann")
    b = await make_user(telegram_id="2", name="Bob")
    b_code = await get_or_create_friend_code(db, b)

    friend, status = await add_friend_by_code(db, a, b_code)
    assert status == "ok" and friend.id == b.id

    # Both directions exist — each sees the other.
    a_friends = await get_friends(db, a)
    b_friends = await get_friends(db, b)
    assert [f.id for f in a_friends] == [b.id]
    assert [f.id for f in b_friends] == [a.id]


@pytest.mark.asyncio
async def test_add_friend_idempotent_and_guards(db, make_user):
    a = await make_user(telegram_id="1", name="Ann")
    b = await make_user(telegram_id="2", name="Bob")
    b_code = await get_or_create_friend_code(db, b)
    a_code = await get_or_create_friend_code(db, a)

    assert (await add_friend_by_code(db, a, b_code))[1] == "ok"
    assert (await add_friend_by_code(db, a, b_code))[1] == "already"   # no dup edge
    assert (await add_friend_by_code(db, a, a_code))[1] == "self"      # own code
    assert (await add_friend_by_code(db, a, "ZZZZZZ"))[1] == "not_found"

    # Still exactly one friend after all that.
    assert len(await get_friends(db, a)) == 1


@pytest.mark.asyncio
async def test_add_friend_resolves_canonical_identity(db, make_user):
    """Adding via someone's LINKED secondary identity lands the edge on their
    canonical brain — not the throwaway channel row."""
    canon = await make_user(telegram_id="2", name="Bob")
    secondary = await make_user(telegram_id="im:bob", name=None, onboarded=False,
                                linked_to_user_id=canon.id)
    # The secondary row generated/holds a code, but it points at canon.
    secondary.friend_code = "SECOND"
    await db.commit()

    a = await make_user(telegram_id="1", name="Ann")
    friend, status = await add_friend_by_code(db, a, "SECOND")
    assert status == "ok"
    assert friend.id == canon.id  # followed the link to the canonical user


@pytest.mark.asyncio
async def test_remove_friend_drops_both_edges(db, make_user):
    a = await make_user(telegram_id="1", name="Ann")
    b = await make_user(telegram_id="2", name="Bob")
    await add_friend_by_code(db, a, await get_or_create_friend_code(db, b))

    assert await remove_friend(db, a, b.id) is True
    assert await get_friends(db, a) == []
    assert await get_friends(db, b) == []  # symmetric removal


# ── leaderboard ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_circle_empty_state(db, make_user):
    a = await make_user(telegram_id="1", name="Ann")
    circle = await build_circle(db, a)
    assert circle["friend_count"] == 0
    assert len(circle["rows"]) == 1 and circle["rows"][0]["is_me"]
    assert "empty gym" in render_circle_text(circle)


@pytest.mark.asyncio
async def test_circle_ranks_by_effort_and_shows_raw_stats(db, make_user):
    me = await make_user(telegram_id="1", name="Ann Smith")
    rival = await make_user(telegram_id="2", name="Bob Jones")
    await add_friend_by_code(db, me, await get_or_create_friend_code(db, rival))

    # Me: 2 workouts this week, ate 1800 today.
    await _add_day(db, me, days_ago=0, calories=1800, protein=150, workout=True)
    await _add_day(db, me, days_ago=1, calories=2000, workout=True)
    # Rival: 4 workouts this week — more effort, should rank #1.
    for d in range(4):
        await _add_day(db, rival, days_ago=d, calories=2500, protein=200, workout=True)

    circle = await build_circle(db, me)
    rows = {r["name"]: r for r in circle["rows"]}
    assert circle["rows"][0]["name"] == "Bob"          # ranked first on workouts
    assert rows["Bob"]["rank"] == 1 and rows["Ann"]["rank"] == 2
    assert rows["Ann"]["is_me"] is True
    # Raw numbers ARE exposed (the product decision): today's calories visible.
    assert rows["Ann"]["calories_today"] == 1800
    assert rows["Bob"]["calories_today"] == 2500
    assert rows["Bob"]["workouts_week"] == 4


@pytest.mark.asyncio
async def test_streak_counts_consecutive_logged_days(db, make_user):
    u = await make_user(telegram_id="1", name="Ann")
    # Logged today, yesterday, 2 days ago — then a gap at day 3.
    await _add_day(db, u, days_ago=0, calories=1500)
    await _add_day(db, u, days_ago=1, calories=1600)
    await _add_day(db, u, days_ago=2, workout=True)
    await _add_day(db, u, days_ago=4, calories=1000)  # broken by the day-3 gap

    circle = await build_circle(db, u)
    assert circle["rows"][0]["streak"] == 3


@pytest.mark.asyncio
async def test_empty_autolog_does_not_fake_a_streak(db, make_user):
    u = await make_user(telegram_id="1", name="Ann")
    await _add_day(db, u, days_ago=0, calories=0)  # zero-cal placeholder row
    circle = await build_circle(db, u)
    assert circle["rows"][0]["streak"] == 0
    assert circle["rows"][0]["logged_today"] is False
