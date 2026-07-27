"""Achievements engine (core/achievements.py) — quiet trophies, loud moments.

The contract under test:
  * Badges award ONCE (idempotent), based on real aggregate counts.
  * Several badges in one turn → one `primary` (highest rank), all in `new`.
  * `effect_taken` mutes the celebration; the badge still lands.
  * A badge earned earlier today mutes later celebrations (one/day).
  * badge_wall returns the full registry in order with earned_at markers.
"""
from datetime import date, datetime, timedelta

import pytest

from core.achievements import (
    BADGES, NEXT_UP_COUNT, ZERO_STATE, _PROVIDER_OF,
    check_achievements, badge_wall, compute_state, wall_with_backfill,
)
from db.models import Achievement, DailyLog, ExerciseEntry, FoodEntry

pytestmark = pytest.mark.asyncio


def _as_async(fn):
    """Wrap a sync spy so it can stand in for an async provider."""
    async def _inner(*a, **kw):
        return fn(*a, **kw)
    return _inner


async def _add_day(db, uid, d, calories=500, foods=0, workouts=0,
                   protein=0.0, from_photo=False):
    log = DailyLog(user_id=uid, date=d, total_calories=calories,
                   total_protein=protein)
    db.add(log)
    await db.flush()
    for i in range(foods):
        db.add(FoodEntry(daily_log_id=log.id, parsed_food_name=f"food{i}",
                         calories=300, from_photo=from_photo))
    for i in range(workouts):
        db.add(ExerciseEntry(daily_log_id=log.id, exercise_name=f"lift{i}"))
    await db.commit()
    return log


async def test_registry_integrity():
    ids = [b["id"] for b in BADGES]
    assert len(ids) == len(set(ids)), "duplicate badge ids"
    for b in BADGES:
        assert b["tier"] in ("big", "small")
        assert b["line"] and b["title"] and b["icon"] and b["rank"] > 0
        # v2: every badge is cast in a metal, filed under a family, and
        # measured by a metric/target pair.
        assert b["metal"] in ("bronze", "silver", "gold", "platinum")
        assert b["family"] in ("nutrition", "training", "consistency", "precision")
        assert isinstance(b["target"], int) and b["target"] > 0
        # A badge whose metric no provider computes is permanently unearnable —
        # the exact shape of the protein_7 bug, caught structurally this time.
        assert b["metric"] in _PROVIDER_OF, \
            f"{b['id']}: metric {b['metric']!r} has no provider"


async def test_every_metric_is_reachable_and_zeroed():
    """Every provider metric must appear in ZERO_STATE, or the fail-open floor
    would KeyError instead of degrading to no progress."""
    for metric in _PROVIDER_OF:
        assert metric in ZERO_STATE


async def test_ranks_are_unique():
    ranks = [b["rank"] for b in BADGES]
    assert len(ranks) == len(set(ranks)), "duplicate rank — celebration order is ambiguous"


async def test_metal_ladder_rises_with_rank():
    """The metal must never go DOWN as badges get harder — a 100-day streak
    outranking a 3-day one is the whole point of the ladder."""
    order = {"bronze": 0, "silver": 1, "gold": 2, "platinum": 3}
    by_family: dict[str, list] = {}
    for b in sorted(BADGES, key=lambda b: b["rank"]):
        by_family.setdefault(b["family"], []).append(b)
    for family, badges in by_family.items():
        metals = [order[b["metal"]] for b in badges]
        assert metals == sorted(metals), f"{family} metal ladder goes backwards"


async def test_first_food_awards_once(db, make_user):
    u = await make_user()
    await _add_day(db, u.id, date(2026, 7, 10), foods=1)
    ach = await check_achievements(db, u)
    assert ach is not None and "first_food" in ach["new"]

    # Second check with no new data: nothing new, no duplicate row.
    again = await check_achievements(db, u)
    assert again is None or "first_food" not in (again["new"] if again else [])
    rows = [b for b in await badge_wall(db, u) if b["id"] == "first_food"]
    assert rows[0]["earned_at"] is not None


