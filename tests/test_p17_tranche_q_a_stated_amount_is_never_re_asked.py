"""⛔⛔ P17 TRANCHE Q — A STATED AMOUNT IS NEVER RE-ASKED.

From production, 2026-08-20, build `76076b69aea5`, user 26:

    user   "I also had 100g of grilled chicken"
    item   {"food": "Grilled chicken breast", "amount": 100, "unit": "g",
            "basis": "estimate", ...}          <- the interpreter PARSED IT
    ask    "How much grilled chicken breast?"
    chips  6 oz (170.1 g)  ·  16 oz (435 g)    <- both from HISTORY
    logged 170.1 g / 281 kcal                  <- against a stated 100 g / 165

`_item_is_stated` short-circuits on the interpreter's `basis` declaration:
`basis == "estimate"` returns False BEFORE the deterministic "does the number
literally appear beside its unit in the clause naming this food" proxy is ever
consulted. So `stated_amount` stayed None, `QUANTITY_ALREADY_STATED` never
fired, and an ask opened whose option set could not express the answer the
user had already given.

⭐ THE FIX IS NARROWER THAN "LITERAL ALWAYS WINS", and the last test here is
why. The article branch (`f == 1.0` -> "a"/"an" beside the unit or the food)
is the WEAKEST evidence in the function, and the `basis` veto is what stops it
turning "a scoop of peanut butter" into a stated tablespoon — the shipped
190-calorie defect the code comments record. Strong literal evidence outranks
`basis`; the bare article does not.
"""
from __future__ import annotations

import pytest

from core.food_turn import _item_is_stated

#: The production case, verbatim.
CHICKEN_MESSAGE = "I also had 100g of grilled chicken"
CHICKEN_ITEM = {"food": "Grilled chicken breast", "amount": 100, "unit": "g",
                "calories": 165, "protein": 31, "carbs": 0, "fats": 4,
                "branded": False, "basis": "estimate",
                "entity_id": "food:grilled chicken breast"}


def test_the_exact_production_case_is_stated():
    """⛔ REQUIREMENT 1: the literal quantity in the message outranks the
    interpreter's `basis`. This is the turn that logged 170.1 g for a stated
    100 g."""
    assert _item_is_stated(dict(CHICKEN_ITEM), CHICKEN_MESSAGE) is True, (
        "the user typed '100g' and the interpreter carried amount=100 unit=g, "
        "yet basis='estimate' vetoed it before the literal proxy ran")


@pytest.mark.parametrize("basis", ["estimate", "regular", "", None])
def test_no_basis_label_can_veto_a_number_the_user_typed(basis):
    """The twin: whatever the interpreter declares, a number sitting beside
    its unit in the user's own clause is the user's own words. `regular` is
    included deliberately — it means WE supplied the amount from their
    regulars, which is a claim about provenance that a literal '100g' in the
    message simply refutes."""
    item = dict(CHICKEN_ITEM)
    if basis is None:
        item.pop("basis")
    else:
        item["basis"] = basis
    assert _item_is_stated(item, CHICKEN_MESSAGE) is True, (
        f"basis={basis!r} suppressed a literally-typed amount")


@pytest.mark.parametrize("message,amount,unit,food", [
    ("I also had 100g of grilled chicken", 100, "g", "Grilled chicken breast"),
    ("had 6oz of grilled chicken", 6, "oz", "Grilled chicken breast"),
    ("2 eggs this morning", 2, "egg", "Eggs"),
    ("250 ml of whole milk", 250, "ml", "Whole milk"),
])
def test_a_typed_amount_survives_basis_estimate(message, amount, unit, food):
    """The shape generalises past the one production message."""
    item = {"food": food, "amount": amount, "unit": unit, "basis": "estimate"}
    assert _item_is_stated(item, message) is True, (
        f"{amount}{unit} was typed in {message!r} and still read as inferred")


def test_the_bare_article_still_cannot_override_basis():
    """⛔⛔ THE GUARD ON THE FIX ITSELF. "A scoop of peanut butter" arriving
    as 1 tbsp matches the article branch, and treating that as stated is the
    shipped 190-calorie defect: an assumption presented as the user's own
    words. The `basis` veto is what stops it, so widening "literal outranks
    basis" to the WEAKEST evidence in the function would reintroduce the bug
    this fix is modelled on.

    A number the user typed is evidence. An indefinite article is not."""
    item = {"food": "Peanut butter", "amount": 1, "unit": "tbsp",
            "basis": "estimate"}
    assert _item_is_stated(item, "and a scoop of peanut butter") is False, (
        "the bare article overrode an explicit basis='estimate' — this is the "
        "190-calorie assumption reaching the user as their own statement")


