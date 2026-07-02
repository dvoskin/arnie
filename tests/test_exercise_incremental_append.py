"""RECONCILE-BEFORE-LOG (exercise) — the incremental-append path.

Danny 2026-07-02: 83% of strength entries were one-row-per-set because a set
reported on its own ("fell to 10", "another set of 15") missed the full-restate
rollup and inserted a parallel one-set row. find_incremental_append is the
rollup's strict complement: a pure single-set report of a movement already in
this session GROWS that session row (reps CSV +1 token, weights CSV when the
load differs), with a refire guard so a re-emitted (weight, reps) pair can't
double-append.

Integration style mirrors test_log_exercise_dedup_integration.py —
SimpleNamespace rows, monkeypatched writers, no real DB.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from handlers import tool_executor as TE
from skills.fitness.exercise_dedup import find_incremental_append


def _prior(id_=500, name="Incline Bench Machine Press", sets=1, reps="15",
           weight=92.98636, weights=None, seconds_ago=180, cardio_type=None):
    return SimpleNamespace(
        id=id_, exercise_name=name, sets=sets, reps=reps, weight=weight,
        weights=weights, cardio_type=cardio_type,
        timestamp=datetime.utcnow() - timedelta(seconds=seconds_ago),
    )


def _harness(monkeypatch, today_log):
    """Patch both writers; return (inserts, updates) capture dicts."""
    inserts = {"n": 0}
    updates = {"n": 0, "entry_id": None, "changes": None}

    async def _insert(*a, **kw):
        inserts["n"] += 1

    async def _update(db, entry_id, user_id, **changes):
        updates["n"] += 1
        updates["entry_id"] = entry_id
        updates["changes"] = changes
        return SimpleNamespace(
            id=entry_id, exercise_name="Incline Bench Machine Press",
            sets=changes.get("sets"), reps=changes.get("reps"),
            weight=92.98636, weights=changes.get("weights"))

    monkeypatch.setattr(TE, "add_exercise_entry", _insert)
    monkeypatch.setattr(TE, "q_update_exercise_entry", _update)
    return inserts, updates


async def _refresh(*a, **kw):
    pass


def _dispatch_args(today_log):
    user = SimpleNamespace(id=26, timezone="UTC")
    return user, today_log, SimpleNamespace(refresh=_refresh)


# ── the fragmentation fix ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_incremental_single_set_appends_not_inserts(monkeypatch):
    """'Fell down to 10' 3 min after the 15-rep opener must GROW row #500 to
    2×'15,10', not insert a second one-set row."""
    today_log = SimpleNamespace(id=1, exercise_entries=[_prior(seconds_ago=180)])
    inserts, updates = _harness(monkeypatch, today_log)
    user, log, db = _dispatch_args(today_log)

    inp = {"exercise_name": "Incline Bench Machine Press", "sets": 1,
           "reps": "10", "weight": 205, "weight_unit": "lbs"}
    result = await TE._dispatch(
        "log_exercise", inp, user, log, db=db, source_type="ios",
        user_message="Fell down to 10 reps on that second set",
    )
    assert inserts["n"] == 0, "incremental set must NOT insert a new row"
    assert updates["n"] == 1 and updates["entry_id"] == 500
    assert updates["changes"]["sets"] == 2
    assert updates["changes"]["reps"] == "15,10"
    assert updates["changes"].get("weights") is None, "same load → scalar stands"
    assert result.startswith("Appended the set"), result
    assert inp.get("_entry_id") == 500, "native edit must target the grown row"


@pytest.mark.asyncio
async def test_identical_pair_with_add_cue_appends(monkeypatch):
    """'Another set of 15' — the (weight, reps) pair already exists, but the
    turn gate authorizes the repeat → append, don't block, don't insert."""
    today_log = SimpleNamespace(
        id=1, exercise_entries=[_prior(sets=2, reps="15,10", seconds_ago=200)])
    inserts, updates = _harness(monkeypatch, today_log)
    user, log, db = _dispatch_args(today_log)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Incline Bench Machine Press", "sets": 1,
         "reps": "15", "weight": 205, "weight_unit": "lbs"},
        user, log, db=db, source_type="ios",
        user_message="Another set of 15",
    )
    assert inserts["n"] == 0
    assert updates["n"] == 1
    assert updates["changes"]["reps"] == "15,10,15"
    assert updates["changes"]["sets"] == 3
    assert result.startswith("Appended the set"), result


@pytest.mark.asyncio
async def test_identical_pair_no_cue_within_guard_blocked(monkeypatch):
    """Double-fire shape (Danny 23:07 'Hit 10 again' processed twice): the pair
    was just performed, no add cue → refire-block, no write of any kind."""
    today_log = SimpleNamespace(
        id=1, exercise_entries=[_prior(sets=2, reps="15,10", seconds_ago=30)])
    inserts, updates = _harness(monkeypatch, today_log)
    user, log, db = _dispatch_args(today_log)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Incline Bench Machine Press", "sets": 1,
         "reps": "10", "weight": 205, "weight_unit": "lbs"},
        user, log, db=db, source_type="ios",
        user_message="what's next",
    )
    assert inserts["n"] == 0 and updates["n"] == 0
    assert result.startswith("Already on the board:"), result


@pytest.mark.asyncio
async def test_identical_pair_no_cue_beyond_guard_falls_to_legacy(monkeypatch):
    """The same identical pair 8 minutes later without a cue is ambiguous — the
    append path stands down (legacy paths own it; here that's a visible insert,
    never a silent phantom append)."""
    today_log = SimpleNamespace(
        id=1, exercise_entries=[_prior(sets=2, reps="15,10", seconds_ago=480)])
    inserts, updates = _harness(monkeypatch, today_log)
    user, log, db = _dispatch_args(today_log)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Incline Bench Machine Press", "sets": 1,
         "reps": "10", "weight": 205, "weight_unit": "lbs"},
        user, log, db=db, source_type="ios",
        user_message="10",
    )
    assert updates["n"] == 0, "ambiguous refire-shape must not append"
    assert inserts["n"] == 1, "legacy path inserts (visible, correctable)"
    assert result.startswith("Logged "), result


@pytest.mark.asyncio
async def test_drop_set_appends_with_weights_csv(monkeypatch):
    """A drop set (same movement, lighter load) grows the SAME row and records
    the per-set loads in the weights CSV — that's what the column is for."""
    today_log = SimpleNamespace(id=1, exercise_entries=[_prior(seconds_ago=150)])
    inserts, updates = _harness(monkeypatch, today_log)
    user, log, db = _dispatch_args(today_log)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Incline Bench Machine Press", "sets": 1,
         "reps": "12", "weight": 185, "weight_unit": "lbs"},
        user, log, db=db, source_type="ios",
        user_message="dropped to 185 for 12",
    )
    assert inserts["n"] == 0 and updates["n"] == 1
    assert updates["changes"]["reps"] == "15,12"
    w = updates["changes"]["weights"]
    assert w is not None and w.startswith("92.99,83.9"), w  # kg CSV, 2dp
    assert result.startswith("Appended the set"), result


