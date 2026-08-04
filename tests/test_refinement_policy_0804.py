"""Refinement is a decision with conditions, not a predicate.

`same_food("bread", "banana bread")` returned True, which is an invalid
identity assertion — a meal can contain both. The adversarial cases did NOT
reproduce a live deletion through `_undeferred`, whose exact-first injective
matching preserved every tested pair. That is evidence about one execution
path and not architectural clearance: the algorithm was compensating for a
false predicate, which is the latent coupling the rebuild exists to remove.

So identity is narrowed to aliases, refinement is a separate decision that
requires the caller to state its conditions, and the decision carries evidence
so production can be asked why a food was bound.
"""
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from data.identity_collisions import THREE_WAY_FAMILIES          # noqa: E402

from core.food_turn import _undeferred                           # noqa: E402
from skills.nutrition.entities import may_refine, same_food      # noqa: E402
from skills.nutrition.refinement import (RefinementContext,      # noqa: E402
                                         RefinementOperation,
                                         RefinementReason,
                                         evaluate_refinement)


def _ctx(size=1, exact=True, unconsumed=True):
    return RefinementContext(
        operation=RefinementOperation.UNDEFER_PENDING_ITEM,
        exact_pass_completed=exact, candidate_is_unconsumed=unconsumed,
        candidate_set_size=size)


def _c(n):
    return {"name": "log_food", "input": {"food_name": n}}


def _names(calls):
    return [c["input"]["food_name"] for c in calls]


# ── level 1: identity is narrow ──────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("bread", "banana bread"), ("rice", "fried rice"),
    ("orange", "orange chicken"), ("coffee", "coffee cake"),
    ("chicken", "chicken noodle soup"), ("yogurt", "greek yogurt"),
])
def test_relatedness_is_not_identity(a, b):
    assert same_food(a, b) is False, f"{a}/{b} must not be one entity"


@pytest.mark.parametrize("a,b", [
    ("potato", "potatoes"), ("cookie", "cookies"), ("berry", "berries"),
])
def test_a_true_alias_is_identity(a, b):
    assert same_food(a, b) is True


# ── level 2: refinement is directional and contextual ────────────────────────

def test_refinement_is_directional():
    """"greek yogurt" refines "yogurt"; the reverse is not a refinement.
    `_undeferred` compensates by asking both ways, because it cannot know which
    of its two readings is narrower — but the predicate itself stays honest."""
    assert may_refine("yogurt", "greek yogurt") is True
    assert may_refine("greek yogurt", "yogurt") is False


def test_ambiguity_refuses():
    d = evaluate_refinement("bread", "banana bread", _ctx(size=3))
    assert not d.allowed and d.reason is RefinementReason.AMBIGUOUS


def test_an_unfinished_exact_pass_refuses():
    d = evaluate_refinement("yogurt", "greek yogurt", _ctx(exact=False))
    assert not d.allowed
    assert d.reason is RefinementReason.EXACT_PASS_INCOMPLETE


def test_a_consumed_candidate_refuses():
    d = evaluate_refinement("yogurt", "greek yogurt", _ctx(unconsumed=False))
    assert not d.allowed
    assert d.reason is RefinementReason.CANDIDATE_CONSUMED


@pytest.mark.parametrize("a,b", [
    ("chicken", "chicken noodle soup"), ("banana", "banana bread"),
    ("orange", "orange juice"), ("milk", "milk chocolate"),
])
def test_a_recorded_boundary_refuses_with_its_reason(a, b):
    """An ingredient edge is a REFUSAL that was considered, not a gap nobody
    filled — and the decision says which."""
    d = evaluate_refinement(a, b, _ctx())
    assert not d.allowed
    assert d.reason in (RefinementReason.CROSSES_BOUNDARY,
                        RefinementReason.NOT_RELATED)
    assert d.evidence, "a refusal must carry its evidence"


def test_a_decision_names_both_entities():
    d = evaluate_refinement("yogurt", "greek yogurt", _ctx())
    assert d.allowed
    assert d.source_entity_id and d.candidate_entity_id
    assert d.source_entity_id != d.candidate_entity_id


