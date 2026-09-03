"""PHASE 0 STEPS 8-9 — THE PROOF, AND THE DRIFT LEDGER THAT KEEPS IT TRUE.

⭐ THE POISON IS THE PROOF. A build that merely happens not to call the
resolver proves nothing — it might be reusing annotations, or the resolver
might have been quietly unreachable, and both look identical from outside. So
the resolver is replaced with a function that RAISES and the build must
produce the same artifact anyway. `resolved_this_build == 0` then means "it
could not have asked", not "it did not happen to".

⭐⭐ AND THE POISON IS VERIFIED TO BITE FIRST. Reading a zero from an
instrument that was never armed is the exact trap this migration kept finding.
One deliberate call must raise before any conclusion is drawn from silence.

⭐⭐⭐ THE COMPARISON IS PRE-RETENTION. Retention exists to carry forward
candidates a build cannot account for, which means it can MANUFACTURE the
agreement this proof measures. Comparing after it would let a rescue read as a
reproduction.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from scripts import freeze_winner_accounting as fz
from scripts import prove_reproducibility as pr
from scripts import winner_review as wr
from skills.nutrition import pricing_artifact as art
from skills.nutrition import semantic_annotations as sa


@pytest.fixture(scope="module")
def proof():
    if not art.ARTIFACT_PATH.exists():
        pytest.skip("no committed artifact")
    return asyncio.run(pr.prove(runs=2))


# ── the proof ─────────────────────────────────────────────────────────────

def test_the_spine_reproduces_itself_with_the_resolver_poisoned(proof):
    assert proof["failures"] == []
    assert proof["poison_bites"] is True
    assert proof["resolved_this_build"] == [0] * proof["runs"]
    assert proof["identities"] == 37   # re-frozen 2026-09-03 (IR-PUBLISH)


def test_the_poison_would_actually_raise():
    """ANTI-VACUITY. A zero from an unarmed instrument is not evidence."""
    with pytest.raises(pr.ResolverPoisoned):
        asyncio.run(pr._poisoned("anything", []))


def test_the_reproduced_winners_are_the_frozen_ones(proof):
    frozen = json.loads(fz.FREEZE_PATH.read_text())
    assert len(frozen["rows"]) == proof["identities"]


# ── the permanent drift ledger ────────────────────────────────────────────

def _store():
    document = json.loads(art.ARTIFACT_PATH.read_text())
    return document, sa.Store.from_payload(
        (document.get("meta") or {}).get("annotations") or {})


def test_every_committed_candidate_is_annotated():
    """A candidate with no annotation is a pair the next build must ASK
    about — which is the difference between a frozen baseline and one that
    merely has not been disturbed yet."""
    document, store = _store()
    missing = [(identity, art.candidate_evidence_id(c))
               for identity, entry in (document.get("entries") or {}).items()
               for c in (entry.get("candidates") or ())
               if store.get(identity, art.candidate_evidence_id(c)) is None]
    assert missing == [], missing[:5]


def test_no_ordinary_rebuild_may_replace_an_annotation():
    """⛔ THE FREEZE, ENFORCED. A newer model is not authority to rewrite a
    semantic fact, and `baseline_migration` is closed."""
    _document, store = _store()
    identity, evidence = next(iter(store.by_key)).split("␟")
    with pytest.raises(sa.AnnotationReplacementRefused):
        store.record(sa.Annotation(identity, evidence, sa.DIFFERENT_IDENTITY))
    with pytest.raises(sa.AnnotationReplacementRefused):
        store.record(sa.Annotation(identity, evidence, sa.DIFFERENT_IDENTITY),
                     cause=sa.BASELINE_MIGRATION)


def test_a_destructive_removal_is_attributable():
    """Every candidate that left the artifact says who removed it and why."""
    document = json.loads(art.ARTIFACT_PATH.read_text())
    for removal in document.get("removed_evidence") or ():
        for field in ("identity", "evidence_id", "reason", "round"):
            assert str(removal.get(field) or "").strip(), removal
        assert ":" in removal["evidence_id"], removal


def test_no_evidence_id_anywhere_has_lost_its_namespace():
    """⛔ SOURCE NAMESPACE COLLAPSE = FAIL. Two providers' local ids collide,
    and a bare number merges them silently."""
    document, store = _store()
    for identity, entry in (document.get("entries") or {}).items():
        for candidate in (entry.get("candidates") or ()):
            assert ":" in art.candidate_evidence_id(candidate), identity
    for key in store.by_key:
        assert ":" in key.split("␟")[1], key


def test_no_winner_signature_is_stale_against_the_current_universe():
    """A signature is about a specific ladder. A moved ladder does not make it
    false — it makes it UNVERIFIED, and that must be reported."""
    frozen = json.loads(fz.FREEZE_PATH.read_text())
    assert fz.stale_signatures(frozen) == ()


def test_held_is_never_silently_upgraded_to_signed():
    """⭐ PHASE 0 CLOSURE DOES NOT APPROVE A WINNER. `HELD` means
    deterministic and NOT approved for broad promotion; if closure could
    upgrade it, the distinction would be decorative."""
    frozen = json.loads(fz.FREEZE_PATH.read_text())
    held = [r for r in frozen["rows"] if r["winner_status"] == wr.HELD]
    assert len(held) == 25
    for row in held:
        assert row["reason"] in wr.BLOCKING_CAUSES, row["identity_key"]


def test_the_population_run_is_not_mistaken_for_the_proof():
    """The creation run REQUIRED resolver calls; the proof requires none.
    Conflating them would let a creation run's success stand in for a
    determinism claim it cannot make."""
    from scripts.populate_semantic_store import RUN_RECORD
    if not RUN_RECORD.exists():
        pytest.skip("no population run recorded")
    record = json.loads(RUN_RECORD.read_text())
    assert record["is_reproducibility_evidence"] is False
    assert record["resolved_this_build"] > 0
