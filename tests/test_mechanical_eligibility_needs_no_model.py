"""PHASE 0 — the deterministic boundary moves earlier.

    evidence -> DETERMINISTIC ELIGIBILITY -> advisory semantics -> ranking

The pricing artifact was deterministic at READ time and not at BUILD time: two
builds from identical seeds produced different qualified evidence, because a
model decided every dimension and its verdicts varied. `temperature` is not
available on the resolver model, so determinism cannot be bought by
configuring it — the model has to decide LESS.

⭐ THE CLAIM THIS FILE EXISTS TO PROVE FIRST. `from_usda` used to DISCARD
every structured field USDA states — `data_type`, `basis`, serving mass — and
preserve only title, brand and nutrition. The model was handed PROSE because
nothing else survived, which is a large part of why qualification became its
job at all.

    A dimension decidable from a structured field must not be decided by a
    language model, and it cannot be decided in code that never receives it.

So the first gates follow those fields through the WHOLE path — provider row,
adapter, `EvidenceRecord`, eligibility — rather than asserting the dataclass
has an attribute.

⭐⭐ AND TWO RULES ABOUT WHAT A MECHANICAL RULE MAY DO:

    IT VETOES AND NEVER ADMITS. A rule that could admit would be a second
    authority on identity — the defect this migration removes, relocated.

    A VETO IS NOT AN ABSTENTION. "Cannot evaluate" and "incompatible" are
    different outcomes. There is deliberately no reason meaning "unknown",
    because a rule that cannot evaluate its dimension must stay SILENT rather
    than manufacture a negative — which is this session's invariant applied
    to the layer replacing the thing that violated it.
"""
from __future__ import annotations

import pytest

from core.semantic_evidence import EvidenceRecord
from skills.nutrition import eligibility as el
from skills.nutrition.evidence_semantics import from_usda


def _row(fdc_id, description, *, data_type="SR Legacy", basis="per_100g",
         calories=200.0, protein=20.0, brand=""):
    """A provider row in the shape `from_usda` actually receives."""
    return {"fdc_id": fdc_id, "description": description, "brand": brand,
            "data_type": data_type, "basis": basis,
            "per100g": {"calories": calories, "protein": protein},
            "serving_mass_g": None, "serving_ml": None}


# ── ⭐ the structured facts survive the whole path ──────────────────────────

def test_provider_facts_survive_retrieval_into_the_record():
    """The adapter previously threw these away. Everything downstream that is
    supposed to be deterministic reads them, so losing them here silently
    re-delegates the decision to the model."""
    record = from_usda([_row(1, "Fish, mackerel, raw",
                             data_type="Foundation", basis="per_100g")])[0]
    assert record.structured["data_type"] == "Foundation"
    assert record.structured["basis"] == "per_100g"
    assert "serving_mass_g" in record.structured
    assert record.nutrition["calories"] == 200.0


def test_the_structured_facts_reach_eligibility_and_decide_it():
    """Not "the field exists" — the field CHANGES THE OUTCOME. A gate that
    only asserted presence would pass over an eligibility layer that ignored
    what it was handed."""
    curated = from_usda([_row(1, "Chicken, broilers, raw")])
    branded = from_usda([_row(2, "MEGA NUGGETS", data_type="Branded")])

    assert el.vetoes(curated) == ()
    vetoed = el.vetoes(branded)
    assert len(vetoed) == 1
    assert vetoed[0].reason == el.BRANDED_FOR_GENERIC
    assert vetoed[0].detail == "Branded"


def test_a_missing_structured_field_produces_silence_not_a_veto():
    """⭐ THE INVARIANT, at this layer. An absent `data_type` means we cannot
    evaluate brandedness — which is NOT evidence that the record is branded.
    Manufacturing a veto from a missing field is exactly how "no answer"
    became "negative answer" in the qualifier this replaces."""
    unknown = from_usda([_row(1, "Fish, mackerel, raw", data_type="")])
    assert el.vetoes(unknown) == ()


# ── veto vocabulary is closed, and has no "unknown" member ─────────────────

def test_there_is_no_reason_meaning_unknown():
    assert not (el.REASONS & {"unknown", "unclear", "undecidable",
                              "insufficient_evidence", "abstained"})


