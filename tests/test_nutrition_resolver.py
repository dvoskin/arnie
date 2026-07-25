"""Candidate selection (work order steps 4/5).

The bug these are written against: fetch order equalling winner priority. The
current cascade tries memory, then USDA, then OFF, then web, first acceptable
result wins — so a USDA cousin outranks the product's own label because USDA
was asked first.

Here retrieval ranks nothing and the resolver scores afterwards, by authority
tier and then match grade. These tests pin that, plus the three things a
ladder cannot do: lose with a reason, mix field-level sources, and say "I
don't know".
"""
import pytest

from skills.nutrition.candidates import (Candidate, gather_candidates,
                                         off_candidate, usda_candidates)
from skills.nutrition.models import (FoodResolutionRequest, profile_from_values)
from skills.nutrition.provenance import MatchGrade, SourceTier
from skills.nutrition.resolver import (ASK_SPANS, resolve, resolution_log,
                                       should_ask)
from skills.nutrition.scaling import Per100g, PerUnit


def _request(name="Royo Plain Bagel", qty="100g", **kw):
    kw.setdefault("brand", "Royo")
    return FoodResolutionRequest(food_name=name, raw_quantity=qty, **kw)


def _cand(source, tier, name, grade=MatchGrade.EXACT, basis=None, **amounts):
    return Candidate(
        source=source, tier=tier, name=name,
        profile=profile_from_values(source, basis="per_100g", confidence=0.8,
                                    **amounts),
        basis=basis or Per100g(), reported_grade=grade)


# ── authority beats fetch order ───────────────────────────────────────────────
def test_a_branded_label_beats_a_usda_cousin():
    """The core failure: USDA is asked first, so USDA wins. Here it doesn't."""
    usda = _cand("usda", SourceTier.GENERIC_EXACT, "Bagel, plain, enriched",
                 grade=MatchGrade.CATEGORY, calories=290, protein=11)
    off = _cand("off", SourceTier.BRANDED_EXACT, "Royo Plain Bagel",
                calories=80, protein=8)
    # USDA listed FIRST — order must not matter.
    out = resolve(_request(), [usda, off])
    assert out.source == "off"
    assert out.nutrients.amount("calories") == 80


def test_a_saved_regular_beats_every_external_database():
    regular = _cand("user_regular", SourceTier.USER_REGULAR, "Royo Plain Bagel",
                    calories=80, protein=8)
    off = _cand("off", SourceTier.BRANDED_EXACT, "Royo Plain Bagel",
                calories=110, protein=9)
    out = resolve(_request(), [off, regular])
    assert out.source == "user_regular"


def test_a_user_label_beats_the_saved_regular():
    """Tier 1. We asked, they answered — even their own history doesn't
    outrank the label in their hand."""
    label = _cand("user_label", SourceTier.USER_LABEL, "Royo Plain Bagel",
                  calories=80, protein=8)
    regular = _cand("user_regular", SourceTier.USER_REGULAR,
                    "Royo Plain Bagel", calories=110)
    out = resolve(_request(), [regular, label])
    assert out.source == "user_label"
    assert out.tier is SourceTier.USER_LABEL


def test_match_grade_breaks_ties_inside_a_tier():
    """A branded source with a category-only match must not beat a branded
    source that matched the exact product."""
    loose = _cand("off", SourceTier.BRANDED_EXACT, "Royo Bagel Assortment",
                  grade=MatchGrade.CATEGORY, calories=200)
    tight = _cand("web_label", SourceTier.BRANDED_EXACT, "Royo Plain Bagel",
                  grade=MatchGrade.EXACT, calories=80)
    out = resolve(_request(), [loose, tight])
    assert out.source == "web_label"


# ── losing, with a reason ─────────────────────────────────────────────────────
def test_a_rejected_candidate_records_why():
    """"We picked USDA's garlic powder" is only diagnosable if the rejected
    alternatives are in the log next to the winner."""
    powder = _cand("usda", SourceTier.GENERIC_EXACT, "Garlic powder",
                   calories=331, protein=17)
    fresh = _cand("usda", SourceTier.GENERIC_EXACT, "Garlic, raw",
                  calories=149, protein=6)
    out = resolve(FoodResolutionRequest(food_name="garlic", raw_quantity="10g"),
                  [powder, fresh])
    assert out.source == "usda" and out.canonical_name == "Garlic, raw"
    reasons = {r.reason for r in out.rejected_candidates}
    assert "identity_conflict" in reasons


