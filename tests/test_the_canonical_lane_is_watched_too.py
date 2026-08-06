"""EVERY LANE MUST PASS UNDER THE SAME SAFETY NETS.

MEASURED 2026-08-06. `phantom_log_claim` — the detector for "claimed to log,
logged nothing" — showed `flags=None` on both turns of the 2026-08-05 data
loss, and it fires correctly when called directly with those exact strings:

    looks_like_phantom_log_claim(
        "I had some rice",
        "Logged White rice, steamed, 64 cal, 1g protein.", False) -> True

It was never called. The canonical answer branch returns a `TurnResult` about
three thousand lines above `detect_turn_flags`, so turn health ran on ZERO
canonical turns. Not a tuning problem — no coverage at all, and every future
canonical lane inherits the same blind spot by construction.

The general shape, and why this file is not a one-line assertion: a new path
that returns early silently opts out of every cross-cutting check the old path
happens to flow through. Nothing fails; the checks simply stop applying to the
traffic that matters most, which is the new traffic.
"""
import pytest

from tests.test_a_full_day_of_food import (  # noqa: F401
    app_db, edges, seeded, rows, item,
)
from tests.test_a_conversation_across_turns import (  # noqa: F401
    CAPABLE, b1_live, say, operations, B1_ELIGIBLE,
)


@pytest.mark.asyncio
async def test_a_canonical_answer_turn_runs_turn_health(edges, b1_live, app_db):
    """The turn must come back having been LOOKED AT.

    `health_flags` being empty is the correct outcome for a healthy turn — so
    this asserts the machinery ran rather than asserting a particular flag,
    which is the difference between "we checked and it was fine" and "we never
    checked". Those were indistinguishable for the whole life of this lane.
    """
    from core import conversation

    seen = {}
    real = conversation.detect_turn_flags

    def _spy(**kw):
        seen.update(kw)
        return real(**kw)

    conversation.detect_turn_flags = _spy
    try:
        edges.plans.append(B1_ELIGIBLE)
        await say(b1_live, "I had some chicken breast")
        seen.clear()                       # the ASK turn is not what we assert
        await say(b1_live, "6 oz")         # the ANSWER turn is
    finally:
        conversation.detect_turn_flags = real

    assert seen, (
        "the canonical answer turn returned without turn health ever being "
        "called — the detector cannot fire on a lane it never sees")
    assert "response_text" in seen and seen["response_text"], seen


@pytest.mark.asyncio
async def test_a_committed_answer_is_not_reported_as_a_phantom(
        edges, b1_live, app_db):
    """The truth, not the proxy.

    The legacy call passes `has_tool_calls` as a stand-in for "a write
    happened". On this lane that proxy is simply false — the canonical path
    commits without the model firing a tool — so passing it would flag every
    successful commit as a phantom log and make the signal useless the moment
    anyone looked at it. `entry_id` is the fact the proxy was standing in for.
    """
    from core import conversation

    captured = {}
    real = conversation.detect_turn_flags

    def _spy(**kw):
        captured.update(kw)
        return real(**kw)

    conversation.detect_turn_flags = _spy
    try:
        edges.plans.append(B1_ELIGIBLE)
        await say(b1_live, "I had some chicken breast")
        result = await say(b1_live, "6 oz")
    finally:
        conversation.detect_turn_flags = real

    board = await rows(b1_live)
    assert len(board) == 1, "the answer did not commit; this asserts the wrong thing"
    assert captured.get("has_tool_calls") is True, (
        "a committed canonical turn reported no write, so every successful "
        "commit would be flagged as a phantom log")
    assert "phantom_log_claim" not in (result.health_flags or []), (
        f"a turn that really committed was flagged as a phantom: "
        f"{result.health_flags}")
