"""PHASE 0.4 — the model becomes a one-time annotator; code owns policy.

Two things were measured before this design was chosen, and both constrain it.

REMOVING THE MODEL IS NOT VIABLE. With mechanical eligibility alone,
deterministic fuzzy ranking selects `Babyfood, guava and papaya with tapioca`
for "papaya", `Chicken spread` for "chicken" and `Fish oil, salmon` at
902 kcal for "salmon". The semantic boundary is load bearing.

RE-SAMPLING THE MODEL IS NOT VIABLE EITHER. `temperature` returns
`400 deprecated for this model`, and a row scoring 0.75 in one build and 0.80
in the next enters or leaves the priced universe with no source change.

So: judge once, store it, version it, and let CODE decide what the judgement
means. The gates below are the ones that distinguish that from a cache.
"""
from __future__ import annotations

import pytest

from skills.nutrition import semantic_annotations as sa

IDENTITY = "mackerel|roasted"


def _ann(evidence_id="usda:1", relationship=sa.SAME_IDENTITY, confidence=0.9,
         **kw):
    return sa.Annotation(identity_key=IDENTITY, evidence_id=evidence_id,
                         relationship=relationship, confidence=confidence,
                         **kw)


# ── ⭐ GATE 0.4.6 — POLICY OWNS ELIGIBILITY ────────────────────────────────

def test_the_vocabulary_cannot_express_an_operational_conclusion():
    """A relationship is an OBSERVATION. If the vocabulary could say
    "eligible", the model could state a conclusion and the gate would have
    been serialized rather than removed."""
    assert not (sa.RELATIONSHIPS & {"ELIGIBLE", "eligible", "PRICE", "USE",
                                    "WINNER", "RANK"})


def test_an_annotation_cannot_carry_an_eligible_field():
    import dataclasses

    names = {f.name for f in dataclasses.fields(sa.Annotation)}
    assert not (names & {"eligible", "priceable", "use", "winner", "rank",
                         "price"}), (
        "the model's conclusion would be persisted, which is the gate with a "
        "longer cache rather than the gate removed")


def test_code_decides_what_the_relationship_means():
    """The same stored observation yields different eligibility under
    different POLICY — which is only possible because policy is code."""
    assert sa.eligible(_ann(relationship=sa.SAME_IDENTITY, confidence=0.9))
    assert sa.eligible(_ann(relationship=sa.COMPATIBLE_SPECIALIZATION,
                            confidence=0.85))
    assert not sa.eligible(_ann(relationship=sa.SAME_IDENTITY, confidence=0.7))
    assert not sa.eligible(_ann(relationship=sa.DIFFERENT_IDENTITY,
                                confidence=0.99))
    assert not sa.eligible(_ann(relationship=sa.AMBIGUOUS, confidence=0.99))


# ── ⭐⭐ GATE 0.4.5 — UNKNOWN IS NON-DESTRUCTIVE ───────────────────────────

def test_a_missing_annotation_is_unresolved_and_never_a_different_identity():
    """THE INVARIANT. A timeout, a malformed reply, a no-text reply and a row
    nobody has classified are all UNRESOLVED. None is evidence that a record
    is a different food."""
    assert sa.disposition(None) == "unresolved_never_annotated"
    assert sa.disposition(_ann(relationship=sa.UNRESOLVED)) == "unresolved"
    for absent in (None, _ann(relationship=sa.UNRESOLVED)):
        assert sa.disposition(absent) != "different_identity"


def test_the_model_cannot_assert_unresolved():
    """UNRESOLVED is what the SYSTEM records when no verdict exists. A model
    able to claim it could launder a failure into a stored fact."""
    assert sa.UNRESOLVED not in sa.MODEL_ASSERTABLE
    assert sa.MODEL_ASSERTABLE < sa.RELATIONSHIPS


def test_disposition_separates_four_reasons_that_all_mean_not_priced():
    """Collapsing these is the defect this phase exists to remove. Two are
    revisitable and two are settled, and only a distinct reason says which."""
    assert sa.disposition(None).startswith("unresolved")
    assert sa.disposition(_ann(relationship=sa.AMBIGUOUS)) == "ambiguous"
    assert sa.disposition(_ann(relationship=sa.DIFFERENT_IDENTITY)) \
        == "different_identity"
    assert sa.disposition(_ann(confidence=0.5)) == "below_confidence"
    assert len({sa.disposition(None),
                sa.disposition(_ann(relationship=sa.AMBIGUOUS)),
                sa.disposition(_ann(relationship=sa.DIFFERENT_IDENTITY)),
                sa.disposition(_ann(confidence=0.5))}) == 4


