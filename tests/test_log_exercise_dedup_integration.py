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


# ── Multi-set re-log window (Danny 2026-06-14 phantom Face Pull) ─────────────

@pytest.mark.asyncio
async def test_multiset_relog_within_10min_blocked(monkeypatch):
    """A completed multi-set block (sets>=2) re-fired 8 minutes later — the
    Danny 2026-06-14 Face Pull case (3×12 @ 70lb logged at 23:41, re-logged
    identically at 23:49). Outside the 120s single-set window but inside the
    widened 600s multi-set window → must be blocked."""
    user = SimpleNamespace(id=1, timezone="UTC")
    # 8 minutes ago — outside 120s, inside the 600s multi-set window
    prior = _prior_entry(id_=194, name="Face Pull", sets=3, reps="12,12,12",
                         weight=31.751, seconds_ago=480)
    today_log = SimpleNamespace(id=1, exercise_entries=[prior])

    write_count = {"n": 0}

    async def _no_write(*a, **kw):
        write_count["n"] += 1

    monkeypatch.setattr(TE, "add_exercise_entry", _no_write)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Face Pull", "sets": 3, "reps": "12,12,12",
         "weight": 70, "weight_unit": "lbs"},
        user, today_log, db=None, source_type="text",
    )
    assert result.startswith("Already on the board:"), result
    assert write_count["n"] == 0, "8-min multi-set re-log must be blocked"


@pytest.mark.asyncio
async def test_single_set_relog_at_8min_still_writes(monkeypatch):
    """A SINGLE-set entry re-reported 8 minutes later stays legitimate — the
    widened window applies ONLY to multi-set blocks, so a real second single
    at the same load must still write through (no false block)."""
    user = SimpleNamespace(id=1, timezone="UTC")
    prior = _prior_entry(id_=189, name="Cable Lateral Raise", sets=1,
                         reps="16", weight=9.072, seconds_ago=480)
    today_log = SimpleNamespace(id=1, exercise_entries=[prior])

    write_count = {"n": 0}

    async def _capture(*a, **kw):
        write_count["n"] += 1

    monkeypatch.setattr(TE, "add_exercise_entry", _capture)

    async def _refresh(*a, **kw):
        pass

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Cable Lateral Raise", "sets": 1, "reps": "16",
         "weight": 20, "weight_unit": "lbs"},
        user, today_log, db=SimpleNamespace(refresh=_refresh), source_type="text",
    )
    assert result.startswith("Logged "), result
    assert write_count["n"] == 1, "single-set re-log at 8min must still write"


# ── Log-divergence monitoring (#4) ───────────────────────────────────────────

def test_divergence_flags_phantom_dup_block():
    """The Danny 7-for-3 signature: Face Pull 3×12 logged twice → dup_block."""
    entries = [
        _prior_entry(id_=192, name="Face Pull", sets=1, reps="12", weight=31.75),
        _prior_entry(id_=194, name="Face Pull", sets=3, reps="12,12,12", weight=31.75),
        _prior_entry(id_=196, name="Face Pull", sets=3, reps="12,12,12", weight=31.75),
    ]
    log = SimpleNamespace(exercise_entries=entries)
    flags = TE._detect_log_divergence(log)
    assert any("face pull" in f and "dup_block" in f for f in flags), flags


def test_divergence_clean_session_no_flags():
    """A normal session — distinct movements, no identical multi-set repeats."""
    entries = [
        _prior_entry(id_=1, name="Face Pull", sets=3, reps="12,12,12", weight=31.75),
        _prior_entry(id_=2, name="Upright Row", sets=3, reps="12,12,12", weight=49.9),
        _prior_entry(id_=3, name="Cable Front Raise", sets=1, reps="12", weight=36.3),
    ]
    log = SimpleNamespace(exercise_entries=entries)
    assert TE._detect_log_divergence(log) == []


def test_divergence_flags_high_volume():
    """One movement with an implausible session set count gets flagged."""
    entries = [_prior_entry(id_=i, name="Bicep Curl", sets=2, reps=f"{10+i},{9+i}",
                            weight=20.0 + i) for i in range(6)]  # 12 sets, all distinct
    log = SimpleNamespace(exercise_entries=entries)
    flags = TE._detect_log_divergence(log)
    assert any("high_volume" in f for f in flags), flags


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


# ── Bulk post-factum paste: snapshot-based dedup ─────────────────────────────

@pytest.mark.asyncio
async def test_bulk_paste_identical_payloads_all_log_through(monkeypatch):
    """A user pastes a post-factum workout where multiple sets have the
    exact same payload (e.g. 'did 4 sets of 135x5 on bench'). The model
    fires log_exercise multiple times in one batch (suboptimal — the
    prompt rules say to consolidate, but it does happen). All sets MUST
    write — the dedup must not self-block within a single tool batch.

    Pre-Phase-1.1 behavior: only first set logged, others blocked.
    Post-Phase-1.1: snapshot-based dedup ignores entries created in this
    batch, so all 4 write through."""
    user = SimpleNamespace(id=1, timezone="UTC")
    # Empty pre-existing log — user logged nothing earlier today
    today_log = SimpleNamespace(id=1, exercise_entries=[])

    write_count = {"n": 0}

    async def _capture(db, daily_log_id, **kw):
        # Simulate the DB-write side effect: each write adds a row to
        # target_log.exercise_entries (mimicking the db.refresh that
        # tool_executor does after add_exercise_entry).
        write_count["n"] += 1
        new_id = 1000 + write_count["n"]
        today_log.exercise_entries.append(SimpleNamespace(
            id=new_id, exercise_name=kw.get("exercise_name"),
            sets=kw.get("sets"), reps=kw.get("reps"),
            weight=kw.get("weight"),
            timestamp=datetime.utcnow(),
        ))

    monkeypatch.setattr(TE, "add_exercise_entry", _capture)

    async def _refresh(*a, **kw):
        pass

    db = SimpleNamespace(refresh=_refresh)

    # Simulate the model firing log_exercise four times in one turn for
    # four identical-payload sets — bulk post-factum paste pattern.
    tool_calls = [
        {"name": "log_exercise",
         "input": {"exercise_name": "Bench Press", "sets": 1,
                   "reps": "5", "weight": 135, "weight_unit": "lbs"}}
        for _ in range(4)
    ]
    results = await TE.execute_tool_calls(
        tool_calls, user, today_log, db, source_type="text",
    )
    assert write_count["n"] == 4, (
        f"all 4 bulk-paste identical sets should write, got {write_count['n']}. "
        f"results: {results}"
    )


