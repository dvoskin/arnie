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
        # ⚠ ONE COMMITTED ROW PER ITEM. The first version returned NO committed
        # items for a meal it had just "settled", which is not a shape the real
        # owner can produce — and once mismatch became a typed raise, this
        # double started failing the test it was written to support. A double
        # that cannot occur in production tests nothing.
        self.calls.append(kwargs)
        items = list(kwargs.get("items") or ())
        return SimpleNamespace(
            committed_items=[{"entry_id": 100 + i, "calories": 1.0,
                              "protein": 0.1} for i, _ in enumerate(items)],
            meal_totals={"calories": float(len(items)), "protein": 0.1})


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


# ══ THE COMMITTED NUMBERS, NOT THE PROPOSED ONES ════════════════════════════

def test_the_rendered_batch_is_the_committed_number_not_the_models():
    """⛔⛔ THE FAILURE THIS CLOSES, STATED AS THE CASE THAT PRODUCES IT.

        operation says   mackerel 180 cal / 20 g protein
        canonical writes                  305 cal / 33 g
        the reply must say                305, never 180

    `compute_batch("commit", ...)` sums the OPERATION INPUTS, which are the
    model's proposal. That was survivable while only the legacy executor wrote
    (it syncs committed macros back onto the input); canonical settlement
    prices from the artifact and never touches the input. Publishing an
    ExecutionResult made the native renderer reachable — this makes it
    truthful.
    """
    from types import SimpleNamespace

    from core.turns.stages.render_native import _transaction_snapshot

    operations = [{"name": "log_food",
                   "input": {"food_name": "Mackerel", "quantity": "100 g",
                             "calories": 180, "protein": 20}}]
    call = SimpleNamespace(name="log_food", committed=True,
                           raw_input=dict(operations[0]["input"]),
                           receipt={"calories": 305.0, "protein": 33.0,
                                    "entry_id": 7})
    # ⛔ THE TOTALS ARE CARRIED, NOT SUMMED HERE. C3 failed the first version of
    # this seam for computing them in the renderer; `MealCommitResult` owns them.
    snapshot = SimpleNamespace(
        execution=SimpleNamespace(calls=(call,),
                                  meal_totals={"calories": 305.0,
                                               "protein": 33.0}),
        day_totals={"calories": 305, "protein": 33},
        remaining_targets={"calories": 1695, "protein": 147})

    rendered = _transaction_snapshot(snapshot, operations)

    assert rendered.batch_cal == 305, (
        f"the reply would narrate {rendered.batch_cal} cal over a row "
        f"committed at 305 — the proposal beat the committed state")
    assert rendered.batch_protein == 33
    assert rendered.logged == ("Mackerel",)


def test_a_legacy_execution_without_receipts_still_uses_compute_batch():
    """⚠ THE FALLBACK IS UNCHANGED. A receipt exists only where a writer
    recorded one, so the legacy path must take exactly the branch it always
    took — this fix may not quietly re-price legacy turns."""
    from types import SimpleNamespace

    from core.turns.stages.render_native import _transaction_snapshot

    operations = [{"name": "log_food",
                   "input": {"food_name": "Toast", "calories": 90,
                             "protein": 3}}]
    call = SimpleNamespace(name="log_food", committed=True,
                           raw_input=dict(operations[0]["input"]),
                           receipt=None)
    snapshot = SimpleNamespace(
        execution=SimpleNamespace(calls=(call,), meal_totals=None),
        day_totals={"calories": 90, "protein": 3},
        remaining_targets={"calories": 1910, "protein": 177})

    assert _transaction_snapshot(snapshot, operations).batch_cal == 90


