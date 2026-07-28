"""A turn that wrote nothing may not state a total.

Audit T-2, from the production transcript of 2026-07-28:

    Protein roll, 300 cal, 25g protein
    Total: 300 cal, 25g protein
        → ASK. nothing logged. no card.

The day was sitting near 800 cal, so "Total" was not the day. It was the batch
total of an item that never landed, printed as a fact, with no card to
contradict it.

Every guard that should have caught it was structurally unable to:

  PENDING_AS_COMMITTED   iterates `plan.pending_items`, which no clarify
                         builder populated — verified `()`. Its only producer
                         anywhere in the tree is `plan_from_resolution`, part
                         of the MealResolution chain that has no caller.
  _recites_card_facts    reads `facts_visible_in_card`, empty on a clarify.
  _claims_it_landed      needs a success verb near the name. A bare recital
                         has no verb.

So the fix is two-sided: give the existing guard something to iterate, and add
one that fires without a verb.
"""
import pytest

from core.food_response import (FoodItemSummary, FoodResponseIntent,
                                FoodResponsePlan, Reason, apply_policy,
                                held_items, plan_clarify, validate)


def _clarify(**kw):
    kw.setdefault("card_will_render", False)
    return plan_clarify(question="Was it a branded roll?",
                        unresolved=FoodItemSummary(name="protein roll"), **kw)


# ── the collection the guard reads is no longer empty ─────────────────────────

def test_the_held_item_is_visible_to_the_guard():
    """`unresolved_item` and `pending_items` describe the same food, and only
    one of them was ever populated — the one nothing checked.

    `held_items` reads whichever holds it. Note it does NOT copy into
    `pending_items`: that field is also what the deterministic fallback lists
    as the meal, so filling it made a held food read back as settled."""
    plan = _clarify()
    assert [i.name for i in held_items(plan)] == ["protein roll"]
    assert plan.pending_items == (), "the held item must not read as the meal"


def test_naming_the_held_food_is_not_a_claim_that_it_landed():
    """The verb check stays on the commit-side collections.

    Pointing it at a clarification's held item rejected the sentences the
    feature exists to produce: `_claims_it_landed` fires on ordinary phrasing
    near the name — "chicken 180 — about 380 all in" reads as landed because of
    the "in". Naming the held food is REQUIRED here, so that guard cannot see
    it.
    """
    assert validate(
        "Roll 300, bar 200 — about 500 all in. The roll is the guess: branded?",
        _clarify()).ok is True


def test_a_clarify_with_no_held_item_stays_empty():
    plan = plan_clarify(question="How much?", card_will_render=False)
    assert held_items(plan) == ()


# ── the defect itself ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Protein roll, 300 cal, 25g protein\nTotal: 300 cal, 25g protein. Branded?",
    "Protein roll — 300 cal|||Total — about 300 cal. Branded or homemade?",
])
def test_a_day_state_lookalike_is_refused_when_nothing_committed(text):
    """A line OPENING "Total:" is typographically the card's day-state row.
    On a turn that logged nothing it reads as a day they have not eaten."""
    result = validate(text, _clarify())
    assert result.ok is False
    assert result.reason == Reason.PENDING_AS_COMMITTED


@pytest.mark.parametrize("text", [
    "Protein roll — 300 cal, about 300 for the one of them. Branded?",
    "Roll 300, bar 200 — about 500 all in. Which brand was the roll?",
    "That totals about 300. Was it a branded roll?",
])
def test_a_spoken_roll_up_is_exactly_what_the_prompt_asks_for(text):
    """SHOW THE READING, THEN ASK (2d69d41) prices the items and sums them out
    loud, and `build_prompt` instructs it.

    A wider guard was tried and rejected the composer's own instructed output,
    so every clarification silently fell back to the deterministic renderer. A
    guard that fights the prompt turns the feature off instead of protecting
    it — these cases are the regression test for that.
    """
    assert validate(text, _clarify()).ok is True


# ── and what must keep working ────────────────────────────────────────────────

def test_stating_the_reading_before_asking_is_still_allowed():
    """SHOW THE READING, THEN ASK is the deliberate shape (2d69d41). The guard
    is about claiming a TOTAL, not about naming what we made of the food —
    otherwise the fix silently reverts a feature."""
    result = validate(
        "Protein roll, around 300 cal. Was it branded or from a bakery?",
        _clarify())
    assert result.ok is True


def test_an_ordinary_question_is_untouched():
    result = validate("Got the bar. Was the chicken closer to 100g or 200g?",
                      _clarify())
    assert result.ok is True


def test_a_commit_may_total_what_it_actually_wrote():
    """The scope of the guard. A turn that committed rows is entitled to sum
    them; the defect is a total over an empty set."""
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT,
        committed_items=(FoodItemSummary(name="protein roll",
                                         portion="1 roll"),),
        card_will_render=False))
    assert validate("Total: 210 cal for the meal.", plan).reason \
        != Reason.PENDING_AS_COMMITTED
