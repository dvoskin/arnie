"""⭐ THE INTERPRETATION BOUNDARY'S SUBSTRATE — three states, one durable answer.

> Surface language is for DISPLAY and AUDIT. Canonical identity comes from
> INTERPRETED FOOD MEANING. *(Danny, 2026-08-14)*

These gates cover the STORE and its invariants. The producer that fills it is a
separate slice, and separating them is deliberate: the properties asserted here
must hold whatever eventually writes the rows, including a human.

Danny's acceptance list has seven items. Four of them are about the substrate
and are gated here — an unresolved food falls back to today's exact behaviour ·
settlement performs zero model calls · a changed resolver cannot silently mutate
a bound resolution without version semantics · and the key can tell the
collision class apart. The other three (Помидор → tomato, white rice → rice,
творог NOT → cottage cheese) are producer gates and land with the producer.
"""
from __future__ import annotations

import inspect
import pathlib

import pytest
import pytest_asyncio

from skills.nutrition import entity_resolution as er
from skills.nutrition.entity_resolution import (EntityResolution,
                                                ResolutionState,
                                                canonical_entity_id_for,
                                                contract_fingerprint,
                                                surface_key)
from tests.test_a_full_day_of_food import app_db, seeded  # noqa: F401


@pytest_asyncio.fixture
async def store(app_db, seeded):           # noqa: F811
    import db.database as D
    async with D.AsyncSessionLocal() as session:
        yield session


def _res(surface, state, entity="", **kw):
    return EntityResolution(surface_form=surface, surface_key=surface_key(surface),
                            state=state, canonical_entity_id=entity, **kw)


# ── the key can tell the collision class apart ────────────────────────────────

def test_the_key_distinguishes_the_foods_normalize_name_merged():
    """⛔ THE WHOLE POINT. `normalize_name` reduced all three of these to `'2'`,
    which is how a user's cottage cheese was priced from their boiled corn."""
    from core.food_intelligence import normalize_name

    corn, tvorog, eggs = ("Кукуруза варёная (2 початка)", "Творог 2%",
                          "Омлет из 2 яиц")
    assert normalize_name(corn) == normalize_name(tvorog) == normalize_name(eggs)
    assert len({surface_key(corn), surface_key(tvorog), surface_key(eggs)}) == 3


def test_the_key_is_case_insensitive_across_scripts():
    """`casefold`, not `lower` — the latter is not the case-insensitive
    comparison operation outside ASCII."""
    assert surface_key("ТВОРОГ 2%") == surface_key("Творог 2%")
    assert surface_key("White Rice") == surface_key("white rice")


def test_punctuation_becomes_a_boundary_and_not_a_deletion():
    """Deleting it in place is how `steak/roast` became `steakroast` once."""
    assert surface_key("steak/roast") == "steak roast"
    assert surface_key("Молоко (2.5%)") == "молоко 2 5"


# ── an absent answer is never a present one ───────────────────────────────────

def test_unresolved_may_not_carry_an_entity():
    """⭐ STRUCTURAL, NOT CONVENTIONAL. The type refuses it, so no producer can
    write a non-decision that reads as a decision."""
    with pytest.raises(ValueError, match="absent answer"):
        _res("Помидор", ResolutionState.UNRESOLVED, "tomato")


@pytest.mark.parametrize("state", [ResolutionState.RESOLVED,
                                   ResolutionState.DISTINCT])
def test_a_binding_state_must_name_its_entity(state):
    with pytest.raises(ValueError, match="must name the entity"):
        _res("Помидор", state, "")


def test_distinct_binds_its_own_identity_rather_than_a_false_mapping():
    """⭐ `DISTINCT` IS THE STATE THAT DOES THE WORK. Without it the only
    choices are a convenient English approximation or nothing, and every design
    that can only say RESOLVED-or-nothing takes the approximation whenever it
    looks close enough. `творог` is not `cottage cheese`."""
    kept = _res("Творог 2%", ResolutionState.DISTINCT, "tvorog")
    assert kept.binds and kept.canonical_entity_id == "tvorog"


# ── settlement's single question ──────────────────────────────────────────────

def test_every_way_of_having_no_answer_returns_the_same_empty_string():
    """⭐ THE MONOTONICITY GUARANTEE, AS CODE. No row · stale contract ·
    UNRESOLVED all collapse to `""`, so there is no branch in which a caller
    receives something it has to interpret."""
    assert canonical_entity_id_for(None) == ""
    assert canonical_entity_id_for(
        _res("Помидор", ResolutionState.UNRESOLVED)) == ""
    stale = _res("Помидор", ResolutionState.RESOLVED, "tomato",
                 contract_fingerprint="erc_from_another_era")
    assert canonical_entity_id_for(stale) == ""


def test_a_current_binding_resolution_is_the_one_thing_that_returns_an_entity():
    """ANTI-VACUITY: a function that always returned `""` would pass every
    assertion above and delete the entire feature."""
    live = _res("Помидор", ResolutionState.RESOLVED, "tomato",
                contract_fingerprint=contract_fingerprint())
    assert canonical_entity_id_for(live) == "tomato"


