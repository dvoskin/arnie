"""⭐ WIRING — the producer runs where the turn already pays for a model call.

Step 4 of Danny's frozen order: wire `ensure_resolved()` at interpretation time.
Steps 5 and 6 (persist, then CONSUME downstream) are deliberately still open, so
this lands in SHADOW: resolution populates the durable store and alters no price,
no card and no row.

⭐ SHADOW IS NOT A HALF-MEASURE HERE. The store fills from real traffic — which
is what lets the 691-entry instrument be re-run against identities users
actually produced rather than a backfill script's guesses — while the blast
radius stays exactly zero, because nothing reads `canonical_entity_id` yet.

⛔ AND OFF IS THE DEFAULT, so this commit cannot change production behaviour
whatever its deploy state. That matters while exact-head CI is still owed.
"""
from __future__ import annotations

import pytest

from core.turns.stages.food import (entity_resolution_mode,
                                    plan_from_interpretation,
                                    stamp_canonical_identity)


class _DB:
    """A db handle that would explode if it were ever used. Presence alone is
    what the guard checks, so the tests that pass one must never reach it."""

    def __getattr__(self, name):
        raise AssertionError(f"the store was touched via .{name}() when the "
                             f"flag should have prevented it")


def _interpretation():
    return {"action": "log",
            "items": [{"food": "Помидор", "amount": 2, "unit": "шт"},
                      {"food": "Творог 2%", "amount": 150, "unit": "g"}],
            "tool_calls": [{"name": "log_food", "input": {"food_name": "Помидор"}}]}


@pytest.fixture
def resolver(monkeypatch):
    """Replace the producer, and record what it was asked."""
    calls = []

    async def _fake(db, surfaces):
        calls.append(list(surfaces))
        return {"Помидор": "tomato", "Творог 2%": "tvorog 2 percent"}

    import skills.nutrition.entity_resolver as producer
    monkeypatch.setattr(producer, "ensure_resolved", _fake)
    monkeypatch.setenv("ENTITY_RESOLUTION_MODE", "shadow")
    return calls


# ── the flag ──────────────────────────────────────────────────────────────────

def test_the_default_is_off(monkeypatch):
    monkeypatch.delenv("ENTITY_RESOLUTION_MODE", raising=False)
    assert entity_resolution_mode() == "off"


def test_an_unrecognised_value_reads_as_off(monkeypatch):
    """⚠ A TYPO MUST NOT ENABLE A FEATURE. `TURN_COORDINATOR_MODE` learned this
    the same way — an unparsed value has to fail toward the safe state, not
    toward whichever branch happens to be written first."""
    monkeypatch.setenv("ENTITY_RESOLUTION_MODE", "shaddow")
    assert entity_resolution_mode() == "off"


@pytest.mark.asyncio
async def test_nothing_is_resolved_while_the_flag_is_off(monkeypatch):
    monkeypatch.delenv("ENTITY_RESOLUTION_MODE", raising=False)
    out = _interpretation()

    await stamp_canonical_identity(out, _DB())

    assert all("canonical_entity_id" not in item for item in out["items"])


# ── shadow ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_shadow_RESOLVES_every_item_and_stamps_NONE_of_them(resolver):
    """⛔⛔ THE CONTRACT CHANGED ON 2026-08-15, AND THIS TEST IS WHERE IT SHOWS
    *(Danny)*. It used to assert that `shadow` STAMPS, which was safe only while
    the stamp was inert metadata. After `1f13347` it is not: the stamp rides
    `_log_call` into `_analyze_food`, where `memory_key(food, entity)` addresses
    a DIFFERENT durable memory row — so stamping moves a PRICE.

    ⭐ AND THE OLD MEANING WAS COORDINATOR-DEPENDENT, WHICH IS THE REAL DEFECT.
    The legacy seams record without stamping; `FoodPlanStage.run` (only under
    `new_execute`) stamps. One flag called `shadow` therefore meant "record" on
    ordinary traffic and "consume" on coordinator traffic, with the difference
    invisible in its name.

    So `shadow` resolves and persists — `resolver` below proves the producer
    RAN — and annotates nothing. `consume` is the state that annotates.
    """
    out = _interpretation()

    await stamp_canonical_identity(out, _DB())

    # THE PRODUCER RAN: without this the assertion under it passes vacuously on
    # a turn where nothing was resolved at all.
    assert resolver == [["Помидор", "Творог 2%"]]
    assert all("canonical_entity_id" not in item for item in out["items"]), (
        "shadow stamped an item — that reaches memory_key and moves the price")


