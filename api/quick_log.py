"""
Manual quick-log REST endpoints for the iOS native app.

Three thin wrappers around the same query helpers the chat-side logging
tools (`log_food`, `log_exercise`, `log_weight`) use, so a tap on a Today
"+ Add" button and a chat "had a banana" land in the same canonical rows.

Endpoints:
  POST /api/v1/food      — direct food entry (caller supplies macros)
  POST /api/v1/exercise  — direct exercise entry (sets/reps/load or cardio)
  POST /api/v1/weight    — body weight (kg)

USDA enrichment, intent classification, and conversational logging behavior
all stay on the chat path. These endpoints are for the explicit
"the user typed the values, just write them" flow.

A TAP IS A TURN — literally, not as a slogan
────────────────────────────────────────────
`record_ledger_event` stamps the canonical turn id from the ambient contextvar
(`core.turn_identity.CURRENT_TURN_ID`). Every chat surface sets it. These
endpoints did not, so on deployed 433cdf39f2d0 every tap-logged event landed
with `turn_id = NULL` — a canonical row that could not be joined to the request
that caused it, on the primary iOS logging surface. Each handler now opens a
turn scope before it writes.

The same request delivered twice — a double tap, a retry on a flaky network, an
OS-level replay — used to write the food twice (measured: two taps, two rows).
Clients send `Idempotency-Key`; the write is claimed against it and a replay
returns the ORIGINAL committed result. An ABSENT key deduplicates nothing on
purpose: only the client can tell a retry from a second helping, and dropping
food the user really ate is the worse failure.
"""
import logging
from contextlib import contextmanager
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from api.auth import current_identity
from core.commit_coordinator import CommitInProgress
from core.idempotency import (
    IdempotencyConflict,
    IdempotencyInProgress,
    claim_request,
    complete_claim,
)
from core.request_trace import RequestTrace
from core.turn_identity import CURRENT_TURN_ID, make_turn_id
from db.database import AsyncSessionLocal
from db.queries import (
    add_body_metric,
    add_exercise_entry,
    get_or_create_today_log,   # exercise + weight; food is canonical now
    resolve_user,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["quick-log"])

CHANNEL = "ios"


@contextmanager
def _turn_scope(turn_id: str):
    """Bind the canonical turn identity for the life of this request.

    Reset in `finally` — the endpoint runs on a shared worker task, and a
    leaked contextvar would stamp the NEXT request's writes with this turn.
    """
    token = CURRENT_TURN_ID.set(turn_id)
    try:
        yield
    finally:
        CURRENT_TURN_ID.reset(token)


def _client_key(raw) -> Optional[str]:
    """The client's idempotency key, or None.

    FastAPI resolves `Header(...)` before calling the handler, but a DIRECT
    call — tests, and any internal caller reusing these handlers — receives the
    unresolved `FieldInfo` default instead. Stringifying that produced a turn
    id of `ios:annotation=Union[str, NoneType] required=False...`, which is
    worse than the null it replaced: a unique-looking id that is really the
    same for every keyless request, so two unrelated taps would collide on it.

    Anything that is not a non-empty string is absent.
    """
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def _claim_failed(exc: Exception, command: str) -> HTTPException:
    """Both failures are 409, and the client treats them differently: a
    conflict is a bug to report, an in-flight claim is a retry to repeat."""
    if isinstance(exc, IdempotencyConflict):
        return HTTPException(
            status_code=409,
            detail={"error": "idempotency_conflict", "command": command,
                    "message": "This Idempotency-Key was already used for a "
                               "different request."})
    return HTTPException(
        status_code=409,
        detail={"error": "request_in_progress", "command": command,
                "retryable": True,
                "message": "The original delivery of this request is still "
                           "running."})


# ── Food ────────────────────────────────────────────────────────────────────


class FoodLogBody(BaseModel):
    """Manual food entry — every field the user can pick on a Today add
    sheet. Macros required (server doesn't second-guess; it's an explicit
    log)."""
    food_name: str = Field(min_length=1, max_length=200)
    quantity: Optional[str] = None
    calories: float = Field(ge=0, le=10_000)
    protein: float = Field(ge=0, le=500)
    carbs: float = Field(ge=0, le=1_500)
    fats: float = Field(ge=0, le=500)
    meal_type: Optional[Literal["breakfast", "lunch", "dinner", "snack"]] = None


