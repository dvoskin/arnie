"""
GET /api/v1/coach/live — the one contract every feed section reads.

THE POINT OF THIS ENDPOINT IS THAT IT IS THE ONLY ONE.

The Coach feed used to assemble itself from six independent fetches, each card
interpreting the day for itself. That is why a macro strip could say protein was
fine while the card below it said protein was the day's risk: nothing forced them
to agree, because nothing was shared except raw numbers.

This route is a pure ASSEMBLER. It gathers facts the app already stores, hands
them to `core.coach_live.compute` — which is deterministic, has no clock of its
own and no LLM — and serialises the result. Every interpretation lives there.
Nothing in this file decides what kind of day it is.

Cost: this is a CONSOLIDATION, not an addition. The client currently issues
`/day`, `/week`, `/fitness`, `/workout_program` and `/recovery` to build the same
screen; this issues the same reads once, server-side, and returns one answer.
"""
from datetime import datetime, timezone as _tz
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from api.auth import current_identity
from core import coach_live as engine
from db.database import AsyncSessionLocal
from db.queries import resolve_user

router = APIRouter(prefix="/api/v1/coach", tags=["coach"])


def _aware(value, tz: ZoneInfo):
    """Stored timestamps are naive UTC. Every hour-of-day rule in the engine
    reads the user's own zone, so a naive value handed straight in silently
    coaches someone in the wrong part of their day."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=_tz.utc)
    return value.astimezone(tz)


def _meals(day: dict | None, tz: ZoneInfo) -> tuple:
    if not day:
        return ()
    out = []
    for e in day.get("food_entries") or []:
        stamp = e.get("timestamp")
        if not stamp:
            # No timestamp means no position in the day, and therefore no way to
            # replay the state before it. Dropping it from the EVENT list costs
            # only the "what changed" line; the totals it contributed are read
            # from the day's own totals, so nothing is under-counted.
            continue
        try:
            at = _aware(datetime.fromisoformat(stamp), tz)
        except ValueError:
            continue
        out.append(engine.MealEvent(
            at=at,
            calories=int(e.get("calories") or 0),
            protein=int(e.get("protein") or 0),
            meal_type=e.get("meal_type"),
        ))
    return tuple(sorted(out, key=lambda m: m.at))


def _training_events(day: dict | None, tz: ZoneInfo) -> tuple:
    if not day:
        return ()
    out = []
    for e in day.get("exercise_entries") or []:
        stamp = e.get("timestamp")
        if not stamp:
            continue
        try:
            at = _aware(datetime.fromisoformat(stamp), tz)
        except ValueError:
            continue
        out.append(engine.TrainingEvent(
            at=at, name=e.get("name") or "",
            is_cardio=bool(e.get("is_cardio")),
        ))
    return tuple(sorted(out, key=lambda t: t.at))


async def _planned_session(db, user):
    """Today's session from the user's program, or `None` for UNKNOWN.

    Reuses `unified_active_program` + `infer_today` — the same pair the workout
    card reads — rather than re-deriving which day of the rotation it is. Two
    answers to "what am I training today" is how the card and the coach end up
    naming different sessions.

    Returns `(planned_name, is_rest_day)` where either may be None/unknown.
    """
    try:
        from api.workout_api import unified_active_program
        from core.program_rotation import infer_today, recent_entries_by_day
        from db.queries import _user_today

        program = await unified_active_program(db, user.id)
        if not program:
            return None, None      # no program: unknown, never "no workout"
        today_iso = _user_today(getattr(user, "timezone", None) or "UTC").isoformat()
        day, _done = infer_today(
            program, await recent_entries_by_day(db, user.id), today_iso)
        override = program.get("today_override") or {}
        if override.get("date") == today_iso and override.get("day"):
            if override["day"] == "__rest__":
                return None, True
            day = override["day"]
        # `infer_today` returning nothing means the rotation puts a rest here.
        return (day, False) if day else (None, True)
    except Exception:
        # A program-inference failure must degrade to SILENCE, not to a false
        # "you missed your workout".
        return None, None


async def _wearable(db, user, tz: ZoneInfo):
    """Connection + last sync, read from the one place that records it.

    `WearableDevice.last_sync_at` is what Whoop and Oura `/status` already
    report; HealthKit now writes it too (see `api.health_sync`). Reading the
    max across a user's devices means a Whoop user who also syncs a phone gets
    the more recent of the two, which is the honest answer to "is Arnie current".
    """
    from sqlalchemy import select

    from db.models import WearableDevice

    rows = (await db.execute(
        select(WearableDevice).where(WearableDevice.user_id == user.id)
    )).scalars().all()
    if not rows:
        return False, None, None
    synced = [r for r in rows if r.last_sync_at]
    if not synced:
        return True, None, (rows[0].device_type or None)
    newest = max(synced, key=lambda r: r.last_sync_at)
    return True, _aware(newest.last_sync_at, tz), (newest.device_type or None)


@router.get("/live")
async def get_coach_live(identity: str = Depends(current_identity)) -> dict:
    """The whole feed's state, interpreted once."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        tz = ZoneInfo(getattr(user, "timezone", None) or "UTC")
        now = datetime.now(tz)

        from api.native_data import day_data, fitness_data, week_data

        day_payload = await day_data(db, user)
        week_payload = await week_data(db, user)
        fitness_payload = await fitness_data(db, user)

        day = day_payload.get("day") or {}
        targets = day_payload.get("targets") or {}
        health = day_payload.get("health") or {}

        planned, is_rest = await _planned_session(db, user)
        connected, synced_at, source = await _wearable(db, user, tz)

        # Readiness comes from `core.coaching_state`, which already owns it.
        # Re-deriving it here would be a second opinion nobody asked for.
        readiness = training_rec = None
        try:
            from core.coaching_state import compute_coaching_state
            from db.queries import get_recent_health_snapshots, get_recent_logs
            snaps = await get_recent_health_snapshots(db, user.id, days=7)
            logs = await get_recent_logs(db, user.id, days=7)
            cs = compute_coaching_state(snaps, logs, user)
            if cs.readiness != "unknown":
                readiness, training_rec = cs.readiness, cs.training_rec
        except Exception:
            pass

        weight_block = day_payload.get("weight") or {}
        latest = (weight_block or {}).get("latest") or {}
        weighed_today = bool(latest.get("date") == now.date().isoformat())
        tracks_weight = bool(
            (weight_block or {}).get("recent")
            or latest or (weight_block or {}).get("goal"))

        inp = engine.LiveInput(
            now=now,
            calorie_target=targets.get("calories"),
            calories_consumed=int(day.get("calories") or 0),
            protein_target=targets.get("protein"),
            protein_consumed=int(day.get("protein") or 0),
            meals=_meals(day, tz),
            workout_completed=bool(day.get("workout_completed")),
            cardio_completed=bool(day.get("cardio_completed")),
            training_events=_training_events(day, tz),
            planned_workout=planned,
            is_rest_day=is_rest,
            weight_logged_today=weighed_today,
            tracks_weight=tracks_weight,
            wearable_source=source,
            wearable_updated_at=synced_at,
            wearable_connected=connected,
            readiness=readiness,
            training_rec=training_rec,
            steps=health.get("steps"),
            steps_goal=_steps_goal(fitness_payload),
            history=tuple(
                engine.DayHistory(
                    date=h.get("date") or "",
                    calories=int(h.get("calories") or 0),
                    protein=int(h.get("protein") or 0),
                    trained=bool(h.get("workout")),
                )
                for h in (week_payload.get("history") or [])
            ),
        )

    return engine.to_wire(engine.compute(inp), generated_at=now)


def _steps_goal(fitness_payload: dict) -> int | None:
    """No step goal is stored anywhere yet, so this returns `None` and the
    activity domain reports `unknown` rather than inventing a 10,000 nobody
    chose. Wire it here the day a goal becomes a real user setting."""
    return None
