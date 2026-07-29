"""The answering turn applies the stored resolution instead of re-deriving it.

Cause A, wired. `test_the_ask_carries_the_resolution.py` covers the codec; this
covers what the lane does with it — the application rules, and the two seams the
payload has to cross:

  ask return  ->  `staged_items` on the dict `core/conversation.py` stashes
  pending row ->  `parse_prior_answer`'s `prior`, decoded and applied

The rule the production trace turns on is that **an answer which changes
identity is not an application**. "It's sopresseta" replaces the food, so the
stored per-100g basis describes something else and re-resolution is correct.
An answer about the portion of the same food is arithmetic. Getting that
backwards prices the wrong food, which is the "Dollar pizza slices" write.
"""
import json
import os
from dataclasses import replace

import pytest

from skills.nutrition.answer_application import (apply_answer, changes_identity,
                                                 commit_from_answer, find_item,
                                                 price_from_resolution)
from skills.nutrition.candidate_sets import ProductCandidate
from skills.nutrition.models import NutrientProfile
from skills.nutrition.provenance import NutrientValue, SourceTier
from skills.nutrition.staged_codec import encode_items
from skills.nutrition.staging import (FoodClass, FoodIdentity, PreparationIntent,
                                      QuantityIntent, ResolutionStatus,
                                      StagedFoodItem)


def _per100g(calories: float, protein: float) -> NutrientProfile:
    return NutrientProfile(values={
        "calories": NutrientValue(value=calories, unit="kcal", source="usda",
                                  basis="per_100g", source_id="171284"),
        "protein": NutrientValue(value=protein, unit="g", source="usda",
                                 basis="per_100g", source_id="171284"),
    })


def _sopressata() -> StagedFoodItem:
    """A held item priced per 100 g, waiting on how much was eaten."""
    return StagedFoodItem(
        staged_item_id="stg_1", original_text="the sopressata",
        food_class=FoodClass.BRANDED,
        identity=FoodIdentity(canonical_name="Sopressata", brand="Seppe"),
        quantity=QuantityIntent(descriptor="some"),
        candidate_products=(ProductCandidate(
            candidate_id="c1", canonical_name="Sopressata", brand="Seppe",
            serving_basis="per_100g", source="usda",
            tier=SourceTier.BRANDED_EXACT, source_id="171284",
            overall_score=0.9, nutrient_profile=_per100g(400.0, 22.0),
            match_grade="exact"),),
        resolution_status=ResolutionStatus.NEEDS_CLARIFICATION,
        meal_group_id="meal_1")


# ── which answers may be applied ──────────────────────────────────────────────
def test_a_portion_answer_is_arithmetic_on_the_stored_basis():
    item = _sopressata()
    priced = price_from_resolution(
        apply_answer(item, {"estimated_mass_g": 50.0}))
    assert priced is not None
    # 400 cal / 100 g at 50 g. No lookup ran to produce this.
    assert priced["calories"] == pytest.approx(200.0, abs=1.0)
    assert priced["protein"] == pytest.approx(11.0, abs=0.5)
    assert priced["food"] == "Seppe Sopressata"


def test_a_brand_does_not_get_logged_as_the_food():
    """`FoodIdentity.describe()` prefers the canonical name only when it has
    MORE words than the brand — so a one-word food under a one-word brand
    describes as the brand alone. Caught by this test failing with "Seppe":
    the row would have said the user ate a brand.

    `describe()` itself is untouched (it names cards, questions and replies
    everywhere); the write-side name is repaired where the row is built.
    """
    item = _sopressata()
    assert item.identity.describe() == "Seppe"      # the underlying behaviour
    priced = price_from_resolution(
        apply_answer(item, {"estimated_mass_g": 50.0}))
    assert priced["food"] == "Seppe Sopressata"


def test_a_name_already_containing_the_brand_is_not_doubled():
    item = replace(_sopressata(),
                   identity=FoodIdentity(canonical_name="Royo Everything Bagel",
                                         brand="Royo"))
    priced = price_from_resolution(
        apply_answer(item, {"estimated_mass_g": 50.0}))
    assert priced["food"] == "Royo Everything Bagel"


@pytest.mark.parametrize("answer", [
    {"canonical_name": "Dollar pizza slices, plain"},
    {"brand": "Royo"},
    {"variant": "hot"},
    {"barcode": "0123456789012"},
])
def test_an_answer_that_changes_identity_is_not_applied(answer):
    """The stored pricing describes the OLD food. Declining here is what sends
    the turn back through re-resolution — the correct, more expensive path."""
    assert changes_identity(answer) is True
    assert apply_answer(_sopressata(), answer) is None
    assert commit_from_answer(encode_items([_sopressata()]), "stg_1",
                              answer) is None


def test_an_answer_settling_nothing_applicable_declines():
    assert apply_answer(_sopressata(), {}) is None
    assert apply_answer(_sopressata(), {"unrelated_field": 1}) is None


def test_a_stated_preparation_is_recorded_as_stated():
    """§4.2b: an inferred preparation became a standing default because nothing
    distinguished it from one the user gave. An ANSWER is the user giving it."""
    item = replace(_sopressata(),
                   preparation=PreparationIntent(method="raw", stated=False))
    applied = apply_answer(item, {"method": "grilled"})
    assert applied.preparation.method == "grilled"
    assert applied.preparation.stated is True