async def test_primary_is_highest_rank_and_photo_counts(db, make_user):
    u = await make_user()
    # 3-day streak + first food + first photo all land in one check.
    for i in range(3):
        await _add_day(db, u.id, date(2026, 7, 10) + timedelta(days=i),
                       calories=1200, foods=1, from_photo=True)
    ach = await check_achievements(db, u)
    assert ach is not None
    assert {"first_food", "first_photo", "streak_3"} <= set(ach["new"])
    assert ach["primary"]["id"] == "streak_3"          # big > small
    assert ach["primary"]["tier"] == "big"


async def test_effect_taken_mutes_celebration_but_awards(db, make_user):
    u = await make_user()
    await _add_day(db, u.id, date(2026, 7, 10), foods=1)
    ach = await check_achievements(db, u, effect_taken=True)
    assert ach is not None and ach["celebrate"] is False
    assert "first_food" in ach["new"]


async def test_one_celebration_per_day(db, make_user):
    u = await make_user()
    # A badge already earned today → later badges land quietly.
    db.add(Achievement(user_id=u.id, badge_id="first_photo",
                       earned_at=datetime.utcnow()))
    await db.commit()
    await _add_day(db, u.id, date(2026, 7, 10), foods=1)
    ach = await check_achievements(db, u)
    assert ach is not None and "first_food" in ach["new"]
    assert ach["celebrate"] is False


async def test_workout_and_protein_badges(db, make_user):
    u = await make_user()
    u.protein_target = 150
    for i in range(7):
        await _add_day(db, u.id, date(2026, 7, 1) + timedelta(days=i),
                       workouts=2, protein=160)
    ach = await check_achievements(db, u)
    assert ach is not None
    assert {"first_workout", "workouts_10", "protein_7"} <= set(ach["new"])


async def test_badge_wall_full_registry_in_order(db, make_user):
    u = await make_user()
    wall = await badge_wall(db, u)
    assert [b["id"] for b in wall] == [b["id"] for b in BADGES]
    assert all(b["earned_at"] is None for b in wall)


# ── v2: progress + next_up ───────────────────────────────────────────────────


async def test_wall_progress_tracks_real_counts(db, make_user):
    u = await make_user()
    for i in range(7):
        await _add_day(db, u.id, date(2026, 7, 1) + timedelta(days=i),
                       foods=1, workouts=1)
    wall = {b["id"]: b for b in await badge_wall(db, u)}

    # 7 foods against the 50-food badge — real numerator, clamped pct.
    p = wall["foods_50"]["progress"]
    assert p == {"current": 7, "target": 50, "pct": 0.14}
    # 7 workouts against 10.
    assert wall["workouts_10"]["progress"]["current"] == 7
    # Nothing photo-logged.
    assert wall["first_photo"]["progress"]["current"] == 0


async def test_earned_badges_read_full_even_when_the_streak_breaks(db, make_user):
    """A streak badge stays earned after the chain dies; a half-drawn ring
    under an earned mark would read as though it had been taken away."""
    u = await make_user()
    db.add(Achievement(user_id=u.id, badge_id="streak_30",
                       earned_at=datetime.utcnow()))
    await db.commit()
    wall = {b["id"]: b for b in await badge_wall(db, u)}
    p = wall["streak_30"]["progress"]
    assert p["pct"] == 1.0 and p["current"] == p["target"] == 30


async def test_progress_and_earn_condition_use_the_same_rule(db, make_user):
    """Whatever hits pct 1.0 must be exactly what mints — the metric/target
    pair is the single source for both."""
    u = await make_user()
    u.protein_target = 150
    for i in range(7):
        await _add_day(db, u.id, date(2026, 7, 1) + timedelta(days=i),
                       foods=1, workouts=2, protein=160)
    state = await compute_state(db, u)
    await check_achievements(db, u)
    wall = await badge_wall(db, u, state=state)
    for b in wall:
        full = b["progress"]["pct"] >= 1.0
        assert full == (b["earned_at"] is not None), \
            f"{b['id']}: progress says {full}, wall says {b['earned_at'] is not None}"


