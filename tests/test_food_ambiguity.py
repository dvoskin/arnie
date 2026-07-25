"""Typed ambiguity and materiality scoring (build order 3, 6).

The rule these encode: a question is not justified by uncertainty existing.
It is justified by the uncertainty materially changing the log.

Materiality is normalized against the mode's thresholds, so 1.0 means exactly
"at the line" and the same number is comparable across modes and axes.
"""
import pytest

from skills.nutrition.ambiguity import (AmbiguityOption, AmbiguityType,
                                        DEFAULT_THRESHOLDS, build_ambiguity,
                                        make_ambiguity_id, materiality,
                                        spans_across, thresholds_for)
from skills.nutrition.models import profile_from_values


# ── thresholds are data ───────────────────────────────────────────────────────
def test_strictness_tightens_every_axis():
    quick, moderate, strict = (thresholds_for(m)
                               for m in ("quick", "moderate", "strict"))
    for key in ("calories", "protein", "carbs", "fat"):
        assert quick[key] > moderate[key] > strict[key]


def test_an_unknown_mode_falls_back_to_moderate():
    assert thresholds_for("banana") == DEFAULT_THRESHOLDS["moderate"]
    assert thresholds_for("") == DEFAULT_THRESHOLDS["moderate"]


def test_a_threshold_can_be_retuned_without_a_deploy(monkeypatch):
    """These are meant to be tuned from production traces. Burying them in a
    prompt would make that a code change."""
    monkeypatch.setenv("NUTRITION_ASK_MODERATE_CALORIES", "80")
    assert thresholds_for("moderate")["calories"] == 80.0
    assert thresholds_for("moderate")["protein"] == 8.0      # others untouched


def test_a_malformed_override_is_ignored_rather_than_fatal(monkeypatch):
    monkeypatch.setenv("NUTRITION_ASK_STRICT_CALORIES", "not-a-number")
    assert thresholds_for("strict")["calories"] == 20.0


# ── materiality ───────────────────────────────────────────────────────────────
def test_the_score_is_normalized_so_one_is_the_line():
    assert materiality(mode="moderate", calorie_span=60.0) == 1.0
    assert materiality(mode="moderate", calorie_span=30.0) == 0.5
    assert materiality(mode="moderate", calorie_span=120.0) == 2.0


def test_the_same_span_is_more_material_in_a_stricter_mode():
    """Strictness changes the threshold, not the truth. The span is identical;
    only whether it crosses the line moves."""
    span = 60.0
    assert materiality(mode="quick", calorie_span=span) == 0.5
    assert materiality(mode="moderate", calorie_span=span) == 1.0
    assert materiality(mode="strict", calorie_span=span) == 3.0


def test_the_max_axis_wins_so_a_protein_swing_cannot_hide():
    """Averaging would let a 3x protein swing hide behind unchanged calories —
    which is exactly the Fairlife case: 26 g vs 42 g protein."""
    score = materiality(mode="moderate", calorie_span=0.0, protein_span=24.0)
    assert score == 3.0


def test_identity_risk_counts_even_when_the_calories_match():
    """Getting the product wrong is a different kind of error from getting the
    portion slightly wrong. Two products with identical calories and different
    everything else is still the wrong product."""
    assert materiality(mode="quick", calorie_span=0.0, identity_risk=1.2) == 1.2


def test_serving_basis_risk_enters_directly():
    """"80 per bagel" vs "80 per half bagel" is not measured in grams."""
    assert materiality(mode="quick", serving_basis_risk=1.5) == 1.5


def test_unknown_spans_contribute_nothing_rather_than_zero():
    """An axis nobody measured is not an axis everybody agrees on."""
    assert materiality(mode="strict", calorie_span=None,
                       protein_span=None) == 0.0


def test_a_trivial_difference_is_never_material_in_any_mode():
    """Royo Plain vs Royo Everything is ~10 calories. Interrupting someone
    over that is friction with no payoff."""
    for mode in ("quick", "moderate", "strict"):
        score = materiality(mode=mode, calorie_span=10.0, protein_span=1.0)
        if mode != "strict":
            assert score < 1.0
    # Even strict only barely notices it.
    assert materiality(mode="strict", calorie_span=10.0) == 0.5


def test_the_fairlife_case_is_material_in_every_mode():
    """190 calories and 16 g of protein between two bottles of the same brand.
    This is the case the layer exists for."""
    for mode in ("quick", "moderate", "strict"):
        assert materiality(mode=mode, calorie_span=190.0,
                           protein_span=16.0) > 1.0


# ── construction ──────────────────────────────────────────────────────────────
def test_building_an_ambiguity_scores_it():
    amb = build_ambiguity(
        staged_item_id="item_1", ambiguity_type=AmbiguityType.PACKAGE_SIZE,
        field_name="package_size", mode="moderate",
        calorie_span=190, protein_span=16,
        options=(AmbiguityOption("11.5 oz Nutrition Plan", 0.31),
                 AmbiguityOption("14 oz Core Power", 0.51),
                 AmbiguityOption("14 oz Core Power Elite", 0.18)),
        prompt="Which Fairlife bottle was it?")
    assert amb.is_material
    assert amb.materiality_score > 1.0
    assert amb.confidence == 0.51            # the LEADING option's confidence
    assert amb.clarification_prompt == "Which Fairlife bottle was it?"
    assert amb.ambiguity_type.is_identity


def test_top_options_are_ranked():
    amb = build_ambiguity(
        staged_item_id="item_1", ambiguity_type=AmbiguityType.PRODUCT_LINE,
        field_name="product_line",
        options=(AmbiguityOption("a", 0.2), AmbiguityOption("b", 0.6),
                 AmbiguityOption("c", 0.4)))
    assert [o.label for o in amb.top_options(2)] == ["b", "c"]


def test_one_ambiguity_per_item_and_field():
    """Asking the same question twice about the same field is the loop this
    prevents."""
    a = make_ambiguity_id("item_1", "product_line")
    assert a == make_ambiguity_id("item_1", "product_line")
    assert a != make_ambiguity_id("item_1", "consumed_fraction")
    assert a != make_ambiguity_id("item_2", "product_line")


def test_quantity_ambiguity_is_not_an_identity_ambiguity():
    assert not AmbiguityType.CONSUMED_QUANTITY.is_identity
    assert AmbiguityType.PRODUCT_VARIANT.is_identity


# ── spans from real candidate profiles ────────────────────────────────────────
def test_spans_measure_what_the_choice_costs():
    core = profile_from_values("off", calories=170, protein=26)
    elite = profile_from_values("off", calories=230, protein=42)
    spans = spans_across([core, elite])
    assert spans["calories_span"] == 60.0
    assert spans["protein_span"] == 16.0


def test_a_field_no_candidate_knows_has_no_span():
    """All unknown is not all agree — reporting a 0 span would make a totally
    unmeasured axis look settled."""
    a = profile_from_values("off", calories=170)
    b = profile_from_values("off", calories=230)
    spans = spans_across([a, b])
    assert spans["calories_span"] == 60.0
    assert spans["protein_span"] is None


def test_a_single_candidate_has_no_span():
    spans = spans_across([profile_from_values("off", calories=170)])
    assert spans["calories_span"] is None
