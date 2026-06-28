"""
Focused data fetchers for the native /api/v1 dashboard endpoints.

Each /api/v1 tab needs only a slice of the data, but the legacy
`_build_stats_for_user` fetches EVERYTHING (60d history, 90d weights, health,
Whoop tokens, attributes, analytics, streak, reminder gates) on every call. The
Today tab loading all of that just to show today's macros is the over-fetch.

These fetchers pull ONLY what each endpoint needs and produce the SAME shaped
pieces (`targets`, `day`, `history`, `weights`) the endpoints already consume — so
the wire output is byte-identical (verified by golden diff). The prod-shared
`_build_stats_for_user` (used by the legacy HTML dashboard / insights) is untouched.
"""
from __future__ import annotations

import json
from datetime import datetime, date as _date, timedelta

from db.queries import (
    get_or_create_today_log,
    get_recent_logs,
    get_recent_weights,
    get_recent_health_snapshots,
    _user_today,
)


def _targets(user) -> dict:
    prefs = user.preferences
    return {
        "calories": prefs.calorie_target if prefs else None,
        "protein": prefs.protein_target if prefs else None,
        "carbs": prefs.carb_target if prefs else None,
        "fats": prefs.fat_target if prefs else None,
    }


def _weights_csv_to_lbs(csv: str | None) -> str | None:
    """Convert per-set weight CSV from kg (DB) → lbs (client) so the iOS row
    can render '5×225 · 5×235' without doing the conversion itself. Drops
    blank tokens; returns None when the input is empty / unparseable."""
    if not csv:
        return None
    parts: list[str] = []
    for piece in csv.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            kg = float(piece)
        except ValueError:
            continue
        parts.append(str(round(kg * 2.20462, 1)))
    return ",".join(parts) if parts else None


