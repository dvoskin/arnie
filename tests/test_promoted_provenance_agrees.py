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
that a generic is standing in for a named product, could never fire on a
promoted item at all.
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
    re-derived.

    The NAME does the classifying, not the flag: "Legendary Foods roll" reads
    as manufactured whatever `is_packaged` says, which is `classify`'s job and
    not something to work around here.
    """
    return analyze(name, "1 serving", 210, 20, 24, 4,
                   usda_candidate=None, memory_match=None, web_candidate=None,
                   is_packaged=is_packaged)


def _promote(tier, *, legacy=None, source="off"):
    resolution = NutritionResolution(
        canonical_name="Legendary Foods roll", quantity=None,
        nutrients=profile_from_values(source, confidence=0.9, calories=210,
                                      protein=20, carbs=24, fat=4),
        source=source, tier=tier, match_grade=MatchGrade.EXACT, confidence=0.9)
    return to_food_analysis(resolution, food_name="Legendary Foods roll",
                            quantity="1 roll",
                            legacy=legacy if legacy is not None else _legacy())


# ── the four fields agree ─────────────────────────────────────────────────────

def test_an_exact_branded_match_is_not_recorded_as_an_estimate():
    out = _promote(SourceTier.BRANDED_EXACT)
    assert out.source == "off"
    assert out.confidence == "exact"
    # The two that used to contradict the two above.
    assert out.provenance.rung == "branded_exact"
    assert out.provenance.macros_are_estimated is False
    assert out.provenance.is_fallback is False
    assert A.display_detail(out.provenance) == "From the product label"


def test_a_real_estimate_still_says_so():
    """The guard against over-correcting: this must not start claiming a
    source it does not have."""
    out = _promote(SourceTier.ESTIMATED)
    assert out.provenance.rung == "estimate"
    assert out.provenance.macros_are_estimated is True
    assert out.confidence == "estimated"


# ── the disclosure that could never fire ──────────────────────────────────────

def test_a_generic_standing_in_for_a_product_discloses_itself():
    """`usda_generic` is in FALLBACK_RUNGS precisely so this case is visible.
    With provenance left at `estimate`, `is_fallback` was True for the wrong
    reason on every promoted row and carried no information at all."""
    out = _promote(SourceTier.GENERIC_EXACT)
    assert out.provenance.rung == "usda_generic"
    assert out.provenance.is_fallback is True
    assert "standing in" in A.display_detail(out.provenance).lower()


def test_the_same_tier_on_a_generic_food_is_not_a_fallback():
    """A generic answer for a genuinely generic food is the ANSWER, not a
    substitute — which is why the tier alone cannot decide the rung."""
    out = _promote(SourceTier.GENERIC_EXACT,
                   legacy=_legacy("oatmeal", is_packaged=False))
    assert out.provenance.rung == "usda_exact"
    assert out.provenance.is_fallback is False


# ── inherited identity facts ──────────────────────────────────────────────────

def test_the_food_class_survives_promotion():
    """Promotion has no opinion about what the food IS. Re-deriving the class
    here from a name and no candidates is how the empty provenance happened in
    the first place."""
    legacy = _legacy(is_packaged=True)
    out = _promote(SourceTier.BRANDED_EXACT, legacy=legacy)
    assert out.provenance.food_class == legacy.provenance.food_class


@pytest.mark.parametrize("tier", list(SourceTier))
def test_every_tier_produces_a_seated_rung(tier):
    """No tier may fall through to an empty rung — an unseated provenance is
    what the receipt renders as a silent 'estimate'."""
    out = _promote(tier)
    assert out.provenance.rung
    assert out.provenance.display_source
