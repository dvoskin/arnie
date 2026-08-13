"""PHASE 0.5 — A MECHANICAL MISMATCH VETO, AND THE 36% IT REFUSES TO GUESS.

    If a base-food mismatch is MECHANICALLY PROVABLE, code rejects it before
    semantic qualification. If it is not, code stays SILENT.

⭐ RECALL IS NOT THE OBJECTIVE. Measured over the 77 hand-adjudicated pairs:
precision 1.00, recall 0.64, and not one legitimate row touched. The value is
a deterministic floor under the subset code can PROVE wrong without judgement —
not coverage.

⭐⭐ AND THE MISSES ARE THE BOUNDARY, NOT A GAP TO CLOSE LATER BY GUESSING:

    mushrooms vs beef            mechanically different        CAUGHT
    sweet potato vs potato       needs "sweet" to CHANGE identity
    wild rice vs rice            needs "wild" to CHANGE identity
    salted mackerel vs mackerel  needs "salted" to NOT change it

Token structure cannot separate the last three safely, and a rule that guessed
would destroy evidence deterministically. The semantic layer catches all four
today. Silence is the correct output.

⭐⭐⭐ PLACEMENT IS THE WHOLE POINT. It runs FIRST, before semantic
qualification, on the retrieval population. Run after, it would be ceremonial:
the semantic layer would already have removed exactly these rows, and the
committed artifact — which has been through that layer — yields ZERO.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from skills.nutrition import eligibility as el
from skills.nutrition import pricing_artifact as art

#: The seven the survey proved catchable, from the signed discovery corpus.
KNOWN_MISMATCHES = [
    ("chicken", "Mushrooms, portabella, grilled"),
    ("beef", "Mushrooms, portabella, grilled"),
    ("egg", "Beef, New Zealand, imported, manufacturing beef"),
    ("potato", "Egg, whole, cooked, fried"),
    ("tilapia", "Lamb, New Zealand, imported, frozen, shoulder"),
    ("tilapia", "Buckwheat groats, cooked"),
    ("lamb", "Tofu, fried"),
]

#: Legitimate rows the veto must NEVER touch — including the four it cannot
#: prove, which must survive rather than be guessed at.
MUST_SURVIVE = [
    ("mackerel", "Fish, mackerel, salted"),
    ("banana", "Bananas, raw"),
    ("potato", "Potatoes, raw, skin"),
    ("salmon", "Fish, salmon, chinook, cooked, dry heat"),
    ("chicken", "Chicken, roasting, meat and skin, cooked, roasted"),
    # the deferred class: WRONG food, but not mechanically provable
    ("potato", "Sweet potato, cooked, boiled, without skin"),
    ("potato", "Sweet potato leaves, cooked, steamed, with salt"),
    ("rice", "Wild rice, cooked"),
]


@pytest.mark.parametrize("entity, description", KNOWN_MISMATCHES)
def test_every_provable_mismatch_is_vetoed(entity, description):
    assert el.base_food_mismatch(entity, description)


@pytest.mark.parametrize("entity, description", MUST_SURVIVE)
def test_no_legitimate_row_is_touched(entity, description):
    assert not el.base_food_mismatch(entity, description)


@pytest.mark.parametrize("entity, description", [
    ("beef", ""), ("", "Anything at all"), ("", ""),
])
def test_nothing_to_prove_means_silence_not_a_veto(entity, description):
    """⛔ AN ABSENT INPUT IS NOT A NEGATIVE ANSWER — the standing rule, one
    more layer down. A missing title must not read as 'not this food'."""
    assert not el.base_food_mismatch(entity, description)


def test_the_committed_artifact_yields_no_additional_vetoes():
    """⭐ CEREMONIAL IF RUN LATE. The committed artifact has already been
    through semantic qualification, so this rule finds nothing there — which
    is exactly why it must run on the RETRIEVAL population instead."""
    if not art.ARTIFACT_PATH.exists():
        pytest.skip("no committed artifact")
    document = json.loads(art.ARTIFACT_PATH.read_text())
    vetoed = [(identity, c.get("description"))
              for identity, entry in (document.get("entries") or {}).items()
              for c in (entry.get("candidates") or ())
              if el.base_food_mismatch(identity.partition("|")[0],
                                       c.get("description", ""))]
    assert vetoed == [], vetoed


def test_the_veto_is_typed_apart_from_semantic_rejection():
    """A later provenance audit must be able to tell MECHANICAL exclusion from
    a human or model semantic one; they answer different questions."""
    assert el.BASE_FOOD_MISMATCH == "mechanical_base_food_mismatch"
    assert el.BASE_FOOD_MISMATCH in el.REASONS
    veto = el.Ineligible("usda:1", el.BASE_FOOD_MISMATCH)
    assert veto.reason != el.BRANDED_FOR_GENERIC


def test_it_runs_before_any_semantic_work():
    """Placement, pinned: a mismatched record is refused without a duplicate
    key, a basis check, an energy read or a model ever being consulted."""
    from types import SimpleNamespace
    record = SimpleNamespace(evidence_id="usda:1",
                             title="Mushrooms, portabella, grilled",
                             structured={"data_type": "sr legacy"},
                             nutrition={"calories": 29},
                             provider_record_id="1")
    found = el.vetoes([record], base_entity="beef")
    assert len(found) == 1
    assert found[0].reason == el.BASE_FOOD_MISMATCH


def test_without_a_base_entity_the_rule_does_not_apply():
    """Supplied, never derived — composing an identity is the identity
    boundary's job, and this module must not become a second place that knows
    how."""
    from types import SimpleNamespace
    record = SimpleNamespace(evidence_id="usda:1",
                             title="Mushrooms, portabella, grilled",
                             structured={"data_type": "sr legacy"},
                             nutrition={"calories": 29},
                             provider_record_id="1")
    assert el.vetoes([record]) == ()


def test_a_weakened_rule_fails_the_discovery_cases():
    """ANTI-VACUITY: mutate the rule to always stay silent and the seven
    provable mismatches must stop being caught."""
    original = el.base_food_mismatch
    try:
        el.base_food_mismatch = lambda *_a, **_k: False
        survived = [pair for pair in KNOWN_MISMATCHES
                    if not el.base_food_mismatch(*pair)]
        assert len(survived) == len(KNOWN_MISMATCHES)
    finally:
        el.base_food_mismatch = original
    assert all(el.base_food_mismatch(*pair) for pair in KNOWN_MISMATCHES)
