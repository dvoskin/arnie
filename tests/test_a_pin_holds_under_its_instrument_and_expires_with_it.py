"""⛔ THE PIN CONTRACT (2026-09-03). A reviewed pin holds a frozen-222 seed on its
v1 candidate set. It is bound to the INSTRUMENT — resolver_version + retrieval
fingerprint — because the reviewed conclusion does not depend on which extra
rows one expansion happened to retrieve: beef| and oats| populations moved
between two otherwise identical builds. A pin under another instrument must
NOT apply, and must say so; pool drift must NOT expire it; empty candidates
never pin."""
from __future__ import annotations

import pytest


@pytest.fixture
def bp():
    import scripts.build_pricing_artifact as bp
    from skills.nutrition import pricing_artifact as art
    return bp, art


def _pin(art, **over):
    base = {"resolver_version": art.resolver_version(),
            "retrieval_fingerprint": art.retrieval_fingerprint(),
            "expanded_candidate_fingerprint": "sha256:reviewed00000000",
            "reason": "TEST_HOLD",
            "candidates": [{"evidence_id": "usda:1", "description": "Egg, whole, cooked, omelet"}]}
    base.update(over)
    return base


def test_a_pin_under_the_same_instrument_holds_the_seed(bp, capsys):
    bp, art = bp
    entries = {"egg|": {"candidates": [{"evidence_id": "usda:9", "description": "Egg, whole, raw, fresh"}]}}
    by_key = {"egg|": {"candidate_fingerprint": "sha256:reviewed00000000"}}
    doc = bp._apply_reviewed_pins(by_key, entries, {"egg|": _pin(art)})
    assert [c["evidence_id"] for c in entries["egg|"]["candidates"]] == ["usda:1"]
    assert doc["egg|"]["pinned_evidence_ids"] == ["usda:1"]
    assert "PINNED egg|" in capsys.readouterr().out


def test_pool_drift_does_not_expire_a_pin_but_is_said(bp, capsys):
    bp, art = bp
    entries = {"egg|": {"candidates": [{"evidence_id": "usda:9"}]}}
    by_key = {"egg|": {"candidate_fingerprint": "sha256:drifted000000000"}}
    bp._apply_reviewed_pins(by_key, entries, {"egg|": _pin(art)})
    out = capsys.readouterr().out
    assert entries["egg|"]["candidates"][0]["evidence_id"] == "usda:1", "drift must not expire the hold"
    assert "PIN NOTE egg|" in out and "sha256:drifted000000000" in out


@pytest.mark.parametrize("over", [{"resolver_version": "food_evidence_semantics_v1"},
                                  {"retrieval_fingerprint": "sha256:otherinstrument0"}])
def test_a_pin_under_another_instrument_does_not_apply_and_says_so(bp, capsys, over):
    """⛔ THE NO-TRANSITION CASE. A new resolver may have FIXED the judgement the
    pin was holding against; silently carrying the hold would hide that."""
    bp, art = bp
    entries = {"egg|": {"candidates": [{"evidence_id": "usda:9"}]}}
    by_key = {"egg|": {"candidate_fingerprint": "sha256:reviewed00000000"}}
    doc = bp._apply_reviewed_pins(by_key, entries, {"egg|": _pin(art, **over)})
    assert entries["egg|"]["candidates"][0]["evidence_id"] == "usda:9", "published as built"
    assert doc == {}
    assert "PIN DOES NOT APPLY to egg|" in capsys.readouterr().out


def test_empty_candidates_never_pin(bp, capsys):
    bp, art = bp
    entries = {"egg|": {"candidates": [{"evidence_id": "usda:9"}]}}
    doc = bp._apply_reviewed_pins({"egg|": {}}, entries, {"egg|": _pin(art, candidates=[])})
    assert doc == {} and entries["egg|"]["candidates"][0]["evidence_id"] == "usda:9"
    assert "PIN DOES NOT APPLY" in capsys.readouterr().out
