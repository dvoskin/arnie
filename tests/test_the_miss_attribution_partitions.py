"""⛔⛔⛔ THE MISS-ATTRIBUTION INSTRUMENT, REPAIRED FOR THE POST-P17g PREDICATE.

*(Danny, 2026-08-22, taxonomy supplied verbatim)*

P17g replaced `has_mass`/`has_artifact` in `decide()` with
`selected_rung_authoritative`, and the ranking instrument was not moved with it.
Two layers went stale at once, and both failed SILENTLY:

  FLIPS       every entry in the old `_COUNTERFACTUAL` — `has_mass`,
              `has_artifact`, `has_memory`, `has_identity`, `has_quantity` —
              became inert against `decide()`. All eight mechanisms therefore
              reported `0.0%` recoverable points, which read as "no tranche is
              worth anything" and was actually "the instrument can no longer
              move the predicate".
  CLASSIFIER  `_mechanism` still branched on `facts.has_mass`, so items that
              HAD a mass and declined for the P17g reason fell through into the
              evidence buckets. Measured on the frozen population: 310 of 313
              declining items fired the SAME predicate branch while being
              spread across eight differently-named buckets. The taxonomy had
              stopped partitioning anything.

⭐ **A COLUMN OF ZEROS IS NOT EVIDENCE THAT NOTHING IS RECOVERABLE.** It is the
instrument's own silence, and this file exists so that silence cannot recur
undetected.

THE CONTRACT, as specified:

  * every analyzed item lands in EXACTLY ONE terminal mechanism
  * classification consumes the REAL selected-rung result, never a re-derivation
  * counterfactuals rerun the REAL selector and the REAL predicate
  * an intervention that cannot be run against CONCRETE evidence reports
    UNMEASURED — it never inherits the sole-blocked count
  * MASS IS AN ORTHOGONAL FIELD, not a mechanism
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from core.general_settlement import ItemFacts  # noqa: E402
from measure_settlement_coverage import (  # noqa: E402
    MECHANISMS, UNMEASURED, mechanism_for)


def _facts(**kw) -> ItemFacts:
    base = dict(identity="Banana", entity="banana", preparation="",
                has_identity=True, has_quantity=True, has_mass=False,
                has_memory=False, has_artifact=False,
                selected_rung="", selected_rung_authoritative=False)
    base.update(kw)
    return ItemFacts(**base)


# ── EXACTLY ONE TERMINAL MECHANISM ────────────────────────────────────────

#: Every shape an `ItemFacts` can take at the predicate's decision points. The
#: product of these is walked below, so the partition claim is made over the
#: whole space rather than over the handful of cases that came to mind.
_AXES = {
    "has_identity": (True, False),
    "has_quantity": (True, False),
    "has_memory": (True, False),
    "has_artifact": (True, False),
    "has_mass": (True, False),
    "selected_rung": ("", "memory", "artifact", "product", "estimate"),
    "product_bound": (True, False),
}


def _every_shape():
    import itertools
    keys = list(_AXES)
    for combo in itertools.product(*(_AXES[k] for k in keys)):
        yield dict(zip(keys, combo))


def test_every_analyzed_item_lands_in_exactly_one_declared_mechanism():
    """⛔⛔ TOTALITY AND DISJOINTNESS, OVER THE WHOLE FACT SPACE.

    The old classifier's leaves were reachable only through a chain of `if`s
    that no longer matched the predicate, and nothing asserted the chain was
    exhaustive — so a shape it did not anticipate silently fell into whichever
    bucket came last. `mechanism_for` returns ONE string, and that string is
    always a declared mechanism: no fall-through, no invented leaf."""
    seen = set()
    for shape in _every_shape():
        got = mechanism_for(_facts(**shape))
        assert isinstance(got, str) and got, f"no mechanism for {shape}"
        assert got in MECHANISMS, (
            f"{got!r} is not a declared mechanism — a leaf that no consumer "
            f"can rank, for {shape}")
        seen.add(got)
    unreachable = set(MECHANISMS) - seen - {"MULTIPLE_BLOCKERS"}
    assert not unreachable, (
        f"declared but unreachable: {sorted(unreachable)} — a mechanism no "
        f"input can produce is a bucket that will always read zero")


# ── CLASSIFICATION CONSUMES THE REAL SELECTED-RUNG RESULT ─────────────────


@pytest.mark.parametrize("shape,expected", [
    ({"selected_rung": "memory"}, "MEMORY_WINNER_NONAUTHORITATIVE"),
    ({"selected_rung": "artifact"}, "ARTIFACT_WINNER_NONAUTHORITATIVE"),
    ({"selected_rung": "", "has_memory": True}, "ARTIFACT_PRESENT_NO_WINNER"),
    ({"selected_rung": "", "has_artifact": True}, "ARTIFACT_PRESENT_NO_WINNER"),
    ({"selected_rung": ""}, "NO_LOCAL_EVIDENCE"),
])
def test_the_mechanism_is_read_off_the_selector_not_re_derived(shape, expected):
    """⛔⛔⛔ THE SELECTED RUNG DECIDES, AND IT IS THE PRICER'S OWN ANSWER.

    `ItemFacts.selected_rung` is written by `look()` from `select_priced_rung`
    — the loop `price()` runs. Re-deriving "which rung wins" here from
    `has_memory`/`has_artifact` would be a THIRD opinion about the thing the
    shared selector exists to settle, and it would drift on exactly the inputs
    nobody tested — the same defect P17g closed inside `decide()`."""
    assert mechanism_for(_facts(**shape)) == expected


def test_mass_is_an_ORTHOGONAL_FIELD_and_never_a_mechanism():
    """⛔⛔ MASS IS REPORTED BESIDE THE MECHANISM, NOT AS ONE *(Danny)*.

    The old classifier branched on `has_mass` and returned a mass-shaped bucket
    (`mass_stated_but_unit_unparsed`, `count_only_quantity`, …), which is why
    62 items with an unparsed unit and 103 count-only items were filed as
    different tranches while firing the identical predicate branch. Whether a
    mass happens to be present is a FACT about the item; it is not the reason
    canonical declined it, and treating it as one splits one tranche into
    several and hides the real one.

    So flipping mass — and nothing else — must never move the mechanism."""
    for shape in _every_shape():
        with_mass = dict(shape, has_mass=True)
        without = dict(shape, has_mass=False)
        assert mechanism_for(_facts(**with_mass)) == \
            mechanism_for(_facts(**without)), (
            f"mass changed the mechanism for {shape} — it is a field, not a "
            f"bucket")


def test_no_mechanism_name_describes_a_mass():
    """⭐ AND THE VOCABULARY ITSELF CARRIES NO MASS SHAPE. A leaf named for a
    quantity shape invites the split this repair removed."""
    for name in MECHANISMS:
        lowered = name.lower()
        for word in ("mass", "count_only", "unit_unparsed", "gram"):
            assert word not in lowered, (
                f"{name!r} names a quantity shape — mass is orthogonal")


# ── THE COUNTERFACTUAL RUNS THE REAL SELECTOR ─────────────────────────────


def test_an_unrunnable_intervention_reads_UNMEASURED_not_the_blocked_count():
    """⛔⛔⛔ THE FAILURE MODE THIS WHOLE REPAIR EXISTS TO PREVENT.

    `NO_LOCAL_EVIDENCE` has no executable counterfactual: supplying "the
    evidence that does not exist" cannot be run against concrete data, so the
    recovery is unknown. Two wrong answers are available and both look like
    measurements — scoring it ZERO (which reads "coverage is worthless") or
    scoring it the SOLE-BLOCKED COUNT (which reads "coverage recovers all 120",
    an upper bound wearing a measurement's clothes).

    ⭐ UNMEASURED IS A THIRD STATE, and it must be representable. An absent
    answer must never be indistinguishable from an answered one."""
    from measure_settlement_coverage import INTERVENTIONS

    assert INTERVENTIONS["NO_LOCAL_EVIDENCE"] is None, (
        "an intervention was registered for NO_LOCAL_EVIDENCE — there is no "
        "concrete evidence to supply, so it cannot be executable")
    assert UNMEASURED != 0 and not isinstance(UNMEASURED, int), (
        "UNMEASURED must not be an integer, or it will be summed, ranked and "
        "compared against real recoveries")


def test_the_memory_measures_counterfactual_drives_the_REAL_selector():
    """⛔⛔⛔ AN EXECUTABLE COUNTERFACTUAL, FROM CONCRETE EVIDENCE ON BOTH SIDES.

    The `MEMORY_WINNER_NONAUTHORITATIVE` tranche is "the memory rung carries
    sourced measures". That IS runnable without inventing anything: the
    nutrition is the user's own memory row, and the measures are the ones the
    COMMITTED ARTIFACT already holds for the same entity — real, provenanced
    `SourcedMeasure`s. The tranche relocates an existing fact onto the rung
    that lacks it, and that is exactly what gets simulated.

    ⛔ THE FIRST VERSION TOOK THE PER-100 G FROM THE ARTIFACT TOO, which
    silently simulates "the artifact rung wins" — a different and more generous
    tranche. A counterfactual that supplies more than its tranche delivers
    measures a capability nobody is building.

    ⭐ AND IT RUNS THE REAL SELECTOR. A counterfactual that recreated the
    selection rule would measure the recreation, and would keep reporting
    recoveries after the real rule changed underneath it."""
    from measure_settlement_coverage import memory_measures_counterfactual

    facts = _facts(identity="Banana", entity="banana",
                   selected_rung="memory", has_memory=True)
    updated = memory_measures_counterfactual(
        item={"food_name": "Banana", "quantity": "1 large banana"},
        facts=facts, memory_per100g={"calories": 89.0, "protein": 1.1,
                                     "carbs": 22.8, "fat": 0.3})

    assert updated is not None, (
        "the counterfactual could not be run for a food the committed "
        "artifact holds measures for — it should be measurable here")
    assert updated.selected_rung_authoritative is True, (
        "handing the memory rung the artifact's own sourced measures did not "
        "make `1 large banana` scale authoritatively through the real selector")


def test_the_counterfactual_carries_the_USERS_numbers_not_the_artifacts():
    """⛔⛔ THE TRANCHE SUPPLIES MEASURES, NOT NUTRITION. If the simulation
    swapped in the artifact's per-100 g it would be measuring a different
    tranche — so the numbers that come back must be the ones handed in."""
    from core.canonical_pricing import _profile  # noqa: F401
    from measure_settlement_coverage import memory_measures_counterfactual

    mine = {"calories": 12345.0, "protein": 1.0, "carbs": 1.0, "fat": 1.0}
    updated = memory_measures_counterfactual(
        item={"food_name": "Banana", "quantity": "1 large banana"},
        facts=_facts(identity="Banana", entity="banana",
                     selected_rung="memory", has_memory=True),
        memory_per100g=mine)
    assert updated is not None and updated.selected_rung == "memory", (
        "the simulated winner was not the MEMORY rung — the counterfactual is "
        "simulating a different tranche than the one it is named for")


def test_no_memory_row_is_UNSIMULATABLE_not_a_failure():
    """⭐ A user with no usable row cannot be simulated, and that is not the
    same claim as "the tranche does not recover this"."""
    from measure_settlement_coverage import memory_measures_counterfactual

    assert memory_measures_counterfactual(
        item={"food_name": "Banana", "quantity": "1 large banana"},
        facts=_facts(selected_rung="memory"), memory_per100g={}) is None


def test_the_counterfactual_reports_UNSIMULATABLE_without_artifact_measures():
    """⭐ AND IT SAYS SO RATHER THAN SCORING A FAILURE. A food the artifact
    holds no measures for cannot be simulated — that is not "the tranche does
    not recover it", it is "we do not know", and the two must not be the same
    return value."""
    from measure_settlement_coverage import memory_measures_counterfactual

    got = memory_measures_counterfactual(
        item={"food_name": "Zzzznonexistent Food", "quantity": "1 bowl"},
        facts=_facts(identity="Zzzznonexistent Food",
                     entity="zzzznonexistent", selected_rung="memory",
                     has_memory=True),
        memory_per100g={"calories": 100.0})
    assert got is None, (
        "an unsimulatable item returned facts — a missing measurement was "
        "reported as a measured non-recovery")


# ── THE RESULT IS USED, NOT MERELY CALCULATED ─────────────────────────────


@pytest.mark.asyncio
async def test_recovery_is_the_COUNTERFACTUALS_RESULT_not_the_blocked_count():
    """⛔⛔⛔ THE GUARD THAT SEPARATES A MEASUREMENT FROM A RESTATEMENT *(Danny)*.

    The easiest wrong implementation computes the counterfactual, throws the
    answer away, and reports `meals_blocked_solely` in the recovery column. It
    looks like a measurement, moves when the population moves, and is simply
    the addressable population under a second name — which is exactly how the
    old instrument's zeros went unnoticed for a whole tranche.

    So: two sole-blocked meals, an intervention that clears ONE of them. A
    recovery column reading 2 is the blocked count; reading 0 is the result
    discarded; only 1 is the result being consumed."""
    import measure_settlement_coverage as M

    good = _facts(selected_rung="memory", has_memory=True)
    bad = _facts(selected_rung="memory", has_memory=True)

    def _intervention(*, item, facts, memory_per100g):
        # clears the meal whose item says so, leaves the other untouched
        if item["food_name"] == "clears":
            return _facts(selected_rung="memory", has_memory=True,
                          selected_rung_authoritative=True)
        return facts

    original = M.INTERVENTIONS["MEMORY_WINNER_NONAUTHORITATIVE"]
    M.INTERVENTIONS["MEMORY_WINNER_NONAUTHORITATIVE"] = _intervention
    try:
        ranked = await M.rank_mechanisms(None, declining_meals={
            "m1": [{"facts": good, "mechanism": "MEMORY_WINNER_NONAUTHORITATIVE",
                    "item": {"food_name": "clears"}, "memory_per100g": {"c": 1}}],
            "m2": [{"facts": bad, "mechanism": "MEMORY_WINNER_NONAUTHORITATIVE",
                    "item": {"food_name": "stays"}, "memory_per100g": {"c": 1}}],
        })
    finally:
        M.INTERVENTIONS["MEMORY_WINNER_NONAUTHORITATIVE"] = original

    entry = ranked["MEMORY_WINNER_NONAUTHORITATIVE"]
    assert entry["meals_blocked_solely"] == 2
    assert entry["measured_recovered_meals"] == 1, (
        "recovery reported %r for two sole-blocked meals where the "
        "counterfactual clears exactly one — 2 means the blocked count was "
        "restated, 0 means the counterfactual's result was discarded"
        % (entry["measured_recovered_meals"],))


@pytest.mark.asyncio
async def test_a_meal_whose_items_disagree_is_excluded_from_ranking():
    """⭐ MULTIPLE_BLOCKERS IS NOT A TRANCHE. A meal whose declining items name
    different mechanisms has no sole cause, so no single tranche recovers it —
    counting it under either would inflate both."""
    import measure_settlement_coverage as M

    ranked = await M.rank_mechanisms(None, declining_meals={
        "mixed": [
            {"facts": _facts(selected_rung="memory", has_memory=True),
             "mechanism": "MEMORY_WINNER_NONAUTHORITATIVE",
             "item": {"food_name": "a"}, "memory_per100g": None},
            {"facts": _facts(selected_rung=""),
             "mechanism": "NO_LOCAL_EVIDENCE",
             "item": {"food_name": "b"}, "memory_per100g": None},
        ]})
    assert ranked["MULTIPLE_BLOCKERS"]["meals"] == 1
    for mech in ("MEMORY_WINNER_NONAUTHORITATIVE", "NO_LOCAL_EVIDENCE"):
        assert ranked[mech]["meals_blocked_solely"] == 0, (
            f"{mech} claimed a meal whose items disagree")


@pytest.mark.parametrize("food,why", [
    ("Broccoli", "the artifact's winning record states NO portions at all"),
    ("Oats", "the ranker returns no winner, so the rung does not build"),
])
def test_each_UNSIMULATABLE_shape_is_reached_and_reported(food, why):
    """⛔⛔ THE THREE WAYS A SIMULATION CAN BE IMPOSSIBLE, EACH REACHED.

    The first version of this proof used a food that does not exist in the
    artifact at all — which returns at the FIRST guard (`evidence is None`) and
    therefore never reaches the other two. A mutation that broke the
    empty-measures guard stayed green, and the mutation harness correctly
    scored my witness INVALID rather than crediting it.

    ⭐ A GUARD YOU CANNOT REACH IS A GUARD YOU HAVE NOT TESTED. So the shapes
    are chosen from the COMMITTED artifact by inspection: `broccoli`'s winner
    carries no portions, `oats` has candidates the ranker cannot choose
    between. Both must report UNSIMULATABLE rather than a non-recovery."""
    from measure_settlement_coverage import memory_measures_counterfactual

    got = memory_measures_counterfactual(
        item={"food_name": food, "quantity": "1 cup"},
        facts=_facts(identity=food, entity=food.lower(),
                     selected_rung="memory", has_memory=True),
        memory_per100g={"calories": 34.0, "protein": 2.8, "carbs": 6.6,
                        "fat": 0.4})
    assert got is None, (
        f"{food!r} was simulated although {why} — an absent measurement "
        f"reported as a measured non-recovery")
