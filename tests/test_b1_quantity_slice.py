"""B-1: one item, one mass-quantity field — the first authoritative slice.

What is measured here, and why each one is load-bearing:

  * THE PREDICATE DECLINES BY DEFAULT. Every clause is a thing B-1 has not
    built. A decline costs nothing (the turn stays legacy, exactly as today);
    a wrong claim strands a meal mid-clarification.
  * OPTIONS COME FROM EVIDENCE, not from tiers. The bracket offered is the one
    the ontology already computed to decide the question was worth asking.
  * NO NEAR-DUPLICATES. `4.8 / 5.0 / 5.2` was three chips carrying one answer.
  * CHIP AND TYPED CONVERGE on one patch type, differing only in provenance —
    a tap is not the user's own figure (C14, and the 2026-08-04 disclosure
    defect).
  * STALE, FOREIGN AND INVALID ANSWERS FAIL CLOSED. A tap on last turn's chip
    addresses a field this interaction does not have; it is refused, never
    applied to whatever looks closest.
  * TERMINAL OWNERSHIP (C10). Once the operation exists there is no path back
    to legacy — not on a cancelled rollout, not on an unparseable answer.
"""
from decimal import Decimal

import pytest

from core.clarification_answer import Outcome, answer_from_chip, answer_from_text
from core.semantics import (CandidateSource, CandidateValue, Dimension,
                            Provenance, ResponseType, SetQuantity)
from skills.nutrition import quantity_clarification as qc
from skills.nutrition import quantity_rollout as qr
from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
from skills.nutrition.staging import (FoodIdentity, QuantityIntent,
                                      StagedFoodItem)

OP, REV = "chat:144:t_1", 0


def _ambiguity(field_name="estimated_mass_g", kind=AmbiguityType.CONSUMED_QUANTITY,
               score=2.0, item_id="si_1"):
    return FoodAmbiguity(ambiguity_id=f"amb_{field_name}", staged_item_id=item_id,
                         ambiguity_type=kind, field_name=field_name,
                         materiality_score=score, calorie_span=180.0)


def _item(*, name="chicken breast", stated=False, ambiguities=None,
          vague="some"):
    return StagedFoodItem(
        staged_item_id="si_1", original_text=f"{vague} {name}",
        identity=FoodIdentity(canonical_name=name),
        quantity=(QuantityIntent(stated_amount=5.0, stated_unit="oz")
                  if stated else QuantityIntent(descriptor=vague)),
        vague_measure=vague,
        ambiguities=tuple(ambiguities if ambiguities is not None
                          else (_ambiguity(),)))


class _Decision:
    def __init__(self, items):
        self.staged_items = tuple(items)


def _eligible_decision(**kw):
    return _Decision([_item(**kw)])


def _candidates(*grams_and_sources):
    out = []
    for cid, grams, source, prob, conf in grams_and_sources:
        prov = (Provenance.USER_HISTORY if source is CandidateSource.USER_HISTORY
                else Provenance.ONTOLOGY)
        out.append(CandidateValue(
            candidate_id=cid,
            semantic_value=qc._quantity(grams, provenance=prov,
                                        confidence=conf),
            source=source, probability=prob, confidence=conf))
    return tuple(out)


REAL = _candidates(
    ("ont_low", 85.0, CandidateSource.ONTOLOGY, 0.2, 0.6),
    ("hist_last", 141.7, CandidateSource.USER_HISTORY, 0.55, 0.9),
    ("ont_high", 226.0, CandidateSource.ONTOLOGY, 0.3, 0.6),
)


def _interaction(candidates=REAL, food="chicken breast"):
    item = _item(name=food)
    field = qc.quantity_field(operation_id=OP, revision=REV, item=item)
    options = qc.select(candidates, field=field, food_name=food)
    return qc.build_interaction(operation_id=OP, revision=REV, item=item,
                                options=options,
                                introduction="How much chicken breast?")


def _field_id(ix):
    return ix.groups[0].fields[0].field_id


