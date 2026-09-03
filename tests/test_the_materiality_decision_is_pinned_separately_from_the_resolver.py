"""⛔ A CLARIFICATION-POLICY CHANGE DOES NOT RIDE ON A PRICING-RESOLVER BUMP
(Danny, 2026-09-03, IR-PUBLISH hold). Regenerating the preparation-materiality
artifact under resolver v2 declared potato and mushrooms immaterial — those
turns would stop asking the preparation question — and nothing in the Identity
Reachability proposition covers that. The shipped decision therefore stays in
force under an explicit certified pin; a build under a newer resolver is refused
until the pin is bumped by its own certification."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from core import materiality_artifact as ma
from skills.nutrition import preparation_artifact as pa
from skills.nutrition.preparation_activation import space_is_material

PRE_IR_DECISION = {
    "chicken": {"grilled": 151.0, "roasted": 167.0, "fried": 219.0},
    "mushrooms": {"grilled": 29.0, "fried": 39.0},
    "potato": {"roasted": 127.0, "fried": 260.0},
}


def test_the_committed_artifact_is_the_pre_ir_decision_and_loads_under_the_pin():
    doc = json.loads(pa.ARTIFACT_PATH.read_text())
    assert {k: v["space"] for k, v in doc["entries"].items()} == PRE_IR_DECISION
    assert doc["resolver_version"] == pa.CERTIFIED_RESOLVER_VERSION == "food_evidence_semantics_v1"
    artifact = pa.verified()                       # raises Stale if the reader refuses it
    assert set(artifact.entries) == {"chicken", "mushrooms", "potato"}


@pytest.mark.parametrize("food", ["potato", "mushrooms", "chicken"])
def test_the_preparation_question_still_opens_for_the_pre_ir_foods(food):
    """The behaviour the hold protects: these foods keep a material space."""
    space = pa.space_for(food)
    assert space, f"{food} lost its material space — the clarification behaviour changed"
    assert space_is_material(space)


def test_the_pin_is_not_the_live_resolver():
    """The decoupling itself. When the pricing resolver moves, this stays put;
    moving it is a deliberate, separately certified act."""
    from skills.nutrition import evidence_semantics
    assert pa.live_resolver_version() == evidence_semantics.VERSION == "food_evidence_semantics_v2"
    assert pa.resolver_version() == pa.CERTIFIED_RESOLVER_VERSION != pa.live_resolver_version()


def test_a_build_under_a_newer_resolver_is_refused_until_the_pin_moves():
    """⛔ THE NO-TRANSITION CASE: the v2 regeneration that dropped potato and
    mushrooms must not be readable by accident."""
    from scripts.build_materiality_artifact import assemble_document, MATERIAL
    doc = assemble_document([{"food": "chicken", "status": MATERIAL, "material": True,
                              "space": {"fried": 219.0, "roasted": 167.0}, "evidence_ids": ["usda:1"]}],
                            now=datetime.now(timezone.utc))
    assert doc["resolver_version"] == pa.live_resolver_version()
    with pytest.raises(ma.Stale):
        ma.verify(ma.parse(doc), resolver_version=pa.resolver_version(),
                  vocabulary_fingerprint=pa.vocabulary_fingerprint(),
                  retrieval_fingerprint=pa.retrieval_fingerprint())
