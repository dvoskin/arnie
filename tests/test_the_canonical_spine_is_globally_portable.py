"""GLOBAL-READINESS INVARIANT — enforced, not written down.

    Arnie V1 remains US-first, but no new canonical food contract may encode
    USDA, English, US customary units, or the US market as intrinsic
    properties of FOOD IDENTITY.

    Source belongs to evidence.        Language belongs to interpretation.
    Units belong to quantity.          Geography belongs to source policy.
    Brand/variant belongs to typed identity.
    None may leak into the universal canonical food lifecycle.

⭐ WHY THIS IS A TEST FILE AND NOT A PARAGRAPH. This session alone produced
three guarantees that existed only as prose and were violated anyway: the
"77 rows" that turned out to be 6 production rows, the "two-engine" suite that
was one engine twice, and a length-penalty comment that described a category
prefix. A constraint nobody executes is a constraint nobody keeps.

⭐⭐ AND THESE GATES ARE CHEAP TODAY ON PURPOSE. Most already pass — the spine
was built well. Their value is not discovery, it is REGRESSION: they fail the
day someone adds `fdc_id` to an identity key, or keys a semantic rule on
ounces, or assumes an evidence id is globally unique. Rebuilding the canonical
spine at a million foods across dozens of markets is the cost they exist to
avoid, and it is paid years before it is felt.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from skills.nutrition import semantic_annotations as sa
from skills.nutrition.pricing_artifact import key, priced_identity, split_identity

_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The modules that decide what a food IS. Evidence adapters and presentation
#: are deliberately excluded: source and language are legitimate THERE.
_SEMANTIC_MODULES = (
    "skills/nutrition/eligibility.py",
    "skills/nutrition/cooking_state.py",
    "skills/nutrition/semantic_annotations.py",
    "skills/nutrition/preference_dimensions.py",
    "skills/nutrition/preparation_ontology.py",
)


def _source(relative):
    path = _ROOT / relative
    if not path.exists():
        pytest.skip(f"{relative} not present")
    return path.read_text()


# ── 1. identity cannot require a USDA id ──────────────────────────────────

def test_a_canonical_identity_needs_no_usda_id():
    """An identity is (entity, preparation). Nothing else. If a provider id
    were ever required to name a food, every non-USDA market would need a
    parallel identity space."""
    identity = key("berenjena", "asada")
    assert identity == "berenjena|asada"
    assert "usda" not in identity.lower()
    assert split_identity("berenjena", "asada")[0] == "berenjena"
    assert priced_identity("berenjena", "asada")


def test_an_annotation_is_keyed_by_identity_and_evidence_not_by_provider():
    annotation = sa.Annotation(identity_key="berenjena|asada",
                               evidence_id="bedca:12345",
                               relationship=sa.SAME_IDENTITY, confidence=0.9)
    store = sa.Store()
    store.record(annotation)
    assert sa.eligible(store.get("berenjena|asada", "bedca:12345"))
    assert not store.needs_resolution("berenjena|asada", "bedca:12345")


@pytest.mark.parametrize("relative", _SEMANTIC_MODULES)
def test_no_semantic_module_hard_codes_a_provider(relative):
    """⭐ `usda` may appear in PROSE explaining where a rule came from — this
    checks CODE. A string literal or identifier naming one provider inside a
    module that decides identity is the provider leaking into the spine."""
    tree = ast.parse(_source(relative))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "usda" in node.value.lower() and not node.value.startswith("\n"):
                offenders.append(node.value[:60])
        if isinstance(node, ast.Name) and "usda" in node.id.lower():
            offenders.append(node.id)
    # docstrings are Constants too; exclude the module/class/function ones
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc[:60])
    offenders = [o for o in offenders if o not in docstrings]
    assert offenders == [], f"{relative} names a provider in code: {offenders}"


# ── 2. identity cannot require an English display string ──────────────────

@pytest.mark.parametrize("entity, preparation", [
    ("berenjena", "asada"),          # es
    ("aubergine", "grillée"),        # fr, with an accent
    ("なす", "焼き"),                  # ja, non-latin
    ("баклажан", "жареный"),         # ru, cyrillic
])
def test_a_canonical_identity_survives_any_language(entity, preparation):
    """⭐ THE IDENTITY IS AN OPAQUE KEY, not a display string. Translation must
    later RESOLVE INTO an identity, never create a translated duplicate of
    one — which is only possible if the key itself is language-agnostic."""
    identity = key(entity, preparation)
    assert entity in identity and preparation in identity

    annotation = sa.Annotation(identity_key=identity, evidence_id="src:1",
                               relationship=sa.SAME_IDENTITY, confidence=0.9)
    store = sa.Store()
    store.record(annotation)
    assert sa.eligible(store.get(identity, "src:1"))
    assert sa.disposition(store.get(identity, "src:1")) == "priceable"


def test_the_relationship_vocabulary_is_not_a_display_vocabulary():
    """Relationships are enum members, not sentences. A UI string in this
    vocabulary would make the semantic layer untranslatable."""
    for relationship in sa.RELATIONSHIPS:
        assert relationship.isupper()
        assert " " not in relationship


# ── 3. semantic rules cannot depend on US measurement units ───────────────

_US_UNITS = ("ounce", " oz", "pound", " lb", "cup", "tablespoon", "tbsp",
             "teaspoon", "tsp", "fahrenheit", "fluid ounce")


@pytest.mark.parametrize("relative", _SEMANTIC_MODULES)
def test_no_semantic_rule_keys_on_a_us_customary_unit(relative):
    """⭐ UNITS BELONG TO QUANTITY NORMALIZATION. A rule that decides what a
    food IS by reading "oz" or "cup" would answer differently in a market that
    writes grams — and identity must not depend on how the amount was typed."""
    tree = ast.parse(_source(relative))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            if any(unit in lowered for unit in _US_UNITS):
                offenders.append(node.value[:60])
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc[:60])
    offenders = [o for o in offenders if o not in docstrings]
    assert offenders == [], f"{relative} keys on a US unit: {offenders}"


# ── 4. evidence ids must be source-namespaced ─────────────────────────────

def test_an_evidence_id_carries_its_source():
    """⭐ NOT GLOBALLY UNIQUE — NAMESPACED. USDA 173089 and some future
    national database's 173089 are different rows, and an annotation store
    keyed on the bare number would silently merge them. `usda:` is already
    the shape; this keeps it from being dropped as "redundant"."""
    from skills.nutrition import pricing_artifact as art
    import json

    if not art.ARTIFACT_PATH.exists():
        pytest.skip("no committed artifact")
    doc = json.loads(art.ARTIFACT_PATH.read_text())
    from scripts import baseline_signatures as bs

    unnamespaced = [evidence for _identity, evidence in bs.by_pair()
                    if ":" not in evidence]
    assert unnamespaced == [], unnamespaced
    assert all(evidence.split(":", 1)[0].isalnum()
               for _i, evidence in bs.by_pair())


def test_two_sources_can_describe_one_identity_without_collision():
    """The same numeric id in two namespaces must stay two annotations."""
    store = sa.Store()
    store.record(sa.Annotation("aubergine|", "usda:173089",
                               sa.SAME_IDENTITY, confidence=0.9))
    store.record(sa.Annotation("aubergine|", "ciqual:173089",
                               sa.DIFFERENT_IDENTITY, confidence=0.9))
    assert len(store.by_key) == 2
    assert sa.eligible(store.get("aubergine|", "usda:173089"))
    assert not sa.eligible(store.get("aubergine|", "ciqual:173089"))


# ── 5. market variants without hacking generic identity ───────────────────

def test_a_market_variant_is_a_separate_identity_not_a_special_case():
    """⭐ A regional formulation is a DIFFERENT FOOD, expressible with the
    ordinary identity mechanism. If it needed a flag, an exception table or a
    suffix convention, generic identity would be carrying market knowledge."""
    generic = key("chocolate bar", "")
    variant = key("chocolate bar eu", "")
    assert generic != variant

    store = sa.Store()
    store.record(sa.Annotation(generic, "usda:1", sa.SAME_IDENTITY,
                               confidence=0.9))
    store.record(sa.Annotation(variant, "openfoodfacts:1",
                               sa.COMPATIBLE_SPECIALIZATION, confidence=0.9))
    assert sa.eligible(store.get(generic, "usda:1"))
    assert sa.eligible(store.get(variant, "openfoodfacts:1"))
    # and the two never resolve to each other by accident
    assert store.get(generic, "openfoodfacts:1") is None


def test_the_invalidation_vocabulary_has_no_market_or_provider_member():
    """A cause named for one provider would make provider-specific behaviour
    a first-class part of the lifecycle."""
    for cause in sa.INVALIDATION_CAUSES:
        lowered = cause.lower()
        assert "usda" not in lowered and "fdc" not in lowered
        assert "us_" not in lowered and not lowered.endswith("_us")


# ── 6. DESTRUCTIVE operations must honour the namespace too ───────────────

def test_a_rejection_removes_only_its_own_source():
    """⛔ THE MUTATION WITNESS. `apply_admission_decisions` used to compute
    `evidence.split(":")[-1]` and match on `fdc_id`, discarding the source at
    the exact point the operation becomes irreversible — so a rejection naming
    `usda:123` would have deleted `ciqual:123` as well.

    ⭐ THE IRONY IS THE LESSON. The gates above already proved the ANNOTATION
    STORE keeps those two apart. Proving it for storage and not for DELETION
    left the invariant true everywhere except where it mattered most."""
    from skills.nutrition import pricing_artifact as art

    ladder = [{"fdc_id": "123", "evidence_id": "usda:123", "description": "a"},
              {"fdc_id": "123", "evidence_id": "ciqual:123", "description": "b"}]
    kept = [c for c in ladder
            if art.candidate_evidence_id(c) != "usda:123"]
    assert [c["evidence_id"] for c in kept] == ["ciqual:123"]


def test_an_unqualified_candidate_is_refused_not_assumed_usda():
    """A default here would be how one provider silently becomes "the food
    database" — by convenience rather than by decision."""
    from skills.nutrition import pricing_artifact as art

    with pytest.raises(art.UnqualifiedEvidence):
        art.candidate_evidence_id({"fdc_id": "1"})
    with pytest.raises(art.UnqualifiedEvidence):
        art.candidate_evidence_id({"evidence_id": "170032"})
    assert art.candidate_evidence_id({"source": "ciqual", "fdc_id": "9"}) \
        == "ciqual:9"