def _parse_micros(raw) -> dict | None:
    """Parse a FoodEntry.micronutrients_json blob into a clean {name: number} dict
    for the iOS nutrient card. None when absent / empty / malformed."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    clean = {str(k): v for k, v in data.items() if isinstance(v, (int, float))}
    return clean or None


def _log_to_day(log) -> dict | None:
    """Shape a DailyLog into the `day` dict. Mirrors _build_stats_for_user._log_to_day."""
    if not log:
        return None
    return {
        "date": str(log.date),
        "calories": round(log.total_calories or 0),
        "protein": round(log.total_protein or 0),
        "carbs": round(log.total_carbs or 0),
        "fats": round(log.total_fats or 0),
        "water_ml": round(log.total_water_ml or 0),
        "workout_completed": log.workout_completed,
        "cardio_completed": log.cardio_completed,
        "food_entries": [
            {
                "id": e.id, "name": e.parsed_food_name or "?",
                "quantity": e.quantity or "",
                "calories": round(e.calories or 0), "protein": round(e.protein or 0),
                "carbs": round(e.carbs or 0), "fats": round(e.fats or 0),
                # Micronutrient profile for the Log's tap-to-expand nutrient card.
                "fiber":  round(e.fiber, 1) if e.fiber  is not None else None,
                "sugar":  round(e.sugar, 1) if e.sugar  is not None else None,
                "sodium": round(e.sodium)   if e.sodium is not None else None,
                "micros": _parse_micros(getattr(e, "micronutrients_json", None)),
                "estimated": bool(e.estimated_flag),
                "from_photo": bool(getattr(e, "from_photo", False)),
                # Prefer EATEN-at (meal_time) over logged-at so a back-dated or
                # time-stamped meal lands at the right spot on the timeline. Old
                # entries set meal_time≈timestamp, so this is backward compatible.
                "timestamp": (e.meal_time or e.timestamp).isoformat() if (e.meal_time or e.timestamp) else None,
                "meal_type": e.meal_type,
            }
            for e in sorted(
                (log.food_entries or []),
                key=lambda e: ((e.meal_time or e.timestamp) or datetime.min, e.id or 0),
            )
        ],
        "exercise_entries": [
            {
                "id": e.id, "name": e.exercise_name or "?",
                # T-WK1: surface the time so workouts sort + show on the iOS timeline
                # alongside meals. Prefer occurred-at (user-stated time or a wearable
                # workout's start) over logged-at; null occurred_at falls back to it.
                "timestamp": (e.occurred_at or e.timestamp).isoformat() if (e.occurred_at or e.timestamp) else None,
                "sets": e.sets, "reps": e.reps,
                "weight": round(e.weight * 2.20462, 1) if e.weight else None,
                # Per-set load — CSV in lbs for the client. Null when uniform.
                "weights": _weights_csv_to_lbs(e.weights),
                "duration_minutes": e.duration_minutes,
                "is_cardio": bool(e.cardio_type),
                "cardio_type": e.cardio_type,
                # T-EX1: surface the rest of the ExerciseEntry shape so the iOS
                # row can show the same parameters the web app does (RIR for
                # strength, calories for cardio, free-text notes for either).
                "rir": e.rir,
                "calories_burned": round(e.calories_burned_estimate) if e.calories_burned_estimate else None,
                "avg_hr": e.avg_hr,
                "notes": e.notes,
                # Origin tag (whoop / apple_health / text) so the iOS row can show a
                # "Whoop" / "Apple Watch" badge on auto-synced workouts.
                "source": e.source_type,
            }
            # Time-ordered like the food entries, so the timeline reads chronologically.
            for e in sorted(
                (log.exercise_entries or []),
                key=lambda e: ((e.occurred_at or e.timestamp) or datetime.min, e.id or 0),
            )
        ],
        # Timestamped hydration logs — water nodes on the iOS timeline (filterable
        # under Nutrition). DailyLog.total_water_ml stays the day's cached aggregate.
        "water_entries": [
            {
                "id": w.id,
                "ml": round(w.amount_ml or 0),
                "timestamp": w.timestamp.isoformat() if w.timestamp else None,
                "context": w.context,
            }
            for w in sorted(
                (log.water_entries or []),
                key=lambda w: (w.timestamp or datetime.min, w.id or 0),
            )
        ],
    }


async def day_data(db, user, target_date=None) -> dict:
    """Log + targets + weight record + the wearable snapshot FOR `target_date`
    (today by default; past days now surface their own snapshot too instead of
    dropping the strip). Past dates are fetched read-only — if
    no log exists for that date the `day` dict is None and the client
    renders an empty state. Today is auto-created so live coaching always
    has a log to write into. The `weight` block is the same across dates
    (user-scoped, not day-scoped) — we send it on every Today fetch so the
    screen has the recent trend at hand without a second round-trip. The
    `health` block is today's snapshot only; iOS hides the strip when nil."""
    from db.queries import get_log_by_date, get_recent_weights, get_recent_health_snapshots
    is_today = target_date is None or target_date == _user_today_date(user)

    # Read everything derived from `user` BEFORE creating/fetching today's log.
    # On a lost create race, get_or_create_today_log does a `db.rollback()` that
    # expires every loaded object including `user`; touching `user` afterward then
    # triggers an async lazy-load with no greenlet → 500 (MissingGreenlet). By
    # gathering targets/weights/health here, nothing reads `user` after the create.
    targets = _targets(user)
    user_tz = user.timezone or "UTC"
    weights = await get_recent_weights(db, user.id, days=30)
    weight_block = _weight_block(weights, user)

    health_block = None
    snap = (
        await _today_health_snapshot_linked(db, user) if is_today
        else await _health_snapshot_for_date_linked(db, user, target_date)
    )
    if snap:
        health_block = _health_block(snap)

    if is_today:
        log = await get_or_create_today_log(db, user.id, user_tz)
    else:
        log = await get_log_by_date(db, user.id, target_date)

    # Stamp the user's zone on the day so the iOS timeline renders clock labels in
    # THEIR timezone (naive timestamps are stored UTC). Without this iOS falls back
    # to the device zone, which is wrong for any cross-zone view.
    day = _log_to_day(log)
    if day is not None:
        day["timezone"] = user_tz

    return {
        "targets": targets,
        "day": day,
        "weight": weight_block,
        "health": health_block,
    }


