"""Directive §14 and §15 — the four shipped failures, and the release gate.

§14 asks for four exact regression transcripts. Each one below is a real
conversation that shipped, replayed at the layer where it actually broke rather
than forced through a single harness. Forcing them all through the
clarification runner would have meant asserting on proxies, and a proxy that
passes while the screenshot is still wrong is worse than no test.

  A. The 33% meal — two named products with published labels, answered from
     generic data, on a ladder that was the same for every food.
  B. "A scoop of peanut butter" reaching a review turn as "1 tbsp Peanut
     Butter — does that look right?", a 190-calorie assumption wearing the
     user's authority.
  C. "Protein covered · 2,320 cal over", and directly beneath it, "You're on
     pace, so there's nothing to correct."
  D. The card read back underneath itself, in language no one uses: "two large
     pieces of eggs", "0.5 bagel".

§15 is the release gate: the criteria that must hold together, not one at a
time. They are at the bottom, and they are assertions rather than a checklist
because a checklist cannot fail a build.
"""
import pytest

from core.food_intelligence import analyze
from core.receipt import build_receipt
from skills.nutrition import authority
from skills.nutrition.normalize import normalize_quantity


# ══ A. The meal that ran 33% high ═══════════════════════════════════════════
#
# Logged: a bagel, Philadelphia scallion cream cheese, half a Starbucks turkey
# bacon sandwich, salmon. Shipped 560 cal against an actual 420. The bagel and
# the salmon — the two that needed no branded lookup — were both right. 105 of
# the 140 calorie overcount came from the two named products, each of which has
# a published label that was never consulted, because selection was
# `memory or usda or off or web` for every food alike.

def _usda(cal, **macros):
    return {"per100g": dict(calories=cal, **macros), "_match": "likely",
            "fdc_id": "usda-row"}


def _label(cal, **macros):
    return {"per100g": dict(calories=cal, **macros), "_match": "exact",
            "fdc_id": "label"}


def test_A_a_named_product_is_not_answered_from_generic_data():
    """Philadelphia scallion cream cheese: 100 shipped against a 60 label."""
    result = analyze("Philadelphia scallion cream cheese", "2 tbsp",
                     100, 2, 2, 9,
                     usda_candidate=_usda(342), web_candidate=_label(200),
                     is_packaged=True)
    assert result.provenance.food_class == authority.FoodClass.MANUFACTURED.value
    assert result.provenance.rung == "manufacturer"


def test_A_a_menu_item_is_not_answered_from_usda_at_all():
    """Half a Starbucks turkey bacon sandwich: 180 shipped against 115. USDA
    has no row for a chain's menu item, so against one it is not a weaker
    answer — it is not an answer."""
    result = analyze("Starbucks turkey bacon sandwich", "half", 115, 12, 10, 3,
                     usda_candidate=_usda(250, protein=12, sodium=500))
    assert result.provenance.food_class == authority.FoodClass.RESTAURANT.value
    assert result.calories == 115
    # Not discarded — it fills the panel it can legitimately fill.
    assert result.provenance.micronutrient_source == "usda_generic"


def test_A_the_items_that_were_already_right_stay_right():
    """The fix must not cost the cases the old ladder handled. A bagel and a
    piece of salmon need no branded lookup and USDA has both."""
    salmon = analyze("salmon", "150g", 250, 22, 0, 14,
                     usda_candidate=_label(200, protein=20, fat=12))
    assert salmon.provenance.rung == "usda_exact"
    assert salmon.calories == 300           # forward from 150 g × density

    bagel = analyze("everything bagel", "1 bagel", 280, 11, 55, 2,
                    usda_candidate=_usda(270, protein=11, carbs=53))
    assert bagel.provenance.food_class == authority.FoodClass.GENERIC.value


def test_A_the_card_does_not_credit_a_source_that_only_supplied_sodium():
    """The same meal's card said "From the USDA database" under numbers USDA
    never produced — it had contributed the sodium."""
    result = analyze("Starbucks turkey bacon sandwich", "half", 115, 12, 10, 3,
                     usda_candidate=_usda(250, sodium=600))
    detail = authority.display_detail(result.provenance)
    assert "From the USDA database" not in detail
    assert "supplemented" in detail


