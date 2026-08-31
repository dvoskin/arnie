"""⛔⛔⛔ AN UNRESOLVED FACT CARRIES ITS OWN IMPACT BASIS.

**The exit test for the tranche opened 2026-08-31.** Frozen by Danny before the
repair was designed:

> An unresolved fact carries its own impact basis. Re-parenting that fact may
> change representation, but cannot change the inputs used to decide whether it
> is material.
>
>     Mayo as staged row                 -> decision X
>     same Mayo re-parented under sandwich -> decision X

## What was wrong

`FoodAmbiguity.item_calories` was named after the ITEM, and its producer duly
filled it from whichever `StagedFoodItem` happened to OWN the ambiguity after
composition. Measured 2026-08-31 over the frozen corpus:

```
baseline c1  TWO staged items — the sandwich, and `Mayo` as its own row.
             mayo: CONSUMED_QUANTITY/`quantity`, material=True   -> ASK 2/2
under C      ONE staged item. Mayo is an `extras` fact ON THE SANDWICH,
             material=False                                      -> ASK 0/4
```

`of_item` divided by the parent. **7 of 8 spans flipped on that alone** — as its
own row the mayo was material from 27 calories; carried on an 800-calorie
sandwich it needed 240.

## What the repair is, and what it deliberately is NOT

`FoodAmbiguity.impact_basis_cal` — state on the FACT, decided once by the
producer that knows what the fact is about, travelling with the fact through any
re-parenting. `attach_ambiguities` **consumes** it instead of rediscovering a
denominator from the owning row.

- ⛔ **NOT a special case in the scorer.** `materiality` takes a basis and a
  span and knows nothing about condiments, extras, or ownership.
- ⛔ **NOT a blanket `item_calories=None`.** That mutation proved causality; it
  is not product semantics. Whole-item facts — `quantity`, `prep`, `variant`,
  `identity` — still size against their own item, unchanged, and the controls
  below pin that.
- ⛔ **NOT a flattening of the policy.** `of_day` is still the daily target.
  Only the other denominator was inheriting a parent.

## The one thing this repair does NOT close, pinned below

An `extras` record carries **no size for the component** — the interpreter is
told to report `{"item": "<the item it concerns>"}`, and an unstated sauce ON a
sandwich concerns the sandwich. So the fact arrives with its own basis genuinely
NOT ESTABLISHED, and `None` now says so explicitly instead of borrowing the
parent's number.

The two encodings therefore still differ in a **1-calorie boundary window**
(`test_the_residual_gap_is_ONE_CALORIE_WIDE`), because one of them knows the
mayo is 90 calories and the other does not. That is the registered measurement
gap, not a leak in the invariant — and it is pinned so it cannot silently widen.
"""
from __future__ import annotations

import core.food_pipeline as FP
from skills.nutrition import materiality as M

#: ⭐ THE BACK-LINK. `data/criteria_registry.json` names this file as the
#: mechanical proof of that criterion; this names the criterion back, so the
#: binding is two-way and an unrelated passing file cannot be substituted for
#: it. Enforced by
#: `tests/test_no_criterion_promoted_from_its_own_corpus.py::
#:  test_every_architectural_invariant_names_a_live_mechanical_proof`.
PROVES = "materiality_is_representation_invariant"

TURN = "test:representation-invariance"
MODE = "moderate"

#: The census probe identity's real targets, through `_daily_targets`.
TARGETS = {"calories": 2510.0, "protein": 171.0, "carbs": 308.0, "fat": 66.0}

#: c1, verbatim. The span is the model's own `impact_cal` as captured in
#: `data/corpus/producer_census_both_authorities_2026-08-28.jsonl` case 1 rep 1.
SPAN = 120.0
COMPONENT_CAL = 90.0
PARENT_CAL = 800.0

#: ⭐ THE FROZEN REPRESENTATION GRID. Not one alternative parent — every parent
#: size a real sandwich, bowl or platter could plausibly carry, because the
#: claim is that the parent does not enter the decision AT ALL.
PARENT_GRID = (90.0, 200.0, 400.0, 800.0, 1200.0, 2000.0)
SPAN_GRID = (20, 40, 60, 80, 100, 120, 150, 200, 240, 300)


