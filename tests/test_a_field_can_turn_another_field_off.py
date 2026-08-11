"""B-1.6 — CONDITIONAL ACTIVATION, AND THE HALF THAT IS EASY TO SKIP.

Opening a dependent field is the obvious direction and the cheap one. The
expensive one is CLOSING it:

    "chicken, cooked in oil"   -> added_fat_amount opens
    "about a tablespoon"       -> answered
    "actually, no oil"         -> the amount must DIE, not merely disappear

Hiding the chip while `added_fat_amount=1 tbsp` stays in `answered` prices a
meal with fat the user just said was not there. That is a silent nutrition
corruption, and it is the specific failure these tests exist to make
impossible.

THE TWO RATCHETS ARE BOTH HERE, on purpose. `register()` refuses a CONDITIONAL
field with no predicate — an ADMISSION check that has existed since the
contract was written and had NO CONSUMER until this slice. A contract enforced
at one end with nothing reading the other is the shape of every instrument
that lied by silence in this codebase, so the consumer side is ratcheted too:
every registered conditional must actually be evaluated by the reconciler.
"""
from __future__ import annotations

import pytest

from core import field_activation as fa
from core import semantic_fields as sf
from decimal import Decimal

from core.semantics import (CanonicalQuantity, ClarificationAttribute, Dimension,
                            SetAddedFatAmount, SetAddedFatPresent,
                            SetPreparation, SetQuantity)

PRESENT = ClarificationAttribute.ADDED_FAT_PRESENT.value
AMOUNT = ClarificationAttribute.ADDED_FAT_AMOUNT.value


@pytest.fixture(autouse=True)
def _installed():
    sf._ensure_installed()


def _present(value: bool):
    return SetAddedFatPresent(event_id="food_item_1",
                              field_id=f"op:food_item_1:{PRESENT}:0",
                              present=value)


def _amount(revision: int = 0):
    return SetAddedFatAmount(
        event_id="food_item_1",
        field_id=f"op:food_item_1:{AMOUNT}:{revision}",
        quantity=CanonicalQuantity(amount=Decimal("1"), unit_id="tbsp",
                                   dimension=Dimension.VOLUME))


def _state(**resolved):
    return fa.ActivationState(item={"food": "Chicken"}, resolved=resolved)


# ── activation, both directions ────────────────────────────────────────────

def test_a_dependent_field_is_closed_until_its_dependency_is_true():
    """Unresolved is FALSE. "We have not asked whether there was oil" is not
    "there was oil", and a dependent field that opens on an unanswered
    question is a question asked about nothing."""
    assert AMOUNT not in fa.active_attributes(_state())
    assert AMOUNT not in fa.active_attributes(_state(**{PRESENT: _present(False)}))
    assert AMOUNT in fa.active_attributes(_state(**{PRESENT: _present(True)}))


def test_the_dependency_runs_one_way():
    """Presence must not depend on amount. A mutual pair is a question that
    silently never opens, which is why the graph is declared and checked."""
    assert sf.spec_for(PRESENT).depends_on == ()
    assert sf.spec_for(AMOUNT).depends_on == (PRESENT,)


def test_activation_is_the_same_however_the_value_arrived():
    """ORDER INDEPENDENCE — B-1.5 paid for this lesson on the answer path.

    A value from the original utterance, a chip, or typed text must produce
    the same TOPOLOGY, because the calculation is a function of resolved state
    and of nothing else.
    """
    from core.semantics import Provenance

    sets = []
    for source in (Provenance.USER_STATED, Provenance.USER_SELECTED,
                   Provenance.UNKNOWN):
        patch = SetAddedFatPresent(event_id="food_item_1",
                                   field_id=f"op:food_item_1:{PRESENT}:0",
                                   present=True, provenance=source)
        sets.append(fa.active_attributes(_state(**{PRESENT: patch})))
    assert len(set(sets)) == 1, (
        "the active set depended on WHERE the answer came from — conditional "
        "topology must be a function of resolved state alone")


def test_a_predicate_that_raises_does_not_open_the_field():
    """The same rule `derive_unresolved` follows: an activation we could not
    evaluate is not evidence that a question is needed."""
    class _Explodes(fa.Rule):
        def evaluate(self, state): raise ZeroDivisionError("boom")
        def attributes(self): return frozenset({PRESENT})

    spec = sf.spec_for(AMOUNT)
    sf._REGISTRY[AMOUNT] = type(spec)(**{**spec.__dict__,
                                         "active_when": _Explodes()})
    try:
        assert AMOUNT not in fa.active_attributes(
            _state(**{PRESENT: _present(True)}))
    finally:
        sf._REGISTRY[AMOUNT] = spec


# ── reconciliation: the three sets ─────────────────────────────────────────

def test_reconciliation_reports_what_turned_on_and_what_turned_off():
    on = fa.reconcile(previously_active=[PRESENT],
                      state=_state(**{PRESENT: _present(True)}))
    assert AMOUNT in on.newly_active
    assert PRESENT in on.still_active
    assert on.changed

    off = fa.reconcile(previously_active=[PRESENT, AMOUNT],
                       state=_state(**{PRESENT: _present(False)}))
    assert AMOUNT in off.newly_inactive
    assert off.changed