async def test_next_up_is_ranked_by_nearness_not_registry_order(db, make_user):
    u = await make_user()
    # 240 foods deep: foods_250 is a hair away and must lead the queue, even
    # though the registry lists cheaper unearned badges before it.
    await _add_day(db, u.id, date(2026, 7, 10), foods=240)
    await check_achievements(db, u)
    wall = await badge_wall(db, u)
    queue = sorted((b for b in wall if b["next_up"] is not None),
                   key=lambda b: b["next_up"])

    assert len(queue) == NEXT_UP_COUNT
    assert queue[0]["id"] == "foods_250"
    assert all(b["earned_at"] is None for b in queue), "earned badge in next_up"
    # Positions are a dense 0..n-1 queue.
    assert [b["next_up"] for b in queue] == list(range(NEXT_UP_COUNT))


async def test_next_up_skips_a_badge_that_is_complete_but_unminted(db, make_user):
    """Wall read WITHOUT the backfill (or with a backfill that threw): a badge
    at 100% is mid-award, not a target. "50 of 50 — shoot for this" is broken
    copy, so it stays out of the queue until it mints."""
    u = await make_user()
    await _add_day(db, u.id, date(2026, 7, 10), foods=60)
    wall = await badge_wall(db, u)          # note: no check_achievements
    by_id = {b["id"]: b for b in wall}

    assert by_id["foods_50"]["progress"]["pct"] == 1.0
    assert by_id["foods_50"]["earned_at"] is None
    assert by_id["foods_50"]["next_up"] is None, "complete-but-unminted led the queue"
    assert all(b["progress"]["pct"] < 1.0
               for b in wall if b["next_up"] is not None)


async def test_next_up_falls_back_to_rank_for_a_brand_new_user(db, make_user):
    """Everything at 0% — the opening shelf should be the gentle three, not
    a thousand-food badge."""
    u = await make_user()
    wall = await badge_wall(db, u)
    queue = sorted((b for b in wall if b["next_up"] is not None),
                   key=lambda b: b["next_up"])
    assert [b["id"] for b in queue] == ["first_food", "first_photo", "first_workout"]


async def test_wall_read_skips_the_streak_walk_when_no_streak_badge_is_open(
        db, make_user, monkeypatch):
    """`_best_streak` fetches 90 days of logs — the most expensive call in the
    module. Once every streak badge is earned it's pure waste, and the wall
    read must not pay for it just because progress bars exist now."""
    import core.achievements as ach

    u = await make_user()
    for b in BADGES:
        if b["metric"] == "streak":
            db.add(Achievement(user_id=u.id, badge_id=b["id"],
                               earned_at=datetime.utcnow()))
    await db.commit()

    called = False

    async def spy(*a, **kw):
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(ach, "_best_streak", spy)
    await ach.wall_with_backfill(db, u)
    assert not called, "walked 90 days of logs with every streak badge earned"


async def test_wall_read_computes_nothing_when_everything_is_earned(
        db, make_user, monkeypatch):
    """Nothing left to chase → no counters at all. The wall is then just the
    Achievement rows, exactly as cheap as it was before progress existed."""
    import core.achievements as ach

    u = await make_user()
    for b in BADGES:
        db.add(Achievement(user_id=u.id, badge_id=b["id"],
                           earned_at=datetime.utcnow()))
    await db.commit()

    async def boom(*a, **kw):
        raise AssertionError("computed counters with every badge earned")

    monkeypatch.setattr(ach, "compute_state", boom)
    wall = await ach.wall_with_backfill(db, u)
    assert len(wall) == len(BADGES)
    assert all(b["earned_at"] is not None for b in wall)
    assert all(b["progress"]["pct"] == 1.0 for b in wall)
    assert all(b["next_up"] is None for b in wall)


