"""Regression: Danny's 2026-07-03 "duplication nation" arm session.

Two live-workout double-writes were observed in prod that night (parsed from
his logs). Both are prevented by the current tool_executor dedup path; these
tests lock that behavior at the dispatch level so a future change can't
silently reopen the gap. (The prod rows themselves were repaired separately —
see scripts/cleanup_danny_dup_cable_crunch.py.)

Incident A — Cable Crunch set 1 double-counted:
    00:49  "15x160"  -> row #595  sets=1 reps='15'   @160lb
    00:52  "14x160"  -> model re-states the running list sets=2 reps='15,14'
    Bug on prod: a NEW row #596 was inserted, leaving #595 in place, so the
    first crunch set was counted twice. Correct behavior: rollup-supersede #595
    in place -> one row '15,14', no insert.

Incident B — Overhead Cable Extension logged 3x:
    The completed 3-set block (14,12,10 @110lb) was re-fired identically on a
    question turn ("3 sets enough for triceps?") and a wrap-up turn ("gonna do
    some spin"). Correct behavior: the identical multi-set re-fire inside the
    600s window is blocked, no insert.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from handlers import tool_executor as TE


@pytest.mark.asyncio
async def test_crunch_rollup_supersedes_not_inserts(monkeypatch):
    """15 -> 15,14 at the same load must GROW #595, never insert a second row."""
    user = SimpleNamespace(id=26, timezone="America/New_York")
    prior = SimpleNamespace(
        id=595, exercise_name="Cable Crunch", sets=1, reps="15",
        weight=72.57472, weights=None, cardio_type=None,
        timestamp=datetime.utcnow() - timedelta(seconds=157),
    )
    today_log = SimpleNamespace(id=226, exercise_entries=[prior])

    writes = {"n": 0}
    updates = {"n": 0, "changes": None}

    async def _no_write(*a, **kw):
        writes["n"] += 1

    async def _capture_update(db, entry_id, user_id, **changes):
        updates["n"] += 1
        updates["changes"] = changes
        return SimpleNamespace(
            id=entry_id, exercise_name="Cable Crunch",
            sets=changes.get("sets"), reps=changes.get("reps"),
            weight=72.57472, weights=changes.get("weights"),
        )

    monkeypatch.setattr(TE, "add_exercise_entry", _no_write)
    monkeypatch.setattr(TE, "q_update_exercise_entry", _capture_update)

    async def _refresh(*a, **kw):
        pass

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Cable Crunch", "sets": 2, "reps": "15,14",
         "weight": 160, "weight_unit": "lbs"},
        user, today_log, db=SimpleNamespace(refresh=_refresh), source_type="text",
    )

    assert writes["n"] == 0, "rollup must NOT insert a second row"
    assert updates["n"] == 1, "must supersede the existing session row in place"
    assert updates["changes"]["reps"] == "15,14"
    assert "#595" in result, result


@pytest.mark.asyncio
async def test_overhead_ext_identical_multiset_refire_blocked(monkeypatch):
    """The completed 3-set block re-fired identically 12s later (question turn)
    must be caught by the multi-set dedup window — no second write."""
    user = SimpleNamespace(id=26, timezone="America/New_York")
    prior = SimpleNamespace(
        id=592, exercise_name="Overhead Cable Extension", sets=3,
        reps="14,12,10", weight=49.9, weights="45.36,49.9,49.9",
        cardio_type=None,
        timestamp=datetime.utcnow() - timedelta(seconds=12),
    )
    today_log = SimpleNamespace(id=226, exercise_entries=[prior])

    writes = {"n": 0}

    async def _no_write(*a, **kw):
        writes["n"] += 1

    monkeypatch.setattr(TE, "add_exercise_entry", _no_write)

    async def _refresh(*a, **kw):
        pass

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Overhead Cable Extension", "sets": 3,
         "reps": "14,12,10", "weights": "100,110,110", "weight_unit": "lbs"},
        user, today_log, db=SimpleNamespace(refresh=_refresh), source_type="text",
    )

    assert writes["n"] == 0, "identical multi-set re-fire must NOT write a second row"
    assert result.startswith("Already on the board:"), result
    assert "#592" in result, result
