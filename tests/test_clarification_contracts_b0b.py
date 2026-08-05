"""B-0b: the typed clarification layer the legacy producers migrate onto.

The chip directive's target flow is
    unresolved field → candidates → deterministic selection → typed patches
    → rendered labels
and these types are its vocabulary. What is pinned here:

  * closed sets where free strings shipped bugs (attribute typos, ad-hoc
    response types, status drift);
  * field identity derived from SEMANTICS (operation/event/attribute/revision),
    never list position or display text;
  * every patch names its target and validates its value at construction;
  * chip taps and typed answers CONVERGE — same patch type, same boundary
    (C14 target);
  * the cross-domain seam: workout attributes exist without any food edit.
"""
from decimal import Decimal

import pytest

from core.semantics import (CandidateSource, CandidateValue, CanonicalQuantity,
                            ClarificationAttribute, ClarificationGroup,
                            ClarificationInteraction, ClarificationOption,
                            Dimension, Provenance, ResponseType, SelectEntity,
                            SelectProductVariant, SemanticPatch,
                            SetConsumedFraction, SetPreparation, SetQuantity,
                            SetServingBasis, UncertaintyEvidence,
                            UnresolvedField)


def _field(**kw):
    base = dict(operation_id="op_1", revision=3, event_id="food_chicken",
                attribute=ClarificationAttribute.QUANTITY)
    base.update(kw)
    return UnresolvedField(**base)


# ── field identity ───────────────────────────────────────────────────────────

def test_field_identity_derives_from_semantics_not_rendering():
    """Reordering a list or rewording a question must not change identity —
    the adapter's position+text ids are the defect, not the pattern."""
    f = _field()
    assert f.field_id == "op_1:food_chicken:quantity:3"
    assert _field().field_id == f.field_id, "identity must be deterministic"
    assert _field(revision=4).field_id != f.field_id, \
        "a new revision is a new question"


def test_a_field_without_its_owners_cannot_exist():
    with pytest.raises(ValueError):
        UnresolvedField(operation_id="", revision=0, event_id="e",
                        attribute=ClarificationAttribute.QUANTITY)
    with pytest.raises(ValueError):
        UnresolvedField(operation_id="op", revision=0, event_id="",
                        attribute=ClarificationAttribute.QUANTITY)


def test_attributes_are_a_closed_set():
    """`attribute="prepration"` was representable and silently unanswerable."""
    with pytest.raises(ValueError):
        _field(attribute="prepration")
    assert _field(attribute="preparation").attribute is \
        ClarificationAttribute.PREPARATION


def test_workout_attributes_exist_without_a_food_edit():
    """The Phase-O seam: onboarding workouts must not touch this file."""
    f = _field(event_id="ex_bench", attribute="set_count")
    assert f.attribute is ClarificationAttribute.SET_COUNT
    assert f.field_id == "op_1:ex_bench:set_count:3"


# ── patches ──────────────────────────────────────────────────────────────────

def test_every_patch_names_its_target():
    for cls, extra in ((SetQuantity, {"quantity": CanonicalQuantity(
                            amount=Decimal("5"), unit_id="oz",
                            dimension=Dimension.MASS, grams=Decimal("141.7"))}),
                       (SelectEntity, {"entity_id": "food.chicken"}),
                       (SetPreparation, {"preparation_id": "prep.grilled"})):
        with pytest.raises(ValueError):
            cls(event_id="", field_id="f", **extra)
        with pytest.raises(ValueError):
            cls(event_id="e", field_id="", **extra)


def test_a_quantity_patch_carries_dimensions_not_bare_numbers():
    with pytest.raises(ValueError, match="CanonicalQuantity"):
        SetQuantity(event_id="e", field_id="f", quantity=5)
    q = SetQuantity(event_id="e", field_id="f",
                    quantity=CanonicalQuantity(amount=Decimal("5"),
                                               unit_id="oz",
                                               dimension=Dimension.MASS,
                                               grams=Decimal("141.7")))
    assert q.quantity.dimension is Dimension.MASS


def test_consumed_fraction_bounds():
    ok = SetConsumedFraction(event_id="e", field_id="f",
                             fraction=Decimal("0.5"))
    assert ok.fraction == Decimal("0.5")
    for bad in (Decimal("0"), Decimal("1.5"), None):
        with pytest.raises(ValueError):
            SetConsumedFraction(event_id="e", field_id="f", fraction=bad)