def _health_block(snap) -> dict:
    """Shape today's wearable snapshot for the Today strip — every wearable
    field the web dashboard surfaces, all optional so the strip degrades
    row-by-row. iOS groups these into Recovery / Activity / Sleep on render."""
    return {
        "source":      snap.source,
        # Recovery / heart
        "recovery":    snap.recovery_score,
        "strain":      round(snap.strain, 1) if snap.strain is not None else None,
        "hrv":         round(snap.hrv) if snap.hrv is not None else None,
        "resting_hr":  round(snap.resting_hr) if snap.resting_hr is not None else None,
        "avg_hr":      round(snap.avg_hr) if snap.avg_hr is not None else None,
        # Activity
        "steps":           snap.steps,
        "active_calories": round(snap.active_calories) if snap.active_calories is not None else None,
        "resting_calories": round(snap.resting_calories) if snap.resting_calories is not None else None,
        "exercise_minutes": snap.exercise_minutes,
        "stand_hours":     snap.stand_hours,
        # Sleep
        "sleep_hours":           round(snap.sleep_hours, 1) if snap.sleep_hours is not None else None,
        "sleep_deep_hours":      round(snap.sleep_deep_hours, 1) if snap.sleep_deep_hours is not None else None,
        "sleep_rem_hours":       round(snap.sleep_rem_hours, 1) if snap.sleep_rem_hours is not None else None,
        "sleep_need_hours":      round(snap.sleep_need_hours, 1) if snap.sleep_need_hours is not None else None,
        "sleep_performance_pct": round(snap.sleep_performance_pct) if snap.sleep_performance_pct is not None else None,
        "sleep_efficiency_pct":  round(snap.sleep_efficiency_pct) if snap.sleep_efficiency_pct is not None else None,
        # Body / sleep physiology (Whoop)
        "respiratory_rate":  round(snap.respiratory_rate, 1) if snap.respiratory_rate is not None else None,
        "spo2_percentage":   round(snap.spo2_percentage, 1) if snap.spo2_percentage is not None else None,
        "skin_temp_celsius": round(snap.skin_temp_celsius, 1) if snap.skin_temp_celsius is not None else None,
    }


def _one_per_day_prefer_manual(weights):
    """Collapse raw BodyMetric rows to ONE reading per calendar day, preferring
    the MANUAL (deliberate) reading over an apple_health (passive) one for that
    day, and return them chronologically (oldest → newest).

    Why: a single morning can now legitimately carry two rows — the user's manual
    weigh-in AND a HealthKit sync. The trend must plot one point per day, and the
    headline ("latest") must be the user's own number, not whichever timestamp is
    newest. With manual winning each day, the last element is the manual reading
    of the most recent day whenever one exists — so callers get manual-wins for
    free by taking `[-1]`.

    Grouping key is the UTC calendar date (matching the %Y-%m-%d the dashboard
    already emits for trend points). Within a day, manual wins; if a day has only
    apple_health (or only manual), that single reading is used. Ties within the
    same source fall to the latest timestamp.
    """
    by_day: dict = {}
    for w in sorted(weights, key=lambda w: w.timestamp):
        if getattr(w, "weight_kg", None) is None:
            continue
        day = w.timestamp.strftime("%Y-%m-%d")
        cur = by_day.get(day)
        if cur is None:
            by_day[day] = w
            continue
        cur_manual = (getattr(cur, "source", None) or "manual") == "manual"
        w_manual = (getattr(w, "source", None) or "manual") == "manual"
        # Prefer manual; among equal source-rank, the later timestamp wins
        # (iteration is already chronological, so w is the later one).
        if w_manual or not cur_manual:
            by_day[day] = w
    return [by_day[d] for d in sorted(by_day.keys())]


def _weight_block(weights, user) -> dict | None:
    """Shape the weight record for the Today screen: latest reading, the
    user's goal, and recent readings (most-recent-first, capped at 14) for a
    sparkline. Returns None when nothing's ever been logged.

    One reading per day (manual preferred) — so a manual weigh-in plus a passive
    HealthKit sync the same morning render as a single point headlined by the
    user's own number, not a stacked/oscillating pair."""
    if not weights:
        return None
    sorted_weights = _one_per_day_prefer_manual(weights)
    if not sorted_weights:
        return None
    recent = [
        {
            "date": w.timestamp.strftime("%Y-%m-%d"),
            "kg":   round(w.weight_kg, 1),
            "lbs":  round(w.weight_kg * 2.20462, 1),
            # so iOS can tag an auto-synced reading ("Apple Health") vs a manual one
            "source": getattr(w, "source", None) or "manual",
        }
        for w in sorted_weights[-14:]
    ]
    latest = recent[-1] if recent else None
    goal = None
    if getattr(user, "goal_weight_kg", None) is not None:
        goal = {
            "kg":  round(user.goal_weight_kg, 1),
            "lbs": round(user.goal_weight_kg * 2.20462, 1),
        }
    return {"latest": latest, "goal": goal, "recent": recent}


def _user_today_date(user):
    """The user's current LOGGING day as a date. Delegates to db.queries._user_today
    so the rollover-hour grace window (late-night → previous day) is identical here
    and in the write path — otherwise the day view and the log it writes to disagree."""
    return _user_today(getattr(user, "timezone", None) or "UTC")