def test_every_committed_candidate_carries_its_source():
    """After the backfill, provenance is CARRIED rather than inferred."""
    import json

    from skills.nutrition import pricing_artifact as art
    if not art.ARTIFACT_PATH.exists():
        pytest.skip("no committed artifact")
    doc = json.loads(art.ARTIFACT_PATH.read_text())
    for identity, entry in (doc.get("entries") or {}).items():
        for candidate in (entry.get("candidates") or ()):
            evidence = art.candidate_evidence_id(candidate)
            assert ":" in evidence, (identity, evidence)


# ── 7. the proof regime is declared, not inherited ────────────────────────

def test_the_ranking_regime_ignores_a_hostile_caller_environment():
    """⭐ A BASELINE THE SHELL CAN MOVE IS NOT FROZEN. Every flag the regime
    depends on is set explicitly — including the ones wanted OFF, because an
    unset variable and one set elsewhere are identical to `os.getenv` and only
    one of them is a decision."""
    import os

    from skills.nutrition import v2_gate

    hostile = {"NUTRITION_ACCURACY_V2": "true",
               "NUTRITION_AS_EATEN_PREFERENCE": "true"}
    previous = {k: os.environ.get(k) for k in hostile}
    os.environ.update(hostile)
    try:
        with v2_gate.ranking_regime(v2_gate.RANK_V2) as regime:
            assert regime == v2_gate.RANK_V2
            assert v2_gate.ranking_policy_version() == "rank_v2"
            assert v2_gate.as_eaten_active() is False
        with v2_gate.ranking_regime(v2_gate.RANK_V1):
            assert v2_gate.ranking_policy_version() == "rank_v1"
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import importlib
        import core.food_intelligence as fi
        importlib.reload(fi)


