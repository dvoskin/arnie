"""The staged resolution survives the turn that produced it.

Cause A. A clarification is a question about an item the lane has already
resolved — classified, scored, priced, with its assumptions recorded. The
pending row persisted the question text and a `staged_item_id` pointing at an
object that no longer existed, so the answering turn re-interpreted from the raw
message and re-ran the whole ladder. Production, in one window:

  * 22:59 asked "around 580 cal, 10g protein"; the answer turn searched the
    cheesecake again, cost 16.2s, and logged 8g. Two pricings, disagreeing.
  * 00:49 held a photo, the user said "It's sopresseta" at 00:54, and thirteen
    hours later the answer turn logged "Dollar pizza slices, plain" — a cold
    re-interpretation reaching for their most common pizza over a fact stated
    in the same thread.

These assert on BEHAVIOUR — encode, decode, compare — rather than on the source
containing the right words. `test_a_correction_re_resolves.py:138` asserted the
executor's source text contained "correction_unpriced" while the disclosure had
never fired in production for anyone; a grep stood in for the behaviour and the
gap survived a release.
"""
import json
from dataclasses import replace

import pytest

from skills.nutrition.ambiguity import AmbiguityOption, AmbiguityType, FoodAmbiguity
from skills.nutrition.candidate_sets import ProductCandidate
from skills.nutrition.models import NutrientProfile
from skills.nutrition.provenance import NutrientValue, SourceTier
from skills.nutrition.staged_codec import (STAGED_CODEC_VERSION, decode_item,
                                           decode_items, encode_item,
                                           encode_items)
from skills.nutrition.staging import (FoodAssumption, FoodClass, FoodIdentity,
                                      NutrientDeltaRange, PreparationIntent,
                                      Quantity, QuantityIntent,
                                      ResolutionStatus, StagedFoodItem)


def _priced_item() -> StagedFoodItem:
    """A fully-resolved item, of the shape the lane holds when it decides to
    ask about ONE remaining dimension."""
    profile = NutrientProfile(values={
        "calories": NutrientValue(value=290.0, unit="kcal", source="usda",
                                  confidence=0.9, basis="per_100g",
                                  source_id="171284"),
        "protein": NutrientValue(value=5.5, unit="g", source="usda",
                                 confidence=0.9, basis="per_100g",
                                 source_id="171284"),
    })
    candidate = ProductCandidate(
        candidate_id="cand_1", canonical_name="Junior's Original Cheesecake",
        brand="Junior's", serving_basis="per_100g", source="usda",
        tier=SourceTier.GENERIC_EXACT, source_id="171284",
        identity_score=0.8, overall_score=0.77,
        nutrient_profile=profile, match_grade="close")
    ambiguity = FoodAmbiguity(
        ambiguity_id="amb_1", staged_item_id="stg_1",
        ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
        field_name="stated_amount",
        candidate_values=(
            AmbiguityOption(label="a slice", confidence=0.6,
                            payload=1, candidate_id="cand_1"),
            AmbiguityOption(label="half a slice", confidence=0.3, payload=0.5)),
        calorie_span=190.0, protein_span=4.0, confidence=0.6,
        materiality_score=1.4, clarification_prompt="A whole slice, or half?",
        impact_basis_cal=580.0)
    return StagedFoodItem(
        staged_item_id="stg_1", original_text="a slice of the cheesecake",
        ordinal=0, food_class=FoodClass.RESTAURANT,
        identity=FoodIdentity(canonical_name="Junior's Original Cheesecake",
                              brand="Junior's",
                              package_size=Quantity(amount=1.0, unit="slice")),
        quantity=QuantityIntent(inferred_amount=1.0, inferred_unit="slice",
                                descriptor="a slice",
                                mass_range_g=(120.0, 200.0)),
        vague_measure="a slice",
        preparation=PreparationIntent(method="baked", stated=False,
                                      modifiers=("no topping",)),
        candidate_products=(candidate,),
        ambiguities=(ambiguity,),
        resolution_status=ResolutionStatus.NEEDS_CLARIFICATION,
        assumptions=(FoodAssumption(
            staged_item_id="stg_1", field_name="stated_amount",
            assumed_value=1.0, alternatives=(0.5, 2.0), confidence=0.6,
            nutrition_impact=NutrientDeltaRange(calories=190.0, protein=4.0),
            user_visible_text="Assumed one slice."),),
        meal_group_id="meal_1")


def test_the_whole_resolution_survives_a_round_trip():
    item = _priced_item()
    back = decode_item(encode_item(item))
    assert back is not None
    # Equality across the whole frozen graph — identity, quantity, preparation,
    # candidates, ambiguities, assumptions. This is the assertion that makes an
    # answering turn able to APPLY rather than re-resolve.
    assert back == item


def test_it_survives_actual_json_because_that_is_where_it_is_stored():
    """The pending payload is a JSON column. A codec that round-trips in
    memory but not through `json.dumps` would fail only in production."""
    item = _priced_item()
    back = decode_item(json.loads(json.dumps(encode_item(item))))
    assert back == item


def test_the_anchor_and_the_basis_cross_the_boundary():
    """The two fields that make the answer turn a zero-lookup commit: an
    `fdc_id`, and what the number was measured against. Without them the stored
    resolution is a claim about a word and the ladder has to run again."""
    back = decode_item(encode_item(_priced_item()))
    candidate = back.candidate_products[0]
    assert candidate.source_id == "171284"
    assert candidate.nutrient_profile.get("calories").basis == "per_100g"
    assert candidate.nutrient_profile.get("calories").value == 290.0
    assert candidate.tier is SourceTier.GENERIC_EXACT


