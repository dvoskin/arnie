"""A message must not wait forever behind the same person's previous turn.

`_coached_reply` held a per-identity `asyncio.Lock` with `async with lock` and
no timeout, while the turn budget is 60 s. A burst of messages therefore queued
one full turn each — measured against production: 12.8 s of server work
reported in the receipt, ~3 minutes on the phone, because the receipt times
`_run_turn` and cannot see the wait in FRONT of it.

The reply on timeout is a heads-up, not an error: nothing failed and nothing was
lost, their message just arrived mid-turn.
"""
import asyncio

import pytest

import api.chat as C


def test_the_wait_is_shorter_than_a_turn_budget():
    """22 s against a 60 s budget: a normal turn (3-13 s) never reaches it, and
    nobody waits a full minute to be told anything."""
    assert 5 <= C._LOCK_WAIT_S < 60


def test_the_heads_up_varies_but_is_stable_per_message():
    """Someone sending three things in a row should not get the same canned
    string three times — but a retry of the SAME message must not reword, or it
    reads as a different failure."""
    lines = {C._still_working_line(m) for m in
             ("a David bar", "2 eggs", "some pasta", "чай с молоком", "a shake")}
    assert len(lines) > 1
    assert C._still_working_line("a David bar") == C._still_working_line("a David bar")


def test_every_heads_up_reads_as_a_heads_up():
    """Not an apology and not a failure: these are the words that decide whether
    a user thinks their log was lost."""
    for line in C._STILL_WORKING:
        low = line.lower()
        assert "|||" in line, "should be two bubbles"
        assert not any(w in low for w in
                       ("error", "failed", "sorry", "went wrong", "confused"))


@pytest.mark.asyncio
async def test_a_held_lock_answers_instead_of_queueing(monkeypatch):
    """The behaviour under test: with the lock held, the caller gets a reply
    quickly rather than blocking for the holder's whole turn."""
    monkeypatch.setattr(C, "_LOCK_WAIT_S", 0.05)
    ident = "test-identity"
    lock = C._locks.setdefault(ident, asyncio.Lock())
    await lock.acquire()
    try:
        out = await asyncio.wait_for(
            C._coached_reply(ident, "just had a David bar", "text"), timeout=3)
    finally:
        lock.release()
        C._locks.pop(ident, None)
    assert out["bubbles"], "must still answer"
    assert out["tools"] == []
    assert any("still" in b.lower() or "hang on" in b.lower()
               or "one sec" in b.lower() or "beat" in b.lower()
               for b in out["bubbles"]), out["bubbles"]
