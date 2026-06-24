"""
Whoop OAuth2 + API client + daily data sync.

Flow:
  1. /connect command in Telegram → user gets auth URL with state=their_token
  2. User authorizes on Whoop's site → Whoop redirects to /whoop/callback?code=...&state=...
  3. callback() exchanges code for access+refresh tokens, saves to user record
  4. Daily scheduler calls sync_user_whoop() → refreshes if needed, fetches data,
     upserts into HealthSnapshot table

API docs: https://developer.whoop.com/api
"""
import asyncio
import logging
import os
import time
from datetime import datetime, date, timedelta, timezone
from typing import Optional

import httpx

from db.models import User
from db.queries import set_whoop_tokens, clear_whoop_tokens, upsert_health_snapshot

logger = logging.getLogger(__name__)

WHOOP_CLIENT_ID = os.getenv("WHOOP_CLIENT_ID", "")
WHOOP_CLIENT_SECRET = os.getenv("WHOOP_CLIENT_SECRET", "")

AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API_BASE = "https://api.prod.whoop.com/developer"

SCOPES = " ".join([
    "read:recovery",
    "read:cycles",
    "read:sleep",
    "read:workout",
    "read:profile",
    "read:body_measurement",
    "offline",  # REQUIRED to get a refresh_token so we can auto-refresh
])


def build_auth_url(redirect_uri: str, state: str) -> str:
    """Build the Whoop OAuth authorize URL the user visits."""
    from urllib.parse import urlencode
    params = {
        "client_id": WHOOP_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


# In-memory cache to make the callback idempotent.
# OAuth codes are one-time use, so if the browser hits the callback URL twice
# (refresh, prefetch, back button), the second exchange would fail with
# "code already used". We cache successful exchanges for 5 min and replay
# the cached tokens on duplicate hits.
_CODE_CACHE: dict = {}
_CODE_TTL = 300  # seconds


def _gc_code_cache():
    now = time.time()
    expired = [k for k, v in _CODE_CACHE.items() if v["expires_at"] < now]
    for k in expired:
        _CODE_CACHE.pop(k, None)


async def exchange_code(code: str, redirect_uri: str) -> dict:
    """
    POST to /oauth/oauth2/token with the auth code.
    Returns {"ok": True, "tokens": {...}} on success
    or {"ok": False, "error": "...", "details": "..."} on failure.
    Idempotent: replays cached tokens on repeated calls with the same code.
    """
    if not WHOOP_CLIENT_ID or not WHOOP_CLIENT_SECRET:
        return {"ok": False, "error": "WHOOP_CLIENT_ID / WHOOP_CLIENT_SECRET env vars not set on server"}

    _gc_code_cache()
    cached = _CODE_CACHE.get(code)
    if cached:
        logger.info("Replaying cached token exchange for duplicate callback hit")
        return {"ok": True, "tokens": cached["tokens"], "replayed": True}

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": WHOOP_CLIENT_ID,
                    "client_secret": WHOOP_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if r.status_code >= 400:
                logger.error(f"Whoop token exchange HTTP {r.status_code}: {r.text}")
                return {
                    "ok": False,
                    "error": f"Whoop returned HTTP {r.status_code}",
                    "details": r.text[:500],
                }
            tokens = r.json()
            logger.info(
                f"Whoop token exchange OK — keys: {list(tokens.keys())}, "
                f"has_refresh: {bool(tokens.get('refresh_token'))}, "
                f"scope: {tokens.get('scope')!r}, "
                f"expires_in: {tokens.get('expires_in')}"
            )
            _CODE_CACHE[code] = {"tokens": tokens, "expires_at": time.time() + _CODE_TTL}
            return {"ok": True, "tokens": tokens}
        except Exception as e:
            logger.error(f"Whoop token exchange failed: {e}")
            return {"ok": False, "error": str(e)[:500]}


async def refresh_access_token(refresh_token: str) -> Optional[dict]:
    """Use the refresh token to get a new access token."""
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": WHOOP_CLIENT_ID,
                    "client_secret": WHOOP_CLIENT_SECRET,
                    "scope": SCOPES,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"Whoop token refresh failed: {e}")
            return None


