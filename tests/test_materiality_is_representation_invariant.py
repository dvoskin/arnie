"""⛔⛔⛔ THE SAME UNRESOLVED COMPONENT MUST GET THE SAME MATERIALITY DECISION
HOWEVER IT IS REPRESENTED.

**The exit test for the tranche opened 2026-08-31.** Frozen by Danny before any
repair was designed:

> Materiality must consume an invariant representation of the unresolved
> component, not whatever parent item happens to contain it.
>
> An unresolved `Mayo ~120 cal` must get the same materiality decision whether
> it is `StagedFoodItem("Mayo")` or `Sandwich.ambiguity(extras="Mayo")`. The
> parent representation may change for logging and decomposition purposes; the
> unknown's own impact basis may not.

## Why this test exists — measured, not supposed

The Shape-C slice passed its north-star exit test and was REJECTED for adoption
anyway, because the measurement of WHY it passed said this:

```
baseline c1  TWO staged items — the sandwich, and `Mayo` as its own row.
             mayo: CONSUMED_QUANTITY/`quantity`, material=True  -> ASK 2/2
under C      ONE staged item. The mayo is not a row; it is an `extras`
             ambiguity ON THE SANDWICH, material=False          -> ASK 0/4
```

Nothing about the unknown changed. `of_item` divides by the row the ambiguity
hangs off, and C moved the row. Over the captured condiment spans **7 of 8
flip on the denominator alone** — as its own row the mayo is material from 27
calories; carried on an 800-calorie sandwich it needs 240.

So a policy experiment can improve the aggregate ask metric by re-representing
a subject rather than by judging it, and the north-star metric cannot see the
difference. This test can.

## ⭐ WHAT THIS TEST IS NOT

It is not an assertion that the mayo question is a GOOD question, and it takes
no position on whether `impact_cal=120` is a truthful span. Both are separate
registered questions. This pins only the independence: **whatever the policy
decides about an unknown, it must decide the same thing about that same unknown
under a different parent.**

## ⛔ CURRENTLY RED — `xfail(strict=True)`, DELIBERATELY

The defect is live, so a plain assertion would leave the tree red. Strict xfail
is the honest encoding: it passes while the defect exists and goes RED THE
MOMENT THE REPAIR LANDS, which forces whoever fixes it to promote this to a
real assertion rather than quietly leaving a passing xfail behind.
"""
from __future__ import annotations

import pytest

import core.food_pipeline as FP
from skills.nutrition import materiality as M

TURN = "test:representation-invariance"
MODE = "moderate"

#: The census probe identity's real targets, through `_daily_targets`.
TARGETS = {"calories": 2510.0, "protein": 171.0, "carbs": 308.0, "fat": 66.0}

#: c1, verbatim. The span is the model's own `impact_cal` as captured in
#: `data/corpus/producer_census_both_authorities_2026-08-28.jsonl` case 1 rep 1.
SPAN = 120.0
COMPONENT_CAL = 90.0        # the mayo, as its own row
PARENT_CAL = 800.0          # the footlong, which the `extras` note hangs off


def _data(items, ambiguities):
    return {"action": "log", "items": items, "say": "",
            "ambiguities": ambiguities, "_calls": []}


def _decide(items, ambiguities):
    """Run the REAL producer and report whether it raised a material unknown.

    Not a reimplementation of the scorer: `attach_ambiguities` is the function
    that chose the denominator in production, so the denominator has to come
    from it or this test proves nothing about the shipped path.
    """
    staged, _ = FP.stage_items(_data(items, []), turn_id=TURN)
    staged = FP.attach_ambiguities(staged, _data(items, ambiguities),
                                   mode=MODE, targets=TARGETS)
    return any(a.is_material for i in staged for a in i.ambiguities)


def _as_its_own_row(span=SPAN):
    """`StagedFoodItem("Mayo")` — the baseline representation."""
    return _decide(
        [{"food": "subway footlong turkey", "calories": PARENT_CAL},
         {"food": "mayo", "calories": COMPONENT_CAL}],
        [{"item": "mayo", "field": "quantity", "impact_cal": span}])


def _as_a_note_on_the_parent(span=SPAN):
    """`Sandwich.ambiguity(extras="Mayo")` — the Shape-C representation."""
    return _decide(
        [{"food": "subway footlong turkey", "calories": PARENT_CAL}],
        [{"item": "subway footlong turkey", "field": "extras",
          "impact_cal": span}])