@pytest.mark.asyncio
async def test_consume_is_the_state_that_stamps(resolver, monkeypatch):
    """The other half: `consume` must still annotate, or the split has quietly
    deleted consumption's doorway while every recording gate stays green."""
    monkeypatch.setenv("ENTITY_RESOLUTION_MODE", "consume")
    out = _interpretation()

    await stamp_canonical_identity(out, _DB())

    assert [item["canonical_entity_id"] for item in out["items"]] == [
        "tomato", "tvorog 2 percent"]
    assert resolver == [["Помидор", "Творог 2%"]]


@pytest.mark.asyncio
async def test_the_plan_and_its_operations_are_untouched(resolver):
    """⭐ THE BLAST RADIUS, ASSERTED RATHER THAN PROMISED. Shadow may write to
    the store; it may not change what the turn does. The lifted plan is what
    every later stage reads, so if it is identical the turn is identical."""
    before = plan_from_interpretation(_interpretation())

    out = _interpretation()
    await stamp_canonical_identity(out, _DB())
    after = plan_from_interpretation(out)

    assert after.operations == before.operations
    assert after.response_intent == before.response_intent
    assert after.narration_hint == before.narration_hint


@pytest.mark.asyncio
async def test_an_unresolved_food_is_left_alone(monkeypatch):
    """Absence stamps nothing — the item keeps exactly the shape it had, which
    is what makes `UNRESOLVED` reproduce today's behaviour byte for byte."""
    async def _nothing(db, surfaces):
        return {}

    import skills.nutrition.entity_resolver as producer
    monkeypatch.setattr(producer, "ensure_resolved", _nothing)
    monkeypatch.setenv("ENTITY_RESOLUTION_MODE", "shadow")
    out = _interpretation()

    await stamp_canonical_identity(out, _DB())

    assert all("canonical_entity_id" not in item for item in out["items"])


# ── it cannot break a turn ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_failing_resolver_does_not_fail_the_turn(monkeypatch):
    """A food turn must not break over an identity annotation NOTHING YET
    CONSUMES. The producer already swallows its own errors; this is the outer
    guard for everything else — an import error, a dead session, a bug here."""
    async def _explodes(db, surfaces):
        raise RuntimeError("resolver on fire")

    import skills.nutrition.entity_resolver as producer
    monkeypatch.setattr(producer, "ensure_resolved", _explodes)
    monkeypatch.setenv("ENTITY_RESOLUTION_MODE", "shadow")
    out = _interpretation()

    await stamp_canonical_identity(out, _DB())      # must not raise

    assert plan_from_interpretation(out).operations == tuple(out["tool_calls"])


@pytest.mark.asyncio
async def test_no_db_means_no_resolution(resolver):
    """The legacy entry point and the coordinator both carry `db`, but a stage
    invoked without one must degrade rather than construct its own session."""
    out = _interpretation()

    await stamp_canonical_identity(out, None)

    assert resolver == []


@pytest.mark.asyncio
async def test_an_ask_turn_with_no_items_asks_nothing(resolver):
    await stamp_canonical_identity({"action": "ask", "items": []}, _DB())
    await stamp_canonical_identity(None, _DB())

    assert resolver == []


@pytest.mark.asyncio
async def test_a_nameless_item_never_reaches_the_producer(resolver):
    """An empty surface is not a question worth asking, and asking it would put
    a row keyed on `''` into a store whose key is the food."""
    await stamp_canonical_identity(
        {"action": "log", "items": [{"food": ""}, {"food": "   "}]}, _DB())

    assert resolver == []
