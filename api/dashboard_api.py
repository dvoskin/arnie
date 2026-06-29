"""
Native dashboard data API — the JSON the iOS app's dashboard screens consume.

The legacy dashboard is server-rendered HTML (api/templates.py) authed by a
webhook token in the URL. These endpoints serve the SAME underlying data
(via the shared `_build_stats_for_user` builder) but as a clean, versioned JSON
contract authed by the app's bearer identity — so chat and dashboard share one
identity, one session, one rendering layer (native SwiftUI).

First slice: GET /api/v1/day (the Today screen). Week / Fitness / Brain / Profile
follow the same pattern — each reshapes a slice of `_build_stats_for_user` into a
focused contract.
"""
from __future__ import annotations

import logging

from typing import Optional
from datetime import date as _date

from fastapi import APIRouter, Depends, HTTPException, Query

from db.database import AsyncSessionLocal
from db.queries import resolve_user
from api.auth import current_identity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["dashboard"])

WIRE_VERSION = 1


@router.get("/day")
async def get_day(
    identity: str = Depends(current_identity),
    date: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to today"),
):
    """Totals, targets, and logged entries for the Today screen — optionally
    for a past date when `date=YYYY-MM-DD` is supplied (read-only browse).

    Shape:
      { v, date, targets{calories,protein,carbs,fats},
        totals{calories,protein,carbs,fats,water_ml},
        workout_completed, cardio_completed,
        food_entries[], exercise_entries[] }

    `targets` is null-valued for a user who hasn't set them yet (still in
    onboarding) — the client renders an empty/teaser state in that case. When
    `date` is in the past and no log exists, the day is rendered empty (zero
    totals, empty lists) — never auto-created.
    """
    from api.native_data import day_data

    parsed_date: Optional[_date] = None
    if date:
        try:
            parsed_date = _date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        stats = await day_data(db, user, target_date=parsed_date)

    targets = stats.get("targets") or {}
    day = stats.get("day") or {}

    return {
        "v": WIRE_VERSION,
        "date": day.get("date") or (str(parsed_date) if parsed_date else None),
        "targets": {
            "calories": targets.get("calories"),
            "protein": targets.get("protein"),
            "carbs": targets.get("carbs"),
            "fats": targets.get("fats"),
        },
        "totals": {
            "calories": day.get("calories", 0),
            "protein": day.get("protein", 0),
            "carbs": day.get("carbs", 0),
            "fats": day.get("fats", 0),
            "water_ml": day.get("water_ml", 0),
        },
        "workout_completed": bool(day.get("workout_completed")),
        "cardio_completed": bool(day.get("cardio_completed")),
        "food_entries": day.get("food_entries", []),
        "exercise_entries": [_normalize_exercise(e) for e in day.get("exercise_entries", [])],
        # Timestamped hydration logs so water surfaces on the iOS Daily Log
        # timeline (day_data builds these; this endpoint previously dropped them).
        "water_entries": day.get("water_entries", []),
        "weight": stats.get("weight"),
        "health": stats.get("health"),
    }


@router.get("/profile")
async def get_profile(identity: str = Depends(current_identity)):
    """The user's profile, goals, and connection state for the Profile tab.

    Reshapes `_build_stats_for_user`'s `profile` dict into a grouped contract.
    Empty strings are normalized to null so the client can cleanly hide unset rows.
    """
    from api.native_data import profile_data

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        stats = await profile_data(db, user)

    p = stats.get("profile") or {}

    def clean(v):
        return v if v else None

    return {
        "v": WIRE_VERSION,
        "name": p.get("name") or "User",
        "primary_goal": clean(p.get("primary_goal")),
        "streak_days": p.get("streak_days") or 0,
        "stats": {
            "age": p.get("age"),
            "sex": clean(p.get("sex")),
            "height": clean(p.get("height_ft")),
            "current_weight_lbs": p.get("current_weight_lbs"),
            "goal_weight_lbs": p.get("goal_weight_lbs"),
        },
        "targets": {
            "calories": p.get("calorie_target"),
            "protein": p.get("protein_target"),
            "carbs": p.get("carb_target"),
            "fats": p.get("fat_target"),
        },
        "training": {
            "experience": clean(p.get("training_experience")),
            "activity": clean(p.get("non_training_activity")),
            "injuries": clean(p.get("injuries")),
        },
        "diet": clean(p.get("dietary_preferences")),
        "coaching": {
            "style": clean(p.get("coaching_style")),
            "logging_mode": clean(p.get("food_logging_mode")),
            "reminders_on": bool(p.get("reminders_on")),
            "reminder_frequency": clean(p.get("reminder_frequency")),
        },
        "connections": {
            "whoop": bool(p.get("whoop_connected")),
            "apple_health": bool(p.get("apple_health_connected")),
        },
        # Location/locale grouping — surfaced as its own Profile section so
        # the user can correct the timezone Arnie uses for day boundaries.
        # `coords_set` is the source of truth for "has the user actually
        # shared their location" — iOS uses it to display the correct
        # Settings row state (Shared ✓ vs Share ›).
        "location": {
            "timezone": clean(p.get("timezone")),
            "city": clean(p.get("city")),
            "coords_set": bool(p.get("coords_set")),
        },
    }


