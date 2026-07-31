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
from contextlib import contextmanager
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from api.auth import current_identity
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
    add_food_entry,
    get_or_create_today_log,
    resolve_user,
)

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

            return await _write_food(db, user, payload, turn_id, claim, trace)


async def _write_food(db, user, payload, turn_id, claim, trace) -> dict:
    """The committed half — split out so the handler above reads as one shape:
    identity, claim, write. Takes the trace rather than opening its own, so a
    request stays ONE line however many functions it passes through."""
    with trace.stage("write"), _turn_scope(turn_id):
        log = await get_or_create_today_log(db, user.id, user.timezone or "UTC")
        # A TAP IS A TURN (audit O-1). Without the `created` event
        # `ledger_undo` takes the last one unconditionally, so "undo that"
        # after a tap-log removed the previous CHAT-logged item — a row the
        # user never mentioned.
        #
        # `ledger_source` makes `add_food_entry` write that event inside the
        # row's OWN transaction, rather than this endpoint committing it
        # separately afterwards: two commits meant a crash between them left a
        # food row with no history at all. Written inside the turn scope
        # either way, so the event carries the turn id.
        entry = await add_food_entry(
            db,
            daily_log_id=log.id,
            user_id=user.id,
            ledger_source="quick_log:ios",
            # The claim completes INSIDE this transaction. Completing it
            # afterwards left a window where the meal was committed and the
            # claim was not, and a retry took the stale claim over and wrote
            # the meal again — the one failure the claim exists to prevent.
            claim_id=claim.record_id,
            raw_input=payload.food_name,
            parsed_food_name=payload.food_name,
            quantity=payload.quantity,
            calories=payload.calories,
            protein=payload.protein,
            carbs=payload.carbs,
            fats=payload.fats,
            meal_type=payload.meal_type,
            source_type="ios",
        )

    trace.note(entry=entry.id, claim="completed_in_txn")
    return {
        "ok": True,
        "entry_id": entry.id,
        "daily_log_id": log.id,
        "turn_id": turn_id,
    }


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
        try:
            claim = await claim_request(
                db, channel=CHANNEL, command="log_exercise", user_id=user.id,
                client_key=client_key, payload=payload, turn_id=turn_id)
        except (IdempotencyConflict, IdempotencyInProgress) as e:
            raise _claim_failed(e, "log_exercise")

        if claim.replay:
            return {"ok": True, "idempotent_replay": True,
                    "turn_id": claim.turn_id, **claim.stored_result}

        kwargs = payload.model_dump(exclude={"is_cardio", "exercise_name"},
                                    exclude_none=True)
        kwargs["exercise_name"] = payload.exercise_name
        kwargs["source_type"] = "ios"
        with _turn_scope(turn_id):
            log = await get_or_create_today_log(db, user.id,
                                                user.timezone or "UTC")
            # ONE ledger writer — `add_exercise_entry` records the `created`
            # event itself (master audit 2026-07-30: this endpoint's second
            # record made every tap-logged set a duplicate operation). The
            # provenance label rides through instead.
            entry = await add_exercise_entry(
                db,
                daily_log_id=log.id,
                is_cardio=payload.is_cardio,
                ledger_source="quick_log:ios",
                **kwargs,
            )

        await complete_claim(db, claim, entry_id=entry.id,
                             daily_log_id=log.id)
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
        try:
            claim = await claim_request(
                db, channel=CHANNEL, command="log_weight", user_id=user.id,
                client_key=client_key, payload=payload, turn_id=turn_id)
        except (IdempotencyConflict, IdempotencyInProgress) as e:
            raise _claim_failed(e, "log_weight")

        if claim.replay:
            return {"ok": True, "idempotent_replay": True,
                    "turn_id": claim.turn_id,
                    "metric_id": claim.stored_result.get("entry_id"),
                    "current_weight_kg": payload.weight_kg}

        with _turn_scope(turn_id):
            metric = await add_body_metric(
                db,
                user_id=user.id,
                weight_kg=payload.weight_kg,
                context=payload.context,
                source=(payload.source or "manual"),
            )

        await complete_claim(db, claim, entry_id=metric.id)
        return {
            "ok": True,
            "metric_id": metric.id,
            "current_weight_kg": payload.weight_kg,
            "turn_id": turn_id,
        }