# ── eligibility ──────────────────────────────────────────────────────────────

def test_the_canonical_shape_is_eligible():
    e = qc.is_eligible(_eligible_decision(), message="I had some chicken breast",
                       client_capable=True)
    assert e.ok, e.reason
    assert e.item.identity.canonical_name == "chicken breast"


@pytest.mark.parametrize("kw,message,expected", [
    ({}, "actually make that 8oz", qc.Ineligible.CORRECTION_TURN),
    ({"stated": True}, "I had 5oz of chicken", qc.Ineligible.QUANTITY_ALREADY_STATED),
    ({"ambiguities": ()}, "I had some chicken", qc.Ineligible.NO_QUANTITY_QUESTION),
    ({"ambiguities": (_ambiguity("variant", AmbiguityType.PRODUCT_VARIANT),)},
     "I had a Core Power", qc.Ineligible.IDENTITY_AMBIGUOUS),
    ({"ambiguities": (_ambiguity("preparation", AmbiguityType.PREPARATION),)},
     "I had some chicken", qc.Ineligible.PREPARATION_DEPENDENCY),
    ({"ambiguities": (_ambiguity("consumed_fraction", AmbiguityType.CONSUMED_QUANTITY),)},
     "I had some of it", qc.Ineligible.NOT_MASS),
])
def test_every_out_of_scope_shape_declines_with_its_reason(kw, message, expected):
    """A typed reason, not a bool: 'how often, and for what' is the
    measurement that sizes B-1.5 and B-2."""
    e = qc.is_eligible(_eligible_decision(**kw), message=message,
                       client_capable=True)
    assert not e.ok
    assert e.reason is expected


def test_a_multi_item_meal_is_not_b1():
    d = _Decision([_item(name="chicken breast"), _item(name="white rice")])
    assert qc.is_eligible(d, message="chicken and rice",
                          client_capable=True).reason is \
        qc.Ineligible.MULTIPLE_ITEMS


def test_an_incapable_client_is_excluded_not_downgraded():
    """Rendering canonical options as prose for a client that cannot read the
    payload would keep the sentence parser alive INSIDE the replacement."""
    assert qc.is_eligible(_eligible_decision(), message="I had some chicken",
                          client_capable=False).reason is \
        qc.Ineligible.CLIENT_INCAPABLE


def test_an_unresolved_identity_is_not_b1():
    d = _Decision([StagedFoodItem(staged_item_id="si_1", original_text="something",
                                  identity=FoodIdentity(),
                                  ambiguities=(_ambiguity(),))])
    assert qc.is_eligible(d, message="I ate something",
                          client_capable=True).reason is \
        qc.Ineligible.IDENTITY_UNRESOLVED


# ── options are a projection of evidence ─────────────────────────────────────

def test_options_are_the_bracket_the_ontology_already_computed():
    ix = _interaction()
    options = ix.groups[0].fields[0].options
    assert [str(o.patch.quantity.grams) for o in options] == \
        ["85.0", "141.7", "226.0"], "the offered masses must be the evidence"
    assert [o.source for o in options] == [
        CandidateSource.ONTOLOGY, CandidateSource.USER_HISTORY,
        CandidateSource.ONTOLOGY]


def test_every_canonical_option_carries_a_typed_patch():
    for o in _interaction().groups[0].fields[0].options:
        assert isinstance(o.patch, SetQuantity)
        assert o.patch.quantity.dimension is Dimension.MASS
        assert o.adapter_built is False
        assert o.option_id, "a tap submits ids; an unidentified option is unanswerable"


def test_near_duplicates_are_suppressed():
    """`4.8 / 5.0 / 5.2` — three chips, one answer, no information gained."""
    crowded = _candidates(
        ("a", 136.0, CandidateSource.ONTOLOGY, 0.4, 0.6),
        ("b", 141.7, CandidateSource.USER_HISTORY, 0.55, 0.9),
        ("c", 147.0, CandidateSource.ONTOLOGY, 0.3, 0.6),
    )
    field = qc.quantity_field(operation_id=OP, revision=REV, item=_item())
    assert len(qc.select(crowded, field=field, food_name="chicken breast")) == 1