@pytest.mark.asyncio
async def test_full_restate_still_rolls_up_not_append(monkeypatch):
    """A cumulative restate ('15' → '15,10') is the ROLLUP's job — the append
    path must stand down so the two never double-count."""
    today_log = SimpleNamespace(id=1, exercise_entries=[_prior(seconds_ago=200)])
    inserts, updates = _harness(monkeypatch, today_log)
    user, log, db = _dispatch_args(today_log)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Incline Bench Machine Press", "sets": 2,
         "reps": "15,10", "weight": 205, "weight_unit": "lbs"},
        user, log, db=db, source_type="ios",
    )
    assert inserts["n"] == 0 and updates["n"] == 1
    assert updates["changes"]["reps"] == "15,10"
    assert result.startswith("Updated the running set"), result


@pytest.mark.asyncio
async def test_constant_rep_block_expands_then_appends(monkeypatch):
    """A compact constant-rep row (sets=3, reps='12') expands per set before the
    append so the CSV stays aligned: → 4×'12,12,12,10'."""
    today_log = SimpleNamespace(
        id=1, exercise_entries=[_prior(sets=3, reps="12", seconds_ago=240)])
    inserts, updates = _harness(monkeypatch, today_log)
    user, log, db = _dispatch_args(today_log)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Incline Bench Machine Press", "sets": 1,
         "reps": "10", "weight": 205, "weight_unit": "lbs"},
        user, log, db=db, source_type="ios",
        user_message="last one, 10",
    )
    assert inserts["n"] == 0 and updates["n"] == 1
    assert updates["changes"]["sets"] == 4
    assert updates["changes"]["reps"] == "12,12,12,10"
    assert result.startswith("Appended the set"), result


@pytest.mark.asyncio
async def test_first_set_of_movement_still_inserts(monkeypatch):
    """No same-movement row in the session → nothing to append → insert."""
    today_log = SimpleNamespace(
        id=1, exercise_entries=[_prior(name="Lat Pulldown", seconds_ago=300)])
    inserts, updates = _harness(monkeypatch, today_log)
    user, log, db = _dispatch_args(today_log)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Seated Cable Row", "sets": 1, "reps": "11",
         "weight": 145, "weight_unit": "lbs"},
        user, log, db=db, source_type="ios",
        user_message="rows 145x11",
    )
    assert updates["n"] == 0
    assert inserts["n"] == 1
    assert result.startswith("Logged "), result


@pytest.mark.asyncio
async def test_cardio_never_appends(monkeypatch):
    """Two bike bouts are two entries — cardio skips the append path entirely."""
    today_log = SimpleNamespace(
        id=1, exercise_entries=[
            _prior(name="Stationary Bike", sets=None, reps=None, weight=None,
                   cardio_type="Zone 1-2 spin", seconds_ago=600)])
    inserts, updates = _harness(monkeypatch, today_log)
    user, log, db = _dispatch_args(today_log)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Stationary Bike", "is_cardio": True,
         "cardio_type": "Zone 1-2 spin", "duration_minutes": 15},
        user, log, db=db, source_type="ios",
        user_message="another 15 min spin",
    )
    assert updates["n"] == 0
    assert inserts["n"] == 1


# ── pure-function edges ──────────────────────────────────────────────────────

def test_append_requires_a_loaded_single_set():
    now = datetime.utcnow()
    rows = [_prior(seconds_ago=100)]
    # multi-set incoming → None (rollup territory)
    assert find_incremental_append(
        exercise_name="Incline Bench Machine Press", sets=2, reps="15,10",
        weight_kg=92.99, existing_entries=rows, now_utc=now) is None
    # unloaded / bodyweight → None (legacy paths)
    assert find_incremental_append(
        exercise_name="Incline Bench Machine Press", sets=1, reps="10",
        weight_kg=None, existing_entries=rows, now_utc=now) is None
    # no candidates → None
    assert find_incremental_append(
        exercise_name="Incline Bench Machine Press", sets=1, reps="10",
        weight_kg=92.99, existing_entries=[], now_utc=now) is None


def test_append_skips_rows_outside_session_window():
    now = datetime.utcnow()
    stale = [_prior(seconds_ago=2 * 3600)]  # 2h — a different session
    assert find_incremental_append(
        exercise_name="Incline Bench Machine Press", sets=1, reps="10",
        weight_kg=92.99, existing_entries=stale, now_utc=now) is None
