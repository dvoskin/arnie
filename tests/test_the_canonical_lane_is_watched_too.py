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


# ── Precision: a claim about a PRIOR meal is not a phantom ───────────────────

def test_a_reply_that_asks_is_not_claiming_to_have_logged():
    """The real false positive, 2026-08-06.

    "Already got chicken breast on the books at 718 cal. Now, salmon, how much
    did you have?" was flagged as a phantom log. It names a PRIOR meal and asks
    about the current one — honest reporting, and exactly what the assistant
    should be doing.

    SOLVED WITH FACTS, NOT MORE REGEX. Every phrasing rule that separates "I
    just logged it" from "that is already logged" is defeated by the next
    sentence someone writes; the turn's own action is not. A turn that ASKS has
    not claimed to log anything, whatever words it used to say so.
    """
    from core.turn_health import looks_like_phantom_log_claim as phantom

    reply = ("Already got chicken breast on the books at 718 cal, 89g protein. "
             "Now, salmon, how much did you have? Small fillet or bigger?")
    assert phantom("I had some salmon", reply, False), (
        "without the turn's facts this is indistinguishable from a phantom — "
        "which is the point: the text alone cannot settle it")
    assert not phantom("I had some salmon", reply, False, asked_this_turn=True)


def test_a_turn_that_wrote_is_never_a_phantom():
    """`wrote_this_turn` is the fact `has_tool_calls` was standing in for.

    The proxy is false on the canonical lane even for a successful commit, so
    a caller that knows what landed must say so rather than let the detector
    infer it from prose.
    """
    from core.turn_health import looks_like_phantom_log_claim as phantom

    claim = "Logged White rice, steamed, 64 cal, 1g protein."
    assert phantom("I had some rice", claim, False, wrote_this_turn=False)
    assert not phantom("I had some rice", claim, False, wrote_this_turn=True)


def test_the_original_data_loss_is_still_caught():
    """Precision must not cost coverage.

    The 2026-08-05 turns wrote nothing and asked nothing — they asserted a log
    that did not happen. That is the case this detector exists for, and no
    amount of false-positive tuning may quietly exclude it.
    """
    from core.turn_health import looks_like_phantom_log_claim as phantom

    for said in ("I had some rice", "Had some oatmeal"):
        assert phantom(said, "Logged White rice, steamed, 64 cal, 1g protein.",
                       False, wrote_this_turn=False, asked_this_turn=False), said


def test_a_failed_turn_that_claims_a_log_is_still_a_phantom():
    """The hole a broad `asked_this_turn` would have opened.

    `asked_this_turn` SUPPRESSES detection, so mapping it from "outcome is not
    applied" would have silenced the phantom check on CANCELLED, REFUSED and
    internal-failure turns — exactly the paths most likely to emit log-like
    copy without a write behind it. Of the four outcomes only REPAIR re-asks
    the field.

    So: nothing written, nothing asked, and a reply that says it logged.
    That must still fire, whatever went wrong upstream.
    """
    from core.turn_health import looks_like_phantom_log_claim as phantom

    assert phantom("I had some rice", "Logged White rice, 64 cal.", False,
                   wrote_this_turn=False, asked_this_turn=False), (
        "an internally-failed turn claiming a log was not flagged — this is "
        "the case the detector exists for")


def test_only_a_repair_counts_as_having_asked():
    """Pin the mapping against the enum, not against a string I remembered.

    `Outcome` has four members and exactly one of them produces a question.
    If a member is added later, this fails rather than silently widening the
    suppression.
    """
    from core.clarification_answer import Outcome

    asks = {o for o in Outcome
            if str(o.value) == "repair"}
    assert asks == {Outcome.REPAIR}, asks
    assert {o.value for o in Outcome} == {
        "applied", "cancelled", "repair", "refused"}, (
        "the outcome set changed — re-check which of them actually ask a "
        "question before trusting `asked_this_turn`")