@pytest.mark.asyncio
async def test_bulk_paste_mixed_with_prior_session_still_blocks_old_dup(monkeypatch):
    """Compound scenario: user has prior entries from earlier today, then
    pastes a bulk paste in the next message. The bulk paste's NEW sets
    should log. If the model re-logs an OLD set from earlier (the
    re-log-on-context-shift bug), THAT should still be blocked.

    Pins both behaviors: bulk paste passes through, prior-turn dup catches."""
    user = SimpleNamespace(id=1, timezone="UTC")
    # Prior session set from earlier today (in pre-existing snapshot)
    prior = SimpleNamespace(
        id=100, exercise_name="Cable Pushdown",
        sets=1, reps="10", weight=86.18,
        timestamp=datetime.utcnow() - timedelta(seconds=30),
    )
    today_log = SimpleNamespace(id=1, exercise_entries=[prior])

    write_count = {"n": 0}

    async def _capture(db, daily_log_id, **kw):
        write_count["n"] += 1
        new_id = 1000 + write_count["n"]
        today_log.exercise_entries.append(SimpleNamespace(
            id=new_id, exercise_name=kw.get("exercise_name"),
            sets=kw.get("sets"), reps=kw.get("reps"),
            weight=kw.get("weight"),
            timestamp=datetime.utcnow(),
        ))

    monkeypatch.setattr(TE, "add_exercise_entry", _capture)

    async def _refresh(*a, **kw):
        pass

    db = SimpleNamespace(refresh=_refresh)

    # Batch with 3 calls:
    #   1) Cable Pushdown 1×10 @ 190lb — duplicates the prior session set → BLOCKED
    #   2) Bench Press 1×5 @ 135lb — fresh, should log
    #   3) Bench Press 1×5 @ 135lb — identical to #2 in this batch, should log
    tool_calls = [
        {"name": "log_exercise",
         "input": {"exercise_name": "Cable Pushdown", "sets": 1,
                   "reps": "10", "weight": 190, "weight_unit": "lbs"}},
        {"name": "log_exercise",
         "input": {"exercise_name": "Bench Press", "sets": 1,
                   "reps": "5", "weight": 135, "weight_unit": "lbs"}},
        {"name": "log_exercise",
         "input": {"exercise_name": "Bench Press", "sets": 1,
                   "reps": "5", "weight": 135, "weight_unit": "lbs"}},
    ]
    await TE.execute_tool_calls(
        tool_calls, user, today_log, db, source_type="text",
    )
    # The Cable Pushdown re-log was blocked; both Bench Press sets wrote
    assert write_count["n"] == 2, (
        f"expected 2 writes (both Bench), Cable Pushdown blocked. "
        f"got {write_count['n']}"
    )


@pytest.mark.asyncio
async def test_bulk_paste_different_movements_all_log(monkeypatch):
    """Bulk paste covering different movements, all NEW. Each movement
    writes once. This is the most common bulk-paste shape — Phase 2's
    canonicalization + the snapshot means it Just Works."""
    user = SimpleNamespace(id=1, timezone="UTC")
    today_log = SimpleNamespace(id=1, exercise_entries=[])

    written: list = []

    async def _capture(db, daily_log_id, **kw):
        written.append(kw)
        today_log.exercise_entries.append(SimpleNamespace(
            id=1000 + len(written),
            exercise_name=kw.get("exercise_name"),
            sets=kw.get("sets"), reps=kw.get("reps"),
            weight=kw.get("weight"),
            timestamp=datetime.utcnow(),
        ))

    monkeypatch.setattr(TE, "add_exercise_entry", _capture)

    async def _refresh(*a, **kw):
        pass

    db = SimpleNamespace(refresh=_refresh)

    tool_calls = [
        {"name": "log_exercise",
         "input": {"exercise_name": "Back Squat", "sets": 3,
                   "reps": "10,9,8", "weight": 225, "weight_unit": "lbs"}},
        {"name": "log_exercise",
         "input": {"exercise_name": "Leg Press", "sets": 3,
                   "reps": "12,12,10", "weight": 360, "weight_unit": "lbs"}},
        {"name": "log_exercise",
         "input": {"exercise_name": "Leg Extension", "sets": 3,
                   "reps": "12,12,10", "weight": 130, "weight_unit": "lbs"}},
    ]
    await TE.execute_tool_calls(
        tool_calls, user, today_log, db, source_type="text",
    )
    assert len(written) == 3
    # Verify canonical names were stored (Phase 2 wiring still active)
    names = {w["exercise_name"] for w in written}
    assert "Back Squat" in names
    assert "Leg Press" in names
    assert "Leg Extension" in names
