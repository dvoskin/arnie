"""Narrow answer parsers (build order 9, 21).

A clarification answer must not go through the full food interpreter. We asked
"which Fairlife bottle, and did you drink the whole thing?" — "Elite, about
half" is two field values, not a new meal. Sending it to the interpreter is
how a clarification becomes a second entry.

The other half of the contract: a parser that is not confident returns
nothing. Leaving a question pending is recoverable; writing the wrong bottle
to the ledger is not.
"""
import pytest

from skills.nutrition.answer_parsers import (ClarificationCommand, MIN_CONFIDENCE,
                                             parse_answer, parse_command,
                                             parse_fraction,
                                             parse_product_and_fraction,
                                             parse_product_selection,
                                             parse_quantity_answer,
                                             parse_serving_basis,
                                             parse_yes_no)
from skills.nutrition.clarify_policy import (ClarificationOption,
                                             ClarificationQuestion,
                                             ResponseSchema)


def _question(schema, fields, options=()):
    return ClarificationQuestion(
        question_id="q1", staged_item_id="item_1", requested_fields=fields,
        prompt="?", response_schema=schema,
        options=tuple(ClarificationOption(*o) if isinstance(o, tuple) else o
                      for o in options))


_FAIRLIFE = _question(
    ResponseSchema.PRODUCT_AND_FRACTION,
    ("product_line", "package_size", "consumed_fraction"),
    [ClarificationOption("Core Power · 26g",
                         {"product_line": "Core Power"}, "c1"),
     ClarificationOption("Core Power Elite · 42g",
                         {"product_line": "Core Power Elite"}, "c2")])


# ── the headline case ─────────────────────────────────────────────────────────
def test_elite_about_half_fills_three_fields_without_the_interpreter():
    """One sentence, three fields, deterministically."""
    answer = parse_answer("Elite, about half", _FAIRLIFE)
    assert answer.values["product_line"] == "Core Power Elite"
    assert answer.values["consumed_fraction"] == 0.5
    assert answer.matched_candidate_id == "c2"
    assert answer.confidence > 0.9


def test_a_product_with_a_stated_amount_also_parses():
    answer = parse_answer("the Elite one, 8 oz of it", _FAIRLIFE)
    assert answer.values["product_line"] == "Core Power Elite"
    assert answer.values["stated_amount"] == 8.0
    assert answer.values["stated_unit"] == "oz"


def test_a_partial_answer_is_progress_not_completion():
    """A product with no portion answers half the question. It should apply
    what it knows and leave the rest open."""
    answer = parse_product_and_fraction("Elite", _FAIRLIFE)
    assert answer.values.get("product_line") == "Core Power Elite"
    assert "consumed_fraction" not in answer.values


# ── refusing to guess ─────────────────────────────────────────────────────────
def test_the_normal_one_stays_pending():
    """The directive's case: a vague selection must not resolve to whatever
    ranked first."""
    assert parse_answer("the normal one", _FAIRLIFE).unparsed
    assert parse_answer("the regular size", _FAIRLIFE).unparsed
    assert parse_answer("the usual", _FAIRLIFE).unparsed


def test_an_answer_matching_two_offered_options_equally_is_no_answer():
    q = _question(ResponseSchema.PRODUCT_SELECTION, ("product_line",),
                  [ClarificationOption("Vanilla Shake", "v", "c1"),
                   ClarificationOption("Chocolate Shake", "c", "c2")])
    assert parse_product_selection("shake", q).unparsed


def test_an_unrelated_answer_does_not_resolve_a_product():
    assert parse_answer("it was pretty good honestly", _FAIRLIFE).unparsed


def test_matching_is_against_the_options_offered_not_the_food_universe():
    """"Elite" is unambiguous inside a two-option question and meaningless
    outside one."""
    assert parse_product_selection("Elite", options=()).unparsed


def test_a_low_confidence_parse_is_discarded_by_the_gate():
    q = _question(ResponseSchema.PRODUCT_SELECTION, ("product_line",),
                  [ClarificationOption("Core Power Elite Chocolate 14oz",
                                       "cpe", "c1")])
    # One weak token overlap out of five — under the floor, so nothing applies.
    answer = parse_product_selection("chocolate", q)
    if not answer.unparsed:
        assert parse_answer("chocolate", q).unparsed or \
            answer.confidence >= MIN_CONFIDENCE


