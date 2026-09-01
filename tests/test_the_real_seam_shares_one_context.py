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
    """Both providers stubbed, every semantic classification counted.

    ⭐ C2.1a §2 pointed these tests at `_fetch_usda_off` — the entry point
    production actually calls — instead of the uncached inner function. That
    is the difference between exercising the seam and exercising a private
    helper, and it brings `_INFLIGHT_FETCHES` with it: a MODULE-LEVEL dict of
    futures that outlives the turn. Without clearing it the second test in
    this file reuses the first test's fetch, every provider count reads 0, and
    the file goes green while proving nothing — the same silence as the
    fixtures that made preparation unreachable.
    """
    from handlers import tool_executor as _te
    _te._INFLIGHT_FETCHES.clear()

    calls = {"classify": 0, "usda": 0}

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

    monkeypatch.setattr("api.usda.search_food", fake_search_food)
    monkeypatch.setattr(
        "skills.nutrition.evidence_qualification._default_complete",
        fake_complete)
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
    from handlers.tool_executor import _fetch_usda_off
    from skills.nutrition.evidence_qualification import assessment_key
    from skills.nutrition.evidence_semantics import VERSION

    turn = EvidenceContext()
    token = CURRENT_EVIDENCE.set(turn)
    try:
        # 1. The real speculative enrichment caller.
        await _fetch_usda_off("chicken", False)
        # ⭐ THE KEY IS NOW ROW-SCOPED, so the test cannot precompute it: the
        # rows come from a real fetch. Derived from the context by PREFIX
        # instead, which proves more than the old hardcoded key did — that
        # enrichment registered EXACTLY ONE assessment of chicken, rather than
        # that it registered one under a name the test already knew.
        prefix = assessment_key("chicken", VERSION)
        keys = [k for k in turn._inflight if k.startswith(prefix)]
        assert len(keys) == 1, (
            f"{len(keys)} chicken assessments on the turn's context — "
            "enrichment did not register exactly one and nothing downstream "
            "can reuse it")
        key = keys[0]
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

    # ⭐ WHAT THIS STILL PROVES, AND WHAT IT NO LONGER DOES.
    #
    # It used to assert that field derivation's trace note landed on THIS
    # context — proof that the same object reached both production callers,
    # which a call count cannot show (a second context never STARTS work, so
    # `classify` stays 1 while nothing is shared, and that is exactly how the
    # defect hid). B-1.5 took preparation off the evidence path entirely: it
    # reads a build-time artifact, writes no trace, and asks for nothing.
    #
    # So this is now a statement about the PRICING lane alone — enrichment and
    # ownership resolve one context, and qualification runs once per turn.
    # That lane still shares evidence through `EvidenceContext`, so the seam
    # it broke on is still a seam, and the counts above are still the guard.




@pytest.mark.asyncio
async def test_a_second_turn_shares_nothing_with_the_first(sessions, user,
                                                           wired):
    """Ambient does not mean global: a new turn is a new context, so no
    assessment can cross turns."""
    from handlers.tool_executor import _fetch_usda_off
    from skills.nutrition.evidence_qualification import assessment_key
    from skills.nutrition.evidence_semantics import VERSION

    # Row-scoped now, so matched by prefix — see the note in the seam test.
    prefix = assessment_key("chicken", VERSION)
    first = EvidenceContext()
    token = CURRENT_EVIDENCE.set(first)
    try:
        await _fetch_usda_off("chicken", False)
    finally:
        CURRENT_EVIDENCE.reset(token)
    keys = [k for k in first._inflight if k.startswith(prefix)]
    assert len(keys) == 1, f"{len(keys)} chicken assessments on the first turn"
    key = keys[0]
    assert first.reused(key)

    second = EvidenceContext()
    token = CURRENT_EVIDENCE.set(second)
    try:
        assert not second.reused(key), (
            "a later turn saw the previous turn's classification")
        assert not [k for k in second._inflight if k.startswith(prefix)], (
            "a later turn inherited the previous turn's assessment under any key")
    finally:
        CURRENT_EVIDENCE.reset(token)


# ── the deadline ────────────────────────────────────────────────────────────



# ── C2.1a: what the turn waits for, and what it does not ────────────────────



@pytest.mark.asyncio
async def test_one_waiters_timeout_does_not_destroy_shared_evidence():
    """§6, THE BUG THIS DIRECTIVE NAMED.

    `EvidenceContext.shared` read

        await asyncio.shield(task) if task.done() else await task

    which shields the case that cannot be cancelled and leaves bare the case
    that can. `preparation_space` wraps it in `wait_for`, so ONE waiter giving
    up cancelled the SHARED future and deleted the acquisition for every other
    consumer of that key — evidence nobody else had asked to abandon.
    """
    ctx, calls = EvidenceContext(), []

    async def slow():
        calls.append(1)
        await asyncio.sleep(0.25)
        return "evidence"

    impatient = asyncio.ensure_future(
        asyncio.wait_for(ctx.shared("k", slow), timeout=0.02))
    with pytest.raises(asyncio.TimeoutError):
        await impatient

    # The second consumer must still get the value — one acquisition, intact.
    assert await ctx.shared("k", slow) == "evidence", (
        "a waiter's timeout cancelled the shared acquisition")
    assert len(calls) == 1, f"{len(calls)} acquisitions for one key"


def test_generic_enrichment_no_longer_speculates():
    """§3. Speculation ran for every food the executor touched, including
    turns the canonical lane never owned and ANSWER turns, which have no field
    to open and can only pay for it. AST, so a re-added call cannot hide."""
    import ast
    import pathlib

    import handlers.tool_executor as te

    tree = ast.parse(pathlib.Path(te.__file__).read_text(encoding="utf-8"))
    offenders = [n.lineno for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and (getattr(n.func, "id", "")
                      or getattr(n.func, "attr", "")) == "start_supplemental"]
    assert not offenders, (
        f"tool_executor speculates again at {offenders} — evidence for a field "
        f"starts at lane eligibility, not on every enrichment")