def test_a_corrupt_stored_row_loads_as_absent_not_as_a_negative():
    store = sa.Store.from_payload({"k": {"relationship": "NONSENSE"}})
    assert store.by_key == {}
    assert sa.disposition(store.get(IDENTITY, "usda:1")) \
        == "unresolved_never_annotated"


# ── ⭐ GATE 0.4.1 — KNOWN EVIDENCE ASKS THE RESOLVER NOTHING ───────────────

def test_a_known_pair_never_needs_resolution():
    store = sa.Store()
    store.record(_ann())
    assert not store.needs_resolution(IDENTITY, "usda:1")


def test_an_unseen_pair_may_be_resolved():
    store = sa.Store()
    store.record(_ann())
    assert store.needs_resolution(IDENTITY, "usda:999")


def test_reuse_does_not_consider_whether_the_model_would_now_agree():
    """Marginal confidence, a newer model and an ordinary rebuild are each a
    way to re-roll a judgement without deciding to. `needs_resolution` reads
    only whether a resolved annotation EXISTS."""
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(sa.Store.needs_resolution))
    tree = ast.parse(src)
    read = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    # `source_fingerprint` is deliberately permitted: a judgement is ABOUT a
    # specific source row, so a changed row makes the stored verdict answer a
    # question nobody asked. That is `source_changed`, not a re-roll.
    assert not (read & {"confidence", "resolver_model", "resolver_version",
                        "created_at"}), (
        f"reuse consults {read} — anything beyond existence is a door for "
        f"re-rolling a stored judgement")


# ── ⭐ GATE 0.4.3 — A NEWER MODEL IS NOT AN INVALIDATION EVENT ─────────────

def test_a_model_version_change_alone_does_not_permit_replacement():
    store = sa.Store()
    store.record(_ann(resolver_model="claude-sonnet-5"))
    with pytest.raises(sa.AnnotationReplacementRefused):
        store.record(_ann(relationship=sa.DIFFERENT_IDENTITY,
                          resolver_model="claude-sonnet-6"))


@pytest.mark.parametrize("cause", ["rebuild", "retry", "new_model_available",
                                   "confidence_changed", "unexplained", ""])
def test_the_causes_that_let_history_rewrite_itself_cannot_be_spelled(cause):
    store = sa.Store()
    store.record(_ann())
    with pytest.raises(sa.AnnotationReplacementRefused):
        store.record(_ann(relationship=sa.DIFFERENT_IDENTITY), cause=cause)


# ── ⭐ GATE 0.4.8 — REPLACEMENT REQUIRES A STATED CAUSE ────────────────────

@pytest.mark.parametrize("cause", sorted(sa.INVALIDATION_CAUSES))
def test_an_explicit_cause_permits_replacement(cause):
    store = sa.Store()
    store.record(_ann())
    store.record(_ann(relationship=sa.DIFFERENT_IDENTITY), cause=cause)
    assert store.get(IDENTITY, "usda:1").relationship == sa.DIFFERENT_IDENTITY


def test_an_unresolved_placeholder_may_be_filled_without_a_cause():
    """Recording a first real judgement over UNRESOLVED is not a replacement —
    nothing is being overwritten."""
    store = sa.Store()
    store.record(_ann(relationship=sa.UNRESOLVED, confidence=0.0))
    store.record(_ann(relationship=sa.SAME_IDENTITY, confidence=0.9))
    assert sa.eligible(store.get(IDENTITY, "usda:1"))


# ── provenance survives a round trip ───────────────────────────────────────

def test_an_annotation_round_trips_with_its_whole_provenance():
    original = _ann(resolver_model="claude-sonnet-5", resolver_version="v3",
                    source_fingerprint="sha256:abc", created_at="2026-08-11",
                    review_status="unreviewed")
    back = sa.Annotation.from_payload(original.to_payload())
    assert back == original
    assert back.semantic_policy_version == sa.SEMANTIC_POLICY_VERSION


def test_the_policy_version_is_part_of_the_record():
    """A policy change must be a visible re-annotation rather than silent
    drift, so the version travels with every judgement."""
    assert _ann().semantic_policy_version == sa.SEMANTIC_POLICY_VERSION
    assert sa.SEMANTIC_POLICY_VERSION


# ── the fingerprint: a judgement is ABOUT a specific source row ────────────

def test_a_changed_source_row_needs_re_annotation():
    """The stored verdict describes content that no longer exists. Reusing it
    would answer a question nobody asked."""
    store = sa.Store()
    store.record(_ann(source_fingerprint="sha256:aaa"))
    assert not store.needs_resolution(IDENTITY, "usda:1", "sha256:aaa")
    assert store.needs_resolution(IDENTITY, "usda:1", "sha256:bbb")
    assert store.stale_source(IDENTITY, "usda:1", "sha256:bbb")