async def _ensure_fresh_token(db, user: User) -> Optional[str]:
    """
    Return a valid access token, refreshing if expired or close to expiring.
    Falls back to the existing access_token if refresh isn't possible
    (e.g. Whoop didn't issue a refresh_token in the first place).
    """
    now = datetime.utcnow()
    # Whoop access tokens last 3600 seconds (1 hour). We sync every 30 min, so
    # use a 35-minute buffer — every sync proactively refreshes the token before
    # it can expire between runs. No window where a call hits an expired token.
    REFRESH_BUFFER = timedelta(minutes=35)
    has_fresh_access = (
        user.whoop_access_token
        and user.whoop_token_expires_at
        and user.whoop_token_expires_at > now + REFRESH_BUFFER
    )

    # Token still has plenty of life — use it directly.
    if has_fresh_access:
        return user.whoop_access_token

    # Token expired or within 35 min of expiry — proactively refresh.
    if user.whoop_refresh_token:
        logger.info(f"User {user.id}: proactively refreshing Whoop access token")
        tokens = await refresh_access_token(user.whoop_refresh_token)
        if tokens:
            expires_at = now + timedelta(seconds=tokens.get("expires_in", 3600))
            await set_whoop_tokens(
                db, user.id,
                access_token=tokens["access_token"],
                refresh_token=tokens.get("refresh_token", user.whoop_refresh_token),
                expires_at=expires_at,
            )
            logger.info(f"User {user.id}: Whoop token refreshed, expires in {tokens.get('expires_in', 3600)//60} min")
            return tokens["access_token"]
        logger.warning(f"User {user.id}: Whoop token refresh failed — will try stale access token")

    # No refresh token, no fresh access — best we can do is try the
    # stale access token. Whoop will reject it if truly expired.
    if user.whoop_access_token:
        logger.info(f"User {user.id}: using stale/no-refresh access token")
        return user.whoop_access_token

    return None


async def _whoop_get(token: str, path: str, params: Optional[dict] = None) -> Optional[dict]:
    """GET a Whoop API endpoint with the bearer token."""
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(
                f"{API_BASE}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params or {},
            )
            if r.status_code >= 400:
                logger.error(f"Whoop GET {path} → HTTP {r.status_code}: {r.text[:300]}")
                return None
            data = r.json()
            record_count = len(data.get("records", [])) if isinstance(data, dict) else 0
            logger.info(f"Whoop GET {path} → {record_count} records")
            return data
        except Exception as e:
            logger.error(f"Whoop GET {path} failed: {e}")
            return None


def _scored(record: dict) -> Optional[dict]:
    """
    Return a record's `score` dict only when it is actually usable.

    Whoop API v2 attaches a `score_state` to every record and only includes the
    `score` object when score_state == "SCORED" (the other states are
    "PENDING_SCORE" and "UNSCORABLE", both of which carry a null score). Reading
    a half-processed record would silently write NULLs over the columns, so every
    parser gates on this.

    Defensive: if a response ever omits score_state but still carries a populated
    score (a legacy or degraded shape), accept it rather than drop real data.
    """
    score = record.get("score")
    if not isinstance(score, dict) or not score:
        return None
    state = record.get("score_state")
    if state is not None and state != "SCORED":
        return None
    return score


