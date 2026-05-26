"""
FastAPI app — runs alongside the Telegram bot in the same process.
Exposes:
  GET  /health                  — health check
  GET  /dashboard/{token}       — read-only user dashboard (HTML)
  GET  /api/stats/{token}       — dashboard data (JSON)
  POST /health/apple?token=...  — Apple Health inbound webhook
"""
import os
from datetime import date, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from db.database import AsyncSessionLocal
from db.queries import (
    get_user_by_webhook_token, upsert_health_snapshot,
    get_today_log, get_log_by_date, get_recent_logs, get_recent_weights,
    get_recent_health_snapshots,
    update_food_entry, delete_food_entry,
    update_exercise_entry, delete_exercise_entry,
)

app = FastAPI(title="Arnie API", docs_url=None, redoc_url=None)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ok", "service": "Arnie Bot"}


@app.get("/health")
async def healthcheck():
    return {"status": "ok"}


# ── Whoop OAuth ────────────────────────────────────────────────────────────────

@app.get("/whoop/callback", response_class=HTMLResponse)
async def whoop_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Whoop redirects here after user authorizes. Exchange code for tokens."""
    if error:
        return HTMLResponse(
            f"<h2>Whoop connection failed</h2><p>Error: {error}</p>"
            f"<p>You can try again in Telegram with /connect whoop</p>",
            status_code=400,
        )
    if not code or not state:
        return HTMLResponse("<h2>Missing code or state.</h2>", status_code=400)

    from api.whoop import exchange_code, sync_user_whoop
    from db.queries import set_whoop_tokens
    from datetime import datetime, timedelta

    base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000").rstrip("/")
    redirect_uri = f"{base_url}/whoop/callback"

    result = await exchange_code(code, redirect_uri)

    # If Whoop says "code already used" but the user already has valid tokens
    # from a previous (successful) exchange, treat this as success instead of
    # an error. This handles browser back/refresh after a working connection.
    if not result.get("ok") and "already been used" in (result.get("details") or "").lower():
        async with AsyncSessionLocal() as db:
            existing_user = await get_user_by_webhook_token(db, state)
            if existing_user and existing_user.whoop_refresh_token:
                return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Whoop already connected</title>
<style>body{font-family:system-ui;text-align:center;padding:60px 20px;background:#0f1117;color:#f1f5f9}
.box{max-width:480px;margin:auto;background:#1a1d27;border:1px solid #2e3347;border-radius:12px;padding:32px}
.check{font-size:48px;color:#22c55e}h1{font-size:24px;margin:16px 0}p{color:#94a3b8;margin:8px 0}</style>
</head><body>
<div class="box">
  <div class="check">✓</div>
  <h1>Already connected</h1>
  <p>Your Whoop is already linked. No action needed.</p>
  <p style="margin-top:20px">Run <b>/whoop</b> in Telegram to see your status.</p>
</div></body></html>""")

    if not result.get("ok"):
        err = result.get("error", "Unknown error")
        details = result.get("details", "")
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Whoop connection failed</title>
<style>body{{font-family:system-ui;text-align:left;padding:40px;background:#0f1117;color:#f1f5f9;max-width:640px;margin:auto}}
.box{{background:#1a1d27;border:1px solid #2e3347;border-radius:12px;padding:24px}}
h1{{font-size:22px;margin:0 0 12px;color:#ef4444}}
code{{background:#0f1117;padding:2px 6px;border-radius:4px;font-size:12px;color:#94a3b8;display:block;padding:12px;margin-top:8px;white-space:pre-wrap;word-break:break-all}}
.next{{margin-top:20px;padding-top:16px;border-top:1px solid #2e3347;color:#94a3b8}}</style>
</head><body><div class="box">
<h1>Whoop connection failed</h1>
<p><b>Error:</b> {err}</p>
{f'<code>{details}</code>' if details else ''}
<div class="next">
  <p><b>Common causes:</b></p>
  <ul style="color:#94a3b8;line-height:1.7">
    <li>The auth code already expired (they're one-time, ~30 seconds) — try /connect whoop again</li>
    <li>WHOOP_CLIENT_ID or WHOOP_CLIENT_SECRET env var on Render is wrong or missing</li>
    <li>The Redirect URL in Whoop's developer dashboard doesn't exactly match this server's URL</li>
  </ul>
</div></div></body></html>""", status_code=400)

    tokens = result["tokens"]
    user_id_for_sync = None
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, state)
        if not user:
            return HTMLResponse("<h2>Invalid state — user not found.</h2>", status_code=401)

        expires_at = datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))
        await set_whoop_tokens(
            db, user.id,
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token", ""),
            expires_at=expires_at,
        )
        user_id_for_sync = user.id

    # Kick off the initial sync in the background — DON'T block the response.
    # Whoop's three API calls together can take 30+ seconds and Render's
    # load balancer will 502 if the response doesn't come back in time.
    import asyncio
    asyncio.create_task(_background_initial_sync(user_id_for_sync, user.telegram_id))

    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Whoop connected</title>
<style>body{{font-family:system-ui;text-align:center;padding:60px 20px;background:#0f1117;color:#f1f5f9}}
.box{{max-width:480px;margin:auto;background:#1a1d27;border:1px solid #2e3347;border-radius:12px;padding:32px}}
.check{{font-size:48px;color:#22c55e}}h1{{font-size:24px;margin:16px 0}}p{{color:#94a3b8;margin:8px 0}}</style>
</head><body>
<div class="box">
  <div class="check">✓</div>
  <h1>Whoop connected</h1>
  <p>Tokens saved. I'm pulling your last 7 days of data in the background — should be ready in 30 seconds or so.</p>
  <p style="margin-top:20px">Head back to Telegram and run <b>/whoop</b> to see your latest snapshot.</p>
</div></body></html>""")


async def _background_initial_sync(user_id: int, telegram_id: str = ""):
    """Run the initial Whoop data pull after the OAuth callback has returned."""
    import logging
    import os
    logger = logging.getLogger(__name__)
    from api.whoop import sync_user_whoop
    try:
        async with AsyncSessionLocal() as db:
            from db.queries import reload_user
            user = await reload_user(db, user_id)
            synced = await sync_user_whoop(db, user, days=7)
            logger.info(f"Background Whoop sync: user {user_id} → {synced} days")

            if telegram_id:
                snaps = await get_recent_health_snapshots(db, user_id, days=1)
                snap = snaps[0] if snaps else None
                from telegram import Bot
                bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN", ""))
                if snap and snap.recovery_score is not None:
                    rec = snap.recovery_score
                    emoji = "🟢" if rec >= 67 else ("🟡" if rec >= 34 else "🔴")
                    parts = [f"✅ <b>Whoop connected + synced!</b>", ""]
                    parts.append(f"{emoji} Recovery: <b>{rec}%</b>")
                    if snap.hrv:
                        parts.append(f"HRV: {snap.hrv:.0f}ms  |  RHR: {snap.resting_hr:.0f}bpm" if snap.resting_hr else f"HRV: {snap.hrv:.0f}ms")
                    if snap.sleep_hours:
                        s = f"Sleep: {snap.sleep_hours:.1f}h"
                        extras = []
                        if snap.sleep_deep_hours:
                            extras.append(f"deep {snap.sleep_deep_hours:.1f}h")
                        if snap.sleep_rem_hours:
                            extras.append(f"REM {snap.sleep_rem_hours:.1f}h")
                        if extras:
                            s += f" ({', '.join(extras)})"
                        parts.append(s)
                    if snap.strain is not None:
                        parts.append(f"Strain: {snap.strain:.1f}")
                    await bot.send_message(chat_id=telegram_id, text="\n".join(parts), parse_mode="HTML")
                else:
                    await bot.send_message(
                        chat_id=telegram_id,
                        text="✅ <b>Whoop connected!</b>\n\nPulled your last 7 days. Recovery scores will show once Whoop processes your sleep data — usually by 9am.",
                        parse_mode="HTML"
                    )
                await bot.close()
    except Exception as e:
        logger.error(f"Background Whoop sync failed for user {user_id}: {e}")


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    """Minimal privacy policy required by Whoop / Apple Health OAuth."""
    return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Arnie — Privacy Policy</title>
<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 20px;line-height:1.6;color:#222}h1{font-size:24px}h2{font-size:18px;margin-top:28px}</style>
</head><body>
<h1>Arnie — Privacy Policy</h1>
<p><em>Last updated: 2026</em></p>

<h2>What Arnie collects</h2>
<p>Arnie is a personal fitness and nutrition coaching bot. With your consent, Arnie collects:</p>
<ul>
<li>Profile information you provide during onboarding (name, age, sex, height, weight, goals, training experience, dietary preferences, injuries).</li>
<li>Food, exercise, body-weight, and water entries you log via chat, voice, or photos.</li>
<li>Wearable data you choose to connect (e.g. WHOOP recovery and sleep, Apple Health metrics).</li>
<li>Conversation history with the bot, used to provide context-aware coaching.</li>
</ul>

<h2>How Arnie uses your data</h2>
<p>Your data is used solely to:</p>
<ul>
<li>Track your nutrition, training, and recovery over time.</li>
<li>Provide personalized coaching responses, pacing reminders, and progress insights.</li>
<li>Display your data back to you via the Telegram chat and your personal dashboard.</li>
</ul>
<p>Your data is never sold, shared with advertisers, or used to train any external models.</p>

<h2>Where your data is stored</h2>
<p>Data is stored on a private server (Render.com) in an encrypted database accessible only by you (via your unique Telegram account and personal dashboard token). Conversation history is processed by Anthropic's Claude API to generate coaching responses; per Anthropic's policy, API data is not used for model training.</p>

<h2>Third-party services Arnie uses</h2>
<ul>
<li><strong>Telegram</strong> — the chat platform itself.</li>
<li><strong>Anthropic Claude</strong> — generates coaching responses.</li>
<li><strong>OpenAI</strong> — used for voice transcription (Whisper) and optional image generation (DALL-E).</li>
<li><strong>WHOOP</strong> (if you connect it) — fitness wearable data.</li>
<li><strong>Apple Health</strong> (if you connect it) — fitness wearable data, sent via your own iOS Shortcut.</li>
</ul>

<h2>Your rights</h2>
<p>You can:</p>
<ul>
<li>Clear today's log with <code>/reset today</code>.</li>
<li>Permanently delete all your data with <code>/reset all confirm</code>.</li>
<li>Disconnect WHOOP or revoke its access from your WHOOP account at any time.</li>
<li>Stop using Arnie by blocking the bot in Telegram.</li>
</ul>

<h2>Contact</h2>
<p>For any privacy questions or to request data deletion, contact the Arnie developer through the GitHub repository.</p>
</body></html>""")


# ── Telegram webhook ───────────────────────────────────────────────────────────

@app.post("/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    """Receive updates from Telegram (production webhook mode)."""
    if token != os.getenv("TELEGRAM_BOT_TOKEN", ""):
        raise HTTPException(status_code=403, detail="Forbidden")

    ptb_app = getattr(request.app.state, "ptb_app", None)
    if ptb_app is None:
        raise HTTPException(status_code=503, detail="Bot not ready")

    from telegram import Update
    data = await request.json()
    update = Update.de_json(data, ptb_app.bot)
    await ptb_app.process_update(update)
    return {"ok": True}


# ── Stats API ──────────────────────────────────────────────────────────────────

@app.get("/api/insights/{token}")
async def get_insights_endpoint(token: str, force: bool = False):
    """Return 3-5 AI-generated coaching insights based on user data."""
    from api.insights import get_insights
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        # Re-use the stats payload to feed the LLM
        stats = await _build_stats_for_user(db, user)
        insights = await get_insights(user.id, stats, force=force)
    return {"insights": insights}


def _compute_analytics(user, prefs, weight_data):
    """TDEE, deficit, protein rec, and goal-pace from user profile."""
    result = {}
    if not all([user.current_weight_kg, user.height_cm, user.age, user.sex]):
        return result

    w, h, a = user.current_weight_kg, user.height_cm, user.age
    sex = (user.sex or "").lower()
    if sex in ("m", "male", "man"):
        bmr = 10 * w + 6.25 * h - 5 * a + 5
    else:
        bmr = 10 * w + 6.25 * h - 5 * a - 161

    exp = (user.training_experience or "").lower()
    if any(k in exp for k in ("advanced", "athlete", "very")):
        factor = 1.725
    elif any(k in exp for k in ("beginner", "new", "start")):
        factor = 1.375
    else:
        factor = 1.55

    tdee = round(bmr * factor)
    result["tdee_estimate"] = tdee
    result["bmr"] = round(bmr)
    result["activity_factor"] = factor

    lbs = w * 2.20462
    result["rec_protein_min"] = round(lbs * 0.7)
    result["rec_protein_max"] = round(lbs * 1.0)

    if prefs and prefs.calorie_target:
        daily_diff = prefs.calorie_target - tdee
        result["daily_vs_tdee"] = daily_diff
        result["pace_label"] = "deficit" if daily_diff < 0 else ("surplus" if daily_diff > 0 else "maintenance")
        result["pace_lbs_per_week"] = round(abs(daily_diff) * 7 / 3500, 1) if daily_diff != 0 else 0

        if user.goal_weight_kg and result.get("pace_lbs_per_week", 0) > 0:
            lbs_to_go = abs(w - user.goal_weight_kg) * 2.20462
            result["lbs_to_goal"] = round(lbs_to_go, 1)
            result["weeks_to_goal"] = round(lbs_to_go / result["pace_lbs_per_week"])

    if len(weight_data) >= 2:
        oldest, newest = weight_data[0], weight_data[-1]
        from datetime import date as dt
        d1, d2 = dt.fromisoformat(oldest["date"]), dt.fromisoformat(newest["date"])
        days = (d2 - d1).days
        if days > 0:
            result["actual_lbs_per_week"] = round((newest["lbs"] - oldest["lbs"]) / (days / 7), 1)

    return result


async def _build_stats_for_user(db, user, target_date=None):
    """Shared stats-building logic for /api/stats and /api/insights."""
    from datetime import date as dt_date
    prefs = user.preferences
    history = await get_recent_logs(db, user.id, days=60)
    weights = await get_recent_weights(db, user.id, days=90)
    health_snaps = await get_recent_health_snapshots(db, user.id, days=14)

    # Determine which day's entries to return
    if target_date:
        day_log = await get_log_by_date(db, user.id, target_date)
    else:
        day_log = await get_today_log(db, user.id, user.timezone or "UTC")

    weight_data = [
        {"date": w.timestamp.strftime("%Y-%m-%d"),
         "kg": round(w.weight_kg, 1),
         "lbs": round(w.weight_kg * 2.20462, 1)}
        for w in sorted(weights, key=lambda w: w.timestamp)
    ]

    def _log_to_day(log):
        if not log:
            return None
        return {
            "date": str(log.date),
            "status": log.status,
            "calories": round(log.total_calories or 0),
            "protein": round(log.total_protein or 0),
            "carbs": round(log.total_carbs or 0),
            "fats": round(log.total_fats or 0),
            "water_ml": round(log.total_water_ml or 0),
            "workout_completed": log.workout_completed,
            "cardio_completed": log.cardio_completed,
            "food_entries": [
                {"id": e.id, "name": e.parsed_food_name or "?",
                 "quantity": e.quantity or "",
                 "calories": round(e.calories or 0), "protein": round(e.protein or 0),
                 "carbs": round(e.carbs or 0), "fats": round(e.fats or 0),
                 "estimated": bool(e.estimated_flag)}
                for e in (log.food_entries or [])
            ],
            "exercise_entries": [
                {"id": e.id, "name": e.exercise_name or "?",
                 "sets": e.sets, "reps": e.reps,
                 "weight": round(e.weight * 2.20462, 1) if e.weight else None,
                 "duration_minutes": e.duration_minutes}
                for e in (log.exercise_entries or [])
            ],
        }

    hist_data = [
        {"date": str(log.date),
         "calories": round(log.total_calories or 0),
         "protein": round(log.total_protein or 0),
         "carbs": round(log.total_carbs or 0),
         "fats": round(log.total_fats or 0),
         "workout": log.workout_completed,
         "status": log.status}
        for log in sorted(history, key=lambda l: l.date)
    ]

    health_data = [
        {"date": str(s.date), "source": s.source,
         "recovery_score": s.recovery_score,
         "hrv": round(s.hrv) if s.hrv else None,
         "resting_hr": round(s.resting_hr) if s.resting_hr else None,
         "sleep_hours": s.sleep_hours,
         "sleep_deep_hours": s.sleep_deep_hours,
         "sleep_rem_hours": s.sleep_rem_hours,
         "strain": s.strain,
         "steps": s.steps}
        for s in health_snaps
    ]

    available_dates = sorted({d["date"] for d in hist_data})
    analytics = _compute_analytics(user, prefs, weight_data)

    def _ht():
        if not user.height_cm:
            return ""
        total_in = user.height_cm / 2.54
        return f"{int(total_in // 12)}'{int(total_in % 12)}\""

    profile = {
        "name": user.name or "User",
        "age": user.age,
        "sex": user.sex,
        "height_cm": user.height_cm,
        "height_ft": _ht(),
        "current_weight_lbs": round(user.current_weight_kg * 2.20462, 1) if user.current_weight_kg else None,
        "goal_weight_lbs": round(user.goal_weight_kg * 2.20462, 1) if user.goal_weight_kg else None,
        "primary_goal": user.primary_goal,
        "training_experience": user.training_experience,
        "dietary_preferences": user.dietary_preferences,
        "injuries": user.injuries,
        "timezone": user.timezone,
        "coaching_style": prefs.coaching_style if prefs else None,
        "calorie_target": prefs.calorie_target if prefs else None,
        "protein_target": prefs.protein_target if prefs else None,
        "whoop_connected": bool(user.whoop_access_token or user.whoop_refresh_token),
        "apple_health_connected": any(s.source == "apple_health" for s in health_snaps),
        "analytics": analytics,
    }

    return {
        "profile": profile,
        "targets": {
            "calories": prefs.calorie_target if prefs else None,
            "protein": prefs.protein_target if prefs else None,
        },
        "day": _log_to_day(day_log),
        "history": hist_data,
        "weights": weight_data,
        "health": health_data,
        "available_dates": available_dates,
        "viewing_date": str(target_date or dt_date.today()),
        # keep legacy 'today' + 'user' keys so existing insights endpoint works unchanged
        "today": _log_to_day(day_log),
        "user": {"name": user.name or "User", "goal": user.primary_goal or "—",
                 "current_weight_lbs": profile["current_weight_lbs"],
                 "goal_weight_lbs": profile["goal_weight_lbs"]},
    }


@app.get("/api/stats/{token}")
async def get_stats(token: str, date: Optional[str] = Query(None)):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        target_date = None
        if date:
            try:
                from datetime import date as dt_date
                target_date = dt_date.fromisoformat(date)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date, use YYYY-MM-DD")
        return await _build_stats_for_user(db, user, target_date=target_date)


# ── Edit / delete entries from the dashboard ───────────────────────────────────

class FoodPatch(BaseModel):
    food_name: Optional[str] = None
    quantity: Optional[str] = None
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None


class ExercisePatch(BaseModel):
    exercise_name: Optional[str] = None
    sets: Optional[int] = None
    reps: Optional[str] = None
    weight: Optional[float] = None  # in lbs from the dashboard, converted to kg below
    duration_minutes: Optional[float] = None


@app.patch("/api/food/{entry_id}")
async def api_edit_food(entry_id: int, patch: FoodPatch, token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        changes = patch.model_dump(exclude_none=True)
        # Map external "food_name" → internal column "parsed_food_name"
        if "food_name" in changes:
            changes["parsed_food_name"] = changes.pop("food_name")
        entry = await update_food_entry(db, entry_id, user.id, **changes)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
    return {"status": "ok", "id": entry_id}


@app.delete("/api/food/{entry_id}")
async def api_delete_food(entry_id: int, token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        ok = await delete_food_entry(db, entry_id, user.id)
        if not ok:
            raise HTTPException(status_code=404, detail="Entry not found")
    return {"status": "ok"}


@app.patch("/api/exercise/{entry_id}")
async def api_edit_exercise(entry_id: int, patch: ExercisePatch, token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        changes = patch.model_dump(exclude_none=True)
        # Dashboard sends weight in lbs; DB stores kg
        if "weight" in changes:
            changes["weight"] = changes["weight"] * 0.453592
        entry = await update_exercise_entry(db, entry_id, user.id, **changes)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
    return {"status": "ok", "id": entry_id}


@app.delete("/api/exercise/{entry_id}")
async def api_delete_exercise(entry_id: int, token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        ok = await delete_exercise_entry(db, entry_id, user.id)
        if not ok:
            raise HTTPException(status_code=404, detail="Entry not found")
    return {"status": "ok"}


# ── Dashboard HTML ─────────────────────────────────────────────────────────────

@app.get("/dashboard/{token}", response_class=HTMLResponse)
async def dashboard(token: str):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            return HTMLResponse("<h2>Invalid or expired link.</h2>", status_code=401)

    return HTMLResponse(_dashboard_html(token))


def _dashboard_html(token: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Arnie</title>
<script>
(function(){{
  var t=localStorage.getItem('arnie-theme')||
    (window.matchMedia('(prefers-color-scheme:light)').matches?'light':'dark');
  document.documentElement.setAttribute('data-theme',t);
}})();
</script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}}

/* ── THEMES ─────────────────────────────────────────────── */
[data-theme="dark"]{{
  --bg:#070c18;
  --sf:rgba(255,255,255,.045); --sf2:rgba(255,255,255,.08); --sf3:rgba(255,255,255,.13);
  --bd:rgba(255,255,255,.09);  --bd2:rgba(255,255,255,.18);
  --ac:#00e676; --ac-rgb:0,230,118; --ac-dim:rgba(0,230,118,.12);
  --bl:#3b82f6; --or:#f97316; --pu:#a855f7; --re:#ef4444; --ye:#eab308;
  --tx:#eef2ff; --tx2:#c8d0e8; --mu:#6b7a99; --di:#3d4a66;
  --sh:none; --hbg:rgba(7,12,24,.92);
  --cgrid:rgba(255,255,255,.05); --ctick:#4a5568; --inp:rgba(255,255,255,.05);
}}
[data-theme="light"]{{
  --bg:#f0f4f8;
  --sf:#ffffff; --sf2:#f5f8fc; --sf3:#edf2f7;
  --bd:#e2e8f0; --bd2:#cbd5e1;
  --ac:#059669; --ac-rgb:5,150,105; --ac-dim:rgba(5,150,105,.1);
  --bl:#2563eb; --or:#ea580c; --pu:#9333ea; --re:#dc2626; --ye:#d97706;
  --tx:#0f172a; --tx2:#334155; --mu:#64748b; --di:#94a3b8;
  --sh:0 1px 3px rgba(0,0,0,.07),0 4px 16px rgba(0,0,0,.05);
  --hbg:rgba(240,244,248,.92);
  --cgrid:#e2e8f0; --ctick:#94a3b8; --inp:#f8fafc;
}}

/* ── BASE ────────────────────────────────────────────────── */
html{{background:var(--bg);transition:background .3s,color .3s}}
body{{
  font-family:'Inter',-apple-system,system-ui,sans-serif;
  background:var(--bg);color:var(--tx);min-height:100vh;
  -webkit-font-smoothing:antialiased;overflow-x:hidden;position:relative;
  padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom);
  transition:background .3s,color .3s;
}}
[data-theme="dark"] body::before{{
  content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(ellipse 80% 50% at 15% 20%,rgba(0,230,118,.07),transparent),
    radial-gradient(ellipse 60% 40% at 85% 70%,rgba(59,130,246,.05),transparent);
  animation:mesh 20s ease-in-out infinite alternate;
}}
@keyframes mesh{{0%{{opacity:.7;transform:scale(1)}}100%{{opacity:1;transform:scale(1.06)}}}}

/* ── HEADER ─────────────────────────────────────────────── */
header{{
  background:var(--hbg);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
  border-bottom:1px solid var(--bd);padding:10px 16px;
  display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;z-index:100;transition:background .3s;
}}
.logo{{
  font-size:17px;font-weight:800;letter-spacing:-.5px;
  background:linear-gradient(130deg,var(--ac),var(--bl));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}}
.hdr-r{{display:flex;align-items:center;gap:8px}}
.u-name{{font-size:13px;font-weight:600;color:var(--tx2)}}
.g-tag{{
  background:var(--ac-dim);color:var(--ac);font-size:10px;font-weight:700;
  padding:3px 8px;border-radius:20px;border:1px solid rgba(var(--ac-rgb),.25);
  text-transform:capitalize;
}}
.hbtn{{
  background:var(--sf2);border:1px solid var(--bd2);color:var(--mu);
  width:34px;height:34px;border-radius:10px;cursor:pointer;font-size:15px;
  display:flex;align-items:center;justify-content:center;font-family:inherit;
  transition:all .2s;flex-shrink:0;
}}
.hbtn:hover{{border-color:var(--ac);color:var(--ac)}}
.hbtn:active{{transform:scale(.91)}}

/* ── TABS ────────────────────────────────────────────────── */
.tabs{{
  background:var(--hbg);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
  border-bottom:1px solid var(--bd);padding:8px 14px;
  display:flex;gap:4px;position:sticky;top:55px;z-index:99;
  transition:background .3s;
}}
.tab-pill{{
  position:absolute;bottom:8px;height:calc(100% - 16px);
  background:var(--sf2);border:1px solid var(--bd2);border-radius:10px;
  transition:left .25s cubic-bezier(.4,0,.2,1),width .25s cubic-bezier(.4,0,.2,1);
  pointer-events:none;z-index:0;
}}
.tab-btn{{
  flex:1;padding:8px 10px;border-radius:10px;border:none;
  background:transparent;color:var(--mu);font-size:13px;font-weight:600;
  cursor:pointer;font-family:inherit;min-height:36px;
  transition:color .2s;position:relative;z-index:1;
}}
.tab-btn.active{{color:var(--tx)}}

/* ── MAIN ────────────────────────────────────────────────── */
main{{max-width:920px;margin:0 auto;padding:14px 12px 72px;position:relative;z-index:1}}
#app-load{{text-align:center;padding:80px 20px;color:var(--mu);font-size:14px}}
.tab-panel{{display:none;animation:fadeUp .28s ease}}
.tab-panel.active{{display:block}}

/* ── SECTION TITLES ─────────────────────────────────────── */
.stitle{{
  font-size:10px;font-weight:700;color:var(--di);text-transform:uppercase;
  letter-spacing:1.4px;margin:22px 2px 10px;display:flex;align-items:center;gap:8px;
}}
.stitle:first-child{{margin-top:2px}}
.ai-pill{{
  background:var(--ac-dim);color:var(--ac);border:1px solid rgba(var(--ac-rgb),.2);
  padding:2px 7px;border-radius:10px;font-size:9px;letter-spacing:.5px;font-weight:700;
}}

/* ── DATE NAV ────────────────────────────────────────────── */
.dnav{{display:flex;align-items:center;gap:6px;margin-bottom:16px}}
.dscroll{{flex:1;display:flex;gap:6px;overflow-x:auto;scrollbar-width:none}}
.dscroll::-webkit-scrollbar{{display:none}}
.darr{{
  background:var(--sf);border:1px solid var(--bd);color:var(--mu);
  width:36px;height:36px;min-width:36px;border-radius:10px;cursor:pointer;
  font-size:16px;display:flex;align-items:center;justify-content:center;
  font-family:inherit;flex-shrink:0;transition:all .2s;
  backdrop-filter:blur(12px);box-shadow:var(--sh);
}}
.darr:hover{{border-color:var(--bd2);color:var(--tx)}}
.darr:disabled{{opacity:.3;cursor:default}}
.dchip{{
  background:var(--sf);border:1px solid var(--bd);color:var(--mu);
  padding:7px 13px;border-radius:10px;font-size:12px;font-weight:600;
  white-space:nowrap;cursor:pointer;transition:all .2s;flex-shrink:0;
  display:inline-flex;align-items:center;gap:5px;
  backdrop-filter:blur(12px);box-shadow:var(--sh);
}}
.dchip:hover{{border-color:var(--bd2);color:var(--tx2)}}
.dchip.active{{background:var(--ac-dim);border-color:var(--ac);color:var(--ac)}}
.today-tag{{
  background:var(--ac);color:#fff;font-size:9px;font-weight:700;
  padding:1px 5px;border-radius:5px;
}}
[data-theme="dark"] .today-tag{{color:#000}}

/* ── MACRO CARDS ─────────────────────────────────────────── */
.cards{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}}
@media(min-width:560px){{.cards{{grid-template-columns:repeat(4,1fr)}}}}
.card{{
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;padding:15px;
  backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
  box-shadow:var(--sh);transition:background .3s,border-color .3s;
  position:relative;overflow:hidden;
}}
[data-theme="dark"] .card::before{{
  content:'';position:absolute;inset:0;border-radius:16px;
  background:linear-gradient(135deg,rgba(255,255,255,.025),transparent);
  pointer-events:none;
}}
.clbl{{font-size:10px;color:var(--mu);text-transform:uppercase;letter-spacing:.8px;margin-bottom:6px;font-weight:700}}
.cval{{font-size:24px;font-weight:800;line-height:1;letter-spacing:-.5px}}
.csub{{font-size:11px;color:var(--mu);margin-top:4px;font-weight:500}}
.ptrack{{background:var(--sf2);border-radius:999px;height:4px;margin-top:12px;overflow:hidden}}
.pfill{{height:100%;border-radius:999px;transition:width .8s cubic-bezier(.4,0,.2,1)}}
[data-theme="dark"] .pfill{{filter:brightness(1.15) saturate(1.2)}}

/* ── STATUS BADGES ───────────────────────────────────────── */
.sbrow{{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}}
.badge{{
  display:inline-flex;align-items:center;gap:5px;
  padding:6px 12px;border-radius:10px;font-size:12px;font-weight:600;
  border:1px solid transparent;
}}
.bg-g{{background:rgba(var(--ac-rgb),.1);color:var(--ac);border-color:rgba(var(--ac-rgb),.2)}}
.bg-n{{background:var(--sf2);color:var(--mu);border-color:var(--bd)}}
.bg-b{{background:rgba(59,130,246,.1);color:var(--bl);border-color:rgba(59,130,246,.2)}}

/* ── INSIGHTS ────────────────────────────────────────────── */
.icrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;overflow:hidden;
  backdrop-filter:blur(16px);box-shadow:var(--sh);transition:background .3s;
}}
[data-theme="dark"] .icrd{{
  background:linear-gradient(160deg,rgba(0,230,118,.04),transparent 60%),var(--sf);
  border-color:rgba(0,230,118,.15);
}}
.irow{{
  display:grid;grid-template-columns:28px 1fr;gap:10px;
  padding:12px 14px;border-bottom:1px solid var(--bd);align-items:flex-start;
}}
.irow:last-child{{border-bottom:none}}
.iico{{
  font-size:11px;width:24px;height:24px;flex-shrink:0;margin-top:1px;
  background:var(--ac-dim);color:var(--ac);border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  border:1px solid rgba(var(--ac-rgb),.2);
}}
.itxt{{font-size:13px;line-height:1.55;color:var(--tx2)}}
.iload,.iempty{{padding:20px 14px;color:var(--mu);font-size:13px;text-align:center}}

/* ── WEARABLE ────────────────────────────────────────────── */
.hgrid{{display:grid;gap:8px;grid-template-columns:repeat(3,1fr)}}
@media(min-width:560px){{.hgrid{{grid-template-columns:repeat(6,1fr)}}}}
.htile{{
  background:var(--sf);border:1px solid var(--bd);border-radius:14px;
  padding:12px 10px;text-align:center;backdrop-filter:blur(12px);
  box-shadow:var(--sh);transition:background .3s;
}}
.hv{{font-size:17px;font-weight:800;line-height:1;letter-spacing:-.3px}}
.hl{{font-size:9px;color:var(--mu);text-transform:uppercase;letter-spacing:.6px;margin-top:4px;font-weight:700}}

/* ── LOG CARDS ───────────────────────────────────────────── */
.lcrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;overflow:hidden;
  backdrop-filter:blur(16px);box-shadow:var(--sh);transition:background .3s;
}}
.lrow{{padding:13px 14px;border-bottom:1px solid var(--bd);position:relative}}
.lrow:last-child{{border-bottom:none}}
.lname{{font-size:14px;font-weight:600;line-height:1.3;word-break:break-word;padding-right:70px;color:var(--tx)}}
.lqty{{font-size:11px;color:var(--mu);margin-top:2px;font-weight:500}}
.lmac{{display:flex;gap:10px;font-size:12px;margin-top:6px;flex-wrap:wrap}}
.lmac span{{color:var(--mu)}}
.lmac b{{color:var(--tx2);font-weight:700}}
.lempty{{padding:22px 14px;color:var(--mu);font-size:13px;text-align:center}}
.erow{{padding:13px 14px;border-bottom:1px solid var(--bd);position:relative}}
.erow:last-child{{border-bottom:none}}
.ecnt{{display:flex;justify-content:space-between;align-items:center;padding-right:70px;gap:10px}}
.ename{{font-size:14px;font-weight:600;word-break:break-word;flex:1;color:var(--tx)}}
.edet{{font-size:12px;color:var(--ac);font-weight:700;white-space:nowrap}}

/* ── EDIT / DELETE ───────────────────────────────────────── */
.ract{{position:absolute;top:10px;right:10px;display:flex;gap:4px}}
.ibtn{{
  background:var(--sf2);border:1px solid var(--bd);color:var(--mu);
  width:30px;height:30px;border-radius:8px;cursor:pointer;font-size:13px;
  display:flex;align-items:center;justify-content:center;font-family:inherit;
  transition:all .15s;
}}
.ibtn:active{{transform:scale(.88)}}
.ibtn:hover{{border-color:var(--bd2);color:var(--tx)}}
.ibtn.del:hover{{background:rgba(239,68,68,.12);color:var(--re);border-color:rgba(239,68,68,.4)}}
.eform{{display:grid;gap:8px;margin-top:4px}}
.eform input{{
  background:var(--inp);border:1px solid var(--bd);color:var(--tx);
  padding:8px 10px;border-radius:9px;font-size:13px;font-family:inherit;width:100%;
  transition:border-color .15s;
}}
.eform input:focus{{outline:none;border-color:var(--ac)}}
.emac{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}}
.emc label{{font-size:10px;color:var(--mu);display:block;margin-bottom:3px;font-weight:600}}
.eact{{display:flex;gap:6px;margin-top:4px}}
.sbtn{{
  background:var(--ac);color:#000;border:none;padding:9px 16px;
  border-radius:9px;font-weight:700;font-size:13px;cursor:pointer;font-family:inherit;
  flex:1;min-height:38px;transition:opacity .15s;
}}
[data-theme="light"] .sbtn{{color:#fff}}
.sbtn:hover{{opacity:.88}}
.cbtn{{
  background:var(--sf2);color:var(--mu);border:1px solid var(--bd);
  padding:9px 16px;border-radius:9px;font-size:13px;cursor:pointer;font-family:inherit;
  min-height:38px;transition:all .15s;
}}
.cbtn:hover{{border-color:var(--bd2);color:var(--tx)}}

/* ── CHARTS ──────────────────────────────────────────────── */
.ccrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;padding:16px;
  backdrop-filter:blur(16px);box-shadow:var(--sh);transition:background .3s;
}}
.ctitle{{font-size:11px;font-weight:700;margin-bottom:14px;color:var(--mu);text-transform:uppercase;letter-spacing:.8px}}
.cwrap{{position:relative;height:160px}}
@media(min-width:700px){{.cwrap{{height:180px}}}}
.c2col{{display:grid;grid-template-columns:1fr;gap:10px}}
@media(min-width:700px){{.c2col{{grid-template-columns:1fr 1fr}}}}

/* ── HISTORY TABLE ───────────────────────────────────────── */
.htbl{{width:100%;border-collapse:collapse;font-size:12px}}
.htbl th{{
  color:var(--di);text-transform:uppercase;letter-spacing:.6px;
  font-size:10px;font-weight:700;padding:9px 10px;text-align:left;
  border-bottom:1px solid var(--bd);
}}
.htbl td{{padding:9px 10px;border-bottom:1px solid var(--bd);color:var(--mu)}}
.htbl tr:last-child td{{border-bottom:none}}
.htbl td:first-child{{color:var(--tx2);font-weight:600}}
.td-ok{{color:var(--ac)!important;font-weight:700}}
.td-ov{{color:var(--re)!important;font-weight:700}}

/* ── PROFILE ─────────────────────────────────────────────── */
.infocrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;overflow:hidden;
  backdrop-filter:blur(16px);box-shadow:var(--sh);margin-bottom:10px;transition:background .3s;
}}
.inrow{{
  display:flex;justify-content:space-between;align-items:center;
  padding:12px 14px;border-bottom:1px solid var(--bd);
}}
.inrow:last-child{{border-bottom:none}}
.inlbl{{font-size:13px;color:var(--mu);font-weight:500}}
.inval{{font-size:13px;font-weight:700;color:var(--tx2);text-align:right;max-width:60%}}
.ancrd{{
  background:var(--sf);border:1px solid var(--bd);border-radius:16px;padding:16px;
  backdrop-filter:blur(16px);box-shadow:var(--sh);margin-bottom:10px;transition:background .3s;
}}
[data-theme="dark"] .ancrd{{
  background:linear-gradient(135deg,rgba(59,130,246,.06),transparent 60%),var(--sf);
  border-color:rgba(59,130,246,.15);
}}
.antitle{{font-size:10px;color:var(--mu);font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px}}
.angrid{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}}
@media(min-width:560px){{.angrid{{grid-template-columns:repeat(3,1fr)}}}}
.anitem{{background:var(--sf2);border-radius:12px;padding:11px;border:1px solid var(--bd);transition:background .3s}}
.anval{{font-size:18px;font-weight:800;line-height:1;letter-spacing:-.3px}}
.anlbl{{font-size:10px;color:var(--mu);margin-top:4px;font-weight:600;text-transform:uppercase;letter-spacing:.4px}}
.devrow{{display:flex;align-items:center;gap:12px;padding:13px 14px;border-bottom:1px solid var(--bd)}}
.devrow:last-child{{border-bottom:none}}
.devname{{font-size:13px;font-weight:700;flex:1;color:var(--tx)}}
.devst{{font-size:12px;font-weight:700}}
.devst.on{{color:var(--ac)}}
.devst.off{{color:var(--mu)}}

/* ── MISC ────────────────────────────────────────────────── */
footer{{text-align:center;padding:20px 16px;color:var(--di);font-size:11px;position:relative;z-index:1}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:translateY(0)}}}}
.fade-in{{animation:fadeUp .3s ease}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.spin{{display:inline-block;animation:spin 1s linear infinite}}
</style>
</head>
<body>

<header>
  <div class="logo">&#9889; Arnie</div>
  <div class="hdr-r">
    <span class="u-name" id="user-name"></span>
    <span id="goal-tag" class="g-tag"></span>
    <button class="hbtn" id="theme-btn" onclick="toggleTheme()" title="Toggle theme">&#9790;</button>
    <button class="hbtn" onclick="refreshCurrent()" title="Refresh">&#8635;</button>
  </div>
</header>

<div class="tabs" id="tabs-bar" role="tablist">
  <div class="tab-pill" id="tab-pill"></div>
  <button class="tab-btn active" id="tab-day"     role="tab" onclick="switchTab('day')">Day</button>
  <button class="tab-btn"        id="tab-week"    role="tab" onclick="switchTab('week')">Week</button>
  <button class="tab-btn"        id="tab-profile" role="tab" onclick="switchTab('profile')">Profile</button>
</div>

<main>
  <div id="app-load">Loading your data&hellip;</div>

  <!-- DAY TAB -->
  <div class="tab-panel active" id="panel-day">
    <div class="dnav">
      <button class="darr" id="date-prev" onclick="navDate(-1)" aria-label="Previous day">&#8249;</button>
      <div class="dscroll" id="date-chips"></div>
      <button class="darr" id="date-next" onclick="navDate(1)"  aria-label="Next day">&#8250;</button>
    </div>

    <div class="stitle">&#10024; Coach insights <span class="ai-pill">AI</span></div>
    <div class="icrd fade-in" id="insights-card">
      <div class="iload"><span class="spin">&#9675;</span> Analyzing&hellip;</div>
    </div>

    <div class="stitle" id="day-label">Today</div>
    <div class="cards">
      <div class="card">
        <div class="clbl">Calories</div>
        <div class="cval" id="cal-val">&mdash;</div>
        <div class="csub" id="cal-sub"></div>
        <div class="ptrack"><div class="pfill" id="cal-bar" style="background:var(--ac);width:0%"></div></div>
      </div>
      <div class="card">
        <div class="clbl">Protein</div>
        <div class="cval" id="pro-val">&mdash;</div>
        <div class="csub" id="pro-sub"></div>
        <div class="ptrack"><div class="pfill" id="pro-bar" style="background:var(--bl);width:0%"></div></div>
      </div>
      <div class="card">
        <div class="clbl">Carbs</div>
        <div class="cval" id="carb-val">&mdash;</div>
        <div class="csub" style="color:var(--or)">grams</div>
      </div>
      <div class="card">
        <div class="clbl">Fats</div>
        <div class="cval" id="fat-val">&mdash;</div>
        <div class="csub" style="color:var(--pu)">grams</div>
      </div>
    </div>

    <div class="sbrow">
      <span id="wo-badge" class="badge bg-n"></span>
      <span id="ca-badge" class="badge bg-n"></span>
      <span id="wt-badge" class="badge bg-b" style="display:none"></span>
    </div>

    <div class="stitle">Food log</div>
    <div class="lcrd" id="food-log"><div class="lempty">Loading&hellip;</div></div>

    <div class="stitle">Workouts</div>
    <div class="lcrd" id="ex-log"><div class="lempty">Loading&hellip;</div></div>

    <div id="health-section" style="display:none">
      <div class="stitle">Wearable</div>
      <div class="hgrid" id="health-grid"></div>
    </div>
  </div>

  <!-- WEEK TAB -->
  <div class="tab-panel" id="panel-week">
    <div class="c2col">
      <div class="ccrd">
        <div class="ctitle">Calories &mdash; 30 days</div>
        <div class="cwrap"><canvas id="calChart"></canvas></div>
      </div>
      <div class="ccrd">
        <div class="ctitle">Protein &mdash; 30 days</div>
        <div class="cwrap"><canvas id="proChart"></canvas></div>
      </div>
      <div class="ccrd">
        <div class="ctitle">Weight trend (lbs)</div>
        <div class="cwrap"><canvas id="weightChart"></canvas></div>
      </div>
    </div>
    <div class="stitle">Last 14 days</div>
    <div class="infocrd" id="hist-table-wrap"><div class="lempty">Loading&hellip;</div></div>
  </div>

  <!-- PROFILE TAB -->
  <div class="tab-panel" id="panel-profile">
    <div class="stitle">Your info</div>
    <div class="infocrd" id="profile-info"></div>
    <div class="stitle">Targets</div>
    <div class="infocrd" id="profile-targets"></div>
    <div class="stitle">Science</div>
    <div class="ancrd">
      <div class="antitle">Performance analytics</div>
      <div class="angrid" id="analytics-grid"></div>
    </div>
    <div class="stitle">Connected devices</div>
    <div class="infocrd" id="devices-card"></div>
  </div>

</main>
<footer>Arnie &middot; auto-refresh 5 min</footer>

<script>
// ── Constants ─────────────────────────────────────────────────────────────
const TOKEN        = '{token}';
const STATS_BASE   = '/api/stats/'    + TOKEN;
const INSIGHTS_API = '/api/insights/' + TOKEN;

// ── State ─────────────────────────────────────────────────────────────────
let _baseData=null, _dayCache={{}}, _viewingDate=null, _todayStr=null;
let _availDates=[], _activeTab='day', calChart, proChart, weightChart;

// ── Theme ─────────────────────────────────────────────────────────────────
(function(){{
  var t=localStorage.getItem('arnie-theme')||
    (window.matchMedia('(prefers-color-scheme:light)').matches?'light':'dark');
  document.documentElement.setAttribute('data-theme',t);
  var btn=document.getElementById('theme-btn');
  if(btn) btn.textContent=t==='dark'?'☾':'☀';
}})();

function toggleTheme(){{
  var html=document.documentElement;
  var next=html.getAttribute('data-theme')==='dark'?'light':'dark';
  html.setAttribute('data-theme',next);
  document.getElementById('theme-btn').textContent=next==='dark'?'☾':'☀';
  localStorage.setItem('arnie-theme',next);
  if(_baseData && _activeTab==='week') setTimeout(()=>renderWeekTab(_baseData),50);
}}

// ── Tab indicator pill ────────────────────────────────────────────────────
function updatePill(name){{
  var btn=document.getElementById('tab-'+name);
  var bar=document.getElementById('tabs-bar');
  var pill=document.getElementById('tab-pill');
  if(!btn||!bar||!pill) return;
  var br=bar.getBoundingClientRect(), br2=btn.getBoundingClientRect();
  pill.style.left=(br2.left-br.left)+'px';
  pill.style.width=br2.width+'px';
}}

// ── Utils ─────────────────────────────────────────────────────────────────
function esc(s){{
  return String(s??'').replace(/[&<>"']/g,c=>(
    {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
}}
function escA(s){{return String(s??'').replace(/"/g,'&quot;')}}
function pct(v,t){{return(!t||v==null)?0:Math.min(100,Math.round(v/t*100))}}
function fmt(n){{return n!=null?Number(n).toLocaleString():'—'}}
function fmtDate(d){{
  var[,m,day]=d.split('-');
  return['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+m-1]+' '+ +day;
}}
function countUp(el,target,dur){{
  if(target==null||isNaN(target)){{el.textContent='—';return}}
  dur=dur||700;var t0=performance.now();
  (function tick(now){{
    var p=Math.min((now-t0)/dur,1),e=1-Math.pow(1-p,3);
    el.textContent=Math.round(target*e);
    if(p<1) requestAnimationFrame(tick);
  }})(t0);
}}

// ── API ───────────────────────────────────────────────────────────────────
async function fetchStats(d){{
  var r=await fetch(d?STATS_BASE+'?date='+d:STATS_BASE);
  if(!r.ok) throw new Error('HTTP '+r.status);
  return r.json();
}}
async function fetchInsights(){{
  try{{
    var r=await fetch(INSIGHTS_API);
    if(!r.ok) return[];
    return(await r.json()).insights||[];
  }}catch(e){{return[]}}
}}

// ── Tab switching ─────────────────────────────────────────────────────────
function switchTab(name){{
  _activeTab=name;
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  document.getElementById('panel-'+name).classList.add('active');
  updatePill(name);
  if(name==='week' && _baseData) renderWeekTab(_baseData);
  if(name==='profile' && _baseData) renderProfileTab(_baseData);
}}

// ── Boot ──────────────────────────────────────────────────────────────────
async function init(){{
  updatePill('day');
  try{{
    var data=await fetchStats(null);
    _baseData=data;
    _todayStr=data.viewing_date||data.day?.date||new Date().toISOString().slice(0,10);
    _viewingDate=_todayStr;
    var hd=(data.history||[]).map(h=>h.date);
    _availDates=[...new Set([...hd,_todayStr])].sort();
    _dayCache[_todayStr]=data;
    document.getElementById('user-name').textContent=data.profile?.name||'';
    document.getElementById('goal-tag').textContent=data.profile?.primary_goal||'';
    document.getElementById('app-load').style.display='none';
    renderDateNav();
    renderDayTab(data);
    fetchInsights().then(renderInsights);
  }}catch(e){{
    document.getElementById('app-load').textContent='Failed to load — tap ↻ to retry.';
  }}
}}

async function refreshCurrent(){{
  delete _dayCache[_viewingDate];
  if(_viewingDate===_todayStr){{
    try{{
      var data=await fetchStats(null);
      _baseData=data;_dayCache[_todayStr]=data;
      renderDayTab(data);
      if(_activeTab==='week') renderWeekTab(data);
      if(_activeTab==='profile') renderProfileTab(data);
    }}catch(e){{}}
  }}else{{
    await loadDayData(_viewingDate);
  }}
}}

// ── Date nav ──────────────────────────────────────────────────────────────
function renderDateNav(){{
  var el=document.getElementById('date-chips');
  el.innerHTML='';
  var ci=_availDates.indexOf(_viewingDate);
  var s=Math.max(0,ci-2),e=Math.min(_availDates.length-1,ci+2);
  while(e-s<4&&s>0) s--;
  while(e-s<4&&e<_availDates.length-1) e++;
  for(var i=s;i<=e;i++){{
    var d=_availDates[i],chip=document.createElement('button');
    chip.className='dchip'+(d===_viewingDate?' active':'');
    chip.appendChild(document.createTextNode(fmtDate(d)));
    if(d===_todayStr){{
      var tag=document.createElement('span');
      tag.className='today-tag';tag.textContent='Today';chip.appendChild(tag);
    }}
    (function(dd){{chip.onclick=()=>selectDate(dd)}})(d);
    el.appendChild(chip);
  }}
  document.getElementById('date-prev').disabled=ci<=0;
  document.getElementById('date-next').disabled=ci>=_availDates.length-1;
}}

async function navDate(dir){{
  var ci=_availDates.indexOf(_viewingDate),ni=ci+dir;
  if(ni<0||ni>=_availDates.length) return;
  await selectDate(_availDates[ni]);
}}

async function selectDate(d){{
  _viewingDate=d;renderDateNav();
  if(_dayCache[d]) renderDayTab(_dayCache[d]);
  else await loadDayData(d);
}}

async function loadDayData(d){{
  document.getElementById('food-log').innerHTML='<div class="lempty">Loading…</div>';
  document.getElementById('ex-log').innerHTML='<div class="lempty">Loading…</div>';
  try{{
    var data=await fetchStats(d);
    _dayCache[d]=data;renderDayTab(data);
  }}catch(e){{
    document.getElementById('food-log').innerHTML='<div class="lempty">Failed to load.</div>';
  }}
}}

// ── Day tab ───────────────────────────────────────────────────────────────
function renderDayTab(d){{
  var isToday=_viewingDate===_todayStr;
  document.getElementById('day-label').textContent=isToday?'Today':fmtDate(_viewingDate);
  var day=d.day||{{}},tgt=d.targets||{{}};
  var cp=pct(day.calories,tgt.calories),pp=pct(day.protein,tgt.protein);

  var calEl=document.getElementById('cal-val');
  if(day.calories!=null) countUp(calEl,day.calories);
  else calEl.textContent='—';
  document.getElementById('cal-sub').textContent=tgt.calories?'/ '+tgt.calories+' ('+cp+'%)':'kcal';
  document.getElementById('cal-bar').style.width=cp+'%';

  var proEl=document.getElementById('pro-val');
  proEl.textContent=day.protein!=null?day.protein+'g':'—';
  document.getElementById('pro-sub').textContent=tgt.protein?'/ '+tgt.protein+'g ('+pp+'%)':'grams';
  document.getElementById('pro-bar').style.width=pp+'%';
  document.getElementById('carb-val').textContent=day.carbs!=null?day.carbs+'g':'—';
  document.getElementById('fat-val').textContent=day.fats!=null?day.fats+'g':'—';

  var wb=document.getElementById('wo-badge');
  wb.className='badge '+(day.workout_completed?'bg-g':'bg-n');
  wb.textContent=day.workout_completed?'💪 Workout done':'⬜ No workout';
  var cb=document.getElementById('ca-badge');
  cb.className='badge '+(day.cardio_completed?'bg-g':'bg-n');
  cb.textContent=day.cardio_completed?'🏃 Cardio done':'⬜ No cardio';
  var wb2=document.getElementById('wt-badge');
  if(day.water_ml>0){{
    wb2.style.display='inline-flex';
    wb2.textContent='💧 '+(day.water_ml>=1000?(day.water_ml/1000).toFixed(1)+'L':day.water_ml+'ml');
  }}else wb2.style.display='none';

  var fe=day.food_entries||[];
  document.getElementById('food-log').innerHTML=fe.length?fe.map(renderFoodRow).join('')
    :'<div class="lempty">Nothing logged'+(isToday?' yet':'')+'</div>';
  var ee=day.exercise_entries||[];
  document.getElementById('ex-log').innerHTML=ee.length?ee.map(renderExerciseRow).join('')
    :'<div class="lempty">No exercises logged'+(isToday?' yet':'')+'</div>';

  var hl=d.health||[],hd=hl.find(h=>h.date===_viewingDate)||null;
  var hs=document.getElementById('health-section');
  if(hd){{hs.style.display='block';renderHealthGrid(hd)}}
  else hs.style.display='none';
}}

function renderHealthGrid(h){{
  var tiles=[];
  if(h.recovery_score!=null){{
    var rec=h.recovery_score;
    var col=rec>=67?'var(--ac)':rec>=34?'var(--ye)':'var(--re)';
    var r=20,circ=2*Math.PI*r,dash=(rec/100)*circ,gap=circ-dash;
    tiles.push(
      '<div class="htile">'+
      '<svg viewBox="0 0 56 56" style="width:52px;height:52px;margin:0 auto;display:block">'+
      '<circle cx="28" cy="28" r="'+r+'" fill="none" stroke="var(--sf2)" stroke-width="4"/>'+
      '<circle cx="28" cy="28" r="'+r+'" fill="none" stroke="'+col+'" stroke-width="4"'+
        ' stroke-dasharray="'+dash.toFixed(1)+' '+gap.toFixed(1)+'"'+
        ' stroke-linecap="round" transform="rotate(-90 28 28)"/>'+
      '<text x="28" y="33" text-anchor="middle" font-size="11" font-weight="800"'+
        ' font-family="Inter,sans-serif" fill="'+col+'">'+rec+'%</text>'+
      '</svg><div class="hl">Recovery</div></div>'
    );
  }}
  function tile(v,l,c){{
    return '<div class="htile"><div class="hv" style="color:'+c+'">'+esc(v)+'</div><div class="hl">'+esc(l)+'</div></div>';
  }}
  if(h.hrv!=null)         tiles.push(tile(h.hrv+'ms',            'HRV',     'var(--pu)'));
  if(h.resting_hr!=null)  tiles.push(tile(h.resting_hr+'bpm',    'Rest HR', 'var(--bl)'));
  if(h.sleep_hours!=null) tiles.push(tile((+h.sleep_hours).toFixed(1)+'h','Sleep','var(--ac)'));
  if(h.strain!=null)      tiles.push(tile((+h.strain).toFixed(1),'Strain',  'var(--or)'));
  if(h.steps!=null)       tiles.push(tile((+h.steps).toLocaleString(),'Steps','var(--ye)'));
  document.getElementById('health-grid').innerHTML=tiles.join('');
}}

// ── Week tab ──────────────────────────────────────────────────────────────
function renderWeekTab(d){{
  var dk=document.documentElement.getAttribute('data-theme')!=='light';
  var hist=(d.history||[]).slice(-30),tgt=d.targets||{{}};
  var labels=hist.map(h=>h.date.slice(5));
  var calD=hist.map(h=>h.calories??0),proD=hist.map(h=>h.protein??0);
  var tick=dk?'#4a5568':'#94a3b8',grid=dk?'rgba(255,255,255,.05)':'#e2e8f0';
  var opts={{
    responsive:true,maintainAspectRatio:false,
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{grid:{{display:false}},ticks:{{color:tick,font:{{size:9}},maxRotation:0,autoSkip:true,maxTicksLimit:8}}}},
      y:{{grid:{{color:grid}},ticks:{{color:tick,font:{{size:10}}}},beginAtZero:true}}
    }}
  }};

  if(calChart) calChart.destroy();
  calChart=new Chart(document.getElementById('calChart'),{{
    type:'bar',
    data:{{
      labels,
      datasets:[
        {{
          data:calD,
          backgroundColor:calD.map(v=>tgt.calories&&v>tgt.calories
            ?(dk?'rgba(239,68,68,.7)':'rgba(220,38,38,.7)')
            :(dk?'rgba(0,230,118,.65)':'rgba(5,150,105,.65)')),
          borderRadius:4,
        }},
        ...(tgt.calories?[{{
          type:'line',data:Array(labels.length).fill(tgt.calories),
          borderColor:dk?'rgba(255,255,255,.25)':'rgba(0,0,0,.2)',
          borderDash:[4,4],borderWidth:1.5,pointRadius:0,fill:false,
        }}]:[])
      ]
    }},
    options:opts,
  }});

  if(proChart) proChart.destroy();
  proChart=new Chart(document.getElementById('proChart'),{{
    type:'bar',
    data:{{
      labels,
      datasets:[
        {{
          data:proD,
          backgroundColor:proD.map(v=>tgt.protein&&v>=tgt.protein
            ?(dk?'rgba(59,130,246,.85)':'rgba(37,99,235,.85)')
            :(dk?'rgba(59,130,246,.3)':'rgba(37,99,235,.3)')),
          borderRadius:4,
        }},
        ...(tgt.protein?[{{
          type:'line',data:Array(labels.length).fill(tgt.protein),
          borderColor:dk?'rgba(255,255,255,.25)':'rgba(0,0,0,.2)',
          borderDash:[4,4],borderWidth:1.5,pointRadius:0,fill:false,
        }}]:[])
      ]
    }},
    options:opts,
  }});

  if(weightChart) weightChart.destroy();
  var wD=(d.weights||[]).slice(-30);
  weightChart=new Chart(document.getElementById('weightChart'),{{
    type:'line',
    data:{{
      labels:wD.map(w=>w.date.slice(5)),
      datasets:[
        {{
          data:wD.map(w=>w.lbs),
          borderColor:dk?'#f97316':'#ea580c',
          backgroundColor:dk?'rgba(249,115,22,.08)':'rgba(234,88,12,.06)',
          borderWidth:2.5,pointRadius:3,pointBackgroundColor:dk?'#f97316':'#ea580c',
          fill:true,tension:0.35,
        }},
        ...(d.profile?.goal_weight_lbs&&wD.length?[{{
          type:'line',data:Array(wD.length).fill(d.profile.goal_weight_lbs),
          borderColor:dk?'rgba(0,230,118,.35)':'rgba(5,150,105,.4)',
          borderDash:[4,4],borderWidth:1.5,pointRadius:0,fill:false,
        }}]:[])
      ]
    }},
    options:{{...opts,scales:{{...opts.scales,y:{{...opts.scales.y,beginAtZero:false}}}}}},
  }});

  var rows=(hist.slice(-14)||[]).reverse();
  document.getElementById('hist-table-wrap').innerHTML=rows.length===0
    ?'<div class="lempty">No history yet</div>'
    :'<table class="htbl"><thead><tr><th>Date</th><th>Calories</th><th>Protein</th><th>Workout</th></tr></thead><tbody>'+
      rows.map(h=>{{
        var cc=tgt.calories
          ?(h.calories>=tgt.calories*.9&&h.calories<=tgt.calories*1.1?'td-ok':h.calories>tgt.calories*1.1?'td-ov':'')
          :'';
        var pc=tgt.protein?(h.protein>=tgt.protein*.9?'td-ok':''):'';
        return '<tr><td>'+esc(h.date.slice(5))+'</td>'+
          '<td class="'+cc+'">'+(h.calories??'—')+'</td>'+
          '<td class="'+pc+'">'+(h.protein!=null?h.protein+'g':'—')+'</td>'+
          '<td>'+(h.workout?'✓':'✗')+'</td></tr>';
      }}).join('')+'</tbody></table>';
}}

// ── Profile tab ───────────────────────────────────────────────────────────
function renderProfileTab(d){{
  var p=d.profile||{{}},tgt=d.targets||{{}},an=p.analytics||{{}};
  var rows=[
    ['Name',p.name],['Age',p.age?p.age+' yrs':null],['Sex',p.sex],
    ['Height',p.height_ft||(p.height_cm?p.height_cm+' cm':null)],
    ['Current weight',p.current_weight_lbs?p.current_weight_lbs+' lbs':null],
    ['Goal weight',p.goal_weight_lbs?p.goal_weight_lbs+' lbs':null],
    ['Goal',p.primary_goal],['Experience',p.training_experience],
    ['Diet',p.dietary_preferences&&p.dietary_preferences!=='none'?p.dietary_preferences:null],
    ['Injuries',p.injuries&&p.injuries!=='none'?p.injuries:null],
    ['Timezone',p.timezone],['Coaching style',p.coaching_style],
  ].filter(([,v])=>v!=null&&v!=='');
  document.getElementById('profile-info').innerHTML=rows.map(([l,v])=>
    '<div class="inrow"><span class="inlbl">'+esc(l)+'</span><span class="inval">'+esc(String(v))+'</span></div>'
  ).join('')||'<div class="lempty">No profile data</div>';

  document.getElementById('profile-targets').innerHTML=
    '<div class="inrow"><span class="inlbl">Calorie target</span>'+
    '<span class="inval" style="color:var(--ac)">'+(tgt.calories?tgt.calories.toLocaleString()+' kcal/day':'—')+'</span></div>'+
    '<div class="inrow"><span class="inlbl">Protein target</span>'+
    '<span class="inval" style="color:var(--bl)">'+(tgt.protein?tgt.protein+'g/day':'—')+'</span></div>';

  var items=[
    ['TDEE',an.tdee_estimate!=null?an.tdee_estimate.toLocaleString()+' kcal':null,'var(--ac)'],
    ['BMR',an.bmr!=null?an.bmr.toLocaleString()+' kcal':null,'var(--bl)'],
    ['Daily diff',an.daily_vs_tdee!=null?(an.daily_vs_tdee>0?'+':'')+an.daily_vs_tdee+' kcal':null,
      an.pace_label==='surplus'?'var(--or)':'var(--ac)'],
    ['Target pace',an.pace_lbs_per_week!=null?an.pace_lbs_per_week+' lbs/wk':null,'var(--ac)'],
    ['Actual pace',an.actual_lbs_per_week!=null?an.actual_lbs_per_week+' lbs/wk':null,'var(--mu)'],
    ['Weeks to goal',an.weeks_to_goal!=null?an.weeks_to_goal+' wks':null,'var(--ye)'],
    ['Rec. protein',(an.rec_protein_min&&an.rec_protein_max)?an.rec_protein_min+'–'+an.rec_protein_max+'g':null,'var(--pu)'],
  ].filter(([,v])=>v!=null);
  document.getElementById('analytics-grid').innerHTML=items.map(([l,v,c])=>
    '<div class="anitem"><div class="anval" style="color:'+c+'">'+esc(String(v))+'</div>'+
    '<div class="anlbl">'+esc(l)+'</div></div>'
  ).join('')||'<div style="color:var(--mu);font-size:13px;grid-column:1/-1">No analytics data yet</div>';

  document.getElementById('devices-card').innerHTML=
    '<div class="devrow"><span style="font-size:20px">&#8987;</span>'+
    '<span class="devname">Whoop</span>'+
    '<span class="devst '+(p.whoop_connected?'on':'off')+'">'+
    (p.whoop_connected?'✓ Connected':'⚠ Not connected')+'</span></div>'+
    '<div class="devrow"><span style="font-size:20px">&#63743;</span>'+
    '<span class="devname">Apple Health</span>'+
    '<span class="devst '+(p.apple_health_connected?'on':'off')+'">'+
    (p.apple_health_connected?'✓ Syncing':'⚠ Not connected')+'</span></div>';
}}

// ── Insights ──────────────────────────────────────────────────────────────
function renderInsights(ins){{
  var el=document.getElementById('insights-card');
  if(!ins||!ins.length){{
    el.innerHTML='<div class="iempty">Not enough data yet — keep logging and check back tomorrow.</div>';
    return;
  }}
  el.innerHTML=ins.map(txt=>
    '<div class="irow fade-in"><div class="iico">&#9656;</div><div class="itxt">'+esc(txt)+'</div></div>'
  ).join('');
}}

// ── Food rows ─────────────────────────────────────────────────────────────
function renderFoodRow(f){{
  var est=f.estimated?' <span style="color:var(--di);font-size:10px;font-weight:500">~est</span>':'';
  return '<div class="lrow" id="food-row-'+f.id+'">'+
    '<div class="lname">'+esc(f.name)+est+'</div>'+
    '<div class="lqty">'+esc(f.quantity||'')+'</div>'+
    '<div class="lmac">'+
    '<span><b>'+(f.calories??0)+'</b> cal</span>'+
    '<span><b>'+(f.protein??0)+'g</b> P</span>'+
    '<span><b>'+(f.carbs??0)+'g</b> C</span>'+
    '<span><b>'+(f.fats??0)+'g</b> F</span></div>'+
    '<div class="ract">'+
    '<button class="ibtn" onclick="editFood('+f.id+')" aria-label="Edit">&#9998;</button>'+
    '<button class="ibtn del" onclick="deleteFood('+f.id+')" aria-label="Delete">&#215;</button>'+
    '</div></div>';
}}

function renderExerciseRow(e){{
  var det='';
  if(e.sets&&e.reps) det=e.sets+'×'+e.reps+(e.weight?' @ '+e.weight+'lb':'');
  else if(e.duration_minutes) det=e.duration_minutes+' min';
  return '<div class="erow" id="ex-row-'+e.id+'">'+
    '<div class="ecnt"><div class="ename">'+esc(e.name)+'</div>'+
    '<div class="edet">'+esc(det)+'</div></div>'+
    '<div class="ract">'+
    '<button class="ibtn" onclick="editExercise('+e.id+')" aria-label="Edit">&#9998;</button>'+
    '<button class="ibtn del" onclick="deleteExercise('+e.id+')" aria-label="Delete">&#215;</button>'+
    '</div></div>';
}}

// ── Inline edit: food ─────────────────────────────────────────────────────
function findFood(id){{
  return(_dayCache[_viewingDate]?.day?.food_entries||[]).find(f=>f.id===id);
}}
function findEx(id){{
  return(_dayCache[_viewingDate]?.day?.exercise_entries||[]).find(e=>e.id===id);
}}

function editFood(id){{
  var f=findFood(id);if(!f)return;
  document.getElementById('food-row-'+id).innerHTML=
    '<div class="eform">'+
    '<input type="text" id="ef-n-'+id+'" value="'+escA(f.name)+'" placeholder="Food name">'+
    '<input type="text" id="ef-q-'+id+'" value="'+escA(f.quantity||'')+'" placeholder="Quantity">'+
    '<div class="emac">'+
    '<div class="emc"><label>Cal</label><input type="number" id="ef-c-'+id+'" value="'+(f.calories??'')+'" inputmode="numeric"></div>'+
    '<div class="emc"><label>P (g)</label><input type="number" id="ef-p-'+id+'" value="'+(f.protein??'')+'" inputmode="numeric"></div>'+
    '<div class="emc"><label>C (g)</label><input type="number" id="ef-cb-'+id+'" value="'+(f.carbs??'')+'" inputmode="numeric"></div>'+
    '<div class="emc"><label>F (g)</label><input type="number" id="ef-f-'+id+'" value="'+(f.fats??'')+'" inputmode="numeric"></div>'+
    '</div>'+
    '<div class="eact">'+
    '<button class="sbtn" onclick="saveFood('+id+')">Save</button>'+
    '<button class="cbtn" onclick="cancelEdit()">Cancel</button>'+
    '</div></div>';
}}

async function saveFood(id){{
  var body={{
    food_name:document.getElementById('ef-n-'+id).value,
    quantity:document.getElementById('ef-q-'+id).value,
    calories:parseFloat(document.getElementById('ef-c-'+id).value)||0,
    protein:parseFloat(document.getElementById('ef-p-'+id).value)||0,
    carbs:parseFloat(document.getElementById('ef-cb-'+id).value)||0,
    fats:parseFloat(document.getElementById('ef-f-'+id).value)||0,
  }};
  var btn=document.querySelector('#food-row-'+id+' .sbtn');
  if(btn){{btn.disabled=true;btn.textContent='…'}}
  var r=await fetch('/api/food/'+id+'?token='+TOKEN,{{
    method:'PATCH',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body),
  }});
  if(!r.ok){{
    alert('Save failed — please try again.');
    if(btn){{btn.disabled=false;btn.textContent='Save'}}
    return;
  }}
  delete _dayCache[_viewingDate];await loadDayData(_viewingDate);
}}

async function deleteFood(id){{
  var f=findFood(id);
  if(!confirm('Delete "'+(f?f.name:'this item')+'"?')) return;
  var r=await fetch('/api/food/'+id+'?token='+TOKEN,{{method:'DELETE'}});
  if(!r.ok){{alert('Delete failed.');return}}
  delete _dayCache[_viewingDate];await loadDayData(_viewingDate);
}}

// ── Inline edit: exercise ─────────────────────────────────────────────────
function editExercise(id){{
  var e=findEx(id);if(!e)return;
  document.getElementById('ex-row-'+id).innerHTML=
    '<div class="eform">'+
    '<input type="text" id="ee-n-'+id+'" value="'+escA(e.name)+'" placeholder="Exercise name">'+
    '<div class="emac" style="grid-template-columns:repeat(3,1fr)">'+
    '<div class="emc"><label>Sets</label><input type="number" id="ee-s-'+id+'" value="'+(e.sets??'')+'" inputmode="numeric"></div>'+
    '<div class="emc"><label>Reps</label><input type="text" id="ee-r-'+id+'" value="'+escA(e.reps??'')+'"></div>'+
    '<div class="emc"><label>Weight (lb)</label><input type="number" id="ee-w-'+id+'" value="'+(e.weight??'')+'" inputmode="decimal"></div>'+
    '</div>'+
    '<div class="eact">'+
    '<button class="sbtn" onclick="saveExercise('+id+')">Save</button>'+
    '<button class="cbtn" onclick="cancelEdit()">Cancel</button>'+
    '</div></div>';
}}

async function saveExercise(id){{
  var body={{
    exercise_name:document.getElementById('ee-n-'+id).value||null,
    sets:parseInt(document.getElementById('ee-s-'+id).value)||null,
    reps:document.getElementById('ee-r-'+id).value||null,
    weight:parseFloat(document.getElementById('ee-w-'+id).value)||null,
  }};
  Object.keys(body).forEach(k=>body[k]==null&&delete body[k]);
  var btn=document.querySelector('#ex-row-'+id+' .sbtn');
  if(btn){{btn.disabled=true;btn.textContent='…'}}
  var r=await fetch('/api/exercise/'+id+'?token='+TOKEN,{{
    method:'PATCH',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body),
  }});
  if(!r.ok){{
    alert('Save failed.');
    if(btn){{btn.disabled=false;btn.textContent='Save'}}
    return;
  }}
  delete _dayCache[_viewingDate];await loadDayData(_viewingDate);
}}

async function deleteExercise(id){{
  var e=findEx(id);
  if(!confirm('Delete "'+(e?e.name:'this exercise')+'"?')) return;
  var r=await fetch('/api/exercise/'+id+'?token='+TOKEN,{{method:'DELETE'}});
  if(!r.ok){{alert('Delete failed.');return}}
  delete _dayCache[_viewingDate];await loadDayData(_viewingDate);
}}

function cancelEdit(){{
  var d=_dayCache[_viewingDate];
  if(d) renderDayTab(d);
}}

// ── Start ─────────────────────────────────────────────────────────────────
init();
setInterval(()=>{{
  delete _dayCache[_todayStr];
  if(_viewingDate===_todayStr) refreshCurrent();
}}, 5*60*1000);
</script>
</body>
</html>"""



# ── Apple Health webhook ────────────────────────────────────────────────────────

class AppleHealthPayload(BaseModel):
    date: Optional[str] = None
    steps: Optional[int] = None
    active_calories: Optional[float] = None
    resting_calories: Optional[float] = None
    sleep_hours: Optional[float] = None
    sleep_deep_hours: Optional[float] = None
    sleep_rem_hours: Optional[float] = None
    resting_hr: Optional[float] = None
    avg_hr: Optional[float] = None
    hrv: Optional[float] = None
    stand_hours: Optional[int] = None
    exercise_minutes: Optional[int] = None


@app.post("/health/apple")
async def receive_apple_health(
    payload: AppleHealthPayload,
    token: str = Query(...),
):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        from datetime import date as _date
        snap_date = _date.today()
        if payload.date:
            try:
                snap_date = _date.fromisoformat(payload.date)
            except ValueError:
                raise HTTPException(status_code=400, detail="Use YYYY-MM-DD")

        data = payload.model_dump(exclude={"date"}, exclude_none=True)
        data.setdefault("source", "apple_health")
        await upsert_health_snapshot(db, user.id, snap_date, **data)

    return {"status": "ok", "date": str(snap_date)}


# ── Apple Health setup guide ───────────────────────────────────────────────────

@app.get("/health/apple/guide", response_class=HTMLResponse)
async def apple_health_guide(token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            return HTMLResponse("<h2>Invalid or expired link.</h2>", status_code=401)

    base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000").rstrip("/")
    endpoint = f"{base_url}/health/apple?token={token}"
    return HTMLResponse(_apple_guide_html(endpoint))


def _apple_guide_html(endpoint: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Apple Health Setup — Arnie</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Inter',-apple-system,sans-serif;background:#070c18;color:#eef2ff;
  min-height:100vh;padding:0 0 48px;-webkit-font-smoothing:antialiased}}
header{{background:rgba(7,12,24,.95);border-bottom:1px solid rgba(255,255,255,.08);
  padding:14px 20px;position:sticky;top:0;z-index:10;backdrop-filter:blur(16px)}}
.logo{{font-size:17px;font-weight:800;background:linear-gradient(130deg,#00e676,#3b82f6);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
main{{max-width:640px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;font-weight:800;margin-bottom:6px;letter-spacing:-.4px}}
.sub{{font-size:14px;color:#6b7a99;margin-bottom:28px;line-height:1.5}}
.section{{margin-bottom:32px}}
.section-lbl{{font-size:10px;font-weight:700;color:#3d4a66;text-transform:uppercase;
  letter-spacing:1.4px;margin-bottom:12px}}
.url-box{{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);
  border-radius:12px;padding:14px;display:flex;align-items:center;gap:10px;cursor:pointer}}
.url-text{{font-family:monospace;font-size:12px;color:#00e676;word-break:break-all;flex:1;line-height:1.5}}
.copy-btn{{background:rgba(0,230,118,.15);border:1px solid rgba(0,230,118,.3);color:#00e676;
  padding:8px 14px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;
  white-space:nowrap;font-family:inherit;transition:all .2s;flex-shrink:0}}
.copy-btn:active{{transform:scale(.94)}}
.steps{{display:grid;gap:12px}}
.step{{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);
  border-radius:14px;padding:16px;display:grid;grid-template-columns:32px 1fr;gap:12px;align-items:start}}
.step-num{{width:32px;height:32px;background:rgba(0,230,118,.12);border:1px solid rgba(0,230,118,.25);
  color:#00e676;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-size:13px;font-weight:800;flex-shrink:0}}
.step-title{{font-size:14px;font-weight:700;color:#eef2ff;margin-bottom:4px}}
.step-body{{font-size:13px;color:#8899aa;line-height:1.55}}
.step-body b{{color:#c8d0e8;font-weight:600}}
.step-body code{{background:rgba(255,255,255,.08);padding:1px 6px;border-radius:5px;
  font-size:11px;color:#00e676;font-family:monospace}}
.json-block{{background:rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.08);
  border-radius:10px;padding:14px;font-family:monospace;font-size:12px;
  color:#8899aa;line-height:1.7;overflow-x:auto;margin-top:10px}}
.json-block .k{{color:#c8d0e8}}.json-block .v{{color:#00e676}}.json-block .c{{color:#3d4a66}}
.metrics-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
@media(min-width:480px){{.metrics-grid{{grid-template-columns:repeat(3,1fr)}}}}
.metric{{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);
  border-radius:10px;padding:10px}}
.metric-key{{font-family:monospace;font-size:11px;color:#00e676;margin-bottom:3px}}
.metric-src{{font-size:11px;color:#6b7a99}}
.tip{{background:rgba(59,130,246,.08);border:1px solid rgba(59,130,246,.2);
  border-radius:12px;padding:14px;font-size:13px;color:#8899aa;line-height:1.55}}
.tip b{{color:#3b82f6}}
footer{{text-align:center;padding:32px 16px 0;color:#3d4a66;font-size:11px}}
</style>
</head>
<body>
<header><div class="logo">&#9889; Arnie</div></header>
<main>

<h1>Apple Health Setup</h1>
<p class="sub">Sync your iPhone's health data to Arnie automatically each morning using an iOS Shortcut.</p>

<div class="section">
  <div class="section-lbl">Your personal endpoint</div>
  <div class="url-box" onclick="copyUrl()">
    <div class="url-text" id="url-text">{endpoint}</div>
    <button class="copy-btn" id="copy-btn">Copy</button>
  </div>
</div>

<div class="section">
  <div class="section-lbl">Create the iOS Shortcut</div>
  <div class="steps">

    <div class="step">
      <div class="step-num">1</div>
      <div>
        <div class="step-title">Open Shortcuts → New Shortcut</div>
        <div class="step-body">
          On your iPhone open the <b>Shortcuts</b> app and tap <b>+</b> in the top right.
          Tap the title to rename it <b>"Arnie Health Sync"</b>.
        </div>
      </div>
    </div>

    <div class="step">
      <div class="step-num">2</div>
      <div>
        <div class="step-title">Add health data actions</div>
        <div class="step-body">
          Tap <b>Add Action</b>, search <b>"Find Health Samples"</b> and add one for each metric you want to sync.
          For each action set the date range to <b>Today</b> and choose the right statistic:<br><br>
          • <b>Step Count</b> — Summarise: Sum<br>
          • <b>Resting Heart Rate</b> — Limit: 1, Sort: Newest first<br>
          • <b>Heart Rate Variability</b> — Limit: 1, Sort: Newest first<br>
          • <b>Active Energy Burned</b> — Summarise: Sum<br>
          • <b>Sleep Analysis</b> — Summarise: Sum (gives hours × 3600 — divide by 3600 in the next step)<br><br>
          Set a <b>variable name</b> for the result of each action (e.g. "steps", "rhr", "hrv", "cals", "sleep").
        </div>
      </div>
    </div>

    <div class="step">
      <div class="step-num">3</div>
      <div>
        <div class="step-title">Build the request body</div>
        <div class="step-body">
          Add a <b>Dictionary</b> action and add keys for each metric using your variables:
          <div class="json-block">
<span class="c">// key → Health variable</span>
<span class="k">date</span>         → <span class="v">Format Date (Today, "yyyy-MM-dd")</span>
<span class="k">steps</span>        → <span class="v">steps variable</span>
<span class="k">resting_hr</span>   → <span class="v">rhr variable</span>
<span class="k">hrv</span>          → <span class="v">hrv variable</span>
<span class="k">active_calories</span> → <span class="v">cals variable</span>
<span class="k">sleep_hours</span>  → <span class="v">sleep ÷ 3600</span></div>
        </div>
      </div>
    </div>

    <div class="step">
      <div class="step-num">4</div>
      <div>
        <div class="step-title">Send to Arnie</div>
        <div class="step-body">
          Add a <b>"Get Contents of URL"</b> action:<br><br>
          • URL: <code>{endpoint}</code><br>
          • Method: <b>POST</b><br>
          • Request Body: <b>JSON</b> → set to the Dictionary from step 3
        </div>
      </div>
    </div>

    <div class="step">
      <div class="step-num">5</div>
      <div>
        <div class="step-title">Automate it</div>
        <div class="step-body">
          In Shortcuts tap <b>Automation</b> (bottom tab) → <b>+</b> → <b>Time of Day</b><br><br>
          • Time: <b>8:00 AM</b> (or whenever you wake up)<br>
          • Repeat: <b>Daily</b><br>
          • Run Shortcut: <b>Arnie Health Sync</b><br><br>
          Turn off "Ask Before Running" so it runs silently in the background.
        </div>
      </div>
    </div>

  </div>
</div>

<div class="section">
  <div class="section-lbl">Supported fields</div>
  <div class="metrics-grid">
    <div class="metric"><div class="metric-key">date</div><div class="metric-src">yyyy-MM-dd</div></div>
    <div class="metric"><div class="metric-key">steps</div><div class="metric-src">Step Count</div></div>
    <div class="metric"><div class="metric-key">resting_hr</div><div class="metric-src">Resting HR (bpm)</div></div>
    <div class="metric"><div class="metric-key">avg_hr</div><div class="metric-src">Heart Rate avg</div></div>
    <div class="metric"><div class="metric-key">hrv</div><div class="metric-src">HRV SDNN (ms)</div></div>
    <div class="metric"><div class="metric-key">active_calories</div><div class="metric-src">Active Energy (kcal)</div></div>
    <div class="metric"><div class="metric-key">resting_calories</div><div class="metric-src">Basal Energy (kcal)</div></div>
    <div class="metric"><div class="metric-key">sleep_hours</div><div class="metric-src">Sleep total (hrs)</div></div>
    <div class="metric"><div class="metric-key">sleep_deep_hours</div><div class="metric-src">Sleep deep (hrs)</div></div>
    <div class="metric"><div class="metric-key">sleep_rem_hours</div><div class="metric-src">Sleep REM (hrs)</div></div>
    <div class="metric"><div class="metric-key">stand_hours</div><div class="metric-src">Stand Hours</div></div>
    <div class="metric"><div class="metric-key">exercise_minutes</div><div class="metric-src">Exercise Minutes</div></div>
  </div>
</div>

<div class="tip">
  <b>Tip:</b> You only need to include the metrics you care about — all fields are optional.
  Once your first sync arrives, the dashboard will show Apple Health as connected and your metrics
  will appear in the Wearable section of the Day tab.
</div>

</main>
<footer>Arnie &middot; Apple Health via iOS Shortcut</footer>

<script>
function copyUrl(){{
  var url=document.getElementById('url-text').textContent;
  navigator.clipboard.writeText(url).then(function(){{
    var btn=document.getElementById('copy-btn');
    btn.textContent='Copied!';
    setTimeout(function(){{btn.textContent='Copy'}},2000);
  }});
}}
</script>
</body>
</html>"""
