"""Product-family rules and failure states (build order 18, 19).

"A Fairlife" is not under-specified because the user was careless. It is
under-specified because Fairlife sells four product lines in three sizes with
materially different nutrition, and the brand name genuinely does not identify
a product.

The failure states matter just as much: four different things all present as
"we don't have a good answer", and telling a user "I couldn't identify the
product" when USDA was simply down is both wrong and unactionable.
"""
import pytest

from skills.nutrition.families import (CandidateResolutionFailure,
                                       PRODUCT_FAMILIES, classify_failure,
                                       failure_message, required_dimensions,
                                       rule_for)
from skills.nutrition.candidate_sets import ProductCandidate
from skills.nutrition.models import profile_from_values
from skills.nutrition.provenance import SourceTier
from skills.nutrition.staging import FoodIdentity, Quantity


def _cand(name, cal, brand=None, line=None):
    return ProductCandidate(
        candidate_id=name, canonical_name=name, brand=brand, product_line=line,
        tier=SourceTier.BRANDED_EXACT,
        nutrient_profile=profile_from_values("off", calories=cal))


# ── family rules ──────────────────────────────────────────────────────────────
def test_a_brand_alone_leaves_required_dimensions_missing():
    """The Fairlife case: brand known, product unknown."""
    missing = required_dimensions(FoodIdentity(brand="Fairlife"))
    assert set(missing) == {"product_line", "package_size"}


def test_naming_the_line_still_leaves_the_size():
    missing = required_dimensions(
        FoodIdentity(brand="Fairlife", product_line="Core Power Elite"))
    assert missing == ("package_size",)


def test_a_fully_specified_product_needs_nothing():
    assert required_dimensions(FoodIdentity(
        brand="Fairlife", product_line="Core Power Elite",
        package_size=Quantity(14, "oz"))) == ()


def test_a_barcode_satisfies_every_dimension():
    """It IS the product — there is nothing left to disambiguate."""
    assert required_dimensions(FoodIdentity(brand="Fairlife",
                                            barcode="0081111")) == ()


def test_a_brand_with_no_family_rule_requires_nothing():
    """Absence of a rule means no evidence the brand is structurally
    ambiguous — not that every unknown field is mandatory."""
    assert required_dimensions(FoodIdentity(brand="Some Local Bakery")) == ()


def test_the_rule_is_found_via_an_alias_in_the_food_name():
    assert rule_for(None, "a fair life core power").brand == "Fairlife"
    assert rule_for(None, "rx bar chocolate").brand == "RXBAR"
    assert rule_for(None, "mcdonald's fries").brand == "McDonald's"


def test_the_longest_alias_match_wins():
    """"core power" is more specific than "fairlife" when both appear."""
    rule = rule_for("Fairlife", "fairlife core power elite")
    assert rule is not None
    assert "package_size" in rule.required_identity_fields


def test_kind_needs_only_the_flavour():
    """Flavour drives nuts vs fruit vs chocolate — a material swing — but KIND
    has one product line, so asking about it would be noise."""
    assert PRODUCT_FAMILIES["kind"].required_identity_fields == ("variant",)
    assert required_dimensions(FoodIdentity(brand="KIND")) == ("variant",)


def test_every_family_rule_names_at_least_one_required_dimension():
    """A rule requiring nothing is a rule that does nothing."""
    for key, rule in PRODUCT_FAMILIES.items():
        assert rule.required_identity_fields, key
        assert rule.brand, key
        # Required and optional must not overlap — a field cannot both block
        # and not block.
        assert not (set(rule.required_identity_fields)
                    & set(rule.optional_fields)), key


def test_rules_encode_dimensions_not_conversational_copy():
    """A new brand should need new data, not new prose."""
    for rule in PRODUCT_FAMILIES.values():
        for name in (*rule.required_identity_fields, *rule.optional_fields):
            assert name in FoodIdentity.__dataclass_fields__, name


# ── failure states ────────────────────────────────────────────────────────────
def test_several_plausible_products_is_ambiguity_not_failure():
    failure = classify_failure(
        candidates=[_cand("Core Power", 170), _cand("Elite", 230)],
        sources_attempted=2)
    assert failure is CandidateResolutionFailure.MULTIPLE_MATERIAL_MATCHES
    assert failure.is_askable


def test_two_candidates_that_agree_are_not_ambiguous():
    """Nutritionally the same answer either way — asking would be friction with
    no payoff."""
    assert classify_failure(
        candidates=[_cand("Bagel A", 80), _cand("Bagel B", 86)],
        sources_attempted=2) is None


def test_nothing_found_with_working_sources_is_no_match():
    failure = classify_failure(candidates=[], sources_attempted=3,
                              source_errors=0)
    assert failure is CandidateResolutionFailure.NO_MATCH
    assert "label" in failure_message(failure)


def test_all_sources_failing_is_unavailable_not_no_match():
    """"I couldn't identify the product" is a lie when we never got to look —
    and it sends the user to read a label they may not need."""
    failure = classify_failure(candidates=[], sources_attempted=2,
                              source_errors=2)
    assert failure is CandidateResolutionFailure.SOURCE_UNAVAILABLE
    assert "estimate" in failure_message(failure)
    assert not failure.is_askable      # the user cannot fix a dead API


def test_a_partial_source_outage_that_still_found_nothing_is_no_match():
    """One of two sources died but the other answered and found nothing. That
    is a genuine miss."""
    assert classify_failure(candidates=[], sources_attempted=2,
                            source_errors=1) is \
        CandidateResolutionFailure.NO_MATCH


def test_an_incoherent_serving_basis_is_its_own_state():
    """We found the product; its serving info does not add up. Asking "what
    does the label say per serving" is actionable in a way "which product" is
    not."""
    failure = classify_failure(candidates=[_cand("Thing", 100)],
                               invalid_serving_basis=True)
    assert failure is CandidateResolutionFailure.INVALID_SERVING_BASIS
    assert "per serving" in failure_message(failure)
    assert failure.is_askable


def test_the_serving_basis_check_precedes_everything_else():
    failure = classify_failure(candidates=[], sources_attempted=2,
                               source_errors=2, invalid_serving_basis=True)
    assert failure is CandidateResolutionFailure.INVALID_SERVING_BASIS


def test_options_are_offered_only_where_choosing_resolves_something():
    ambiguous = failure_message(
        CandidateResolutionFailure.MULTIPLE_MATERIAL_MATCHES,
        options=("the 26g bottle", "the 42g bottle"))
    assert "26g" in ambiguous and "42g" in ambiguous

    # A dead source is not fixed by picking from a list.
    unavailable = failure_message(CandidateResolutionFailure.SOURCE_UNAVAILABLE,
                                  options=("a", "b"))
    assert "a" not in unavailable.split() and "estimate" in unavailable


def test_every_failure_state_has_a_distinct_actionable_message():
    messages = {f: failure_message(f) for f in CandidateResolutionFailure}
    assert len(set(messages.values())) == len(messages)
    for failure, text in messages.items():
        assert text and text[0].isupper(), failure
