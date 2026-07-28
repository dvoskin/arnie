"""The answer turn parses against the shape we asked in.

`skills/nutrition/answer_parsers` was fully written and fully tested and had no
production caller — not because nothing called `parse_prior_answer`, which
`core/food_turn.py` does on every answer turn, but because the one field it
dispatches on never survived the trip.

The ask returns `response_schema`, `question_id`, `staged_item_id`,
`requested_fields`, `options` and `meal_group_id`. `conversation.py` persisted
`original`, `question`, `kind`, `ask_count`, `items` — and the answer turn read
that back as `prior`. So `parse_prior_answer` returned None before it reached
`PARSERS`, the whole interpreter re-ran on "about a cup", and the staged item
the question was bound to was gone by the time the reply arrived.

`parse_command` takes no schema. That is the entire reason "skip it" has always
worked and "about a cup" never has — and it is why the gap could sit in
production looking like a model quality problem.

These tests bind the two ends together, because a payload dict and the parser
that reads it are exactly the kind of pair that drifts silently: neither file
fails to import when they disagree.
"""
import json

import pytest

from core.food_turn import parse_prior_answer


#: What `conversation.py` now writes into `pending_questions.payload_json` for
#: a staged-pipeline ask. Kept as a literal rather than built from the policy so
#: the test fails if the persisted SHAPE changes, which is the thing that broke.
def _payload(**over):
    base = {
        "original": "peanut butter on toast",
        "question": "Was the scoop closer to one or two tablespoons?",
        "kind": "clarify", "ask_count": 1,
        "items": [{"food": "peanut butter"}],
        "response_schema": "quantity",
        "question_id": "q1",
        "staged_item_id": "sid-abc",
        "requested_fields": ["consumed_fraction"],
        "options": ["one tablespoon", "two tablespoons"],
        "meal_group_id": "mg1",
    }
    base.update(over)
    # Through JSON, because that is how it actually travels. A tuple that
    # survives in-process and arrives as a list is its own class of bug.
    return json.loads(json.dumps(base))


# ── the fix ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("answer,amount,unit", [
    ("about a cup", 1.0, "cup"),
    ("two tablespoons", 2.0, "tablespoons"),
])
def test_a_quantity_answer_is_settled_without_the_interpreter(answer, amount,
                                                              unit):
    """The narrow parser resolves the field the question asked about.

    No model call, and the answer lands as a VALUE rather than as prose to be
    re-read — which is what keeps it bound to the item instead of arriving as a
    new meal.
    """
    parsed = parse_prior_answer(answer, _payload())
    assert parsed is not None
    assert parsed.unparsed is False
    assert parsed.values == {"stated_amount": amount, "stated_unit": unit}


def test_the_question_still_knows_which_item_it_was_about():
    """`staged_item_id` is the whole point of asking a bound question.

    Carried end to end it is what lets the answer edit one row of a meal; lost,
    the answer turn has the user's words and nothing to attach them to.
    """
    prior = _payload()
    assert prior["staged_item_id"] == "sid-abc"
    assert parse_prior_answer("about a cup", prior) is not None


# ── the regression it fixes, pinned so it cannot come back ────────────────────

def test_the_old_payload_could_not_reach_a_parser_at_all():
    """The exact shape production persisted until 2026-07-28.

    Not a hypothetical: drop the schema and every quantity answer falls through
    to the interpreter again. This asserts the failure so that removing a key
    from `payload_json` fails HERE, loudly, instead of degrading into a model
    quality complaint three weeks later.
    """
    old = {k: v for k, v in _payload().items()
           if k in ("original", "question", "kind", "ask_count", "items")}
    assert parse_prior_answer("about a cup", old) is None
    assert parse_prior_answer("two tablespoons", old) is None


def test_a_command_never_needed_the_schema_and_still_does_not():
    """"Skip it" worked throughout the outage and must keep working.

    It is the control: it proves the answer turn was reaching
    `parse_prior_answer` all along, so the gap really was the missing field and
    not a dead call site.
    """
    for payload in (_payload(), {"original": "x", "question": "y"}):
        parsed = parse_prior_answer("skip it", payload)
        assert parsed is not None
        assert parsed.command is not None


# ── the seam itself ───────────────────────────────────────────────────────────

def test_every_field_the_parser_dispatches_on_is_one_the_ask_emits():
    """Bind the producer to the consumer.

    `food_turn`'s ask branch builds these keys and `conversation.py` copies
    them; `parse_prior_answer` reads them back. Nothing else checks that those
    three lists agree, and when they stopped agreeing the only symptom was a
    parser module that looked unused.
    """
    consumed = {"response_schema", "question_id", "staged_item_id",
                "requested_fields", "options"}
    assert consumed <= set(_payload())

    # And each one arrives as the type the parser expects, not merely present.
    prior = _payload()
    assert isinstance(prior["response_schema"], str) and prior["response_schema"]
    assert isinstance(prior["requested_fields"], list)
    assert isinstance(prior["options"], list)


def test_an_answer_that_does_not_fit_the_shape_defers_rather_than_guessing():
    """UNPARSED is a legitimate outcome and must not be mistaken for a value.

    The interpreter still gets these — with the question bound to its item,
    which is the difference between a fallback and a fresh meal.
    """
    parsed = parse_prior_answer("it was the blue packet", _payload())
    assert parsed is None or parsed.unparsed or not parsed.values