def test_the_advisory_fields_are_never_read_by_the_decision():
    """⚠ ADVISORY MEANS STRUCTURALLY ADVISORY. A confidence threshold is how a
    stochastic judgement becomes a silent policy — the STATE is the decision,
    and an unsure producer writes UNRESOLVED rather than RESOLVED with a low
    number attached. Asserted on the source, because a runtime check could pass
    on values that merely happen not to differ."""
    source = inspect.getsource(canonical_entity_id_for)
    assert "confidence" not in source and "reason" not in source

    timid = _res("Помидор", ResolutionState.RESOLVED, "tomato",
                 confidence=0.01, reason="barely",
                 contract_fingerprint=contract_fingerprint())
    assert canonical_entity_id_for(timid) == "tomato"


def test_settlement_performs_no_model_call_for_entity_resolution():
    """Danny's gate 5. The read path is a lookup; production of a resolution
    belongs to the interpretation stage, where a model call is already made and
    its latency already paid."""
    source = pathlib.Path(er.__file__).read_text()
    for forbidden in ("anthropic", "client.messages", "acompletion",
                      "call_model", "resolve_with_model"):
        assert forbidden not in source, (
            f"{forbidden!r} reached the resolution module — settlement reads "
            f"the durable result and only the durable result (Gate B)")


# ── version and invalidation semantics ────────────────────────────────────────

def test_a_moved_contract_makes_a_stored_answer_unverified_not_wrong():
    """Danny's gate 6. When `RESOLVED` eventually targets opaque ids instead of
    the artifact namespace, every stored row becomes a resolution of a different
    question — and expires honestly rather than silently persisting."""
    bound = _res("Помидор", ResolutionState.RESOLVED, "tomato",
                 contract_fingerprint=contract_fingerprint())
    assert bound.is_current()
    assert not bound.is_current("erc_after_the_namespace_moves")


def test_the_fingerprint_covers_both_the_resolver_and_the_namespace(monkeypatch):
    """Either half moving must change it. A fingerprint that only tracked the
    resolver would let a namespace migration reuse answers about the old one."""
    before = contract_fingerprint()
    monkeypatch.setattr(er, "ENTITY_NAMESPACE", "opaque_entity_v2")
    assert contract_fingerprint() != before
    monkeypatch.setattr(er, "ENTITY_NAMESPACE", "artifact_entity_v1")
    monkeypatch.setattr(er, "RESOLVER_VERSION", "entity_resolution_v2")
    assert contract_fingerprint() != before


# ── the durable store ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_recorded_resolution_reads_back_and_binds(store):
    await er.record(store, _res("Помидор", ResolutionState.RESOLVED, "tomato",
                                interpreted_meaning="the fruit, raw",
                                source_language="ru", model_id="claude-sonnet-5"))

    found = await er.resolve(store, "помидор")           # any casing
    assert found is not None
    assert found.state is ResolutionState.RESOLVED
    assert found.interpreted_meaning == "the fruit, raw"
    assert found.model_id == "claude-sonnet-5"
    assert await er.entity_id_for_surface(store, "ПОМИДОР") == "tomato"


@pytest.mark.asyncio
async def test_an_unknown_food_yields_todays_behaviour(store):
    """Danny's gate 4 at the store: nothing recorded means nothing claimed."""
    assert await er.resolve(store, "Шакшука") is None
    assert await er.entity_id_for_surface(store, "Шакшука") == ""


@pytest.mark.asyncio
async def test_the_colliding_foods_do_not_share_a_stored_resolution(store):
    """The production collision class, at the durable layer."""
    await er.record(store, _res("Кукуруза варёная (2 початка)",
                                ResolutionState.RESOLVED, "corn"))
    await er.record(store, _res("Творог 2%", ResolutionState.DISTINCT, "tvorog"))

    assert await er.entity_id_for_surface(store, "Кукуруза варёная (2 початка)") == "corn"
    assert await er.entity_id_for_surface(store, "Творог 2%") == "tvorog"


@pytest.mark.asyncio
async def test_the_fingerprint_is_stamped_by_the_store_not_by_the_caller(store):
    """⭐ A producer that could choose its own contract id could claim currency
    it does not have, and the expiry mechanism would answer to whoever wrote
    last rather than to the contract."""
    written = await er.record(store, _res("Помидор", ResolutionState.RESOLVED,
                                          "tomato",
                                          contract_fingerprint="erc_i_say_so"))
    assert written.contract_fingerprint == contract_fingerprint()
    assert (await er.resolve(store, "Помидор")).is_current()


@pytest.mark.asyncio
async def test_a_new_answer_replaces_the_old_one_rather_than_merging(store):
    """⚠ A merge would produce a row no single resolver ever asserted — the
    shape of defect that made a partial abstention read as a confident
    negative."""
    await er.record(store, _res("Творог 2%", ResolutionState.RESOLVED,
                                "cottage cheese", reason="close enough",
                                model_id="old-model"))
    await er.record(store, _res("Творог 2%", ResolutionState.DISTINCT, "tvorog",
                                interpreted_meaning="a distinct dairy food"))

    found = await er.resolve(store, "Творог 2%")
    assert found.state is ResolutionState.DISTINCT
    assert found.canonical_entity_id == "tvorog"
    assert found.reason == "" and found.model_id == ""
    assert found.interpreted_meaning == "a distinct dairy food"


@pytest.mark.asyncio
async def test_one_surface_form_keeps_exactly_one_row(store):
    from sqlalchemy import func, select

    from db.models import FoodEntityResolution

    for entity in ("tomato", "tomatoes", "tomato"):
        await er.record(store, _res("Помидор", ResolutionState.RESOLVED, entity))

    count = (await store.execute(
        select(func.count()).select_from(FoodEntityResolution))).scalar()
    assert count == 1
