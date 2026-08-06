"""B-1.9 commit 5 — selection is a pure, versioned policy over the universe.

    CandidateSet + CandidateSelectionContext + policy version
        -> selected candidates, and a typed reason for every other one

The gates below defend that signature. A selector that reached for anything
else — a food name, a fresh query, a rendered label — would produce decisions
the persisted record could not explain, which is the one property the whole
durable universe exists to provide.
"""
import pathlib
import re
from decimal import Decimal

import pytest

from core.semantics import (CandidateSelectionContext, CandidateSet,
                            CandidateSource, EvidenceContext, ExclusionReason,
                            SelectionSurface, ServingBasis, measure_on)
from skills.nutrition import candidate_selection as policy
from tests._typed_candidates import ENTITY, candidate

REPO = pathlib.Path(__file__).resolve().parent.parent


def _ctx(**kw):
    from skills.nutrition.quantity_clarification import (
        RENDERER_CONTRACT_VERSION)

    base = dict(surface=SelectionSurface.LABEL_TEXT, locale="en",
                maximum_options=3,
                renderer_contract_version=RENDERER_CONTRACT_VERSION)
    base.update(kw)
    return CandidateSelectionContext(**base)


def _universe(*candidates, user_id=26):
    return CandidateSet(
        candidate_set_id="cs1", operation_id="op1", user_id=user_id,
        context=EvidenceContext(user_id=user_id, canonical_entity_id=ENTITY),
        interaction_revision=0, field_id="f1", generator_version="gen_v1",
        generation_input_fingerprint="fp", candidates=candidates)


def _ids(candidates):
    return [c.candidate_id for c in candidates]


# ── determinism ─────────────────────────────────────────────────────────────

def test_the_same_inputs_always_produce_the_same_decision():
    """Set + context + policy is the WHOLE input. Nothing else may vary the
    result, or the persisted record stops explaining the screen."""
    universe = _universe(candidate("c1", 85.0, prior=0.2),
                         candidate("c2", 141.7,
                                   source=CandidateSource.USER_HISTORY,
                                   prior=0.55, confidence=0.9),
                         candidate("c3", 226.0, prior=0.3))
    runs = [policy.select(universe, context=_ctx()) for _ in range(5)]
    first = (_ids(runs[0][0]), sorted(runs[0][1]))
    for chosen, excluded in runs[1:]:
        assert (_ids(chosen), sorted(excluded)) == first


def test_an_unregistered_policy_fails_shut():
    with pytest.raises(ValueError, match="not a registered selection policy"):
        policy.select(_universe(candidate("c1", 85.0)), context=_ctx(),
                      policy_version="wishful_v9")


def test_a_version_cannot_be_redefined():
    """A policy version names one rule forever. Redefining it would silently
    change what past decisions claimed to be."""
    with pytest.raises(ValueError, match="already registered"):
        policy.register(policy.SELECTION_POLICY_VERSION)(lambda u, c: ((), ()))


def test_registering_a_new_version_leaves_the_baseline_alone():
    """`changing policy version permits a new append-only decision` — and the
    old policy must keep deciding exactly as it did."""
    @policy.register("test_take_nothing_v1")
    def _nothing(universe, context):
        return (), tuple((c.candidate_id, ExclusionReason.SELECTION_CAP)
                         for c in universe.candidates)

    universe = _universe(candidate("c1", 85.0), candidate("c2", 226.0))
    assert policy.select(universe, context=_ctx(),
                         policy_version="test_take_nothing_v1")[0] == ()
    assert _ids(policy.select(universe, context=_ctx())[0]) == ["c1", "c2"]
    assert {"test_take_nothing_v1",
            policy.SELECTION_POLICY_VERSION} <= policy.registered()


# ── the partition ───────────────────────────────────────────────────────────

def test_every_candidate_is_selected_or_excluded_exactly_once():
    universe = _universe(*(candidate(f"c{i}", 50.0 * (i + 1))
                           for i in range(6)))
    chosen, excluded = policy.select(universe, context=_ctx())
    decided = _ids(chosen) + [cid for cid, _r in excluded]
    assert sorted(decided) == sorted(universe.candidate_ids)
    assert len(decided) == len(set(decided))


def test_a_policy_that_loses_a_candidate_is_rejected():
    """The aggregate catches it later, but by then the message is about a
    record rather than about the rule that produced it — and a new policy is
    exactly where this mistake gets made."""
    @policy.register("test_forgetful_v1")
    def _forgetful(universe, context):
        return (universe.candidates[0],), ()

    with pytest.raises(ValueError, match="did not account for every"):
        policy.select(_universe(candidate("c1", 85.0), candidate("c2", 226.0)),
                      context=_ctx(), policy_version="test_forgetful_v1")