async def _persist_whoop_workouts(db, user: User, workout_by_date: dict) -> tuple[int, int]:
    """Auto-create ExerciseEntry rows from synced WHOOP workouts.

    Deduped by `source_ref` ("whoop:<workout_id>") so repeated syncs upsert the
    same row in place instead of duplicating. Each entry carries the workout's
    real start time as `occurred_at` so it lands at the right spot on the day's
    timeline. Best-effort and idempotent; recomputes the day's totals after.

    Note: dedups whoop-vs-whoop only. If the user ALSO manually logged the same
    session, both can coexist (rare; auto-populate is the explicit ask here).
    """
    from sqlalchemy import select
    from db.models import ExerciseEntry
    from db.queries import get_or_create_log_for_date, recompute_log_totals

    created = updated = 0
    for d, workouts in (workout_by_date or {}).items():
        try:
            log = await get_or_create_log_for_date(db, user.id, d)
        except Exception:
            continue
        touched = False
        for w in workouts:
            wid = w.get("id")
            if not wid:
                continue  # no stable key → skip, never risk a dup storm
            source_ref = f"whoop:{wid}"
            occurred = None
            if w.get("start"):
                try:
                    occurred = (datetime.fromisoformat(w["start"].replace("Z", "+00:00"))
                                .astimezone(timezone.utc).replace(tzinfo=None))
                except Exception:
                    occurred = None
            sport = w.get("sport") or "Workout"
            dur = w.get("duration_min")
            cals = w.get("calories")
            bits = []
            if w.get("strain") is not None:
                bits.append(f"strain {w['strain']}")
            if w.get("avg_hr"):
                bits.append(f"avg HR {w['avg_hr']}")
            notes = "WHOOP: " + ", ".join(bits) if bits else "WHOOP"

            existing = (await db.execute(
                select(ExerciseEntry).where(ExerciseEntry.source_ref == source_ref)
            )).scalars().first()
            if existing:
                existing.daily_log_id = log.id
                existing.exercise_name = sport
                existing.cardio_type = sport       # whoop sessions are duration/HR based
                existing.duration_minutes = dur
                existing.calories_burned_estimate = cals
                existing.occurred_at = occurred
                existing.notes = notes
                updated += 1
            else:
                db.add(ExerciseEntry(
                    daily_log_id=log.id,
                    exercise_name=sport,
                    cardio_type=sport,
                    duration_minutes=dur,
                    calories_burned_estimate=cals,
                    source_type="whoop",
                    source_ref=source_ref,
                    occurred_at=occurred,
                    notes=notes,
                ))
                created += 1
            touched = True
        if touched:
            await db.flush()
            await recompute_log_totals(db, log.id)
    if created or updated:
        logger.info(f"whoop auto-log user {user.id}: {created} created, {updated} updated")
    return created, updated