def test_an_unchanged_source_row_is_never_re_annotated():
    store = sa.Store()
    store.record(_ann(source_fingerprint="sha256:aaa"))
    for _ in range(20):
        assert not store.needs_resolution(IDENTITY, "usda:1", "sha256:aaa")


def test_a_missing_fingerprint_does_not_force_re_annotation():
    """Silence about the source is not evidence the source changed —
    the same invariant, one layer down."""
    store = sa.Store()
    store.record(_ann(source_fingerprint=""))
    assert not store.needs_resolution(IDENTITY, "usda:1", "sha256:new")
    assert not store.stale_source(IDENTITY, "usda:1", "sha256:new")


def test_replacing_a_stale_annotation_still_requires_the_stated_cause():
    """Detecting staleness does not by itself authorize a rewrite — the cause
    must be recorded so the change is attributable."""
    store = sa.Store()
    store.record(_ann(source_fingerprint="sha256:aaa"))
    with pytest.raises(sa.AnnotationReplacementRefused):
        store.record(_ann(source_fingerprint="sha256:bbb"))
    store.record(_ann(source_fingerprint="sha256:bbb"),
                 cause=sa.SOURCE_CHANGED)
    assert store.get(IDENTITY, "usda:1").source_fingerprint == "sha256:bbb"


# ── GATE 0.4.7 — turn-time pricing stays model-free ────────────────────────

def test_turn_time_pricing_remains_synchronous_and_model_free():
    """Re-asserted HERE, not only in the pricing suite. 0.4 changes what
    BUILD time may trust; it must not quietly open a door at TURN time."""
    import ast
    import asyncio
    import inspect
    import textwrap

    from core.canonical_pricing import price

    assert not asyncio.iscoroutinefunction(price)
    tree = ast.parse(textwrap.dedent(inspect.getsource(price)))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Await)], (
        "price() can await — a provider or model call can hide on the settle "
        "path")


def test_the_pricer_never_imports_the_annotation_layer():
    """Annotations are a BUILD-time artifact. If turn-time pricing could read
    them it could also refresh them, and the settle path would acquire a
    reason to talk to a model."""
    import ast
    import pathlib

    src = (pathlib.Path(__file__).resolve().parent.parent
           / "core" / "canonical_pricing.py").read_text("utf-8")
    modules = {n.module for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.ImportFrom) and n.module}
    assert not any("semantic_annotations" in m for m in modules)


# ── GATE 0.4.10 — the semantic boundary still holds ───────────────────────

def test_a_judged_negative_keeps_the_bad_fuzzy_winners_out():
    """MEASURED: with mechanical eligibility alone, fuzzy ranking picks
    `Fish oil, salmon` (902 kcal) for "salmon", `Chicken spread` for
    "chicken", and a babyfood for "papaya". A stored DIFFERENT_IDENTITY is
    what keeps them out — and it does so without any model call."""
    store = sa.Store()
    for evidence_id, relationship in (
            ("usda:fish_oil", sa.DIFFERENT_IDENTITY),
            ("usda:chicken_spread", sa.DIFFERENT_IDENTITY),
            ("usda:babyfood", sa.DIFFERENT_IDENTITY),
            ("usda:salmon_chinook_raw", sa.COMPATIBLE_SPECIALIZATION)):
        store.record(sa.Annotation(identity_key="salmon|",
                                   evidence_id=evidence_id,
                                   relationship=relationship, confidence=0.95))
    priced = [e for e in ("usda:fish_oil", "usda:chicken_spread",
                          "usda:babyfood", "usda:salmon_chinook_raw")
              if sa.eligible(store.get("salmon|", e))]
    assert priced == ["usda:salmon_chinook_raw"]


def test_those_negatives_survive_a_resolver_outage():
    """The exclusions are DATA. They do not weaken when the model is
    unreachable — which is the whole difference from a live gate."""
    store = sa.Store()
    store.record(sa.Annotation(identity_key="salmon|",
                               evidence_id="usda:fish_oil",
                               relationship=sa.DIFFERENT_IDENTITY,
                               confidence=0.95))
    assert not store.needs_resolution("salmon|", "usda:fish_oil")
    assert not sa.eligible(store.get("salmon|", "usda:fish_oil"))


# ── ⭐ COLD-START HONESTY — what this architecture does NOT claim ──────────
#
# The danger this gate exists to prevent is a FUTURE STATUS DOCUMENT, not a
# code regression. "Reproducible from frozen semantic inputs" is a true and
# valuable claim. "Deterministic from raw USDA evidence alone" is a different
# claim, it is FALSE, and the two are one careless sentence apart.
#
# The model has no determinism knob (`temperature` -> 400 deprecated). First
# resolutions CAN vary. The architecture does not make the model deterministic;
# it converts a stochastic per-build authority into an explicit versioned INPUT
# that is created once and thereafter reproduced exactly.
#
# So these gates deliberately do NOT assert that first annotations are equal.
# They assert that the SYSTEM tells the truth about which regime it is in.