def test_at_most_three_numeric_options():
    many = _candidates(*[(f"c{i}", 50.0 * (i + 1), CandidateSource.ONTOLOGY,
                          0.3, 0.6) for i in range(6)])
    field = qc.quantity_field(operation_id=OP, revision=REV, item=_item())
    assert len(qc.select(many, field=field,
                         food_name="chicken breast")) <= qc.MAX_NUMERIC_OPTIONS


def test_no_candidates_becomes_an_explicit_free_text_fallback():
    """C15: never a blank select the client 'repairs' by parsing prose."""
    field = qc.quantity_field(operation_id=OP, revision=REV, item=_item(),
                              options=())
    assert field.response_type is ResponseType.FREE_TEXT_FALLBACK
    assert field.options == ()


def test_labels_are_rendered_last_and_never_carry_meaning():
    ix = _interaction()
    options = ix.groups[0].fields[0].options
    assert [o.label for o in options] == ["3 oz", "5 oz", "8 oz"], \
        "meat is answered in ounces, not grams — a question, not a chore"
    # The label is presentation: the meaning is the patch, and they differ.
    assert options[0].label == "3 oz"
    assert options[0].patch.quantity.grams == Decimal("85.0")


# ── the ten answer variants ──────────────────────────────────────────────────

def test_a_chip_tap_resolves_to_the_stored_patch():
    ix = _interaction()
    r = answer_from_chip(ix, field_id=_field_id(ix), option_id="opt_hist_last",
                         revision=REV)
    assert r.outcome is Outcome.APPLIED
    assert r.patch.quantity.grams == Decimal("141.7")
    assert r.patch.provenance is Provenance.USER_SELECTED


def test_a_typed_quantity_that_was_offered_produces_the_same_patch_type():
    ix = _interaction()
    r = answer_from_text(ix, field_id=_field_id(ix), text="5 oz",
                         food_name="chicken breast")
    assert r.outcome is Outcome.APPLIED
    assert isinstance(r.patch, SetQuantity)
    assert r.patch.provenance is Provenance.USER_STATED, \
        "typing it is a statement; tapping it is a selection (C14)"


def test_a_typed_quantity_that_was_never_offered_is_a_first_class_answer():
    """The typed path is not a fallback for people the chips failed."""
    ix = _interaction()
    r = answer_from_text(ix, field_id=_field_id(ix), text="about 6 ounces",
                         food_name="chicken breast")
    assert r.outcome is Outcome.APPLIED
    assert 160 < float(r.patch.quantity.grams) < 185
    assert r.patch.provenance is Provenance.USER_STATED


def test_a_stale_revision_is_refused_not_retargeted():
    ix = _interaction()
    r = answer_from_chip(ix, field_id=_field_id(ix), option_id="opt_hist_last",
                         revision=REV + 1)
    assert r.outcome is Outcome.REFUSED
    assert "revision" in r.reason


def test_a_foreign_field_is_refused():
    ix = _interaction()
    r = answer_from_chip(ix, field_id=f"{OP}:food_other:quantity:{REV}",
                         option_id="opt_hist_last", revision=REV)
    assert r.outcome is Outcome.REFUSED
    r2 = answer_from_text(ix, field_id="op_2:food_si_1:quantity:0", text="5 oz")
    assert r2.outcome is Outcome.REFUSED


def test_a_wrong_event_cannot_be_smuggled_through_an_option():
    """An option that patches another field is unconstructable (B-0c)."""
    field = qc.quantity_field(operation_id=OP, revision=REV, item=_item())
    from core.semantics import ClarificationOption
    foreign = ClarificationOption(
        label="5 oz", option_id="opt_x", field_id="op_1:food_rice:quantity:0",
        patch=SetQuantity(event_id="food_rice",
                          field_id="op_1:food_rice:quantity:0",
                          quantity=qc._quantity(141.7,
                                                provenance=Provenance.ONTOLOGY)))
    with pytest.raises(ValueError, match="mixed chip row, one level down"):
        qc.quantity_field(operation_id=OP, revision=REV, item=_item(),
                          options=(foreign,))