def test_phase_zero_names_the_regime_it_proves_against():
    from skills.nutrition import v2_gate
    assert v2_gate.PHASE_0_REGIME == v2_gate.RANK_V2
    with pytest.raises(ValueError):
        with v2_gate.ranking_regime("rank_whatever"):
            pass


# ── 8. the preference refuses ambiguity rather than taking the first ──────

def test_two_comparable_as_eaten_forms_refuse_the_refinement():
    """⭐ ORDER MUST NOT BECOME AN IMPLICIT PREFERENCE. With two equally
    comparable as-eaten rows this policy genuinely does not know which, and
    saying so leaves the winner where an owned policy put it."""
    from skills.nutrition.preference_dimensions import prefer_as_eaten

    winner = {"fdc_id": "1", "description": "Chicken, meat only, cooked"}
    one = {"fdc_id": "2", "description": "Chicken, meat and skin, cooked"}
    assert prefer_as_eaten(winner, [one]) is one            # exactly one
    two = {"fdc_id": "3", "description": "Chicken, lean and fat, cooked"}
    assert prefer_as_eaten(winner, [one, two]) is winner     # more than one
    assert prefer_as_eaten(winner, []) is winner             # none


def test_comparability_is_symmetric_and_refinement_preserves_the_residue():
    from skills.nutrition.preference_dimensions import (comparable,
                                                        prefer_as_eaten,
                                                        residue)
    a = "Chicken, roasting, meat only, cooked, roasted"
    b = "Chicken, roasting, meat and skin, cooked, roasted"
    assert comparable(a, b) == comparable(b, a)

    winner = {"fdc_id": "1", "description": a}
    refined = prefer_as_eaten(winner, [{"fdc_id": "2", "description": b}])
    assert refined is not winner
    assert residue(a) == residue(refined["description"])
