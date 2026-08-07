"""THE SEMANTIC EXTENSION CONTRACT, enforced.

Every invariant here exists because its absence produced a defect, or because
the shape of one is already visible. The contract is not a document — a
documented convention is one careless commit from a fifth legacy producer, and
this codebase is currently deleting the first four.

WHAT THIS FILE IS NOT. It does not claim the field mechanism is generic. Two
fields can share an abstraction that is secretly bespoke, and quantity and
preparation both resolve to a single scalar answer — an interface fitting
exactly those two proves very little. That claim is
`tests/test_the_rule_of_three_fields.py`, and it is deliberately a separate
file so that "the contract passes" and "the mechanism is generic" cannot be
confused for one another.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from core import semantic_fields as sf
from core.semantics import ClarificationAttribute


def _source_files():
    root = pathlib.Path(__file__).resolve().parent.parent
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", ".venv/", "alembic/", "scripts/")):
            continue
        yield rel, path


# ── every field is registered, and declares everything ──────────────────────

def test_every_registered_field_declares_the_whole_contract():
    """A spec with a hole is a field whose behaviour lives somewhere else."""
    assert sf.registered(), "the registry installed nothing"
    for key, spec in sf.registered().items():
        assert spec.value_space in sf.ValueSpace, key
        assert spec.pricing in sf.Pricing, key
        assert spec.evidence in sf.Evidence, key
        assert spec.activation in sf.Activation, key
        assert spec.settlement is sf.Settlement.RESOLVED_FIELDS, key
        assert spec.patch_type, key
        assert spec.caption, f"{key} has no presentation caption"


def test_an_unregistered_field_cannot_be_presented():
    """`ClarificationAttribute` is what COULD be asked; the registry is what
    CAN be. An interaction is where that distinction has to bite, because it
    is the thing persisted, rendered and answered."""
    from core.semantics import (ClarificationGroup, ClarificationInteraction,
                                ResponseType, UnresolvedField)

    # Constructible — the Phase-O seam depends on workout attributes existing
    # without a food edit.
    orphan = UnresolvedField(
        operation_id="op_1", revision=0, event_id="ex_bench",
        attribute=ClarificationAttribute.SET_COUNT,
        response_type=ResponseType.FREE_TEXT)

    # Not presentable.
    with pytest.raises(sf.ContractViolation):
        ClarificationInteraction(
            interaction_id="ix", operation_id="op_1", revision=0,
            groups=(ClarificationGroup(event_id="ex_bench", label="Bench",
                                       fields=(orphan,)),))


# ── unsupported semantics cannot be emitted ─────────────────────────────────

def test_a_field_that_prices_by_identity_must_speak_the_resolver_s_words():
    """MEASURED, NOT HYPOTHETICAL. `breaded` and `plain` were proposed for
    B-1.5 and are inert — asked, answered, and no number moves."""
    from skills.nutrition.validators import _PREPARATIONS

    with pytest.raises(sf.ContractViolation) as caught:
        sf.register(sf.FieldSpec(
            attribute=ClarificationAttribute.SERVING_BASIS,
            value_space=sf.ValueSpace.ENUMERATED,
            patch_type="set_serving_basis",
            pricing=sf.Pricing.IDENTITY,
            evidence=sf.Evidence.ONTOLOGY,
            vocabulary=("breaded", "plain"),
            # The domain declares what it can act on — core calls this and
            # understands nothing about it.
            supported_vocabulary=lambda: _PREPARATIONS,
            caption="Basis"))
    assert "breaded" in str(caught.value)


def test_the_registered_preparation_vocabulary_is_actually_actionable():
    """The live check, over what is really registered rather than a fixture."""
    from skills.nutrition.validators import _PREPARATIONS

    spec = sf.spec_for(ClarificationAttribute.PREPARATION)
    assert set(spec.vocabulary) <= set(_PREPARATIONS)
    assert spec.vocabulary, "preparation registered an empty vocabulary"


def test_an_unknown_patch_type_is_refused():
    with pytest.raises(sf.ContractViolation):
        sf.register(sf.FieldSpec(
            attribute=ClarificationAttribute.PACKAGE_SIZE,
            value_space=sf.ValueSpace.MEASURED,
            patch_type="set_package_size_someday",
            pricing=sf.Pricing.NONE, evidence=sf.Evidence.ONTOLOGY,
            caption="Size"))


def test_two_fields_cannot_both_decide_the_amount():
    with pytest.raises(sf.ContractViolation):
        sf.register(sf.FieldSpec(
            attribute=ClarificationAttribute.PACKAGE_SIZE,
            value_space=sf.ValueSpace.MEASURED,
            patch_type="set_consumed_fraction",
            pricing=sf.Pricing.AMOUNT, evidence=sf.Evidence.ONTOLOGY,
            caption="Size"))


def test_a_conditional_field_must_declare_its_predicate_as_data():
    """B-1.6's shape, refused early. `if fried: ask_oil()` in a producer is
    exactly what an undeclared predicate becomes."""
    with pytest.raises(sf.ContractViolation):
        sf.register(sf.FieldSpec(
            attribute=ClarificationAttribute.PACKAGE_SIZE,
            value_space=sf.ValueSpace.MEASURED,
            patch_type="set_consumed_fraction",
            pricing=sf.Pricing.NONE, evidence=sf.Evidence.ONTOLOGY,
            activation=sf.Activation.CONDITIONAL, caption="Size"))


def test_one_attribute_cannot_have_two_specs():
    with pytest.raises(sf.ContractViolation):
        sf.register(sf.FieldSpec(
            attribute=ClarificationAttribute.PREPARATION,
            value_space=sf.ValueSpace.ENUMERATED,
            patch_type="set_preparation", pricing=sf.Pricing.NONE,
            evidence=sf.Evidence.ONTOLOGY, vocabulary=("grilled",),
            caption="Preparation again"))


# ── there is no second settlement authority ─────────────────────────────────

def test_settlement_has_exactly_one_member():
    """`ResolvedFields` is the settlement boundary. The enum exists so adding
    a second way is a visible, arguable change to this contract rather than a
    function someone writes beside it."""
    assert [m.value for m in sf.Settlement] == ["resolved_fields"]


def test_there_is_no_multiplier_pricing():
    """A preparation factor applied to calories is a second opinion about
    nutrition held by an operation with no business holding one — the defect
    B-1.75 deleted on the quantity side. A field that wants to move a number
    changes WHICH FOOD we ask about."""
    assert "multiplier" not in {m.value for m in sf.Pricing}


def test_settlement_takes_resolved_fields_and_nothing_narrower():
    """`pricing_patch(held)` was replaced by `resolved_fields(held)` for a
    reason: the next field would have added `preparation_patch()` beside it,
    and B-2 would have become a pile of field-specific extractors inside the
    coordinator."""
    import inspect

    from core import b1_quantity_operation as ops

    params = inspect.signature(ops.settle).parameters
    assert "resolved" in params, "settle stopped taking the resolved state"
    assert "patch" not in params, (
        "settle takes a single extracted patch again — that is the shape "
        "field-specific settlement helpers grow back from")
    assert not hasattr(ops, "pricing_patch"), \
        "pricing_patch came back; use ResolvedFields"


# ── source ratchets over the patterns that must not return ──────────────────

#: Extractors that must not come back. `pricing_patch` existed and was right
#: while quantity was the only actionable field; the others are the shapes it
#: would have grown into once there were two.
_BANNED_EXTRACTORS = ("pricing_patch", "preparation_patch", "quantity_patch",
                      "variant_patch", "fraction_patch")


def test_no_field_specific_settlement_extractor_returns():
    """AST, NOT SUBSTRING.

    A substring scan cannot tell code from prose, and the first thing it
    flagged was `ResolvedFields`' own docstring explaining what it replaced.
    A ratchet that punishes writing down WHY pressures the next author to
    delete the explanation, which costs more than the ratchet is worth. This
    looks for definitions and calls.
    """
    offenders = []
    for rel, path in _source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:                       # pragma: no cover
            continue
        for node in ast.walk(tree):
            name = ""
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
            elif isinstance(node, ast.Call):
                name = (getattr(node.func, "id", "")
                        or getattr(node.func, "attr", ""))
            if name in _BANNED_EXTRACTORS:
                offenders.append(f"{rel}:{node.lineno} {name}")
    assert not offenders, (
        f"{offenders} — field-specific extraction in the coordinator. "
        f"Settlement takes the whole ResolvedFields state and the domain "
        f"reads what it needs; one extractor per field is what B-2 becomes "
        f"if this is allowed back")


def test_no_module_invents_a_field_attribute_outside_the_registry():
    """Every `ClarificationAttribute.X` referenced in production code must be
    a registered field — reaching for an attribute the system cannot serve is
    how a half-built field ships."""
    seen = set()
    for rel, path in _source_files():
        if rel in ("core/semantics.py", "core/semantic_fields.py"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:                       # pragma: no cover
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "ClarificationAttribute"):
                seen.add(node.attr)
    unregistered = {
        name for name in seen
        if not sf.is_registered(getattr(ClarificationAttribute, name).value)}
    assert not unregistered, (
        f"{sorted(unregistered)} are used in production code but not "
        f"registered — a field the system cannot serve")


def test_nutrition_is_never_scaled_by_a_preparation_factor():
    """The arithmetic that must never appear. Searched as source rather than
    asserted behaviourally, because the point is that nobody writes it."""
    banned = ("preparation_multiplier", "prep_factor", "PREPARATION_FACTOR",
              "fried_multiplier", "cooking_factor")
    offenders = []
    for rel, path in _source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        offenders += [f"{rel}:{b}" for b in banned if b in text]
    assert not offenders, (
        f"{offenders} — preparation changes the canonical IDENTITY sent to "
        f"the resolver; it does not adjust the resolver's answer")


# ── item 5: the two gates owed before B-1.6 broadens ────────────────────────

def test_the_same_attribute_can_coexist_across_events():
    """chicken.quantity and rice.quantity are different fields.

    Field identity is operation:event:attribute:revision, so two foods raising
    the SAME attribute produce two ids and the held map keeps both. Pinned
    because B-2 depends on it entirely, and the failure mode — one silently
    overwriting the other — is a lost meal that looks like a logged one.
    """
    from decimal import Decimal

    from core.b1_quantity_operation import resolved_fields
    from core.semantics import (CanonicalQuantity, Dimension, Provenance,
                                SetQuantity)

    def amount(event, grams):
        return SetQuantity(
            event_id=event, field_id=f"op:{event}:quantity:0",
            quantity=CanonicalQuantity(amount=Decimal(grams), unit_id="g",
                                       dimension=Dimension.MASS,
                                       grams=Decimal(grams)),
            provenance=Provenance.USER_SELECTED)

    held = {p.field_id: p for p in (amount("food_chicken", "174"),
                                    amount("food_rice", "150"))}
    assert len(held) == 2, "one food's answer overwrote the other"

    resolved = resolved_fields(held)
    assert len(resolved.of_type("set_quantity")) == 2
    assert resolved.event_ids == ("food_chicken", "food_rice")
    # PER EVENT, which is how B-2 settles.
    assert resolved.for_event("food_rice").quantity.quantity.grams \
        == Decimal("150")


def test_collapsing_two_events_to_one_answer_is_loud():
    """The B-2 landmine, defused.

    `.quantity` returned `found[0]` — correct for one food and silently wrong
    for two: it would price the chicken and drop the rice without a word. It
    cannot fire in B-1.5, which asks about one event by construction, so this
    is here for the day it can.
    """
    from decimal import Decimal

    from core.b1_quantity_operation import resolved_fields
    from core.semantics import (CanonicalQuantity, Dimension, Provenance,
                                SetQuantity)

    def amount(event):
        return SetQuantity(
            event_id=event, field_id=f"op:{event}:quantity:0",
            quantity=CanonicalQuantity(amount=Decimal("1"), unit_id="g",
                                       dimension=Dimension.MASS,
                                       grams=Decimal("1")),
            provenance=Provenance.USER_SELECTED)

    both = resolved_fields({p.field_id: p
                            for p in (amount("food_a"), amount("food_b"))})
    with pytest.raises(ValueError, match="collapse"):
        _ = both.quantity


def test_core_does_not_import_any_domain():
    """GENERIC INFRASTRUCTURE MUST NOT KNOW A DOMAIN'S PRIVATES.

    `core.semantic_fields` imported `skills.nutrition.validators._PREPARATIONS`
    — core reaching into one domain's PRIVATE detail, which would make every
    future domain either a nutrition import or an exception. Core now enforces
    THAT an identity-pricing field declares how its vocabulary is validated;
    the domain supplies WHAT that means, and registration lives with the
    domain that owns the semantics.
    """
    import ast as _ast
    import pathlib as _pathlib

    source = _pathlib.Path(sf.__file__).read_text(encoding="utf-8")
    tree = _ast.parse(source)
    imported = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, _ast.Import):
            imported.update(a.name for a in node.names)
    domain = {m for m in imported if m.split(".")[0] in ("skills", "handlers")}
    assert not domain, (
        f"core.semantic_fields imports {sorted(domain)} — registration belongs "
        f"in the domain that owns the semantics; core names domains only in "
        f"_DOMAIN_REGISTRARS")


def test_an_identity_priced_field_must_declare_how_its_vocabulary_is_checked():
    """Core cannot know what is actionable for a domain it does not import, so
    it requires the field to say."""
    with pytest.raises(sf.ContractViolation, match="supported_vocabulary"):
        sf.register(sf.FieldSpec(
            attribute=ClarificationAttribute.SERVING_BASIS,
            value_space=sf.ValueSpace.ENUMERATED,
            patch_type="set_serving_basis",
            pricing=sf.Pricing.IDENTITY,
            evidence=sf.Evidence.ONTOLOGY,
            vocabulary=("grilled",),
            caption="Basis"))
