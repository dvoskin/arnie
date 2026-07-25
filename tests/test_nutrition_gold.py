"""The gold-set runner (work order step 9).

Every case in tests/gold/nutrition_cases.py runs through the real resolver
with fixed candidate data, so nutrient correctness becomes a number that moves
rather than a series of anecdotes — and it runs offline, because what is under
test is the resolution logic, not whether USDA is up.

A failure here names the case id, which is also the ticket: adding a case is
the cheapest way to make a nutrition bug stay fixed.
"""
from collections import Counter

import pytest

from skills.nutrition.candidates import Candidate
from skills.nutrition.models import FoodResolutionRequest, profile_from_values
from skills.nutrition.resolver import resolve, should_ask
from skills.nutrition.provenance import SourceTier
from skills.nutrition.scaling import basis_from_spec
from tests.gold.nutrition_cases import ALL_CASES

def _basis(spec):
    # `as_served` follows the tier: a branded/USDA serving is measured, every
    # other tier describes the helping the user actually had.
    return basis_from_spec(
        spec.get("basis", "per_100g"),
        serving_mass_g=spec.get("serving_mass_g"),
        as_served=SourceTier(spec["tier"]).describes_as_served)


def _candidate(spec):
    return Candidate(
        source=spec["source"], tier=spec["tier"], name=spec["name"],
        profile=profile_from_values(spec["source"], basis=spec["basis"],
                                    confidence=0.8, **spec["values"]),
        basis=_basis(spec), brand=spec.get("brand"),
        variant=spec.get("variant"), reported_grade=spec["grade"])


def _run(case):
    request = FoodResolutionRequest(**case["request"])
    return request, resolve(request, [_candidate(s) for s in case["candidates"]])


def _ids(cases):
    return [c["id"] for c in cases]


@pytest.mark.parametrize("case", ALL_CASES, ids=_ids(ALL_CASES))
def test_gold_case(case):
    request, out = _run(case)
    expect = case["expect"]
    where = f"[{case['id']}]"

    if "source" in expect:
        assert out.source == expect["source"], (
            f"{where} expected source {expect['source']}, got {out.source} "
            f"(rejected: {[r.reason for r in out.rejected_candidates]})")

    if "identity" in expect:
        assert out.canonical_name == expect["identity"], where

    if "grade" in expect:
        assert out.match_grade == expect["grade"], where

    for field in ("calories", "protein"):
        if field in expect:
            lo, hi = expect[field]
            actual = out.nutrients.amount(field)
            assert actual is not None, f"{where} {field} was unknown"
            assert lo <= actual <= hi, (
                f"{where} {field} {actual} outside [{lo}, {hi}]")

    for field in expect.get("known", ()):
        assert out.nutrients.amount(field) is not None, (
            f"{where} {field} should be populated, is unknown")

    for field in expect.get("unknown", ()):
        # The rule this pins: unknown is NULL, never 0. A zero here would read
        # as an established product fact.
        assert out.nutrients.amount(field) is None, (
            f"{where} {field} should be unknown, is "
            f"{out.nutrients.amount(field)}")
        assert field not in out.nutrients.as_dict(), (
            f"{where} {field} must not be persisted as a value")

    for source in expect.get("rejects", ()):
        assert any(r.source == source for r in out.rejected_candidates), (
            f"{where} expected {source} to lose and be recorded losing; "
            f"recorded: {[(r.source, r.reason) for r in out.rejected_candidates]}")

    if "assumption_contains" in expect:
        needle = expect["assumption_contains"]
        assert any(needle in a for a in out.assumptions), (
            f"{where} no assumption contains {needle!r}: {out.assumptions}")

    if "warning_contains" in expect:
        needle = expect["warning_contains"]
        assert any(needle in w for w in out.warnings), (
            f"{where} no warning contains {needle!r}: {out.warnings}")

    for mode, should in (expect.get("asks") or {}).items():
        asked = should_ask(out.ambiguities, mode) is not None
        assert asked == should, (
            f"{where} mode={mode} expected asks={should}, got {asked} "
            f"(ambiguities: {[(a.field, a.calorie_span, a.calorie_fraction) for a in out.ambiguities]})")


# ── properties that must hold across the WHOLE set ────────────────────────────
@pytest.mark.parametrize("case", ALL_CASES, ids=_ids(ALL_CASES))
def test_no_case_ever_persists_a_zero_it_did_not_learn(case):
    """The invariant with the widest blast radius. A zero written for a field
    nothing established turns "we don't know this product's sodium" into "this
    product has no sodium" — and the health score believes it."""
    _, out = _run(case)
    persisted = out.nutrients.as_dict()
    for field, value in persisted.items():
        source_value = out.nutrients.get(field)
        assert source_value is not None, case["id"]
        if value == 0:
            # A real zero is allowed, but only when a source actually said so.
            assert source_value.source not in ("", None), case["id"]


@pytest.mark.parametrize("case", ALL_CASES, ids=_ids(ALL_CASES))
def test_every_resolution_is_explainable(case):
    """No silent answers: a resolution either names its source and grade, or
    says it could not resolve. Both are fine; a confident anonymous number is
    not."""
    _, out = _run(case)
    if out.source == "unresolved":
        assert out.warnings, case["id"]
        assert out.nutrients.is_empty, case["id"]
    else:
        assert out.match_grade, case["id"]
        assert out.tier is not None, case["id"]
        assert out.resolver_version, case["id"]


@pytest.mark.parametrize("case", ALL_CASES, ids=_ids(ALL_CASES))
def test_mode_never_changes_the_nutrition_answer(case):
    """Strictness is friction policy, not truth policy. The same food resolved
    in quick and strict must produce identical numbers."""
    quick = resolve(FoodResolutionRequest(**{**case["request"], "mode": "quick"}),
                    [_candidate(s) for s in case["candidates"]])
    strict = resolve(FoodResolutionRequest(**{**case["request"], "mode": "strict"}),
                     [_candidate(s) for s in case["candidates"]])
    assert quick.nutrients.as_dict() == strict.nutrients.as_dict(), case["id"]
    assert quick.source == strict.source, case["id"]


def test_the_set_covers_every_category():
    """A gold set that drifts to one category stops being a safety net."""
    categories = {c["category"] for c in ALL_CASES}
    assert categories >= {"branded", "generic", "pieces", "composite",
                          "micros", "modes"}


def test_case_ids_are_unique():
    ids = [c["id"] for c in ALL_CASES]
    assert len(ids) == len(set(ids))


#: Floors, not targets. A gold set shrinks by attrition — a case deleted to
#: make a change go green, a category quietly stopping at four rows — and the
#: shrinking is invisible without a number to fail against. Raise these when
#: the set grows; lowering one should take an argument.
CATEGORY_FLOORS = {"branded": 45, "generic": 15, "pieces": 12,
                   "composite": 22, "micros": 20, "modes": 6,
                   "ambiguity": 12, "portioning": 20}


def test_the_set_has_not_shrunk():
    counts = Counter(c["category"] for c in ALL_CASES)
    short = {k: (counts.get(k, 0), floor)
             for k, floor in CATEGORY_FLOORS.items() if counts.get(k, 0) < floor}
    assert not short, f"categories below their floor (have, floor): {short}"
    assert len(ALL_CASES) >= 170, len(ALL_CASES)
