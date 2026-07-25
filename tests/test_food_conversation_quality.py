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

from core.food_response import (CLARIFY_OPENER, REVIEW_OPENER,
                                FoodItemSummary, FoodResponseIntent,
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

    # CLARIFY, not REVIEW: the peanut butter scoop is still open, so the turn
    # says it is interpreting rather than about to log.
    assert text.startswith(CLARIFY_OPENER)
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


# ── 6. the answers the new question invites ───────────────────────────────────
#
# The question is "Was the peanut butter scoop closer to one tablespoon or two
# tablespoons?" — so the two options it offers, and the natural ways people
# answer a question shaped like that, all have to parse. Before this, both of
# its own options were unparseable.
class _Question:
    """A stand-in for the clarification question, carrying its offered range."""
    def __init__(self, *labels):
        from skills.nutrition.clarify_policy import ClarificationOption
        self.options = tuple(
            ClarificationOption(label=l, field_name="consumed_fraction")
            for l in labels)


@pytest.mark.parametrize("answer,amount", [
    ("one tablespoon", 1.0),
    ("two tablespoons", 2.0),
    ("1 tbsp", 1.0),
    ("2 tbsp", 2.0),
    # Qualitative, resolved against the offered ends.
    ("a heaping spoonful", 2.0),
    ("just a small spoon", 1.0),
    ("the bigger one", 2.0),
    # No middle option exists, so the midpoint is computed rather than an end
    # being picked silently — the same rule as the rest of this PR.
    ("somewhere in between", 1.5),
])
def test_the_questions_own_options_parse(answer, amount):
    from skills.nutrition.answer_parsers import parse_quantity_answer

    parsed = parse_quantity_answer(
        answer, _Question("one tablespoon", "two tablespoons"))
    assert parsed.values.get("stated_amount") == amount, dict(parsed.values)


def test_asking_for_an_estimate_is_a_command_not_a_quantity():
    from skills.nutrition.answer_parsers import (ClarificationCommand,
                                                 parse_quantity_answer)

    parsed = parse_quantity_answer(
        "use your best estimate", _Question("one tablespoon",
                                            "two tablespoons"))
    assert parsed.command is ClarificationCommand.ESTIMATE


def test_a_qualitative_answer_needs_a_question_to_resolve_against():
    """"A small one" says nothing without knowing what was offered, and
    guessing a number from it would be the silent conversion again."""
    from skills.nutrition.answer_parsers import parse_quantity_answer

    assert parse_quantity_answer("just a small one").unparsed


def test_an_unrelated_answer_still_refuses():
    from skills.nutrition.answer_parsers import parse_quantity_answer

    parsed = parse_quantity_answer(
        "purple", _Question("one tablespoon", "two tablespoons"))
    assert parsed.unparsed


# ── 7. coaching reads as sentences ────────────────────────────────────────────
def test_the_deterministic_tail_is_not_a_progress_bar():
    """"You're at 458 / 2165 calories today, good room left." — a dashboard
    someone typed out. The remaining amount is the useful part."""
    from handlers.tool_executor import deterministic_confirmation

    class _P:
        calorie_target, protein_target = 2000, 180

    class _L:
        total_calories, total_protein = 500, 20

    out = deterministic_confirmation(
        [{"name": "log_food", "input": {"food_name": "Rice"}}], _L(), _P())
    assert "/" not in out
    assert "1500" in out, out


def test_card_verdicts_are_complete_sentences():
    """"Small add. Real meal still needed." is a telegram. Every verdict the
    card can show has to read as something a person said."""
    import re

    from core import receipt

    source = (receipt.__file__ or "")
    with open(source, "r") as handle:
        verdicts = re.findall(r'verdict = \(?"([^"]{12,})"', handle.read())

    assert verdicts, "no verdicts found — did the module move?"
    for text in verdicts:
        first = text.split(".")[0]
        assert len(first.split()) >= 4, f"telegraphic verdict: {text!r}"


# ── 8. "you pick" is a request to decide, not to decide silently ─────────────
def test_asking_for_an_estimate_produces_an_amount():
    """The command was parsed and then dropped — nothing turned it into a
    number, so a user who answered "no idea, you pick" left the item exactly as
    unresolved as before they answered."""
    from skills.nutrition.answer_parsers import parse_quantity_answer

    parsed = parse_quantity_answer(
        "use your best estimate", _Question("one tablespoon",
                                            "two tablespoons"))
    assert parsed.values.get("stated_amount") == 1.5


def test_an_estimate_says_what_it_chose():
    """Being asked to choose is not permission to choose silently."""
    from skills.nutrition.answer_parsers import parse_quantity_answer

    parsed = parse_quantity_answer(
        "no idea", _Question("one tablespoon", "two tablespoons"))
    assert "1.5" in parsed.disclosure
    assert "tablespoon" in parsed.disclosure


def test_an_estimate_with_nothing_to_estimate_from_stays_a_command():
    """No offered range means no basis for a midpoint. The command still
    stands so the caller falls back to its own estimate path rather than
    re-asking a question the user has already declined."""
    from skills.nutrition.answer_parsers import (ClarificationCommand,
                                                 parse_quantity_answer)

    class _Bare:
        options = ()

    parsed = parse_quantity_answer("no idea", _Bare())
    assert parsed.command is ClarificationCommand.ESTIMATE
    assert not parsed.values


# ── 9. the meal total moves with the answer ───────────────────────────────────
def _peanut_butter(tablespoons):
    """Resolve peanut butter at N tablespoons through the real resolver."""
    from skills.nutrition.candidates import Candidate
    from skills.nutrition.models import (FoodResolutionRequest,
                                         profile_from_values)
    from skills.nutrition.provenance import MatchGrade, SourceTier
    from skills.nutrition.resolver import resolve
    from skills.nutrition.scaling import Per100g

    candidate = Candidate(
        source="usda", tier=SourceTier.GENERIC_EXACT, name="Peanut butter",
        profile=profile_from_values("usda", basis="per_100g", confidence=0.8,
                                    calories=588, protein=25, fat=50),
        basis=Per100g(), reported_grade=MatchGrade.EXACT)
    return resolve(FoodResolutionRequest(
        food_name="Peanut butter",
        raw_quantity=f"{tablespoons} tbsp"), [candidate])


def test_the_meal_total_moves_when_the_scoop_is_answered():
    """The reason the question is worth asking. One versus two tablespoons is
    the difference the user was being asked to approve blind."""
    one = _peanut_butter(1).nutrients.amount("calories")
    two = _peanut_butter(2).nutrients.amount("calories")

    assert one and two
    assert two > one * 1.8, (one, two)
    # ~95 calories, which is what makes it material rather than a detail.
    assert 80 <= (two - one) <= 115, (one, two)


# ── 10. source precedence for a named product ─────────────────────────────────
def test_a_saved_user_food_outranks_a_manufacturer_record():
    """A user's own saved food for the same product is the higher authority —
    they weighed it, or corrected it, and that beats a database.

    Read this together with tests/test_food_memory_authority.py: the tier is
    only reached by a row the user ACTUALLY corrected. Auto-cached lookups used
    to arrive here too, which is how a generic estimate came to outrank a real
    product label. This test constructs the tier directly, so it pins the
    ordering; that file pins who is allowed into it.
    """
    from skills.nutrition.provenance import MatchGrade, SourceTier

    out = _resolve_mms([
        _candidate("off", SourceTier.BRANDED_EXACT, "Peanut M&Ms", 515,
                   MatchGrade.EXACT),
        _candidate("user_regular", SourceTier.USER_REGULAR, "Peanut M&Ms",
                   490, MatchGrade.EXACT)])
    assert out.source == "user_regular"


def test_a_different_variant_does_not_answer_for_this_one():
    """Peanut M&M's and plain M&M's are different products. A variant mismatch
    must not quietly answer — it is the near-neighbour failure with a brand
    name attached."""
    from skills.nutrition.models import FoodResolutionRequest
    from skills.nutrition.provenance import MatchGrade, SourceTier
    from skills.nutrition.resolver import resolve

    out = resolve(
        FoodResolutionRequest(food_name="Peanut M&Ms", brand="M&Ms",
                              variant="peanut", raw_quantity="27g",
                              is_packaged=True),
        [_candidate("off", SourceTier.BRANDED_EXACT, "Peanut Butter M&Ms",
                    520, MatchGrade.EXACT)])
    # DOWNGRADED, not rejected: it is plausibly the same product family, so
    # throwing it away would leave nothing where a rough answer was available.
    # What it must not be is EXACT — at that grade it outranks a real match and
    # its disagreement counts as decisive evidence.
    assert out.match_grade == "category", out.match_grade


# ── 11. nothing narrates the transaction ──────────────────────────────────────
@pytest.mark.parametrize("narration", [
    "Give me a moment. Logging all 3 now.",
    "One sec, saving that.",
    "Processing your log now.",
    "Let me log that for you.",
])
def test_processing_narration_never_validates(narration):
    """The turn tells the user what happened, never that something is about to
    happen. A progress announcement is a stall the user has to sit through."""
    plan = FoodResponsePlan(intent=FoodResponseIntent.COMMIT,
                            allow_no_text=True)
    assert not validate(narration, plan).ok


# ── 12. refusing to scale is the loudest doubt, not the quietest ──────────────
def _unscalable():
    """A portion with no known mass: "1 platter" of a food nothing can weigh."""
    from skills.nutrition.candidates import Candidate
    from skills.nutrition.models import (FoodResolutionRequest,
                                         profile_from_values)
    from skills.nutrition.provenance import MatchGrade, SourceTier
    from skills.nutrition.resolver import resolve
    from skills.nutrition.scaling import Per100g

    candidate = Candidate(
        source="usda", tier=SourceTier.GENERIC_EXACT, name="Shawarma platter",
        profile=profile_from_values("usda", basis="per_100g", confidence=0.8,
                                    calories=200, protein=20),
        basis=Per100g(), reported_grade=MatchGrade.EXACT)
    return resolve(FoodResolutionRequest(
        food_name="shawarma platter", raw_quantity="1 platter"), [candidate])


def test_an_unscalable_portion_logs_nothing_rather_than_the_wrong_portion():
    """The 588-calorie tablespoon. A per-100g row is not a fallback for a
    portion we could not convert — it describes a different amount of food."""
    out = _unscalable()
    assert out.nutrients.amount("calories") in (None, 0), out.nutrients.as_dict()
    assert any("not scaled" in w for w in out.warnings), out.warnings


def test_a_refused_scaling_still_sizes_its_own_doubt():
    """The regression this exists to catch: emptying the profile also emptied
    every calorie_span computed from it, so the state where the resolver knows
    LEAST reported zero doubt and the ask ladder went quiet. The magnitude for
    sizing comes from the unscaled row; the ANSWER still comes from nowhere."""
    from skills.nutrition.resolver import should_ask

    out = _unscalable()
    basis = [a for a in out.ambiguities if a.field == "serving_basis"]
    assert basis, out.ambiguities
    assert basis[0].calorie_span > 0, basis[0]
    # And it reaches the user in the mode that exists to catch exactly this.
    assert should_ask(out.ambiguities, "strict") is not None


# ── 13. a dropped food says what actually happened ───────────────────────────
#
# From the same pair of screenshots as section 5. The confirmed Barebells bar
# came back as "Couldn't touch the Barebells Salty Peanut Protein Bar - the
# board changed under me", and the user's note was "it got dropped for some
# reason." The reason was unrecoverable afterwards, which is the defect these
# pin: one notice asserted a single cause for every failure mode, and nothing
# recorded the real one.
def _exec(*calls):
    from core.execution_result import CallResult, ExecutionResult
    return ExecutionResult(calls=tuple(calls))


def _call(name, status, result_text, food="Barebells bar"):
    from core.execution_result import CallResult
    return CallResult(name=name, raw_input={"food_name": food},
                      status=status, result_text=result_text)


def test_the_notice_no_longer_blames_a_stale_board_for_everything():
    """STALE BOARD is only ever emitted by update_food_entry's compare-and-swap.
    The dropped bar was a log_food, so a concurrent edit could not have been
    the cause — the user was sent to re-read a board that was never involved."""
    from core.food_ledger import build_failure_notice
    out = build_failure_notice(_exec(
        _call("log_food", "blocked", "Error: something broke")).failures())
    assert "board" not in out.lower(), out
    assert "Barebells bar" in out


def test_a_stale_board_is_still_reported_as_one():
    """The fix must not flatten every failure into one vague sentence either.
    Where the board really did change, say so."""
    from core.food_ledger import build_failure_notice
    out = build_failure_notice(_exec(
        _call("update_food_entry", "blocked",
              "STALE BOARD: entry #1 is now 500 cal, not 180.")).failures())
    assert "changed while I was writing" in out, out


@pytest.mark.parametrize("result_text,expected", [
    ("Already on the board — duplicate", "it was already logged"),
    ("COULD NOT FIND that food", "I couldn't find it"),
    ("Nothing to restore", "there was nothing to restore"),
    ("Skipped — no log to update", "it didn't save"),
    ("Failed to write", "it didn't save"),
])
def test_each_failure_class_gets_its_own_words(result_text, expected):
    from core.food_ledger import failure_reason
    assert failure_reason(result_text) == expected


def test_every_failure_prefix_is_explained_or_falls_back_honestly():
    """A prefix added without a reason must degrade to "it didn't save" rather
    than to a confident wrong cause. This is the drift guard: the two tuples
    live together, and this asserts the fallback is the safe one."""
    from core.food_ledger import (FAILURE_PREFIXES, GENERIC_FAILURE_REASON,
                                  failure_reason)
    for prefix in FAILURE_PREFIXES:
        reason = failure_reason(f"{prefix} whatever")
        assert reason, prefix
        assert "board" not in reason or prefix == "STALE BOARD", (prefix, reason)
    assert failure_reason("something entirely new") == GENERIC_FAILURE_REASON


# ── the silent-drop hole ──────────────────────────────────────────────────────
def test_a_failed_call_is_reported_not_swallowed():
    """`status` is documented as committed|blocked|failed, but failed_names()
    filtered to "blocked" alone. A call landing on "failed" was excluded from
    ok_tool_calls() for not committing AND from the notice for not being
    blocked — gone from the card and the reply both, with no trace anywhere.
    Nothing sets it today; that is what makes it a trap rather than a bug."""
    ex = _exec(_call("log_food", "failed", "Error: boom", food="Protein bar"))
    assert ex.ok_tool_calls() == []
    assert "Protein bar" in ex.failed_names()


def test_a_committed_call_is_never_reported_as_dropped():
    ex = _exec(_call("log_food", "committed", "", food="Banana"))
    assert ex.failed_names() == []
    assert len(ex.ok_tool_calls()) == 1


def test_two_foods_lost_the_same_way_read_as_one_sentence():
    from core.food_ledger import build_failure_notice
    out = build_failure_notice(_exec(
        _call("log_food", "blocked", "Error: a", food="bagel"),
        _call("log_food", "blocked", "Error: b", food="eggs")).failures())
    assert out.count("I couldn't log") == 1, out
    assert "bagel and eggs" in out


def test_the_notice_is_a_complete_sentence():
    """Same contract as the card verdicts — no terse fragments."""
    from core.food_ledger import build_failure_notice
    out = build_failure_notice(_exec(
        _call("log_food", "blocked", "Error: x", food="bagel")).failures())
    assert out[0].isupper() and out.rstrip().endswith("?"), out
    assert " — " in out


def test_no_failures_produces_no_notice():
    from core.food_ledger import build_failure_notice
    assert build_failure_notice([]) == ""
    assert build_failure_notice(_exec(
        _call("log_food", "committed", "")).failures()) == ""


# ── 14. the two review turns do not sound alike ──────────────────────────────
#
# The directive gives two openers because the turns differ: one is still
# forming an opinion and is about to ask about part of it, the other has
# nothing open and is taking a last look before writing. Sharing an opener made
# them indistinguishable to a reader, which is how "does that look right?"
# ended up standing in front of a question not yet asked.
def test_an_open_question_says_it_is_interpreting():
    decision = _decision()
    text = clarify_text(decision, decision.question, user_message=MESSAGE)
    assert text.startswith(CLARIFY_OPENER)
    assert REVIEW_OPENER not in text


def test_a_settled_meal_says_it_is_about_to_log():
    text = fallback(plan_review(
        tuple(FoodItemSummary(name=n, portion=p) for n, p in
              (("egg", "2"), ("sourdough toast", "1 slice"),
               ("butter", "1 tsp")))))
    assert text.startswith(REVIEW_OPENER)
    assert CLARIFY_OPENER not in text
    assert text.endswith("Does that all look right?")


def test_neither_opener_is_a_heading():
    """The banned register is the label over a list — "Meal check", "Quick
    review". Both openers must be sentences addressed to a person."""
    for opener in (CLARIFY_OPENER, REVIEW_OPENER):
        assert opener.endswith(":"), opener
        assert len(opener.split()) >= 5, opener
        assert opener[0].isupper() and "'" in opener


def test_the_question_names_what_is_uncertain():
    """"Was the peanut butter scoop closer to..." reads like a form validating
    a field. Naming the food first lets the ask stay short and keeps it
    bindable in a three-food meal."""
    decision = _decision()
    prompt = decision.question.prompt
    assert prompt.startswith("The peanut butter is the only part")
    assert "Was the scoop closer to" in prompt


@pytest.mark.parametrize("low,high,expected", [
    ("one tablespoon", "two tablespoons", "one or two tablespoons"),
    ("one cup", "two cups", "one or two cups"),
    # Different units must both survive — this is a real choice, not a plural.
    ("one teaspoon", "one tablespoon", "one teaspoon or one tablespoon"),
    # An article is not an amount: "a or two scoops" reads as a typo.
    ("a scoop", "two scoops", "a scoop or two scoops"),
    # A qualifier does not survive losing its noun: "half a or one cup".
    ("half a cup", "one cup", "half a cup or one cup"),
])
def test_a_shared_unit_is_said_once(low, high, expected):
    from core.food_pipeline import _shared_unit
    assert _shared_unit(low, high) == expected


# ── 15. coaching is prose, not a status line ─────────────────────────────────
def _tail(cal, pro, cal_t=2165, pro_t=180):
    from types import SimpleNamespace
    from handlers.tool_executor import deterministic_confirmation
    return deterministic_confirmation(
        [{"name": "log_food", "input": {"food_name": "Peanut M&Ms"}}],
        SimpleNamespace(total_calories=cal, total_protein=pro),
        SimpleNamespace(calorie_target=cal_t, protein_target=pro_t))


@pytest.mark.parametrize("banned", [
    "Good room left.", "good room left", "Tight finish.", "tight finish",
    "Small add.", "Real meal still needed.", "Go protein-first next.",
])
def test_the_compressed_phrases_are_gone(banned):
    """Named in the directive as the register to leave behind."""
    for cal, pro in ((458, 12), (1200, 170), (1900, 170), (2300, 170)):
        assert banned not in _tail(cal, pro), (banned, cal, pro)


def test_the_calorie_and_protein_states_share_one_bubble():
    """Split across two they read as a pair of status lines, which is the debug
    output the card already owns."""
    bubbles = _tail(458, 12).split("|||")
    assert len(bubbles) == 2, bubbles
    assert "calories" in bubbles[1] and "protein-forward" in bubbles[1]


def test_the_coaching_bubble_is_complete_sentences():
    """Every sentence starts as one, and the bubble as a whole is prose rather
    than a status line.

    Deliberately NOT a per-sentence word count. "Good room left." (banned) and
    "Protein's tracking well." (fine) are both three words — the difference is
    a subject and a verb, not length, and a length threshold that separated
    them would be a coincidence rather than a rule. The named fragments are
    pinned directly in test_the_compressed_phrases_are_gone; this asserts the
    shape around them.
    """
    for cal, pro in ((458, 12), (1200, 170), (1900, 170), (2300, 170)):
        coaching = _tail(cal, pro).split("|||")[-1]
        sentences = [s.strip() for s in coaching.split(". ") if s.strip()]
        assert len(coaching.split()) >= 12, (coaching, cal, pro)
        for sentence in sentences:
            assert sentence[0].isupper(), (sentence, cal, pro)


def test_no_slash_totals_survive_anywhere_in_the_tail():
    """"458 / 2165 calories" is a progress bar someone typed out."""
    import re
    for cal, pro in ((458, 12), (1200, 170), (1900, 170), (2300, 170)):
        assert not re.search(r"\d+\s*/\s*\d+", _tail(cal, pro))
