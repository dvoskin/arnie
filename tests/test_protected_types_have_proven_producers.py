"""⛔⛔⛔ NEVER TREAT "GUARD PASSES" AS EVIDENCE UNLESS THE PROTECTED STATE IS
PROVEN REACHABLE.

The standing rule the 2026-08-27 session earned. Its failures all had one shape:

    CF23        trust was TRUE OF ROWS NOBODY COULD CREATE — correct and inert
    memory rung `float('exact')` in a bare except: 0 of 836 rows, gates green
    _backfill_city  dead since P17f.5 behind `except: pass`
    ask_type    `classify("consumed")` maps correctly, and NOTHING EMITS
                `field="consumed"` — so a consumption question arrived labelled
                `menu_size`, a DEFAULTABLE type, while the negative-invariant
                test passed and was correct

A mapping can be right while its protected input never occurs. **A guard whose
protected input never occurs is a guard nobody has.**

⭐ This test does NOT demand that every type be reachable — three are not, and
that is the measured truth, recorded rather than hidden. What it forbids is
**treating an unproven type as authority**: no policy may consume a type whose
producer has never been observed.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from skills.nutrition import ask_type as AT

REGISTRY = pathlib.Path("data/ask_type_producers.json")


def _types() -> dict:
    return json.loads(REGISTRY.read_text())["types"]


def policy_may_consume(t: str) -> bool:
    """THE GUARD, as one function. A type is consumable by policy only if it is
    BOTH a defaultable candidate AND producer-proven."""
    info = _types().get(t) or {}
    return t in AT.DEFAULTABLE_CANDIDATES and info.get("status") == "proven"


def test_every_canonical_type_declares_its_producer_status():
    """A type with no declared status cannot be checked — indistinguishable
    from one that has something to hide."""
    reg = _types()
    for t in AT.ALL:
        if t == AT.UNCLASSIFIED:
            continue
        assert t in reg, f"{t} declares no producer evidence"
        assert reg[t].get("status") in {"proven", "unproven"}, reg[t]


def test_a_proven_type_CITES_its_evidence():
    """'Proven' with no citation is an assertion, not evidence."""
    for t, info in _types().items():
        if info.get("status") == "proven":
            assert info.get("evidence"), f"{t} claims proven with no evidence"
            assert (info.get("turns") or 0) > 0, f"{t} claims proven with 0 turns"


def test_NO_POLICY_MAY_CONSUME_AN_UNPROVEN_TYPE():
    """⭐ THE RULE, ENFORCED. Measured 2026-08-27: three types have zero
    producers, and `portion_multiplier` + `unstated_extras` are in
    DEFAULTABLE_CANDIDATES. A policy reading them would be acting on a subject
    nothing has ever been observed to produce."""
    unproven_but_defaultable = [
        t for t in AT.DEFAULTABLE_CANDIDATES
        if (_types().get(t) or {}).get("status") != "proven"]
    for t in unproven_but_defaultable:
        assert not policy_may_consume(t), (
            f"{t} is a defaultable candidate with NO proven producer and the "
            "guard would let a policy consume it")


def test_the_guard_REJECTS_and_ACCEPTS_the_right_things():
    """⭐ THE NEGATIVE INVARIANT. Without this, `policy_may_consume` returning
    False unconditionally would satisfy every test above."""
    assert policy_may_consume("menu_size"), (
        "the guard rejects a proven defaultable type — it would block the very "
        "path it exists to protect")
    assert not policy_may_consume("portion_multiplier"), "unproven, must reject"
    # ⛔⛔ TWO GUARDS IN SERIES, AND THE OUTER ANSWERED FOR BOTH (P3, again).
    # Asserting only `not policy_may_consume(...)` here was VACUOUS for this
    # type: it is refused because it is UNPROVEN, so adding it to
    # DEFAULTABLE_CANDIDATES left this suite GREEN (mutation M4) — the
    # unprovenness shielded the mutation. The membership is asserted DIRECTLY
    # so the shield is removed and this test stands on its own.
    assert AT.CONSUMPTION_COMPLETE not in AT.DEFAULTABLE_CANDIDATES, (
        "consumption_complete became a defaultable candidate — 'did you finish "
        "it?' is user state, and no producer status may make it consumable")
    assert not policy_may_consume("consumption_complete"), (
        "NOT defaultable by decision — must never be consumable")
    assert not policy_may_consume("preparation_fat"), "OILS-owned, not defaultable"
    assert not policy_may_consume("nonsense"), "unknown type must reject"


def test_consumption_complete_is_recorded_as_COLLAPSING_into_a_defaultable_type():
    """⛔ The specific live hazard, pinned so it cannot be quietly forgotten:
    a consumption question was observed wearing the `menu_size` label."""
    info = _types()["consumption_complete"]
    assert info["status"] == "unproven"
    assert "menu_size" in (info.get("note") or ""), (
        "the record no longer states that consumption_complete collapses into "
        "menu_size — that is the reason a menu_size row is not authorization")


@pytest.mark.parametrize("t", ["menu_size", "continuous_portion"])
def test_contaminated_proven_types_say_so(t):
    """Producer-proven is not the same as CLEAN. Both of these have a real
    producer AND a documented case of another subject wearing their label."""
    assert "⚠" in (_types()[t].get("note") or ""), (
        f"{t} no longer records that its bucket is contaminated")
