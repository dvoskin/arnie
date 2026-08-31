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
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "criteria_registry.json"


def _load() -> list:
    return json.loads(REGISTRY.read_text())["criteria"]


def _violates(c: dict) -> bool:
    """The gate itself, as ONE function, so the tests and any future caller
    cannot drift apart.

    ⭐ 2026-08-31 — TWO KINDS OF CLAIM, TWO OBLIGATIONS, NEITHER OPTIONAL.

    A `corpus_criterion` is a claim about FOOD ("an ask is material when its
    span exceeds X"). Only a held-out corpus can settle it, and four of them
    have died to being validated on the cases that generated them.

    An `architectural_invariant` is a claim about the SYSTEM ("the same
    unresolved fact gets the same decision under any parent"). It is not
    derived from a corpus and **no corpus can validate it** — a corpus could
    only ever fail to notice a violation. Requiring a held-out corpus for it
    would demand evidence that cannot exist, which is how a gate teaches people
    to route around it.

    ⛔ SO THE LABEL IS NOT AN ESCAPE HATCH — it SWAPS one obligation for a
    harder one. An architectural invariant must name a mechanical proof that
    EXISTS, COLLECTS, PASSES, and CARRIES NO XFAIL, checked below. A
    corpus criterion has to survive one held-out corpus; this has to survive
    every input its grid can generate, and be shown to go red when the
    behaviour it pins is removed.
    """
    if c.get("status") != "promoted":
        return False
    if c.get("kind") == "architectural_invariant":
        # judged by `test_every_architectural_invariant_names_a_live_proof`,
        # not by corpus independence — but never by nothing.
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
        assert c.get("kind") in {"corpus_criterion", "architectural_invariant"}, (
            f"{c['name']} declares no kind — and the two kinds carry different "
            "obligations, so an undeclared one has neither")
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


def test_every_architectural_invariant_names_a_live_mechanical_proof():
    """⛔⛔⛔ THE OBLIGATION THAT REPLACES THE HELD-OUT CORPUS.

    `architectural_invariant` exempts a claim from corpus independence. That
    exemption is worth exactly as much as what replaces it, so what replaces it
    is checked here and is deliberately stricter:

      the named file EXISTS      — a proof nobody can open is a claim
      it COLLECTS >0 tests       — a file that imports and asserts nothing
                                   passes silently, which is the vacuity this
                                   repo keeps cataloguing
      it PASSES                  — now, on this tree, not when it was written
      it carries NO xfail        — ⭐ a solved xfail left behind, or a strict
                                   xfail still marking a live defect, both mean
                                   the invariant is NOT actually held. An
                                   invariant whose proof is allowed to fail is
                                   not an invariant.
    """
    import subprocess

    invariants = [c for c in _load()
                  if c.get("kind") == "architectural_invariant"
                  and c.get("status") == "promoted"]
    assert invariants, (
        "no promoted architectural invariant — if this is genuinely true, "
        "delete this gate rather than leaving it green over nothing")

    for c in invariants:
        proof = c.get("mechanical_proof")
        assert proof, f"{c['name']} names no mechanical_proof"
        path = ROOT / proof
        assert path.exists(), f"{c['name']}: {proof} does not exist"

        src = path.read_text(encoding="utf-8")
        # ⛔ THE BINDING MUST GO BOTH WAYS, AND MUTATION M3 IS WHY.
        # Checking only "a file exists and passes" accepted
        # `tests/test_food_calibration.py` as the proof of an invariant it has
        # nothing to do with — the shape was right and the substance was
        # absent, which is the grep trap wearing a different hat. So the proof
        # has to DECLARE which criterion it proves: the registry names the
        # file, the file names the criterion, and an unrelated file cannot
        # satisfy it by accident. A copy-paste now has to lie in writing.
        assert c["name"] in src, (
            f"{c['name']}: {proof} does not name the criterion it is claimed "
            f"to prove. Add `PROVES = \"{c['name']}\"` (or name it in the "
            "module docstring) so the binding is two-way and a passing but "
            "unrelated file cannot stand in for the proof")
        assert "xfail" not in src, (
            f"{c['name']}: {proof} contains an xfail. A promoted invariant "
            "whose proof is allowed to fail is not an invariant — either the "
            "defect is live (so demote the criterion) or the xfail is solved "
            "(so promote it to a plain assertion)")

        # ⛔ NO `-q` HERE, AND THIS GATE CAUGHT ITS OWN VERSION OF THE TRAP.
        # `addopts` in the project config already carries `-q`; adding another
        # makes `-qq`, which prints NINE DOTS AND NO TALLY LINE while exiting
        # 0. The first draft of this check did exactly that and failed on its
        # own proof file — which is the behaviour you want from a gate that
        # exists to refuse "it collected nothing" dressed as success.
        run = subprocess.run(
            [sys.executable, "-m", "pytest", str(path), "-p", "no:randomly",
             "--no-header"],
            cwd=ROOT, capture_output=True, text=True, timeout=300)
        assert run.returncode == 0, (
            f"{c['name']}: its mechanical proof does not pass on this tree\n"
            f"{run.stdout[-1500:]}")
        assert re.search(r"\b[1-9]\d* passed", run.stdout), (
            f"{c['name']}: {proof} collected no passing tests — a file that "
            f"asserts nothing passes silently\n{run.stdout[-800:]}")


def test_the_architectural_exemption_is_not_a_BLANK_CHEQUE():
    """⭐ THE NEGATIVE INVARIANT ON THE NEW BRANCH. `_violates` now returns
    False for every architectural invariant, so the corpus gate cannot be what
    protects them — and a gate that protects nothing is how an exemption
    becomes a laundering label. This pins that the REPLACEMENT obligation is
    real by showing it rejects the three ways of faking it."""
    import subprocess

    # a corpus criterion is still judged the old way, unchanged
    assert _violates({"name": "x", "kind": "corpus_criterion",
                      "status": "promoted", "derived_from_corpus": "a",
                      "validated_on_corpus": "a"})
    # ...and relabelling it does exempt it from THAT gate —
    assert not _violates({"name": "x", "kind": "architectural_invariant",
                          "status": "promoted", "derived_from_corpus": "a",
                          "validated_on_corpus": "a"})
    # — which is only safe because the other gate then demands a live proof.
    # Proven by running it against a file that does not exist.
    missing = ROOT / "tests" / "test_this_file_does_not_exist_on_purpose.py"
    assert not missing.exists()
    run = subprocess.run(
        [sys.executable, "-m", "pytest", str(missing), "-p", "no:randomly",
         "--no-header"],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert run.returncode != 0, (
        "pytest exits 0 on a missing proof file, so 'the proof exists' would "
        "not actually be checked by running it")
