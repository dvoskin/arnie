"""Invariant: leave no food behind (universal, not flag-gated).

The prod bug: "150g turkey and a corn" → the corn was silently dropped when the
turkey triggered a clarification. Root: on an ask, only `ready` commits, so a
food the interpreter parsed into `items` but neither asked about nor marked ready
is lost. The interpreter's sorting isn't reliable enough to trust with data
integrity, so the PATH commits any such orphan rather than dropping it. These
drive the real turn with a mocked interpreter and assert nothing is lost.
"""
import json
import pytest
from types import SimpleNamespace

import core.food_turn as FT


def _fake_chat(payload):
    async def fc(messages, system, tools=True, max_tokens=0, model=None, **k):
        return {"text": json.dumps(payload), "raw_content": [], "tool_calls": []}
    return fc


def _user():
    return SimpleNamespace(preferences=SimpleNamespace(food_logging_mode="moderate"))


def _item(food, cal=100):
    return {"food": food, "amount": 1, "unit": "", "calories": cal,
            "protein": 5, "carbs": 10, "fats": 3}


def _committed(out):
    return {str(c["input"]["food_name"]).lower() for c in (out.get("tool_calls") or [])}


@pytest.mark.asyncio
async def test_co_item_in_items_not_ready_is_committed_not_dropped(monkeypatch):
    # The corn shape: ask about Alpha, Bravo left in items (the interpreter's
    # mis-sort). Bravo must survive.
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "ask",
        "points": [{"label": "Alpha", "qs": ["how much?"]}],
        "items": [_item("Alpha"), _item("Bravo")]}))
    out = await FT.run("alpha and bravo", _user())
    assert out["action"] == "ask"
    assert "bravo" in _committed(out)          # rescued, not dropped


@pytest.mark.asyncio
async def test_the_asked_item_still_waits(monkeypatch):
    # Alpha is what we're asking about (in points AND items) — it must NOT be
    # committed by the orphan rescue; it waits for the answer.
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "ask",
        "points": [{"label": "Alpha", "qs": ["how much?"]}],
        "items": [_item("Alpha"), _item("Bravo")]}))
    out = await FT.run("alpha and bravo", _user())
    assert "alpha" not in _committed(out)


@pytest.mark.asyncio
async def test_ready_items_still_commit(monkeypatch):
    # Unchanged behaviour: a settled food in `ready` commits.
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "ask",
        "points": [{"label": "Alpha", "qs": ["how much?"]}],
        "items": [_item("Alpha")], "ready": [_item("Bravo")]}))
    assert "bravo" in _committed(await FT.run("alpha and bravo", _user()))


@pytest.mark.asyncio
async def test_orphan_without_calories_is_not_written(monkeypatch):
    # A name with no number can't be logged — it is surfaced (logged), not
    # written as a phantom row. (It must also not crash the turn.)
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "ask",
        "points": [{"label": "Alpha", "qs": ["how much?"]}],
        "items": [_item("Alpha"), {"food": "Bravo"}]}))
    out = await FT.run("alpha and bravo", _user())
    assert out["action"] == "ask"
    assert "bravo" not in _committed(out)      # not a phantom row