def test_a_cold_start_is_creation_not_reproduction():
    """An empty store must report that every pair needs resolution. Anything
    else would be claiming knowledge it does not have."""
    store = sa.Store()
    assert store.needs_resolution(IDENTITY, "usda:1")
    assert store.needs_resolution(IDENTITY, "usda:2")
    assert sa.disposition(store.get(IDENTITY, "usda:1")) \
        == "unresolved_never_annotated"


def test_first_resolutions_are_permitted_to_disagree():
    """⭐ THE HONESTY GATE. Two cold starts may legitimately produce different
    judgements — that is a property of the MODEL, which this architecture does
    not and cannot fix. What it fixes is that the disagreement happens ONCE,
    is recorded, and is never silently re-rolled afterwards.

    Asserting equality here would be asserting something false about the
    world, and a green test making a false claim is worse than no test.
    """
    cold_a, cold_b = sa.Store(), sa.Store()
    cold_a.record(_ann(relationship=sa.SAME_IDENTITY, confidence=0.9))
    cold_b.record(_ann(relationship=sa.DIFFERENT_IDENTITY, confidence=0.9))

    # They disagree, and the architecture does NOT prevent that.
    assert (cold_a.get(IDENTITY, "usda:1").relationship
            != cold_b.get(IDENTITY, "usda:1").relationship)

    # What it guarantees is that each is now STABLE and needs no further call.
    for store in (cold_a, cold_b):
        assert not store.needs_resolution(IDENTITY, "usda:1")


def test_a_populated_baseline_reproduces_exactly():
    """The claim that IS true: given the same frozen annotations, repeated
    reads produce the same eligibility every time, with no resolver."""
    store = sa.Store()
    store.record(_ann(relationship=sa.SAME_IDENTITY, confidence=0.9,
                      source_fingerprint="sha256:aaa"))
    outcomes = {(sa.eligible(store.get(IDENTITY, "usda:1")),
                 sa.disposition(store.get(IDENTITY, "usda:1")),
                 store.needs_resolution(IDENTITY, "usda:1", "sha256:aaa"))
                for _ in range(50)}
    assert outcomes == {(True, "priceable", False)}


def test_the_two_regimes_are_distinguishable_from_the_build_itself():
    """A build must be able to SAY which regime it ran in. `resolved_this_build`
    empty means every judgement was reproduced; non-empty means new semantic
    data was CREATED and the run is not a reproduction proof."""
    store = sa.Store()
    store.record(_ann())
    assert store.resolved_this_build == [], (
        "recording a pre-existing annotation must not look like resolution")

    store.resolved_this_build.append((IDENTITY, "usda:new"))
    assert store.resolved_this_build, (
        "a build that resolved new evidence must be unable to present itself "
        "as a pure reproduction")


# ── ⭐ PHASE 1.5 — BASELINE ADMISSION ──────────────────────────────────────
#
# Phase 1 proved reproducibility and exposed a different gap: raw generation
# was BEHIND the committed artifact (mackerel|roasted raw=1, final=4) and
# retention was covering it. Admission converts that hidden repair into
# explicit reviewed data.
#
# The rule both halves of the review must obey:
#     production presence   != automatic semantic admission
#     cold-start appearance != automatic semantic admission

def test_the_migration_cause_is_unavailable_to_ordinary_rebuilds():
    """`baseline_migration` would otherwise become the universal escape hatch
    — a cause meaning "because I said so", available forever."""
    store = sa.Store()
    store.record(_ann())
    sa.close_baseline_migration()
    with pytest.raises(sa.AnnotationReplacementRefused):
        store.record(_ann(relationship=sa.DIFFERENT_IDENTITY),
                     cause=sa.BASELINE_MIGRATION)


def test_the_migration_cause_works_only_while_the_migration_is_open():
    store = sa.Store()
    store.record(_ann())
    sa.open_baseline_migration()
    try:
        store.record(_ann(relationship=sa.DIFFERENT_IDENTITY),
                     cause=sa.BASELINE_MIGRATION)
        assert store.get(IDENTITY, "usda:1").relationship \
            == sa.DIFFERENT_IDENTITY
    finally:
        sa.close_baseline_migration()
    with pytest.raises(sa.AnnotationReplacementRefused):
        store.record(_ann(), cause=sa.BASELINE_MIGRATION)


def test_baseline_migration_is_not_in_the_ordinary_cause_vocabulary():
    assert sa.BASELINE_MIGRATION not in sa.INVALIDATION_CAUSES


