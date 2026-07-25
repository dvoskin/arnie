"""Calibration and release certification (PR #31).

Two kinds of test here.

The first kind pins the calibration MACHINERY: that a sweep is honest about what
it measured, that it restores what it touched, that "nothing got worse" is not
reported as evidence for a change, and that a disabled rule cannot win as the
tightest one.

The second kind pins the three defects the calibration found. Those matter more
than the thresholds, because in each case two constants in two modules were
compensating for each other — and a threshold tuned against a compensated
number bakes the error in permanently.
"""
import pytest

from skills.nutrition import calibration
from skills.nutrition.calibration import Point, sweep


# ── the three findings ────────────────────────────────────────────────────────
def test_cross_source_spans_are_sized_at_the_portion():
    """Finding one: spans were computed per 100 g and compared against
    portion-scale thresholds, overstating the doubt on a small portion and
    understating it on a large one.

    Two granolas 109 cal/100g apart, on 60 g. The real gap is 65.
    """
    from skills.nutrition.candidates import Candidate
    from skills.nutrition.models import (FoodResolutionRequest,
                                         profile_from_values)
    from skills.nutrition.provenance import MatchGrade, SourceTier
    from skills.nutrition.resolver import resolve
    from skills.nutrition.scaling import Per100g

    def _c(name, calories, protein):
        return Candidate(
            source="usda", tier=SourceTier.GENERIC_EXACT, name=name,
            profile=profile_from_values("usda", basis="per_100g",
                                        confidence=0.8, calories=calories,
                                        protein=protein),
            basis=Per100g(), reported_grade=MatchGrade.EXACT)

    out = resolve(
        FoodResolutionRequest(food_name="Cereal, granola",
                              raw_quantity="60g"),
        [_c("Cereal, granola, homemade", 489, 13),
         _c("Cereal, granola, lowfat", 380, 8)])

    gap = next(a for a in out.ambiguities if a.field == "nutrient_values")
    assert 60 <= gap.calorie_span <= 70, gap.calorie_span
    # And the fraction is now a portion-scale ratio rather than a per-100g
    # number divided by a portion total.
    assert 0.15 <= gap.calorie_fraction <= 0.30, gap.calorie_fraction


def test_a_protein_only_disagreement_is_material():
    """Finding two: `sources_disagree` gated on calories alone, so whey isolate
    against a whey blend — 20 g of protein apart, identical calories — was not
    a disagreement at all. No ambiguity existed, so no mode could ask."""
    from skills.nutrition.models import profile_from_values
    from skills.nutrition.validators import sources_disagree

    isolate = profile_from_values("off", basis="per_100g", confidence=0.8,
                                  calories=380, protein=80)
    blend = profile_from_values("off", basis="per_100g", confidence=0.8,
                                calories=390, protein=60)

    gap = sources_disagree(isolate, blend)
    assert gap is not None
    assert gap["driver"] == "protein"
    assert gap["protein_span"] == 20.0


def test_a_free_choice_is_still_a_free_choice():
    """The other edge of the same rule. Widening materiality must not make
    every pair of near-identical sources into a question."""
    from skills.nutrition.models import profile_from_values
    from skills.nutrition.validators import sources_disagree

    a = profile_from_values("off", basis="per_100g", confidence=0.8,
                            calories=380, protein=80)
    b = profile_from_values("off", basis="per_100g", confidence=0.8,
                            calories=384, protein=79)
    assert sources_disagree(a, b) is None


def test_a_portion_doubt_reports_a_protein_span():
    """Finding three: `scaling_uncertainty` computed calories only, so every
    portion ambiguity said protein_span=0 — telling the ladder protein was
    certain when the mass was not."""
    from skills.nutrition.models import (NormalizedQuantity,
                                         profile_from_values)
    from skills.nutrition.scaling import Per100g, scaling_spans

    deli = profile_from_values("usda", basis="per_100g", confidence=0.8,
                               calories=104, protein=17)
    six_slices = NormalizedQuantity(amount=6, unit="slice", grams=108.0,
                                    uncertainty_g=24.0, count=6)

    spans = scaling_spans(deli, Per100g(), six_slices)
    assert spans["calories"] > 0
    assert spans["protein"] > 0, "a mass doubt scales protein too"


def test_the_absolute_gate_is_not_pre_empted_by_the_relative_one():
    """The compensating-constants bug in its purest form: a 65-calorie gap that
    is only 19% relatively was reported as agreement, so strict mode's
    60-calorie threshold had nothing to fire on."""
    from skills.nutrition.models import profile_from_values
    from skills.nutrition.validators import sources_disagree

    a = profile_from_values("usda", basis="per_100g", confidence=0.8,
                            calories=342, protein=9)
    b = profile_from_values("usda", basis="per_100g", confidence=0.8,
                           calories=277, protein=6)
    gap = sources_disagree(a, b)
    assert gap is not None and gap["calorie_span"] == 65.0


def test_the_reporting_bar_matches_the_tightest_ask_threshold():
    """The two constants that drifted apart. `validators` reports a
    disagreement; the ladder decides whether to ask. If the reporting bar rises
    above the strictest ask threshold, the ladder silently stops being able to
    act on gaps it was configured to catch."""
    from skills.nutrition.resolver import ASK_SPANS
    from skills.nutrition.validators import MATERIAL_CALORIE_ABSOLUTE

    assert MATERIAL_CALORIE_ABSOLUTE <= min(ASK_SPANS.values()), (
        "the reporting bar must not exceed the tightest mode's threshold, or "
        "that mode cannot fire on gaps it is configured to catch")


