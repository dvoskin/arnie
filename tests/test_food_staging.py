"""Staged food items (directive 2026-07-25, build order 1, 2, 13).

The failures these close, all of which follow from treating ambiguity as one
meal-level boolean:

  • a clear food gets re-questioned because a neighbour was vague;
  • a vague food gets committed because a neighbour was clear;
  • "14 oz bottle" and "drank 14 oz" land in the same field, and a third of a
    bottle logs as a whole one;
  • a held item gets described as committed.
"""
import pytest

from skills.nutrition.staging import (FoodAssumption, FoodClass, FoodIdentity,
                                      NutrientDeltaRange, PreparationIntent,
                                      Quantity, QuantityIntent,
                                      ResolutionStatus, StagedFoodItem,
                                      classify_food, make_meal_group_id,
                                      make_staged_item_id,
                                      missing_requirements)


def _item(text="a Fairlife", ordinal=0, **kw):
    kw.setdefault("food_class", FoodClass.BRANDED)
    return StagedFoodItem(
        staged_item_id=make_staged_item_id("imessage:G-1", ordinal, text),
        original_text=text, ordinal=ordinal, **kw)


# ── identity and quantity are separate facts ──────────────────────────────────
def test_package_size_is_not_consumed_amount():
    """The failure this prevents: a 14 oz bottle half-drunk logging as 14 oz.
    Package size describes the PRODUCT; consumption describes the event."""
    item = _item(identity=FoodIdentity(brand="Fairlife",
                                       product_line="Core Power Elite",
                                       package_size=Quantity(14, "oz")),
                 quantity=QuantityIntent(consumed_fraction=0.5))
    assert item.identity.package_size.amount == 14
    assert item.quantity.consumed_fraction == 0.5
    assert item.quantity.stated_amount is None      # nothing implied
    assert item.quantity.describe() == "half"


def test_known_identity_with_unknown_amount():
    item = _item(identity=FoodIdentity(brand="Fairlife",
                                       product_line="Core Power Elite"),
                 quantity=QuantityIntent(descriptor="some"))
    assert item.identity.known_fields() == ("brand", "product_line")
    assert item.quantity.is_vague


def test_exact_amount_with_unknown_identity():
    """The mirror case. One "how sure are we" number could not tell these
    apart, and they need opposite questions."""
    item = _item(identity=FoodIdentity(brand="Fairlife"),
                 quantity=QuantityIntent(stated_amount=14, stated_unit="oz"))
    assert item.quantity.is_stated and not item.quantity.is_vague
    assert item.identity.product_line is None


def test_a_stated_amount_is_distinguishable_from_an_inferred_one():
    """"6 oz" and "we estimated 170 g" must never read the same. One is the
    user's word; the other is ours."""
    stated = QuantityIntent(stated_amount=6, stated_unit="oz")
    inferred = QuantityIntent(descriptor="a handful", estimated_mass_g=45,
                              mass_confidence=0.68)
    assert stated.is_stated and not inferred.is_stated
    assert inferred.mass_confidence == 0.68


# ── per-class completeness ────────────────────────────────────────────────────
def test_a_brand_alone_is_not_an_identity():
    """Fairlife makes four products with materially different nutrition.
    "a Fairlife" is a brand, not a product."""
    item = _item(identity=FoodIdentity(brand="Fairlife"),
                 quantity=QuantityIntent(container_count=1))
    assert "identity" in missing_requirements(item)


def test_brand_plus_product_line_is_an_identity():
    item = _item(identity=FoodIdentity(brand="Fairlife",
                                       product_line="Core Power Elite"),
                 quantity=QuantityIntent(container_count=1))
    assert "identity" not in missing_requirements(item, serving_basis_known=True)


def test_a_barcode_is_sufficient_identity_on_its_own():
    item = _item(identity=FoodIdentity(barcode="0081111"),
                 quantity=QuantityIntent(container_count=1))
    assert "identity" not in missing_requirements(item, serving_basis_known=True)


