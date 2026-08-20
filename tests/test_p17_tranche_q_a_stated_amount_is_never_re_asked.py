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


# ══════════════════════════════════════════════════════════════════════════
# ROUND 2 — WHAT THE EVAL BATTERY CAUGHT THAT THE UNIT SUITE DID NOT
#
# The battery case "a unit that does not fix a size is asked about"
# ("had a bowl of white rice and two fried eggs", expect=ask) went flaky on
# PR #79. Two of its three reps died on an unrelated API-billing error, but
# probing the case deterministically found a REAL regression underneath, in
# both directions at once.
#
# ⛔⛔ THE ARTICLE GOT PROMOTED TO STRONG EVIDENCE. `normalize_quantity`
# reports `user_stated_amount=1` for "a bowl of white rice" — it cannot tell
# a number the user TYPED from one an indefinite article IMPLIES, and it was
# never asked to. Moving the `basis` veto below the normalizer handed that
# conflation the authority the veto used to withhold: measured at
# 41297ca, `{"unit": "bowl", "basis": "estimate"}` returned True where
# deployed main (76076b6) returned False.
#
# That is the SAME defect class as the raw-substring fallback caught in
# review — a bare article overruling an explicit `basis="estimate"` — simply
# arriving through the door next to it. ⭐ A GUARD THAT MOVES MUST BE JUDGED
# AGAINST EVERY PATH IT NOW SITS BELOW, not just the one that prompted it.
#
# The existing bare-article guard did not catch it because its item is
# `1 tbsp` — a MEASURED unit, where the unit check vetoes independently.
# Only a unit that carries no measure ("bowl") leaves the article alone with
# the decision. So the guard was real, and its single fixture was load-
# bearing in a way nothing had stated.
# ══════════════════════════════════════════════════════════════════════════

BOWL_MESSAGE = "had a bowl of white rice and two fried eggs"


@pytest.mark.parametrize("basis", ["estimate", "regular"])
def test_an_article_beside_an_unmeasured_unit_is_not_a_stated_amount(basis):
    """⛔⛔ THE REGRESSION. "A bowl" is one bowl, but the user never counted
    it — and a bowl is not a size. Reading it as stated suppresses the very
    question this message exists to provoke.

    The normalizer's `user_stated_amount` answers "what amount does this
    phrase denote", NOT "did the user write one". Only the second question
    can outrank `basis`."""
    item = {"food": "White rice", "amount": 1, "unit": "bowl", "basis": basis}
    assert _item_is_stated(item, BOWL_MESSAGE) is False, (
        "an indefinite article overrode an explicit basis=%r — the ask that "
        "settles an unfixed unit never opens" % basis)


def test_the_article_still_stands_when_the_interpreter_declares_nothing():
    """The fix must not overshoot into the case it never governed. With no
    `basis` to weigh it against, the article remains what it always was: the
    weakest evidence, but the only evidence there is. Deployed main returned
    True here and must continue to."""
    item = {"food": "White rice", "amount": 1, "unit": "bowl"}
    assert _item_is_stated(item, BOWL_MESSAGE) is True


def test_a_spelled_count_outranks_basis_like_a_digit_does(basis="estimate"):
    """⛔ THE OTHER HALF OF REQUIREMENT 1. "two fried eggs" is a literal
    quantity the user typed; `basis="estimate"` was overruling it, exactly as
    `100g` was. The tranche is named for the rule that a declaration loses to
    the message — a rule that cannot be spelled digits-only.

    It fails today for a reason worth recording: the normalizer returns
    `user_stated_unit="fried"`, grabbing the adjective sitting where a unit
    usually sits. The item's unit is "egg". So a unit check written to stop
    "scoop" masquerading as "tbsp" fires on a word that is not a unit at all,
    and the user's own count loses to it."""
    item = {"food": "Fried eggs", "amount": 2, "unit": "egg", "basis": basis}
    assert _item_is_stated(item, BOWL_MESSAGE) is True, (
        "a spelled count the user typed lost to the interpreter's basis")


def test_the_scoop_veto_survives_the_spelled_count_fix():
    """⛔⛔ THE GUARD ON THAT SECOND FIX. Loosening the unit check enough to
    let "two fried eggs" through must not loosen it enough to let "a scoop of
    peanut butter" carry a tablespoon. The separator is that the clause names
    THIS item's unit in the user's own words: "eggs" is written, "tbsp" is
    not."""
    item = {"food": "Peanut butter", "amount": 1, "unit": "tbsp",
            "basis": "estimate"}
    assert _item_is_stated(item, "and a scoop of peanut butter") is False


