"""One typed clarification field, from four producers that disagree.

Measured 2026-08-04: four sites in `food_turn` produce the wire's `questions`
list in three shapes — plain dicts from `_questions_from_points`, the staged
pipeline's `ClarificationQuestion`, a literal dict, and the calorie-only
fallback. The typed one does not survive the trip: it is FLATTENED into loose
payload keys and RECONSTRUCTED on the answer turn, and `parse_prior_answer`
returns None the moment `response_schema` is absent.

`ClarificationField` holds the question AND its options on one object, which is
the property the step exists for. A question whose options are derived
separately can lose them, and did — prod 2026-08-03 shipped `options: []` on 39
of the last 40 asks, so iOS re-derived chips by parsing Arnie's own sentence.

SHADOW ONLY. Nothing here is on a write path, and these tests assert that the
live `resp.buttons` is untouched.
"""
import logging

import pytest

from core.semantics import ClarificationField, ClarificationOption
from skills.nutrition.clarification_adapter import (field_from_dict,
                                                    field_from_question,
                                                    fields_from_turn,
                                                    free_text_required,
                                                    missing_expected_options)


class _Q:
    """The staged pipeline's shape, structurally."""
    def __init__(self, **kw):
        self.__dict__.update(kw)


# ── every producer normalises to the same type ───────────────────────────────

def test_the_interpreter_branchs_dict():
    f = field_from_dict({"item": "Chicken", "text": "How was it cooked?",
                         "options": ["Grilled", "Baked"]})
    assert isinstance(f, ClarificationField)
    assert f.question == "How was it cooked?"
    assert [o.label for o in f.options] == ["Grilled", "Baked"]
    assert f.response_type == "single_select"


def test_the_staged_pipelines_typed_question():
    f = field_from_question(_Q(question_id="q_7", staged_item_id="item_3",
                               prompt="Which yogurt was it?",
                               response_schema="single_select",
                               options=(_Q(label="Greek", value="greek"),),
                               resolved_materiality=180.0))
    assert f.id == "q_7" and f.event_id == "item_3"
    assert f.materiality == 180.0
    assert f.options[0].label == "Greek" and f.options[0].value == "greek"


def test_the_two_option_shapes_both_read():
    """`ClarificationOption.value` and `AmbiguityOption.payload` are the same
    idea under two names, and neither is guaranteed present. That is the
    duplication this type replaces."""
    f = field_from_question(_Q(
        question_id="q", prompt="Which?",
        options=(_Q(label="A", value="a"),          # ClarificationOption
                 _Q(label="B", payload="b"),        # AmbiguityOption
                 "C")))                             # a bare string
    assert [(o.label, o.value) for o in f.options] == \
        [("A", "a"), ("B", "b"), ("C", None)]


def test_a_bare_string_option_still_sends_something():
    """Telegram and iMessage have no value channel — a reply keyboard sends the
    label. It must remain a usable answer."""
    f = field_from_dict({"item": "", "text": "Grilled or fried?",
                         "options": ["Grilled"]})
    assert f.options[0].send_value == "Grilled"


# ── the question and its options are ONE object ──────────────────────────────

def test_the_live_ask_produces_two_answerable_fields():
    """The 2026-08-04 turn, end to end through the real producer."""
    from core.food_turn import _questions_from_points

    qs = _questions_from_points(
        [{"label": "Chicken", "qs": ["How was the chicken cooked?"]},
         {"label": "Chicken", "qs": ["About how much chicken?"]}],
        message="Having some chicken and rice",
        items=[{"food": "Chicken", "amount": 6, "unit": "oz"}])
    fields = fields_from_turn({"action": "ask", "questions": qs})

    assert len(fields) == 2
    assert [f.attribute for f in fields] == ["preparation", "portion"]
    assert not missing_expected_options(fields), "every select must offer choices"
    # And each option belongs to ITS question, which is what a flat chip row
    # could not say when Arnie asked two things at once.
    for f in fields:
        assert all(o.field_id == f.id for o in f.options)


def test_free_text_is_not_the_same_as_broken():
    """RENAMED METRIC. `unanswerable` counted every optionless question as a
    defect, which would have overstated breakage in production and pushed
    toward generating chips for questions that should stay free text.

    "What restaurant was it from?" correctly requires typing. Only a field that
    PROMISES a choice and offers none is broken.
    """
    fields = fields_from_turn({"action": "ask", "questions": [
        {"item": "Soup", "text": "What kind of soup?", "options": []}]})
    assert len(free_text_required(fields)) == 1
    assert len(missing_expected_options(fields)) == 0, (
        "a question with no options was typed free_text, so it is not broken")

    # And the real defect: a select that offers nothing.
    from core.semantics import ClarificationField
    broken = (ClarificationField(id="q", event_id="i", attribute="identity",
                                 question="Which one?", options=(),
                                 response_type="single_select"),)
    assert len(missing_expected_options(broken)) == 1


