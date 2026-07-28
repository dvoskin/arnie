"""A promoted row tells one story about where its numbers came from.

Audit I-2, live on every food log (`NUTRITION_RESOLVER_MODE=live`, empty
allowlist, no canary percentage).

`to_food_analysis` routes through `analyze(...)` with every candidate set to
None — deliberately, so derived fields are computed by one code path — then
overwrites `source`, `confidence`, `enrichment_source` and `fdc_id`. It never
rebuilt `provenance`, which `analyze` had just computed from no candidates at
all. So one row carried three answers about itself, and three surfaces each
read a different one:

    .source                          off        receipt headline: "Found the
                                                product in Open Food Facts"
    .confidence                      exact      card badge: not estimated
    .provenance.rung                 estimate   receipt detail: "Best estimate
                                                from the description"
    .provenance.macros_are_estimated True

`_stash_sourcing` persists `provenance.as_dict()`, so the STORED record said
`estimate` for exactly-matched branded rows — and `is_fallback`, the disclosure
that a generic is standing in for a named product, was always True for the
wrong reason and carried no information at all.

THE RUNG COMES FROM THE LANE, NOT THE TIER. The lanes run concurrently and
`authority.candidate_map` already prioritises them; deriving the rung from the
resolver's tier instead would be a second prioritisation, and the two disagree
where it matters — a web_label answer carries tier BRANDED_EXACT, so a tier
mapping calls it "From the product label" while the ladder seats it at
`manufacturer`, "From the manufacturer's label".

The tier still decides whether the MACROS are sourced. Those are separate
questions, which is the whole reason `SourceProvenance` is per-role: a turn can
identify a product from a branded index and still be estimating its numbers.
"""
import pytest

from core.food_intelligence import analyze
from skills.nutrition import authority as A
from skills.nutrition.models import NutritionResolution, profile_from_values
from skills.nutrition.promotion import to_food_analysis
from skills.nutrition.provenance import MatchGrade, SourceTier


def _legacy(name="Legendary Foods roll", is_packaged=True):
    """A legacy pass that classified the food from the real candidate set.

    Promotion changes WHICH candidate's nutrients win — not what the food is —
    so identity, portion and micro facts are inherited from here rather than
    re-derived. The NAME does the classifying, not the flag.
    """
    return analyze(name, "1 serving", 210, 20, 24, 4,
                   usda_candidate=None, memory_match=None, web_candidate=None,
                   is_packaged=is_packaged)


def _promote(*, source, tier, legacy=None, grade=MatchGrade.EXACT):
    resolution = NutritionResolution(
        canonical_name="Legendary Foods roll", quantity=None,
        nutrients=profile_from_values(source, confidence=0.9, calories=210,
                                      protein=20, carbs=24, fat=4),
        source=source, tier=tier, match_grade=grade, confidence=0.9)
    return to_food_analysis(resolution, food_name="Legendary Foods roll",
                            quantity="1 serving",
                            legacy=legacy if legacy is not None else _legacy())


# ── the four fields agree ─────────────────────────────────────────────────────

def test_an_exact_branded_match_is_not_recorded_as_an_estimate():
    out = _promote(source="off", tier=SourceTier.BRANDED_EXACT)
    assert out.source == "off"
    assert out.confidence == "exact"
    # The two that used to contradict the two above.
    assert out.provenance.rung == "branded_exact"
    assert out.provenance.macros_are_estimated is False
    assert out.provenance.is_fallback is False
    assert A.display_detail(out.provenance) == "From the product label"


def test_a_web_label_answer_is_not_called_a_product_label():
    """The case that proves lane-not-tier.

    A web answer carries tier BRANDED_EXACT. Keyed by tier it would print "From
    the product label"; the ladder seats a web candidate at `manufacturer`, and
    that is the sentence that is true of it.
    """
    out = _promote(source="web_label", tier=SourceTier.BRANDED_EXACT)
    assert out.provenance.rung == "manufacturer"
    assert A.display_detail(out.provenance) == "From the manufacturer's label"


# ── the disclosure that could never fire ──────────────────────────────────────

def test_a_generic_standing_in_for_a_product_discloses_itself():
    """USDA answering for a MANUFACTURED food seats at `usda_generic`, which is
    in FALLBACK_RUNGS precisely so this is visible. With provenance left at
    `estimate`, `is_fallback` was True on every promoted row for the wrong
    reason and meant nothing."""
    out = _promote(source="usda", tier=SourceTier.GENERIC_EXACT)
    assert out.provenance.rung == "usda_generic"
    assert out.provenance.is_fallback is True
    assert "standing in" in A.display_detail(out.provenance).lower()


def test_the_same_lane_on_a_generic_food_is_the_answer():
    """A generic source answering a genuinely generic food is the ANSWER, not a
    substitute — which is why a lane alone cannot decide the rung either."""
    out = _promote(source="usda", tier=SourceTier.GENERIC_EXACT,
                   legacy=_legacy("oatmeal", is_packaged=False))
    assert out.provenance.rung == "usda_exact"
    assert out.provenance.is_fallback is False


# ── lane and tier answer different questions ──────────────────────────────────

def test_a_branded_identity_can_still_carry_estimated_macros():
    """Separate fields because they are separately true (§6).

    The resolver can identify the product from Open Food Facts and still refuse
    its numbers — a serving-basis reject, an Atwater failure. Identity stays
    branded; the macros say estimated. Collapsing that to one string is the
    thing `SourceProvenance` exists to stop.
    """
    out = _promote(source="off", tier=SourceTier.ESTIMATED)
    assert out.provenance.identity_source == "branded_exact"
    assert out.provenance.macros_are_estimated is True
    assert out.confidence == "estimated"


def test_a_weak_branded_hit_seats_nowhere():
    """Open Food Facts earns branded authority on a good match only. A weak
    name hit is a guess wearing a database's name, and must not print as one."""
    out = _promote(source="off", tier=SourceTier.BRANDED_EXACT,
                   grade=MatchGrade.NONE)
    assert out.provenance.rung == "estimate"


# ── inherited identity facts ──────────────────────────────────────────────────

def test_the_food_class_survives_promotion():
    """Promotion has no opinion about what the food IS. Re-deriving the class
    from a name and no candidates is how the empty provenance happened."""
    legacy = _legacy(is_packaged=True)
    out = _promote(source="off", tier=SourceTier.BRANDED_EXACT, legacy=legacy)
    assert out.provenance.food_class == legacy.provenance.food_class


@pytest.mark.parametrize("tier", list(SourceTier))
def test_every_tier_produces_a_seated_rung(tier):
    """No tier may fall through to an empty rung — an unseated provenance is
    what the receipt renders as a silent 'estimate'."""
    out = _promote(source="off", tier=tier)
    assert out.provenance.rung
    assert out.provenance.display_source
