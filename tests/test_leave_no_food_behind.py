"""Invariant: leave no food behind (universal, not flag-gated).

The prod bug: "150g turkey and a corn" → the corn was silently dropped when the
turkey triggered a clarification. Root: on an ask, only `ready` commits, so a
food the interpreter parsed into `items` but neither asked about nor marked ready
is lost. The interpreter's sorting isn't reliable enough to trust with data
integrity, so the PATH must not depend on it. These drive the real turn with a
mocked interpreter and assert nothing is lost.

RETARGETED TO THE EXCHANGE, 2026-08-03, and deliberately made harder rather
than easier. Two of these used to assert that the orphan appeared in the ASK
turn's `tool_calls` — the rescue as it was implemented then, an immediate
write. That is a claim about the MECHANISM, and it is the assertion that
blocked "an ask writes nothing": holding the write and stashing it is not the
same code path, but it is the same guarantee.

So they now assert the guarantee: the food exists, exactly once, when the
exchange is over — and the answer turn's interpreter is mocked to DROP it,
which is the failure the file is named for. This still fails against the
original bug (the corn is in neither turn), and it additionally fails against
a bug the single-turn version could not see: the ask writing the corn and the
answer turn writing it again. Weakening it to match an implementation is the
one thing this file exists to prevent; if a future change makes these pass by
losing a food, that change is wrong.

Cross-turn coverage in breadth lives in
tests/test_every_food_survives_the_clarification.py. These stay as the
narrow, adversarial cases.
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


def _written(*outs):
    """Every food written across the turns — a LIST, because "exactly once" is
    the assertion and a set is how a double-write hides."""
    return [str((c.get("input") or {}).get("food_name") or "").lower()
            for out in outs
            for c in ((out or {}).get("tool_calls") or [])
            if c.get("name") == "log_food"]


def _prior(ask, original):
    """The pending-question payload as core/conversation.py stashes it, through
    JSON — a stash that only survives in memory has not survived the turn."""
    return json.loads(json.dumps({
        "original": original, "question": (ask or {}).get("text") or "",
        "kind": "clarify", "ask_count": 1,
        "items": (ask or {}).get("items") or None,
        "staged_items": (ask or {}).get("staged_items") or [],
        "deferred_calls": (ask or {}).get("deferred_calls") or [],
        "staged_item_id": (ask or {}).get("staged_item_id") or "",
        "response_schema": (ask or {}).get("response_schema") or "",
        "log_date": ""}))


async def _answered(monkeypatch, ask, original, answer_payload, answer="150g"):
    """The second turn, with an interpreter that behaves as badly as the real
    one does — the premise of this whole file."""
    monkeypatch.setattr(FT, "chat", _fake_chat(answer_payload))
    return await FT.run(answer, _user(), prior=_prior(ask, original))


@pytest.mark.asyncio
async def test_co_item_in_items_not_ready_is_not_dropped(monkeypatch):
    # The corn shape: ask about Alpha, Bravo left in items (the interpreter's
    # mis-sort). Bravo must survive the exchange — and the answer turn here
    # forgets it completely, which is exactly what production did.
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "ask",
        "points": [{"label": "Alpha", "qs": ["how much?"]}],
        "items": [_item("Alpha"), _item("Bravo")]}))
    ask = await FT.run("alpha and bravo", _user())
    assert ask["action"] == "ask"
    reply = await _answered(monkeypatch, ask, "alpha and bravo",
                            {"action": "log", "items": [_item("Alpha")]})
    written = _written(ask, reply)
    assert written.count("bravo") == 1, f"lost or doubled: {written}"


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
async def test_ready_items_still_land(monkeypatch):
    # A settled food in `ready` reaches the board. On the ask if the switch is
    # on, on the answer if it is held — never neither, and never both.
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "ask",
        "points": [{"label": "Alpha", "qs": ["how much?"]}],
        "items": [_item("Alpha")], "ready": [_item("Bravo")]}))
    ask = await FT.run("alpha and bravo", _user())
    reply = await _answered(monkeypatch, ask, "alpha and bravo",
                            {"action": "log", "items": [_item("Alpha")]})
    written = _written(ask, reply)
    assert written.count("bravo") == 1, f"lost or doubled: {written}"


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
