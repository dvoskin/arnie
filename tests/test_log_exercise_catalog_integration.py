"""Integration tests for catalog canonicalization at the tool_executor layer.

Verifies that when the model fires log_exercise with a user-typed name like
"crunches (cable/machine)" or "pushdowns", the executor:
  1. Canonicalizes BEFORE writing (so exercise_entries.exercise_name stores
     "Cable Crunch" / "Cable Pushdown", not the raw string)
  2. Canonicalizes BEFORE dedup (so two phrasings of the same movement
     collide on the dedup key)
  3. Echoes the canonical name in the tool result (so the model's log line
     matches what was stored)
  4. Falls back to the raw name when no catalog match exists
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from handlers import tool_executor as TE


@pytest.mark.asyncio
async def test_canonicalization_normalizes_name_before_write(monkeypatch):
    """The model fires log_exercise with 'crunches (cable/machine)' — the
    string Danny actually saw it use. The DB write should receive 'Cable
    Crunch' so a later 'cable crunch' log collides on the dedup key."""
    user = SimpleNamespace(id=1, timezone="UTC")
    today_log = SimpleNamespace(id=1, exercise_entries=[])

    captured = {}

    async def _capture(db, daily_log_id, **kw):
        captured.update(kw)

    monkeypatch.setattr(TE, "add_exercise_entry", _capture)

    async def _refresh(*a, **kw):
        pass

    db = SimpleNamespace(refresh=_refresh)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "crunches (cable/machine)", "sets": 1,
         "reps": "14", "weight": 140, "weight_unit": "lbs"},
        user, today_log, db=db, source_type="text",
    )
    assert captured["exercise_name"] == "Cable Crunch", captured
    # Tool result should echo the canonical name so the model's log line uses it
    assert "Cable Crunch" in result, result


@pytest.mark.asyncio
async def test_two_phrasings_dedup_via_canonical(monkeypatch):
    """Existing entry stored as 'Cable Crunch' (canonical). Model fires
    log_exercise with 'crunches (cable/machine)'. Dedup must fire — both
    phrasings canonicalize to 'Cable Crunch'."""
    user = SimpleNamespace(id=1, timezone="UTC")
    # Prior entry already stored under canonical name (post-Phase-2 path)
    prior = SimpleNamespace(
        id=151,
        exercise_name="Cable Crunch",
        sets=1, reps="14", weight=63.50,
        timestamp=datetime.utcnow() - timedelta(seconds=10),
    )
    today_log = SimpleNamespace(id=1, exercise_entries=[prior])

    write_count = {"n": 0}

    async def _no_write(*a, **kw):
        write_count["n"] += 1

    monkeypatch.setattr(TE, "add_exercise_entry", _no_write)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "crunches (cable/machine)", "sets": 1,
         "reps": "14", "weight": 140, "weight_unit": "lbs"},
        user, today_log, db=None, source_type="text",
    )
    assert result.startswith("Already on the board:"), result
    assert write_count["n"] == 0


@pytest.mark.asyncio
async def test_unknown_name_passes_through(monkeypatch):
    """A movement not in the catalog (e.g. a wild aerobics class name) must
    still log under the raw user-typed name, not vanish."""
    user = SimpleNamespace(id=1, timezone="UTC")
    today_log = SimpleNamespace(id=1, exercise_entries=[])

    captured = {}

    async def _capture(db, daily_log_id, **kw):
        captured.update(kw)

    monkeypatch.setattr(TE, "add_exercise_entry", _capture)

    async def _refresh(*a, **kw):
        pass

    db = SimpleNamespace(refresh=_refresh)

    raw = "Some Niche Class Movement"
    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": raw, "sets": 3, "reps": "12,12,10"},
        user, today_log, db=db, source_type="text",
    )
    assert captured["exercise_name"] == raw, captured
    assert raw in result


@pytest.mark.asyncio
async def test_canonical_used_in_dedup_skip_message(monkeypatch):
    """The dedup-skipped message tells the model what was already saved.
    It must reference the canonical name (which is what's in [TODAY]),
    not the raw user-typed string — so the model's reply names the right
    exercise."""
    user = SimpleNamespace(id=1, timezone="UTC")
    prior = SimpleNamespace(
        id=147,
        exercise_name="Cable Pushdown",
        sets=1, reps="10", weight=86.18,
        timestamp=datetime.utcnow() - timedelta(seconds=8),
    )
    today_log = SimpleNamespace(id=1, exercise_entries=[prior])

    async def _no_write(*a, **kw):
        pass

    monkeypatch.setattr(TE, "add_exercise_entry", _no_write)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "pushdowns", "sets": 1, "reps": "10",
         "weight": 190, "weight_unit": "lbs"},
        user, today_log, db=None, source_type="text",
    )
    assert result.startswith("Already on the board:"), result
    assert "Cable Pushdown" in result, result
