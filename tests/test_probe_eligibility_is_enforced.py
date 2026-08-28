"""⛔⛔⛔ A PROBE THAT CANNOT REACH THE BEHAVIOUR UNDER TEST IS AN INSTRUMENT
THAT CANNOT FAIL.

Two D1 rounds died to this. Round 1: two of six semantic probes never asked.
Round 2: c301 asked 0/3. Both chose utterances for the property being TESTED
without verifying they exhibit the behaviour the test REQUIRES — roughly 18
wasted turns, and worse, an absent behaviour read as evidence about its cause.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from scripts.probe_eligibility import (REGISTRY, IneligibleProbe, assert_eligible,
                                       is_eligible)

QUALIFIED = "Five Guys Little Cheeseburger and a small fries"
KILLED_AN_ARM = "An In-N-Out cheeseburger and fries"


def test_a_qualified_probe_passes():
    assert is_eligible(QUALIFIED)
    assert_eligible([{"id": 1, "message": QUALIFIED}])


def test_an_unqualified_probe_is_FATAL_not_a_data_point():
    """⭐ THE WHOLE POINT. Recording a miss as '0 asks observed' is how absence
    of the target behaviour became evidence about its cause."""
    with pytest.raises(IneligibleProbe):
        assert_eligible([{"id": 2, "message": "some utterance nobody qualified"}])


def test_a_probe_that_ALREADY_killed_an_arm_cannot_be_reused():
    assert not is_eligible(KILLED_AN_ARM)
    with pytest.raises(IneligibleProbe) as e:
        assert_eligible([{"id": 3, "message": KILLED_AN_ARM}])
    assert "INELIGIBLE" in str(e.value)


def test_eligibility_does_not_transfer_across_CODE_CHANGES():
    """Eligibility is evidence about a specific CODE state, not a property of
    the words.

    ⭐ CODE sha, not the whole tree. Comparing whole-repo SHAs made the guard
    self-defeating: registering eligibility is a commit, which changed the SHA,
    which invalidated the eligibility just registered. It blocked its own
    experiment twice on 2026-08-27. Scoping to behaviour-relevant paths is not
    a relaxation - a docs or corpus commit cannot change what the model does.
    """
    with pytest.raises(IneligibleProbe) as e:
        assert_eligible([{"id": 4, "message": QUALIFIED}],
                        {"_code_sha": "deadbeef"})
    assert "code" in str(e.value)
    # ...and it passes on the code state where it was actually established
    sha = json.loads(REGISTRY.read_text())["probes"][QUALIFIED]["code_sha"]
    assert_eligible([{"id": 4, "message": QUALIFIED}], {"_code_sha": sha})


def test_eligibility_is_NOT_power():
    """A probe asking 5 of 8 is eligible; whether 8 turns yield enough asks to
    decide anything is the separate INSUFFICIENT rule. Collapsing them would
    silently drop a real but low-rate probe."""
    probes = json.loads(REGISTRY.read_text())["probes"]
    panda = probes["Panda Express Bigger Plate: Orange Chicken, Teriyaki Chicken, and Super Greens"]
    assert panda["asks_observed"] == 5 and panda["turns"] == 8
    assert panda["eligible"] is True


def test_every_registered_probe_cites_its_evidence():
    for utt, p in json.loads(REGISTRY.read_text())["probes"].items():
        assert "asks_observed" in p and "turns" in p, utt
        assert p.get("code_sha"), f"{utt} has no code sha"
        assert p.get("evidence"), f"{utt} claims a status with no run cited"
        if p["eligible"]:
            assert p["asks_observed"] > 0, f"{utt} eligible with 0 asks"
        else:
            assert p["asks_observed"] == 0, (
                f"{utt} marked ineligible despite reaching the behaviour")
