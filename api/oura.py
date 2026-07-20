"""
Oura OAuth2 + API client + daily data sync.

Flow (mirrors api/whoop.py):
  1. /connect oura in Telegram (or /api/v1/oura/connect-url from iOS) → user gets
     auth URL with state=their webhook_token
  2. User authorizes on Oura's site → Oura redirects to /oura/callback?code=...&state=...
  3. callback() exchanges code for access+refresh tokens, saves to user record
  4. Scheduler calls sync_user_oura() → refreshes if needed, fetches data,
     upserts into HealthSnapshot table

Oura specifics vs Whoop:
  - Access tokens last 24 h; refresh tokens are SINGLE-USE and rotate on every
    refresh, so the new refresh_token must always be persisted.
  - All v2 endpoints take start_date/end_date (YYYY-MM-DD) and return
    {"data": [...], "next_token": ...} — no score_state gating.
  - Every record carries a `day` field; for sleep it is the WAKE day, matching
    the "sleep lands on the day you woke up" convention the Whoop sync uses.

API docs: https://cloud.ouraring.com/docs
"""
import asyncio
import logging
import os
import time
from datetime import datetime, date, timedelta, timezone
from typing import Optional

import httpx

from db.models import User
from db.queries import set_oura_tokens, upsert_health_snapshot

logger = logging.getLogger(__name__)

OURA_CLIENT_ID = os.getenv("OURA_CLIENT_ID", "")
OURA_CLIENT_SECRET = os.getenv("OURA_CLIENT_SECRET", "")

AUTH_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"
API_BASE = "https://api.ouraring.com/v2/usercollection"

SCOPES = " ".join([
    "personal",
    "daily",      # daily_readiness / daily_sleep / daily_activity / daily_spo2
    "heartrate",
    "workout",
    "session",
    "spo2",
])