def test_branded_needs_a_serving_basis_and_generic_does_not():
    """One universal completeness check would be wrong for both."""
    branded = _item(identity=FoodIdentity(brand="Fairlife",
                                          product_line="Core Power"),
                    quantity=QuantityIntent(container_count=1))
    generic = _item("chicken breast", food_class=FoodClass.GENERIC,
                    identity=FoodIdentity(canonical_name="chicken breast"),
                    quantity=QuantityIntent(stated_amount=200,
                                            stated_unit="g"))
    assert "serving_basis" in missing_requirements(branded)
    assert missing_requirements(generic) == ()


def test_a_missing_amount_is_reported_for_every_class():
    for cls in (FoodClass.BRANDED, FoodClass.GENERIC, FoodClass.RESTAURANT,
                FoodClass.COMPOSITE):
        item = _item("thing", food_class=cls,
                     identity=FoodIdentity(canonical_name="thing",
                                           brand="B", product_line="L"),
                     quantity=QuantityIntent(descriptor="some"))
        assert "consumed_quantity" in missing_requirements(
            item, serving_basis_known=True)


# ── status ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("status,committable", [
    (ResolutionStatus.RESOLVED_EXACT, True),
    (ResolutionStatus.RESOLVED_ESTIMATED, True),
    (ResolutionStatus.NEEDS_CLARIFICATION, False),
    (ResolutionStatus.UNRESOLVED, False),
    (ResolutionStatus.REJECTED, False),
])
def test_a_held_item_is_structurally_undescribable_as_committed(status,
                                                                committable):
    """The renderer reads this property. No held item is ever narrated as
    logged."""
    assert _item().with_status(status).resolution_status.is_committable is committable


# ── resolution keeps the row ──────────────────────────────────────────────────
def test_answering_fills_fields_without_moving_the_row():
    """The whole point of staging: an answer an hour later still names exactly
    one item, and updates it rather than re-identifying it."""
    item = _item(identity=FoodIdentity(brand="Fairlife"),
                 quantity=QuantityIntent(descriptor="some"))
    original_id = item.staged_item_id

    resolved = item.resolving(product_line="Core Power Elite",
                              package_size=Quantity(14, "oz"),
                              consumed_fraction=0.5)
    assert resolved.staged_item_id == original_id
    assert resolved.identity.product_line == "Core Power Elite"
    assert resolved.identity.brand == "Fairlife"        # untouched
    assert resolved.identity.package_size.amount == 14
    assert resolved.quantity.consumed_fraction == 0.5
    assert resolved.original_text == item.original_text


def test_answering_clears_only_the_ambiguities_it_settled():
    from skills.nutrition.ambiguity import (AmbiguityType, FoodAmbiguity)
    item = _item().with_ambiguities([
        FoodAmbiguity(ambiguity_id="a1", staged_item_id="i",
                      ambiguity_type=AmbiguityType.PRODUCT_LINE,
                      field_name="product_line"),
        FoodAmbiguity(ambiguity_id="a2", staged_item_id="i",
                      ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
                      field_name="consumed_fraction")])
    resolved = item.resolving(product_line="Core Power Elite")
    assert [a.field_name for a in resolved.ambiguities] == ["consumed_fraction"]


# ── a partial answer to a bundled question ────────────────────────────────────
# "Which Fairlife was it, and how much did you drink?" names two ambiguities.
# `answering()` used to clear every ambiguity the QUESTION named, so "Elite"
# cleared the quantity as well and the item committed with a product we knew and
# an amount we had invented. Bundled questions get partial answers routinely.
def _bundled_item():
    from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
    return _item(identity=FoodIdentity(brand="Fairlife"),
                 quantity=QuantityIntent(descriptor="some")).with_ambiguities([
        FoodAmbiguity(ambiguity_id="a1", staged_item_id="i",
                      ambiguity_type=AmbiguityType.PRODUCT_LINE,
                      field_name="product_line"),
        FoodAmbiguity(ambiguity_id="a2", staged_item_id="i",
                      ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
                      field_name="consumed_fraction")])


class _Q:
    """The bundled question: both ambiguities, asked in one sentence."""
    ambiguity_ids = ("a1", "a2")
    requested_fields = ("product_line", "consumed_fraction")