# ── the precondition: both encodings really do reach the producer ─────────────
def test_both_encodings_actually_produce_an_ambiguity():
    """⛔ WITHOUT THIS THE INVARIANT BELOW IS VACUOUS. An encoding that gets
    DROPPED — an unmatched item name, a field the maps reject — would agree
    with anything by producing nothing at all, and the test would read green
    while measuring silence."""
    for label, items, ambs in (
        ("own row",
         [{"food": "subway footlong turkey", "calories": PARENT_CAL},
          {"food": "mayo", "calories": COMPONENT_CAL}],
         [{"item": "mayo", "field": "quantity", "impact_cal": SPAN}]),
        ("note on parent",
         [{"food": "subway footlong turkey", "calories": PARENT_CAL}],
         [{"item": "subway footlong turkey", "field": "extras",
           "impact_cal": SPAN}]),
    ):
        staged, _ = FP.stage_items(_data(items, []), turn_id=TURN)
        staged = FP.attach_ambiguities(staged, _data(items, ambs),
                                       mode=MODE, targets=TARGETS)
        raised = [a for i in staged for a in i.ambiguities]
        assert len(raised) == 1, (
            f"{label}: expected exactly one ambiguity, got {len(raised)} — "
            "the invariant test below cannot mean anything if an encoding is "
            "silently dropped")
        assert raised[0].calorie_span == SPAN, (
            f"{label}: the span did not survive into the ambiguity")


def test_the_denominator_is_the_parent_row_today():
    """The MECHANISM, pinned so the repair cannot be mistaken for a tuning.

    This is what makes the decision representation-dependent: `item_calories`
    is whatever row the ambiguity matched, so the SAME unknown is divided by
    90 in one encoding and by 800 in the other.
    """
    staged, _ = FP.stage_items(
        _data([{"food": "subway footlong turkey", "calories": PARENT_CAL}], []),
        turn_id=TURN)
    staged = FP.attach_ambiguities(
        staged,
        _data([{"food": "subway footlong turkey", "calories": PARENT_CAL}],
              [{"item": "subway footlong turkey", "field": "extras",
                "impact_cal": SPAN}]),
        mode=MODE, targets=TARGETS)
    amb = [a for i in staged for a in i.ambiguities][0]
    assert amb.item_calories == PARENT_CAL, (
        "the extras unknown is sized against the PARENT — if this changes, "
        "the repair has landed and the xfails below must be promoted to "
        "assertions")


# ── the exit test ─────────────────────────────────────────────────────────────
@pytest.mark.xfail(strict=True, reason=(
    "TRANCHE 2026-08-31 OPEN: materiality consumes the parent row's calories, "
    "so re-representing a component as an ambiguity on its parent flips the "
    "decision. Promote to a plain assertion when the repair lands."))
def test_c1_gets_the_same_decision_under_both_representations():
    """⭐ THE CASE THAT REJECTED SHAPE C, reduced to two encodings."""
    assert _as_its_own_row() == _as_a_note_on_the_parent(), (
        "the same 120-calorie mayo unknown is material as its own row and "
        "immaterial as an `extras` note on the sandwich — representation "
        "decided, not the unknown")


@pytest.mark.xfail(strict=True, reason=(
    "TRANCHE 2026-08-31 OPEN: the flip is architectural, not a mayo edge "
    "case — it holds across the policy grid."))
def test_the_decision_is_invariant_across_the_WHOLE_policy_grid():
    """⭐⭐⭐ NOT ONE FIXTURE. Danny's exit test is the FULL grid, because one
    agreeing pair proves nothing about a rule that disagrees everywhere else —
    and the measured flip covered 7 of 8 captured spans."""
    flips = [span for span in (20, 40, 60, 80, 100, 120, 150, 200, 240, 300)
             if _as_its_own_row(span) != _as_a_note_on_the_parent(span)]
    assert not flips, (
        f"{len(flips)} of 10 spans get a different materiality decision from "
        f"representation alone: {flips}")


def test_the_flip_is_real_and_this_file_is_measuring_it():
    """⛔ THE MUTATION GUARD. A strict xfail that stopped exercising the defect
    would go RED for the wrong reason, and a reader would 'fix' a test that had
    quietly stopped testing. So the flip itself is asserted POSITIVELY here,
    with the numbers that produced it — this is the assertion that must be
    DELETED when the repair lands, not edited."""
    assert _as_its_own_row() is True, "the mayo is material as its own row"
    assert _as_a_note_on_the_parent() is False, (
        "the mayo is immaterial as a note on the sandwich")
    # and the policy agrees, called directly with the two denominators
    assert M.is_material(mode=MODE, calorie_span=SPAN,
                         item_calories=COMPONENT_CAL, targets=TARGETS)
    assert not M.is_material(mode=MODE, calorie_span=SPAN,
                             item_calories=PARENT_CAL, targets=TARGETS)