# ══════════════════════════════════════════════════════════════════════════
# ROUND 3 — A COUNT HAS TO BE THIS FOOD'S COUNT
#
# `_literal_amount_with_unit` deliberately drops the unit requirement when the
# item is measured in a COUNT ("egg", "piece", "slice"): "15" versus "piece"
# is not a disagreement, so demanding agreement there would refuse real
# statements. The cost of dropping it was never stated: with no unit to bind
# to, ANY number in the clause satisfies the match.
#
# So a number belonging to the food NEXT to this one can be read as this
# one's, and `basis="estimate"` no longer vetoes it — round 1 moved that veto
# below this rung. The quantity ask is then suppressed and an inferred count
# commits.
#
# ⭐ WORTH RECORDING PRECISELY, because the reported example does not
# reproduce: in "I had 2 tacos and fried eggs" the clause splitter already
# keeps the eggs clause down to "fried eggs", and the "2" is never in scope.
# The defect is real but needs a shape the splitter does NOT cut — a
# connective it does not split on:
#
#     "fried eggs after 2 tacos"   ->  clause "fried eggs after 2 tacos"
#
# measured True at abf615d against an item of 2 egg / basis="estimate". Both
# shapes are pinned below, so the guard cannot be weakened back to the one
# that happened to be safe.
# ══════════════════════════════════════════════════════════════════════════

EGGS_2 = {"food": "Fried eggs", "amount": 2, "unit": "egg", "basis": "estimate"}


@pytest.mark.parametrize("message,stated,why", [
    ("2 fried eggs", True,
     "the count sits on this food's own noun"),
    ("I had 2 fried eggs", True,
     "a leading verb does not break the binding"),
    ("2 tacos and fried eggs", False,
     "the count belongs to the tacos"),
    ("fried eggs after 2 tacos", False,
     "REPRO at abf615d: the splitter does not cut on 'after', so the taco "
     "count landed inside the eggs clause and bound to it"),
    ("fried eggs with 2 slices of toast", False,
     "a side dish's count is not this food's count"),
])
def test_a_count_must_bind_to_this_food(message, stated, why):
    """⛔⛔ THE TWIN. A count literal has to attach to THIS food's own words —
    its head noun or its unit — and not merely appear somewhere in the clause.

    A measured unit carries its own proof of ownership: `100 g` beside a food
    measured in grams is that food's mass. A bare count carries none, so the
    binding has to come from the words around it."""
    assert _item_is_stated(dict(EGGS_2), message) is stated, why


def test_the_count_binding_does_not_cost_the_awkward_real_fixtures():
    """⛔ THE GUARD ON THE GUARD. "Bind to the head noun" alone would refuse
    two shapes already shipped and tested — a food whose name tokenises badly
    ("Peanut M&Ms") and one whose count precedes an adjective ("15 peanut
    m&m"). Binding accepts any recognised word of THIS food's name, which is
    what keeps those working while still refusing the taco."""
    assert _item_is_stated(
        {"food": "Peanut M&Ms", "amount": 15, "unit": "pieces",
         "basis": "estimate"},
        "I had like 15 peanut m&m, half a banana and a scoop of peanut butter",
    ) is True
    assert _item_is_stated(
        {"food": "Chicken nuggets", "amount": 6, "unit": "piece",
         "basis": "estimate"}, "had 6 chicken nuggets") is True


def test_a_measured_unit_does_not_need_the_noun_beside_it():
    """The binding requirement is for COUNTS only. "200g of grilled chicken
    breast" proves ownership through the unit, and demanding the food's noun
    within a few words of the number would refuse it."""
    assert _item_is_stated(
        {"food": "Grilled chicken breast", "amount": 200, "unit": "g",
         "basis": "estimate"},
        "3 large eggs and 200g of grilled chicken breast") is True


def test_a_spelled_count_whose_unit_is_absent_still_needs_the_unit():
    """A written number is necessary, not sufficient. If the user spelled a
    count but named a unit this item cannot be measured in, the disagreement
    is real and still vetoes."""
    item = {"food": "Whole milk", "amount": 2, "unit": "cup",
            "basis": "estimate"}
    assert _item_is_stated(item, "I had two glasses of milk") is False