async def week_data(db, user) -> dict:
    """Targets + recent daily history + recent weights — enough for the 7-day window
    and weight trend, without health/Whoop/attributes."""
    history = await get_recent_logs(db, user.id, days=14)   # 14d → enough for adaptive TDEE
    weights = await get_recent_weights(db, user.id, days=30)
    hist_data = [
        {
            "date": str(log.date),
            "calories": round(log.total_calories or 0),
            "protein": round(log.total_protein or 0),
            "carbs": round(log.total_carbs or 0),
            "fats": round(log.total_fats or 0),
            "workout": log.workout_completed,
        }
        for log in sorted(history, key=lambda l: l.date)
    ]
    # One reading per day, manual preferred — the trend mustn't double-count a
    # day that has both a manual weigh-in and a passive HealthKit sync.
    weight_data = [
        {
            "date": w.timestamp.strftime("%Y-%m-%d"),
            "kg": round(w.weight_kg, 1),
            "lbs": round(w.weight_kg * 2.20462, 1),
        }
        for w in _one_per_day_prefer_manual(weights)
    ]
    return {"targets": _targets(user), "history": hist_data, "weights": weight_data}


# ── Fitness + Profile (shared health/whoop/streak helpers) ───────────────────

async def _today_health_snapshot_linked(db, user):
    """Today's wearable snapshot across the user's WHOLE linked account — the
    canonical row (`linked_to_user_id or id`) plus every identity pointing at it.
    A recovery synced under the user's Telegram identity then still shows in the
    app, which queries by the iOS identity. Prefers a snapshot that actually
    carries a recovery score; falls back to whatever today's snapshot is.
    """
    from sqlalchemy import select
    from db.models import User as _U

    canonical_id = user.linked_to_user_id or user.id
    id_rows = await db.execute(
        select(_U.id).where((_U.id == canonical_id) | (_U.linked_to_user_id == canonical_id))
    )
    ids = list(id_rows.scalars().all()) or [user.id]

    candidates = []
    for uid in ids:
        snaps = await get_recent_health_snapshots(db, uid, days=1)
        if snaps:
            candidates.append(snaps[0])
    if not candidates:
        return None
    with_recovery = [c for c in candidates if c.recovery_score is not None]
    return with_recovery[0] if with_recovery else candidates[0]


async def _health_snapshot_for_date_linked(db, user, target_date):
    """The wearable snapshot for a SPECIFIC date across the user's whole linked
    account — so a PAST day surfaces its recovery/sleep/HRV instead of dropping
    the strip (the 'wearable data disappears for previous days' bug). Mirrors the
    linked-account + prefer-recovery logic of the today version, filtered to the
    exact date."""
    from sqlalchemy import select
    from db.models import User as _U

    canonical_id = user.linked_to_user_id or user.id
    id_rows = await db.execute(
        select(_U.id).where((_U.id == canonical_id) | (_U.linked_to_user_id == canonical_id))
    )
    ids = list(id_rows.scalars().all()) or [user.id]
    span = max(1, (_user_today_date(user) - target_date).days + 2)
    candidates = []
    for uid in ids:
        for s in await get_recent_health_snapshots(db, uid, days=span):
            if s.date == target_date:
                candidates.append(s)
    if not candidates:
        return None
    with_recovery = [c for c in candidates if c.recovery_score is not None]
    return with_recovery[0] if with_recovery else candidates[0]


async def _merged_health_snaps(db, user):
    """Health snapshots for the user, merged with any linked identities — mirrors
    the merge in _build_stats_for_user so output matches exactly."""
    from sqlalchemy import select
    from db.models import User as _U

    snaps = await get_recent_health_snapshots(db, user.id, days=14)
    linked = (await db.execute(select(_U).where(_U.linked_to_user_id == user.id))).scalars().all()
    if not snaps and linked:
        for lu in linked:
            linked_snaps = await get_recent_health_snapshots(db, lu.id, days=14)
            if linked_snaps:
                snaps = linked_snaps
                break
    elif linked:
        covered = {s.date for s in snaps}
        for lu in linked:
            for ls in await get_recent_health_snapshots(db, lu.id, days=14):
                if ls.date not in covered:
                    snaps.append(ls)
                    covered.add(ls.date)
    return snaps