def test_a_reason_outside_the_vocabulary_cannot_be_constructed():
    """A cause that is not structural belongs to the advisory layer, where it
    cannot delete evidence."""
    with pytest.raises(ValueError):
        el.Ineligible("usda:1", "looked_wrong_to_me")


# ── the mechanical rules themselves ────────────────────────────────────────

def test_a_branded_record_is_vetoed_only_for_a_generic_intent():
    branded = from_usda([_row(1, "BRAND CHICKEN", data_type="Branded")])
    assert len(el.vetoes(branded, generic_intent=True)) == 1
    assert el.vetoes(branded, generic_intent=False) == ()


def test_a_basis_the_pricer_cannot_scale_is_vetoed():
    ok = from_usda([_row(1, "x", basis="per_100g")])
    bad = from_usda([_row(2, "x", basis="per_package_unknown")])
    assert el.vetoes(ok) == ()
    assert el.vetoes(bad)[0].reason == el.INCOMPATIBLE_BASIS


def test_a_record_stating_no_energy_cannot_price_anything():
    """A veto rather than silence, because the absence is the RECORD's own
    statement about itself — not our failure to evaluate it."""
    none = from_usda([_row(1, "x", calories=None)])
    assert el.vetoes(none)[0].reason == el.NO_ENERGY


def test_the_same_row_twice_is_one_piece_of_evidence():
    twice = from_usda([_row(7, "Fish, mackerel, raw"),
                       _row(7, "Fish, mackerel, raw")])
    vetoed = el.vetoes(twice)
    assert len(vetoed) == 1 and vetoed[0].reason == el.DUPLICATE


def test_two_different_rows_are_not_duplicates():
    both = from_usda([_row(1, "Fish, mackerel, raw"),
                      _row(2, "Fish, mackerel, cooked")])
    assert el.vetoes(both) == ()


# ── ⭐⭐ it vetoes, and never admits ────────────────────────────────────────

def test_eligibility_exposes_no_way_to_admit_a_record():
    """A rule that could ADMIT would be a second authority on identity. The
    module's whole surface returns vetoes; nothing returns an authorization."""
    public = {n for n in dir(el) if not n.startswith("_")}
    for name in ("vetoes", "ineligible_ids", "Ineligible", "REASONS"):
        assert name in public
    for forbidden in ("admit", "accept", "approve", "qualify", "eligible_ids",
                      "authorize", "select", "best"):
        assert forbidden not in public, (
            f"eligibility exposes {forbidden!r} — a mechanical layer that can "
            f"admit is a second authority on identity")


def test_no_rule_reads_a_model_produced_value():
    """Determinism is only real if the inputs are. `relationship`,
    `confidence` and `extracted` are the model's; none may be read here."""
    import ast
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent
              / "skills" / "nutrition" / "eligibility.py").read_text("utf-8")
    tree = ast.parse(source)

    # BOTH FORMS. The first version of this gate read only `ast.Attribute`,
    # so `record.confidence` was caught and `getattr(record, "confidence")`
    # sailed past — and this codebase reaches for `getattr` almost everywhere,
    # so the gate was guarding the form nobody writes. Found by mutation:
    # planting the getattr version left it GREEN.
    read = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)):
            read.add(node.args[1].value)

    assert not (read & {"relationship", "confidence", "extracted",
                        "abstained", "assessments"}), (
        "a mechanical rule reads model output — then it is not mechanical, "
        "and its determinism is borrowed from something that has none")


# ── determinism ────────────────────────────────────────────────────────────

def test_the_same_records_always_produce_the_same_vetoes():
    records = from_usda([
        _row(1, "Fish, mackerel, raw"),
        _row(2, "BRAND MACKEREL", data_type="Branded"),
        _row(3, "x", basis="per_package_unknown"),
        _row(4, "y", calories=None),
        _row(1, "Fish, mackerel, raw"),
    ])
    outcomes = {el.ineligible_ids(records) for _ in range(50)}
    assert len(outcomes) == 1, "eligibility is not deterministic"
    assert el.ineligible_ids(records) == frozenset(
        {"usda:2", "usda:3", "usda:4", "usda:1"})


def test_the_policy_is_versioned_so_a_removal_is_attributable():
    """A candidate that disappears between builds must be attributable to a
    POLICY CHANGE rather than filed as unexplained drift."""
    assert el.ELIGIBILITY_POLICY_VERSION