def test_nothing_changing_is_not_a_change():
    """`changed` drives the revision bump, so a false positive would
    invalidate every chip on the user's screen for no reason."""
    steady = fa.reconcile(previously_active=fa.active_attributes(_state()),
                          state=_state())
    assert not steady.changed
    assert not steady.newly_active and not steady.newly_inactive


def test_turning_the_dependency_off_retracts_the_answer_not_just_the_chip():
    """⭐ THE CORRUPTION THIS SLICE EXISTS TO PREVENT."""
    held = {_amount().field_id: _amount(),
            _present(True).field_id: _present(False)}
    reconciliation = fa.reconcile(
        previously_active=[PRESENT, AMOUNT],
        state=fa.state_from({"food": "Chicken"}, held),
        answered_by_field=held,
        attribute_of_field=fa.attribute_of_field_id)

    assert _amount().field_id in reconciliation.retracted, (
        "the amount survived its dependency going false — settlement would "
        "price fat the user just said was not there")


# ── settlement gates ───────────────────────────────────────────────────────

def test_settlement_refuses_a_value_whose_dependency_is_off():
    """The commit boundary re-checks independently, so an alternate caller or
    a future repair path cannot bypass the answer path's reconciliation."""
    answered = {_amount().field_id: _amount(),
                _present(True).field_id: _present(False)}
    with pytest.raises(fa.InactiveValueAtSettlement):
        fa.assert_settlement_is_consistent(item={"food": "Chicken"},
                                           answered=answered)


def test_settlement_refuses_an_active_required_field_with_no_answer():
    with pytest.raises(fa.UnresolvedActiveField):
        fa.assert_settlement_is_consistent(
            item={"food": "Chicken"},
            answered={_present(True).field_id: _present(True)},
            required=(AMOUNT,))


def test_a_consistent_payload_settles():
    answered = {_present(True).field_id: _present(True),
                _amount().field_id: _amount()}
    fa.assert_settlement_is_consistent(item={"food": "Chicken"},
                                       answered=answered, required=(AMOUNT,))


def test_settlement_is_unaffected_by_fields_that_were_never_active():
    """"Never asked" must not read as "retracted". The quantity/preparation
    pair carries no dependency and must settle exactly as before."""
    quantity = SetQuantity(event_id="food_item_1",
                           field_id="op:food_item_1:quantity:0",
                           quantity=CanonicalQuantity(amount=Decimal("120"), unit_id="g",
                                                     dimension=Dimension.MASS))
    preparation = SetPreparation(event_id="food_item_1",
                                 field_id="op:food_item_1:preparation:0",
                                 preparation_id="grilled")
    fa.assert_settlement_is_consistent(
        item={"food": "Chicken"},
        answered={quantity.field_id: quantity,
                  preparation.field_id: preparation})


# ── identity: a reopened field is a NEW field ──────────────────────────────

def test_a_reopened_field_at_a_new_revision_is_not_the_old_one():
    """yes -> 1 tbsp -> no -> yes must NOT revive the first tablespoon.

    `field_id` is `operation:event:attribute:revision`, so the generation is
    the revision and the attribute identity is stable across it. A stale tap
    carrying the old id addresses a field that no longer exists.
    """
    first, reopened = _amount(revision=0), _amount(revision=1)
    assert first.field_id != reopened.field_id
    assert (fa.attribute_of_field_id(first.field_id)
            == fa.attribute_of_field_id(reopened.field_id) == AMOUNT)


def test_the_attribute_survives_an_operation_id_containing_colons():
    """Production ids look like `chat_quantity:26:ios:<uuid>` — splitting from
    the left would read "26" as the attribute."""
    real = ("chat_quantity:26:ios:C6B61BC0-12A3-4147-B344-A8A583ABD1:"
            "food_item_c0e1922cfeac:added_fat_amount:0")
    assert fa.attribute_of_field_id(real) == AMOUNT


# ── the graph ──────────────────────────────────────────────────────────────

def test_the_installed_graph_is_acyclic_and_fully_declared():
    fa.assert_declares_its_dependencies()
    fa.assert_acyclic()


def test_a_cycle_is_refused_rather_than_ordered_arbitrarily():
    """Two fields waiting on each other present as a question that silently
    never opens — which is why this breaks the process instead."""
    present, amount = sf.spec_for(PRESENT), sf.spec_for(AMOUNT)
    sf._REGISTRY[PRESENT] = type(present)(
        **{**present.__dict__,
           "activation": sf.Activation.CONDITIONAL,
           "active_when": fa.IsTrue(AMOUNT)})
    try:
        with pytest.raises(fa.ActivationCycle):
            fa.assert_acyclic()
    finally:
        sf._REGISTRY[PRESENT] = present


