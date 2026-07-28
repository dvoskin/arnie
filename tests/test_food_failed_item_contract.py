"""A failed item was not represented in the response plan at all.

From the directive's test list: "failed or pending commit does not show the
[success receipt]". The pending half was guarded. The failed half was not, and
could not be — because a failed item never reached the response layer.

`MealResolution` has carried four buckets all along, and says so:

    Renderers read `committed` for what to narrate as logged and `pending`
    for what to describe as waiting. Nothing in `pending` may be narrated as
    logged — that is enforced by them being different collections rather than
    one list with a flag someone forgets to check.

`plan_from_resolution` read two of them. `failed` went on the floor, so a
dropped item arrived at the composer as **nothing at all** — which inverted
both halves of the guarantee at once:

  • the false claim was LEGAL. `validate()` walked `plan.pending_items`
    looking for anything described as landed, and a failed item was in no
    bucket, so "Barebells bar is in." passed.
  • the honest mention was ILLEGAL. `approved_names` was built from the same
    three buckets, so naming the dropped bar counted as an INVENTED_ITEM.

That is the seam the Barebells bar came through on 2026-07-25. #34 gave the
drop an honest REASON; this makes the drop a fact the response contract knows
about, so nothing downstream can claim otherwise.
"""
import pytest

from core.food_response import (CARD_FACTS, FoodItemSummary,
                                FoodResponseIntent, FoodResponsePlan, Reason,
                                apply_policy, validate)

BAR = "Barebells bar"


def _committed(name="Cottage Cheese", sid="c1", entry_id=1):
    return FoodItemSummary(name=name, staged_item_id=sid)


def _failed(name, sid="s1"):
    return FoodItemSummary(name=name, staged_item_id=sid)


def _plan(*, committed=(), pending=(), failed=()):
    """Built directly rather than through `plan_from_resolution`, which was
    removed with the rest of the MealResolution chain — it had no production
    caller. The CONTRACT under test is live and unchanged: `failed_items` is
    its own bucket, and `validate()` refuses to let one be called committed."""
    intent = (FoodResponseIntent.PARTIAL_COMMIT if (pending and committed)
              else FoodResponseIntent.CLARIFY if pending
              else FoodResponseIntent.COMMIT)
    return apply_policy(FoodResponsePlan(
        intent=intent, committed_items=tuple(committed),
        pending_items=tuple(pending), failed_items=tuple(failed),
        unresolved_item=(pending[0] if pending else None),
        card_will_render=bool(committed),
        facts_visible_in_card=(CARD_FACTS if committed else frozenset())))


def _transcript_plan():
    """The shipped shape: cottage cheese and honey landed, the bar did not."""
    return _plan(
        committed=(_committed("Cottage Cheese", "c1", 1),
                   _committed("Honey", "c2", 2)),
        failed=(_failed(BAR),))


# ── 1. the plan carries the failure at all ───────────────────────────────────
def test_a_failed_item_reaches_the_response_plan():
    plan = _transcript_plan()
    assert [i.name for i in plan.failed_items] == [BAR]


def test_a_failed_item_is_not_in_the_committed_bucket():
    """The buckets are separate collections precisely so nothing has to
    remember to check a flag."""
    plan = _transcript_plan()
    assert BAR not in [i.name for i in plan.committed_items]
    assert BAR not in [i.name for i in plan.pending_items]


def test_a_failed_item_is_approved_for_mention():
    """The other half of the inversion: the honest sentence was being rejected
    as an invented food, because the dropped item was in no bucket."""
    plan = _transcript_plan()
    assert BAR.lower() in plan.approved_names


def test_a_failure_with_no_name_never_reaches_the_approved_vocabulary():
    """An unnamed failure would put an empty string in the approved vocabulary,
    and the empty string is a substring of every text — one nameless failure
    would make the invented-item guard pass anything.

    The guarantee used to live in `plan_from_resolution`, which filtered on the
    way in and was the only builder that did. It sits on `approved_names` now,
    where every caller gets it."""
    plan = _plan(committed=(_committed(),),
                 failed=(FoodItemSummary(name="", staged_item_id="s1"),))
    assert "" not in plan.approved_names


