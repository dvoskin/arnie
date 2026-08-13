"""THE FROZEN WINNER ACCOUNTING, AND WHAT WOULD MAKE IT A LIE.

27 rows, each binding identity · source-qualified evidence · SIGNED|HELD ·
reason · ranking_policy_version · candidate_universe_fingerprint.

⭐ THE FINGERPRINT IS WHAT LETS A SIGNATURE EXPIRE HONESTLY. A reviewer said
"this row is the representative one" while looking at a specific ladder. Add a
better candidate tomorrow and that sentence has not become FALSE — it has
become UNVERIFIED, which is a different state and the one this phase keeps
insisting on. Without the fingerprint the signature would silently survive the
field changing under it, which is a signature about nothing.
"""
from __future__ import annotations

import json

import pytest

from scripts import freeze_winner_accounting as fz
from scripts import winner_review as wr
from skills.nutrition.v2_gate import PHASE_0_REGIME


@pytest.fixture
def frozen():
    if not fz.FREEZE_PATH.exists():
        pytest.skip("winner accounting not frozen")
    return json.loads(fz.FREEZE_PATH.read_text())


def test_the_frozen_record_still_verifies(frozen):
    assert fz.verify(frozen) == ()


def test_the_counts_are_exactly_what_was_signed(frozen):
    rows = frozen["rows"]
    counts = {"signed": 0, "held": 0}
    for row in rows:
        counts[row["winner_status"]] += 1
    assert len(rows) == 27
    assert counts == {"signed": 13, "held": 14}


def test_every_row_binds_all_six_facts(frozen):
    for row in frozen["rows"]:
        for field in ("identity_key", "winner_evidence_id", "winner_status",
                      "reason", "ranking_policy_version",
                      "candidate_universe_fingerprint"):
            assert str(row.get(field) or "").strip(), (row["identity_key"], field)
        assert ":" in row["winner_evidence_id"]
        assert row["ranking_policy_version"] == PHASE_0_REGIME


def test_no_signature_is_stale_against_the_current_artifact(frozen):
    """⭐ THE EXPIRY CHECK. A moved candidate universe does not falsify a
    signature — it makes it unverified, and that must be REPORTED rather than
    absorbed by re-deriving agreement."""
    assert fz.stale_signatures(frozen) == ()


def test_a_moved_candidate_universe_is_detected(frozen):
    """ANTI-VACUITY: the expiry check must go red when the field moves."""
    mutated = {"regime": frozen["regime"],
               "rows": [dict(r) for r in frozen["rows"]]}
    mutated["rows"][0]["candidate_universe_fingerprint"] = "0" * 16
    stale = fz.stale_signatures(mutated)
    assert len(stale) == 1
    assert stale[0][0] == mutated["rows"][0]["identity_key"]


def test_the_freeze_refuses_a_regime_it_was_not_computed_under(frozen):
    mutated = {"regime": frozen["regime"],
               "rows": [dict(r) for r in frozen["rows"]]}
    mutated["rows"][0]["ranking_policy_version"] = "rank_v2+as_eaten"
    assert any("frozen under" in f for f in fz.verify(mutated))


def test_every_held_row_names_a_blocking_cause(frozen):
    held = [r for r in frozen["rows"] if r["winner_status"] == wr.HELD]
    assert len(held) == 14
    for row in held:
        assert row["reason"] in wr.BLOCKING_CAUSES, row["identity_key"]


def test_a_bare_evidence_id_fails_the_freeze(frozen):
    """A winner named by a provider-local number alone would merge two
    sources the moment a second one exists."""
    mutated = {"regime": frozen["regime"],
               "rows": [dict(r) for r in frozen["rows"]]}
    mutated["rows"][0]["winner_evidence_id"] = "170032"
    assert any("not source-qualified" in f for f in fz.verify(mutated))


def test_the_delta_from_the_earlier_counts_reconciles():
    """⭐ A COUNTS CHANGE IS WHERE A SEMANTIC DECISION GETS MISTAKEN FOR A
    BOOKKEEPING ONE. An earlier report read 15 SIGNED / 11 HELD over 26
    identities; the freeze reads 13 / 14 over 27. The movements are enumerated
    and the arithmetic is CHECKED, because a delta nobody can reconstruct is a
    delta that gets normalised."""
    assert fz.reconcile_delta() == ()
    assert fz.PRIOR == {"identities": 26, "signed": 15, "held": 11}
    assert len(fz.MOVEMENTS) == 5
    for identity, was, now, why in fz.MOVEMENTS:
        assert now in ("signed", "held")
        assert was in ("signed", "held", None)
        assert len(why) > 40, f"{identity}: the reason must actually explain"


def test_every_moved_identity_holds_the_state_the_delta_claims(frozen):
    """The narrative and the frozen record must agree row by row."""
    by_identity = {r["identity_key"]: r for r in frozen["rows"]}
    for identity, _was, now, _why in fz.MOVEMENTS:
        assert identity in by_identity, identity
        assert by_identity[identity]["winner_status"] == now, identity


def test_a_movement_that_does_not_add_up_is_caught():
    """ANTI-VACUITY: drop a movement and the arithmetic must go red."""
    original = fz.MOVEMENTS
    try:
        fz.MOVEMENTS = original[1:]
        assert any("imply" in f for f in fz.reconcile_delta())
    finally:
        fz.MOVEMENTS = original
