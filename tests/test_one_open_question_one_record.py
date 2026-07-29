"""An open question is one record, and the record that asks can answer.

Two systems were tracking the same question. `sync_pending_questions` extracts
a hook from the reply and opens a `conversation_hook`, suppressed when a
logging tool fired — which is exactly false on the turn the food lane ASKS. So
the extractor read the lane's own question back out of its own reply and opened
a second pending for it, under a different kind, with its own lifecycle.

Production, 2026-07-28/29: the same text stored twice, seconds apart — 1962 and
1963 (47s), 1965 and 1966 (12s). The two then diverged:

  * `conversation_hook` re-asked on its own policy and produced the 13:00 "How
    many slices of that sopressata did you end up having?"
  * `food_structured_ask` 1965 stayed open 13.2 hours — its tier had no policy
    at all and fell to `casual`, 24 hours — and when the answer finally arrived
    it went to the lane that had been silent, carrying none of the thread the
    other had chased. That turn logged "Dollar pizza slices".

The chase was right and belonged to the wrong record. So: one record, owned by
the lane that can receive the answer, keeping the cadence that worked.
"""
from types import SimpleNamespace

from reminders.pending import TIER_POLICY, select_follow_up, should_follow_up


def _pending(tier, *, minutes_ago, kind="food_structured_ask",
             follow_ups=0, answered=False):
    from datetime import datetime, timedelta
    asked = datetime.utcnow() - timedelta(minutes=minutes_ago)
    return SimpleNamespace(
        kind=kind, tier=tier, asked_at=asked, last_asked_at=asked,
        follow_up_count=follow_ups,
        answered_at=datetime.utcnow() if answered else None,
        question="Was that a regular slice, or an extra-large one?")


# ── the food ask can now be chased ───────────────────────────────────────────

def test_a_food_question_has_a_follow_up_policy_of_its_own():
    """It had none, so it fell to `casual` — a full day before a first re-ask,
    while its duplicate chased at 25 minutes."""
    assert "food_clarification" in TIER_POLICY
    assert TIER_POLICY["food_clarification"].first_delay_h < 1.0


def test_a_food_question_is_followed_up_at_the_cadence_the_hook_used():
    pq = _pending("food_clarification", minutes_ago=40)
    assert should_follow_up(pq, mins_since_last_exchange=600) is True


def test_a_food_question_is_not_chased_immediately():
    pq = _pending("food_clarification", minutes_ago=5)
    assert should_follow_up(pq, mins_since_last_exchange=600) is False


def test_a_food_question_is_chased_once_and_then_left_alone():
    """`max_follow_ups=1`. Nagging about a portion is worse than an estimate."""
    pq = _pending("food_clarification", minutes_ago=600, follow_ups=1)
    assert should_follow_up(pq, mins_since_last_exchange=600) is False


def test_an_answered_food_question_is_never_chased():
    pq = _pending("food_clarification", minutes_ago=600, answered=True)
    assert should_follow_up(pq, mins_since_last_exchange=600) is False


# ── it outranks a generic hook ───────────────────────────────────────────────

def test_a_blocked_write_outranks_a_conversational_hook():
    """Answering it puts food on the board; the hook only continues a chat."""
    food = _pending("food_clarification", minutes_ago=60)
    hook = _pending("conversation_hook", minutes_ago=90, kind="conversation_hook")
    assert select_follow_up([hook, food], mins_since_last_exchange=600) is food


def test_an_unknown_tier_sorts_last_rather_than_mid_table():
    """The default was a hardcoded 3, which now collides with a real tier."""
    known = _pending("food_clarification", minutes_ago=60)
    unknown = _pending("something_new", minutes_ago=10_000)
    assert select_follow_up([unknown, known],
                            mins_since_last_exchange=600) is known


# ── the duplicate is not opened ──────────────────────────────────────────────

_STATS = dict(age=30, sex="male", height_cm=180.0)
_ASKING_REPLY = ("Junior's cheesecake, around 580 cal for a regular slice.\n\n"
                 "Was it a regular slice, or one of their extra-large ones?")


async def test_no_second_record_is_opened_for_a_question_the_food_lane_owns(
        make_user, db):
    """The turn the lane asks is the turn `had_logging_tool` is false, so the
    extractor fired on the lane's own question and stored it twice."""
    from core.food_turn import ASK_KIND
    from db.queries import (get_open_pending_questions,
                            record_pending_question)
    from reminders.lifecycle import sync_pending_questions

    u = await make_user(telegram_id="9101", **_STATS)
    await record_pending_question(db, u.id, kind=ASK_KIND,
                                  question="Regular slice, or extra-large?",
                                  tier="food_clarification")
    await sync_pending_questions(db, u, llm_reply_text=_ASKING_REPLY,
                                 source_type="ios", had_logging_tool=False)

    kinds = [q.kind for q in await get_open_pending_questions(db, u.id)]
    assert kinds.count("conversation_hook") == 0, (
        f"the food lane already owns this question; got {kinds}")
    assert kinds.count(ASK_KIND) == 1


async def test_an_ordinary_hook_is_still_opened_when_no_food_question_is_open(
        make_user, db):
    """The extractor is suppressed by the food lane, not disabled."""
    from db.queries import get_open_pending_questions
    from reminders.lifecycle import sync_pending_questions

    u = await make_user(telegram_id="9102", **_STATS)
    await sync_pending_questions(db, u, llm_reply_text=_ASKING_REPLY,
                                 source_type="ios", had_logging_tool=False)

    kinds = [q.kind for q in await get_open_pending_questions(db, u.id)]
    assert "conversation_hook" in kinds