# ── binding the answer to the right row ───────────────────────────────────────
def test_the_answer_binds_to_the_question_s_own_item():
    other = replace(_sopressata(), staged_item_id="stg_2",
                    original_text="the bread")
    items = (_sopressata(), other)
    assert find_item(items, "stg_2").original_text == "the bread"


def test_an_unmatched_id_binds_to_nothing_rather_than_guessing():
    """Applying an answer to the wrong row is the failure this mechanism
    exists to prevent, so an id that names no held item declines."""
    assert find_item((_sopressata(),), "stg_missing") is None


def test_no_id_and_several_items_declines():
    items = (_sopressata(), replace(_sopressata(), staged_item_id="stg_2"))
    assert find_item(items, "") is None
    assert find_item((_sopressata(),), "") is not None


# ── refusing rather than guessing ─────────────────────────────────────────────
def test_a_vague_helping_against_a_per_serving_row_refuses():
    """`scale_profile` refuses a per-serving row scaled by an estimated
    helping — inventing a factor is how a plate becomes "one serving". The
    caller's fallback is the lookup it already runs."""
    item = replace(
        _sopressata(),
        quantity=QuantityIntent(descriptor="some"),
        candidate_products=(replace(_sopressata().candidate_products[0],
                                    serving_basis="per_serving"),))
    assert price_from_resolution(item) is None


def test_a_candidate_with_no_numbers_declines():
    item = replace(_sopressata(),
                   candidate_products=(replace(
                       _sopressata().candidate_products[0],
                       nutrient_profile=None),))
    assert price_from_resolution(apply_answer(
        item, {"estimated_mass_g": 50.0})) is None


def test_no_candidates_at_all_declines():
    item = replace(_sopressata(), candidate_products=())
    assert price_from_resolution(apply_answer(
        item, {"estimated_mass_g": 50.0})) is None


def test_an_unreadable_payload_declines_without_raising():
    assert commit_from_answer(None, "stg_1", {"estimated_mass_g": 50.0}) is None
    assert commit_from_answer([], "stg_1", {"estimated_mass_g": 50.0}) is None
    assert commit_from_answer([{"v": "staged_v99"}], "stg_1",
                              {"estimated_mass_g": 50.0}) is None


# ── the seams ─────────────────────────────────────────────────────────────────
def test_the_payload_survives_the_pending_row_and_still_commits():
    """The whole crossing: encode at the ask, `json.dumps` into
    `pending_questions.payload_json`, read back on the answer turn, apply."""
    stored = json.dumps({"staged_items": encode_items([_sopressata()]),
                         "staged_item_id": "stg_1"})
    prior = json.loads(stored)
    priced = commit_from_answer(prior["staged_items"],
                                prior["staged_item_id"],
                                {"estimated_mass_g": 50.0})
    assert priced is not None
    assert priced["calories"] == pytest.approx(200.0, abs=1.0)


def test_the_ask_return_carries_the_held_item_and_not_the_committed_ones():
    """Only HELD items travel. Carrying a food that was just committed forward
    into a later turn is cause C's residue — the "Thanks" turn that wrote two
    foods its own message never mentioned."""
    from core.food_pipeline import FoodTurnDecision
    from skills.nutrition.clarify_policy import ClarificationDecision

    held = _sopressata()
    ready = replace(_sopressata(), staged_item_id="stg_ready",
                    original_text="the bread")
    decision = FoodTurnDecision(
        staged_items=(held, ready),
        clarification=ClarificationDecision(ready_item_ids=("stg_ready",),
                                            held_item_ids=("stg_1",)))
    held_ids = set(decision.clarification.held_item_ids)
    payload = encode_items([i for i in decision.staged_items
                            if i.staged_item_id in held_ids])
    assert [p["staged_item_id"] for p in payload] == ["stg_1"]


def test_the_write_path_is_off_by_default_and_shadows():
    """A new write path ships shadowed, like `FOOD_FAST_PATH`. The switch is
    thrown on an agreement rate from real traffic, not on this test."""
    from core.food_turn import answer_apply_enabled
    assert answer_apply_enabled() is False, (
        "FOOD_ANSWER_APPLY must default off — it is a new write path")
    os.environ["FOOD_ANSWER_APPLY"] = "true"
    try:
        assert answer_apply_enabled() is True
    finally:
        os.environ.pop("FOOD_ANSWER_APPLY", None)


def test_the_priced_item_builds_a_real_log_call():
    """`price_from_resolution` returns the interpreter's item shape, so the
    existing `_log_call` builder — not a second one — makes the write."""
    from core.food_turn import _log_call

    priced = commit_from_answer(encode_items([_sopressata()]), "stg_1",
                                {"estimated_mass_g": 50.0})
    call = _log_call(priced)
    assert call is not None
    assert call["name"] == "log_food"
    assert call["input"]["food_name"] == "Seppe Sopressata"
    assert call["input"]["calories"] == pytest.approx(200.0, abs=1.0)
    assert call["input"]["is_packaged"] is True