@router.get("/week")
async def get_week(identity: str = Depends(current_identity)):
    """Last 7 days of intake + training, plus the weight trend, for the Week tab.

    Gaps are filled: every one of the 7 days is present (0s for unlogged days) so
    the client's bar chart has a complete axis. Averages are over LOGGED days only.
    """
    from datetime import timedelta
    from db.queries import _user_today
    from api.native_data import week_data

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        stats = await week_data(db, user)
        today = _user_today(user.timezone or "UTC")

    targets = stats.get("targets") or {}
    by_date = {h["date"]: h for h in (stats.get("history") or [])}

    days = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        h = by_date.get(d.isoformat()) or {}
        days.append({
            "date": d.isoformat(),
            "weekday": d.strftime("%a"),
            "calories": h.get("calories", 0),
            "protein": h.get("protein", 0),
            "carbs": h.get("carbs", 0),
            "fats": h.get("fats", 0),
            "workout": bool(h.get("workout")),
        })

    logged = [x for x in days if x["calories"] > 0]

    def avg(key):
        return round(sum(x[key] for x in logged) / len(logged)) if logged else 0

    weights = stats.get("weights") or []
    from core.targets import compute_adaptive_tdee
    expenditure = compute_adaptive_tdee(stats.get("history") or [], weights)

    # 14-day adherence (Coach strip card): per-day calories/protein + whether a
    # weigh-in landed that day. Built from the 14-day history (by_date) + weigh-in
    # dates, so it's independent of the 7-day `days`/`averages` window above.
    weigh_dates = {w["date"] for w in weights}
    adherence_days = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        h = by_date.get(d.isoformat()) or {}
        adherence_days.append({
            "date": d.isoformat(),
            "calories": h.get("calories", 0),
            "protein": h.get("protein", 0),
            "weighed": d.isoformat() in weigh_dates,
        })

    return {
        "v": WIRE_VERSION,
        "targets": {
            "calories": targets.get("calories"),
            "protein": targets.get("protein"),
            "carbs": targets.get("carbs"),
            "fats": targets.get("fats"),
        },
        "days": days,
        "averages": {
            "calories": avg("calories"), "protein": avg("protein"),
            "carbs": avg("carbs"), "fats": avg("fats"),
        },
        "days_logged": len(logged),
        "days_trained": sum(1 for x in days if x["workout"]),
        "weights": [{"date": w["date"], "lbs": w["lbs"]} for w in weights[-30:]],
        "adherence_days": adherence_days,
        # Adaptive TDEE (energy-balance from intake + weight trend); null when data
        # is too thin — the Coach expenditure card hides itself in that case.
        "expenditure": expenditure,
    }


@router.get("/brain")
async def get_brain(identity: str = Depends(current_identity)):
    """What Arnie has learned about the user, grouped into category lobes.

    Mirrors the web brain page's calibration model: progress toward 25 durable
    facts (UNLOCK_NODES). Only active attributes are surfaced; empty lobes are
    omitted.
    """
    from memory.attribute_store import get_all_attributes

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        attrs = await get_all_attributes(db, user.id)

    active = [a for a in attrs if a.attribute_status == "active"]

    LOBES = [
        ("nutrition", "Nutrition"), ("fitness", "Fitness"), ("health", "Health"),
        ("lifestyle", "Lifestyle"), ("behavior", "Behavior"), ("mental", "Mental"),
    ]
    lobes = []
    for key, name in LOBES:
        items = [a for a in active if a.category == key]
        if not items:
            continue
        lobes.append({
            "category": key,
            "name": name,
            "count": len(items),
            "attributes": [
                {
                    "label": (a.display_name or a.attribute_key.replace("_", " ")).strip(),
                    "value": a.value,
                    "confidence": a.confidence,
                }
                for a in items
            ],
        })

    TARGET = 25  # matches web brain page UNLOCK_NODES
    return {
        "v": WIRE_VERSION,
        "attribute_count": len(active),
        "target": TARGET,
        "unlocked": len(active) >= int(TARGET * 0.6),
        "lobes": lobes,
    }


