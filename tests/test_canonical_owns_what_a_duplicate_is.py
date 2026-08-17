"""⛔⛔ A12 — THE TWO SETTLEMENT OWNERS DISAGREED ABOUT WHAT A DUPLICATE IS.

Measured 2026-08-17 by driving one message three times through the real turn:

    legacy branch     1 row, 2 refusals   (claim_processed_turn, 60 minutes)
    canonical branch  3 rows              (the operation id was the TURN id, so
                                           a retyped message is a new operation)

The turn id absorbs a REDELIVERY and nothing else. So promoting a user from
legacy to canonical silently changed what happens when they send the same thing
twice — a user invariant, not an implementation detail. **The migration was the
one that moved, so the migration is what gets corrected.**

⭐ IDENTITY IS THE USER'S MESSAGE; REVISION IS WHICH OCCURRENCE. `meal_commits`
is already unique on (operation_id, operation_revision), so canonical needs no
second claim and no new table — and nothing from legacy is imported.

⭐⭐ AND KEYING ON THE MESSAGE RATHER THAN THE PLAN CLOSES THE OTHER HOLE IN THE
SAME MOVE. The legacy key fingerprints `input["food_name"]` verbatim, so the
same three sends produced "White rice" once and "White Rice" once and the third
slipped through a guard working exactly as written. A key that depends on model
output is only as stable as the model.

⚠ WHAT THIS DELIBERATELY DOES NOT DECIDE: whether a day-clear should drop its
claims. The window is legacy's 60 minutes, unchanged, so this slice moves WHO
decides and not WHAT is decided.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from core.general_settlement import (DUPLICATE_WINDOW_SEC, DuplicateMeal,
                                     GeneralSettlementOwner, meal_identity,
                                     meal_surface, occurrence_for)
from tests.test_a_full_day_of_food import app_db, seeded  # noqa: F401


# ══ the identity, pure ══════════════════════════════════════════════════════

def test_case_and_spacing_do_not_make_a_second_meal():
    assert meal_surface("100g of White Rice") == meal_surface(
        "  100G  of white   rice ")


def test_a_different_sentence_is_a_different_meal():
    """⭐ NORMALISATION IS NOT UNDERSTANDING. Word order and content still
    separate meals — someone who types the second sentence meant to."""
    assert meal_surface("chicken and rice") != meal_surface("rice and chicken")
    assert meal_surface("100g of white rice") != meal_surface(
        "200g of white rice")


def test_the_same_message_in_any_casing_is_one_identity():
    a = meal_identity(26, source_text="100g of white rice",
                      source_turn_id="ios:A")
    b = meal_identity(26, source_text="100G Of White Rice",
                      source_turn_id="ios:B")
    assert a == b, "the identity moved with the casing, or with the turn id"


def test_two_users_typing_the_same_words_never_share_a_meal():
    """⛔⛔ THE SCOPING GUARD, AND IT MATTERS MORE NOW THAN IT DID.

    `meal_commits` is unique on (operation_id, revision) and deliberately
    excludes `user_id`, and `_load` looks up by id alone — so the id must carry
    the scope. With the identity a hash of the MESSAGE, two users typing the
    same sentence produce the same digest; without user scoping the second
    would be handed the first's committed result and write no row of its own.
    """
    assert meal_identity(26, source_text="100g of white rice",
                         source_turn_id="ios:A") != \
           meal_identity(27, source_text="100g of white rice",
                         source_turn_id="ios:A")


def test_a_message_less_meal_falls_back_to_transport_identity():
    """⚠ AN ABSENT MESSAGE MUST NOT BE REPRESENTABLE AS A SHARED IDENTITY.

    Hashing an empty surface would give every text-less meal ONE identity, and
    a photo log would be handed a tap's committed result. Absence degrades to
    the turn id — which is what this path had before — never to a collision.
    """
    a = meal_identity(26, source_text="", source_turn_id="ios:A")
    b = meal_identity(26, source_text="   ", source_turn_id="ios:B")
    assert a != b, "two text-less meals collapsed onto one identity"


# ══ the occurrence, against a real schema (dual-engine via app_db) ═══════════

async def _commit_row(operation_id, *, revision=0, user_id=1, payload=None,
                      age_seconds=0.0):
    """One `meal_commits` row, aged by writing `created_at` explicitly."""
    import db.database as D
    from core import clock
    from db.models import MealCommit

    async with D.AsyncSessionLocal() as s:
        s.add(MealCommit(operation_id=operation_id, operation_revision=revision,
                         user_id=user_id,
                         status="committed" if payload else "claimed",
                         result_payload=payload,
                         created_at=clock.now() - timedelta(seconds=age_seconds)))
        await s.commit()


def _payload():
    """A stored result the loader will actually decode — an undecodable one
    would read as 'no result' and quietly turn a duplicate into a fresh claim,
    which is the assertion inverted."""
    from core.meal_commit import MealCommitResult, encode_result
    return encode_result(MealCommitResult(committed_items=(), meal_totals={}))


@pytest.mark.asyncio
async def test_the_first_send_of_a_meal_claims_revision_zero(app_db):  # noqa: F811
    import db.database as D

    async with D.AsyncSessionLocal() as s:
        assert await occurrence_for(s, operation_id="general:1:meal:none") \
            == (0, None)


@pytest.mark.asyncio
async def test_a_repeat_inside_the_window_replays_rather_than_claiming(app_db):  # noqa: F811
    import db.database as D

    await _commit_row("general:1:meal:inside", payload=_payload(),
                      age_seconds=DUPLICATE_WINDOW_SEC / 2)
    async with D.AsyncSessionLocal() as s:
        revision, replay = await occurrence_for(
            s, operation_id="general:1:meal:inside")

    assert revision == 0
    assert replay is not None, (
        "a repeat inside the window was handed a fresh claim — canonical would "
        "write the meal a second time")


@pytest.mark.asyncio
async def test_the_same_meal_after_the_window_is_a_new_occurrence(app_db):  # noqa: F811
    """⭐ THE NEGATIVE TWIN OF THE DUPLICATE RULE. A guard that refuses forever
    is not idempotency, it is a ban: eating the same lunch tomorrow has to log.
    """
    import db.database as D

    await _commit_row("general:1:meal:outside", payload=_payload(),
                      age_seconds=DUPLICATE_WINDOW_SEC + 60)
    async with D.AsyncSessionLocal() as s:
        revision, replay = await occurrence_for(
            s, operation_id="general:1:meal:outside")

    assert (revision, replay) == (1, None), (
        "the same meal an hour later could not be logged again")


@pytest.mark.asyncio
async def test_a_claim_with_no_result_is_occupied_not_absent(app_db):  # noqa: F811
    """⚠ IN FLIGHT IS NOT AVAILABLE. A durable claim with no recorded result
    means another writer may still be running. Handing this send the NEXT
    revision would let both write; returning the same one makes it meet
    `CommitInProgress`, which is the existing and louder answer.
    """
    import db.database as D

    await _commit_row("general:1:meal:inflight", payload=None, age_seconds=1)
    async with D.AsyncSessionLocal() as s:
        assert await occurrence_for(
            s, operation_id="general:1:meal:inflight") == (0, None)


# ══ through the owner, end to end ═══════════════════════════════════════════

def _artifact_food():
    from skills.nutrition.pricing_artifact import _artifact, evidence_for
    entity = next((str(i).split("|")[0]
                   for i in (getattr(_artifact(), "entries", None) or {})
                   if evidence_for(str(i).split("|")[0], "") is not None), None)
    assert entity, "the artifact is empty — this gate cannot settle anything"
    return entity


async def _settle(user_id, *, text, turn_id, food, name=None):
    import db.database as D
    from db.queries import reload_user

    async with D.AsyncSessionLocal() as s:
        user = await reload_user(s, user_id)
        result = await GeneralSettlementOwner().settle(
            s, user=user, items=[{"food_name": name or food,
                                  "food_hint": food, "quantity": "100 g"}],
            source_turn_id=turn_id, source_text=text)
        await s.commit()
        return result


async def _food_rows(user_id):
    import db.database as D
    from sqlalchemy import func, select
    from db.models import DailyLog, FoodEntry

    async with D.AsyncSessionLocal() as s:
        return int((await s.execute(
            select(func.count()).select_from(FoodEntry)
            .join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
            .where(DailyLog.user_id == user_id))).scalar() or 0)


@pytest.mark.asyncio
async def test_the_same_message_retyped_settles_once(app_db, seeded):  # noqa: F811
    """⛔⛔ THE INVARIANT THE MIGRATION WAS BREAKING. Legacy refuses this;
    canonical wrote a second row. Now both refuse, and canonical decides it."""
    food = _artifact_food()

    first = await _settle(seeded, text="100g of white rice",
                          turn_id="ios:one", food=food)
    assert first.committed_items, "the first send wrote nothing — vacuous gate"

    with pytest.raises(DuplicateMeal):
        await _settle(seeded, text="100g of white rice",
                      turn_id="ios:two", food=food)

    assert await _food_rows(seeded) == 1, (
        "a retyped identical message wrote a second row — the canonical owner "
        "still disagrees with legacy about what a duplicate is")


@pytest.mark.asyncio
async def test_the_models_capitalisation_cannot_defeat_the_guard(app_db,  # noqa: F811
                                                                 seeded):  # noqa: F811
    """⛔ THE EXACT SHAPE THAT SLIPPED THROUGH IN THE PRODUCTION TRIPLE.

    Send 1 planned `"White rice"`, send 3 planned `"White Rice"`, and the legacy
    key — which fingerprints the plan — missed. Canonical keys on the message,
    so the plan may vary however the model likes.
    """
    food = _artifact_food()

    await _settle(seeded, text="100g of white rice", turn_id="ios:one",
                  food=food, name=food.lower())
    with pytest.raises(DuplicateMeal):
        await _settle(seeded, text="100g of white rice", turn_id="ios:two",
                      food=food, name=food.upper())

    assert await _food_rows(seeded) == 1


@pytest.mark.asyncio
async def test_a_different_message_still_settles(app_db, seeded):  # noqa: F811
    """⭐ THE TWIN THAT KEEPS THE GUARD FROM BEING A BAN. A rule that refuses
    everything after the first meal would pass every duplicate assertion above.
    """
    food = _artifact_food()

    await _settle(seeded, text="100g of white rice", turn_id="ios:one",
                  food=food)
    await _settle(seeded, text="200g of white rice", turn_id="ios:two",
                  food=food)

    assert await _food_rows(seeded) == 2, (
        "a genuinely different message was refused as a duplicate")


@pytest.mark.asyncio
async def test_the_duplicate_is_refused_before_anything_is_priced(app_db,  # noqa: F811
                                                                  seeded,  # noqa: F811
                                                                  monkeypatch):
    """⛔ NON-MUTATING BY CONSTRUCTION, AND FREE. A meal already on the board
    must not pay for a second resolution — and a refusal that ran the pricer is
    a refusal that was one exception away from writing.
    """
    food = _artifact_food()
    await _settle(seeded, text="100g of white rice", turn_id="ios:one",
                  food=food)

    priced = []

    async def _spy(self, db, *, user, item):
        priced.append(item)
        raise AssertionError("the pricer ran on a duplicate")

    monkeypatch.setattr(GeneralSettlementOwner, "_price", _spy)
    with pytest.raises(DuplicateMeal):
        await _settle(seeded, text="100g of white rice", turn_id="ios:two",
                      food=food)
    assert priced == []


# ══ one duplicate, one presentation ═════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_user_cannot_tell_which_owner_refused_the_duplicate():
    """⭐ ONE DUPLICATE, ONE ANSWER, WHICHEVER OWNER SETTLED THE TURN.

    Legacy refuses through `claim_processed_turn` (`ExactlyOnceRefusal`);
    canonical refuses through its own occurrence check (`DuplicateMeal`). The
    entrypoint absorbs both into "Already logged that one."

    ⚠ AND THE RENAME IS NOT IN THE STAGE. A8's AST gate forbids any except
    handler in `NativeExecutionStage.run`, because a handler around settlement
    is how a canonical refusal reaches the legacy executor. It refused the first
    version of this slice; the absorption moved here instead.
    """
    import types

    import core.turns.factory as F
    from core.recovery import is_recovery_text
    from core.turns.entrypoint import run_turn
    from core.turns.models import TurnRequest
    from core.turns.stages.execute_native import ExactlyOnceRefusal

    request = TurnRequest(turn_id="ios:DUP", user_id=26, platform="ios",
                          source_type="ios", text="100g of white rice",
                          metadata={})

    async def _answer(error):
        state = types.SimpleNamespace(
            error=error, execution=None, response=None, request=request,
            health_flags=(), snapshot=None, validation=None)

        class _Coordinator:
            route_stage = types.SimpleNamespace(decision=None)

            async def run(self, req):
                return state

        async def _build(req, **kwargs):
            return _Coordinator()

        import pytest as _pytest
        with _pytest.MonkeyPatch.context() as mp:
            mp.setattr(F, "build_coordinator", _build)
            result = await run_turn(request=request)
        return [b for b in
                (getattr(getattr(result, "response", None), "bubbles", None)
                 or []) if (b or "").strip()]

    legacy = await _answer(ExactlyOnceRefusal("ios:DUP"))
    canonical = await _answer(DuplicateMeal("general:26:meal:abc", 0))

    assert canonical == legacy, (
        f"the two owners answer a duplicate differently: {legacy!r} vs "
        f"{canonical!r} — the user can tell which one settled the turn")
    assert canonical and not any(is_recovery_text(b) for b in canonical)
    assert "already logged" in " ".join(canonical).lower()


@pytest.mark.asyncio
async def test_settlement_is_never_wrapped_in_an_except():
    """⛔⛔ THE A8 GATE, RESTATED WHERE THIS SLICE COULD HAVE BROKEN IT.

    `test_a8_the_native_stage_does_not_catch_around_settlement` already asserts
    this and caught the first version of this change. Repeated here because the
    temptation is specific to A12: renaming canonical's duplicate signal at the
    seam is a one-line edit that reads harmless and re-opens the fallback.
    """
    import ast
    import inspect

    from core.turns.stages.execute_native import NativeExecutionStage

    tree = ast.parse(inspect.getsource(NativeExecutionStage.run).lstrip())
    assert not [n for n in ast.walk(tree)
                if isinstance(n, ast.ExceptHandler)], (
        "settlement is wrapped in an except again — a canonical refusal can "
        "reach the legacy executor")


@pytest.mark.asyncio
async def test_a_canonical_duplicate_leaves_no_stale_execution():
    """⚠ THE RENDERER READS `LAST_EXECUTION`. A refusal raised after a previous
    turn's execution was left ambient would narrate that turn's meal as this
    one's — the stale-read class this stage clears for at the top."""
    from types import SimpleNamespace

    from core.execution_result import LAST_EXECUTION
    from core.turns.models import TurnRequest
    from core.turns.stages.execute_native import NativeExecutionStage

    LAST_EXECUTION.set(SimpleNamespace(calls=(), meal_totals={"calories": 999}))

    class _Owner:
        async def settle(self, db, **kwargs):
            raise DuplicateMeal("general:26:meal:abc", 0)

    stage = NativeExecutionStage()

    async def _route(db, user, ops):
        return _Owner(), None

    stage._canonical_route = _route
    request = TurnRequest(turn_id="ios:DUP", user_id=26, platform="ios",
                          source_type="ios", text="100g of white rice",
                          metadata={"db": object(),
                                    "user": SimpleNamespace(id=26)})
    with pytest.raises(DuplicateMeal):
        await stage.run(request, route=None, validation=SimpleNamespace(
            approved_operations=({"name": "log_food", "input": {}},)))

    assert LAST_EXECUTION.get() is None, (
        "a duplicate left the previous turn's execution ambient")


# ══ the legacy boundary, normalised at the same contract ════════════════════

def test_the_legacy_key_no_longer_moves_with_the_models_capitalisation():
    from core.food_ledger import turn_idempotency_key

    def key(name):
        return turn_idempotency_key(
            26, "100g of white rice",
            [{"name": "log_food", "input": {"food_name": name,
                                            "quantity": "100 g"}}])

    assert key("White rice") == key("White Rice") == key("  white   rice  ")


def test_the_legacy_key_still_separates_genuinely_different_plans():
    """⭐ THE TWIN. Normalising to the point where every plan matches would pass
    the test above and refuse every second meal in the product."""
    from core.food_ledger import turn_idempotency_key

    def key(**inp):
        return turn_idempotency_key(
            26, "eggs", [{"name": "log_food", "input": inp}])

    assert key(food_name="eggs", quantity="2") != \
        key(food_name="eggs", quantity="3")
    assert key(food_name="eggs", quantity="2") != \
        key(food_name="egg whites", quantity="2")