def test_an_unknown_food_is_not_refinable():
    d = evaluate_refinement("zzyzx", "zzyzx surprise", _ctx())
    assert not d.allowed and d.reason is RefinementReason.UNKNOWN_ENTITY


# ── level 3: the end-to-end reconciliation ───────────────────────────────────

@pytest.mark.parametrize("family", THREE_WAY_FAMILIES)
def test_a_three_way_family_loses_nothing(family):
    """The generic term faces SEVERAL related compounds, so it has no exact
    counterpart to claim and must reach the refinement policy — which refuses
    on ambiguity. This is the case the adversarial PAIRS did not exercise."""
    kept = _undeferred([_c(f) for f in family], [])
    assert _names(kept) == family, f"lost {set(family) - set(_names(kept))}"


@pytest.mark.parametrize("family", THREE_WAY_FAMILIES)
def test_the_outcome_does_not_depend_on_plan_ordering(family):
    """Reconciliation must be a function of the SETS, not of the order the
    interpreter happened to emit."""
    import itertools

    held = [_c(f) for f in family]
    results = set()
    for plan in itertools.permutations(family[1:]):
        kept = _undeferred([_c(f) for f in family], [_c(p) for p in plan])
        results.add(tuple(sorted(_names(kept))))
    assert len(results) == 1, f"ordering changed the outcome: {results}"


@pytest.mark.parametrize("family", THREE_WAY_FAMILIES)
def test_nothing_is_duplicated(family):
    """The other half of the invariant. Not losing a food is not enough if it
    is written twice."""
    for plan in ([], family, family[:1], family[1:]):
        kept = _names(_undeferred([_c(f) for f in family],
                                  [_c(p) for p in plan]))
        assert len(kept) == len(set(kept)), f"duplicate in {kept}"
        # And nothing survives that the plan is also going to write.
        assert not (set(kept) & set(plan)), (
            f"{set(kept) & set(plan)} would be written twice")


# ── the rollback must actually roll back ─────────────────────────────────────
#
# REGRESSION, found in review of fba5ca1 and reproduced before fixing.
# `_refinement_decision` returned a bare None when either flag was off, and
# `_undeferred` had no branch for it — so a unique fuzzy candidate was
# PRESERVED instead of collapsed. The documented emergency control had silently
# become "create duplicates" rather than "restore the old matcher".

def _unique():
    return _undeferred([_c("White rice")], [_c("White rice, cooked")])


def _ambiguous():
    return _undeferred([_c("Bread")], [_c("Banana bread"), _c("Garlic bread")])


def test_strict_off_restores_unique_legacy_collapse(monkeypatch):
    monkeypatch.setenv("FOOD_IDENTITY_STRICT", "false")
    assert _names(_unique()) == [], "the legacy matcher should have collapsed"


def test_registry_off_restores_unique_legacy_collapse(monkeypatch):
    """The half the first fix missed. Guarding only on strict left the
    registry-off case with an EMPTY candidate set, so the legacy branch had
    nothing to decide — the flag rolled back the decision but not the candidate
    search."""
    monkeypatch.setenv("FOOD_IDENTITY_REGISTRY", "false")
    assert _names(_unique()) == []


def test_both_flags_off_restores_legacy(monkeypatch):
    monkeypatch.setenv("FOOD_IDENTITY_STRICT", "false")
    monkeypatch.setenv("FOOD_IDENTITY_REGISTRY", "false")
    assert _names(_unique()) == []


