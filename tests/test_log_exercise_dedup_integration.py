"""Integration test for log_exercise dedup at the tool_executor layer.

Reproduces Danny's 2026-06-11 re-log-on-context-shift pattern and asserts
the server-side guard catches it BEFORE add_exercise_entry runs.

The model can still fire log_exercise twice — we don't punish that. We
just don't write the duplicate row.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from handlers import tool_executor as TE


def _prior_entry(id_=147, name="Cable Pushdown", sets=1, reps="10",
                 weight=86.18, seconds_ago=15):
    """Build a SimpleNamespace standing in for an ExerciseEntry row already
    loaded on today_log.exercise_entries via selectinload."""
    return SimpleNamespace(
        id=id_,
        exercise_name=name,
        sets=sets,
        reps=reps,
        weight=weight,
        timestamp=datetime.utcnow() - timedelta(seconds=seconds_ago),
    )


@pytest.mark.asyncio
async def test_exact_replay_within_window_skips_write(monkeypatch):
    """The 22:57:02 'Logged 4 exercises' burst: model fires log_exercise for
    a set logged seconds earlier. The write must be skipped and the result
    must signal 'Already on the board' to the model."""
    user = SimpleNamespace(id=1, timezone="UTC")
    prior = _prior_entry(id_=147, name="Cable Pushdown", sets=1, reps="10",
                         weight=86.18, seconds_ago=12)
    today_log = SimpleNamespace(
        id=1,
        exercise_entries=[prior],
    )

    write_count = {"n": 0}

    async def _no_write(*a, **kw):
        write_count["n"] += 1

    monkeypatch.setattr(TE, "add_exercise_entry", _no_write)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Cable Pushdown", "sets": 1, "reps": "10",
         "weight": 190, "weight_unit": "lbs"},
        user, today_log, db=None, source_type="text",
    )
    assert result.startswith("Already on the board:"), result
    assert "Cable Pushdown" in result
    assert "[#147]" in result
    assert write_count["n"] == 0, "dup must NOT reach add_exercise_entry"


@pytest.mark.asyncio
async def test_different_weight_writes_through(monkeypatch):
    """Second set of the same exercise at a different weight is a real drop
    set, not a dup. Must write through."""
    user = SimpleNamespace(id=1, timezone="UTC")
    prior = _prior_entry(id_=157, name="Straight Bar Cable Curl", sets=1,
                         reps="13", weight=63.50, seconds_ago=10)
    today_log = SimpleNamespace(
        id=1,
        exercise_entries=[prior],
    )

    write_count = {"n": 0}

    async def _capture(*a, **kw):
        write_count["n"] += 1

    monkeypatch.setattr(TE, "add_exercise_entry", _capture)

    async def _refresh(*a, **kw):
        pass

    db = SimpleNamespace(refresh=_refresh)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Straight Bar Cable Curl", "sets": 1, "reps": "10",
         "weight": 130, "weight_unit": "lbs"},
        user, today_log, db=db, source_type="text",
    )
    assert result.startswith("Logged "), result
    assert write_count["n"] == 1


@pytest.mark.asyncio
async def test_legit_second_set_outside_window_writes_through(monkeypatch):
    """Same payload but 3 minutes apart — a legit second set of the same
    weight. Must write through."""
    user = SimpleNamespace(id=1, timezone="UTC")
    # 3 minutes ago — outside the 120s default window
    prior = _prior_entry(id_=200, seconds_ago=180)
    today_log = SimpleNamespace(
        id=1,
        exercise_entries=[prior],
    )

    write_count = {"n": 0}

    async def _capture(*a, **kw):
        write_count["n"] += 1

    monkeypatch.setattr(TE, "add_exercise_entry", _capture)

    async def _refresh(*a, **kw):
        pass

    db = SimpleNamespace(refresh=_refresh)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Cable Pushdown", "sets": 1, "reps": "10",
         "weight": 190, "weight_unit": "lbs"},
        user, today_log, db=db, source_type="text",
    )
    assert result.startswith("Logged "), result
    assert write_count["n"] == 1


@pytest.mark.asyncio
async def test_first_exercise_of_session_writes_through(monkeypatch):
    """Empty log — first exercise of the day. Can't be a dup of anything.
    Pins that an empty existing_entries list never raises."""
    user = SimpleNamespace(id=1, timezone="UTC")
    today_log = SimpleNamespace(
        id=1,
        exercise_entries=[],
    )

    write_count = {"n": 0}

    async def _capture(*a, **kw):
        write_count["n"] += 1

    monkeypatch.setattr(TE, "add_exercise_entry", _capture)

    async def _refresh(*a, **kw):
        pass

    db = SimpleNamespace(refresh=_refresh)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Bench Press", "sets": 3, "reps": "8,8,7",
         "weight": 135, "weight_unit": "lbs"},
        user, today_log, db=db, source_type="text",
    )
    assert result.startswith("Logged "), result
    assert write_count["n"] == 1


# ── deterministic_confirmation: dedup-aware fallback ─────────────────────────

def test_deterministic_confirmation_handles_already_on_board():
    """When the model produced no text after a log_exercise that got
    dedup'd, the fallback macro must NOT say 'Exercise logged' — it should
    acknowledge the dup."""
    tc = [{"name": "log_exercise",
           "input": {"exercise_name": "Cable Pushdown", "sets": 1,
                     "reps": "10", "weight": 190}}]
    tool_results = {
        "log_exercise": (
            "Already on the board: Cable Pushdown (1×10 @ 190lb). "
            "Logged as [#147] 12s ago. YOUR REPLY: do NOT emit a fresh log line."
        )
    }
    log = SimpleNamespace(total_calories=0, total_protein=0)
    prefs = SimpleNamespace(calorie_target=None, protein_target=None)
    out = TE.deterministic_confirmation(tc, log, prefs, tool_results=tool_results)
    assert "already on the board" in out.lower(), out
    assert "logged" not in out.lower() or "what's next" in out.lower()


def test_deterministic_confirmation_logged_normal_exercise():
    """Sanity: when the tool result is a normal 'Logged ...' message, the
    macro still says 'Exercise logged. 💪'."""
    tc = [{"name": "log_exercise",
           "input": {"exercise_name": "Bench Press", "sets": 3,
                     "reps": "8,8,7", "weight": 135}}]
    tool_results = {
        "log_exercise": "Logged Bench Press: 3×8,8,7 @ 135lbs. ...",
    }
    log = SimpleNamespace(total_calories=0, total_protein=0)
    prefs = SimpleNamespace(calorie_target=None, protein_target=None)
    out = TE.deterministic_confirmation(tc, log, prefs, tool_results=tool_results)
    assert "logged" in out.lower()
    assert "already on the board" not in out.lower()