def test_a_regular_supplied_amount_is_still_not_stated():
    """`regular` keeps its meaning when the message contains no such number:
    we supplied it, so it is not theirs."""
    item = {"food": "Barebells Salty Peanut Protein Bar", "amount": 1,
            "unit": "bar", "basis": "regular"}
    assert _item_is_stated(item, "Just had a barebell salty peanut bar") is False


def test_quantity_already_stated_declines_the_ask():
    """⛔ REQUIREMENT 2: with the amount stated, B-1's own predicate must
    decline — `QUANTITY_ALREADY_STATED`, not an ask. Driven through the real
    staging path so the test cannot pass on a hand-built item the pipeline
    would never produce."""
    from core.food_pipeline import stage_items
    from skills.nutrition.quantity_clarification import (Ineligible,
                                                         is_eligible)

    items, _ = stage_items({"items": [dict(CHICKEN_ITEM)]},
                           turn_id="t:tranche-q", message=CHICKEN_MESSAGE,
                           mode="strict")
    assert items, "staging produced no item"
    assert items[0].quantity.is_stated is True, (
        "the staged quantity did not carry the user's own 100 g — "
        f"stated_amount={items[0].quantity.stated_amount!r} "
        f"inferred_amount={items[0].quantity.inferred_amount!r}")

    class _Decision:
        staged_items = tuple(items)

    verdict = is_eligible(_Decision(), message=CHICKEN_MESSAGE,
                          client_capable=True, identity_evidence=True)
    assert verdict.reason is Ineligible.QUANTITY_ALREADY_STATED, (
        f"B-1 claimed a turn whose quantity the user had stated: {verdict.reason}")


# ═════ REQUIREMENT 3 — THE OFFER ITSELF REFUSES ════════════════════════════
#
# The net for the day requirement 1 fails again. It cannot ask "was this
# stated?" — that is the question that just got the wrong answer — so it asks
# a different one, on evidence still true in the failure: does this offer
# consist ENTIRELY of the user's own history while they supplied a measured
# amount none of the chips express?

def _option(grams, *, label, item, source):
    """An option that patches THIS item's own field. `UnresolvedField` refuses
    an option addressed elsewhere — the mixed-chip-row guard — so the field id
    has to be derived from the item exactly as the producer derives it."""
    from decimal import Decimal
    from core.semantics import (CanonicalQuantity, ClarificationOption,
                                Dimension, Provenance, SetQuantity)
    from skills.nutrition.quantity_clarification import event_id_for

    event = event_id_for(item)
    field_id = f"op:{event}:quantity:0"
    patch = SetQuantity(event_id=event, field_id=field_id,
                        provenance=Provenance.USER_SELECTED,
                        quantity=CanonicalQuantity(amount=Decimal(str(grams)),
                                                   unit_id="g",
                                                   dimension=Dimension.MASS))
    return ClarificationOption(label=label, option_id=f"opt_{label}",
                               field_id=field_id, patch=patch, source=source)


def _history_option(grams, *, label, item):
    from core.semantics import CandidateSource
    return _option(grams, label=label, item=item,
                   source=CandidateSource.USER_HISTORY)


def _ontology_option(grams, *, label, item):
    from core.semantics import CandidateSource
    return _option(grams, label=label, item=item,
                   source=CandidateSource.ONTOLOGY)


def _staged(message, item):
    from core.food_pipeline import stage_items
    items, _ = stage_items({"items": [dict(item)]}, turn_id="t:req3",
                           message=message, mode="strict")
    return items[0]


def test_a_history_only_offer_is_withheld_when_the_user_gave_a_measure():
    """⛔ REQUIREMENT 3, on the production option set verbatim: 6 oz and
    16 oz, both from history, against a typed 100 g."""
    from core.semantics import ResponseType
    from skills.nutrition.quantity_clarification import quantity_field

    item = _staged(CHICKEN_MESSAGE, CHICKEN_ITEM)
    field = quantity_field(operation_id="op", revision=0, item=item,
                           options=(_history_option(170.1, label="6 oz", item=item),
                                    _history_option(435.0, label="16 oz", item=item)))
    assert field.options == (), (
        "the ask still offered only history amounts against a typed 100 g")
    assert field.response_type is ResponseType.FREE_TEXT_FALLBACK, (
        "the question must stay askable — in words the user can answer")


def test_a_history_offer_that_CONTAINS_the_supplied_amount_is_kept():
    """The guard is about an offer that cannot express the answer, not about
    history as a source. Include the user's number and the chips stand."""
    from skills.nutrition.quantity_clarification import quantity_field

    item = _staged(CHICKEN_MESSAGE, CHICKEN_ITEM)
    field = quantity_field(operation_id="op", revision=0, item=item,
                           options=(_history_option(100.0, label="100 g", item=item),
                                    _history_option(170.1, label="6 oz", item=item)))
    assert len(field.options) == 2