# ══ B. The scoop of peanut butter ═══════════════════════════════════════════
#
# "I had like 15 peanut m&m, half a banana and a scoop of peanut butter." The
# review turn said "1 tbsp Peanut Butter" and asked "Does that look right?" — a
# scoop is plausibly one tablespoon or three, a span of roughly 190 calories,
# and the user was invited to approve a number they had never been shown being
# chosen.

MESSAGE_B = "like 15 peanut m&m, half a banana and a scoop of peanut butter"


def test_B_a_converted_measure_is_never_reported_as_the_users_own():
    from core.food_turn import _item_is_stated
    assert _item_is_stated(
        {"food": "peanut butter", "amount": 1, "unit": "tbsp"}, MESSAGE_B
    ) is False


def test_B_the_amounts_the_user_did_state_are_not_re_asked():
    """The same message states two amounts exactly. Asking about those is the
    friction that made strict mode feel like an interrogation."""
    from core.food_turn import _item_is_stated
    assert _item_is_stated(
        {"food": "banana", "amount": 0.5, "unit": "banana"}, MESSAGE_B) is True
    assert _item_is_stated(
        {"food": "peanut m&m", "amount": 15, "unit": "piece"}, MESSAGE_B) is True


def test_B_an_assumption_we_made_is_disclosed_as_ours():
    q = normalize_quantity("2 eggs", "eggs")
    assert any("assumed large egg" in a for a in q.assumptions)


def test_B_the_users_words_survive_normalization():
    """A clarification about the peanut butter reprints the banana line. It
    must not come back as "0.5 banana"."""
    assert normalize_quantity("half a banana", "banana").describe() == \
        "half a banana"


# ══ C. "On pace", printed under "2,320 cal over" ════════════════════════════
#
# A shipped card read "Protein covered · 2,320 cal over" with the coach line
# "You're on pace, so there's nothing to correct." directly beneath it. The
# string was meant as a quiet default for a repeat state — the day was already
# over target before this item — but it is a claim, and it was false.

def _card(calories, total_cal, cal_target, total_protein, protein_target,
          protein=20.0, hour=19):
    return build_receipt(
        calories=calories, protein=protein, total_cal=total_cal,
        total_protein=total_protein, cal_target=cal_target,
        protein_target=protein_target, local_hour=hour)


def test_C_never_on_pace_while_over():
    """Any over-target day, whether it went over this item or three items ago."""
    for total in (2500, 3000, 4520):
        out = _card(300, total, 2200, 180, 150)
        assert "on pace" not in out["verdict"].lower(), out["verdict"]
        assert out["remaining_cal"] < 0


def test_C_the_calorie_state_leads_and_protein_does_not_soften_it():
    out = _card(600, 4520, 2200, 190, 150)
    assert "over" in out["verdict"].lower()
    assert "2320" in out["verdict"] or "2,320" in out["verdict"]


def test_C_a_small_overage_is_still_described_as_small():
    """Honest in both directions — 80 calories over is not the fact of the day
    and saying so would be its own kind of wrong."""
    out = _card(200, 2280, 2200, 160, 150)
    assert "on pace" not in out["verdict"].lower()
    assert "2280" not in out["verdict"]


def test_C_under_target_is_untouched():
    out = _card(400, 1400, 2200, 90, 150)
    assert out["remaining_cal"] == 800


# ══ D. The card, read back underneath itself ════════════════════════════════
#
# The deterministic renderer predates the meal card and says everything the
# card says. On a surface where the card renders, the user reads their totals
# twice — the second time in language no one uses.

def _summary(name, portion, branded=False):
    from core.food_response import FoodItemSummary
    return FoodItemSummary(name=name, portion=portion, branded=branded)


