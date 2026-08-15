"""⛔⛔ THE NO-TRANSITION CASE FOR EVERY A-CRITERION *(Danny, 2026-08-16)*.

Nineteen positive gates were once green straight through a real defect, and the
only thing that caught it was an invariant stated NEGATIVELY: *a value change
must NOT bump the revision*. A positive gate proves a thing can happen. Its
twin proves the thing does not happen when it must not — and that is the half
that catches a permissive implementation.

    A1   an UNSUPPORTED meal never enters the owner
    A3   an OMITTED quantity does not invent the explicit one
    A4   a bare potato never becomes fried
    A5   a stated `fried` never collapses to bare
    A6   provenance must fail on mismatch EVEN WHEN THE CALORIES MATCH
    A8   a refusal writes no row and no ledger event
    A11  the predicate is stable and side-effect free under repeated evaluation
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.canonical_pricing import (ArtifactEvidence, EstimateEvidence,
                                    MemoryEvidence, PricingRefused, Rung,
                                    price)
from core.general_settlement import (ItemFacts, Supported, Unsupported, decide)
from tests.test_a_full_day_of_food import app_db, seeded  # noqa: F401


def _facts(**over):
    base = dict(identity="Chicken breast", entity="chicken", preparation="",
                has_identity=True, has_quantity=True, has_memory=True,
                has_artifact=False)
    base.update(over)
    return ItemFacts(**base)


# ══ A1 — the meal that must NOT enter the owner ═════════════════════════════

class _RecordingOwner:
    def __init__(self):
        self.calls = []

    async def settle(self, db, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(committed_items=())


def _request(turn_id="t:1", **meta):
    return SimpleNamespace(turn_id=turn_id, source_type="ios", platform="ios",
                           text="I ate a thing", metadata=meta)


@pytest.mark.asyncio
async def test_a1_an_unsupported_meal_never_enters_the_owner(monkeypatch):
    """⛔ AND IT REACHES LEGACY *UNTOUCHED* — not a canonical attempt that fell
    back, not a claim taken and released. Behavioural, because the source-order
    gate can only prove the branch EXISTS, never that it is taken."""
    import core.general_settlement as gs
    from core.turns.stages import execute_native as stage_module

    owner = _RecordingOwner()
    monkeypatch.setattr(gs, "settlement_cohort", lambda user_id=None: True)

    async def unsupported(db, *, user_id, items):
        return Unsupported("no local evidence")

    monkeypatch.setattr(gs, "coverage_for", unsupported)
    monkeypatch.setattr(gs, "GeneralSettlementOwner", lambda: owner)

    legacy = []

    async def fake_executor(ops, user, today_log, db, **kwargs):
        legacy.append(ops)
        return {}

    stage = stage_module.NativeExecutionStage(executor=fake_executor)
    monkeypatch.setattr(stage, "_claim", lambda *a, **k: _true())

    ops = [{"name": "log_food", "input": {"food_name": "Eggplant",
                                          "quantity": "150 g"}}]
    await stage.run(_request(db=object(), user=SimpleNamespace(id=26),
                             today_log=object()),
                    validation=SimpleNamespace(approved_operations=ops))

    assert owner.calls == [], "an Unsupported meal entered canonical settlement"
    assert legacy == [ops], "the legacy path did not receive the whole meal"


@pytest.mark.asyncio
async def test_a1_a_supported_meal_never_reaches_the_legacy_executor(monkeypatch):
    """The twin of the twin. If BOTH ran, one meal would be written twice."""
    import core.general_settlement as gs
    from core.turns.stages import execute_native as stage_module

    owner = _RecordingOwner()
    monkeypatch.setattr(gs, "settlement_cohort", lambda user_id=None: True)

    async def supported(db, *, user_id, items):
        return Supported("artifact", "covered")

    monkeypatch.setattr(gs, "coverage_for", supported)
    monkeypatch.setattr(gs, "GeneralSettlementOwner", lambda: owner)

    legacy = []

    async def fake_executor(ops, user, today_log, db, **kwargs):
        legacy.append(ops)
        return {}

    stage = stage_module.NativeExecutionStage(executor=fake_executor)
    monkeypatch.setattr(stage, "_claim", lambda *a, **k: _true())

    ops = [{"name": "log_food", "input": {"food_name": "Asparagus",
                                          "quantity": "100 g"}}]
    await stage.run(_request(db=object(), user=SimpleNamespace(id=26),
                             today_log=object()),
                    validation=SimpleNamespace(approved_operations=ops))

    assert len(owner.calls) == 1
    assert legacy == [], "a canonically settled meal ALSO reached legacy — "\
                         "that is two writes and two settlement owners"


async def _true():
    return True


# ══ A3 — the quantity that must NOT be invented ═════════════════════════════

def test_a3_calories_move_with_the_stated_mass():
    from skills.nutrition.normalize import normalize_quantity

    memory = MemoryEvidence(per100g={"calories": 200.0, "protein": 20.0,
                                     "carbs": 0.0, "fat": 13.0})
    at_150 = price(entity="Salmon", memory=memory,
                   consumed=normalize_quantity("150 g", "Salmon"))
    at_300 = price(entity="Salmon", memory=memory,
                   consumed=normalize_quantity("300 g", "Salmon"))
    assert round(at_300.calories) == 2 * round(at_150.calories)


def test_a3_an_omitted_quantity_does_not_invent_the_explicit_one():
    """⛔ THE PERMISSIVE FAILURE THIS EXCLUDES: pricing an unquantified food by
    quietly reusing the last mass, or by defaulting to 100 g and presenting it
    as though the user said so. The predicate DECLINES first, and if it is ever
    bypassed the price must not carry a mass nobody stated."""
    assert isinstance(decide(_facts(has_quantity=False)), Unsupported)

    from skills.nutrition.normalize import normalize_quantity

    empty = normalize_quantity("", "Salmon")
    assert not getattr(empty, "grams", None), (
        "an empty quantity resolved to a mass — the explicit case was invented")


# ══ A4 / A5 — the preparation that must NOT drift ═══════════════════════════

def test_a4_a_bare_potato_never_becomes_fried():
    from skills.nutrition.pricing_artifact import key, split_identity

    assert split_identity("Potato") == ("potato", "")
    assert key("potato", "") != key("potato", "fried"), (
        "the bare and fried keys collide — one row would price both, which is "
        "the +30% error B-1.5 measured on chicken")


def test_a5_a_stated_preparation_never_collapses_to_bare():
    from skills.nutrition.pricing_artifact import key, split_identity

    entity, preparation = split_identity("Chicken, fried")
    assert preparation == "fried"
    assert key(entity, preparation) != key(entity, ""), (
        "a stated preparation collapsed into the bare key — the composed "
        "identity stopped being a different food")


# ══ A6 — provenance must fail on MISMATCH, matching numbers notwithstanding ══

def test_a6_a_matching_calorie_number_is_not_provenance():
    """⛔⛔ BANANA 210 = 2x105. A number that agrees with the artifact is not
    evidence that the artifact decided — the coincidence nearly passed for a
    proof once, and A9 exists because of it.

    Here MEMORY carries per-100 g numbers chosen to land on the SAME calories
    the artifact would produce. The recorded rung must still say MEMORY."""
    from skills.nutrition.pricing_artifact import _artifact, evidence_for

    entity = next((str(i).split("|")[0]
                   for i in (getattr(_artifact(), "entries", None) or {})
                   if evidence_for(str(i).split("|")[0], "") is not None), None)
    assert entity, "the artifact is empty — this gate cannot be built"

    artifact = evidence_for(entity, "")
    from_artifact = price(entity=entity, artifact=artifact, consumed=None)

    # Memory that agrees EXACTLY on calories, and still must win as MEMORY.
    twin = price(entity=entity,
                 memory=MemoryEvidence(
                     per100g={"calories": from_artifact.calories,
                              "protein": 0.0, "carbs": 0.0, "fat": 0.0}),
                 artifact=artifact, consumed=None)

    assert round(twin.calories) == round(from_artifact.calories)
    assert twin.rung is Rung.MEMORY, (
        "identical calories were reported as an artifact price — provenance "
        "followed the NUMBER instead of the rung")
    assert twin.evidence_id != from_artifact.evidence_id or not twin.evidence_id


def test_a6_an_estimate_never_borrows_an_evidence_id():
    priced = price(entity="Nothing covered",
                   estimate=EstimateEvidence(calories=250.0, protein=10.0,
                                             carbs=30.0, fat=8.0),
                   consumed=None)
    assert priced.rung is Rung.ESTIMATE
    assert priced.evidence_id == "", (
        "an estimate carried an evidence id — provenance would claim backing "
        "no rung provided")


# ══ A8 — the refusal that must write NOTHING ════════════════════════════════

@pytest.mark.asyncio
async def test_a8_a_refusal_writes_no_row_and_no_ledger_event(app_db, seeded):  # noqa: F811
    """⛔⛔ NON-MUTATING BY CONSTRUCTION, NOT BY CAREFUL HANDLING. Counted on
    BOTH tables, because a refusal that wrote a ledger event and no row would
    leave history describing a meal that does not exist — the phantom shape."""
    import db.database as D
    from sqlalchemy import func, select

    from core.general_settlement import GeneralSettlementOwner
    from db.models import FoodEntry, LedgerEvent

    async def counts():
        async with D.AsyncSessionLocal() as s:
            entries = (await s.execute(
                select(func.count()).select_from(FoodEntry))).scalar()
            events = (await s.execute(
                select(func.count()).select_from(LedgerEvent))).scalar()
            return int(entries or 0), int(events or 0)

    before = await counts()

    async with D.AsyncSessionLocal() as s:
        from db.queries import reload_user

        user = await reload_user(s, seeded)
        with pytest.raises(PricingRefused):
            await GeneralSettlementOwner().settle(
                s, user=user,
                # No memory, no artifact, and an estimate of zero — the
                # mackerel shape, which `refuse_or_return` must reject.
                items=[{"food_name": "Zzz nonexistent food", "quantity": "80 g",
                        "calories": 0, "protein": 0, "carbs": 0, "fat": 0}],
                source_turn_id="refusal:1")
        await s.rollback()

    assert await counts() == before, (
        "a refused settlement left state behind — the refusal must be raised "
        "BEFORE any write, not undone after one")


# ══ A11 — the predicate that must NOT drift or write ════════════════════════

def test_a11_the_predicate_is_stable_under_repeated_evaluation():
    """⛔ A ROUTING DECISION THAT CHANGES BETWEEN TWO IDENTICAL CALLS WOULD MAKE
    ADOPTION UNMEASURABLE — the same meal could be canonical in the log line and
    legacy in the write."""
    facts = _facts(has_memory=False, has_artifact=True)
    verdicts = [decide(facts) for _ in range(5)]
    assert len({(type(v).__name__, getattr(v, "expected_source", ""),
                 v.reason) for v in verdicts}) == 1


@pytest.mark.asyncio
async def test_a11_looking_twice_writes_nothing(app_db, seeded):  # noqa: F811
    """The predicate READS. Called twice it must still have written nothing —
    no cached row, no memory seed, no claim."""
    import db.database as D
    from sqlalchemy import func, select

    from core.general_settlement import coverage_for
    from db.models import FoodEntry, LedgerEvent, UserFoodMatch

    async def counts():
        # A genexp containing `await` is an ASYNC GENERATOR, not a tuple — it
        # returns something truthy that never runs a query, which would have
        # made this gate pass while counting nothing.
        out = []
        async with D.AsyncSessionLocal() as s:
            for table in (FoodEntry, LedgerEvent, UserFoodMatch):
                got = await s.execute(select(func.count()).select_from(table))
                out.append(int(got.scalar() or 0))
        return tuple(out)

    before = await counts()
    async with D.AsyncSessionLocal() as s:
        items = [{"food_name": "Asparagus", "quantity": "100 g"}]
        first = await coverage_for(s, user_id=seeded, items=items)
        second = await coverage_for(s, user_id=seeded, items=items)

    assert type(first) is type(second)
    assert getattr(first, "expected_source", None) == getattr(
        second, "expected_source", None)
    assert await counts() == before, "the coverage predicate wrote state"
