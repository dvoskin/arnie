"""`interpreter_none` was one name for nine different things.

It is the most common escape from the structured lane, and the line reporting
it said only that the interpreter returned nothing. That is true of a model
timeout, an unparseable response, a message with no food in it, a refused
re-ask, and the deliberate writes-only hand-back — which is not a failure at
all but a SUCCESS (held food committed, reply handed to the conversational
brain) wearing a failure's name.

The cost was measured on 2026-08-04: the transcript had to be diagnosed by
reading source, because the only trace of the real cause — a refused re-ask at
`food_turn.py:4801` — was a line saying the interpreter returned nothing.

These pin that the reason is RECORDED, driven through the real function rather
than asserted against source text, so the taxonomy cannot quietly rot back into
a bare `return None`.
"""
import pytest

import core.food_turn as FT


def _user():
    from types import SimpleNamespace
    return SimpleNamespace(id=1, timezone="UTC", preferences=None)


@pytest.mark.asyncio
async def test_an_empty_message_says_so():
    assert await FT._run_untraced("   ", _user()) is None
    assert FT.decline_detail() == "empty_message"


@pytest.mark.asyncio
async def test_a_model_failure_is_not_a_parse_failure(monkeypatch):
    """Two operational problems with two different fixes. One name for both
    meant neither could be counted."""
    async def _boom(*a, **k):
        raise RuntimeError("upstream 500")

    monkeypatch.setattr(FT, "chat", _boom)
    assert await FT._run_untraced("had a burger", _user()) is None
    assert FT.decline_detail() == "model_error"


@pytest.mark.asyncio
async def test_a_timeout_is_named_as_one(monkeypatch):
    """Out of time is the reason latency work cares about, and it used to be
    invisible inside the same bucket as a 500.

    Told apart by TYPE, not by words in the message: `DeadlineExceeded`
    subclasses `TimeoutError`, so the hierarchy the deadline module already
    defines is what decides. The real class is used here rather than a
    look-alike, so this stays true if the message ever changes.
    """
    from core.deadline import DeadlineExceeded

    async def _slow(*a, **k):
        raise DeadlineExceeded("turn budget exhausted before the call started")

    monkeypatch.setattr(FT, "chat", _slow)
    assert await FT._run_untraced("had a burger", _user()) is None
    assert FT.decline_detail() == "timeout"


@pytest.mark.asyncio
async def test_an_unparseable_response_says_schema(monkeypatch):
    async def _junk(*a, **k):
        return {"text": "I'm not JSON at all."}

    monkeypatch.setattr(FT, "chat", _junk)
    assert await FT._run_untraced("had a burger", _user()) is None
    assert FT.decline_detail() == "schema_invalid"


@pytest.mark.asyncio
async def test_the_reason_is_cleared_per_turn(monkeypatch):
    """A reason left over from the previous turn on this task would be reported
    as this turn's, which is worse than reporting nothing. `run()` clears it."""
    FT._none("schema_invalid")
    assert FT.decline_detail() == "schema_invalid"

    async def _ok(*a, **k):
        return {"text": '{"action": "none"}'}

    monkeypatch.setattr(FT, "chat", _ok)
    await FT.run("hey", _user())
    assert FT.decline_detail() != "schema_invalid", (
        "a stale reason must not be attributed to a later turn")


def test_none_always_returns_none():
    """It is used in `return` position at every decline site; anything truthy
    would turn a decline into a plan."""
    for r in ("empty_message", "model_error", "", None):
        assert FT._none(r) is None