def test_a_positional_mismatch_raises_rather_than_reporting_nothing_committed():
    """⛔⛔ UNKNOWN IS NOT ZERO, AND THIS HAS BEEN WRONG IN BOTH DIRECTIONS.

    v1 logged "pairing is unsafe" and paired anyway ([A,B,C] vs [A,C] could
    produce B -> C's entry_id). v2 returned an EMPTY view — which is not
    silence: `affected_entities` reads committed calls only, so an empty view
    reports no affected entities, the renderer returns None, and the turn
    finalises as though NOTHING WAS WRITTEN over a meal that is already
    durable. An absent answer must never be representable as a negative one.
    """
    from core.general_settlement import ExecutionViewMismatch, execution_view

    result = SimpleNamespace(
        committed_items=[{"entry_id": 1, "calories": 10.0, "protein": 1.0},
                         {"entry_id": 3, "calories": 30.0, "protein": 3.0}],
        meal_totals={"calories": 40.0, "protein": 4.0})
    items = [{"food_name": "A"}, {"food_name": "B"}, {"food_name": "C"}]

    with pytest.raises(ExecutionViewMismatch):
        execution_view(result, items)


def test_the_committed_totals_flow_from_the_producer_into_the_renderer():
    """⛔⛔ THE DATAFLOW, NOT THE FIELD NAME. The mackerel test above builds a
    snapshot BY HAND, so it proves the renderer READS `meal_totals` — never
    that `execution_view` WRITES one. Rename the producer's field and that test
    stays green while the reply silently reverts to narrating the model's
    proposal.

    This one consumes exactly what the producer emits: the object under test is
    `execution_view`'s own return value, unmodified.
    """
    from core.general_settlement import execution_view
    from core.turns.stages.render_native import _transaction_snapshot

    items = [{"food_name": "Mackerel", "quantity": "100 g",
              "calories": 180, "protein": 20}]          # the model's PROPOSAL
    result = SimpleNamespace(
        committed_items=[{"entry_id": 7, "calories": 305.0, "protein": 33.0}],
        meal_totals={"calories": 305.0, "protein": 33.0})   # what COMMITTED

    view = execution_view(result, items)                # the producer

    operations = [{"name": "log_food", "input": dict(items[0])}]
    snapshot = SimpleNamespace(execution=view,          # <- no stand-in
                               day_totals={"calories": 305, "protein": 33},
                               remaining_targets={"calories": 1695,
                                                  "protein": 147})
    rendered = _transaction_snapshot(snapshot, operations)   # the consumer

    assert rendered.batch_cal == 305, (
        f"the producer's totals did not reach the renderer: narrated "
        f"{rendered.batch_cal} over a row committed at 305")
    assert rendered.batch_protein == 33
    assert rendered.logged == ("Mackerel",)


@pytest.mark.asyncio
async def test_a_failed_settlement_does_not_leave_a_stale_execution(monkeypatch):
    """⛔⛔ THE ANTI-STALE RULE THE LEGACY EXECUTOR ALREADY HONOURS. It sets
    LAST_EXECUTION to None up front so a batch that dies cannot leave the
    PREVIOUS turn's execution ambient. Seed a sentinel, force settlement to
    raise, and require the ambient value to be gone."""
    from types import SimpleNamespace

    import core.general_settlement as gs
    from core.execution_result import LAST_EXECUTION
    from core.turns.stages import execute_native as stage_module

    sentinel = SimpleNamespace(calls=("A PREVIOUS TURN",))
    LAST_EXECUTION.set(sentinel)

    class _Exploding:
        async def settle(self, db, **kwargs):
            raise PricingRefused("refused after entry")

    monkeypatch.setattr(gs, "settlement_cohort", lambda user_id=None: True)

    async def supported(db, *, user_id, items):
        return Supported("artifact", "covered")

    monkeypatch.setattr(gs, "coverage_for", supported)
    monkeypatch.setattr(gs, "GeneralSettlementOwner", lambda: _Exploding())

    stage = stage_module.NativeExecutionStage(executor=None)
    monkeypatch.setattr(stage, "_claim", lambda *a, **k: _true())

    ops = [{"name": "log_food", "input": {"food_name": "X", "quantity": "1 g"}}]
    with pytest.raises(PricingRefused):
        await stage.run(_request(db=object(), user=SimpleNamespace(id=26),
                                 today_log=object()),
                        validation=SimpleNamespace(approved_operations=ops))

    assert LAST_EXECUTION.get() is None, (
        "a failed settlement left the previous turn's execution ambient — the "
        "renderer would narrate a turn that did not happen")
