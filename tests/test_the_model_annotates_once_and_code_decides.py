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
