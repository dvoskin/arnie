"""Candidate generation and collapse (build order 4, 5).

Clarification must never be built from raw search results. Raw results contain
the same product three times under different artwork, and asking "which of
these five?" when three are nutritionally identical is friction manufactured
by the pipeline rather than by the food.

The collapse rule cuts both ways, and both directions are failures:
  over-collapsing  hides a material choice and logs the wrong product silently
  under-collapsing asks a question with duplicate answers
"""
import pytest

from skills.nutrition.candidate_sets import (ProductCandidate,
                                             build_candidate_set,
                                             collapse_candidates,
                                             grouping_key,
                                             make_candidate_id,
                                             materially_distinct,
                                             normalize_token,
                                             nutrient_signature,
                                             score_candidate)
from skills.nutrition.models import profile_from_values
from skills.nutrition.provenance import SourceTier
from skills.nutrition.staging import Quantity


def _c(name, brand=None, line=None, variant=None, size=None, cal=None,
       protein=None, tier=SourceTier.BRANDED_EXACT, source="off",
       basis="per_serving", cid="", alias=None):
    return ProductCandidate(
        candidate_id=cid, canonical_name=name, brand=brand, product_line=line,
        variant=variant, package_size=size, serving_basis=basis, source=source,
        tier=tier, via_alias=alias,
        nutrient_profile=(profile_from_values("off", calories=cal,
                                              protein=protein)
                          if cal is not None else None))


# ── collapse: what is the same food ───────────────────────────────────────────
def test_the_same_product_under_different_artwork_collapses():
    """Three records, one product. Asking the user to pick between them is
    friction the pipeline invented."""
    a = _c("Core Power Vanilla", "Fairlife", "Core Power", "vanilla",
           Quantity(14, "oz"), cal=170, protein=26, cid="a")
    b = _c("Fairlife Core Power Vanilla 14oz", "Fairlife", "Core Power",
           "vanilla", Quantity(14, "oz"), cal=172, protein=26, cid="b")
    c = _c("CORE POWER vanilla shake", "fairlife", "core power", "Vanilla",
           Quantity(14, "oz"), cal=170, protein=26.5, cid="c")
    out = collapse_candidates([a, b, c])
    assert len(out) == 1
    assert set(out[0].collapsed_from) == {"b", "c"}   # it remembers


def test_core_power_and_elite_never_collapse():
    """190 calories and 16 g of protein apart. Collapsing these would log the
    wrong product silently — the exact failure the layer exists for."""
    core = _c("Core Power", "Fairlife", "Core Power", size=Quantity(14, "oz"),
              cal=170, protein=26)
    elite = _c("Core Power Elite", "Fairlife", "Core Power Elite",
               size=Quantity(14, "oz"), cal=230, protein=42)
    assert len(collapse_candidates([core, elite])) == 2


def test_the_same_product_in_two_sizes_never_collapses():
    small = _c("Core Power", "Fairlife", "Core Power",
               size=Quantity(11.5, "oz"), cal=140, protein=20)
    large = _c("Core Power", "Fairlife", "Core Power",
               size=Quantity(14, "oz"), cal=170, protein=26)
    assert len(collapse_candidates([small, large])) == 2


def test_flavours_with_different_nutrition_never_collapse():
    plain = _c("Royo Plain Bagel", "Royo", "Bagel", "plain", cal=80)
    everything = _c("Royo Everything Bagel", "Royo", "Bagel", "everything",
                    cal=110)
    assert len(collapse_candidates([plain, everything])) == 2


def test_the_survivor_is_the_highest_tier_member():
    """A saved regular and an OFF record of the same product: keep the one
    with more authority."""
    off = _c("Core Power", "Fairlife", "Core Power", size=Quantity(14, "oz"),
             cal=170, protein=26, tier=SourceTier.BRANDED_EXACT, cid="off")
    regular = _c("Core Power", "Fairlife", "Core Power",
                 size=Quantity(14, "oz"), cal=170, protein=26,
                 tier=SourceTier.USER_REGULAR, source="user_regular",
                 cid="reg")
    out = collapse_candidates([off, regular])
    assert len(out) == 1 and out[0].candidate_id == "reg"


# ── the signature ─────────────────────────────────────────────────────────────
def test_unknown_macros_do_not_fingerprint_as_zero():
    """A record that omits protein must not group with a genuinely
    zero-protein food."""
    silent = _c("thing", cal=170)
    zeroed = ProductCandidate(
        candidate_id="z", canonical_name="thing",
        nutrient_profile=profile_from_values("off", calories=170, protein=0.0))
    assert nutrient_signature(silent.nutrient_profile) != \
        nutrient_signature(zeroed.nutrient_profile)
    assert len(collapse_candidates([silent, zeroed])) == 2