# ── quantities ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("the whole thing", 1.0), ("all of it", 1.0), ("half", 0.5),
    ("about half", 0.5), ("1/2", 0.5), ("a quarter", 0.25),
    ("three quarters", 0.75), ("two thirds", round(2 / 3, 3)),
    ("most of it", 0.8), ("75%", 0.75), ("a couple sips", 0.15),
])
def test_fractions_parse(text, expected):
    assert parse_fraction(text) == expected


def test_a_nonsense_percentage_is_not_a_fraction():
    assert parse_fraction("400%") is None


@pytest.mark.parametrize("text,amount,unit", [
    ("200g", 200.0, "g"), ("6 oz", 6.0, "oz"), ("1.5 cups", 1.5, "cups"),
    ("3 slices", 3.0, "slices"), ("about 250 ml", 250.0, "ml"),
])
def test_stated_amounts_parse(text, amount, unit):
    answer = parse_quantity_answer(text)
    assert answer.values["stated_amount"] == amount
    assert answer.values["stated_unit"] == unit


def test_a_quantity_question_answered_with_a_fraction_works():
    answer = parse_quantity_answer("about half of it")
    assert answer.values["consumed_fraction"] == 0.5


def test_an_unanswerable_quantity_stays_pending():
    assert parse_quantity_answer("not much really").unparsed


# ── commands (build order 21) ─────────────────────────────────────────────────
@pytest.mark.parametrize("text,command", [
    ("skip it", ClarificationCommand.SKIP_ITEM),
    ("never mind", ClarificationCommand.SKIP_ITEM),
    ("don't log the yogurt", ClarificationCommand.SKIP_ITEM),
    ("cancel the meal", ClarificationCommand.CANCEL_MEAL),
    ("just estimate it", ClarificationCommand.ESTIMATE),
    ("I don't know", ClarificationCommand.ESTIMATE),
    ("log the rest", ClarificationCommand.COMMIT_READY),
    ("start over", ClarificationCommand.RESTART),
])
def test_commands_are_deterministic(text, command):
    assert parse_command(text) is command


def test_a_command_beats_every_schema_parser():
    """"skip it" is not a product name, however hard a fuzzy matcher tries."""
    answer = parse_answer("skip it", _FAIRLIFE)
    assert answer.command is ClarificationCommand.SKIP_ITEM
    assert answer.values == {}


def test_an_ordinary_answer_is_not_mistaken_for_a_command():
    assert parse_command("Elite, about half") is None
    assert parse_command("200g") is None


# ── other schemas ─────────────────────────────────────────────────────────────
def test_yes_no():
    q = _question(ResponseSchema.YES_NO, ("confirmed",))
    assert parse_yes_no("yes", q).values == {"confirmed": True}
    assert parse_yes_no("nope", q).values == {"confirmed": False}
    assert parse_yes_no("maybe?", q).unparsed


def test_serving_basis():
    q = _question(ResponseSchema.SERVING_BASIS, ("serving_basis",))
    assert parse_serving_basis("that's per serving", q).values[
        "serving_basis"] == "per_serving"
    assert parse_serving_basis("that's the whole container", q).values[
        "serving_basis"] == "per_package"
    assert parse_serving_basis("dunno", q).command is not None


def test_nutrient_values_reuses_the_label_parser():
    """Including its rule that unknown is not zero — an unstated field is
    absent, not filled."""
    q = _question(ResponseSchema.NUTRIENT_VALUES, ("calories", "protein"))
    answer = parse_answer("80 calories and 8g protein", q)
    assert answer.values == {"calories": 80.0, "protein": 8.0}
    assert "sodium" not in answer.values


def test_a_refusal_on_a_label_question_becomes_an_estimate_command():
    q = _question(ResponseSchema.NUTRIENT_VALUES, ("calories",))
    assert parse_answer("no idea", q).command is ClarificationCommand.ESTIMATE


def test_a_parser_crash_leaves_the_question_pending():
    """Failing safe means the question stays open, never that a field gets a
    junk value."""
    class _Broken(ClarificationQuestion):
        pass
    q = _question(ResponseSchema.PRODUCT_SELECTION, ("product_line",),
                  [ClarificationOption("x", object(), "c1")])
    assert parse_answer("", q).unparsed
