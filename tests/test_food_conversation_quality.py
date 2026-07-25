"""The shipped-transcript regressions (Danny, 2026-07-25).

Four screenshots, three defects, one exact conversation. Every test here is
anchored to something a real user saw:

    "I've got:
     15 pieces Peanut M&Ms
     0.5 banana Banana
     1 tbsp Peanut Butter
     Does that look right?"

    ✓ Logged
    Logged: Peanut M&Ms, Banana, Peanut Butter.
    [card]
    You're at 458 / 2165 calories today, good room left.
    Protein's at 12 / 180g, go protein-first next.

Three things went wrong and they are independent:

  * the copy read as a component spec rather than a coach talking
  * "a scoop of peanut butter" silently became "1 tbsp" and the user was asked
    to approve it as part of a general "does that look right?"
  * a named product resolved from generic data and said so nowhere the user
    could see

The transcript is the specification. Where a test asserts an exact string it is
because that string is what the user will read.
"""
import pytest

from core.food_response import (FoodItemSummary, FoodResponseIntent,
                                FoodResponsePlan, describe_portion, fallback,
                                plan_review, strip_card_recitation, validate)
from core.food_turn import _item_is_stated, clarify_text, format_confirm
from core.food_pipeline import _vague_measure_in, plan_turn

#: The message from the screenshot, verbatim.
MESSAGE = ("I had like 15 peanut m&m, half a banana and a scoop of "
           "peanut butter")

#: What the interpreter produced for it, verbatim.
INTERPRETED = {"items": [
    {"food": "Peanut M&Ms", "amount": 15, "unit": "pieces", "branded": True,
     "calories": 135},
    {"food": "Banana", "amount": 0.5, "unit": "banana", "calories": 53},
    {"food": "Peanut Butter", "amount": 1, "unit": "tbsp", "calories": 95},
]}


def _decision(mode="moderate"):
    return plan_turn(INTERPRETED, turn_id="t1", message=MESSAGE, mode=mode)


# ── 1. the copy ───────────────────────────────────────────────────────────────
def test_the_review_turn_reads_as_prose_not_as_a_form():
    decision = _decision()
    text = clarify_text(decision, decision.question, user_message=MESSAGE)

    assert text.startswith("Here's how I'm reading that:")
    for banned in ("I've got:", "Meal check", "Quick review",
                   "Before I log this"):
        assert banned not in text, banned


def test_the_duplicated_food_name_is_gone():
    """"0.5 banana Banana" — the interpreter used the food as its own unit and
    the formatter printed both."""
    decision = _decision()
    text = clarify_text(decision, decision.question, user_message=MESSAGE)

    assert "0.5 banana Banana" not in text
    assert "banana Banana" not in text.replace("Banana", "Banana")
    assert "Half a banana" in text


def test_quantities_are_spoken_not_tabulated():
    decision = _decision()
    text = clarify_text(decision, decision.question, user_message=MESSAGE)

    assert "15 pieces Peanut M&Ms" not in text
    assert "1 tbsp Peanut Butter" not in text
    assert "15 Peanut M&Ms" in text


@pytest.mark.parametrize("portion,name,branded,expected", [
    ("0.5 banana", "Banana", False, "half a banana"),
    ("15 pieces", "Peanut M&Ms", True, "15 Peanut M&Ms"),
    ("1 tbsp", "Peanut Butter", False, "one tablespoon of peanut butter"),
    ("2 tbsp", "Peanut Butter", False, "two tablespoons of peanut butter"),
    ("1 scoop", "Peanut Butter", False, "one scoop of peanut butter"),
    ("150 g", "chicken breast", False, "150g of chicken breast"),
    ("0.5 cup", "Cottage Cheese", False, "half a cup of cottage cheese"),
    ("1 bar", "Barebells", True, "a Barebells bar"),
    ("0.25", "apple", False, "a quarter of an apple"),
    ("2", "eggs", False, "two eggs"),
    ("", "Barebells bar", True, "Barebells bar"),
])
def test_portions_read_the_way_a_person_says_them(portion, name, branded,
                                                  expected):
    assert describe_portion(portion, name, branded=branded) == expected


def test_a_short_simple_meal_stays_prose():
    """One or two simple foods are a sentence. Forcing every response into a
    list is the same mistake as forcing every response into a label."""
    text = format_confirm([{"food": "toast", "amount": 1, "unit": "slice"}],
                          user_message="a slice of toast")
    assert text.startswith("I'm reading that as")
    assert "•" not in text


