"""⛔⛔ EVERY REBUILD SINCE THE LAYOUT MOVED DROPPED 84 HUMAN DECISIONS. The
committed artifact keeps annotations under `meta.annotations`; the producer read
and wrote them at the top level; `loaded 0 existing semantic annotation(s)` was
true on every build and nobody noticed because a model re-rolled the answers.
A person's signed decision must survive an ordinary rebuild regardless of which
layout the file on disk uses."""
from __future__ import annotations

from skills.nutrition import semantic_annotations as sa


def _ann(rel, status="unreviewed"):
    return {"identity_key": "egg|", "evidence_id": "usda:172185", "relationship": rel,
            "confidence": 0.95, "review_status": status}


def test_the_legacy_meta_layout_is_read():
    import scripts.build_pricing_artifact as bp
    doc = {"meta": {"annotations": {"egg|␟usda:172185": _ann("COMPATIBLE_SPECIALIZATION", sa.BASELINE_REVIEWED)}}}
    assert bp._stored_annotations(doc)["egg|␟usda:172185"]["review_status"] == sa.BASELINE_REVIEWED


def test_the_top_level_layout_is_read():
    import scripts.build_pricing_artifact as bp
    doc = {"annotations": {"egg|␟usda:172185": _ann("DIFFERENT_IDENTITY")}}
    assert bp._stored_annotations(doc)["egg|␟usda:172185"]["relationship"] == "DIFFERENT_IDENTITY"


def test_a_signed_decision_outranks_a_model_row_for_the_same_pair():
    """The exact loss: a human ADMITTED omelet for `egg|`; a later model row
    (top level, unreviewed) said DIFFERENT_IDENTITY. The person wins."""
    import scripts.build_pricing_artifact as bp
    doc = {"meta": {"annotations": {"egg|␟usda:172185": _ann("COMPATIBLE_SPECIALIZATION", sa.BASELINE_REVIEWED)}},
           "annotations": {"egg|␟usda:172185": _ann("DIFFERENT_IDENTITY"),
                           "egg|␟usda:171287": _ann("SAME_IDENTITY")}}
    got = bp._stored_annotations(doc)
    assert got["egg|␟usda:172185"]["relationship"] == "COMPATIBLE_SPECIALIZATION"
    assert got["egg|␟usda:171287"]["relationship"] == "SAME_IDENTITY", "unsigned rows still merge"


def test_a_newer_signed_row_replaces_an_older_signed_row():
    import scripts.build_pricing_artifact as bp
    doc = {"meta": {"annotations": {"k": _ann("DIFFERENT_IDENTITY", sa.BASELINE_REVIEWED)}},
           "annotations": {"k": _ann("COMPATIBLE_SPECIALIZATION", sa.BASELINE_REVIEWED)}}
    assert bp._stored_annotations(doc)["k"]["relationship"] == "COMPATIBLE_SPECIALIZATION"


def test_the_committed_artifact_actually_carries_signed_rows():
    """Guards the premise: if HEAD's artifact ever stops carrying the human
    layer, this test — not a silent `loaded 0` — says so."""
    import json, subprocess
    import scripts.build_pricing_artifact as bp
    raw = subprocess.run(["git", "show", "HEAD:data/pricing_evidence_v1.json"], capture_output=True, text=True).stdout
    signed = [k for k, v in bp._stored_annotations(json.loads(raw)).items() if v.get("review_status") == sa.BASELINE_REVIEWED]
    assert len(signed) >= 80, len(signed)
    assert "mackerel|roasted␟usda:174236" in signed