def test_a_row_in_production_still_requires_review():
    """Presence in today's artifact does not prove what relationship should be
    recorded. Reconstructing annotations from historical membership would
    launder past behaviour into new semantic truth."""
    from scripts import baseline_admission as ba

    rows = ba.discovery_report(cold_runs=[], committed={IDENTITY: {"usda:1"}})
    assert len(rows) == 1
    assert rows[0]["production_present"] is True
    assert rows[0]["times_seen"] == 0
    assert rows[0]["review_required"] is True


def test_a_row_seen_in_every_cold_run_but_not_in_production_needs_review():
    """A union of stochastic runs trends toward 'everything the model ever
    thought might match'. Discovery proposes; it does not admit."""
    from scripts import baseline_admission as ba

    runs = [{IDENTITY: {"usda:new": sa.SAME_IDENTITY}} for _ in range(10)]
    rows = ba.discovery_report(cold_runs=runs, committed={IDENTITY: set()})
    assert rows[0]["production_present"] is False
    assert rows[0]["times_seen"] == 10
    assert rows[0]["review_required"] is True


def test_only_full_agreement_between_production_and_every_run_is_stable():
    from scripts import baseline_admission as ba

    runs = [{IDENTITY: {"usda:1": sa.SAME_IDENTITY}} for _ in range(10)]
    stable = ba.discovery_report(runs, {IDENTITY: {"usda:1"}})[0]
    assert stable["review_required"] is False

    mixed = [{IDENTITY: {"usda:1": sa.SAME_IDENTITY}} for _ in range(9)]
    mixed.append({IDENTITY: {"usda:1": sa.DIFFERENT_IDENTITY}})
    unstable = ba.discovery_report(mixed, {IDENTITY: {"usda:1"}})[0]
    assert unstable["review_required"] is True
    assert len(unstable["relationships"]) == 2


# ── ⭐⭐ THE COVERAGE FLOOR ────────────────────────────────────────────────

def test_a_proposed_baseline_may_not_silently_drop_a_production_candidate():
    """THE PHASE 1 GAP, as a rule. `mackerel|roasted` generated 1 candidate
    where production prices 4; retention hid it. Only a reviewed REJECT or a
    mechanical veto may reduce the floor."""
    from scripts import baseline_admission as ba

    committed = {IDENTITY: {"usda:1", "usda:2", "usda:3", "usda:4"}}
    proposed = {IDENTITY: {"usda:1"}}
    violations = ba.coverage_floor_violations(committed, proposed,
                                              dispositions={})
    assert {v["evidence_id"] for v in violations} == {"usda:2", "usda:3",
                                                     "usda:4"}


def test_a_reviewed_rejection_may_reduce_the_floor():
    from scripts import baseline_admission as ba

    committed = {IDENTITY: {"usda:1", "usda:2"}}
    proposed = {IDENTITY: {"usda:1"}}
    reviewed = {IDENTITY: {"usda:2": ba.REJECT}}
    assert ba.coverage_floor_violations(committed, proposed, reviewed) == []


def test_an_unresolved_disposition_does_not_license_a_drop():
    """UNRESOLVED means nobody decided. It is not permission."""
    from scripts import baseline_admission as ba

    committed = {IDENTITY: {"usda:1", "usda:2"}}
    proposed = {IDENTITY: {"usda:1"}}
    for weak in (ba.UNRESOLVED, ba.ADMIT, None):
        reviewed = {IDENTITY: {"usda:2": weak}}
        assert len(ba.coverage_floor_violations(committed, proposed,
                                                reviewed)) == 1


# ── ⭐ THE CONSEQUENCE FRONTIER — why an unreviewed row may stay unreviewed ─
#
# 683 rows were excluded by MODEL CONSENSUS ALONE (measured: 69% of a sample
# had no mechanical veto). Ten unanimous DIFFERENT_IDENTITY votes must not
# amount to a rejection, or "discovery only, never authority" is false.
#
# So they are persisted as UNDECIDED, and may remain so only while
# deterministic analysis proves they cannot influence pricing.

def _rank(identity, candidates):
    from core.food_intelligence import best_candidate

    entity, _, prep = identity.partition("|")
    return best_candidate(f"{entity}, {prep}" if prep else entity,
                          list(candidates))


_STRONG = [{"fdc_id": 1, "description": "Fish, salmon, chinook, raw",
            "per100g": {"calories": 179.0}},
           {"fdc_id": 2, "description": "Fish, salmon, chum, raw",
            "per100g": {"calories": 120.0}}]

#: These gates all concern a COVERED identity. Stating that explicitly is not
#: boilerplate — omitting it makes `consequential` fail closed on unknown
#: coverage, which is correct behaviour and would make the gates assert the
#: wrong thing for the right reason.
_COVERED = {"salmon|": _STRONG}


def _row(fdc_id, description, kcal):
    return {"identity_key": "salmon|", "evidence_id": f"usda:{fdc_id}",
            "record": {"fdc_id": fdc_id, "description": description,
                       "per100g": {"calories": kcal}}}


