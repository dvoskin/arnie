"""⛔⛔⛔ THE COMPOSER MUST BE TOLD WHAT THE QUESTION IS ABOUT.

`FoodResponsePlan` carried the question TEXT and thirty-odd context fields and
**not one structured subject**. The composer's instruction was:

    "ASK EXACTLY THIS (rephrasing for tone is fine): {question}"

True and intended — but with no subject stated alongside it, **a tone rephrase
and a SUBJECT CHANGE are indistinguishable**, and it made both. Measured
2026-08-28:

    c20  field=quantity  prompt="How much of the Trader Joe's Butter Chicken?"
         USER SAW:       "was that the full pouch or about half?"     <- CONSUMPTION
    c2   field=quantity  USER SAW: "did you finish both, or..."        <- CONSUMPTION

⭐ An answer parsed against `quantity` was answering a consumption question, and
nothing downstream could detect it. This is the failure of the one-line
prerequisite: *the thing Arnie structurally thinks it is asking == the thing
the user actually sees.*
"""
from __future__ import annotations

import core.food_response as FR
from core.food_response import FoodResponseIntent, FoodResponsePlan


def _plan(**kw):
    return FoodResponsePlan(intent=FoodResponseIntent.CLARIFY, **kw)


def test_the_plan_can_carry_a_structured_subject():
    p = _plan(clarification_question="How much?", clarification_subject=("quantity",))
    assert p.clarification_subject == ("quantity",)


def test_the_composer_prompt_PINS_the_subject():
    """⭐ THE REPAIR. The subject must reach the layer that writes the words."""
    txt = FR.build_prompt(_plan(
        clarification_question="How much of the Butter Chicken?",
        clarification_subject=("quantity",)))
    assert "ASK EXACTLY THIS" in txt
    assert "THE SUBJECT IS FIXED" in txt, (
        "the composer is not told the subject — a tone rephrase and a subject "
        "change are indistinguishable to it")
    assert "quantity" in txt.split("THE SUBJECT IS FIXED")[1][:200]


def test_the_pin_names_EVERY_field_not_just_the_first():
    txt = FR.build_prompt(_plan(
        clarification_question="Which one, and how much?",
        clarification_subject=("identity", "quantity")))
    seg = txt.split("THE SUBJECT IS FIXED")[1][:200]
    assert "identity" in seg and "quantity" in seg


def test_NO_pin_when_there_is_no_subject():
    """⚠ THE NEGATIVE CASE. Without this the test above passes against a pin
    that is emitted unconditionally, which would say `about ` and pin nothing."""
    txt = FR.build_prompt(_plan(clarification_question="How much?"))
    assert "ASK EXACTLY THIS" in txt
    assert "THE SUBJECT IS FIXED" not in txt, (
        "an empty subject must not produce a pin naming nothing")


def test_the_staged_builder_populates_the_subject_from_requested_fields():
    """The staged path's authority is `ClarificationQuestion.requested_fields`."""
    import inspect
    src = inspect.getsource(FR)
    i = src.index("clarification_question=question.prompt")
    seg = src[i:i + 300]
    assert "clarification_subject" in seg and "requested_fields" in seg, (
        "the staged plan builder does not carry the question's requested_fields")


def test_the_interpreter_builder_populates_the_subject_from_ambiguities():
    from core.food_turn import clarify_plan_from_points
    p = clarify_plan_from_points(
        [{"label": "Butter Chicken", "qs": ["how much?"]}], None,
        user_message="x", items=[{"food": "Butter Chicken"}],
        ambiguities=[{"item": "Butter Chicken", "field": "quantity"},
                     {"item": "Butter Chicken", "field": "prep"},
                     {"item": "Butter Chicken", "field": "quantity"}])
    assert p is not None
    # deduplicated, first-seen order, RAW producer names (provenance, not a
    # translation — a second mapping here would hide which producer spoke)
    assert p.clarification_subject == ("quantity", "prep"), p.clarification_subject


def test_the_subject_is_RAW_producer_fields_not_canonical_types():
    """⚠ Deliberate. Translating to canonical types here would put a SECOND
    mapping between the producer and the record, and the record would no longer
    say which producer spoke."""
    from skills.nutrition.ask_type import ALL
    from core.food_turn import clarify_plan_from_points
    p = clarify_plan_from_points(
        [{"label": "x", "qs": ["q"]}], None, user_message="m",
        items=[{"food": "x"}],
        ambiguities=[{"item": "x", "field": "consumed_fraction"}])
    assert p.clarification_subject == ("consumed_fraction",)
    assert "consumption_complete" not in p.clarification_subject