def test_every_exclusion_names_the_branch_that_produced_it():
    universe = _universe(
        candidate("keep", 85.0, prior=0.9),
        candidate("twin", 86.0, prior=0.5),          # semantically the same
        candidate("far1", 300.0, prior=0.4),
        candidate("far2", 600.0, prior=0.3),
        candidate("far3", 1200.0, prior=0.2))        # past the cap
    _chosen, excluded = policy.select(universe, context=_ctx())
    reasons = dict(excluded)
    assert reasons["twin"] is ExclusionReason.SEMANTIC_DUPLICATE
    assert reasons["far3"] is ExclusionReason.SELECTION_CAP
    assert all(isinstance(r, ExclusionReason) for r in reasons.values())


# ── purity ──────────────────────────────────────────────────────────────────

def test_the_selector_reads_no_labels_and_fetches_no_evidence():
    """A SOURCE SCAN, because the defect is a dependency rather than an
    output: a selector that rendered a label would decide identically today
    and differently the first time a locale worded two candidates apart."""
    source = (REPO / "skills" / "nutrition"
              / "candidate_selection.py").read_text()
    for forbidden in ("labels_for", "_everyday_labels", "normalize_quantity",
                      "distribution_for", "db.execute", "await ",
                      "food_name", "re.compile", "_history"):
        assert forbidden not in source, (
            f"the selector reached for {forbidden!r}; it may read persisted "
            f"candidate features and nothing else")


def test_the_selector_does_not_mutate_what_it_is_given():
    universe = _universe(candidate("c1", 85.0), candidate("c2", 226.0))
    before = universe.to_payload()
    policy.select(universe, context=_ctx())
    assert universe.to_payload() == before


def test_no_food_name_or_curated_tier_reaches_the_policy():
    """Entity-agnostic by construction: the policy signature has nowhere to
    put a food name, so a per-food branch cannot be written without changing
    the contract."""
    import inspect

    params = inspect.signature(policy.select).parameters
    assert set(params) == {"universe", "context", "policy_version"}


# ── the rules themselves ────────────────────────────────────────────────────

def test_a_users_own_history_outranks_the_population():
    """Not by naming a source. History carries prior 0.55 at confidence 0.9
    and the ontology median 0.5 at 0.6, so the ladder falls out of the
    persisted features."""
    history = candidate("hist", 141.7, source=CandidateSource.USER_HISTORY,
                        prior=0.55, confidence=0.9)
    ontology = candidate("ont", 500.0, prior=0.5, confidence=0.6)
    assert policy.rank_of(history) > policy.rank_of(ontology)
    chosen, _ = policy.select(_universe(history, ontology),
                              context=_ctx(maximum_options=1))
    assert _ids(chosen) == ["hist"]


def test_semantically_equivalent_candidates_collapse_and_the_better_survives():
    keep = candidate("keep", 140.0, source=CandidateSource.USER_HISTORY,
                     prior=0.55, confidence=0.9)
    twin = candidate("twin", 141.7, prior=0.3, confidence=0.6)
    chosen, excluded = policy.select(_universe(keep, twin), context=_ctx())
    assert _ids(chosen) == ["keep"]
    assert dict(excluded)["twin"] is ExclusionReason.SEMANTIC_DUPLICATE


def test_distinct_serving_bases_are_never_collapsed():
    """`1 piece` and `1 g` can be numerically adjacent and mean nothing like
    each other. Collapsing them would delete a genuinely distinct option and
    record it as a duplicate."""
    from core.semantics import (CanonicalQuantity, EvidenceScope,
                                QuantityCandidate, QuantityCandidateEvidence,
                                ServingExpression, SourceReference)

    mass = candidate("mass", 1.0)
    one = CanonicalQuantity(count=Decimal("1"))
    # PIECE-BASIS EVIDENCE, because the contract refuses evidence observed on
    # another basis without a sourced conversion — correctly.
    piece = QuantityCandidate(
        candidate_id="piece", canonical_entity_id=ENTITY, quantity=one,
        serving_basis=ServingBasis.PIECE,
        offered=ServingExpression(amount=Decimal("1"), unit_id="piece",
                                  basis=ServingBasis.PIECE, normalized=one),
        evidence=(QuantityCandidateEvidence(
            source_type=CandidateSource.ONTOLOGY,
            source=SourceReference(dataset_id="portion_ontology",
                                   dataset_version="2026-08-06",
                                   record_key="chicken breast:piece",
                                   immutable_within_version=True),
            observed_quantity=one, observed_basis=ServingBasis.PIECE,
            subject_scope=EvidenceScope.POPULATION,
            confidence=Decimal("0.6")),),
        prior=Decimal("0.4"))
    assert not policy._says_the_same_thing(mass, piece)
    chosen, excluded = policy.select(_universe(mass, piece), context=_ctx())
    assert sorted(_ids(chosen)) == ["mass", "piece"]
    assert excluded == ()