def test_a_row_that_cannot_affect_the_outcome_may_stay_unreviewed():
    from scripts import baseline_admission as ba

    for fdc_id, desc, kcal in ((9, "Babyfood, fruit, guava with tapioca", 63.0),
                               (8, "Bologna, chicken, pork", 336.0)):
        hit, why = ba.consequential(_row(fdc_id, desc, kcal), _STRONG, _rank,
                                    coverage=_COVERED)
        assert hit is False
        assert why == "cannot_affect_outcome_within_the_frontier"


def test_a_row_that_would_take_the_winner_must_be_reviewed():
    """`Fish oil, salmon` at 902 kcal WINS the fuzzy ranker for "salmon". Its
    suppression is currently load-bearing, so it is exactly the row a
    consensus must not be allowed to settle silently."""
    from scripts import baseline_admission as ba

    hit, why = ba.consequential(_row(7, "Fish oil, salmon", 902.0),
                                _STRONG, _rank, coverage=_COVERED)
    assert hit is True
    assert why == "admitting_it_changes_the_winner_now"


def test_a_row_with_no_competition_would_price_alone_and_must_be_reviewed():
    from scripts import baseline_admission as ba

    # COVERED identity whose candidate list is genuinely empty here — not the
    # uncovered case, which returns OUT_OF_SCOPE before this arm is reached.
    hit, why = ba.consequential(_row(9, "Babyfood, guava", 63.0), [], _rank,
                                coverage={"salmon|": [{"fdc_id": 99}]})
    assert hit is True


def test_an_unevaluable_row_fails_closed_into_review():
    """⭐ THE INVARIANT, one level down. We cannot evaluate it, so we do not
    get to assume it is harmless. Unknown is not 'fine'."""
    from scripts import baseline_admission as ba

    hit, why = ba.consequential(
        {"identity_key": "salmon|", "evidence_id": "usda:9"}, _STRONG, _rank,
        coverage=_COVERED)
    assert hit is True
    assert why == "unevaluable_row_fails_closed"


def test_the_future_risk_arm_exists_and_is_versioned():
    """A row harmless ONLY because a stronger candidate exists today is not
    forever harmless. Depth is a versioned policy constant, not a guess."""
    from scripts import baseline_admission as ba

    assert isinstance(ba.CONSEQUENCE_DEPTH, int)
    assert ba.CONSEQUENCE_DEPTH >= 1

    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(ba.consequential))
    assert "would_win_after_" in src, (
        "the leave-one-out future-risk arm is gone — a row would then be "
        "judged harmless purely on today's candidate set")
    # And no kcal-distance proxy crept back in as a threshold.
    tree = ast.parse(src)
    numbers = {n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
               and not isinstance(n.value, bool)}
    assert not (numbers - {0, 1}), (
        f"magic thresholds {numbers - {0, 1}} in the frontier — the whole "
        f"point of leave-one-out is that it models drift instead of guessing "
        f"a calorie band")


def test_an_unreviewed_negative_is_not_a_rejection():
    """The class exists precisely so consensus cannot masquerade as a
    decision."""
    from scripts import baseline_admission as ba

    assert ba.UNREVIEWED_NEGATIVE != ba.REJECT
    assert ba.UNREVIEWED_NEGATIVE in ba.EXCLUSION_CLASSES
    row = {"identity_key": "i", "evidence_id": "e",
           "mechanically_vetoed": False, "relationships": {"DIFFERENT_IDENTITY": 10}}
    assert ba.exclusion_class(row) == ba.UNREVIEWED_NEGATIVE


def test_the_report_no_longer_calls_the_whole_population_review_required():
    """950 = 232 mechanical + 683 unreviewed + 35 queue. Calling all of it
    "review required" while also reporting a 35-pair queue was a contradiction
    the next reader would have had to untangle."""
    from scripts import baseline_admission as ba

    runs = [{"salmon|": {"usda:1": sa.SAME_IDENTITY,
                         "usda:2": sa.DIFFERENT_IDENTITY}} for _ in range(10)]
    rows = ba.discovery_report(runs, {"salmon|": {"usda:1"}})
    s = ba.summarise(rows)
    assert "non_production_discovery" in s
    assert s["review_required"] <= s["non_production_discovery"]


# ── ⭐ IDENTITY STATE IS EVALUATED BEFORE ROW CONSEQUENCE ──────────────────
#
# The first frontier conflated "this identity has NO coverage" with "this
# identity has ONE candidate that would become decisive". Those are opposite
# states, and treating them alike escalated 572 rows of noise: `asparagus|fried`
# has no artifact entry, so every row under it reported "would price alone"
# about an identity that prices nothing. 586 escalations -> 42 once the states
# were separated, with the 14 future-risk rows surviving intact.