def build_auth_url(redirect_uri: str, state: str) -> str:
    """Build the Oura OAuth authorize URL the user visits."""
    from urllib.parse import urlencode
    params = {
        "client_id": OURA_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


# In-memory cache to make the callback idempotent — OAuth codes are one-time
# use, so a browser refresh/prefetch of the callback URL would otherwise fail
# with "code already used". Same pattern as api/whoop.py.
_CODE_CACHE: dict = {}
_CODE_TTL = 300  # seconds


def _gc_code_cache():
    now = time.time()
    expired = [k for k, v in _CODE_CACHE.items() if v["expires_at"] < now]
    for k in expired:
        _CODE_CACHE.pop(k, None)


async def exchange_code(code: str, redirect_uri: str) -> dict:
    """
    POST to /oauth/token with the auth code.
    Returns {"ok": True, "tokens": {...}} on success
    or {"ok": False, "error": "...", "details": "..."} on failure.
    Idempotent: replays cached tokens on repeated calls with the same code.
    """
    if not OURA_CLIENT_ID or not OURA_CLIENT_SECRET:
        return {"ok": False, "error": "OURA_CLIENT_ID / OURA_CLIENT_SECRET env vars not set on server"}

    _gc_code_cache()
    cached = _CODE_CACHE.get(code)
    if cached:
        logger.info("Replaying cached Oura token exchange for duplicate callback hit")
        return {"ok": True, "tokens": cached["tokens"], "replayed": True}

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": OURA_CLIENT_ID,
                    "client_secret": OURA_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if r.status_code >= 400:
                logger.error(f"Oura token exchange HTTP {r.status_code}: {r.text}")
                return {
                    "ok": False,
                    "error": f"Oura returned HTTP {r.status_code}",
                    "details": r.text[:500],
                }
            tokens = r.json()
            logger.info(
                f"Oura token exchange OK — keys: {list(tokens.keys())}, "
                f"has_refresh: {bool(tokens.get('refresh_token'))}, "
                f"expires_in: {tokens.get('expires_in')}"
            )
            _CODE_CACHE[code] = {"tokens": tokens, "expires_at": time.time() + _CODE_TTL}
            return {"ok": True, "tokens": tokens}
        except Exception as e:
            logger.error(f"Oura token exchange failed: {e}")
            return {"ok": False, "error": str(e)[:500]}


async def refresh_access_token(refresh_token: str) -> Optional[dict]:
    """Use the refresh token to get a new access token.

    Oura refresh tokens are single-use: the response carries a NEW
    refresh_token that must replace the stored one.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": OURA_CLIENT_ID,
                    "client_secret": OURA_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"Oura token refresh failed: {e}")
            return None


async def _ensure_fresh_token(db, user: User) -> Optional[str]:
    """
    Return a valid access token, refreshing if expired or close to expiring.
    Oura access tokens last 24 h; with a 60-minute buffer every 30-minute sync
    refreshes well before expiry, so no call ever hits a dead token.
    """
    now = datetime.utcnow()
    REFRESH_BUFFER = timedelta(minutes=60)
    has_fresh_access = (
        user.oura_access_token
        and user.oura_token_expires_at
        and user.oura_token_expires_at > now + REFRESH_BUFFER
    )

    if has_fresh_access:
        return user.oura_access_token

    if user.oura_refresh_token:
        logger.info(f"User {user.id}: refreshing Oura access token")
        tokens = await refresh_access_token(user.oura_refresh_token)
        if tokens:
            expires_at = now + timedelta(seconds=tokens.get("expires_in", 86400))
            await set_oura_tokens(
                db, user.id,
                access_token=tokens["access_token"],
                # Rotation: fall back to the old refresh token only if the
                # response somehow omits one (it shouldn't).
                refresh_token=tokens.get("refresh_token", user.oura_refresh_token),
                expires_at=expires_at,
            )
            return tokens["access_token"]
        logger.warning(f"User {user.id}: Oura token refresh failed — will try stale access token")

    if user.oura_access_token:
        logger.info(f"User {user.id}: using stale/no-refresh Oura access token")
        return user.oura_access_token

    return None


async def _oura_get(token: str, path: str, params: Optional[dict] = None) -> Optional[list]:
    """GET an Oura v2 endpoint, following next_token pagination.

    Returns the flattened `data` list, or None on error (so callers can tell
    "endpoint failed" apart from "no records").
    """
    records: list = []
    page_params = dict(params or {})
    async with httpx.AsyncClient(timeout=15) as client:
        for _ in range(5):  # pagination safety cap — a few days of data is 1 page
            try:
                r = await client.get(
                    f"{API_BASE}{path}",
                    headers={"Authorization": f"Bearer {token}"},
                    params=page_params,
                )
                if r.status_code >= 400:
                    logger.error(f"Oura GET {path} → HTTP {r.status_code}: {r.text[:300]}")
                    return None
                payload = r.json()
            except Exception as e:
                logger.error(f"Oura GET {path} failed: {e}")
                return None
            records.extend(payload.get("data") or [])
            next_token = payload.get("next_token")
            if not next_token:
                break
            page_params["next_token"] = next_token
    logger.info(f"Oura GET {path} → {len(records)} records")
    return records


def _day_of(rec: dict) -> Optional[date]:
    d = rec.get("day")
    if not d:
        return None
    try:
        return date.fromisoformat(d)
    except ValueError:
        return None


import re as _re_oura

# Oura's `activity` enum arrives in mixed shapes — camelCase ("strengthTraining"),
# snake_case ("jump_rope"), or already spaced. `.title()` alone COLLAPSES the
# camelCase hump ("strengthTraining" → "Strengthtraining"), which is how Chaya's
# entries read "Strengthtraining" / "Jumpingrope". Split on BOTH boundaries first.
_ACTIVITY_OVERRIDES = {
    "hiit": "HIIT", "spinning": "Spin", "elliptical": "Elliptical",
    "crosstraining": "Cross-Training", "strengthtraining": "Strength Training",
    # already-collapsed legacy values (pre-fix rows) so a re-title repairs them
    "jumpingrope": "Jumping Rope", "jumprope": "Jump Rope",
}


def _prettify_activity(raw: str) -> str:
    raw = (raw or "Workout").strip()
    key = raw.lower().replace("_", "").replace(" ", "").replace("-", "")
    if key in _ACTIVITY_OVERRIDES:
        return _ACTIVITY_OVERRIDES[key]
    # camelCase → spaced ("jumpingRope" → "jumping Rope"), then normalize
    # separators and Title-Case each word.
    spaced = _re_oura.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", raw)
    spaced = spaced.replace("_", " ").replace("-", " ")
    words = [w for w in spaced.split() if w]
    return " ".join(w[:1].upper() + w[1:].lower() for w in words) or "Workout"


async def _persist_oura_workouts(db, user: User, workouts: list) -> tuple[int, int]:
    """Auto-create ExerciseEntry rows from synced Oura workouts.

    Deduped by `source_ref` ("oura:<workout_id>") so repeated syncs upsert the
    same row in place instead of duplicating — same contract as the Whoop
    auto-log. Best-effort and idempotent; recomputes day totals after.
    """
    from sqlalchemy import select
    from db.models import ExerciseEntry
    from db.queries import get_or_create_log_for_date, recompute_log_totals

    by_date: dict = {}
    for w in workouts or []:
        d = _day_of(w)
        if d and w.get("id"):
            by_date.setdefault(d, []).append(w)

    created = updated = 0
    for d, day_workouts in by_date.items():
        try:
            log = await get_or_create_log_for_date(db, user.id, d)
        except Exception:
            continue
        touched = False
        for w in day_workouts:
            source_ref = f"oura:{w['id']}"
            occurred = None
            duration_min = None
            try:
                if w.get("start_datetime"):
                    s = datetime.fromisoformat(w["start_datetime"].replace("Z", "+00:00"))
                    occurred = s.astimezone(timezone.utc).replace(tzinfo=None)
                    if w.get("end_datetime"):
                        e = datetime.fromisoformat(w["end_datetime"].replace("Z", "+00:00"))
                        duration_min = round((e - s).total_seconds() / 60)
            except Exception:
                pass
            activity = _prettify_activity(w.get("activity") or w.get("label") or "Workout")
            cals = w.get("calories")
            notes_bits = []
            if w.get("intensity"):
                notes_bits.append(f"intensity {w['intensity']}")
            notes = "Oura: " + ", ".join(notes_bits) if notes_bits else "Oura"

            existing = (await db.execute(
                select(ExerciseEntry).where(ExerciseEntry.source_ref == source_ref)
            )).scalars().first()
            if existing:
                existing.daily_log_id = log.id
                existing.exercise_name = activity
                existing.cardio_type = activity  # oura sessions are duration-based
                existing.duration_minutes = duration_min
                existing.calories_burned_estimate = cals
                existing.occurred_at = occurred
                existing.notes = notes
                updated += 1
            else:
                db.add(ExerciseEntry(
                    daily_log_id=log.id,
                    exercise_name=activity,
                    cardio_type=activity,
                    duration_minutes=duration_min,
                    calories_burned_estimate=cals,
                    source_type="oura",
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
        logger.info(f"oura auto-log user {user.id}: {created} created, {updated} updated")
    return created, updated


async def sync_user_oura(db, user: User, days: int = 2,
                         snapshot_user_id: int = None) -> int:
    """
    Pull last `days` of Oura data and upsert into HealthSnapshot.
    snapshot_user_id: save snapshots to this user_id (use canonical for linked
                      accounts). Defaults to user.id.
    Returns number of days synced.
    """
    save_id = snapshot_user_id or user.id
    token = await _ensure_fresh_token(db, user)
    if not token:
        return 0

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    params = {"start_date": start.isoformat(), "end_date": end.isoformat()}

    readiness, daily_sleep, sleep_periods, activity, spo2, workouts = await asyncio.gather(
        _oura_get(token, "/daily_readiness", params),
        _oura_get(token, "/daily_sleep", params),
        _oura_get(token, "/sleep", params),
        _oura_get(token, "/daily_activity", params),
        _oura_get(token, "/daily_spo2", params),
        _oura_get(token, "/workout", params),
        return_exceptions=False,
    )

    by_date: dict = {}

    def _ensure(d: date):
        by_date.setdefault(d, {})

    # Readiness score → the "recovery" slot the coach already reads.
    for rec in readiness or []:
        d = _day_of(rec)
        if not d or rec.get("score") is None:
            continue
        _ensure(d)
        by_date[d]["recovery_score"] = rec["score"]

    # Detailed sleep periods. `day` is the wake day; naps/rests are separate
    # records that must not overwrite the night's main sleep.
    for sl in sleep_periods or []:
        d = _day_of(sl)
        if not d:
            continue
        if sl.get("type") not in (None, "long_sleep", "sleep"):
            continue  # skip nap / late_nap / rest
        _ensure(d)
        if sl.get("time_in_bed"):
            by_date[d]["sleep_hours"] = round(sl["time_in_bed"] / 3600, 2)
        if sl.get("deep_sleep_duration"):
            by_date[d]["sleep_deep_hours"] = round(sl["deep_sleep_duration"] / 3600, 2)
        if sl.get("rem_sleep_duration"):
            by_date[d]["sleep_rem_hours"] = round(sl["rem_sleep_duration"] / 3600, 2)
        if sl.get("average_hrv") is not None:
            by_date[d]["hrv"] = sl["average_hrv"]
        if sl.get("lowest_heart_rate") is not None:
            # Oura's nightly lowest HR is its resting-HR signal.
            by_date[d]["resting_hr"] = sl["lowest_heart_rate"]
        if sl.get("average_breath") is not None:
            by_date[d]["respiratory_rate"] = sl["average_breath"]
        if sl.get("efficiency") is not None:
            by_date[d]["sleep_efficiency_pct"] = sl["efficiency"]

    # Daily sleep score → the same slot Whoop's sleep performance uses.
    for rec in daily_sleep or []:
        d = _day_of(rec)
        if not d or rec.get("score") is None:
            continue
        _ensure(d)
        by_date[d]["sleep_performance_pct"] = rec["score"]

    for rec in activity or []:
        d = _day_of(rec)
        if not d:
            continue
        _ensure(d)
        if rec.get("active_calories") is not None:
            by_date[d]["active_calories"] = rec["active_calories"]
        if rec.get("steps") is not None:
            by_date[d]["steps"] = rec["steps"]

    for rec in spo2 or []:
        d = _day_of(rec)
        avg = (rec.get("spo2_percentage") or {}).get("average") if rec else None
        if not d or avg is None:
            continue
        _ensure(d)
        by_date[d]["spo2_percentage"] = avg

    # Auto-populate the day's log with workouts (deduped by source_ref) so a
    # ring-detected session shows up on the timeline like a manual log.
    if workouts:
        try:
            await _persist_oura_workouts(db, user, workouts)
        except Exception as e:  # best-effort: never break the snapshot sync
            logger.warning(f"oura workout auto-log failed for user {user.id}: {e}")

    # Regression visibility (mirrors the Whoop guard): readiness flowing while
    # sleep is empty usually means a scope or endpoint regression, not "the user
    # didn't sleep". Surface it loudly instead of writing half-empty rows.
    has_readiness = any(f.get("recovery_score") is not None for f in by_date.values())
    has_sleep = any(f.get("sleep_hours") is not None for f in by_date.values())
    if has_readiness and not has_sleep:
        logger.warning(
            "User %s: Oura sync wrote readiness but NO sleep — sleep endpoint "
            "returned %s. Check granted scopes and /v2/usercollection/sleep health.",
            user.id,
            "error" if sleep_periods is None else f"{len(sleep_periods)} record(s)",
        )

    count = 0
    for d, fields in by_date.items():
        if not fields:
            continue
        fields = {k: v for k, v in fields.items() if v is not None}
        fields["source"] = "oura"
        await upsert_health_snapshot(db, save_id, d, **fields)
        count += 1

    return count


async def sync_all_oura_users() -> int:
    """Run an Oura sync for every connected user. Called by the scheduler."""
    from db.database import AsyncSessionLocal
    from db.queries import get_users_with_oura

    total = 0
    async with AsyncSessionLocal() as db:
        users = await get_users_with_oura(db)
        for user in users:
            try:
                # 4-day rolling window (was 2): a missed scheduler run or a
                # late-arriving readiness score can't silently drop a day —
                # the sync is idempotent (upsert by date), so the overlap is free.
                synced = await sync_user_oura(db, user, days=4)
                total += synced
                logger.info(f"Oura sync: user {user.id} → {synced} days")
            except Exception as e:
                logger.error(f"Oura sync failed for user {user.id}: {e}")
    return total
