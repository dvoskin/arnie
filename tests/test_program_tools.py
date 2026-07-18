"""Program tools (set_program_day / set_program_target) — edit the PLAN from chat.

The contract under test:
  * set_program_day fuzzy-matches a rotation day and stamps a today_override
    {date, day} into program_json — scoped to the user's local TODAY.
  * An unknown day returns the day list (so the model can clarify), no write.
  * set_program_target writes sets/reps/weight onto every matching exercise
    slot; day_name narrows the match; unknown exercise → no write.
  * build_session_state prefers the override over overlap inference — but
    only on the stamped date (stale overrides are ignored).

Real in-memory DB (conftest fixtures) — these branches hit WorkoutProgram rows.
"""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from handlers import tool_executor as TE
from core.session_state import build_session_state
from db.models import WorkoutProgram

pytestmark = pytest.mark.asyncio


PROGRAM = {
    "split_name": "Upper-Focus PPL",
    "focus": "upper hypertrophy",
    "rotation": ["Push", "Pull", "Legs"],
    "days": [
        {"name": "Push", "priority": "primary", "goals": [],
         "exercises": [{"name": "Bench Press", "category": "main"},
                       {"name": "Lateral Raise", "category": "accessory"}]},
        {"name": "Pull", "priority": "primary", "goals": [],
         "exercises": [{"name": "Barbell Row", "category": "main"}]},
        {"name": "Legs", "priority": "secondary", "goals": [],
         "exercises": [{"name": "Squat", "category": "main"},
                       {"name": "Leg Press", "category": "accessory"}]},
    ],
}


async def _seed(db, make_user):
    user = await make_user(telegram_id="700", timezone="UTC")
    db.add(WorkoutProgram(user_id=user.id, raw_text="x",
                          program_json=json.dumps(PROGRAM)))
    await db.commit()
    return user


async def _prog(db, uid):
    from sqlalchemy import select
    row = (await db.execute(
        select(WorkoutProgram).where(WorkoutProgram.user_id == uid)
    )).scalar_one()
    return json.loads(row.program_json)


def _stub_log():
    return SimpleNamespace(id=1, exercise_entries=[])


async def test_set_program_day_fuzzy_and_stamped_today(db, make_user):
    user = await _seed(db, make_user)
    res = await TE._dispatch("set_program_day", {"day_name": "leg day"},
                             user, _stub_log(), db, "text")
    assert "Legs" in res
    ov = (await _prog(db, user.id))["today_override"]
    assert ov["day"] == "Legs"
    from db.queries import _user_today
    assert ov["date"] == _user_today("UTC").isoformat()


async def test_set_program_day_unknown_lists_days_no_write(db, make_user):
    user = await _seed(db, make_user)
    res = await TE._dispatch("set_program_day", {"day_name": "arms"},
                             user, _stub_log(), db, "text")
    assert "No program day matches" in res
    for day in ("Push", "Pull", "Legs"):
        assert day in res
    assert "today_override" not in await _prog(db, user.id)


async def test_set_program_target_writes_prescription(db, make_user):
    user = await _seed(db, make_user)
    res = await TE._dispatch(
        "set_program_target",
        {"exercise_name": "bench", "sets": 4, "reps": "8",
         "weight": 185, "weight_unit": "lbs"},
        user, _stub_log(), db, "text")
    assert "Bench Press" in res and "4×8" in res and "185" in res
    prog = await _prog(db, user.id)
    bench = prog["days"][0]["exercises"][0]
    assert bench["sets"] == 4 and bench["reps"] == "8"
    assert bench["weight"] == 185.0 and bench["weight_unit"] == "lbs"


async def test_set_program_target_day_scoped_and_unknown(db, make_user):
    user = await _seed(db, make_user)
    # day_name that doesn't contain the exercise → no write, clarify.
    res = await TE._dispatch(
        "set_program_target",
        {"exercise_name": "squat", "day_name": "push", "sets": 3, "reps": "5"},
        user, _stub_log(), db, "text")
    assert "isn't in the program" in res
    assert "sets" not in (await _prog(db, user.id))["days"][2]["exercises"][0]
    # correct day scope writes.
    res = await TE._dispatch(
        "set_program_target",
        {"exercise_name": "squat", "day_name": "legs", "sets": 3, "reps": "5"},
        user, _stub_log(), db, "text")
    assert "Squat" in res
    squat = (await _prog(db, user.id))["days"][2]["exercises"][0]
    assert squat["sets"] == 3 and squat["reps"] == "5"


async def test_set_program_target_requires_a_field(db, make_user):
    user = await _seed(db, make_user)
    res = await TE._dispatch("set_program_target", {"exercise_name": "bench"},
                             user, _stub_log(), db, "text")
    assert "Nothing to set" in res


async def test_no_program_on_file(db, make_user):
    user = await make_user(telegram_id="701")
    res = await TE._dispatch("set_program_day", {"day_name": "push"},
                             user, _stub_log(), db, "text")
    assert "No training program" in res


async def test_session_state_prefers_fresh_override_ignores_stale():
    now = datetime(2026, 7, 18, 10, 0)
    entry = SimpleNamespace(exercise_name="Barbell Row",
                            timestamp=now - timedelta(minutes=10))
    log = SimpleNamespace(id=1, exercise_entries=[entry])

    fresh = dict(PROGRAM, today_override={"date": "2026-07-18", "day": "Legs"})
    out = build_session_state(log, fresh, now)
    assert "Legs" in out  # user-declared day beats the Pull overlap

    stale = dict(PROGRAM, today_override={"date": "2026-07-17", "day": "Legs"})
    out = build_session_state(log, stale, now)
    assert "Pull" in out  # yesterday's override is ignored; overlap wins
