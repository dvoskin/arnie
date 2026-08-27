"""⛔⛔⛔ NO CRITERION MAY BE PROMOTED FROM THE CORPUS THAT GENERATED IT.

FOUR criteria have now died the same death, and the death is always the same
shape: a rule inferred from the cases it was tested on, which therefore explains
them perfectly and predicts nothing.

    magnitude / span thresholds        disproved -- impact_cal overlaps completely
    dish vs vessel                     fitted to 3 fixtures, then "falsified" on
                                       n=1, and the falsification itself did not
                                       survive n=8
    four-criterion evidence contract   drafted on invalid-config behaviour
    H1 unspecified-secondary           refuted by held-out test

Three of those reached a written document. One reached a `docs/` file that was
about to become code. **Four is enough evidence that this must be a GATE rather
than a convention** (Danny, 2026-08-27).

⭐ H1 IS THE PROOF THAT THE GATE PAYS FOR ITSELF. It was derived on
`real_meal_expectations_v1`, preregistered, and tested on
`heldout_defaultability_v1` -- where it died, in 48 turns, instead of in
production. That is the whole point.

⚠ WHAT THIS GATE CANNOT DO. It cannot check that a corpus is a GOOD test, that
it has controls, or that it is powered. `heldout_defaultability_v1` carries
negative and positive control arms and preregistered falsification conditions
because a human designed it that way. This gate only enforces the one property
a machine can check: **the corpus you validated on is not the corpus you
derived from.**
"""
from __future__ import annotations

import json
import pathlib

import pytest

REGISTRY = pathlib.Path("data/criteria_registry.json")


def _load() -> list:
    return json.loads(REGISTRY.read_text())["criteria"]


def _violates(c: dict) -> bool:
    """The gate itself, as ONE function, so the tests and any future caller
    cannot drift apart."""
    if c.get("status") != "promoted":
        return False
    validated = c.get("validated_on_corpus")
    return (not validated) or validated == c.get("derived_from_corpus")


def test_no_promoted_criterion_was_validated_on_its_own_corpus():
    bad = [c["name"] for c in _load() if _violates(c)]
    assert not bad, (
        f"criteria promoted without an independent corpus: {bad}. A rule "
        "validated on the cases that generated it explains them perfectly and "
        "predicts nothing — this has killed four criteria.")


def test_every_criterion_declares_its_provenance():
    """A criterion with no declared origin cannot be checked at all — which is
    indistinguishable from one that has something to hide."""
    for c in _load():
        assert c.get("name"), c
        assert c.get("status") in {"proposed", "promoted", "refuted", "retired"}, c
        assert "derived_from_corpus" in c, (
            f"{c['name']} does not declare the corpus it was derived from")
        assert "validated_on_corpus" in c, (
            f"{c['name']} does not declare the corpus it was validated on")


def test_the_gate_actually_REJECTS_a_self_validated_criterion():
    """⭐ THE NEGATIVE INVARIANT. A gate that has never been shown to fail is a
    gate nobody has. Every criterion in the registry today is proposed, refuted
    or retired, so the positive test above would pass against a `_violates` that
    always returns False."""
    self_validated = {"name": "fabricated", "status": "promoted",
                      "derived_from_corpus": "corpus_a",
                      "validated_on_corpus": "corpus_a"}
    assert _violates(self_validated), (
        "the gate does not reject a criterion validated on its own corpus")

    no_validation = {"name": "fabricated", "status": "promoted",
                     "derived_from_corpus": "corpus_a",
                     "validated_on_corpus": None}
    assert _violates(no_validation), (
        "the gate does not reject a promoted criterion with no held-out corpus")

    legitimate = {"name": "fabricated", "status": "promoted",
                  "derived_from_corpus": "corpus_a",
                  "validated_on_corpus": "corpus_b"}
    assert not _violates(legitimate), (
        "the gate rejects a legitimately held-out criterion — it would block "
        "the very promotion path it exists to protect")


def test_H2_is_registered_and_NOT_promoted():
    """The live case. H2 fits better than anything before it and is exactly the
    kind of rule that gets adopted on enthusiasm."""
    h2 = next((c for c in _load()
               if c["name"] == "h2_unbounded_quantity"), None)
    assert h2 is not None, "H2 is not in the registry"
    assert h2["status"] == "proposed", (
        "H2 was promoted. It was derived post-hoc from the corpus that refuted "
        "H1 and has no independent validation corpus.")
    assert h2["validated_on_corpus"] is None
    assert h2["derived_from_corpus"] == "heldout_defaultability_v1"


@pytest.mark.parametrize("name", ["magnitude_span_threshold", "dish_vs_vessel",
                                  "four_criterion_evidence_contract",
                                  "h1_unspecified_secondary_component"])
def test_the_dead_criteria_stay_dead(name):
    """Registered so a future session cannot rediscover one and adopt it as new.
    `magnitude_span_threshold` in particular was explicitly retired: do not
    encode 'normal range' as food-specific calorie tolerances."""
    c = next((x for x in _load() if x["name"] == name), None)
    assert c is not None, f"{name} vanished from the registry"
    assert c["status"] in {"refuted", "retired"}, (
        f"{name} was revived to status={c['status']}")
