"""
Turn-intent gate for the food / water / exercise dedup guards
(skills/logging_intent.py, wired in handlers/tool_executor._dispatch).

The guards block a log_* call whose payload matches a recent same-day entry —
which silently dropped real repeats (Anya 2026-06-26 "one more same coffee").
The gate honors a log when the user's turn carries explicit add/repeat intent,
while keeping the block for phantom re-fires (topic pivot) and retries
("log it again"). These tests pin both directions for all three log types.

Default-closed safety (empty user_message → unchanged behavior) is already
covered by the existing dedup suites, which call _dispatch without a message.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from handlers import tool_executor as TE
from skills.logging_intent import has_add_intent, turn_supports_log


# ── unit: the shared signal ──────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "one more same coffee", "2 more coffee cups", "another coffee",
    "ещё один капучино", "еще кофе", "давай вторую колу", "добавь ещё",
    "x2 espresso", "one more", "a bit more rice",
])
def test_add_intent_positive(text):
    assert has_add_intent(text) is True


@pytest.mark.parametrize("text", [
    "log the elmhurst again",   # retry — must stay closed (idempotency)
    "log it again", "cappuccino", "had a cappuccino", "log the coffee",
    "no more coffee", "connect apple health", "wait a second", "", None,
])
def test_add_intent_negative(text):
    assert has_add_intent(text) is False


def test_gate_ignores_item_name():
    # naming the item must NOT open the gate (a retry names it too)
    assert turn_supports_log("log the elmhurst again", "Elmhurst shake") is False
    assert turn_supports_log("one more elmhurst", "Elmhurst shake") is True


# ── integration: food ────────────────────────────────────────────────────────

def _food_env(monkeypatch, prior_minutes_ago=33):
    """today_log with one prior cappuccino, all writes/analysis stubbed."""
    prior = SimpleNamespace(
        id=1294, parsed_food_name="cappuccino", quantity="1 cup",
        calories=180.0, timestamp=datetime.utcnow() - timedelta(minutes=prior_minutes_ago),
    )
    today_log = SimpleNamespace(
        id=1, date=datetime.utcnow().date(), food_entries=[prior],
        total_calories=180.0, total_protein=6.0,
    )
    user = SimpleNamespace(id=44, timezone="UTC",
                           preferences=SimpleNamespace(calorie_target=1562, protein_target=121))
    writes = {"n": 0}

    async def _resolve_log(inp, u, tl, db):
        return today_log, None

    async def _analyze(db, u, name, inp):
        return SimpleNamespace(calories=180, protein=6, carbs=22, fat=7, fiber=None,
                               sugar=None, sodium=None, confidence="estimated",
                               coach_note="ok", enrichment_source=None)

    async def _add(db, daily_log_id, **kw):
        writes["n"] += 1
        return SimpleNamespace(id=2000 + writes["n"])

    async def _noop(*a, **kw):
        pass

    monkeypatch.setattr(TE, "_resolve_log", _resolve_log)
    monkeypatch.setattr(TE, "_analyze_food", _analyze)
    monkeypatch.setattr(TE, "add_food_entry", _add)
    db = SimpleNamespace(refresh=_noop, commit=_noop)
    return user, today_log, db, writes


@pytest.mark.asyncio
async def test_food_second_coffee_with_add_intent_logs(monkeypatch):
    """Anya's case: 'one more same coffee' 33 min after the first cappuccino
    must WRITE, not get swallowed as a dup."""
    user, today_log, db, writes = _food_env(monkeypatch)
    inp = {"food_name": "cappuccino", "quantity": "1 cup", "calories": 180}
    result = await TE._dispatch("log_food", inp, user, today_log, db, "ios",
                                user_message="one more same coffee")
    assert result.startswith("Logged "), result
    assert writes["n"] == 1


@pytest.mark.asyncio
async def test_food_phantom_refire_on_pivot_still_blocked(monkeypatch):
    """Same payload, but the user's turn is a topic pivot (the original
    re-log-on-context-shift bug) — must stay blocked."""
    user, today_log, db, writes = _food_env(monkeypatch)
    inp = {"food_name": "cappuccino", "quantity": "1 cup", "calories": 180}
    result = await TE._dispatch("log_food", inp, user, today_log, db, "ios",
                                user_message="can you connect to apple health?")
    assert result.startswith("Already on the board:"), result
    assert writes["n"] == 0


@pytest.mark.asyncio
async def test_food_retry_again_still_blocked(monkeypatch):
    """'log the coffee again' is a retry/re-send, not a second portion — must
    stay blocked so idempotency holds."""
    user, today_log, db, writes = _food_env(monkeypatch)
    inp = {"food_name": "cappuccino", "quantity": "1 cup", "calories": 180}
    result = await TE._dispatch("log_food", inp, user, today_log, db, "ios",
                                user_message="log the coffee again")
    assert result.startswith("Already on the board:"), result
    assert writes["n"] == 0


@pytest.mark.asyncio
async def test_food_default_closed_blocks(monkeypatch):
    """No user_message (default) → gate closed → existing block behavior."""
    user, today_log, db, writes = _food_env(monkeypatch)
    inp = {"food_name": "cappuccino", "quantity": "1 cup", "calories": 180}
    result = await TE._dispatch("log_food", inp, user, today_log, db, "ios")
    assert result.startswith("Already on the board:"), result
    assert writes["n"] == 0


# ── integration: exercise ────────────────────────────────────────────────────

def _ex_env(monkeypatch, seconds_ago=12):
    prior = SimpleNamespace(id=147, exercise_name="Cable Pushdown", sets=1,
                            reps="10", weight=86.18,
                            timestamp=datetime.utcnow() - timedelta(seconds=seconds_ago))
    today_log = SimpleNamespace(id=1, exercise_entries=[prior])
    user = SimpleNamespace(id=44, timezone="UTC")
    writes = {"n": 0}

    async def _resolve_log(inp, u, tl, db):
        return today_log, None

    async def _add(*a, **kw):
        writes["n"] += 1

    async def _noop(*a, **kw):
        pass

    monkeypatch.setattr(TE, "_resolve_log", _resolve_log)
    monkeypatch.setattr(TE, "add_exercise_entry", _add)
    return user, today_log, SimpleNamespace(refresh=_noop), writes


@pytest.mark.asyncio
async def test_exercise_another_set_with_add_intent_logs(monkeypatch):
    """'another set' at the same load is a real second set — must write."""
    user, today_log, db, writes = _ex_env(monkeypatch)
    inp = {"exercise_name": "Cable Pushdown", "sets": 1, "reps": "10",
           "weight": 190, "weight_unit": "lbs"}
    result = await TE._dispatch("log_exercise", inp, user, today_log, db, "text",
                                user_message="another set")
    assert result.startswith("Logged "), result
    assert writes["n"] == 1


@pytest.mark.asyncio
async def test_exercise_refire_on_question_still_blocked(monkeypatch):
    """Same set re-fired while the user asks an open question (no add cue) —
    must stay blocked (the 'Logged 4 exercises' burst case)."""
    user, today_log, db, writes = _ex_env(monkeypatch)
    inp = {"exercise_name": "Cable Pushdown", "sets": 1, "reps": "10",
           "weight": 190, "weight_unit": "lbs"}
    result = await TE._dispatch("log_exercise", inp, user, today_log, db, "text",
                                user_message="any suggestions for my next move?")
    assert result.startswith("Already on the board:"), result
    assert writes["n"] == 0


# ── integration: water ───────────────────────────────────────────────────────

def _water_env(monkeypatch, minutes_ago=20):
    prior = SimpleNamespace(id=77, amount_ml=250.0, context="random",
                            timestamp=datetime.utcnow() - timedelta(minutes=minutes_ago))
    today_log = SimpleNamespace(id=1, water_entries=[prior], total_water_ml=250.0)
    user = SimpleNamespace(id=44, timezone="UTC")

    async def _resolve_log(inp, u, tl, db):
        return today_log, None

    async def _noop(*a, **kw):
        pass

    monkeypatch.setattr(TE, "_resolve_log", _resolve_log)
    # canonical-row write is wrapped in try/except in the branch; a raising db
    # is fine, but give it async no-ops so the happy path is clean.
    db = SimpleNamespace(refresh=_noop, commit=_noop, add=lambda *a, **k: None)
    return user, today_log, db


@pytest.mark.asyncio
async def test_water_another_glass_with_add_intent_logs(monkeypatch):
    user, today_log, db = _water_env(monkeypatch)
    inp = {"amount_ml": 250}
    result = await TE._dispatch("log_water", inp, user, today_log, db, "text",
                                user_message="another glass")
    assert not result.startswith("Already on the board:"), result
    assert today_log.total_water_ml == 500.0


@pytest.mark.asyncio
async def test_water_refire_on_pivot_still_blocked(monkeypatch):
    user, today_log, db = _water_env(monkeypatch)
    inp = {"amount_ml": 250}
    result = await TE._dispatch("log_water", inp, user, today_log, db, "text",
                                user_message="what's my weight trend?")
    assert result.startswith("Already on the board:"), result
    assert today_log.total_water_ml == 250.0  # unchanged