def _data(items, ambiguities):
    return {"action": "log", "items": items, "say": "",
            "ambiguities": ambiguities, "_calls": []}


def _raise(items, ambiguities):
    """Run the REAL producer. Not a reimplementation of the scorer:
    `attach_ambiguities` is the function that chose the denominator in
    production, so the denominator has to come from it or this test proves
    nothing about the shipped path."""
    staged, _ = FP.stage_items(_data(items, []), turn_id=TURN)
    staged = FP.attach_ambiguities(staged, _data(items, ambiguities),
                                   mode=MODE, targets=TARGETS)
    return [a for i in staged for a in i.ambiguities]


def _decide(items, ambiguities):
    return any(a.is_material for a in _raise(items, ambiguities))


def as_its_own_row(span=SPAN, component=COMPONENT_CAL, parent=PARENT_CAL):
    """`StagedFoodItem("Mayo")` — the fact is about a row of its own."""
    return _decide(
        [{"food": "subway footlong turkey", "calories": parent},
         {"food": "mayo", "calories": component}],
        [{"item": "mayo", "field": "quantity", "impact_cal": span}])


def as_a_fact_on_the_parent(span=SPAN, parent=PARENT_CAL):
    """`Sandwich.ambiguity(extras="Mayo")` — the same fact, re-parented."""
    return _decide(
        [{"food": "subway footlong turkey", "calories": parent}],
        [{"item": "subway footlong turkey", "field": "extras",
          "impact_cal": span}])


# ── precondition: both encodings really reach the producer ────────────────────
def test_both_encodings_actually_produce_an_ambiguity():
    """⛔ WITHOUT THIS THE INVARIANT IS VACUOUS. An encoding that gets DROPPED —
    an unmatched item name, a field the maps reject — agrees with anything by
    producing nothing, and the test reads green while measuring silence."""
    for label, items, ambs in (
        ("own row",
         [{"food": "subway footlong turkey", "calories": PARENT_CAL},
          {"food": "mayo", "calories": COMPONENT_CAL}],
         [{"item": "mayo", "field": "quantity", "impact_cal": SPAN}]),
        ("re-parented",
         [{"food": "subway footlong turkey", "calories": PARENT_CAL}],
         [{"item": "subway footlong turkey", "field": "extras",
           "impact_cal": SPAN}]),
    ):
        raised = _raise(items, ambs)
        assert len(raised) == 1, (
            f"{label}: expected exactly one ambiguity, got {len(raised)} — the "
            "invariant cannot mean anything if an encoding is silently dropped")
        assert raised[0].calorie_span == SPAN, (
            f"{label}: the span did not survive into the ambiguity")


# ── the MECHANISM, changed deliberately ───────────────────────────────────────
def test_the_basis_is_the_FACTS_own_not_the_owning_rows():
    """⭐ THE PIN THAT MOVED. Before the repair this asserted the opposite —
    that an `extras` fact was sized against `PARENT_CAL`. It is restated rather
    than deleted so the direction of the change is on the record."""
    reparented = _raise(
        [{"food": "subway footlong turkey", "calories": PARENT_CAL}],
        [{"item": "subway footlong turkey", "field": "extras",
          "impact_cal": SPAN}])[0]
    assert reparented.impact_basis_cal is None, (
        "an `extras` fact carries no size for its component, so its basis is "
        f"NOT ESTABLISHED — it must not be {PARENT_CAL}, which belongs to the "
        "row that happens to carry it")

    own = _raise(
        [{"food": "subway footlong turkey", "calories": PARENT_CAL},
         {"food": "mayo", "calories": COMPONENT_CAL}],
        [{"item": "mayo", "field": "quantity", "impact_cal": SPAN}])[0]
    assert own.impact_basis_cal == COMPONENT_CAL, (
        "a whole-item fact IS about its row, so the row's calories ARE the "
        "fact's own basis — this half must not have changed")


# ── the exit test ─────────────────────────────────────────────────────────────
def test_c1_gets_the_same_decision_under_both_representations():
    """⭐ THE CASE THAT REJECTED SHAPE C, reduced to two encodings."""
    assert as_its_own_row() == as_a_fact_on_the_parent() is True, (
        "the same 120-calorie mayo unknown must be material as its own row and "
        "as an `extras` fact on the sandwich — representation must not decide")