_OIL = {"fdc_id": 7, "description": "Fish oil, salmon",
        "per100g": {"calories": 902.0}}
_COVERAGE = {"salmon|": [{"fdc_id": 1,
                          "description": "Fish, salmon, chinook, raw",
                          "per100g": {"calories": 179.0}}]}


def test_a_row_under_an_uncovered_identity_is_out_of_scope():
    """It cannot change a price that does not exist."""
    from scripts import baseline_admission as ba

    row = {"identity_key": "asparagus|fried", "evidence_id": "usda:7",
           "record": _OIL}
    hit, why = ba.consequential(row, [], _rank, coverage=_COVERAGE)
    assert hit is False
    assert why == ba.OUT_OF_SCOPE


def test_the_same_row_under_a_covered_identity_is_consequential():
    """Identical row, identical evidence — only the identity's coverage
    differs, and that is what decides."""
    from scripts import baseline_admission as ba

    row = {"identity_key": "salmon|", "evidence_id": "usda:7", "record": _OIL}
    hit, why = ba.consequential(row, _COVERAGE["salmon|"], _rank,
                                coverage=_COVERAGE)
    assert hit is True
    assert why == "admitting_it_changes_the_winner_now"


def test_unknown_coverage_fails_closed():
    from scripts import baseline_admission as ba

    row = {"identity_key": "salmon|", "evidence_id": "usda:7", "record": _OIL}
    hit, why = ba.consequential(row, [], _rank, coverage=None)
    assert hit is True
    assert why == "unknown_identity_coverage_fails_closed"


def test_out_of_scope_is_not_harmless_forever():
    """⭐ THE GUARD THAT MAKES THE 544 DEFENSIBLE. An out-of-scope verdict
    records the PREMISE it rests on, so when the premise stops holding the
    verdict is recomputed rather than inherited."""
    from scripts import baseline_admission as ba

    rows = [{"identity_key": "asparagus|fried", "evidence_id": "usda:7",
             "record": _OIL, "relationships": {"DIFFERENT_IDENTITY": 10},
             "production_present": False, "times_seen": 10,
             "mechanically_vetoed": False}]
    stay, escalate = ba.frontier_report(rows, _COVERAGE, _rank)
    assert len(stay) == 1 and not escalate
    assert stay[0]["coverage_state"] == ba.UNCOVERED
    assert stay[0]["revalidate_on"] == ba.COVERAGE_GAINED


def test_an_inert_and_an_out_of_scope_row_carry_DIFFERENT_triggers():
    """⚠ THIS GATE PREVIOUSLY ASSERTED THE DEFECT.

    It read `test_an_evaluated_inert_row_carries_no_revalidation_trigger` and
    required inert rows to carry NO trigger — enshrining the exact gap review
    later found: an inert verdict was judged against TODAY'S candidate set and
    would have been inherited forever. It passed happily, because a gate that
    asserts the current behaviour is correct proves only that the behaviour is
    current.

    The claim that matters is that the two premises are DISTINCT and both
    recorded: out-of-scope rests on the identity pricing nothing; inert rests
    on the candidate set it was judged against.
    """
    from scripts import baseline_admission as ba

    out_of_scope = {"identity_key": "asparagus|fried", "evidence_id": "usda:7",
                    "record": _OIL, "relationships": {"DIFFERENT_IDENTITY": 10},
                    "production_present": False, "times_seen": 10,
                    "mechanically_vetoed": False}
    inert = {"identity_key": "salmon|", "evidence_id": "usda:9",
             "record": {"fdc_id": 9, "description": "Bologna, chicken, pork",
                        "per100g": {"calories": 336.0}},
             "relationships": {"DIFFERENT_IDENTITY": 10},
             "production_present": False, "times_seen": 10,
             "mechanically_vetoed": False}
    stay, escalate = ba.frontier_report([out_of_scope, inert], _COVERAGE, _rank)
    assert not escalate and len(stay) == 2

    by_identity = {r["identity_key"]: r for r in stay}
    assert by_identity["asparagus|fried"]["coverage_state"] == ba.UNCOVERED
    assert by_identity["asparagus|fried"]["revalidate_on"] == ba.COVERAGE_GAINED
    assert by_identity["asparagus|fried"]["judged_against"] == "", (
        "an out-of-scope verdict is not premised on a candidate set")

    assert by_identity["salmon|"]["coverage_state"] == ba.COVERED
    assert by_identity["salmon|"]["revalidate_on"] == ba.CANDIDATE_SET_CHANGED
    assert by_identity["salmon|"]["judged_against"]

    assert (by_identity["asparagus|fried"]["revalidate_on"]
            != by_identity["salmon|"]["revalidate_on"]), (
        "collapsing the two triggers would lose WHY a verdict must be "
        "recomputed")