def test_the_option_capacity_comes_from_the_channel_not_from_a_constant():
    """How many options fit is a property of the surface — three in a
    sentence, more in a chip row — so a policy that hardcoded it could not be
    reused across channels."""
    universe = _universe(*(candidate(f"c{i}", 60.0 * (i + 2) ** 2)
                           for i in range(5)))
    for capacity in (1, 2, 3, 5):
        chosen, excluded = policy.select(
            universe, context=_ctx(maximum_options=capacity,
                                   surface=SelectionSurface.ID_ADDRESSED))
        assert len(chosen) == min(capacity, 5)
        capped = [cid for cid, r in excluded
                  if r is ExclusionReason.SELECTION_CAP]
        # NOTHING IS LOST TO THE CAP SILENTLY — every dropped candidate is
        # still named, with the branch that dropped it.
        assert len(chosen) + len(capped) == 5


def test_the_selected_row_climbs():
    universe = _universe(candidate("c1", 226.0, prior=0.9),
                         candidate("c2", 85.0, prior=0.8),
                         candidate("c3", 141.7, prior=0.7))
    chosen, _ = policy.select(universe, context=_ctx())
    amounts = [float(measure_on(c.quantity, c.serving_basis)) for c in chosen]
    assert amounts == sorted(amounts)


def test_population_evidence_still_cannot_authorise_an_assumption():
    """Selection may OFFER a population candidate; it may never make one
    sufficient to assert a portion on someone's behalf. The two questions stay
    separate."""
    ontology = candidate("ont", 141.7)
    chosen, _ = policy.select(_universe(ontology), context=_ctx())
    assert _ids(chosen) == ["ont"]
    assert not chosen[0].authorizes_assumption(
        EvidenceContext(user_id=26, canonical_entity_id=ENTITY))


# ── the baseline is still what ships ────────────────────────────────────────

def test_the_visible_row_is_unchanged_by_the_restructure():
    """`b1_quantity_select_v1` reproduces the behaviour shipped before the
    selector became a module — to the option, in order."""
    from skills.nutrition import quantity_clarification as qc
    from skills.nutrition.staging import FoodIdentity, StagedFoodItem

    item = StagedFoodItem(staged_item_id="si", original_text="x",
                          identity=FoodIdentity(canonical_name="chicken breast"))
    field = qc.quantity_field(operation_id="op", revision=0, item=item)
    universe = _universe(
        candidate("ont_low", 85.0, prior=0.2),
        candidate("hist", 141.7, source=CandidateSource.USER_HISTORY,
                  prior=0.55, confidence=0.9),
        candidate("ont_high", 226.0, prior=0.3))
    options, record = qc.reduce_universe(universe, field=field, context=_ctx(),
                                         food_name="chicken breast")
    assert [o.label for o in options] == ["3 oz", "5 oz", "8 oz"]
    assert record.decision.selection_policy_version == (
        policy.SELECTION_POLICY_VERSION)
    assert all(o.patch is not None and o.candidate_id for o in options)


def test_a_render_collision_is_recorded_against_the_renderer_not_the_policy():
    """Selection decides what a candidate MEANS; presentation decides what it
    SAYS. A wording judgement must not be attributable to the policy."""
    from skills.nutrition import quantity_clarification as qc
    from skills.nutrition.staging import FoodIdentity, StagedFoodItem

    item = StagedFoodItem(staged_item_id="si", original_text="x",
                          identity=FoodIdentity(canonical_name="chicken breast"))
    field = qc.quantity_field(operation_id="op", revision=0, item=item)
    # 130.5 / 174 / 435 g is the measured production bracket: numerically
    # separated, and rendered "5 oz / 6 oz / 16 oz".
    universe = _universe(candidate("low", 130.5, prior=0.2),
                         candidate("mid", 174.0, prior=0.5),
                         candidate("high", 435.0, prior=0.3))
    _options, record = qc.reduce_universe(universe, field=field,
                                          context=_ctx(),
                                          food_name="chicken breast")
    collided = [x for x in record.decision.exclusions
                if x.reason is ExclusionReason.RENDER_COLLISION]
    assert collided, "the label pass reported no collision on the measured set"
    # The POLICY selected all three; presentation dropped one.
    chosen, excluded = policy.select(universe, context=_ctx())
    assert len(chosen) == 3 and excluded == ()