def test_three_foods_become_a_list():
    text = format_confirm(
        [{"food": "egg", "amount": 2, "unit": "egg"},
         {"food": "sourdough toast", "amount": 1, "unit": "slice"},
         {"food": "butter", "amount": 1, "unit": "tsp"}],
        user_message="two eggs, a slice of sourdough toast and a tsp of butter")
    assert text.count("•") == 3
    assert "Two eggs" in text and "One teaspoon of butter" in text


# ── 2. the silent conversion ──────────────────────────────────────────────────
def test_a_scoop_is_not_silently_one_tablespoon():
    """The defect at the centre of the transcript. One versus two tablespoons
    of peanut butter is about 95 calories, and the user was invited to approve
    it without being shown a number had been chosen."""
    decision = _decision()

    assert decision.asks
    question = decision.question.prompt
    assert "scoop" in question.lower()
    assert "tablespoon" in question.lower()
    assert "peanut butter" in question.lower()


def test_the_unresolved_item_is_shown_in_the_users_own_words():
    """Printing "one tablespoon of peanut butter" above a question about
    whether it was one tablespoon is the silent conversion wearing a
    question mark."""
    decision = _decision()
    text = clarify_text(decision, decision.question, user_message=MESSAGE)

    assert "One scoop of peanut butter" in text
    assert "tablespoon of peanut butter" not in text.lower().split("\n\n")[1]


def test_the_interpretation_and_the_question_arrive_in_one_turn():
    """Asking "does that look right?" and then asking a second question spends
    two turns on one meal."""
    decision = _decision()
    text = clarify_text(decision, decision.question, user_message=MESSAGE)

    assert "Does that look right?" not in text
    assert text.count("?") == 1


def test_the_foods_the_user_did_state_are_not_questioned():
    decision = _decision()
    assert len(decision.clarification.ready_item_ids) == 2
    assert len(decision.clarification.held_item_ids) == 1


def test_a_stated_amount_in_a_neighbouring_clause_is_not_borrowed():
    """The root cause. "a scoop of peanut butter" was read as a STATED amount
    of 1 because the word "a" appeared elsewhere in the message — in "half a
    banana"."""
    assert not _item_is_stated(
        {"food": "Peanut Butter", "amount": 1, "unit": "tbsp"}, MESSAGE)
    assert _item_is_stated(
        {"food": "Peanut M&Ms", "amount": 15, "unit": "pieces"}, MESSAGE)
    assert _item_is_stated(
        {"food": "Banana", "amount": 0.5, "unit": "banana"}, MESSAGE)


@pytest.mark.parametrize("item,message,stated", [
    ({"food": "chicken", "amount": 200, "unit": "g"},
     "200g chicken and a scoop of peanut butter", True),
    ({"food": "salmon", "amount": 6, "unit": "oz"}, "6 oz salmon", True),
    ({"food": "egg", "amount": 1, "unit": "egg"}, "I had one egg", True),
    ({"food": "banana", "amount": 1, "unit": "banana"}, "I had a banana", True),
    # The article sits next to the unit the user actually used.
    ({"food": "Peanut Butter", "amount": 1, "unit": "scoop"},
     "a scoop of peanut butter", True),
])
def test_the_stated_amount_proxy_still_recognises_real_ones(item, message,
                                                            stated):
    assert _item_is_stated(item, message) is stated


def test_a_vague_measure_binds_to_its_own_food():
    """"a scoop of peanut butter and 200g of chicken" contains "scoop", and
    attaching it to the chicken would question a portion stated exactly."""
    assert _vague_measure_in(MESSAGE, "Peanut Butter") == "scoop"
    assert _vague_measure_in(MESSAGE, "Peanut M&Ms") is None
    assert _vague_measure_in("200g chicken and a scoop of pb", "chicken") is None


def test_a_measure_we_did_not_convert_is_not_questioned():
    """"a plate of turkey" arriving as 1 plate is vague but not CONVERTED. The
    portion ontology already discloses the range; asking would be friction for
    a conversion that never happened."""
    data = {"items": [{"food": "Roast turkey plate", "amount": 1,
                       "unit": "plate", "calories": 500}]}
    decision = plan_turn(data, turn_id="t2", message="turkey plate",
                         mode="moderate")
    assert not decision.asks