def test_a_wrong_brand_never_wins_even_unopposed():
    wrong = Candidate(source="off", tier=SourceTier.BRANDED_EXACT,
                      name="Thomas Plain Bagel", brand="Thomas",
                      profile=profile_from_values("off", basis="per_100g",
                                                  calories=250),
                      basis=Per100g(), reported_grade=MatchGrade.EXACT)
    out = resolve(_request(), [wrong])
    assert out.source == "unresolved"
    assert out.nutrients.is_empty
    assert "no candidate survived validation" in out.warnings


def test_an_unresolvable_request_still_answers():
    """A food turn that cannot resolve still has to return something. It
    returns nothing KNOWN — not zeros."""
    out = resolve(_request(), [])
    assert out.source == "unresolved" and out.confidence == 0.0
    assert out.nutrients.as_dict() == {}


# ── mixing, and unknowns ──────────────────────────────────────────────────────
def test_micros_fill_from_a_lower_tier_but_macros_never_do():
    """A label rarely lists potassium; an exact USDA match for the same food
    does. Calories from one source and protein from another describes no real
    food, so macros are never mixed."""
    label = _cand("user_label", SourceTier.USER_LABEL, "Royo Plain Bagel",
                  calories=80, protein=8, carbs=6, fat=1)
    usda = _cand("usda", SourceTier.GENERIC_EXACT, "Royo Plain Bagel",
                 calories=290, protein=11, sodium=400, fiber=3)
    out = resolve(_request(), [label, usda])
    assert out.nutrients.amount("calories") == 80        # macros: label only
    assert out.nutrients.amount("protein") == 8
    assert out.nutrients.amount("sodium") == 400         # micros: mixed in
    assert any("sodium" in a for a in out.assumptions)


def test_what_nothing_established_stays_unknown():
    label = _cand("user_label", SourceTier.USER_LABEL, "Royo Plain Bagel",
                  calories=80, protein=8)
    out = resolve(_request(), [label])
    assert "sodium" in out.nutrients.unknown()
    assert out.nutrients.amount("sodium") is None
    assert "sodium" not in out.nutrients.as_dict()       # never written as 0
    assert any("unknown" in w for w in out.warnings)


def test_an_impossible_micro_is_dropped_but_the_macros_survive():
    """The sodium incident, end to end: the entry keeps its calories and
    loses only the number that was impossible."""
    bad = _cand("usda", SourceTier.GENERIC_EXACT, "Royo Plain Bagel",
                calories=290, protein=11, sodium=20378)
    out = resolve(_request(), [bad])
    assert out.nutrients.amount("calories") is not None
    assert out.nutrients.amount("sodium") is None


# ── scaling and provenance flow through ───────────────────────────────────────
def test_the_portion_is_scaled_by_the_one_engine():
    usda = _cand("usda", SourceTier.GENERIC_EXACT, "Chicken breast, roasted",
                 calories=165, protein=31)
    out = resolve(
        FoodResolutionRequest(food_name="chicken breast, roasted",
                              raw_quantity="200g"), [usda])
    assert out.nutrients.amount("calories") == 330
    assert out.nutrients.amount("protein") == 62.0


def test_an_estimated_portion_is_disclosed_as_an_assumption():
    usda = _cand("usda", SourceTier.GENERIC_EXACT, "Turkey deli slice",
                 calories=104, protein=17)
    out = resolve(FoodResolutionRequest(food_name="turkey deli slice",
                                        raw_quantity="6 thin slices"), [usda])
    assert any("estimated" in a for a in out.assumptions)
    assert any(a.field == "portion_size" for a in out.ambiguities)


