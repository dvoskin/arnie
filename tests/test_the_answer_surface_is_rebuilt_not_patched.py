"""B-1.6b — THE PRODUCER HALF: what the user actually sees change.

B-1.6a made activation a state transition in STORAGE. A field could become
active, become inactive, and have its answer retracted, and none of it reached
the screen. This is the half where the answer surface itself is regenerated.

THE CLAIM THAT NEEDED ITS OWN GATE: removal must happen ON THE WIRE. Marking a
field inactive in storage while the client keeps rendering its chip leaves a
tappable control for a question the system no longer has — and a tap on it is
an answer to nothing. `yes -> amount opens -> no` must return an interaction
in which the amount field is PHYSICALLY ABSENT.

AND PERSISTENCE MUST ROUND-TRIP. A rebuilt interaction that exists only in the
answer turn's memory is one a reload cannot reproduce, and reload is the
normal case: a relaunched app, a second device, another worker. So the gate is
reconcile -> rebuild -> persist -> RELOAD -> wire_payload, not
reconcile -> rebuild -> wire_payload.
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from core import field_activation as fa
from core import interaction_generation as gen
from core import semantic_fields as sf
from core.b1_quantity_operation import wire_payload_for
from core.semantics import (CanonicalQuantity, ClarificationAttribute,
                            ClarificationGroup, ClarificationInteraction,
                            Dimension, SetAddedFatAmount, SetAddedFatPresent,
                            SetQuantity, UnresolvedField)

PRESENT = ClarificationAttribute.ADDED_FAT_PRESENT.value
AMOUNT = ClarificationAttribute.ADDED_FAT_AMOUNT.value
OP = "chat_quantity:26:ios:ABC"
EVENT = "food_item_1"


@pytest.fixture(autouse=True)
def _installed():
    sf._ensure_installed()


def _interaction(attributes, revision=0):
    fields = tuple(gen._field_for(a, operation_id=OP, revision=revision,
                                  event_id=EVENT) for a in attributes)
    return ClarificationInteraction(
        interaction_id="ix_1", operation_id=OP, revision=revision,
        introduction="How much chicken?",
        groups=(ClarificationGroup(event_id=EVENT, label="Chicken",
                                   fields=fields),))


def _present(value: bool, revision=0):
    return SetAddedFatPresent(event_id=EVENT,
                              field_id=f"{OP}:{EVENT}:{PRESENT}:{revision}",
                              present=value)


def _amount(revision=0):
    return SetAddedFatAmount(
        event_id=EVENT, field_id=f"{OP}:{EVENT}:{AMOUNT}:{revision}",
        quantity=CanonicalQuantity(amount=Decimal("1"), unit_id="tbsp",
                                   dimension=Dimension.VOLUME))


def _quantity(revision=0):
    return SetQuantity(
        event_id=EVENT, field_id=f"{OP}:{EVENT}:quantity:{revision}",
        quantity=CanonicalQuantity(amount=Decimal("120"), unit_id="g",
                                   dimension=Dimension.MASS))


def _rebuild(previous, held, previously_active):
    reconciliation = fa.reconcile(
        previously_active=previously_active,
        state=fa.state_from({"food": "Chicken"}, held),
        answered_by_field=held,
        attribute_of_field=fa.attribute_of_field_id)
    for field_id in reconciliation.retracted:
        held.pop(field_id, None)
    return gen.next_generation(previous=previous,
                               reconciliation=reconciliation,
                               answered=held), reconciliation, held


# ── addition ───────────────────────────────────────────────────────────────

def test_a_newly_active_field_appears_on_the_wire():
    previous = _interaction([PRESENT])
    held = {_present(True).field_id: _present(True)}
    rebuilt, _, _ = _rebuild(previous, held, [PRESENT])

    assert rebuilt is not None
    wire = wire_payload_for(rebuilt, locale="en")
    shown = [f["attribute"] for g in wire["groups"] for f in g["fields"]]
    assert AMOUNT in shown, f"the dependent field never reached the client: {shown}"


def test_fields_are_built_from_the_spec_not_per_attribute():
    """A per-attribute branch in the producer would make it a second place
    that knows what a field IS, and the next field would add the next
    branch."""
    field = gen._field_for(PRESENT, operation_id=OP, revision=0,
                           event_id=EVENT)
    assert {o.label for o in field.options} == {"Yes", "No"}
    assert {o.patch.present for o in field.options} == {True, False}
    assert sf.spec_for(PRESENT).vocabulary == ("yes", "no"), (
        "the options no longer come from the registered vocabulary")

    # MEASURED carries no vocabulary, so it must be free text rather than an
    # empty select — C15's rule, reached generically.
    measured = gen._field_for(AMOUNT, operation_id=OP, revision=0,
                              event_id=EVENT)
    assert measured.options == ()
    assert measured.response_type.value == "free_text_fallback"


# ── ⭐ REMOVAL ON THE WIRE, not merely in storage ──────────────────────────

def test_a_retracted_field_is_physically_absent_from_the_new_interaction():
    """yes -> amount opens -> no. The amount chip must be GONE, not greyed,
    not marked inactive — a tappable control for a question the system no
    longer has is a tap that answers nothing."""
    opened = _interaction([PRESENT, AMOUNT], revision=1)
    held = {_present(True, 1).field_id: _present(True, 1),
            _amount(1).field_id: _amount(1)}

    held[_present(True, 1).field_id] = _present(False, 1)   # "actually, no oil"
    rebuilt, reconciliation, held = _rebuild(opened, held, [PRESENT, AMOUNT])

    assert AMOUNT in reconciliation.newly_inactive
    assert rebuilt is not None
    wire = wire_payload_for(rebuilt, locale="en")
    shown = [f["attribute"] for g in wire["groups"] for f in g["fields"]]
    assert AMOUNT not in shown, (
        f"the retracted field is still on the wire: {shown} — the client "
        f"would keep rendering a chip for a question that no longer exists")
    assert not any(AMOUNT in f["field_id"]
                   for g in wire["groups"] for f in g["fields"])
    assert not any(AMOUNT in fa.attribute_of_field_id(k, p)
                   for k, p in held.items()), "the value survived in storage"


# ── revision semantics ─────────────────────────────────────────────────────

def test_one_shape_change_is_exactly_one_revision_bump():
    previous = _interaction([PRESENT], revision=4)
    held = {_present(True, 4).field_id: _present(True, 4)}
    rebuilt, _, _ = _rebuild(previous, held, [PRESENT])
    assert rebuilt.revision == 5


def test_every_rendered_field_is_rebuilt_under_the_new_revision():
    """A survivor carried forward at its old revision would be a
    mixed-generation interaction — half the chips addressing a generation
    that no longer exists."""
    previous = _interaction(["quantity", PRESENT], revision=2)
    held = {_present(True, 2).field_id: _present(True, 2)}
    rebuilt, _, _ = _rebuild(previous, held, ["quantity", PRESENT])

    for group in rebuilt.groups:
        for field in group.fields:
            assert field.revision == rebuilt.revision
            assert field.field_id.endswith(f":{rebuilt.revision}")


def test_a_mixed_generation_interaction_cannot_be_constructed():
    """The guarantee is structural, not a convention this module follows."""
    stale = UnresolvedField(operation_id=OP, revision=0, event_id=EVENT,
                            attribute=ClarificationAttribute.QUANTITY)
    with pytest.raises(ValueError):
        ClarificationInteraction(
            interaction_id="ix_1", operation_id=OP, revision=1,
            groups=(ClarificationGroup(event_id=EVENT, label="Chicken",
                                       fields=(stale,)),))


def test_a_value_change_without_a_shape_change_does_not_bump():
    """`revision` means "answer-surface generation". If any mutation moved
    it, every stale-tap rejection would race the user's own typing."""
    previous = _interaction(["quantity"], revision=7)
    held = {_quantity(7).field_id: _quantity(7)}
    rebuilt, reconciliation, _ = _rebuild(previous, held, ["quantity", PRESENT])
    # nothing activated or deactivated: quantity was answered, that is all
    assert not reconciliation.changed
    assert rebuilt is None, "a value change rebuilt the surface"