def test_the_decision_is_invariant_ACROSS_THE_WHOLE_REPRESENTATION_GRID():
    """⭐⭐⭐ NOT ONE FIXTURE. One agreeing pair proves nothing about a rule that
    disagrees everywhere else, and the measured flip covered 7 of 8 spans."""
    moved = []
    for span in SPAN_GRID:
        decisions = {as_a_fact_on_the_parent(span, parent) for parent in PARENT_GRID}
        if len(decisions) > 1:
            moved.append(span)
    assert not moved, (
        f"the parent's size still moves the decision at spans {moved} — a fact "
        "re-parented onto a bigger host must not become immaterial")

    disagree = [s for s in SPAN_GRID if as_its_own_row(s) != as_a_fact_on_the_parent(s)]
    assert not disagree, (
        f"own-row and re-parented disagree at spans {disagree}")


def test_the_residual_gap_is_ONE_CALORIE_WIDE():
    """⚠ THE HONEST REMAINDER, pinned so it cannot silently widen.

    The two encodings do not carry the same information: the own-row form knows
    the mayo is 90 calories and the `extras` form knows no component size at
    all. So their boundaries sit one calorie apart — own-row turns material at
    27, re-parented at 26, because with no basis the day proportion decides
    alone.

    That is the REGISTERED MEASUREMENT GAP (`condiment_span_truthfulness`'s
    sibling: the interpreter names the parent, never the component), not a leak
    in the invariant. If this window ever grows, the basis has started being
    inferred from somewhere it should not be.
    """
    differ = [s for s in range(1, 401)
              if as_its_own_row(s) != as_a_fact_on_the_parent(s)]
    assert differ == [26], (
        f"expected exactly one boundary calorie of disagreement, got {differ}")


# ── ⛔ CONTROLS: the whole-item path must be UNTOUCHED ────────────────────────
def test_a_genuinely_material_whole_item_unknown_is_still_material():
    """Gate 5. The repair must not have bought invariance by loosening."""
    assert as_its_own_row(span=120, component=90)
    assert _decide([{"food": "protein shake", "calories": 170}],
                   [{"item": "protein shake", "field": "quantity",
                     "impact_cal": 190}]), \
        "the Fairlife case — a doubt exceeding the whole drink — must still ask"


def test_a_genuinely_immaterial_whole_item_unknown_is_still_immaterial():
    """Gate 5, the other direction — the one a loosening would break first."""
    assert not _decide([{"food": "black coffee", "calories": 10}],
                       [{"item": "black coffee", "field": "quantity",
                         "impact_cal": 8}]), \
        "an 8-calorie doubt on a 10-calorie coffee must still be waved through"
    assert not as_its_own_row(span=20, component=90), \
        "a 20-calorie span is below the day fraction and must not ask"


def test_the_whole_item_denominator_still_bites():
    """⛔ THE ANTI-FLATTENING CONTROL. If the repair had simply stopped using a
    denominator, this would go green for the wrong reason: a span that is a
    small part of a large item must still be demoted BY THE ITEM FRACTION."""
    assert not as_its_own_row(span=120, component=500), (
        "120 calories of doubt on a 500-calorie item is 24% of it and below "
        "the 0.3 item fraction — the of_item gate must still be able to refuse")
    assert as_its_own_row(span=120, component=90), (
        "the same span on a 90-calorie item is most of it and must ask — if "
        "both of these do not hold, of_item has stopped mattering")


def test_of_day_is_still_scored_against_the_daily_target():
    """Gate 5. Danny: *`of_day` should remain based on the daily target. Don't
    flatten the entire policy just to make this test pass.*"""
    of_day, _ = M.consequence(spans={"calories": 120.0}, targets=TARGETS,
                              item_calories=None)
    assert abs(of_day - 120.0 / 2510.0) < 1e-5, (   # `consequence` rounds to 5dp
        "of_day must still be the span over the DAY'S TARGET")
    assert not M.is_material(mode=MODE, calorie_span=20, item_calories=None,
                             targets=TARGETS), \
        "a span under the day fraction must be refused even with no basis"