# ── the strictness ladder reads uncertainty, not truth ────────────────────────
def test_mode_decides_when_to_ask_never_what_is_true():
    usda = _cand("usda", SourceTier.GENERIC_EXACT, "Shawarma platter",
                 calories=200)
    request_args = dict(food_name="shawarma platter", raw_quantity="1 platter")
    quick = resolve(FoodResolutionRequest(mode="quick", **request_args), [usda])
    strict = resolve(FoodResolutionRequest(mode="strict", **request_args), [usda])
    # Same nutrition. Only the friction differs.
    assert quick.nutrients.as_dict() == strict.nutrients.as_dict()
    assert should_ask(strict.ambiguities, "strict") is not None
    assert ASK_SPANS["strict"] < ASK_SPANS["quick"]


def test_a_small_span_does_not_interrupt_anyone():
    from skills.nutrition.models import ResolutionAmbiguity
    tiny = (ResolutionAmbiguity(field="product_variant",
                                options=("Royo Plain", "Royo Everything"),
                                calorie_span=10),)
    assert should_ask(tiny, "quick") is None
    assert should_ask(tiny, "strict") is None       # 10 cal is never worth it


def test_a_doubt_covering_the_whole_item_interrupts_below_quick():
    """"80 per bagel" vs "80 per half bagel" is only an 80-calorie span, under
    every absolute threshold — but it is 100% of the item. Being totally wrong
    about a small thing is not a small error, and a flat threshold cannot see
    that. Quick mode still declines, because accepting this risk is what quick
    IS."""
    from skills.nutrition.models import ResolutionAmbiguity
    doubt = (ResolutionAmbiguity(field="serving_basis",
                                 options=("80 per bagel", "80 per half"),
                                 calorie_span=80, calorie_fraction=1.0),)
    assert should_ask(doubt, "strict") is not None
    assert should_ask(doubt, "moderate") is not None
    assert should_ask(doubt, "quick") is None


def test_the_same_span_on_a_big_item_does_not_interrupt():
    """80 calories of doubt on a 900-calorie platter is noise."""
    from skills.nutrition.models import ResolutionAmbiguity
    noise = (ResolutionAmbiguity(field="portion_size", calorie_span=80,
                                 calorie_fraction=0.09),)
    assert should_ask(noise, "strict") is None


def test_material_source_disagreement_becomes_an_ambiguity():
    a = _cand("off", SourceTier.BRANDED_EXACT, "Royo Plain Bagel", calories=80)
    b = _cand("web_label", SourceTier.BRANDED_EXACT, "Royo Plain Bagel",
              calories=260)
    out = resolve(_request(), [a, b])
    assert any(x.field == "nutrient_values" for x in out.ambiguities)


# ── the diagnostic line ───────────────────────────────────────────────────────
def test_every_resolution_logs_what_it_did():
    label = _cand("user_label", SourceTier.USER_LABEL, "Royo Plain Bagel",
                  calories=80, protein=8)
    request = _request()
    line = resolution_log(request, resolve(request, [label]),
                          turn_id="imessage:G-1", entry_id=123)
    assert line["requested_name"] == "Royo Plain Bagel"
    assert line["source"] == "user_label" and line["tier"] == "user_label"
    assert line["calories"] == 80 and line["entry_id"] == 123
    assert "sodium" in line["unknown_fields"]


# ── retrieval is concurrent and failure-tolerant ──────────────────────────────
@pytest.mark.asyncio
async def test_a_dead_source_does_not_take_the_turn_down():
    async def _boom():
        raise RuntimeError("USDA is down")

    async def _off():
        return {"per100g": {"calories": 80, "protein": 8}, "_match": "exact",
                "name": "Royo Plain Bagel", "brand": "Royo"}

    found = await gather_candidates(_request(), usda_search=_boom,
                                    off_search=_off)
    assert [c.source for c in found] == ["off"]


@pytest.mark.asyncio
async def test_retrieval_ranks_nothing():
    """The guarantee that makes selection meaningful: what comes back is
    everything found, in fetch order, unscored."""
    async def _usda():
        return [{"fdc_id": 1, "description": "Bagel, plain",
                 "per100g": {"calories": 290, "protein": 11}}]

    async def _off():
        return {"per100g": {"calories": 80}, "_match": "exact",
                "name": "Royo Plain Bagel", "brand": "Royo"}

    found = await gather_candidates(_request(), usda_search=_usda,
                                    off_search=_off)
    assert {c.source for c in found} == {"usda", "off"}
    # The high-authority source is NOT first — ordering is the resolver's job.
    assert found[0].source == "usda"
