"""THE GATE THAT WAS MISSING, and its absence cost a production turn.

2026-08-07, live: "I had some chicken" took 18.9 s — 6.8 s more than the
comparable pre-qualification turn — and opened ONE field. The mechanism was
fine and thoroughly tested; the two production callers simply never shared a
context:

    b1_quantity_operation.py   derive_unresolved(item, EvidenceContext())
    tool_executor.py           qualify_usda_rows(food_name, cands)

so `_structured_assessments` always saw `reused == False`, the free half
contributed nothing, and everything fell to a web query on the critical path.

WHY THE EXISTING TESTS COULD NOT SEE IT. They seeded a context and proved the
mechanism reused it. A seeded context is one context BY CONSTRUCTION — the
question it can never ask is whether two REAL callers resolve the same object.
This file exercises the actual speculative-enrichment caller and the actual
B-1 ownership caller, and asserts on the seam between them.
"""
from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.evidence_context import CURRENT_EVIDENCE, EvidenceContext
from db.models import Base, User
from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
from skills.nutrition.staging import (FoodIdentity, QuantityIntent,
                                      StagedFoodItem)

#: Real USDA shape, from the captured corpus — two rows the resolver can call
#: compatible with different preparations.
ROWS = [
    {"description": "Chicken, broilers or fryers, breast, meat only, cooked, "
                    "roasted", "fdc_id": 1, "per100g": {"calories": 165}},
    {"description": "Chicken, broilers or fryers, thigh, meat and skin, fried",
     "fdc_id": 2, "per100g": {"calories": 253}},
]


@pytest_asyncio.fixture
async def sessions(tmp_path):
    from db.database import make_engine

    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'seam.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    await eng.dispose()


@pytest_asyncio.fixture
async def user(sessions, monkeypatch):
    async with sessions() as s:
        u = User(telegram_id="seam:1", name="Seam", timezone="UTC")
        s.add(u)
        await s.commit()
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", str(u.id))
    monkeypatch.delenv("B1_QUANTITY_HALT", raising=False)
    monkeypatch.delenv("EVIDENCE_QUALIFICATION_HALT", raising=False)
    return u


@pytest.fixture
def wired(monkeypatch):
    """Both providers stubbed, every semantic classification counted."""
    calls = {"classify": 0, "usda": 0, "web": 0}

    async def fake_search_food(query, page_size=8):
        calls["usda"] += 1
        return list(ROWS)

    async def fake_complete(prompt):
        calls["classify"] += 1
        return json.dumps([
            {"evidence_id": "usda:1",
             "relationship": "COMPATIBLE_SPECIALIZATION", "confidence": 0.92,
             "extracted": {"preparation": "roasted", "kcal_per_100g": 165}},
            {"evidence_id": "usda:2",
             "relationship": "COMPATIBLE_SPECIALIZATION", "confidence": 0.90,
             "extracted": {"preparation": "fried", "kcal_per_100g": 253}},
        ])

    async def fake_web(food_name, exclude=frozenset()):
        calls["web"] += 1
        return {}

    monkeypatch.setattr("api.usda.search_food", fake_search_food)
    monkeypatch.setattr(
        "skills.nutrition.evidence_qualification._default_complete",
        fake_complete)
    monkeypatch.setattr(
        "skills.nutrition.preparation_activation._web_space", fake_web)
    return calls


def _item():
    return StagedFoodItem(
        staged_item_id="si_1", original_text="some chicken",
        identity=FoodIdentity(canonical_name="chicken"),
        quantity=QuantityIntent(descriptor="some"), vague_measure="some",
        ambiguities=(FoodAmbiguity(
            ambiguity_id="a1", staged_item_id="si_1",
            ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
            field_name="estimated_mass_g", materiality_score=2.0,
            calorie_span=180.0),))


def _material():
    return dict(staged_items=(_item(),), asked_item_id="si_1",
                items=[{"food": "chicken", "calories": 187, "protein": 35,
                        "carbs": 0, "fats": 4}],
                message="I had some chicken")


# ── the seam ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enrichment_and_ownership_share_one_context(sessions, user,
                                                          wired):
    """THE PRODUCTION SEAM, both real callers.

    Speculative enrichment runs first (as it does while the interpreter
    streams); B-1 ownership runs after. They must resolve the SAME context,
    await the SAME assessment future, and classify EXACTLY ONCE.
    """
    from core import b1_quantity_operation as b1
    from handlers.tool_executor import _fetch_usda_off_uncached
    from skills.nutrition.evidence_qualification import assessment_key
    from skills.nutrition.evidence_semantics import VERSION

    turn = EvidenceContext()
    token = CURRENT_EVIDENCE.set(turn)
    try:
        # 1. The real speculative enrichment caller.
        await _fetch_usda_off_uncached("chicken", False)
        key = assessment_key("chicken", VERSION)
        assert turn.reused(key), (
            "enrichment did not register its classification on the turn's "
            "context — the seam is broken and nothing downstream can reuse it")
        started = turn._inflight[key]

        # 2. The real B-1 ownership caller.
        async with sessions() as s:
            u = await s.get(User, user.id)
            ask = await b1.try_take_ownership(
                s, user=u, material=_material(), turn_id="t_seam",
                channel="ios", locale="en")
            await s.commit()
    finally:
        CURRENT_EVIDENCE.reset(token)

    assert ask is not None, "B-1 declined; this gate proved nothing"
    # SAME FUTURE — not merely an equal value.
    assert turn._inflight[key] is started, (
        "ownership replaced the in-flight classification instead of awaiting "
        "it")
    # EXACTLY ONE structured classification for the whole turn.
    assert wired["classify"] == 1, (
        f"{wired['classify']} semantic classifications — the two callers did "
        f"not share")
    assert wired["usda"] == 1, f"{wired['usda']} USDA retrievals"

    # ⭐ IDENTITY, DIRECTLY. The count above cannot see a broken seam: a second
    # context simply never STARTS work, so `classify` stays 1 while nothing is
    # shared — which is exactly how today's defect hid. Field derivation writes
    # its trace note to whatever context it was given, so the note appearing on
    # THE TURN'S context is proof the same object reached both callers.
    assert "preparation" in turn.meta, (
        "field derivation wrote its trace to a DIFFERENT context — the two "
        "production callers are not sharing, which is invisible to any count")