# ── 5.1 — exact arithmetic, and purity proven by trap rather than by scan ───

def test_ranking_and_thresholds_never_pass_through_a_float():
    """P1. `float()` WAS A HOLE IN THE DETERMINISM THIS MODULE CLAIMS.

    Two Decimal scores differing in the 18th place collapse to one binary
    float, and generation order silently becomes the tie-breaker — an
    accidental rule nobody wrote, reached only by inputs nobody would think to
    test. The same applied to the near-duplicate ratio and to the final
    ordering.
    """
    # A DECIMAL LITERAL, because `0.5000000000000000001` written as a Python
    # float is already 0.5 before anything here sees it — which is the defect
    # in miniature.
    close = candidate("close", 141.7, prior=Decimal("0.5000000000000000001"),
                      confidence=Decimal("0.6"))
    other = candidate("other", 141.7, prior=Decimal("0.5"),
                      confidence=Decimal("0.6"))
    assert isinstance(policy.rank_of(close), Decimal)
    assert isinstance(policy.NEAR_DUPLICATE_RATIO, Decimal)
    # Distinguishable in Decimal; identical once either passes through float.
    assert policy.rank_of(close) != policy.rank_of(other)
    assert float(policy.rank_of(close)) == float(policy.rank_of(other))


def test_the_near_duplicate_test_does_not_depend_on_the_decimal_context():
    """`hi / lo < ratio` is exact only to the ambient context's precision, and
    that context is process-wide state any library can change — the same trap
    already found in conversion rounding."""
    from decimal import ROUND_UP, localcontext

    a, b = Decimal("100"), Decimal("124.9")
    before = policy._near(a, b)
    with localcontext() as ctx:
        ctx.prec = 3
        ctx.rounding = ROUND_UP
        assert policy._near(a, b) is before
    assert before is True
    assert policy._near(Decimal("100"), Decimal("125")) is False


def test_equal_ranks_break_ties_by_a_stated_rule():
    """Ties used to be resolved by `sorted`'s stability — i.e. by whatever
    order the generator happened to emit, a real rule written nowhere."""
    first = candidate("first", 100.0, prior=0.5, confidence=0.6)
    second = candidate("second", 500.0, prior=0.5, confidence=0.6)
    assert policy.rank_of(first) == policy.rank_of(second)
    chosen, _ = policy.select(_universe(first, second),
                              context=_ctx(maximum_options=1))
    assert _ids(chosen) == ["first"], "the earlier-generated candidate wins"


def test_the_policy_touches_only_approved_candidate_fields():
    """P2. A STRING SCAN CANNOT PROVE ABSENCE.

    It catches an obvious call and misses an indirect one. This wraps every
    candidate in a proxy that RAISES on any attribute outside the approved
    set, so a future policy reaching for something new fails here rather than
    quietly making decisions the persisted record cannot explain.
    """
    APPROVED = {"candidate_id", "canonical_entity_id", "quantity",
                "serving_basis", "evidence", "semantic_hash", "prior",
                "offered", "applies_to", "authorizes_assumption"}

    class _Trap:
        def __init__(self, inner):
            object.__setattr__(self, "_inner", inner)

        def __getattr__(self, name):
            if name.startswith("__"):
                return getattr(object.__getattribute__(self, "_inner"), name)
            if name not in APPROVED:
                raise AssertionError(
                    f"the selector read {name!r}, which is not an approved "
                    f"persisted candidate feature")
            return getattr(object.__getattribute__(self, "_inner"), name)

        def __setattr__(self, name, value):
            raise AssertionError(f"the selector mutated {name!r}")

    real = (candidate("c1", 85.0, prior=0.2),
            candidate("c2", 141.7, source=CandidateSource.USER_HISTORY,
                      prior=0.55, confidence=0.9),
            candidate("c3", 226.0, prior=0.3))
    universe = _universe(*real)

    class _Watched:
        candidate_ids = universe.candidate_ids
        candidates = tuple(_Trap(c) for c in real)

    chosen, excluded = policy.select(_Watched(), context=_ctx())
    assert len(chosen) + len(excluded) == 3


def test_the_policy_reads_only_approved_context_fields():
    """The context decides capacity and surface; a policy reaching past those
    would make decisions that a stored context could not reproduce."""
    APPROVED = {"maximum_options", "surface", "locale",
                "renderer_contract_version"}
    seen = []

    class _WatchedContext:
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            assert name in APPROVED, f"the selector read context.{name!r}"
            seen.append(name)
            return 3 if name == "maximum_options" else "x"

    policy.select(_universe(candidate("c1", 85.0), candidate("c2", 500.0)),
                  context=_WatchedContext())
    assert "maximum_options" in seen