def test_quick_mode_still_commits_a_converted_measure():
    """Quick exists to accept exactly this risk. It commits with the
    assumption stated rather than spending a turn."""
    decision = _decision(mode="quick")
    assert not decision.asks
    assert len(decision.clarification.ready_item_ids) == 3


def test_strict_mode_holds_the_whole_meal():
    decision = _decision(mode="strict")
    assert decision.asks
    assert not decision.clarification.ready_item_ids


# ── 3. the branded source ─────────────────────────────────────────────────────
def _candidate(source, tier, name, calories, grade):
    from skills.nutrition.candidates import Candidate
    from skills.nutrition.models import profile_from_values
    from skills.nutrition.scaling import Per100g
    return Candidate(
        source=source, tier=tier, name=name,
        profile=profile_from_values(source, basis="per_100g", confidence=0.8,
                                    calories=calories, protein=13),
        basis=Per100g(), reported_grade=grade)


def _resolve_mms(candidates):
    from skills.nutrition.models import FoodResolutionRequest
    from skills.nutrition.resolver import resolve
    return resolve(FoodResolutionRequest(
        food_name="Peanut M&Ms", brand="M&Ms", raw_quantity="27g",
        is_packaged=True), candidates)


def test_a_generic_standing_in_for_a_brand_says_so():
    """From the trace: "Logged Peanut M&Ms — 135 cal / From the USDA
    database". The tier order preferred branded correctly; there was no
    branded candidate, so a generic won unopposed and was presented with the
    confidence of a label."""
    from skills.nutrition.provenance import MatchGrade, SourceTier

    out = _resolve_mms([_candidate("usda", SourceTier.GENERIC_EXACT,
                                   "Peanut M&Ms", 497, MatchGrade.CATEGORY)])
    assert any("generic data for a named product" in a
               for a in out.assumptions), out.assumptions
    assert any(a.field == "branded_source" for a in out.ambiguities)


def test_the_generic_fallback_lowers_confidence():
    from skills.nutrition.provenance import MatchGrade, SourceTier

    generic = _resolve_mms([_candidate("usda", SourceTier.GENERIC_EXACT,
                                       "Peanut M&Ms", 497,
                                       MatchGrade.CATEGORY)])
    branded = _resolve_mms([_candidate("off", SourceTier.BRANDED_EXACT,
                                       "Peanut M&Ms", 515, MatchGrade.EXACT)])
    assert generic.confidence < branded.confidence


def test_a_branded_record_removes_the_disclosure():
    """The disclosure is about which KIND of source answered. When a label
    answers, there is nothing to disclose."""
    from skills.nutrition.provenance import MatchGrade, SourceTier

    out = _resolve_mms([
        _candidate("usda", SourceTier.GENERIC_EXACT, "Peanut M&Ms", 497,
                   MatchGrade.CATEGORY),
        _candidate("off", SourceTier.BRANDED_EXACT, "Peanut M&Ms", 515,
                   MatchGrade.EXACT)])
    assert out.source == "off"
    assert not any(a.field == "branded_source" for a in out.ambiguities)
    assert not any("generic data" in a for a in out.assumptions)


def test_a_generic_food_is_not_accused_of_being_a_brand():
    """Chicken breast from USDA is USDA doing its job."""
    from skills.nutrition.models import FoodResolutionRequest
    from skills.nutrition.provenance import MatchGrade, SourceTier
    from skills.nutrition.resolver import resolve

    out = resolve(
        FoodResolutionRequest(food_name="chicken breast", raw_quantity="200g"),
        [_candidate("usda", SourceTier.GENERIC_EXACT, "chicken breast", 165,
                    MatchGrade.EXACT)])
    assert not any("generic data" in a for a in out.assumptions)


# ── 4. what follows the card ──────────────────────────────────────────────────
def _committed_plan():
    return FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT,
        committed_items=(FoodItemSummary(name="Peanut M&Ms"),
                         FoodItemSummary(name="Banana"),
                         FoodItemSummary(name="Peanut Butter")),
        facts_visible_in_card=frozenset({"calories", "protein",
                                         "day_totals"}))