@pytest.mark.parametrize("portion,name,expected", [
    ("2 large piece", "eggs", "two large eggs"),
    ("0.5 bagel", "bagel", "half a bagel"),
    ("1 tbsp", "Peanut Butter", "one tablespoon of Peanut Butter"),
    ("15 pieces", "Peanut M&Ms", "15 Peanut M&Ms"),
    ("1 bar", "Barebells", "a Barebells bar"),
])
def test_D_portions_are_said_the_way_a_person_says_them(portion, name, expected):
    from core.food_response import describe_portion
    assert describe_portion(portion, name, branded=name[0].isupper()) == expected


def test_D_the_card_is_not_recited_beneath_itself():
    from core.food_response import (FoodResponseIntent, FoodResponsePlan,
                                    strip_card_recitation)
    plan = FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT,
        committed_items=(_summary("bagel", "1 bagel"),),
        facts_visible_in_card=frozenset({"calories", "protein",
                                         "remaining_calories"}))
    text = ("Logged the bagel, 280 cal and 11g protein. "
            "You're at 1,240 with 960 left.")
    assert strip_card_recitation(text, plan).strip() == ""


def test_D_forward_looking_numbers_earn_their_digits():
    from core.food_response import (FoodResponseIntent, FoodResponsePlan,
                                    strip_card_recitation)
    plan = FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT,
        committed_items=(_summary("bagel", "1 bagel"),),
        facts_visible_in_card=frozenset({"calories", "protein"}))
    text = "I'd aim for 30-40g of protein at lunch."
    assert strip_card_recitation(text, plan).strip() == text


# ══ §15. The release gate ═══════════════════════════════════════════════════
#
# These hold TOGETHER or the release does not go. Each of them was true on its
# own at some point during this work while another was false, which is exactly
# why they are asserted in one place.

def test_gate_every_ladder_ends_in_a_disclosed_fallback():
    """A ladder whose last rung is not a fallback fails silently when nothing
    above it matched — the failure mode with no symptom."""
    for food_class, rungs in authority.LADDERS.items():
        assert rungs[-1] in authority.FALLBACK_RUNGS, food_class


def test_gate_a_named_product_on_a_fallback_rung_always_re_looks_up():
    """Including from cache. A cached generic is the same failure made
    permanent, and it is self-sustaining: the row is rewritten on every reuse."""
    assert authority.needs_branded_lookup(
        authority.FoodClass.MANUFACTURED, "usda_generic") is True
    assert authority.needs_branded_lookup(
        authority.FoodClass.RESTAURANT, "component_estimate") is True


def test_gate_macro_attribution_is_never_borrowed():
    """No display string may name a source that did not determine the displayed
    calories."""
    prov = authority.provenance_for(
        rung="usda_exact", food_class=authority.FoodClass.GENERIC,
        micronutrient_source="usda_exact", macros_from_source=False)
    assert "From the USDA database" not in authority.display_detail(prov)


def test_gate_every_common_fraction_parses():
    for text, expected in (("1/4 cup", 0.25), ("1/3 cup", 1 / 3),
                           ("1/2 cup", 0.5), ("2/3 cup", 2 / 3),
                           ("3/4 cup", 0.75), ("½ cup", 0.5),
                           ("two thirds of a cup", 2 / 3),
                           ("1 1/2 cups", 1.5)):
        assert normalize_quantity(text, "rice").amount == pytest.approx(
            expected), text


def test_gate_an_impossible_portion_is_refused_not_persisted():
    from skills.nutrition import sanity
    from skills.nutrition.models import NormalizedQuantity, NutrientProfile
    from skills.nutrition.provenance import NutrientValue
    from skills.nutrition.scaling import Per100g
    profile = NutrientProfile(values={
        "calories": NutrientValue(value=588.0, unit="kcal", source="usda")})
    findings = sanity.check(
        profile, Per100g(),
        NormalizedQuantity(amount=1, unit="tbsp", grams=16.0))
    assert any(f.is_fatal for f in findings)


def test_gate_the_coach_never_contradicts_the_card():
    assert "on pace" not in _card(300, 4520, 2200, 190, 150)["verdict"].lower()


def test_gate_the_users_own_words_are_what_comes_back():
    for text in ("Half a Bagel", "three-quarters of a cup", "6 oz"):
        assert normalize_quantity(text, "food").describe() == text