@pytest.mark.asyncio
async def test_preparation_opens_from_the_shared_structured_evidence(
        sessions, user, wired):
    """The payoff: with the seam connected, the FREE structured half alone
    establishes roasted 165 vs fried 253 and preparation opens — no web
    lookup at all."""
    from core import b1_quantity_operation as b1
    from handlers.tool_executor import _fetch_usda_off_uncached

    turn = EvidenceContext()
    token = CURRENT_EVIDENCE.set(turn)
    try:
        await _fetch_usda_off_uncached("chicken", False)
        async with sessions() as s:
            u = await s.get(User, user.id)
            ask = await b1.try_take_ownership(
                s, user=u, material=_material(), turn_id="t_open",
                channel="ios", locale="en")
            await s.commit()
    finally:
        CURRENT_EVIDENCE.reset(token)

    attributes = {f.attribute.value
                  for g in ask.interaction.groups for f in g.fields}
    assert attributes == {"quantity", "preparation"}, attributes
    note = turn.meta.get("preparation") or {}
    assert note.get("assessments_reused") is True
    assert note.get("from_structured") == 2
    assert wired["classify"] == 1


@pytest.mark.asyncio
async def test_preparation_issues_no_provider_request_of_its_own(sessions,
                                                                 user, wired):
    """§4: acquisition belongs to the pricing path. Preparation must add no
    USDA retrieval, and at most one supplemental lookup."""
    from core import b1_quantity_operation as b1
    from handlers.tool_executor import _fetch_usda_off_uncached

    turn = EvidenceContext()
    token = CURRENT_EVIDENCE.set(turn)
    try:
        await _fetch_usda_off_uncached("chicken", False)
        usda_after_enrichment = wired["usda"]
        async with sessions() as s:
            u = await s.get(User, user.id)
            await b1.try_take_ownership(
                s, user=u, material=_material(), turn_id="t_noreq",
                channel="ios", locale="en")
            await s.commit()
    finally:
        CURRENT_EVIDENCE.reset(token)

    assert wired["usda"] == usda_after_enrichment, (
        "preparation issued its own USDA retrieval")
    assert wired["web"] <= 1, f"{wired['web']} supplemental lookups"


@pytest.mark.asyncio
async def test_a_second_turn_shares_nothing_with_the_first(sessions, user,
                                                           wired):
    """Ambient does not mean global: a new turn is a new context, so no
    assessment can cross turns."""
    from handlers.tool_executor import _fetch_usda_off_uncached
    from skills.nutrition.evidence_qualification import assessment_key
    from skills.nutrition.evidence_semantics import VERSION

    key = assessment_key("chicken", VERSION)
    first = EvidenceContext()
    token = CURRENT_EVIDENCE.set(first)
    try:
        await _fetch_usda_off_uncached("chicken", False)
    finally:
        CURRENT_EVIDENCE.reset(token)
    assert first.reused(key)

    second = EvidenceContext()
    token = CURRENT_EVIDENCE.set(second)
    try:
        assert not second.reused(key), (
            "a later turn saw the previous turn's classification")
    finally:
        CURRENT_EVIDENCE.reset(token)


# ── the deadline ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_slow_supplemental_lookup_cannot_delay_the_interaction():
    """A bounded grace period to collapse two turns into one is worth paying.
    Making someone watch a spinner while Arnie researches a second question is
    not — so the wait is capped and expiry means DO NOT ASK."""
    import time

    import skills.nutrition.preparation_activation as pa

    turn = EvidenceContext()
    token = CURRENT_EVIDENCE.set(turn)
    original = pa._web_space
    try:
        async def slow(food_name, exclude=frozenset()):
            await asyncio.sleep(10)
            return {"grilled": 165.0, "fried": 250.0}

        pa._web_space = slow
        pa.start_supplemental("chicken")
        started = time.monotonic()
        space = await pa.preparation_space("chicken")
        elapsed = time.monotonic() - started
    finally:
        pa._web_space = original
        CURRENT_EVIDENCE.reset(token)

    assert elapsed < pa.MATERIALITY_BUDGET_S + 0.5, (
        f"waited {elapsed:.1f}s on a slow lookup")
    assert space == {}, "expired materiality must be UNKNOWN, not a guess"
    assert turn.meta["preparation"]["deadline_expired"] is True


@pytest.mark.asyncio
async def test_no_lookup_is_launched_after_the_deadline():
    """Expiry means the turn proceeds without preparation — it does not mean
    starting another lookup that could arrive even later."""
    import skills.nutrition.preparation_activation as pa

    turn = EvidenceContext()
    token = CURRENT_EVIDENCE.set(turn)
    calls = []
    original = pa._web_space
    try:
        async def counted(food_name, exclude=frozenset()):
            calls.append(food_name)
            return {}

        pa._web_space = counted
        # Nothing speculated this turn.
        await pa.preparation_space("chicken")
    finally:
        pa._web_space = original
        CURRENT_EVIDENCE.reset(token)

    assert not calls, (
        "the decision path started a supplemental lookup — speculation is the "
        "only thing allowed to")
