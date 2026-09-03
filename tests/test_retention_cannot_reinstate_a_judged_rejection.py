"""⛔⛔ A SAFETY NET THAT CANNOT TELL "lost" FROM "rejected" WILL REINSTATE
THE REJECTION.

`_retain_unexplained` carries forward committed candidates a rebuild lost. Its
docstring always said "unless something can attribute its removal" — and the
loop retained UNCONDITIONALLY. It nearly re-admitted the potato SKIN rows the
whole-vs-part rule had just learned to refuse: the correction would have been
silently undone by the mechanism meant to protect corrections.

Attribution is now read from the build's own annotations. This is the negative
case: a prior candidate this build JUDGED stays out; one it never reached stays
in.
"""
from __future__ import annotations

import json

import pytest


def _prior_artifact(tmp_path):
    doc = {"entries": {"potato|": {"candidates": [
        {"fdc_id": "1", "evidence_id": "usda:1", "description": "Potatoes, raw, skin"},
        {"fdc_id": "2", "evidence_id": "usda:2", "description": "Potatoes, boiled, flesh"},
    ]}}}
    p = tmp_path / "artifact.json"
    p.write_text(json.dumps(doc))
    return p


def test_a_judged_rejection_is_not_retained_but_an_unjudged_loss_is(tmp_path, monkeypatch):
    from scripts import build_pricing_artifact as B
    from skills.nutrition import pricing_artifact as art
    from skills.nutrition import semantic_annotations as sa

    monkeypatch.setattr(art, "ARTIFACT_PATH", _prior_artifact(tmp_path))

    # This build lost BOTH prior candidates — but it JUDGED one of them.
    store = sa.Store()
    store.record(sa.Annotation(identity_key="potato|", evidence_id="usda:1",
                               relationship=sa.DIFFERENT_IDENTITY, confidence=0.95,
                               resolver_model="test", source_fingerprint="sf"))
    entries = {"potato|": {"candidates": []}}

    retained = B._retain_unexplained(entries, store)

    ids = {c["evidence_id"] for c in entries["potato|"]["candidates"]}
    assert "usda:1" not in ids, (
        "the row this build JUDGED as a different identity came back — the "
        "net reinstated the very rejection it exists to protect")
    assert "usda:2" in ids, "the row this build never judged was NOT retained"
    assert retained == 1


def test_an_unresolved_judgement_does_not_count_as_attribution(tmp_path, monkeypatch):
    """UNRESOLVED means the judge did not answer. That is not an explanation,
    so the candidate is unexplained and must be retained."""
    from scripts import build_pricing_artifact as B
    from skills.nutrition import pricing_artifact as art
    from skills.nutrition import semantic_annotations as sa

    monkeypatch.setattr(art, "ARTIFACT_PATH", _prior_artifact(tmp_path))
    store = sa.Store()
    store.record(sa.Annotation(identity_key="potato|", evidence_id="usda:1",
                               relationship=sa.UNRESOLVED, confidence=0.0,
                               resolver_model="test", source_fingerprint="sf"))
    entries = {"potato|": {"candidates": []}}
    B._retain_unexplained(entries, store)
    ids = {c["evidence_id"] for c in entries["potato|"]["candidates"]}
    assert ids == {"usda:1", "usda:2"}


def test_without_a_store_nothing_is_attributable_and_everything_is_retained(tmp_path, monkeypatch):
    """The pre-fix behaviour, preserved for a caller that has no judgements —
    absence of a store means absence of attribution, not licence to drop."""
    from scripts import build_pricing_artifact as B
    from skills.nutrition import pricing_artifact as art
    monkeypatch.setattr(art, "ARTIFACT_PATH", _prior_artifact(tmp_path))
    entries = {"potato|": {"candidates": []}}
    assert B._retain_unexplained(entries, None) == 2


def test_a_signed_non_decision_is_attribution_and_is_not_retained(tmp_path, monkeypatch):
    """⛔ THE mayonnaise| CASE. A reviewer signed usda:173594 UNRESOLVED — read
    the record, judged the evidence insufficient, declined to rule. Retention
    read that as "nobody looked" and reinstated the row; it then WON the seed.
    A signed refusal is a decision; the loss is explained."""
    from skills.nutrition import pricing_artifact as art
    from skills.nutrition import semantic_annotations as sa
    import scripts.build_pricing_artifact as bp
    prior = tmp_path / "prior.json"
    prior.write_text(json.dumps({"entries": {"mayonnaise|": {"candidates": [
        {"fdc_id": "171009", "evidence_id": "usda:171009", "description": "Mayonnaise, regular"},
        {"fdc_id": "173594", "evidence_id": "usda:173594", "description": "Salad dressing, mayonnaise-like"}]}}}))
    monkeypatch.setattr(art, "ARTIFACT_PATH", prior)
    store = sa.Store.from_payload({"mayonnaise|␟usda:173594": {
        "identity_key": "mayonnaise|", "evidence_id": "usda:173594", "relationship": sa.UNRESOLVED,
        "confidence": 0.0, "review_status": sa.BASELINE_REVIEWED}})
    # ⚠ retention matches rows by fdc_id — a fixture without it matches nothing and proves nothing
    entries = {"mayonnaise|": {"candidates": [{"fdc_id": "171009", "evidence_id": "usda:171009", "description": "Mayonnaise, regular"}]}}
    bp._retain_unexplained(entries, store)
    assert [c["evidence_id"] for c in entries["mayonnaise|"]["candidates"]] == ["usda:171009"], \
        "a reviewer's refusal to rule must not be undone by retention"