def test_a_callable_predicate_is_refused_outright():
    """⭐ THE HARDENING THAT REPLACED "not async".

    Rejecting `async def` proves nothing: a SYNCHRONOUS closure can capture a
    provider, read a module global, or consult a cache, and its `depends_on`
    would be an unverifiable claim. Only a declarative rule cannot lie about
    what it reads — because it has nowhere to put anything else.
    """
    captured = {"provider": "still reachable from a sync closure"}
    spec = sf.spec_for(AMOUNT)
    for predicate in (lambda state: bool(captured),
                      _an_async_predicate):
        with pytest.raises(sf.ContractViolation):
            sf.register(type(spec)(
                **{**spec.__dict__,
                   "attribute": ClarificationAttribute.EQUIPMENT,
                   "active_when": predicate}))


async def _an_async_predicate(_state):
    return True


def test_dependencies_are_derived_from_the_rule_not_declared_beside_it():
    """A second declaration could disagree with the rule and leave the cycle
    check formally green and semantically false. There is no second
    declaration: `depends_on` walks the rule."""
    spec = sf.spec_for(AMOUNT)
    assert spec.depends_on == tuple(sorted(spec.active_when.attributes()))

    wider = type(spec)(**{**spec.__dict__,
                          "active_when": fa.All((fa.IsTrue(PRESENT),
                                                 fa.Present("quantity")))})
    assert wider.depends_on == (PRESENT, "quantity"), (
        "the edges did not follow the rule — a derived dependency that does "
        "not track its rule is the declaration problem with extra steps")


def test_a_field_cannot_depend_on_itself():
    spec = sf.spec_for(AMOUNT)
    with pytest.raises(sf.ContractViolation):
        sf.register(type(spec)(**{**spec.__dict__,
                                  "attribute": ClarificationAttribute.EQUIPMENT,
                                  "active_when": fa.IsTrue(
                                      ClarificationAttribute.EQUIPMENT.value)}))


def test_field_order_is_topological_and_deterministic():
    """Not set iteration. Field order reaches the iOS payload, and an order
    that depends on registry insertion is a rendering difference with no
    semantic cause — which gets diagnosed as a client bug."""
    order = fa.activation_order()
    assert order == fa.activation_order(), "not deterministic"
    for key in order:
        for dep in sf.spec_for(key).depends_on:
            assert order.index(dep) < order.index(key), (
                f"{key} is ordered before its dependency {dep}")


# ── ⭐ THE CONSUMER RATCHET ────────────────────────────────────────────────

def test_every_registered_conditional_is_actually_evaluated():
    """ADMISSION IS NOT ENOUGH — the other end must read it.

    `register()` has refused a CONDITIONAL field with no `active_when` since
    the contract was written, and NOTHING CONSUMED IT until this slice. A
    field registered conditional would have been admitted, passed its contract
    check, and then never activated: a gate at one end with no consumer at the
    other, which is this codebase's most expensive recurring shape.

    So the ratchet is bidirectional. Every registered conditional must be
    REACHED by the reconciler — proven by observing the predicate get called,
    not by trusting that the loop covers it.
    """
    conditionals = [k for k, s in sf.registered().items()
                    if s.activation is sf.Activation.CONDITIONAL]
    assert conditionals, (
        "no conditional field is registered, so this ratchet proves nothing "
        "— B-1.6 without a conditional field is the contract, not the engine")

    seen = []
    originals = {}
    try:
        for key in conditionals:
            spec = sf.spec_for(key)
            originals[key] = spec
            class _Watch(fa.Rule):
                def __init__(self, key, inner): self._key, self._inner = key, inner
                def evaluate(self, state):
                    seen.append(self._key)
                    return self._inner.evaluate(state)
                def attributes(self): return self._inner.attributes()

            sf._REGISTRY[key] = type(spec)(
                **{**spec.__dict__,
                   "active_when": _Watch(key, spec.active_when)})
        fa.active_attributes(_state())
    finally:
        sf._REGISTRY.update(originals)

    assert sorted(seen) == sorted(conditionals), (
        f"the reconciler evaluated {sorted(seen)} but {sorted(conditionals)} "
        f"are registered conditional — a field nothing consults is a field "
        f"that silently never opens")


def test_policy_does_not_decide_activation():
    """ONE OWNER. If a policy module computed activation independently,
    `active_when` would be advisory and there would be two owners again."""
    import ast
    import pathlib

    # AST, NOT A SUBSTRING SEARCH. The first version of this gate grepped the
    # file text and fired on two modules whose COMMENTS explain why they must
    # not read `active_when` — a gate that cannot tell an access from a
    # sentence about an access punishes the documentation it asked for.
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in (root / "core").glob("*.py"):
        if path.name in ("field_activation.py", "semantic_fields.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        reads = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute) and n.attr == "active_when"]
        if reads:
            offenders.append(path.name)
    assert not offenders, (
        f"{offenders} reads `active_when` directly. Activation truth has one "
        f"owner; policy decides what to DO with an active unresolved field, "
        f"never whether it is active")