def test_an_inferred_amount_does_not_come_back_stated():
    """`stated_*` and `inferred_*` are separate fields precisely so a number we
    chose can never be reported as one the user gave. A round trip that merged
    them would launder the assumption — "a scoop" reaching a later turn as a
    fact they had supplied."""
    back = decode_item(encode_item(_priced_item()))
    assert back.quantity.inferred_amount == 1.0
    assert back.quantity.stated_amount is None
    assert back.quantity.is_stated is False
    assert back.quantity.is_inferred is True


def test_an_inferred_preparation_does_not_come_back_stated():
    """§4.2b: "pan fried" was the user's word about ONE steak, and became a
    standing default on every later one. `stated` is what tells those apart, so
    it may not be invented by the codec."""
    back = decode_item(encode_item(_priced_item()))
    assert back.preparation.method == "baked"
    assert back.preparation.stated is False

    said_it = replace(_priced_item(),
                      preparation=PreparationIntent(method="pan fried",
                                                    stated=True))
    assert decode_item(encode_item(said_it)).preparation.stated is True


def test_an_unknown_nutrient_stays_unknown():
    """`NutrientProfile` omits what it does not know rather than zero-filling.
    A codec that defaulted on the way out would turn "we never learned the
    sodium" into "the sodium is zero"."""
    back = decode_item(encode_item(_priced_item()))
    profile = back.candidate_products[0].nutrient_profile
    assert "sodium" not in profile.values
    assert profile.get("sodium") is None
    assert profile.amount("sodium") is None
    assert "sodium" in profile.unknown()


def test_a_nutrient_whose_value_will_not_read_is_dropped_not_zeroed():
    """The other half, and the one a round-trip test does not reach on its
    own: a nutrient key that IS present but whose number is missing or corrupt.
    Decoding it to 0.0 would put "0 cal" on a row we simply could not read —
    absent restated as zero, which is `8c7dff6`'s defect one layer down.

    Found by mutating the codec to `_num(...) or 0.0` and watching every other
    test in this file still pass.
    """
    payload = encode_item(_priced_item())
    profile = payload["candidate_products"][0]["nutrient_profile"]
    profile["calories"]["value"] = None
    profile["protein"]["value"] = "not a number"

    back = decode_item(payload)
    assert back is not None
    values = back.candidate_products[0].nutrient_profile.values
    assert "calories" not in values, "an unreadable calorie count became a number"
    assert "protein" not in values
    assert back.candidate_products[0].calories is None


def test_the_span_survives_so_a_re_ask_can_still_weigh_itself():
    """The spans are what turn "we're unsure" into "being wrong costs 190
    calories" — the only basis on which interrupting someone is justifiable."""
    back = decode_item(encode_item(_priced_item()))
    amb = back.ambiguities[0]
    assert amb.calorie_span == 190.0
    assert amb.impact_basis_cal == 580.0
    assert amb.is_material is True
    assert [o.label for o in amb.candidate_values] == ["a slice",
                                                       "half a slice"]
    assert amb.candidate_values[0].candidate_id == "cand_1"


def test_the_users_own_vague_word_crosses_the_boundary():
    """A meal clarified over two turns is exactly the case `vague_measure`
    exists for — the word was in the first message and the item now carries a
    resolved name that never appeared there."""
    assert decode_item(encode_item(_priced_item())).vague_measure == "a slice"


def test_the_stored_resolution_is_what_answering_applies_to():
    """The point of persisting it: `resolving()` is a pure function over the
    decoded item, so the answer settles the field with no lookup."""
    back = decode_item(encode_item(_priced_item()))
    answered = back.resolving(stated_amount=0.5, stated_unit="slice")
    assert answered.quantity.stated_amount == 0.5
    assert answered.quantity.is_stated is True
    # The ambiguity the answer settled is gone; identity is untouched, which is
    # what makes a late answer safe.
    assert answered.ambiguities == ()
    assert answered.identity == back.identity
    assert answered.candidate_products[0].source_id == "171284"


@pytest.mark.parametrize("bad", [
    None, "", 42, [], {}, {"staged_item_id": "x"},
    {"v": STAGED_CODEC_VERSION}, {"v": "staged_v0", "staged_item_id": "x"},
])
def test_an_unreadable_payload_is_none_not_an_exception(bad):
    """Losing a resolution costs one re-interpretation — today's behaviour.
    Raising would cost the turn."""
    assert decode_item(bad) is None


def test_a_future_version_declines_rather_than_misreading():
    """A shape change must degrade to re-interpretation, not decode a stale
    payload into the wrong fields."""
    payload = encode_item(_priced_item())
    payload["v"] = "staged_v99"
    assert decode_item(payload) is None


def test_a_partial_list_recovers_the_items_that_read():
    """One unreadable item must not cost the others their resolutions."""
    good = encode_item(_priced_item())
    decoded = decode_items([good, {"v": "staged_v99"}, "nonsense", good])
    assert len(decoded) == 2
    assert all(i.staged_item_id == "stg_1" for i in decoded)


def test_empty_and_default_items_round_trip():
    """The degenerate item — nothing resolved yet — must survive too, or the
    ask path has to special-case it."""
    item = StagedFoodItem(staged_item_id="stg_bare", original_text="cucumber")
    back = decode_item(encode_item(item))
    assert back == item
    assert encode_items(()) == []
    assert decode_items(None) == ()