async def test_wall_read_survives_a_broken_counter_pass(db, make_user, monkeypatch):
    """Fail-open: earned marks come from the rows, so a counter blow-up costs
    the progress bars, never the wall."""
    import core.achievements as ach

    u = await make_user()
    db.add(Achievement(user_id=u.id, badge_id="first_food",
                       earned_at=datetime.utcnow()))
    await db.commit()

    async def boom(*a, **kw):
        raise RuntimeError("counters exploded")

    monkeypatch.setattr(ach, "compute_state", boom)
    wall = await ach.wall_with_backfill(db, u)
    by_id = {b["id"]: b for b in wall}

    assert len(wall) == len(BADGES)
    assert by_id["first_food"]["earned_at"] is not None
    assert by_id["first_food"]["progress"]["pct"] == 1.0
    assert by_id["foods_50"]["progress"]["current"] == 0


# ── v3: rhythm metrics off the day sequence ─────────────────────────────────
#
# These are pure — DailyLog.date is already the user's LOCAL logging day, which
# is what makes weekday badges a cheap count rather than a per-entry fetch.

from types import SimpleNamespace
from core.achievements import _window_metrics

# 2026-07-04 is a Saturday; 07-06 a Monday.
_SAT = date(2026, 7, 4)
_SUN = date(2026, 7, 5)
_MON = date(2026, 7, 6)


def _row(d, cal=1500, workout=False, cardio=False):
    return SimpleNamespace(date=d, total_calories=cal,
                           workout_completed=workout, cardio_completed=cardio)


async def test_weekend_pair_needs_both_days():
    """A lone Saturday isn't a weekend — half the point of the badge is that
    Sunday is the one people skip."""
    lone = _window_metrics([_row(_SAT)], _MON + timedelta(days=30))
    assert lone["weekend_pairs"] == 0

    both = _window_metrics([_row(_SAT), _row(_SUN)], _MON + timedelta(days=30))
    assert both["weekend_pairs"] == 1


async def test_weekend_pairs_do_not_double_count():
    """Keyed off the Saturday — otherwise one weekend counts twice."""
    m = _window_metrics([_row(_SAT), _row(_SUN)], _MON + timedelta(days=30))
    assert m["weekend_pairs"] == 1


async def test_perfect_week_needs_all_seven():
    week = [_row(_MON + timedelta(days=i)) for i in range(7)]
    assert _window_metrics(week, _MON + timedelta(days=30))["perfect_weeks"] == 1
    assert _window_metrics(week[:6], _MON + timedelta(days=30))["perfect_weeks"] == 0


async def test_comeback_needs_a_real_absence():
    """Consecutive days aren't a comeback; the forgiven one-day gap isn't
    either. Only a genuine week away counts."""
    tight = [_row(_MON), _row(_MON + timedelta(days=1))]
    assert _window_metrics(tight, _MON + timedelta(days=40))["comebacks"] == 0

    short_gap = [_row(_MON), _row(_MON + timedelta(days=3))]
    assert _window_metrics(short_gap, _MON + timedelta(days=40))["comebacks"] == 0

    real = [_row(_MON), _row(_MON + timedelta(days=10))]
    assert _window_metrics(real, _MON + timedelta(days=40))["comebacks"] == 1


async def test_double_day_needs_both_kinds_of_work():
    only_lift = _window_metrics([_row(_MON, workout=True)], _MON + timedelta(days=30))
    assert only_lift["double_days"] == 0

    both = _window_metrics([_row(_MON, workout=True, cardio=True)],
                           _MON + timedelta(days=30))
    assert both["double_days"] == 1


async def test_mondays_counts_only_mondays():
    m = _window_metrics([_row(_MON), _row(_SAT), _row(_MON + timedelta(days=7))],
                        _MON + timedelta(days=30))
    assert m["mondays"] == 2


async def test_future_rows_never_count_toward_rhythm():
    """Same guard the streak engine applies — old LLM date bugs left rows
    ahead of today."""
    m = _window_metrics([_row(_MON), _row(_MON + timedelta(days=5))], _MON)
    assert m["mondays"] == 1 and m["weekend_pairs"] == 0


# ── v3: lazy providers + hidden badges ──────────────────────────────────────