def test_label_rounding_does_not_split_a_product():
    a = _c("x", "B", "L", cal=170, protein=26)
    b = _c("x", "B", "L", cal=174, protein=26.8)
    assert len(collapse_candidates([a, b])) == 1


def test_normalization_ignores_words_that_never_distinguish():
    assert normalize_token("The Original Core Power Bottle") == "core power"
    assert normalize_token("CORE-POWER!") == "core power"
    assert normalize_token(None) == ""


def test_grouping_ignores_source_and_artwork():
    a = _c("Core Power", "Fairlife", "Core Power", size=Quantity(14, "oz"),
           cal=170, source="off")
    b = _c("Core Power classic pack", "Fairlife", "Core Power",
           size=Quantity(14, "oz"), cal=170, source="usda")
    assert grouping_key(a) == grouping_key(b)


def test_candidate_ids_are_derived_from_identity():
    a = _c("Core Power", "Fairlife", "Core Power", size=Quantity(14, "oz"),
           cal=170)
    b = _c("core power", "fairlife", "Core Power", size=Quantity(14, "oz"),
           cal=170)
    assert make_candidate_id(a) == make_candidate_id(b)


# ── materially distinct ───────────────────────────────────────────────────────
def test_candidates_within_tolerance_are_not_a_real_choice():
    """Two survivors 8 calories apart produce the same log either way. Asking
    is friction with no payoff."""
    a = _c("Bagel A", "Royo", "Bagel", "plain", cal=80)
    b = _c("Bagel B", "Royo", "Bagel", "sesame", cal=88)
    assert len(materially_distinct([a, b])) == 1


def test_a_real_choice_survives():
    core = _c("Core Power", "Fairlife", "Core Power", cal=170)
    elite = _c("Elite", "Fairlife", "Core Power Elite", cal=230)
    assert len(materially_distinct([core, elite])) == 2


def test_an_unknown_calorie_candidate_always_survives():
    """We cannot claim it agrees with anything."""
    known = _c("Core Power", "Fairlife", "Core Power", cal=170)
    unknown = _c("Mystery", "Fairlife", "Mystery")
    assert len(materially_distinct([known, unknown])) == 2


# ── scoring ───────────────────────────────────────────────────────────────────
def test_dimensions_are_scored_separately():
    """Kept separate because the question to ask depends on WHICH is weak: a
    low size score asks about the bottle, a low variant score about flavour."""
    c = score_candidate(
        _c("Core Power Vanilla", "Fairlife", "Core Power", "vanilla",
           Quantity(14, "oz"), cal=170),
        requested_name="fairlife core power", requested_brand="Fairlife",
        requested_variant="chocolate", requested_size=Quantity(11.5, "oz"))
    assert c.brand_score == 1.0          # brand matched
    assert c.variant_score == 0.0        # flavour did not
    assert c.size_score == 0.0           # size did not
    assert 0.0 < c.overall_score < 1.0


def test_an_alias_hop_costs_confidence():
    """"royal bagel" → "Royo bagel" is a hypothesis. It must never outrank a
    direct hit, and it is never silently rewritten as fact."""
    direct = score_candidate(_c("Royo Bagel", "Royo", "Bagel", cal=80),
                             requested_name="royo bagel")
    aliased = score_candidate(
        _c("Royo Bagel", "Royo", "Bagel", cal=80, alias="royal bagel"),
        requested_name="royo bagel")
    assert aliased.overall_score < direct.overall_score
    assert aliased.via_alias == "royal bagel"     # recorded, not hidden


def test_build_candidate_set_scores_then_collapses_then_ranks():
    raw = [
        _c("Bagel, plain, generic", cal=290, tier=SourceTier.GENERIC_EXACT,
           source="usda"),
        _c("Royo Plain Bagel", "Royo", "Bagel", "plain", cal=80),
        _c("Royo Plain Bagel 4-pack", "Royo", "Bagel", "plain", cal=82),
    ]
    out = build_candidate_set(raw, requested_name="Royo plain bagel",
                              requested_brand="Royo")
    assert len(out) == 2                       # the two Royo records merged
    assert out[0].brand == "Royo"              # and rank above the generic
    assert all(c.candidate_id for c in out)    # every survivor is addressable


def test_an_empty_set_is_not_an_error():
    assert build_candidate_set([], requested_name="anything") == []
