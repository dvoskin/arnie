"""⛔ A REVIEWED PIN IS NOT THE SAFETY NET ACTING (2026-09-03, rebuild #8).

The raw-vs-final report diffed the raw generation snapshot against `entries`
AFTER `_apply_reviewed_pins` had rewritten it, and printed
"RETENTION ALTERED 5 existing key(s)" on a build where `_retain_unexplained`
printed no RETAINED line at all. The five were the pinned seeds. The tally that
exists to say "generation did NOT stand on its own" was being moved by a
person's deliberate hold — the weaker claim printed over the stronger truth.

Each key is charged to the mechanism that moved it: retention's delta is
measured on a snapshot taken BEFORE pins; pins and declines are counted from
their own docs; anything left over is named UNATTRIBUTED, never absorbed.
"""
from __future__ import annotations

import json


def _cand(n: str, desc: str = "") -> dict:
    return {"fdc_id": n, "evidence_id": f"usda:{n}", "description": desc}


def _pin(art, candidates, fp="sha256:reviewed00000000") -> dict:
    return {"resolver_version": art.resolver_version(),
            "retrieval_fingerprint": art.retrieval_fingerprint(),
            "expanded_candidate_fingerprint": fp, "reason": "TEST_HOLD",
            "candidates": candidates}


def _committed(tmp_path, monkeypatch, art, entries: dict) -> None:
    p = tmp_path / "artifact.json"
    p.write_text(json.dumps({"entries": entries}))
    monkeypatch.setattr(art, "ARTIFACT_PATH", p)


def test_a_pin_only_change_is_not_counted_as_a_retention_change(tmp_path, monkeypatch, capsys):
    """THE REBUILD #8 SHAPE. Generation expanded `oats|` to {1, 2}; the committed
    artifact holds {1}, so nothing is missing and retention has nothing to do;
    the reviewed pin then holds the seed on {1}."""
    import scripts.build_pricing_artifact as bp
    from skills.nutrition import pricing_artifact as art
    from skills.nutrition import semantic_annotations as sa

    _committed(tmp_path, monkeypatch, art, {"oats|": {"candidates": [_cand("1")]}})
    entries = {"oats|": {"candidates": [_cand("1", "Oats, cooked"), _cand("2", "Oats, dry")]}}
    raw = bp._candidate_ids(entries)

    assert bp._retain_unexplained(entries, sa.Store()) == 0
    after_retention = bp._candidate_ids(entries)
    by_key = {"oats|": {"candidate_fingerprint": "sha256:reviewed00000000"}}
    pinned = bp._apply_reviewed_pins(by_key, entries, {"oats|": _pin(art, [_cand("1")])})
    final = bp._candidate_ids(entries)
    assert raw["oats|"] == ["1", "2"] and final["oats|"] == ["1"], "the pin took"
    capsys.readouterr()

    report = bp._report_raw_vs_final(raw, after_retention, final, pinned, {})
    out = capsys.readouterr().out

    assert report["retention_changed"] == [] and report["retention_restored"] == []
    assert report["pinned"] == ["oats|"] and report["pinned_altered"] == ["oats|"]
    assert report["unattributed"] == []
    assert "RETENTION ALTERED   nothing — generation stood on its own" in out
    assert "PINNED (held on reviewed set) 1 key(s), 1 differ from generation: ['oats|']" in out
    assert "DECLINED            0 key(s)" in out
    # ⭐ THE OLD ARITHMETIC — raw against FINAL — does name the pinned key. That
    # is exactly the number rebuild #8 printed under the RETENTION label.
    assert [k for k in raw if raw[k] != final.get(k, [])] == ["oats|"]


def test_each_mechanism_is_charged_separately_when_all_three_act(tmp_path, monkeypatch, capsys):
    """Retention restores a lost row on `beef|` and a whole lost key `salmon|`;
    a pin holds `oats|`; `egg|roasted` was declined. Every key lands in exactly
    one bucket, and RETENTION ALTERED counts only retention's two."""
    import scripts.build_pricing_artifact as bp
    from skills.nutrition import pricing_artifact as art
    from skills.nutrition import semantic_annotations as sa

    _committed(tmp_path, monkeypatch, art, {
        "beef|": {"candidates": [_cand("10"), _cand("11")]},
        "salmon|": {"candidates": [_cand("20")]},
        "oats|": {"candidates": [_cand("1")]},
    })
    entries = {"beef|": {"candidates": [_cand("10")]},               # lost 11, unexplained
               "oats|": {"candidates": [_cand("1"), _cand("2")]}}    # salmon| lost whole
    raw = bp._candidate_ids(entries)
    assert bp._retain_unexplained(entries, sa.Store()) == 2
    after_retention = bp._candidate_ids(entries)
    pinned = bp._apply_reviewed_pins({"oats|": {"candidate_fingerprint": "sha256:reviewed00000000"}},
                                     entries, {"oats|": _pin(art, [_cand("1")])})
    declined = {"egg|roasted": {"reason": "IDENTITY_UNRESOLVED"}}
    capsys.readouterr()

    report = bp._report_raw_vs_final(raw, after_retention, bp._candidate_ids(entries),
                                     pinned, declined)
    out = capsys.readouterr().out

    assert report["retention_changed"] == ["beef|"]
    assert report["retention_restored"] == ["salmon|"]
    assert report["pinned"] == ["oats|"] == report["pinned_altered"]
    assert report["declined"] == ["egg|roasted"]
    assert report["unattributed"] == []
    assert "RAW GENERATION      2 identities" in out and "AFTER RETENTION     3 identities" in out
    assert "RETENTION ALTERED   1 existing key(s), restored 1 whole key(s): ['salmon|']" in out
    assert "  altered: ['beef|']" in out
    assert "PINNED (held on reviewed set) 1 key(s), 1 differ from generation: ['oats|']" in out
    assert "DECLINED            1 key(s): ['egg|roasted']" in out
    assert "UNATTRIBUTED" not in out


def test_a_move_no_mechanism_claims_is_named_not_absorbed(capsys):
    """⛔ THE NO-TRANSITION CASE FOR THE ATTRIBUTION ITSELF. If a future stage
    rewrites `entries` after retention without leaving a doc, the report must
    neither charge it to retention (the old defect) nor let it vanish."""
    import scripts.build_pricing_artifact as bp

    report = bp._report_raw_vs_final({"rice|": ["1"]}, {"rice|": ["1"]},
                                     {"rice|": ["1", "3"]}, {}, {})
    out = capsys.readouterr().out
    assert report["retention_changed"] == [] and report["pinned"] == []
    assert report["unattributed"] == ["rice|"]
    assert "RETENTION ALTERED   nothing" in out
    assert "UNATTRIBUTED        1 key(s) moved after retention" in out and "['rice|']" in out