def test_a_turn_that_asks_outside_the_structured_list_still_reports():
    """An ask whose question never reached `questions` is exactly the case that
    shipped no chips. It produces a field with no options rather than
    vanishing, so it is counted."""
    fields = fields_from_turn({"action": "ask", "questions": [],
                               "text": "Was that homemade?"})
    assert len(fields) == 1 and len(free_text_required(fields)) == 1


@pytest.mark.parametrize("sft", [
    {}, {"action": "log"}, {"action": "ask"}, None, "not a dict",
])
def test_a_non_asking_turn_yields_nothing(sft):
    assert fields_from_turn(sft) == ()


# ── shadow only ──────────────────────────────────────────────────────────────

def test_the_shadow_does_not_touch_the_response(caplog):
    """`resp.buttons` is already decided by the time this runs."""
    import core.conversation as CV
    from core.platform import Button, Response

    resp = Response.from_text("How was the chicken cooked?")
    resp.buttons = [Button(label="Grilled", group=0)]
    before = list(resp.buttons)

    with caplog.at_level(logging.INFO, logger="core.conversation"):
        CV._shadow_clarification_fields(
            {"action": "ask",
             "questions": [{"item": "Chicken", "text": "How was it cooked?",
                            "options": ["Grilled", "Baked"]}]}, resp)

    assert resp.buttons == before
    assert [r for r in caplog.records
            if "event=clarification_shadow" in r.getMessage()]


def test_the_shadow_reports_a_mismatch_between_typed_and_wire(caplog):
    """The measurement: typed options the wire did not carry. Prod shipped
    `options: []` on 39 of 40 asks while the questions themselves were fine."""
    import core.conversation as CV
    from core.platform import Response

    resp = Response.from_text("How was the chicken cooked?")
    resp.buttons = []
    with caplog.at_level(logging.INFO, logger="core.conversation"):
        CV._shadow_clarification_fields(
            {"action": "ask",
             "questions": [{"item": "Chicken", "text": "How was it cooked?",
                            "options": ["Grilled", "Baked"]}]}, resp)
    msg = [r.getMessage() for r in caplog.records
           if "event=clarification_shadow" in r.getMessage()][0]
    assert "MISMATCH" in msg and "typed=2" in msg and "wire=0" in msg
    assert "missing_expected=" in msg and "free_text=" in msg, (
        "the two metrics must be reported separately")


def test_the_shadow_never_costs_the_turn(monkeypatch):
    import core.conversation as CV
    monkeypatch.setattr(
        "skills.nutrition.clarification_adapter.fields_from_turn",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    CV._shadow_clarification_fields({"action": "ask", "questions": [{}]}, None)


def test_the_generated_id_is_marked_migration_only():
    """⚠ The shadow's field id is derived from list position and display text,
    so it changes when the interpreter reorders or renames — unusable for
    binding an answer across turns, which is the one job an id has.

    Pinned as a reminder rather than a behaviour: this must not become the
    production contract, and the durable form
    (`pending:item:attribute:revision`) arrives with the PendingOperation
    migration.
    """
    import inspect

    from skills.nutrition import clarification_adapter as CA

    # Whitespace-normalised: these phrases are line-wrapped in the source, and
    # a test that breaks on reflowing a docstring is a test nobody keeps.
    doc = " ".join((inspect.getdoc(CA.field_from_dict) or "").split())
    assert "MEASUREMENT-ONLY" in doc and "DELETION MILESTONE" in doc
    assert "pending_meal_id" in doc

    # The shape threads a pending id when one exists.
    f = CA.field_from_dict({"item": "Chicken", "text": "How?",
                            "options": ["A"]}, 0, pending_id="pm_9")
    assert f.id.startswith("pm_9:")


def test_attribute_inference_is_marked_backwards():
    """The adapter guesses the attribute by reading the RENDERED question,
    which is the direction the architecture reverses. Marked migration-only so
    the new type is not mistaken for a replacement of the prose-parsing it
    currently wraps."""
    import inspect

    from skills.nutrition import clarification_adapter as CA

    doc = " ".join((inspect.getdoc(CA._attribute_of) or "").split())
    assert "MIGRATION-ONLY" in doc and "DELETION MILESTONE" in doc