def test_naming_the_product_leaves_the_quantity_open():
    resolved = _bundled_item().answering(_Q(), product_line="Core Power Elite")
    assert resolved.identity.product_line == "Core Power Elite"
    assert [a.ambiguity_id for a in resolved.ambiguities] == ["a2"]


def test_giving_the_amount_leaves_the_product_open():
    resolved = _bundled_item().answering(_Q(), consumed_fraction=0.5)
    assert resolved.quantity.consumed_fraction == 0.5
    assert [a.ambiguity_id for a in resolved.ambiguities] == ["a1"]


def test_answering_both_settles_both():
    resolved = _bundled_item().answering(_Q(), product_line="Core Power Elite",
                                         consumed_fraction=0.5)
    assert resolved.ambiguities == ()


def test_an_answer_in_a_different_shape_still_settles_the_quantity():
    """"about a cup" answers a mass question with an amount and a unit. Settling
    by field name alone left it standing and the next round re-asked it."""
    resolved = _bundled_item().answering(_Q(), stated_amount=8.0,
                                         stated_unit="oz")
    assert [a.ambiguity_id for a in resolved.ambiguities] == ["a1"]


def test_a_vague_descriptor_settles_nothing():
    """"some" is the vagueness, not its resolution."""
    resolved = _bundled_item().answering(_Q(), descriptor="a bit")
    assert {a.ambiguity_id for a in resolved.ambiguities} == {"a1", "a2"}


def test_a_caller_that_knows_what_it_settled_is_believed():
    resolved = _bundled_item().answering(_Q(), settled_ambiguity_ids=("a2",),
                                         product_line="Core Power Elite")
    assert [a.ambiguity_id for a in resolved.ambiguities] == ["a1"]


# ── identity of the row itself ────────────────────────────────────────────────
def test_item_ids_are_stable_within_a_turn_and_unique_across_items():
    a = make_staged_item_id("imessage:G-1", 0, "a Fairlife")
    again = make_staged_item_id("imessage:G-1", 0, "a Fairlife")
    sibling = make_staged_item_id("imessage:G-1", 1, "some turkey")
    other_turn = make_staged_item_id("imessage:G-2", 0, "a Fairlife")
    assert a == again
    assert a != sibling and a != other_turn


def test_a_meal_group_is_shared_by_the_whole_turn():
    """Partial commit plus a later completion must land in one card, not two
    disconnected ones."""
    assert make_meal_group_id("imessage:G-1") == make_meal_group_id("imessage:G-1")
    assert make_meal_group_id("imessage:G-1") != make_meal_group_id("imessage:G-2")


# ── assumptions are objects, not prose ────────────────────────────────────────
def test_an_assumption_carries_what_it_could_cost():
    a = FoodAssumption(
        staged_item_id="item_1", field_name="estimated_mass_g",
        assumed_value=45, alternatives=(30, 60), confidence=0.71,
        nutrition_impact=NutrientDeltaRange(calories=25),
        user_visible_text="Estimated the small handful of blueberries at about ½ cup.")
    assert a.nutrition_impact.is_material
    assert "½ cup" in a.describe()
    assert a.alternatives == (30, 60)      # what it could have been


def test_an_assumption_without_prose_still_explains_itself():
    a = FoodAssumption(staged_item_id="i", field_name="consumed_fraction",
                       assumed_value=1.0)
    assert "consumed fraction" in a.describe()


# ── classification ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,brand,packaged,expected", [
    ("Core Power Elite", "Fairlife", False, FoodClass.BRANDED),
    ("some bar", None, True, FoodClass.BRANDED),
    ("chicken breast", None, False, FoodClass.GENERIC),
    ("Starbucks turkey bacon sandwich", None, False, FoodClass.RESTAURANT),
    ("chicken shawarma platter", None, False, FoodClass.COMPOSITE),
    ("", None, False, FoodClass.UNKNOWN),
])
def test_food_class_from_the_words(name, brand, packaged, expected):
    assert classify_food(name, brand, packaged) is expected