# ── no transient question ──────────────────────────────────────────────────

def test_present_yes_with_the_amount_already_known_asks_nothing():
    """Active-but-RESOLVED never renders. A produced-then-withdrawn question
    is a visible flicker and, worse, a chip a fast user can tap."""
    previous = _interaction([PRESENT], revision=0)
    held = {_present(True).field_id: _present(True),
            _amount().field_id: _amount()}
    rebuilt, reconciliation, _ = _rebuild(previous, held, [PRESENT])

    assert AMOUNT in reconciliation.newly_active
    shown = [f["attribute"] for g in wire_payload_for(rebuilt, locale="en")["groups"]
             for f in g["fields"]] if rebuilt else []
    assert AMOUNT not in shown, (
        f"the amount was already known and was asked anyway: {shown}")


# ── determinism ────────────────────────────────────────────────────────────

def test_rendered_order_is_topological_and_stable():
    assert gen.renderable(active={AMOUNT, "quantity", PRESENT},
                          resolved_attributes=()) == (
        "quantity", PRESENT, AMOUNT)
    for _ in range(5):
        assert gen.renderable(active={AMOUNT, PRESENT},
                              resolved_attributes=()) == (PRESENT, AMOUNT)


# ── ⭐ PERSISTENCE ROUND TRIP ──────────────────────────────────────────────

