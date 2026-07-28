"""The response contract authors the commit confirmation (review item 3).

It used to be two steps with a seam between them. `food_ledger.render_committed()`
wrote the whole reply — items, macros, day total, remaining — and
`strip_card_recitation()` then took back the parts the card was already showing.
Old copy generated first, imperfectly stripped second, and the plan, which knows
exactly which facts the card shows, had no say in what got written.

The trap in fixing it: the COMMIT plan had no text of its own. `fallback()`
returned `""` when a card renders and `"Got it."` otherwise, because the card was
assumed to be the confirmation. Routing the structured path at the plan as it
stood would have replaced every logged-food reply with "Got it." on Telegram,
which has no card frame — the surface where that sentence IS the confirmation.

So the authoring moved into the response layer rather than the plan being
pointed at what already existed. Same words out; one owner instead of two.
"""
import pytest

from core.food_ledger import build_snapshot
from core.food_response import (CARD_FACTS, FoodItemSummary,
                                FoodResponseIntent, FoodResponsePlan,
                                apply_policy, fallback)

SAY = ("Logged the bagel, {batch_cal} cal and {batch_protein}g protein. "
       "You're at {day_cal} with {cal_left} left.")


def _plan(*, card: bool, say: str = SAY, snapshot=True, **kw):
    calls = [{"input": {"food_name": "bagel", "calories": 280, "protein": 11}}]
    snap = build_snapshot(calls, 280, 11, 1240, 60, 2200, 150) if snapshot else None
    return apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT,
        committed_items=(FoodItemSummary(name="bagel"),),
        committed_snapshot=snap, model_say=say,
        card_will_render=card,
        facts_visible_in_card=(CARD_FACTS if card else frozenset()), **kw))


def test_a_surface_with_no_card_still_gets_its_confirmation():
    """Telegram has no card frame, so the sentence IS the confirmation. This is
    the regression that made a naive "just use the plan" fix unshippable — it
    would have said "Got it." and nothing else."""
    text = fallback(_plan(card=False))
    assert "280" in text and "11g" in text
    assert "960 left" in text
    assert text != "Got it."


def test_where_the_card_renders_the_card_owns_the_facts_but_not_the_subject():
    """The card owns the FIGURES. It does not own the fact that a message was
    heard.

    This asserted `== ""` and was measured shipping exactly that: on every iOS
    turn a card renders, so the deterministic floor for a logged meal was the
    empty string, and the composer — told by its own brief that the card
    confirms the entry — filled the gap with a mood. What the user got for
    logging salmon was "You've got solid room to work with."

    Suppress the numbers, keep the subject."""
    text = fallback(_plan(card=True))
    assert text == "Logged bagel."
    assert "280" not in text and "11g" not in text and "960" not in text


def test_the_composer_may_name_the_food_but_not_price_it():
    """Both halves of "suppress the numbers, keep the subject", checked at the
    gate the composer actually passes through."""
    from core.food_response import Reason, validate
    plan = _plan(card=True)
    assert validate("Bagel's in.", plan).ok
    assert validate("Bagel's in, 280 cal.",
                    plan).reason == Reason.CARD_DUPLICATION


def test_a_forward_looking_number_survives_on_either_surface():
    """"I'd aim for 30-40g at lunch" earns its digits; the card read aloud does
    not. The distinction is the whole point of the card-facts rule."""
    say = "Aim for 30-40g of protein at lunch."
    assert "30-40g" in fallback(_plan(card=True, say=say))


def test_a_failure_notice_is_never_suppressed_by_a_card():
    """A card cannot show an item that was not written, so nothing about the
    card makes the notice redundant. The Barebells bar vanished through this
    class of seam."""
    text = fallback(_plan(card=True, failure_notice=(
        "I couldn't log the Barebells bar — it didn't go through. "
        "Want me to try again?")))
    assert "Barebells" in text


def test_a_question_in_the_model_sentence_is_refused_as_before():
    """The say contract is unchanged — it just runs inside the response layer
    now instead of before it."""
    text = fallback(_plan(card=False, say="Logged it. Anything else?"))
    assert "Anything else?" not in text


def test_a_commit_with_no_snapshot_has_nothing_to_describe():
    """No snapshot, no write to describe — and COMMIT permits no text at all,
    on either surface, because the intent's policy was written on the
    assumption that the card is the confirmation.

    That assumption is exactly why this could not be fixed by pointing the
    structured path at the plan as it stood: the live path ALWAYS has a
    snapshot, and without one there was no text for any surface to fall back
    to. It is asserted here so the difference between "nothing to say" and
    "the confirmation" stays visible."""
    # No snapshot means no FIGURES to describe. It does not mean nothing
    # landed — the committed names are on the plan either way, and naming them
    # is what the reply owes. "Got it." named less than the plan already knew.
    assert fallback(_plan(card=False, snapshot=False)) == "Logged bagel."
    assert fallback(_plan(card=True, snapshot=False)) == "Logged bagel."
    # ...and with a snapshot, the no-card surface carries the numbers too.
    assert "280" in fallback(_plan(card=False))


def test_a_partial_commit_without_a_write_still_names_what_landed():
    """`_commit_text` answers "Got it." with no snapshot, which would have
    dropped the item names the user most needs to see."""
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.PARTIAL_COMMIT,
        committed_items=(FoodItemSummary(name="sandwich"),
                         FoodItemSummary(name="blueberries")),
        pending_items=(FoodItemSummary(name="shake"),),
        clarification_question="Was the shake Core Power or Elite?"))
    text = fallback(plan)
    assert "sandwich and blueberries in" in text
    assert "Core Power or Elite?" in text


# ── one owner ───────────────────────────────────────────────────────────────

def test_the_turn_does_not_strip_its_own_confirmation_after_writing_it():
    """The seam itself: two calls at the call site, the second correcting the
    first. One call now, and the correction is a consequence of the authoring
    rather than a pass over it."""
    import ast
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent
              / "core/conversation.py").read_text()
    tree = ast.parse(source)
    called = {n.func.attr if isinstance(n.func, ast.Attribute) else
              getattr(n.func, "id", "")
              for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "render_committed" not in called
    assert "strip_card_recitation" not in called


def test_the_response_layer_is_where_both_steps_live():
    import inspect
    from core.food_response import _commit_text
    source = inspect.getsource(_commit_text)
    assert "render_committed(" in source
    assert "strip_card_recitation(" in source