async def sync_user_whoop(db, user: User, days: int = 2,
                          snapshot_user_id: int = None) -> int:
    """
    Pull last `days` of Whoop data and upsert into HealthSnapshot.
    snapshot_user_id: save snapshots to this user_id (use canonical for linked accounts).
                      Defaults to user.id.
    Returns number of days synced.
    """
    save_id = snapshot_user_id or user.id
    token = await _ensure_fresh_token(db, user)
    if not token:
        return 0

    # Whoop expects ISO 8601 datetimes
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    params = {"start": start.isoformat(), "end": end.isoformat(), "limit": 25}

    # Fetch all endpoints in parallel — recovery, sleep, cycles, workouts.
    # Whoop API v2: v1 was deprecated and sunset in late 2025, after which its
    # /v1/recovery and /v1/activity/sleep endpoints stopped returning scored data
    # (which is why those columns went NULL while cycle/strain kept flowing). v2
    # keeps the same {"records": [...]} envelope and the same nested score field
    # names — the score object is just gated behind score_state == "SCORED" now
    # (see _scored()). Sleep/workout IDs became UUIDs, but we key on dates, not IDs.
    recovery_data, sleep_data, cycle_data, workout_data = await asyncio.gather(
        _whoop_get(token, "/v2/recovery", params),
        _whoop_get(token, "/v2/activity/sleep", params),
        _whoop_get(token, "/v2/cycle", params),
        _whoop_get(token, "/v2/activity/workout", params),
        return_exceptions=False,
    )

    # Group by date — Whoop has its own cycle/day concept tied to sleep windows.
    # We approximate by using the cycle's `created_at` date.
    by_date: dict = {}

    def _ensure(d: date):
        by_date.setdefault(d, {})

    recovery_seen = recovery_scored = 0
    if recovery_data and "records" in recovery_data:
        for rec in recovery_data["records"]:
            recovery_seen += 1
            created = rec.get("created_at", "")[:10]
            if not created:
                continue
            score = _scored(rec)
            if not score:
                continue
            recovery_scored += 1
            d = date.fromisoformat(created)
            _ensure(d)
            by_date[d]["recovery_score"] = score.get("recovery_score")
            by_date[d]["hrv"] = score.get("hrv_rmssd_milli")
            by_date[d]["resting_hr"] = score.get("resting_heart_rate")
            by_date[d]["skin_temp_celsius"] = score.get("skin_temp_celsius")
            by_date[d]["spo2_percentage"] = score.get("spo2_percentage")

    sleep_seen = sleep_scored = 0
    if sleep_data and "records" in sleep_data:
        for sleep in sleep_data["records"]:
            sleep_seen += 1
            # Naps are separate records in v2; they must not overwrite the day's
            # main sleep (sleep_hours, etc.), so skip them for the daily snapshot.
            if sleep.get("nap"):
                continue
            # Use the sleep END date so it lands on the day the user woke up
            end_str = sleep.get("end", "")[:10]
            if not end_str:
                continue
            score = _scored(sleep)
            if not score:
                continue
            sleep_scored += 1
            d = date.fromisoformat(end_str)
            stages = score.get("stage_summary") or {}
            _ensure(d)
            total_in_bed_ms = stages.get("total_in_bed_time_milli", 0)
            if total_in_bed_ms:
                by_date[d]["sleep_hours"] = round(total_in_bed_ms / 1000 / 3600, 2)
            deep_ms = stages.get("total_slow_wave_sleep_time_milli", 0)
            rem_ms = stages.get("total_rem_sleep_time_milli", 0)
            light_ms = stages.get("total_light_sleep_time_milli", 0)
            awake_ms = stages.get("total_awake_time_milli", 0)
            if deep_ms:
                by_date[d]["sleep_deep_hours"] = round(deep_ms / 1000 / 3600, 2)
            if rem_ms:
                by_date[d]["sleep_rem_hours"] = round(rem_ms / 1000 / 3600, 2)
            # Sleep quality metrics
            if score.get("respiratory_rate") is not None:
                by_date[d]["respiratory_rate"] = score.get("respiratory_rate")
            if score.get("sleep_performance_percentage") is not None:
                by_date[d]["sleep_performance_pct"] = score.get("sleep_performance_percentage")
            if score.get("sleep_needed") is not None:
                needed = score.get("sleep_needed") or {}
                baseline_ms = needed.get("baseline_milli", 0)
                if baseline_ms:
                    by_date[d]["sleep_need_hours"] = round(baseline_ms / 1000 / 3600, 2)
            # Sleep efficiency = actual sleep / time in bed
            actual_sleep_ms = deep_ms + rem_ms + light_ms
            if total_in_bed_ms and actual_sleep_ms:
                by_date[d]["sleep_efficiency_pct"] = round(actual_sleep_ms / total_in_bed_ms * 100, 1)

    if cycle_data and "records" in cycle_data:
        for cyc in cycle_data["records"]:
            created = cyc.get("created_at", "")[:10]
            if not created:
                continue
            score = _scored(cyc)
            if not score:
                continue
            d = date.fromisoformat(created)
            _ensure(d)
            if score.get("strain") is not None:
                by_date[d]["strain"] = score.get("strain")
            if score.get("average_heart_rate") is not None:
                by_date[d]["avg_hr"] = score.get("average_heart_rate")
            if score.get("kilojoule") is not None:
                # Whoop gives kJ; convert to kcal (1 kJ = 0.239 kcal)
                by_date[d]["active_calories"] = round(score["kilojoule"] * 0.239, 0)

    # Workout details — aggregate per day
    if workout_data and "records" in workout_data:
        import json as _json
        workout_by_date: dict = {}
        SPORT_MAP = {
            -1: "Activity", 0: "Running", 1: "Cycling", 16: "Baseball", 17: "Basketball",
            18: "Rowing", 19: "Fencing", 20: "Field Hockey", 21: "Football", 22: "Golf",
            24: "Ice Hockey", 25: "Lacrosse", 27: "Rugby", 28: "Sailing", 29: "Skiing",
            30: "Soccer", 31: "Softball", 32: "Squash", 33: "Swimming", 34: "Tennis",
            35: "Track & Field", 36: "Volleyball", 37: "Water Polo", 38: "Wrestling",
            39: "Boxing", 42: "Dance", 43: "Pilates", 44: "Yoga", 45: "Weightlifting",
            47: "Cross Country Skiing", 48: "Functional Fitness", 49: "Duathlon",
            51: "Gymnastics", 52: "Hiking", 53: "Horse Racing", 55: "Kayaking",
            56: "Martial Arts", 57: "Mountain Biking", 58: "Powerlifting",
            59: "Rock Climbing", 60: "Paddleboarding", 61: "Triathlon",
            62: "Walking", 63: "Surfing", 64: "Elliptical", 65: "Stairmaster",
        }
        for wo in workout_data["records"]:
            start_str = wo.get("start", "")[:10]
            if not start_str:
                continue
            d = date.fromisoformat(start_str)
            score = _scored(wo) or {}  # keep the entry even if scoring is pending
            # v2 adds a human-readable sport_name; fall back to the v1 sport_id map.
            sport_name = wo.get("sport_name")
            if sport_name:
                sport_name = sport_name.replace("_", " ").title()
            else:
                sport_id = wo.get("sport_id", -1)
                sport_name = SPORT_MAP.get(sport_id, f"Sport {sport_id}")
            duration_ms = 0
            if wo.get("start") and wo.get("end"):
                try:
                    from datetime import datetime as _dt
                    s = _dt.fromisoformat(wo["start"].replace("Z", "+00:00"))
                    e = _dt.fromisoformat(wo["end"].replace("Z", "+00:00"))
                    duration_ms = int((e - s).total_seconds() * 1000)
                except Exception:
                    pass
            entry = {
                # id + start power the auto-log path: a stable dedup key
                # ("whoop:<id>") and the workout's actual start time (occurred_at).
                "id": wo.get("id"),
                "start": wo.get("start"),
                "sport": sport_name,
                "strain": round(score.get("strain", 0), 1),
                "duration_min": round(duration_ms / 60000, 0) if duration_ms else None,
                "avg_hr": score.get("average_heart_rate"),
                "max_hr": score.get("max_heart_rate"),
                "calories": round(score.get("kilojoule", 0) * 0.239) if score.get("kilojoule") else None,
            }
            workout_by_date.setdefault(d, []).append(entry)

        for d, workouts in workout_by_date.items():
            _ensure(d)
            by_date[d]["whoop_workouts"] = _json.dumps(workouts)

        # Auto-populate the day's log with these workouts (deduped by source_ref),
        # so a pushed wearable session shows up on the timeline like a manual log.
        try:
            await _persist_whoop_workouts(db, user, workout_by_date)
        except Exception as _e:  # best-effort: never break the snapshot sync
            logger.warning(f"whoop workout auto-log failed for user {user.id}: {_e}")

    # Regression visibility: a connected user whose sync yields strain (from the
    # cycle endpoint) but no recovery AND no sleep almost always means a
    # recovery/sleep endpoint, OAuth scope, or score_state regression — exactly the
    # silent failure that left these columns NULL under the deprecated v1 API.
    # Surface it loudly instead of quietly writing half-empty rows.
    has_strain = any(f.get("strain") is not None for f in by_date.values())
    has_recovery = any(f.get("recovery_score") is not None for f in by_date.values())
    has_sleep = any(f.get("sleep_hours") is not None for f in by_date.values())
    if has_strain and not (has_recovery or has_sleep):
        def _diag(data, seen, scored):
            if data is None:
                return "endpoint error (see GET log above)"
            return f"{seen} record(s), {scored} scored"
        logger.warning(
            "User %s: Whoop sync wrote strain but NO recovery and NO sleep — "
            "recovery=[%s], sleep=[%s]. Check granted scopes (read:recovery "
            "read:sleep) and v2 endpoint health.",
            user.id,
            _diag(recovery_data, recovery_seen, recovery_scored),
            _diag(sleep_data, sleep_seen, sleep_scored),
        )

    # Upsert
    count = 0
    for d, fields in by_date.items():
        if not fields:
            continue
        fields = {k: v for k, v in fields.items() if v is not None}
        fields["source"] = "whoop"
        await upsert_health_snapshot(db, save_id, d, **fields)
        count += 1

    return count


async def sync_all_whoop_users() -> int:
    """Run a Whoop sync for every connected user. Called by the scheduler."""
    from db.database import AsyncSessionLocal
    from db.queries import get_users_with_whoop

    total = 0
    async with AsyncSessionLocal() as db:
        users = await get_users_with_whoop(db)
        for user in users:
            try:
                synced = await sync_user_whoop(db, user, days=2)
                total += synced
                logger.info(f"Whoop sync: user {user.id} → {synced} days")
            except Exception as e:
                logger.error(f"Whoop sync failed for user {user.id}: {e}")
    return total