@router.post("/brain/resync")
async def force_brain_resync(identity: str = Depends(current_identity)):
    """Force an immediate brain re-synthesis for the caller, bypassing the
    throttle. Debug aid for verifying extraction end-to-end from the iOS app
    (the normal path is throttled to 30m–2h depending on user age). Returns the
    fresh attribute count and lobe summary so the client can compare before/after.
    """
    from memory.profile_updater import maybe_update_profile
    from memory.attribute_store import get_all_attributes

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        try:
            updated = await maybe_update_profile(user, db, force=True)
        except Exception as e:
            logger.error(f"force resync failed for {user.id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="resync failed")
        attrs = await get_all_attributes(db, user.id)

    active = [a for a in attrs if a.attribute_status == "active"]
    return {
        "v": WIRE_VERSION,
        "updated": bool(updated),
        "attribute_count": len(active),
    }


@router.get("/fitness")
async def get_fitness(identity: str = Depends(current_identity)):
    """Recovery/readiness (from wearables) + training summary for the Fitness tab.

    `connected` is false when no wearable is linked — the client shows a connect
    teaser instead of empty charts. `recovery_trend` is the last 14 days that have
    a recovery score.
    """
    from datetime import timedelta
    from db.queries import _user_today
    from api.native_data import fitness_data

    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        stats = await fitness_data(db, user)
        today = _user_today(user.timezone or "UTC")

    profile = stats.get("profile") or {}
    health = sorted((stats.get("health") or []), key=lambda h: h["date"])
    latest = health[-1] if health else None

    recovery_trend = [
        {"date": h["date"], "recovery": h.get("recovery_score"), "strain": h.get("strain")}
        for h in health if h.get("recovery_score") is not None
    ][-14:]

    by_date = {h["date"]: h for h in (stats.get("history") or [])}
    sessions_week = sum(
        1 for i in range(7)
        if by_date.get((today - timedelta(days=i)).isoformat(), {}).get("workout")
    )
    week_recov = [p["recovery"] for p in recovery_trend if p["recovery"] is not None][-7:]
    avg_recovery = round(sum(week_recov) / len(week_recov)) if week_recov else None

    return {
        "v": WIRE_VERSION,
        "connected": bool(profile.get("whoop_connected") or profile.get("apple_health_connected")),
        "latest": ({
            "recovery": latest.get("recovery_score"),
            "strain": latest.get("strain"),
            "sleep_hours": latest.get("sleep_hours"),
            "hrv": latest.get("hrv"),
            "resting_hr": latest.get("resting_hr"),
        } if latest else None),
        "recovery_trend": recovery_trend,
        "training": {
            "sessions_this_week": sessions_week,
            "avg_recovery": avg_recovery,
        },
    }


def _normalize_exercise(e: dict) -> dict:
    """Clean the raw exercise shape into well-typed wire fields.

    `reps` stays a STRING — it can hold ranges ("8-10") or "AMRAP", not just a
    number. `duration_minutes` is coerced to a whole-minute int (the builder emits
    a float). Everything else passes through.
    """
    dm = e.get("duration_minutes")
    reps = e.get("reps")
    return {
        "id": e.get("id"),
        "name": e.get("name") or "?",
        "sets": e.get("sets"),
        "reps": (str(reps) if reps is not None else None),
        "weight": e.get("weight"),
        # Per-set load CSV + the rest of the entry shape the iOS row renders. These
        # were being DROPPED here (only the fields above survived), so per-set
        # breakdowns, RIR, cardio calories, and notes never reached the app.
        "weights": e.get("weights"),
        "duration_minutes": (int(round(dm)) if dm is not None else None),
        "is_cardio": bool(e.get("is_cardio")),
        "cardio_type": e.get("cardio_type"),
        "rir": e.get("rir"),
        "calories_burned": e.get("calories_burned"),
        "avg_hr": e.get("avg_hr"),
        "notes": e.get("notes"),
        "source": e.get("source"),
        # THE FIX: surface the timestamp so the timeline can place + time workouts.
        # Food entries already pass theirs through; exercises were stripped here,
        # which is why workouts showed untimed and clustered at the end.
        "timestamp": e.get("timestamp"),
    }