# ── the machinery ─────────────────────────────────────────────────────────────
def test_the_sweep_restores_what_it_touched():
    """A sweep that leaked its last setting would silently reconfigure the
    resolver for every caller after it."""
    from skills.nutrition import resolver

    before = dict(resolver.ASK_PROTEIN_SPANS)
    sweep(calibration.PROTEIN_GRID)
    assert resolver.ASK_PROTEIN_SPANS == before


def test_the_sweep_only_scores_stated_expectations():
    """Inferring "probably should not ask" from silence would manufacture
    ground truth, and a sweep scored against manufactured labels optimizes
    toward whatever the inference assumed."""
    cases = [
        {"id": "stated", "category": "ambiguity",
         "request": {"food_name": "x", "raw_quantity": "100g"},
         "candidates": [], "expect": {"asks": {"strict": True}}},
        {"id": "silent", "category": "ambiguity",
         "request": {"food_name": "y", "raw_quantity": "100g"},
         "candidates": [], "expect": {"source": "unresolved"}},
    ]
    assert len(calibration._gold_expectations(cases)) == 1


def test_a_disabled_rule_cannot_win_as_the_tightest():
    """The bug that made the first sweep recommend switching off the very rule
    it was calibrating: the sentinel was excluded from the tightness sum, so
    "off" scored zero."""
    off = Point(label="off", settings={"T": {"a": 1e9}})
    real = Point(label="real", settings={"T": {"a": 20.0}})
    assert calibration._tightness(off) > calibration._tightness(real)


def test_a_needless_ask_disqualifies_a_setting_outright():
    """Silent misses and needless asks are never summed. A missed material
    ambiguity writes a wrong number into someone's day; a needless ask costs
    one tap. Adding them would let ten saved taps pay for one wrong meal."""
    points = [
        Point(label="loose", settings={"T": 100.0}, silent=3, needless=0),
        Point(label="tight", settings={"T": 10.0}, silent=0, needless=1),
    ]
    assert calibration.recommend(points).label == "loose"


def test_no_clean_setting_recommends_no_change():
    """None is an answer: leave the threshold alone and get more labels."""
    points = [Point(label="a", settings={"T": 1.0}, needless=2)]
    assert calibration.recommend(points) is None


def test_the_sweep_reports_which_cases_it_would_get_wrong():
    """A sweep that reports only counts cannot be acted on — the case id is
    what makes a disagreement checkable by hand, which is how three of this
    PR's findings were found."""
    points = sweep(({"label": "absurd",
                     "ASK_SPANS": {"quick": 1e9, "moderate": 1e9,
                                   "strict": 1e9}},))
    assert points[0].silent > 0
    assert all(m.case_id and m.mode for m in points[0].misses)
    assert {m.kind for m in points[0].misses} == {"silent"}


def test_the_current_settings_are_clean_on_the_labelled_set():
    """The claim the calibrated constants rest on: no missed material ambiguity
    and no needless interruption across every labelled expectation."""
    points = sweep(({"label": "current"},))
    assert points[0].silent == 0, [m.case_id for m in points[0].misses]
    assert points[0].needless == 0, [m.case_id for m in points[0].misses]


def test_production_shape_never_claims_to_measure_accuracy():
    """An ask rate is not an error rate. The logs record what we did, never
    what we should have done, and treating one as the other is the mistake the
    module exists to avoid."""
    shape = calibration.production_shape([])
    assert "frequency, not error" in shape["note"]
    assert "accuracy" not in shape


# ── certification ─────────────────────────────────────────────────────────────
def test_certification_separates_failing_from_unmeasurable():
    """The distinction a release decision needs and the readiness report cannot
    make: one means fix something, the other means deploy something."""
    cert = calibration.certify()
    assert set(cert["failing"]) & set(cert["awaiting_production_data"]) == set()
    for name in cert["awaiting_production_data"]:
        assert cert["gates"][name]["evidence"] in ("logs", "native",
                                                   "corrections")


def test_every_gate_is_told_what_would_answer_it():
    """A gate with no stated evidence source is a gate nobody can clear."""
    from skills.nutrition.readiness import GATES

    missing = [g for g in GATES if g not in calibration.GATE_EVIDENCE]
    assert not missing, missing


def test_nothing_measurable_is_failing():
    """The 9.7 certification claim. Gold-backed gates are answerable now, so a
    failure among them is a real failure rather than a missing deployment."""
    cert = calibration.certify()
    assert cert["failing"] == [], cert["failing"]
    assert cert["measurable_but_unanswered"] == [], (
        cert["measurable_but_unanswered"])


def test_the_ambiguity_recall_gate_is_answerable():
    """It sat at "insufficient" — value 1.0 on a sample of 18 against a minimum
    of 30. Not failing; unanswerable. The fix for that is labels."""
    from skills.nutrition.readiness import gold_ambiguity_recall

    metric = gold_ambiguity_recall()
    assert metric.sample >= 30, metric.sample
    assert metric.verdict() == "pass", (metric.value, metric.sample)


def test_certification_does_not_collapse_to_a_single_verdict():
    """A certification that reduces "eleven gates await production data" to
    "not ready" throws away the only information the reader needs."""
    cert = calibration.certify()
    assert "ready" not in cert
    assert cert["next_action"]
