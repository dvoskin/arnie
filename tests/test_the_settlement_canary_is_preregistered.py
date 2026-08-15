"""A9 — the canary is PRE-REGISTERED OFFLINE, and the artifact cannot drift out
from under it silently.

⛔⛔ A MATCHING CALORIE NUMBER IS NOT PROVENANCE. Banana 210 = 2x105 nearly
passed for a proof, which is why the pre-registration records the
`expected_evidence_id` and marks the calorie figure NON-BINDING in its own key
name. Production observation compares the ID; the number is a decoy kept
deliberately visible.

⭐ AND IT RECORDS WHAT DOES NOT WORK. Three committed identities cannot be
reached by the ranker at all. A canary built only from the identities that
happen to work would report the artifact as fully addressable — the silence
this project keeps paying for.
"""
from __future__ import annotations

import json
import pathlib

import pytest

RECORD = (pathlib.Path(__file__).resolve().parents[1]
          / "data" / "canary" / "general_settlement_preregistration.json")


@pytest.fixture(scope="module")
def record():
    assert RECORD.exists(), "the A9 pre-registration is missing"
    return json.loads(RECORD.read_text())


def test_the_preregistration_is_not_empty(record):
    """⛔ ANTI-VACUITY FIRST. An empty record would satisfy every check below it
    — including 'every entry still matches' — by having nothing to check."""
    assert record["artifact_identities"] >= 20
    assert len(record["reachable"]) >= 6, (
        "fewer than six reachable identities — A9 asks for six canaries and a "
        "record that cannot supply them must say so rather than shrink")


def test_every_preregistered_identity_carries_an_evidence_id(record):
    for entry in record["reachable"]:
        assert entry["expected_evidence_id"], (
            f"{entry['identity']} was pre-registered with no evidence id — "
            f"there would be nothing to compare in production except a number")
        assert entry["expected_rung"] == "artifact"


def test_the_artifact_still_yields_what_was_preregistered(record):
    """⭐ THE DRIFT GATE. If a rebuild changes an evidence id, this fails HERE,
    offline, rather than in production where a canary would silently be
    comparing against a stale expectation."""
    from core.canonical_pricing import price
    from skills.nutrition.pricing_artifact import evidence_for

    drifted = []
    for entry in record["reachable"]:
        evidence = evidence_for(entry["entity"], entry["preparation"])
        if evidence is None:
            drifted.append((entry["identity"], "no evidence today"))
            continue
        priced = price(entity=entry["entity"],
                       preparation=entry["preparation"],
                       artifact=evidence, consumed=None)
        if priced.evidence_id != entry["expected_evidence_id"]:
            drifted.append((entry["identity"], priced.evidence_id))
    assert not drifted, f"the artifact drifted from its pre-registration: {drifted}"


def test_the_unreachable_identities_are_recorded_rather_than_dropped(record):
    """⛔ `mackerel`, `oats`, `tilapia` — committed, and the ranker returns None
    for each. Recorded so the gap is a list rather than a memory."""
    unreachable = {e["identity"] for e in record["committed_but_unreachable"]}
    assert unreachable, "no unreachable identities recorded — if that is now "\
                        "true it is a RESULT and the record should say so"
    total = len(record["reachable"]) + len(unreachable)
    assert total == record["artifact_identities"], (
        f"{total} accounted for of {record['artifact_identities']} — an "
        f"identity fell out of both lists, which is how a coverage number "
        f"gets computed over a survivor set")


def test_the_count_states_its_measurement_mode(record):
    """⛔⛔ NEVER STATE A MATCH NUMBER WITHOUT ITS MODE. Reachability has been
    measured as 5-of-27 for the fleet and 2-of-27 for user 26 because it depends
    on the per-user NUTRITION_ACCURACY_V2 allowlist. This record's 3 is the
    OFFLINE artifact-only figure, and the two must never be compared silently."""
    mode = " ".join(record.get("measurement_mode") or [])
    assert "OFFLINE" in mode and "NUTRITION_ACCURACY_V2" in mode, (
        "the pre-registration does not state the mode its counts were measured "
        "in — the number is not a fact without it")
