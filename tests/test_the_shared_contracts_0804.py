"""The cross-domain contracts, and the invariants that are the point of them.

Landed before the food redesign rather than after, because the alternative has
already happened once: food grew its own quantity, its own option type (twice),
its own pending lifecycle, and generalising afterwards is the work being
avoided.

Nothing here is on a write path yet. These tests exist so each later migration
is a small reviewable change against a contract that already holds.
"""
from decimal import Decimal as D

import pytest

from core.semantics import (CanonicalQuantity, ClarificationField,
                            ClarificationOption, Confidence, Dimension,
                            EventReference, ExecutionResult, PendingOperation,
                            PendingStatus, Provenance, ResolutionStatus,
                            SemanticTurn)


def test_the_execution_result_is_the_one_that_already_existed():
    """THE MOST IMPORTANT TEST IN THIS FILE. `core/execution_result` already
    defines an ExecutionResult, already cross-domain, already consumed by food
    and exercise. Re-exporting rather than redefining is the difference between
    a shared contract and a ninth competing source of truth — which is the
    thing this whole module is against."""
    assert ExecutionResult.__module__ == "core.execution_result"


# ── quantity: dimensional consistency at construction ────────────────────────

@pytest.mark.parametrize("kwargs,why", [
    (dict(dimension=Dimension.MASS, milliliters=D("236.6")),
     "a mass resolved only to millilitres"),
    (dict(dimension=Dimension.VOLUME, grams=D("100")),
     "a volume resolved only to grams"),
])
def test_a_quantity_cannot_disagree_with_itself(kwargs, why):
    """The directive names this shape exactly: `amount=1, unit=ml,
    milliliters=236.6` is two quantities in a trench coat, and food has shipped
    it. Rejected at construction because downstream is where it becomes a
    calorie."""
    with pytest.raises(ValueError):
        CanonicalQuantity(**kwargs)


def test_a_density_conversion_may_carry_both():
    """The legitimate case the check must not break: a cup of rice really is
    236.6 ml AND 158.5 g, because a density produced them together."""
    q = CanonicalQuantity(dimension=Dimension.VOLUME, amount=D("1"),
                          unit_id="cup", grams=D("158.5"),
                          milliliters=D("236.6"))
    assert q.grams and q.milliliters


@pytest.mark.parametrize("kwargs", [
    dict(range_min=D("4"), range_max=D("2")),
    dict(amount=D("-1")),
    dict(grams=D("-5")),
])
def test_impossible_quantities_are_refused(kwargs):
    with pytest.raises(ValueError):
        CanonicalQuantity(**kwargs)


def test_a_range_stays_a_range():
    """"3-4 oz" is not 3.5 oz. Collapsing a stated span to a midpoint invents a
    figure the user did not give — the same defect as reading "5-6 pieces" as
    11, from the other direction."""
    q = CanonicalQuantity(range_min=D("3"), range_max=D("4"), unit_id="oz",
                          dimension=Dimension.MASS)
    assert q.is_range and q.amount is None


# ── provenance: selected is not stated ───────────────────────────────────────

def test_a_tapped_chip_is_not_the_users_own_figure():
    """MEASURED, 2026-08-04. A tapped chip cleared food's `estimated` flag, and
    with it the "(my estimate)" marker, the card range and the disclosure — so
    a portion the SYSTEM proposed was recorded as user precision. The contract
    makes the two different values."""
    assert Provenance.USER_STATED.is_users_own is True
    assert Provenance.USER_SELECTED.is_users_own is False
    assert Provenance.USER_CONFIRMED.is_users_own is False


@pytest.mark.parametrize("p", [Provenance.MODE_DEFAULT, Provenance.ONTOLOGY,
                               Provenance.MODEL_ESTIMATE])
def test_assumptions_know_they_are_assumptions(p):
    assert p.is_assumption and not p.is_users_own


def test_confidence_carries_its_basis():
    """A bare float is unauditable: 0.61 does not say whether to ask."""
    c = Confidence(score=0.61, basis="model-proposed, two candidates")
    assert c.basis
    with pytest.raises(ValueError):
        Confidence(score=1.4)


# ── unknown is a valid answer ────────────────────────────────────────────────

def test_unresolved_is_a_state_not_a_failure():
    assert ResolutionStatus.RESOLVED.is_actionable
    for s in (ResolutionStatus.UNRESOLVED, ResolutionStatus.AMBIGUOUS,
              ResolutionStatus.PARTIALLY_RESOLVED):
        assert not s.is_actionable


def test_an_unbound_reference_stays_unbound():
    """A correction must bind to a stable prior EVENT, not to the closest
    string. `_undeferred`'s fuzzy claim loop is the measured worst case — its
    own comment says it can delete a row the user reported."""
    assert not EventReference(surface_text="that one").is_bound
    assert EventReference(surface_text="that one", event_id="e1",
                          resolution_status=ResolutionStatus.RESOLVED).is_bound


# ── clarification: question and options are one object ───────────────────────

