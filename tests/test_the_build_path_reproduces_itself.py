"""THE BUILD-PATH PROOF MUST BE RUNNABLE, AND IT MUST REPLAY BY QUERY.

⛔ WHY THIS FILE EXISTS AT ALL. `scripts/prove_build_reproducibility.py` was
written to answer a real gap — the earlier proof replays a frozen artifact and
never calls `build_one` — and then NOTHING IMPORTED IT. One commit later G1
started recording the capture at the retrieval seam, the file's schema changed
underneath the reader, and the script began handing `build_one` the literal
string `"meta"` as a food identity and dying on `'str' object has no attribute
'get'`. The suite stayed green the whole time, because a script with no
importer cannot fail.

That is the same shape this migration keeps cataloguing: the eligibility layer
with no production caller, the veto whose result was discarded, the `matched:
0` read from an instrument that was never armed. THE CHECK EXISTED AND DID NOT
FIRE. So this file's first duty is the unglamorous one — to INVOKE the thing.

⭐ AND IT DELIBERATELY DOES NOT ASSERT THAT THE PROOF PASSES. It does not,
today: the semantic store was populated over the committed artifact's
candidates, not over the retrieval population the real build sees, so hundreds
of pairs would still have to ask the resolver. That is a true statement about
the current state and it belongs in the directive as owed work — not papered
over here with a green test, and not frozen here as an expected failure count
that would turn a fix into a red build.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from scripts import build_pricing_artifact as bp
from scripts import capture_retrieval as cr
from scripts import prove_build_reproducibility as pbr
from skills.nutrition import pricing_artifact as art


@pytest.fixture
def capture():
    if not pbr.CAPTURE_PATH.exists():
        pytest.skip("no source capture")
    return json.loads(pbr.CAPTURE_PATH.read_text())


# ── the anti-rot gate ─────────────────────────────────────────────────────

def test_the_proof_actually_runs(capture):
    """⭐ THE GATE THE LAST BREAK NEEDED. Not "is the function correct" but
    "does anything CALL it" — the distinction that let 23 passing gates sit on
    top of a module with no importer."""
    result = asyncio.run(pbr.prove(runs=2))

    assert result["poison_bites"] is True, (
        "the poison must raise before its silence proves anything")
    assert result["identities"] == len(capture["queries"])
    assert result["fingerprint"]
    assert result["capture"] == "seam_recording"
    assert result["capture_fingerprint"] == art.retrieval_fingerprint()


def test_the_build_is_deterministic_over_fixed_inputs():
    """The claim this script exists to make, and it holds today even though
    store coverage does not: identical captured inputs, identical build."""
    result = asyncio.run(pbr.prove(runs=3))
    assert not [f for f in result["failures"] if "differs at" in f]
    assert result["resolved_this_build"] == [0, 0, 0], (
        "a poisoned build must never RECORD a resolution")


# ── the schema seam that actually broke ───────────────────────────────────

def test_the_proof_reads_the_capture_that_capture_retrieval_writes():
    """⛔ ONE CONSTANT, NOT TWO. The break was two `CAPTURE_PATH` definitions
    pointing at one file with two different schemas."""
    assert pbr.CAPTURE_PATH == cr.CAPTURE_PATH


def test_the_capture_keys_are_identities_and_not_envelope_fields(capture):
    """The exact regression: `sorted(capture)` yielded `['meta', 'queries']`,
    so the build was asked to price a food called "meta"."""
    assert set(capture) >= {"meta", "queries"}
    for identity in capture["queries"]:
        assert "|" in identity, identity
    assert "meta" not in capture["queries"]


def test_a_missing_capture_is_refused_and_never_invented(tmp_path, monkeypatch):
    """⛔ THE PROOF MUST NOT MANUFACTURE ITS OWN INPUTS. It used to synthesise
    a corpus from the committed artifact and WRITE IT to the authoritative
    capture path — so the one artifact G1 exists to protect could be replaced
    by a reconstruction of the thing it is supposed to check."""
    absent = tmp_path / "not_here.json"
    monkeypatch.setattr(pbr, "CAPTURE_PATH", absent)

    with pytest.raises(SystemExit):
        asyncio.run(pbr.prove(runs=1))
    assert not absent.exists(), "a missing capture was invented rather than refused"
    assert not hasattr(pbr, "capture_from_artifact"), (
        "the synthetic-capture writer is back; capture belongs to "
        "capture_retrieval and only to it")


# ── the ordering guarantee the capture went out of its way to preserve ────

def test_an_uncaptured_query_fails_loudly_rather_than_reading_as_empty(
        capture, tmp_path, monkeypatch):
    """⭐ CAUSAL, because the defect was never a wrong answer — it was a replay
    that could not tell "this query returned nothing" from "this query was
    never recorded". `build_one` dedupes keeping FIRST OCCURRENCE, so serving
    every shape from one flattened list would replay a DIFFERENT build than
    the one recorded.

    Drop a query the build still issues and the identity must come back
    FAILED. It reaches that verdict the long way — the replay raises, and
    `build_one` collects it through `asyncio.gather(return_exceptions=True)`
    and counts a provider failure — but the guarantee is the one that
    matters: a lost query shape can never read as a food that legitimately
    retrieved fewer rows."""
    intact = asyncio.run(pbr.prove(runs=1))

    maimed = json.loads(json.dumps(capture))
    identity = sorted(maimed["queries"])[0]
    assert len(maimed["queries"][identity]) > 1, identity
    maimed["queries"][identity].pop()

    path = tmp_path / "maimed.json"
    path.write_text(json.dumps(maimed))
    monkeypatch.setattr(pbr, "CAPTURE_PATH", path)
    starved = asyncio.run(pbr.prove(runs=1))

    assert intact["statuses"][identity] != bp.FAILED
    assert starved["statuses"][identity] == bp.FAILED, (
        f"{identity} lost a captured query shape and did not come back "
        f"FAILED — a missing query is reading as a thinner food")


def test_a_capture_from_a_moved_contract_is_refused(capture, tmp_path,
                                                    monkeypatch):
    """A replay against a moved retrieval contract describes a system that no
    longer exists. Produce nothing rather than numbers about the past."""
    moved = json.loads(json.dumps(capture))
    moved["meta"]["retrieval_fingerprint"] = "sha256:0000000000000000"

    path = tmp_path / "moved.json"
    path.write_text(json.dumps(moved))
    monkeypatch.setattr(pbr, "CAPTURE_PATH", path)

    with pytest.raises(cr.RetrievalContractMoved):
        asyncio.run(pbr.prove(runs=1))