async def _whoop_connected(db, user) -> bool:
    from sqlalchemy import select
    from db.models import User as _U
    if user.whoop_access_token or user.whoop_refresh_token:
        return True
    linked = (await db.execute(select(_U).where(_U.linked_to_user_id == user.id))).scalars().all()
    return any(u.whoop_access_token or u.whoop_refresh_token for u in linked)


def _shape_health(snaps) -> list:
    # Only the fields the fitness endpoint consumes (date/recovery/strain/sleep/hrv/rhr),
    # with the same rounding _build_stats_for_user applies.
    return [
        {
            "date": str(s.date),
            "recovery_score": s.recovery_score,
            "strain": s.strain,
            "sleep_hours": s.sleep_hours,
            "hrv": round(s.hrv) if s.hrv else None,
            "resting_hr": round(s.resting_hr) if s.resting_hr else None,
        }
        for s in snaps
    ]


def _height_ft(user) -> str:
    if not user.height_cm:
        return ""
    total_in = user.height_cm / 2.54
    return f"{int(total_in // 12)}'{int(total_in % 12)}\""


def _compute_streak(hist_rows: list, user) -> int:
    logged = {h["date"] for h in hist_rows if (h.get("calories") or 0) > 0 or h.get("workout")}
    if not logged:
        return 0
    try:
        cur = _date.fromisoformat(_user_today(user.timezone or "UTC").isoformat())
    except Exception:
        cur = _date.fromisoformat(max(logged))
    streak = 0
    while cur.isoformat() in logged:
        streak += 1
        cur = cur - timedelta(days=1)
    return streak


async def fitness_data(db, user) -> dict:
    """Health/readiness + training flags — no food/weights/attributes/analytics."""
    snaps = await _merged_health_snaps(db, user)
    history = await get_recent_logs(db, user.id, days=10)
    hist = [{"date": str(log.date), "workout": log.workout_completed}
            for log in sorted(history, key=lambda l: l.date)]
    return {
        "profile": {
            "whoop_connected": await _whoop_connected(db, user),
            "apple_health_connected": any(s.source == "apple_health" for s in snaps),
        },
        "health": _shape_health(snaps),
        "history": hist,
    }


async def profile_data(db, user) -> dict:
    """The profile dict the Profile endpoint consumes — no weights/attributes/analytics."""
    prefs = user.preferences
    history = await get_recent_logs(db, user.id, days=60)
    hist = [{"date": str(log.date), "calories": round(log.total_calories or 0),
             "workout": log.workout_completed}
            for log in sorted(history, key=lambda l: l.date)]
    snaps = await _merged_health_snaps(db, user)

    return {
        "profile": {
            "name": user.name or "User",
            "age": user.age,
            "sex": user.sex,
            "height_cm": user.height_cm,
            "height_ft": _height_ft(user),
            "current_weight_lbs": round(user.current_weight_kg * 2.20462, 1) if user.current_weight_kg else None,
            "goal_weight_lbs": round(user.goal_weight_kg * 2.20462, 1) if user.goal_weight_kg else None,
            "primary_goal": user.primary_goal,
            "training_experience": user.training_experience,
            "non_training_activity": user.non_training_activity,
            "dietary_preferences": user.dietary_preferences,
            "injuries": user.injuries,
            # Location + locale fields. iOS surfaces these in a Location
            # section so users can adjust the timezone Arnie uses for day
            # boundaries / reminder windows and the city used for nearby
            # places lookups. `coords_set` lets the client confirm a prior
            # share-location actually landed on the user row — Settings'
            # Location row was previously showing "Shared ✓" purely from
            # CoreLocation's permission state, not from whether the POST
            # to /api/v1/location had succeeded.
            "timezone": user.timezone,
            "city": user.city,
            "coords_set": user.lat is not None and user.lng is not None,
            "coaching_style": prefs.coaching_style if prefs else None,
            "calorie_target": prefs.calorie_target if prefs else None,
            "protein_target": prefs.protein_target if prefs else None,
            "carb_target": prefs.carb_target if prefs else None,
            "fat_target": prefs.fat_target if prefs else None,
            "reminder_frequency": (prefs.reminder_frequency if prefs else None) or "moderate",
            "reminders_on": bool(prefs.proactive_messaging_enabled) if prefs else False,
            "food_logging_mode": (getattr(prefs, "food_logging_mode", None) or "moderate") if prefs else "moderate",
            "whoop_connected": await _whoop_connected(db, user),
            "apple_health_connected": any(s.source == "apple_health" for s in snaps),
            "streak_days": _compute_streak(hist, user),
        }
    }