async def test_providers_run_only_for_unearned_metrics(db, make_user, monkeypatch):
    """The whole point of grouping metrics by source: a user who has collected
    the rhythm badges stops paying for the 90-day window on every log turn."""
    import core.achievements as ach

    u = await make_user()
    called = []
    for name in ("counts", "days", "window", "corrections"):
        def spy(_db, _user, _n=name):
            called.append(_n)
            return {}
        monkeypatch.setitem(ach._PROVIDERS, name, _as_async(spy))

    await ach.compute_state(db, u, metrics={"foods"})
    assert called == ["counts"], "asked for one counter, ran more than one provider"

    called.clear()
    await ach.compute_state(db, u, metrics={"weekend_pairs"})
    assert called == ["window"]


async def test_hidden_badges_never_appear_as_targets(db, make_user):
    """"Next up: come back after a week away" would be telling the user to
    lapse in order to collect it."""
    u = await make_user()
    wall = await badge_wall(db, u)
    by_id = {b["id"]: b for b in wall}

    assert by_id["comeback"]["hidden"] is True
    assert all(not b["hidden"] for b in wall if b["next_up"] is not None)
    # …but it is still ON the wall, so earning it can be a reveal.
    assert "comeback" in by_id


async def test_hidden_flag_is_on_every_badge_for_the_client():
    """The client branches on it, so it must never be absent."""
    from core.achievements import _wire
    for b in BADGES:
        assert isinstance(_wire(b)["hidden"], bool)


async def test_wall_read_computes_counters_once(db, make_user, monkeypatch):
    """The endpoint hands one state to both the backfill and the wall; passing
    it in must stop badge_wall recomputing."""
    import core.achievements as ach

    calls = 0
    real = ach.compute_state

    async def counting(*a, **kw):
        nonlocal calls
        calls += 1
        return await real(*a, **kw)

    monkeypatch.setattr(ach, "compute_state", counting)
    u = await make_user()
    await _add_day(db, u.id, date(2026, 7, 10), foods=3)

    state = await ach.compute_state(db, u)
    await ach.check_achievements(db, u, effect_taken=True, state=state)
    await ach.badge_wall(db, u, state=state)
    assert calls == 1


# ── Serving-edit micro scaling (db/queries.update_food_entry) ────────────────
# Lives here for suite convenience; exercises the whole-profile rescale that
# the iOS editor relies on (it doesn't display micros — the server scales them).

import json as _json
from db.queries import update_food_entry


async def test_serving_edit_scales_full_nutrient_profile(db, make_user):
    u = await make_user()
    log = DailyLog(user_id=u.id, date=date(2026, 7, 12), total_calories=200)
    db.add(log)
    await db.flush()
    e = FoodEntry(daily_log_id=log.id, parsed_food_name="rice", calories=200,
                  protein=4, carbs=44, fats=0, fiber=1.0, sugar=0.5, sodium=10,
                  micronutrients_json=_json.dumps({"iron": 2.0, "magnesium": 40}))
    db.add(e)
    await db.commit()

    # Double the serving → macros sent doubled by the client; the server
    # scales fiber/sugar/sodium + micros by the same 2x ratio.
    updated = await update_food_entry(db, e.id, u.id, calories=400.0,
                                      protein=8.0, carbs=88.0, fats=0.0)
    assert updated is not None
    assert updated.fiber == 2.0 and updated.sugar == 1.0 and updated.sodium == 20
    micros = _json.loads(updated.micronutrients_json)
    assert micros["iron"] == 4.0 and micros["magnesium"] == 80


async def test_zero_calorie_correction_leaves_micros_alone(db, make_user):
    u = await make_user()
    log = DailyLog(user_id=u.id, date=date(2026, 7, 13), total_calories=100)
    db.add(log)
    await db.flush()
    e = FoodEntry(daily_log_id=log.id, parsed_food_name="tea", calories=100,
                  protein=0, carbs=25, fats=0, fiber=0.5,
                  micronutrients_json=_json.dumps({"potassium": 30}))
    db.add(e)
    await db.commit()

    # Hand-correcting calories to 0 is NOT a rescale — profile stays put.
    updated = await update_food_entry(db, e.id, u.id, calories=0.0)
    assert updated is not None
    assert updated.fiber == 0.5
    assert _json.loads(updated.micronutrients_json)["potassium"] == 30
