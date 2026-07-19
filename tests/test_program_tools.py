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


async def test_add_exercise_to_plural_day_phrase(db, make_user):
    """Danny's live miss: 'add dips to my chest days' — plural phrase,
    exercise appended to every matching day, targets optional."""
    user = await _seed(db, make_user)
    res = await TE._dispatch(
        "add_program_exercise",
        {"exercise_name": "Dips", "day_name": "push days",
         "sets": 3, "reps": "10"},
        user, _stub_log(), db, "text")
    assert "Added Dips" in res and "Push" in res
    prog = await _prog(db, user.id)
    dips = [e for e in prog["days"][0]["exercises"] if e["name"] == "Dips"]
    assert len(dips) == 1
    assert dips[0]["category"] == "accessory"
    assert dips[0]["sets"] == 3 and dips[0]["reps"] == "10"
    # re-adding is a no-op with an honest reply, not a duplicate
    res = await TE._dispatch(
        "add_program_exercise",
        {"exercise_name": "dips", "day_name": "push"},
        user, _stub_log(), db, "text")
    assert "already on" in res
    prog = await _prog(db, user.id)
    assert len([e for e in prog["days"][0]["exercises"]
                if e["name"].lower() == "dips"]) == 1


async def test_add_exercise_unknown_day_no_write(db, make_user):
    user = await _seed(db, make_user)
    res = await TE._dispatch(
        "add_program_exercise",
        {"exercise_name": "Dips", "day_name": "chest day"},
        user, _stub_log(), db, "text")
    assert "No program day matches" in res
    prog = await _prog(db, user.id)
    assert all(e["name"] != "Dips"
               for d in prog["days"] for e in d["exercises"])


async def test_remove_exercise_scoped_and_everywhere(db, make_user):
    user = await _seed(db, make_user)
    res = await TE._dispatch(
        "remove_program_exercise",
        {"exercise_name": "leg press", "day_name": "legs"},
        user, _stub_log(), db, "text")
    assert "Removed" in res and "Legs" in res
    prog = await _prog(db, user.id)
    assert [e["name"] for e in prog["days"][2]["exercises"]] == ["Squat"]
    # unknown exercise → clarify, no crash
    res = await TE._dispatch(
        "remove_program_exercise", {"exercise_name": "pec deck"},
        user, _stub_log(), db, "text")
    assert "isn't in the program" in res


async def test_set_program_target_bulk_all_scoped(db, make_user):
    """'3 sets for each movement' — exercise_name='all' + day scope hits every
    slot on that day and nothing elsewhere; sets-only writes no invented reps."""
    user = await _seed(db, make_user)
    res = await TE._dispatch(
        "set_program_target",
        {"exercise_name": "all", "day_name": "push", "sets": 3},
        user, _stub_log(), db, "text")
    assert "all 2 exercises" in res
    prog = await _prog(db, user.id)
    for e in prog["days"][0]["exercises"]:
        assert e["sets"] == 3
        assert "reps" not in e          # nothing invented
    for e in prog["days"][1]["exercises"] + prog["days"][2]["exercises"]:
        assert "sets" not in e          # scope respected


async def test_set_program_day_rest_is_first_class(db, make_user):
    """'Going with a rest day today' — rest doesn't need to exist in the split;
    it stamps the __rest__ sentinel and session state skips the day pick."""
    user = await _seed(db, make_user)
    res = await TE._dispatch("set_program_day", {"day_name": "rest day"},
                             user, _stub_log(), db, "text")
    assert "REST day" in res
    ov = (await _prog(db, user.id))["today_override"]
    assert ov["day"] == "__rest__"
    # session state: fresh rest override suppresses the program-day read
    from datetime import datetime as _dt
    now = _dt(2026, 7, 18, 10, 0)
    entry = SimpleNamespace(exercise_name="Barbell Row",
                            timestamp=now - timedelta(minutes=10))
    log = SimpleNamespace(id=1, exercise_entries=[entry])
    prog = dict(PROGRAM, today_override={"date": "2026-07-18", "day": "__rest__"})
    out = build_session_state(log, prog, now)
    assert "__rest__" not in out