def test_the_redundant_receipt_sentence_is_removed():
    """"Logged: Peanut M&Ms, Banana, Peanut Butter." shipped directly above a
    card listing the same three names with their macros."""
    out = strip_card_recitation(
        "Logged: Peanut M&Ms, Banana, Peanut Butter.", _committed_plan())
    assert out == ""


def test_progress_rendered_as_arithmetic_is_removed():
    """"458 / 2165" is a progress bar someone typed out. It survived the old
    check by carrying a recommendation."""
    out = strip_card_recitation(
        "You're at 458 / 2165 calories today, good room left."
        "|||Protein's at 12 / 180g, go protein-first next.", _committed_plan())
    assert out == ""


def test_coaching_that_says_something_survives():
    """The rule is not "delete text after the card" — it is "the card owns the
    numbers, the sentence says what they mean"."""
    kept = ("You still have plenty of flexibility today, but protein is "
            "running light. Build your next meal around a substantial "
            "protein source.")
    assert strip_card_recitation(kept, _committed_plan()) == kept


def test_dashboard_syntax_fails_validation_outright():
    """Rejected rather than only stripped, so the composer regenerates instead
    of having its output quietly edited."""
    plan = FoodResponsePlan(intent=FoodResponseIntent.COACH,
                            allow_no_text=True)
    result = validate("Protein's at 12 / 180g, go protein-first next.", plan)
    assert not result.ok
    assert result.reason == "dashboard_syntax"


def test_a_roll_call_of_something_else_is_not_stripped():
    """The rule matches the committed items, not any comma-separated list."""
    plan = _committed_plan()
    text = "Almonds, walnuts and pecans are all good options for that."
    assert strip_card_recitation(text, plan) == text


# ── 5. the confirmed item that never landed ───────────────────────────────────
#
# From the second pair of screenshots: the user confirmed a Barebells Salty
# Peanut bar, answered two follow-up questions about cottage cheese and honey,
# and was then told "Couldn't touch the Barebells Salty Peanut Protein Bar —
# the board changed under me." Two of three items logged; the one they had
# explicitly confirmed was dropped.
_ASSISTANT_ASKED = (
    "Barebell bar (Salty Peanut) locked in\n"
    "Just need a couple things:\n"
    "1. cottage cheese: rough amount - half cup or a full cup?\n"
    "2. honey: about how much - a teaspoon or a tablespoon drizzle?\n"
    "Nothing hits the board till then, keeps your log exact.")
_PRIOR_USER = ("Salty peanut, also a little bit kf cottage cheese "
               "and some honey")
_ANSWER = "Half a cup and like a drizzle baby"


def test_a_clarify_answer_carries_the_intent_of_the_turn_it_answers():
    """The cause of the drop. The combine that gives an answer turn its item
    names was gated on the assistant's message ENDING with "?" — this one asked
    two questions and closed with a reassurance, so the combine switched off,
    the answer named no food, and the carryover guard read a confirmed bar as a
    phantom."""
    from skills.logging_intent import effective_intent_message

    combined = effective_intent_message(_ANSWER, _PRIOR_USER,
                                        _ASSISTANT_ASKED)
    assert combined != _ANSWER, "the answer turn lost its item names"
    assert "salty peanut" in combined.lower()


def test_the_combine_still_needs_a_question():
    """Widening this gate re-opens the phantom re-fire it was built to stop, so
    an assistant turn that asked nothing must not pull the prior message in."""
    from skills.logging_intent import effective_intent_message

    assert effective_intent_message(
        "had a bagel", "earlier stuff", "Nice work today.") == "had a bagel"


def test_the_combine_still_only_applies_to_a_short_answer():
    """A long message stands on its own — combining widens the gate, and the
    bound is what keeps it tight."""
    from skills.logging_intent import effective_intent_message

    long_answer = " ".join(["word"] * 20)
    assert effective_intent_message(
        long_answer, "prior message", "Which one?") == long_answer


def test_the_confirmed_bar_is_named_by_the_combined_turn():
    """End to end for the drop: with the combine restored, the guard that
    blocked the bar can see it named."""
    from skills.logging_intent import effective_intent_message

    combined = effective_intent_message(_ANSWER, _PRIOR_USER,
                                        _ASSISTANT_ASKED).lower()
    signature = ["barebells", "salty", "peanut", "protein", "bar"]
    assert any(word in combined for word in signature), (
        "no signature word survived; the carryover guard would block again")