def test_the_rebuilt_interaction_survives_a_reload():
    """reconcile -> rebuild -> persist -> RELOAD -> wire_payload.

    Producer state that exists only in the answer turn's memory is state a
    reload cannot reproduce — and reload is the normal case: a relaunched app,
    a second device, another worker picking up the operation.
    """
    previous = _interaction([PRESENT], revision=0)
    held = {_present(True).field_id: _present(True)}
    rebuilt, _, _ = _rebuild(previous, held, [PRESENT])

    stored = json.dumps({"interaction": rebuilt.to_payload()})
    reloaded = ClarificationInteraction.from_payload(
        json.loads(stored)["interaction"])

    assert wire_payload_for(reloaded, locale="en") == \
        wire_payload_for(rebuilt, locale="en"), (
        "the wire payload changed across a persist/reload cycle — some part "
        "of the answer surface exists only in memory")
    assert reloaded.revision == rebuilt.revision


def test_a_stale_tap_from_the_previous_generation_finds_nothing():
    """The rejection is structural: `field_id` embeds the revision, so a tap
    carrying the old one addresses a field the new interaction does not
    have."""
    previous = _interaction([PRESENT], revision=0)
    held = {_present(True).field_id: _present(True)}
    rebuilt, _, _ = _rebuild(previous, held, [PRESENT])

    with pytest.raises(KeyError):
        rebuilt.field(f"{OP}:{EVENT}:{PRESENT}:0")      # the old generation


# ── the producer must not recompute activation ─────────────────────────────

def test_the_producer_consumes_reconciliation_and_never_recomputes_it():
    """If it re-evaluated, `active_when` would be advisory and "when is this
    asked" would have two owners — the defect B-1.6a exists to remove,
    reintroduced one layer up."""
    import ast
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent
              / "core" / "interaction_generation.py").read_text(encoding="utf-8")
    called = {getattr(n.func, "attr", "") or getattr(n.func, "id", "")
              for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)}
    assert "active_attributes" not in called, (
        "the producer recomputes activation instead of consuming the "
        "reconciliation it was given")
    assert "reconcile" not in called