def test_the_legitimate_vague_ask_is_untouched():
    """⛔⛔ THE GUARD MUST NOT SILENCE THE QUESTION B-1 EXISTS TO ASK. "A
    scoop of peanut butter" carries a COUNT, not a measured amount, so the
    offer stands however it was sourced — otherwise requirement 3 would delete
    the feature while protecting it."""
    from skills.nutrition.quantity_clarification import quantity_field

    item = _staged("and a scoop of peanut butter",
                   {"food": "Peanut butter", "amount": 1, "unit": "tbsp",
                    "basis": "estimate"})
    field = quantity_field(operation_id="op", revision=0, item=item,
                           options=(_history_option(16.0, label="1 tbsp", item=item),
                                    _history_option(32.0, label="2 tbsp", item=item)))
    assert len(field.options) == 2, (
        "a vague count-based ask lost its chips — the guard over-reached")


def test_ontology_options_are_not_withheld():
    """Danny's rule is about an offer made ENTIRELY of history. An ontology
    bracket is the calibrated answer to a genuinely open question."""
    from skills.nutrition.quantity_clarification import quantity_field

    item = _staged(CHICKEN_MESSAGE, CHICKEN_ITEM)
    field = quantity_field(operation_id="op", revision=0, item=item,
                           options=(_ontology_option(170.1, label="6 oz", item=item),
                                    _ontology_option(435.0, label="16 oz", item=item)))
    assert len(field.options) == 2


# ═════ THE LITERAL PATH MUST PROVE AMOUNT *AND* UNIT ═══════════════════════
#
# Review of PR #79 (Danny): moving the veto exposed a fallback that was never
# strong evidence at all —
#
#     if s in clause:            # s == "1"
#         return True            # matches the "1" inside "100g"
#
# Raw substring, no token boundary, no unit compatibility. The normalizer
# above it correctly REFUSES "100 g" as evidence for "1 tbsp"; this then
# accepted it anyway. Before the veto moved these were unreachable for
# basis="estimate", so the move is what exposed them: a guard relocation has
# to be judged on what it now lets through, not only on what it still stops.

@pytest.mark.parametrize("message,item,why", [
    ("I had 100g of peanut butter",
     {"food": "Peanut butter", "amount": 1, "unit": "tbsp"},
     "the '1' inside '100g' is not a stated tablespoon"),
    ("I had 21 almonds",
     {"food": "Almonds", "amount": 1, "unit": "cup"},
     "the '1' inside '21' is not a stated cup"),
    ("1 scoop of peanut butter",
     {"food": "Peanut butter", "amount": 1, "unit": "tbsp"},
     "they said scoop; we said tablespoon — the 190-calorie defect"),
    ("I had 250ml of milk",
     {"food": "Whole milk", "amount": 2, "unit": "cup"},
     "the '2' inside '250' is not two cups"),
])
def test_a_literal_match_needs_a_compatible_unit(message, item, why):
    """Amount alone is not evidence. The number has to be the user's own
    token AND wear a unit this item can be measured in."""
    payload = dict(item, basis="estimate")
    assert _item_is_stated(payload, message) is False, why


@pytest.mark.parametrize("message,item", [
    ("I also had 100g of grilled chicken",
     {"food": "Grilled chicken breast", "amount": 100, "unit": "g"}),
    ("had 6oz of grilled chicken",
     {"food": "Grilled chicken breast", "amount": 6, "unit": "oz"}),
    ("250 ml of whole milk", {"food": "Whole milk", "amount": 250, "unit": "ml"}),
    ("I had 2 tbsp of peanut butter",
     {"food": "Peanut butter", "amount": 2, "unit": "tbsp"}),
    ("2 tablespoons of peanut butter",
     {"food": "Peanut butter", "amount": 2, "unit": "tbsp"}),
])
def test_a_matching_unit_still_counts_as_stated(message, item):
    """The tightening must not cost the cases it exists to protect — including
    a unit the user spelled out in full."""
    assert _item_is_stated(dict(item, basis="estimate"), message) is True


def test_an_amount_with_no_unit_on_the_item_still_counts():
    """When the item carries no unit there is nothing for a unit to conflict
    with, and the number is still the user's own token."""
    assert _item_is_stated({"amount": 6.5}, "6.5 oz turkey") is True
    assert _item_is_stated({"amount": 2, "basis": "estimate"}, "2 tacos") is True