def test_a_human_label_can_carry_a_machine_value():
    """The split food needed and did not have: only number-first labels could
    be priced, so "Small piece" resolved to None and every human-readable
    option was unusable."""
    o = ClarificationOption(label="Medium piece", value="4 oz")
    assert o.label == "Medium piece" and o.send_value == "4 oz"


def test_an_option_without_a_value_sends_its_label():
    """Telegram and iMessage have no value channel — a reply keyboard sends the
    text. The label must remain a usable answer."""
    assert ClarificationOption(label="Grilled").send_value == "Grilled"


# ── pending: one owner, and a real commit gate ───────────────────────────────

def _field(required):
    return ClarificationField(
        id="e1.portion", event_id="e1", attribute="portion",
        question="About how much chicken?",
        options=(ClarificationOption(label="Medium piece", value="4 oz"),),
        required_by_modes=frozenset(required))


def test_strict_cannot_commit_past_a_required_unresolved_field():
    """The gate `undercount=True` never was. It has been passive telemetry
    sitting beside a commit — observed in production on 2026-08-04 flagging
    undercount with food_logs=0, twice, while nothing acted."""
    p = PendingOperation(id="p1", user_id="26", domain="food",
                         unresolved_fields=(_field({"strict"}),))
    assert p.may_commit("strict") is False
    assert p.may_commit("quick") is True
    assert len(p.required_unresolved("strict")) == 1


def test_terminal_states_close_the_operation():
    for s in (PendingStatus.COMMITTED, PendingStatus.CANCELLED,
              PendingStatus.EXPIRED, PendingStatus.FAILED):
        assert s.is_terminal
        assert not PendingOperation(id="p", user_id="u", domain="food",
                                    status=s).is_open
    assert PendingOperation(id="p", user_id="u", domain="food",
                            status=PendingStatus.AWAITING_CLARIFICATION).is_open


def test_the_idempotency_key_is_a_field_of_the_operation():
    """Not of the message. Food's existing key is
    `turn_idempotency_key(user_id, message, tool_calls)` over an in-process
    dict: it dedupes a repeated MESSAGE rather than a repeated COMMIT, and
    survives neither a restart nor a second worker."""
    assert "idempotency_key" in PendingOperation.__dataclass_fields__


# ── the turn envelope ────────────────────────────────────────────────────────

def test_a_non_latin_message_is_a_blindspot_not_a_decline():
    """98 of 301 real food logs the gate turned away were rejected for their
    alphabet rather than their content. The rules not applying is not the same
    as the message not being food."""
    assert SemanticTurn(turn_id="t", user_id="u",
                        raw_text="Я съел курицу и рис").is_multilingual_blindspot
    assert not SemanticTurn(turn_id="t", user_id="u",
                            raw_text="chicken and rice").is_multilingual_blindspot


# ── the adapter: food adapts INTO the contract ───────────────────────────────

@pytest.mark.parametrize("stated,food,dimension", [
    ("3 eggs", "eggs", Dimension.COUNT),
    ("1 burger", "burger", Dimension.COUNT),
    ("2 potatoes", "potatoes", Dimension.COUNT),
    ("1 cup", "rice", Dimension.VOLUME),
    ("4 oz", "chicken", Dimension.MASS),
    ("500 ml", "water", Dimension.VOLUME),
])
def test_the_dimension_is_what_the_user_said(stated, food, dimension):
    """Not what we resolved. "3 eggs" is a COUNT we happen to have resolved to
    150 g — reading the resolution instead labelled every countable food as
    mass, because a countable food is exactly the case where both are present.
    """
    from skills.nutrition.canonical_adapter import to_canonical
    from skills.nutrition.normalize import normalize_quantity

    q = to_canonical(normalize_quantity(stated, food))
    assert q.dimension is dimension


def test_real_food_quantities_survive_the_contract():
    """Shadow-mode value: anything food carries that the contract refuses is a
    shape food has been carrying all along, found for free."""
    from skills.nutrition.canonical_adapter import to_canonical
    from skills.nutrition.normalize import normalize_quantity

    for stated, food in [("4 oz", "chicken"), ("1 cup", "rice"),
                         ("1 burger", "burger"), ("1/2 cup", "rice"),
                         ("100g", "beef"), ("1 slice", "bread"),
                         ("some", "chicken"), ("1 tbsp", "peanut butter")]:
        to_canonical(normalize_quantity(stated, food))   # must not raise


def test_the_adapter_does_not_flatter_unknown_provenance():
    """`NormalizedQuantity` has no provenance field at all — whether a figure
    was typed or tapped lives several layers away in `_item_is_stated`. So it
    arrives as an argument and defaults to UNKNOWN, never to something
    convenient."""
    from skills.nutrition.canonical_adapter import to_canonical
    from skills.nutrition.normalize import normalize_quantity

    q = to_canonical(normalize_quantity("4 oz", "chicken"))
    assert q.provenance is Provenance.UNKNOWN
    assert q.is_estimated is True