# ── 2. the false claim is now rejected ───────────────────────────────────────
@pytest.mark.parametrize("text", [
    "Barebells bar is in.",
    "The Barebells bar is added.",
    "Logged the Barebells bar.",
    "Added the Barebells bar.",
    "Got the Barebells bar counted.",
    "Cottage cheese and honey are in, and the Barebells bar is in too.",
])
def test_a_dropped_item_may_not_be_described_as_landed(text):
    result = validate(text, _transcript_plan())
    assert not result.ok
    assert result.reason == Reason.FAILED_AS_COMMITTED


def test_the_verb_in_front_is_caught_too():
    """"Logged the X" is the most natural way to say it, and the original
    forward-only window never looked there — so the pending guard had the same
    hole for as long as it existed."""
    plan = _plan(pending=(FoodItemSummary(name="peanut butter", staged_item_id="p1"),))
    assert validate("Logged the peanut butter.", plan).reason == \
        Reason.PENDING_AS_COMMITTED


# ── 3. the honest report stays expressible ───────────────────────────────────
@pytest.mark.parametrize("text", [
    # The shipped wording, with #34's real reason in place of the stale-board lie.
    "Couldn't get the Barebells bar in - it was already logged.",
    "The Barebells bar did not make it onto the log.",
    "The Barebells bar wasn't added.",
    "I didn't log the Barebells bar.",
    "The Barebells bar never landed.",
    "Everything else is in. The Barebells bar was blocked.",
])
def test_saying_what_actually_happened_is_allowed(text):
    """A guard that rejects the truth alongside the lie is worse than no guard:
    it pushes the composer to say nothing about the drop at all."""
    result = validate(text, _transcript_plan())
    assert result.ok, result.reason


def test_naming_the_dropped_item_without_a_verb_is_fine():
    assert validate("The Barebells bar needs another look.",
                    _transcript_plan()).ok


# ── 4. the guard is not so broad it fires on committed items ─────────────────
def test_a_committed_item_may_of_course_be_described_as_landed():
    """The check is scoped to the pending and failed buckets. A committed item
    being called committed is the entire point of the turn."""
    plan = _plan(committed=(_committed("Cottage Cheese"),))
    assert validate("Cottage cheese is in.", plan).ok


def test_a_clean_turn_has_no_failed_items():
    plan = _plan(committed=(_committed(),))
    assert plan.failed_items == ()


# ── 5. pending and failed are guarded alike but reported apart ───────────────
def test_the_two_states_report_different_reasons():
    """Both are "not in the day" and neither may be claimed, but a regeneration
    needs to know which state it got wrong."""
    pending_plan = _plan(committed=(_committed(),),
                         pending=(FoodItemSummary(name="peanut butter",
                                                  staged_item_id="p1"),))
    assert validate("Peanut butter is in.", pending_plan).reason == \
        Reason.PENDING_AS_COMMITTED
    assert validate(f"{BAR} is in.", _transcript_plan()).reason == \
        Reason.FAILED_AS_COMMITTED


def test_a_turn_that_committed_nothing_and_failed_something():
    """Deliberately pinned rather than changed. The intent taxonomy still calls
    this a COMMIT, which is wrong in name — but the drop is narrated by
    `core.food_ledger` from the executor's per-call outcomes, and re-routing the
    intent here would produce two notices for one failure. What matters for this
    change is that the item is now in the plan and cannot be claimed as logged.
    """
    plan = _plan(failed=(FoodItemSummary(name=BAR, staged_item_id="s1"),))
    assert [i.name for i in plan.failed_items] == [BAR]
    assert plan.committed_items == ()
    assert not validate(f"{BAR} is in.", plan).ok