def test_identity_patches_require_stable_ids():
    with pytest.raises(ValueError):
        SelectEntity(event_id="e", field_id="f", entity_id="")
    with pytest.raises(ValueError):
        SelectProductVariant(event_id="e", field_id="f", entity_id="")
    v = SelectProductVariant(event_id="e", field_id="f",
                             entity_id="off:3017620422003",
                             serving_id="bottle_14oz")
    assert v.serving_id == "bottle_14oz"
    with pytest.raises(ValueError):
        SetServingBasis(event_id="e", field_id="f", basis_id="")


def test_chip_and_text_answers_converge_on_one_patch_type():
    """C14 target: a tapped '5 oz' and a typed 'probably around five ounces'
    produce the SAME patch type, differing only in provenance."""
    quantity = CanonicalQuantity(amount=Decimal("5"), unit_id="oz",
                                 dimension=Dimension.MASS,
                                 grams=Decimal("141.7"))
    tapped = SetQuantity(event_id="e", field_id="f", quantity=quantity,
                         provenance=Provenance.USER_SELECTED)
    typed = SetQuantity(event_id="e", field_id="f", quantity=quantity,
                        provenance=Provenance.USER_STATED)
    assert type(tapped) is type(typed)
    assert tapped.provenance is not typed.provenance, \
        "provenance must survive convergence — a tap is not a statement"


# ── candidates and options ───────────────────────────────────────────────────

def test_candidates_carry_their_evidence():
    c = CandidateValue(candidate_id="h1", semantic_value=Decimal("141.7"),
                       source="user_history", probability=0.43,
                       confidence=0.9, evidence_ids=("fe_2810", "fe_2801"))
    assert c.source is CandidateSource.USER_HISTORY
    with pytest.raises(ValueError):
        CandidateValue(candidate_id="x", semantic_value=1,
                       source="vibes", probability=0.5, confidence=0.5)
    with pytest.raises(ValueError):
        CandidateValue(candidate_id="x", semantic_value=1,
                       source="ontology", probability=1.5, confidence=0.5)


def test_an_option_can_carry_the_authoritative_patch():
    """C10 target: the patch is the meaning; the label is presentation. The
    measurement adapter leaves patch=None because the legacy shapes never had
    one — that None is the gap being closed, and it stays visible."""
    f = _field()
    patch = SetQuantity(event_id=f.event_id, field_id=f.field_id,
                        quantity=CanonicalQuantity(amount=Decimal("5"),
                                                   unit_id="oz",
                                                   dimension=Dimension.MASS,
                                                   grams=Decimal("141.7")),
                        provenance=Provenance.USER_SELECTED)
    o = ClarificationOption(label="5 oz", option_id="opt_5oz",
                            field_id=f.field_id, patch=patch,
                            source=CandidateSource.USER_HISTORY)
    assert o.patch.quantity.grams == Decimal("141.7")
    legacy = ClarificationOption(label="Medium piece", value="113 g")
    assert legacy.patch is None


def test_groups_bind_options_to_one_event():
    """The structure that makes the mixed chip row unconstructable: fields sit
    inside their event's group, so 'Elite / Whole thing / 1 cup' cannot be one
    flat list."""
    fairlife = ClarificationGroup(
        event_id="food_fairlife", label="Fairlife",
        fields=(_field(event_id="food_fairlife",
                       attribute="product_variant"),
                _field(event_id="food_fairlife",
                       attribute="consumed_fraction")))
    rice = ClarificationGroup(
        event_id="food_rice", label="Rice",
        fields=(_field(event_id="food_rice"),))
    ix = ClarificationInteraction(interaction_id="ix_1", operation_id="op_1",
                                  revision=3, introduction="Which bottle, "
                                  "and how much?", groups=(fairlife, rice))
    assert [g.event_id for g in ix.groups] == ["food_fairlife", "food_rice"]
    with pytest.raises(ValueError):
        ClarificationInteraction(interaction_id="", operation_id="op",
                                 revision=0)


def test_free_text_fallback_is_explicit():
    """C15 target: a select with no options must SAY it fell back — never a
    blank row the client repairs by parsing prose."""
    assert ResponseType("free_text_fallback") is ResponseType.FREE_TEXT_FALLBACK
