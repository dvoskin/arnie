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
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import current_identity
from db.database import AsyncSessionLocal
from db.queries import (
    add_body_metric,
    add_exercise_entry,
    add_food_entry,
    get_or_create_today_log,
    resolve_user,
)

router = APIRouter(prefix="/api/v1", tags=["quick-log"])


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
) -> dict:
    """Add one food entry to today's log + recompute the day totals."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        log = await get_or_create_today_log(db, user.id, user.timezone or "UTC")
        entry = await add_food_entry(
            db,
            daily_log_id=log.id,
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
        return {
            "ok": True,
            "entry_id": entry.id,
            "daily_log_id": log.id,
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
) -> dict:
    """Add one exercise entry to today's log + recompute the day totals."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        log = await get_or_create_today_log(db, user.id, user.timezone or "UTC")
        kwargs = payload.model_dump(exclude={"is_cardio", "exercise_name"}, exclude_none=True)
        kwargs["exercise_name"] = payload.exercise_name
        kwargs["source_type"] = "ios"
        entry = await add_exercise_entry(
            db,
            daily_log_id=log.id,
            is_cardio=payload.is_cardio,
            **kwargs,
        )
        return {
            "ok": True,
            "entry_id": entry.id,
            "daily_log_id": log.id,
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
) -> dict:
    """Record a body weight. Also updates `users.current_weight_kg` so the
    coaching engine sees the latest value immediately."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        metric = await add_body_metric(
            db,
            user_id=user.id,
            weight_kg=payload.weight_kg,
            context=payload.context,
            source=(payload.source or "manual"),
        )
        return {
            "ok": True,
            "metric_id": metric.id,
            "current_weight_kg": payload.weight_kg,
        }
