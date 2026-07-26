"""Separating one entry into two is the intent a single operation cannot satisfy.

    You:   Can you separate the toast and cheese for me in my log.
    Arnie: Slice of cheese logged, 70 cal
    You:   And put the toast back
    Arnie: Toast's on the board, 80 cal

The composite was 175. After the split it was 70. After the user noticed the
missing half and repaired it themselves, 150. Twenty-five calories evaporated
and the audit was left to them.

The operation vocabulary CAN express this correctly — a mixed turn is
`[{op: update}, {op: log}]` — and the interpreter emitted only the update, so
one component was renamed and the other was never written. Nothing downstream
could tell, because a lone update that lowers a number is exactly what an
ordinary correction looks like.

Prompting harder is not the fix. The structural fact is that a plan of one
update cannot be a split, so it is incomplete by construction. Refusing it
keeps the log intact; committing it loses calories silently.
"""
import json
from types import SimpleNamespace

import pytest

import core.food_turn as FT
from core.food_turn import _asks_to_split


def _interp(payload):
    async def fake(messages, system, tools=True, max_tokens=0, model=None, **k):
        return {"text": json.dumps(payload), "raw_content": [],
                "tool_calls": []}
    return fake


_BOARD = [{"id": 42, "food": "White toast with American cheese",
           "qty": "1 slice", "cal": 175}]

#: What the interpreter actually produced: the cheese half only.
_LONE_UPDATE = {"action": "update", "updates": [
    {"entry_id": 42, "food_name": "American cheese", "amount": 1,
     "unit": "slice", "calories": 70, "protein": 4}],
    "say": "Separated."}

#: What it should produce: one entry becomes two, and the sum is preserved.
_COMPLETE_SPLIT = {"operations": [
    {"op": "update", "entry_id": 42, "food_name": "American cheese",
     "amount": 1, "unit": "slice", "calories": 70, "protein": 4},
    {"op": "log", "food": "White toast", "amount": 1, "unit": "slice",
     "calories": 105, "protein": 3}],
    "say": "Split them."}

_MSG = "Can you separate the toast and cheese for me in my log."


async def _turn(monkeypatch, payload, message=_MSG):
    monkeypatch.setattr(FT, "chat", _interp(payload))
    return await FT.run(message, SimpleNamespace(
        preferences=SimpleNamespace(food_logging_mode="moderate")),
        board=_BOARD)


# ── the intent ────────────────────────────────────────────────────────────────
def test_the_split_intents_are_recognised():
    for line in ("Can you separate the toast and cheese for me in my log.",
                 "split that into two", "break out the cheese",
                 "itemize that", "list them separately"):
        assert _asks_to_split(line), line


def test_an_ordinary_correction_is_not_a_split():
    for line in ("make it 2 tacos", "remove the fries",
                 "I had toast and cheese", "actually it was grilled"):
        assert not _asks_to_split(line), line


# ── the guard ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_lone_update_is_refused_rather_than_losing_calories(monkeypatch):
    out = await _turn(monkeypatch, _LONE_UPDATE)
    assert out["action"] == "ask", out
    assert "total stays right" in out["text"], out["text"]


@pytest.mark.asyncio
async def test_the_original_entry_is_left_alone(monkeypatch):
    """The whole point: the log must still be correct after we decline."""
    out = await _turn(monkeypatch, _LONE_UPDATE)
    assert not out.get("tool_calls"), out


@pytest.mark.asyncio
async def test_a_complete_split_goes_through(monkeypatch):
    out = await _turn(monkeypatch, _COMPLETE_SPLIT)
    assert out["action"] in ("commit", "log", "update"), out
    names = [c["input"].get("food_name") or c["input"].get("entry_id")
             for c in out["tool_calls"]]
    assert len(names) == 2, names


@pytest.mark.asyncio
async def test_a_complete_split_conserves_the_total(monkeypatch):
    """70 + 105 against the 175 it replaced."""
    out = await _turn(monkeypatch, _COMPLETE_SPLIT)
    total = sum(float(c["input"].get("calories") or 0)
                for c in out["tool_calls"])
    assert abs(total - 175) <= 5, total


@pytest.mark.asyncio
async def test_a_plain_correction_still_commits_as_one_update(monkeypatch):
    """The guard must not catch every update — only one asked to be a split."""
    out = await _turn(monkeypatch, _LONE_UPDATE, message="make it 2 slices")
    assert out["action"] != "ask", out