@pytest.mark.parametrize("env", [
    {"FOOD_IDENTITY_STRICT": "false"},
    {"FOOD_IDENTITY_REGISTRY": "false"},
    {"FOOD_IDENTITY_STRICT": "false", "FOOD_IDENTITY_REGISTRY": "false"},
])
def test_rollback_still_does_not_collapse_ambiguous_candidates(env, monkeypatch):
    """Rolling back restores the OLD behaviour, which also carried on
    ambiguity. A rollback that started merging three-way families would be a
    second bug wearing the first one's clothes."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert _names(_ambiguous()) == ["Bread"]


def test_a_broken_policy_fails_closed_rather_than_falling_back(monkeypatch):
    """A DELIBERATE ROLLBACK AND A BROKEN MODULE ARE DIFFERENT EVENTS, and
    used to be indistinguishable — both produced None.

    They need opposite behaviour. Turning the flag off asks for the legacy
    matcher; an import error must NOT silently re-enable the very matcher
    strict mode exists to prevent. So failure preserves both foods.
    """
    import skills.nutrition.refinement as R

    def _boom(*a, **k):
        raise ImportError("policy module gone")

    monkeypatch.setattr(R, "evaluate_refinement", _boom)
    assert _names(_unique()) == ["White rice"], "failure must fail closed"

    from core.food_turn import _refinement_decision
    from skills.nutrition.refinement import DecisionMode
    assert _refinement_decision("white rice", ["white rice, cooked"]).mode \
        is DecisionMode.FAILED_CLOSED


def test_the_decision_says_which_mode_produced_it(monkeypatch):
    """Observability: production must be able to separate "we rolled back" from
    "the policy broke" from "the policy decided"."""
    from core.food_turn import _refinement_decision
    from skills.nutrition.refinement import DecisionMode

    assert _refinement_decision("white rice", ["white rice, cooked"]).mode \
        is DecisionMode.POLICY
    monkeypatch.setenv("FOOD_IDENTITY_STRICT", "false")
    assert _refinement_decision("white rice", ["white rice, cooked"]).mode \
        is DecisionMode.LEGACY_FALLBACK


def test_unevaluated_quantity_compatibility_is_not_reported_as_met():
    """`quantity_compatible: bool = True` let an unchecked condition be
    reported as a satisfied one — one piece of non-evidence inside an object
    whose entire purpose is to carry evidence."""
    from core.food_turn import _refinement_decision

    # A REFINEMENT, not an alias. "white rice" / "white rice, cooked" is the
    # same entity and returns before the quantity check is reached.
    d = _refinement_decision("yogurt", ["greek yogurt"])
    assert d.allowed
    assert any("not evaluated" in e for e in d.evidence), d.evidence


def test_a_runtime_exception_inside_the_policy_also_fails_closed(monkeypatch):
    """The import-failure test proved one path. A policy that IMPORTS and then
    RAISES is the likelier failure in practice — a bad row, a None where an
    entity was expected — and the broad handler must treat it the same way.

    Fail closed means BOTH foods survive. Falling back to the legacy matcher
    here would silently re-enable deletion-capable fuzzy matching at exactly
    the moment the safety policy is known to be broken.
    """
    import skills.nutrition.refinement as R
    from skills.nutrition.refinement import DecisionMode

    def _boom(*a, **k):
        raise RuntimeError("policy raised at runtime")

    monkeypatch.setattr(R, "evaluate_refinement", _boom)
    assert _names(_unique()) == ["White rice"]

    from core.food_turn import _refinement_decision
    d = _refinement_decision("white rice", ["white rice, cooked"])
    assert d.mode is DecisionMode.FAILED_CLOSED and not d.allowed


def test_the_mode_branch_compares_the_enum_not_a_string():
    """`DecisionMode` was introduced to remove an ambiguous string contract;
    comparing `.value == "legacy_fallback"` recreated one, where a typo reads
    as "not a rollback" and silently preserves duplicates."""
    import inspect

    import core.food_turn as FT

    # The check lives in `_is_legacy_fallback` so the import can be guarded —
    # a module-scope enum is None when the policy is unavailable, and
    # dereferencing it raises inside the branch meant to survive that.
    src = inspect.getsource(FT._undeferred) + inspect.getsource(
        FT._is_legacy_fallback)
    assert 'mode.value ==' not in src, (
        "the rollback branch is comparing a string again")
    assert 'getattr(mode, "value"' not in src, (
        "the string contract came back through getattr")
    assert "is DecisionMode.LEGACY_FALLBACK" in src