@router.post("/food")
async def log_food_entry(
    payload: FoodLogBody,
    identity: str = Depends(current_identity),
    client_request_id: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> dict:
    """Add one food entry to today's log + recompute the day totals."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        client_key = _client_key(client_request_id)
        turn_id = make_turn_id(CHANNEL, client_key, user.id,
                               f"{payload.food_name}|{payload.quantity or ''}")
        # One line per request, keyed on the SAME turn id the ledger event
        # carries — so the trace and the row it describes join without a
        # correlation step. This surface emitted nothing at all before.
        with RequestTrace(turn_id=turn_id, channel=CHANNEL,
                          command="log_food", user_id=user.id) as trace:
            trace.note(keyed=bool(client_key))
            try:
                with trace.stage("claim"):
                    claim = await claim_request(
                        db, channel=CHANNEL, command="log_food",
                        user_id=user.id, client_key=client_key,
                        payload=payload, turn_id=turn_id)
            except (IdempotencyConflict, IdempotencyInProgress) as e:
                trace.note(idempotency=type(e).__name__)
                trace.done(outcome="conflict")
                raise _claim_failed(e, "log_food")

            if claim.replay:
                trace.note(idempotency="replay",
                           entry=claim.stored_result.get("entry_id"))
                return {"ok": True, "idempotent_replay": True,
                        "turn_id": claim.turn_id, **claim.stored_result}
            trace.note(idempotency="claimed" if claim.key else "unkeyed")

            try:
                return await _write_food(db, user, payload, turn_id, claim,
                                         trace)
            except CommitInProgress:
                # The COORDINATOR's version of "the original is still
                # running": a durable commit claim with no recorded result.
                # In the promoted flow the claim, rows, result and completion
                # share one transaction, so this is reachable only while
                # another delivery is mid-write — the same situation the
                # idempotency layer answers with a retryable 409, and the two
                # layers must speak with one voice.
                trace.note(commit="in_progress")
                trace.done(outcome="conflict")
                raise HTTPException(
                    status_code=409,
                    detail={"error": "request_in_progress",
                            "command": "log_food", "retryable": True,
                            "message": "The original delivery of this request "
                                       "is still being committed."})


async def _write_food(db, user, payload, turn_id, claim, trace) -> dict:
    """The committed half, on the canonical spine.

    PROMOTED (Phase 1, step 1): this is the first production mutation owner on

        ResolvedMeal -> commit_or_load_existing -> write_canonical_meal
                     -> MealCommitResult

    The legacy `add_food_entry` call this replaces committed per row and
    completed the claim via a side channel. Here the food rows, their ledger
    event, the immutable result and the claim completion land in ONE
    transaction, and a duplicate delivery — client retry or crash replay —
    receives the original result from `meal_commits` rather than re-running.

    A tap was the right first owner because it is already canonical-shaped:
    one item, priced by the client, no clarification, and the day resolved
    here from the user's timezone.
    """
    from core.canonical_writer import DirectOperation, write_canonical_meal
    from core.commit_coordinator import commit_or_load_existing
    from db.queries import _invalidate_briefing_for_log

    with trace.stage("write"), _turn_scope(turn_id):
        meal = _resolved_meal(user, payload, turn_id)
        result = await commit_or_load_existing(
            db, operation=DirectOperation(meal), resolved_meal=meal,
            writer=write_canonical_meal)
        item = result.committed_items[0]
        # The claim completes INSIDE this transaction, same as before the
        # promotion — completing it afterwards left a window where the meal
        # was committed and the claim was not, and a retry took the stale
        # claim over and wrote the meal again.
        await complete_claim(db, claim, entry_id=item["entry_id"],
                             daily_log_id=item["daily_log_id"], commit=False)
        await db.commit()

    # POST-COMMIT WORK, AS DATA. The writer returns what must happen after the
    # commit rather than doing it — dropping the briefing cache while the rows
    # were still invisible would let a concurrent Coach open repopulate it
    # from pre-write state.
    for action in result.render_actions:
        if action.get("action") == "invalidate_briefing":
            _invalidate_briefing_for_log(int(action["user_id"]), by_user=True)

    trace.note(entry=item["entry_id"], claim="completed_in_txn")
    trace.done()
    await trace.persist(db)
    return {
        "ok": True,
        "entry_id": item["entry_id"],
        "daily_log_id": item["daily_log_id"],
        "turn_id": turn_id,
    }


def _resolved_meal(user, payload, turn_id):
    """One tap as a validated canonical meal.

    A TAP IS THE USER'S OWN STATEMENT: they chose the food and the numbers on
    their screen, so it is resolved by construction rather than by a matcher's
    opinion, and priced by the client rather than by the resolver.
    """
    from core.canonical_writer import (MealIntent, ResolvedFood, ResolvedMeal,
                                       operation_id_for)
    from core.semantics import (CanonicalEvent, Confidence, Provenance,
                                ResolutionStatus)
    from core.timezones import safe_timezone
    from db.queries import _user_today

    # THE ZONE THAT ACTUALLY PRODUCES THE DAY, not the raw column.
    # `safe_timezone` degrades junk to UTC — right for a read path, and
    # recorded here as a WARNING rather than a silence, because a meal filed
    # on UTC days for a user who is not on UTC is wrong in the one direction
    # nobody checks. `_user_today` applies the same degradation plus the
    # 4am rollover, so the day is exactly the one the legacy path chose.
    zone = str(getattr(safe_timezone(user.timezone), "zone", "UTC"))
    warnings = ()
    if (user.timezone or "") and zone != user.timezone:
        warnings = (f"stored timezone {user.timezone!r} is not a valid IANA "
                    f"zone; the logging day was computed in {zone}",)

    return ResolvedMeal(
        operation_id=operation_id_for("quick_log", user.id, turn_id),
        revision=0, user_id=user.id,
        logging_day=_user_today(user.timezone or "UTC"),
        user_timezone=zone,
        intent=MealIntent.CREATE, source_turn_id=turn_id,
        meal_type=payload.meal_type, warnings=warnings,
        items=(ResolvedFood(
            event=CanonicalEvent(
                id=f"{turn_id}:0", domain="food",
                entity_id="", surface_text=payload.food_name,
                resolution_status=ResolutionStatus.RESOLVED,
                provenance=Provenance.USER_SELECTED,
                confidence=Confidence(score=1.0, basis="user_selected")),
            calories=payload.calories, protein=payload.protein,
            carbs=payload.carbs, fats=payload.fats,
            quantity_text=payload.quantity or "",
            meal_type=payload.meal_type, source_type="ios",
            raw_input=payload.food_name),))


# ── Exercise ────────────────────────────────────────────────────────────────


class ExerciseLogBody(BaseModel):
    """Manual exercise entry. Caller signals cardio via `is_cardio`;
    strength entries provide sets/reps/load."""
    exercise_name: str = Field(min_length=1, max_length=200)
    is_cardio: bool = False
    sets: Optional[int] = Field(None, ge=1, le=100)
    reps: Optional[str] = None         # CSV "5,5,5" — supports per-set variation
    weight: Optional[float] = Field(None, ge=0, le=1_000)
    weights: Optional[str] = None      # CSV per-set load
    duration_minutes: Optional[int] = Field(None, ge=0, le=480)
    cardio_type: Optional[str] = None
    rir: Optional[int] = Field(None, ge=0, le=20)
    notes: Optional[str] = None
    calories_burned_estimate: Optional[float] = Field(None, ge=0, le=5_000)


@router.post("/exercise")
async def log_exercise_entry(
    payload: ExerciseLogBody,
    identity: str = Depends(current_identity),
    client_request_id: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> dict:
    """Add one exercise entry to today's log + recompute the day totals."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        client_key = _client_key(client_request_id)
        turn_id = make_turn_id(CHANNEL, client_key, user.id,
                               payload.exercise_name)
        with RequestTrace(turn_id=turn_id, channel=CHANNEL,
                          command="log_exercise", user_id=user.id) as trace:
            trace.note(keyed=bool(client_key))
            try:
                with trace.stage("claim"):
                    claim = await claim_request(
                        db, channel=CHANNEL, command="log_exercise",
                        user_id=user.id, client_key=client_key,
                        payload=payload, turn_id=turn_id)
            except (IdempotencyConflict, IdempotencyInProgress) as e:
                trace.note(idempotency=type(e).__name__)
                trace.done(outcome="conflict")
                raise _claim_failed(e, "log_exercise")

            if claim.replay:
                trace.note(idempotency="replay",
                           entry=claim.stored_result.get("entry_id"))
                return {"ok": True, "idempotent_replay": True,
                        "turn_id": claim.turn_id, **claim.stored_result}
            trace.note(idempotency="claimed" if claim.key else "unkeyed")

            kwargs = payload.model_dump(exclude={"is_cardio", "exercise_name"},
                                        exclude_none=True)
            kwargs["exercise_name"] = payload.exercise_name
            kwargs["source_type"] = "ios"
            with trace.stage("write"), _turn_scope(turn_id):
                log = await get_or_create_today_log(db, user.id,
                                                    user.timezone or "UTC")
                # ONE ledger writer — `add_exercise_entry` records the
                # `created` event itself (master audit 2026-07-30: this
                # endpoint's second record made every tap-logged set a
                # duplicate operation). The provenance label rides through
                # instead, and `claim_id` puts the row, its event and the
                # claim in one transaction.
                entry = await add_exercise_entry(
                    db,
                    daily_log_id=log.id,
                    is_cardio=payload.is_cardio,
                    ledger_source="quick_log:ios",
                    claim_id=claim.record_id,
                    **kwargs,
                )

            trace.note(entry=entry.id, claim="completed_in_txn")
            trace.done()
            await trace.persist(db)
            return {
                "ok": True,
                "entry_id": entry.id,
                "daily_log_id": log.id,
                "turn_id": turn_id,
            }


# ── Weight ──────────────────────────────────────────────────────────────────


class WeightLogBody(BaseModel):
    """Body weight (kg). iOS converts lbs → kg client-side."""
    weight_kg: float = Field(gt=20, lt=400)
    context: Optional[str] = None   # "morning", "post-workout", etc.
    # "manual" = the user typed/confirmed it in the app (the headline number);
    # "apple_health" = a passive HealthKit observer sync. Defaults to manual so
    # the existing app weigh-in flow is unchanged; the future HealthKit observer
    # sends "apple_health" so its readings never clobber a deliberate weigh-in.
    source: Optional[str] = None


@router.post("/weight")
async def log_weight(
    payload: WeightLogBody,
    identity: str = Depends(current_identity),
    client_request_id: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> dict:
    """Record a body weight. Also updates `users.current_weight_kg` so the
    coaching engine sees the latest value immediately.

    `add_body_metric` already collapses to one row per (user, logging day,
    source), so weight is the one surface a retry could not duplicate. The
    claim is still taken: it makes the replay return the same answer, and it
    keeps one contract across all three endpoints rather than a special case
    someone has to remember.
    """
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        client_key = _client_key(client_request_id)
        turn_id = make_turn_id(CHANNEL, client_key, user.id,
                               f"weight:{payload.weight_kg}")
        with RequestTrace(turn_id=turn_id, channel=CHANNEL,
                          command="log_weight", user_id=user.id) as trace:
            trace.note(keyed=bool(client_key))
            try:
                with trace.stage("claim"):
                    claim = await claim_request(
                        db, channel=CHANNEL, command="log_weight",
                        user_id=user.id, client_key=client_key,
                        payload=payload, turn_id=turn_id)
            except (IdempotencyConflict, IdempotencyInProgress) as e:
                trace.note(idempotency=type(e).__name__)
                trace.done(outcome="conflict")
                raise _claim_failed(e, "log_weight")

            if claim.replay:
                trace.note(idempotency="replay",
                           entry=claim.stored_result.get("entry_id"))
                return {"ok": True, "idempotent_replay": True,
                        "turn_id": claim.turn_id,
                        "metric_id": claim.stored_result.get("entry_id"),
                        "current_weight_kg": payload.weight_kg}
            trace.note(idempotency="claimed" if claim.key else "unkeyed")

            with trace.stage("write"), _turn_scope(turn_id):
                metric = await add_body_metric(
                    db,
                    user_id=user.id,
                    weight_kg=payload.weight_kg,
                    context=payload.context,
                    source=(payload.source or "manual"),
                    # Weight now carries the same audit contract as food and
                    # exercise: a ledger event in the write's own transaction,
                    # holding the PRIOR reading so a correction stays undoable.
                    ledger_source="quick_log:ios",
                    claim_id=claim.record_id,
                )

            trace.note(entry=metric.id, claim="completed_in_txn")
            trace.done()
            await trace.persist(db)
            return {
                "ok": True,
                "metric_id": metric.id,
                "current_weight_kg": payload.weight_kg,
                "turn_id": turn_id,
            }