def test_gaining_coverage_invalidates_exactly_the_identities_that_gained_it():
    from scripts import baseline_admission as ba

    before = {"a|": [], "b|": [{"fdc_id": 1}], "c|": [{"fdc_id": 2}]}
    after = {"a|": [{"fdc_id": 9}], "b|": [{"fdc_id": 1}], "c|": []}
    assert ba.coverage_change_invalidates(before, after) == ("a|",)


def test_an_identity_absent_from_the_artifact_counts_as_uncovered():
    """The artifact holds only material identities, so absence IS knowable —
    it is not the same as unknown coverage."""
    from scripts import baseline_admission as ba

    assert ba.identity_state("never|seen", _COVERAGE) == ba.UNCOVERED
    assert ba.identity_state("salmon|", _COVERAGE) == ba.COVERED
    assert ba.identity_state("salmon|", None) == ba.UNKNOWN_COVERAGE


# ── ⭐ EVERY STAY-UNREVIEWED VERDICT RECORDS ITS PREMISE ───────────────────
#
# GAP FOUND IN REVIEW. Only out-of-scope rows carried a revalidation trigger.
# The 97 "evaluated inert" rows were judged against TODAY'S candidate set — if
# one candidate disappears, is replaced, re-ranks or becomes mechanically
# vetoed, an inert row turns consequential WITHOUT the identity ever going
# uncovered -> covered. Coverage gain is a SPECIAL CASE of candidate-set
# change, not the general one.

def test_an_inert_verdict_is_revalidated_on_any_candidate_set_change():
    from scripts import baseline_admission as ba

    rows = [{"identity_key": "salmon|", "evidence_id": "usda:9",
             "record": {"fdc_id": 9, "description": "Bologna, chicken, pork",
                        "per100g": {"calories": 336.0}},
             "relationships": {"DIFFERENT_IDENTITY": 10},
             "production_present": False, "times_seen": 10,
             "mechanically_vetoed": False}]
    stay, escalate = ba.frontier_report(rows, _COVERAGE, _rank)
    assert not escalate
    assert stay[0]["revalidate_on"] == ba.CANDIDATE_SET_CHANGED
    assert stay[0]["judged_against"], (
        "an inert verdict with no recorded candidate set cannot be checked "
        "against a later one — the premise would be remembered, not stored")


def test_the_fingerprint_notices_a_reorder_not_only_a_removal():
    """A re-rank with identical membership can change the winner. A
    membership-only fingerprint would call that 'unchanged'."""
    from scripts import baseline_admission as ba

    a = [{"fdc_id": 1}, {"fdc_id": 2}]
    assert ba.candidate_set_fingerprint(a) == \
        ba.candidate_set_fingerprint([{"fdc_id": 1}, {"fdc_id": 2}])
    assert ba.candidate_set_fingerprint(a) != \
        ba.candidate_set_fingerprint([{"fdc_id": 2}, {"fdc_id": 1}])
    assert ba.candidate_set_fingerprint(a) != \
        ba.candidate_set_fingerprint([{"fdc_id": 1}])


def test_coverage_gain_and_set_change_are_reported_distinctly():
    """Different premises, different triggers. Collapsing them would lose the
    reason a verdict must be recomputed."""
    from scripts import baseline_admission as ba

    triggers = ba.revalidation_triggers(
        {"a|": [], "b|": [{"fdc_id": 1}, {"fdc_id": 2}], "c|": [{"fdc_id": 3}]},
        {"a|": [{"fdc_id": 9}], "b|": [{"fdc_id": 1}], "c|": [{"fdc_id": 3}]})
    assert triggers["a|"] == ba.COVERAGE_GAINED
    assert triggers["b|"] == ba.CANDIDATE_SET_CHANGED
    assert "c|" not in triggers


def test_no_stay_unreviewed_verdict_lacks_a_trigger():
    """The whole guard fails if any verdict can be inherited unconditionally."""
    from scripts import baseline_admission as ba

    rows = [
        {"identity_key": "asparagus|fried", "evidence_id": "usda:7",
         "record": _OIL, "relationships": {"DIFFERENT_IDENTITY": 10},
         "production_present": False, "times_seen": 10,
         "mechanically_vetoed": False},
        {"identity_key": "salmon|", "evidence_id": "usda:9",
         "record": {"fdc_id": 9, "description": "Bologna, chicken, pork",
                    "per100g": {"calories": 336.0}},
         "relationships": {"DIFFERENT_IDENTITY": 10},
         "production_present": False, "times_seen": 10,
         "mechanically_vetoed": False},
    ]
    stay, _ = ba.frontier_report(rows, _COVERAGE, _rank)
    assert len(stay) == 2
    assert all(r["revalidate_on"] for r in stay)