def test_an_invalid_option_id_is_refused():
    ix = _interaction()
    r = answer_from_chip(ix, field_id=_field_id(ix), option_id="opt_nope",
                         revision=REV)
    assert r.outcome is Outcome.REFUSED


def test_a_duplicate_tap_is_deterministic():
    """Same ids in, same patch out — idempotency starts by the answer being a
    pure function of the stored interaction."""
    ix = _interaction()
    a = answer_from_chip(ix, field_id=_field_id(ix), option_id="opt_ont_low",
                         revision=REV)
    b = answer_from_chip(ix, field_id=_field_id(ix), option_id="opt_ont_low",
                         revision=REV)
    assert a.patch == b.patch


def test_an_unparseable_answer_repairs_and_never_reaches_the_interpreter():
    ix = _interaction()
    r = answer_from_text(ix, field_id=_field_id(ix), text="it was fine thanks",
                         food_name="chicken breast")
    assert r.outcome is Outcome.REPAIR, \
        "an unparsed answer must ask again, not become a second meal"


def test_an_explicit_cancel_closes_the_operation():
    ix = _interaction()
    r = answer_from_text(ix, field_id=_field_id(ix), text="never mind",
                         food_name="chicken breast")
    assert r.outcome is Outcome.CANCELLED


def test_the_answer_outcomes_have_no_legacy_member():
    """C10, at the type level: there is no way to SAY 'fall back' here."""
    assert {o.value for o in Outcome} == {
        "applied", "cancelled", "repair", "refused"}


# ── the rollout gate ─────────────────────────────────────────────────────────

def test_ownership_is_refused_by_default(monkeypatch):
    for var in ("B1_QUANTITY_HALT", "B1_QUANTITY_ALLOWLIST",
                "B1_QUANTITY_PERCENT"):
        monkeypatch.delenv(var, raising=False)
    assert qr.may_take_ownership(144) is False
    assert qr.cohort_label(144) == "off"


def test_the_halt_outranks_the_allowlist(monkeypatch):
    """An allowlist entry that could override a halt is not a halt."""
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", "144")
    monkeypatch.setenv("B1_QUANTITY_HALT", "true")
    assert qr.may_take_ownership(144) is False
    assert qr.cohort_label(144) == "halted"


def test_widening_the_cohort_adds_users_and_never_swaps_them(monkeypatch):
    monkeypatch.delenv("B1_QUANTITY_HALT", raising=False)
    monkeypatch.setenv("B1_QUANTITY_PERCENT", "10")
    at_ten = {u for u in range(2000) if qr.in_cohort(u)}
    monkeypatch.setenv("B1_QUANTITY_PERCENT", "25")
    at_twentyfive = {u for u in range(2000) if qr.in_cohort(u)}
    assert at_ten and at_ten < at_twentyfive, \
        "widening must be monotonic, or users flap between two systems"


def test_the_b1_cohort_is_not_the_resolver_cohort(monkeypatch):
    """A shared salt would make B-1's 5% exactly the resolver's 5%, and every
    B-1 measurement would carry resolver-V2 as a hidden covariate."""
    from skills.nutrition.canary import bucket_for
    same = sum(1 for u in range(500)
               if bucket_for(u) == bucket_for(u, salt=qr.SALT))
    assert same < 25, f"{same}/500 buckets collide — the salts are not distinct"


def test_the_rollout_gate_has_no_continue_function():
    """C10 by absence: the gate answers 'may we START'. A `should_continue`
    would be read on the answer turn, and every way of acting on a False
    answer there loses a meal in flight."""
    assert not [n for n in dir(qr)
                if "continue" in n or "still" in n or "keep" in n]
