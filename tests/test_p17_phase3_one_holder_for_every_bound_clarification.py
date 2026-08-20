"""⛔ P17 PHASE 3 / CF14 — ONE HOLDER FOR EVERY BOUND CLARIFICATION.

The holder was always general: it holds a product snapshot against a canonical
operation and does not care which question is open. Only the GATE was
quantity-shaped, so a bound scan whose open question was PREPARATION took the
refusal path — and the user lost the exact label they had just scanned, which
is the whole point of scanning.

This file proves the gate, which is where CF9 became CF14. The holder's own
durability is Phase 2's file; the answer path is B-1's.
"""
from types import SimpleNamespace

import pytest

from core.scan_authority import (MATERIAL_SETTLEMENT_FIELDS, QUANTITY_FIELDS,
                                 bound_ask_subject, quantity_only_subject)
from core.turns.models import FoodSubject


def _plan(*subjects):
    """`bound_ask_subject` reads exactly one attribute off the plan, so the
    plan is a stub and the SUBJECTS are the real type — the gate's rules are
    about subject shape, and a real TurnPlan would add construction noise
    without making the claim stronger."""
    return SimpleNamespace(food_subjects=tuple(subjects))


def _sub(*open_fields, consumed=True, name="Barebells Caramel Cashew"):
    return FoodSubject(name=name, role="interpreted", key="k",
                       consumed=consumed, open_fields=tuple(open_fields))


@pytest.mark.parametrize("field", sorted(MATERIAL_SETTLEMENT_FIELDS))
def test_every_material_settlement_field_opens_a_bound_ask(field):
    """⛔ CF14. Each of these, alone on one consumed product, is an ask that
    HOLDS the snapshot — not a refusal. Before Phase 3 only `quantity`
    qualified, so a scanned bar with an open preparation question was turned
    away with its label still in hand."""
    sub = bound_ask_subject(_plan(_sub(field)))
    assert sub is not None, (
        f"{field!r} is a material settlement field and did not open a bound "
        f"ask — the scanned snapshot is lost to a refusal")


def test_identity_is_answered_by_the_snapshot_and_never_asked():
    """⛔⛔ THE SALTY PEANUT INVARIANT, IN THE GATE. A bound ask that offered
    identity would let prose overwrite the label of the product the user
    actually scanned. Identity conflicts are decided by the authority — ask
    or refuse — and never by opening a question the snapshot already
    answers."""
    assert "food_identity" not in MATERIAL_SETTLEMENT_FIELDS
    assert bound_ask_subject(_plan(_sub("food_identity"))) is None
    assert bound_ask_subject(_plan(_sub("quantity", "food_identity"))) is None, (
        "one identity field among material ones still opened an ask — the "
        "set is checked per field, and every field must qualify")


def test_an_inferred_question_still_refuses_rather_than_asks():
    """Unchanged by CF14, and load-bearing: the producer spells an INFERRED
    field `quantity?`, and a guess about what the user was asked is not a
    basis for holding their scanned product against a durable question."""
    assert bound_ask_subject(_plan(_sub("quantity?"))) is None
    assert bound_ask_subject(_plan(_sub("preparation?"))) is None


def test_a_product_nobody_said_they_ate_opens_nothing():
    """CF5c-B2 survives the widening: consumption is a precondition of the
    ask, not one of the fields it may ask about."""
    assert bound_ask_subject(_plan(_sub("quantity", consumed=False))) is None
    assert bound_ask_subject(_plan(_sub("preparation", consumed=False))) is None


def test_two_food_subjects_never_open_a_single_product_bound_ask():
    """A bound ask names ONE product and holds ONE snapshot. Two subjects is
    a multi-food turn, which the authority discards rather than binding."""
    assert bound_ask_subject(_plan(_sub("quantity"),
                                   _sub("preparation", name="Oatmeal"))) is None


def test_the_cf9_case_is_still_expressible_without_a_second_copy():
    """`quantity_only_subject` is the same gate with a narrower field set —
    not a parallel implementation of the subject-shape rules, which is how
    the two would drift apart."""
    assert QUANTITY_FIELDS < MATERIAL_SETTLEMENT_FIELDS
    assert quantity_only_subject(_plan(_sub("quantity"))) is not None
    assert quantity_only_subject(_plan(_sub("preparation"))) is None
    assert bound_ask_subject(_plan(_sub("preparation"))) is not None
