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
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#0f1117">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Arnie</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }}
:root {{
  --bg:#0f1117; --surface:#1a1d27; --surface2:#22263a;
  --border:#2e3347; --green:#22c55e; --blue:#3b82f6;
  --orange:#f97316; --purple:#a855f7; --red:#ef4444; --yellow:#eab308;
  --text:#f1f5f9; --muted:#94a3b8; --dim:#475569;
}}
html, body {{ background: var(--bg); }}
body {{
  font-family: 'Inter', -apple-system, system-ui, sans-serif;
  background: var(--bg); color: var(--text); min-height: 100vh;
  -webkit-font-smoothing: antialiased;
  padding-top: env(safe-area-inset-top);
  padding-bottom: env(safe-area-inset-bottom);
}}

/* ── HEADER ── */
header {{
  background: rgba(15,17,23,0.92);
  backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--border);
  padding: 10px 16px;
  display: flex; align-items: center; justify-content: space-between;
  position: sticky; top: 0; z-index: 20;
}}
.logo {{ font-size: 17px; font-weight: 700; color: var(--green); letter-spacing: -0.4px; }}
.hdr-right {{ display: flex; align-items: center; gap: 8px; }}
.user-name {{ font-weight: 600; font-size: 13px; color: var(--text); }}
.goal-tag {{
  background: var(--surface2); color: var(--muted); font-size: 10px;
  padding: 3px 8px; border-radius: 20px; border: 1px solid var(--border);
  text-transform: capitalize;
}}
.refresh-btn {{
  background: none; border: 1px solid var(--border); color: var(--muted);
  width: 34px; height: 34px; border-radius: 8px; cursor: pointer; font-size: 14px;
  display: flex; align-items: center; justify-content: center; font-family: inherit;
}}
.refresh-btn:active {{ background: var(--surface2); }}

/* ── TABS ── */
.tabs-bar {{
  background: rgba(15,17,23,0.92);
  backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--border);
  padding: 8px 14px;
  display: flex; gap: 6px;
  position: sticky; top: 55px; z-index: 19;
}}
.tab-btn {{
  flex: 1; padding: 8px 10px; border-radius: 9px; border: none;
  background: transparent; color: var(--muted); font-size: 13px; font-weight: 600;
  cursor: pointer; font-family: inherit; min-height: 36px; transition: all 0.15s;
}}
.tab-btn.active {{
  background: var(--surface2); color: var(--text); border: 1px solid var(--border);
}}
.tab-btn:not(.active):active {{ background: var(--surface2); }}

/* ── MAIN ── */
main {{ max-width: 920px; margin: 0 auto; padding: 14px 12px 60px; }}
#app-loading {{ text-align: center; padding: 60px 20px; color: var(--muted); font-size: 14px; }}
.tab-panel {{ display: none; animation: fadeIn 0.25s ease; }}
.tab-panel.active {{ display: block; }}

/* ── SECTION TITLE ── */
.section-title {{
  font-size: 10px; font-weight: 700; color: var(--dim);
  text-transform: uppercase; letter-spacing: 1.2px;
  margin: 22px 2px 9px; display: flex; align-items: center; gap: 8px;
}}
.section-title:first-child {{ margin-top: 2px; }}
.badge-pill {{
  background: var(--surface2); padding: 2px 8px; border-radius: 10px;
  font-size: 9px; letter-spacing: 0.5px; color: var(--muted);
  border: 1px solid var(--border);
}}

/* ── DATE NAV ── */
.date-nav {{
  display: flex; align-items: center; gap: 6px; margin-bottom: 14px;
}}
.date-chips-scroll {{
  flex: 1; display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none;
}}
.date-chips-scroll::-webkit-scrollbar {{ display: none; }}
.date-arrow {{
  background: var(--surface); border: 1px solid var(--border); color: var(--muted);
  width: 36px; height: 36px; min-width: 36px; border-radius: 9px; cursor: pointer;
  font-size: 15px; display: flex; align-items: center; justify-content: center;
  font-family: inherit; flex-shrink: 0; transition: all 0.15s;
}}
.date-arrow:active {{ background: var(--surface2); }}
.date-arrow:disabled {{ opacity: 0.35; cursor: default; }}
.date-chip {{
  background: var(--surface); border: 1px solid var(--border); color: var(--muted);
  padding: 6px 12px; border-radius: 9px; font-size: 12px; font-weight: 600;
  white-space: nowrap; cursor: pointer; transition: all 0.15s; flex-shrink: 0;
  display: inline-flex; align-items: center; gap: 5px;
}}
.date-chip.active {{
  background: var(--surface2); border-color: var(--green); color: var(--text);
}}
.today-tag {{
  background: var(--green); color: #000; font-size: 9px; font-weight: 700;
  padding: 1px 5px; border-radius: 5px;
}}

/* ── MACRO CARDS ── */
.cards {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }}
@media (min-width: 560px) {{ .cards {{ grid-template-columns: repeat(4, 1fr); }} }}
.card {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; padding: 14px;
}}
.card-label {{ font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 6px; font-weight: 600; }}
.card-value {{ font-size: 23px; font-weight: 700; line-height: 1; }}
.card-sub {{ font-size: 11px; color: var(--muted); margin-top: 4px; }}
.progress-track {{ background: var(--surface2); border-radius: 999px; height: 5px; margin-top: 10px; overflow: hidden; }}
.progress-fill {{ height: 100%; border-radius: 999px; transition: width 0.6s ease; }}

/* ── STATUS BADGES ── */
.status-row {{ display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }}
.badge {{
  display: inline-flex; align-items: center; gap: 5px;
  padding: 6px 11px; border-radius: 8px; font-size: 12px; font-weight: 600;
}}
.badge-green  {{ background: rgba(34,197,94,.14); color: var(--green); }}
.badge-gray   {{ background: var(--surface2); color: var(--muted); }}
.badge-blue   {{ background: rgba(59,130,246,.14); color: var(--blue); }}
.badge-orange {{ background: rgba(249,115,22,.14); color: var(--orange); }}

/* ── AI INSIGHTS ── */
.insights-card {{
  background: linear-gradient(160deg, rgba(34,197,94,0.05), rgba(34,197,94,0)), var(--surface);
  border: 1px solid var(--border); border-radius: 14px; padding: 4px 2px;
}}
.insight-row {{
  display: grid; grid-template-columns: 26px 1fr; gap: 10px;
  padding: 11px 14px; border-bottom: 1px solid var(--border); align-items: flex-start;
}}
.insight-row:last-child {{ border-bottom: none; }}
.insight-icon {{
  font-size: 12px; width: 22px; height: 22px; flex-shrink: 0; margin-top: 1px;
  background: rgba(34,197,94,.12); color: var(--green); border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
}}
.insight-text {{ font-size: 13px; line-height: 1.5; color: var(--text); }}
.insights-loading, .insights-empty {{
  padding: 18px 14px; color: var(--muted); font-size: 13px; text-align: center;
}}

/* ── WEARABLE SNAPSHOT ── */
.health-grid {{
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
}}
@media (min-width: 560px) {{ .health-grid {{ grid-template-columns: repeat(6, 1fr); }} }}
.health-tile {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 11px 10px; text-align: center;
}}
.ht-val {{ font-size: 18px; font-weight: 700; line-height: 1; }}
.ht-lbl {{ font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; font-weight: 600; }}

/* ── LOG CARDS ── */
.log-card {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; overflow: hidden;
}}
.log-row {{
  padding: 12px 14px; border-bottom: 1px solid var(--border); position: relative;
}}
.log-row:last-child {{ border-bottom: none; }}
.log-name {{ font-size: 14px; font-weight: 500; line-height: 1.3; word-break: break-word; padding-right: 66px; }}
.log-qty  {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}
.log-macros {{
  display: flex; gap: 10px; font-size: 12px; margin-top: 6px; flex-wrap: wrap;
}}
.log-macros span {{ color: var(--muted); }}
.log-macros b {{ color: var(--text); font-weight: 600; }}
.log-empty {{ padding: 20px 14px; color: var(--muted); font-size: 13px; text-align: center; }}
.ex-row {{
  padding: 12px 14px; border-bottom: 1px solid var(--border); position: relative;
}}
.ex-row:last-child {{ border-bottom: none; }}
.ex-content {{ display: flex; justify-content: space-between; align-items: center; padding-right: 70px; gap: 10px; }}
.ex-name {{ font-size: 14px; font-weight: 500; word-break: break-word; flex: 1; }}
.ex-detail {{ font-size: 12px; color: var(--green); font-weight: 600; white-space: nowrap; }}

/* ── EDIT / DELETE ── */
.row-actions {{ position: absolute; top: 10px; right: 10px; display: flex; gap: 4px; }}
.icon-btn {{
  background: var(--surface2); border: 1px solid var(--border); color: var(--muted);
  width: 30px; height: 30px; border-radius: 8px; cursor: pointer; font-size: 13px;
  display: flex; align-items: center; justify-content: center; font-family: inherit;
  transition: all 0.15s;
}}
.icon-btn:active {{ transform: scale(0.91); }}
.icon-btn:hover {{ background: var(--border); color: var(--text); }}
.icon-btn.danger:hover {{ background: rgba(239,68,68,.15); color: var(--red); border-color: var(--red); }}
.edit-form {{ display: grid; gap: 8px; margin-top: 4px; }}
.edit-form input {{
  background: var(--bg); border: 1px solid var(--border); color: var(--text);
  padding: 8px 10px; border-radius: 8px; font-size: 13px; font-family: inherit; width: 100%;
}}
.edit-form input:focus {{ outline: none; border-color: var(--blue); }}
.edit-macros {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }}
.edit-macro-cell label {{ font-size: 10px; color: var(--muted); display: block; margin-bottom: 2px; }}
.edit-actions {{ display: flex; gap: 6px; margin-top: 4px; }}
.save-btn {{
  background: var(--green); color: #000; border: none; padding: 8px 16px;
  border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; font-family: inherit;
  flex: 1; min-height: 36px;
}}
.cancel-btn {{
  background: var(--surface2); color: var(--muted); border: 1px solid var(--border);
  padding: 8px 16px; border-radius: 8px; font-size: 13px; cursor: pointer; font-family: inherit;
  min-height: 36px;
}}

/* ── CHARTS ── */
.chart-card {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; padding: 16px;
}}
.chart-title {{ font-size: 12px; font-weight: 600; margin-bottom: 12px; color: var(--muted); }}
.chart-wrap {{ position: relative; height: 160px; }}
@media (min-width: 700px) {{ .chart-wrap {{ height: 180px; }} }}
.charts-2col {{ display: grid; grid-template-columns: 1fr; gap: 10px; }}
@media (min-width: 700px) {{ .charts-2col {{ grid-template-columns: 1fr 1fr; }} }}

/* ── HISTORY TABLE ── */
.history-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
.history-table th {{
  color: var(--dim); text-transform: uppercase; letter-spacing: 0.5px;
  font-size: 10px; font-weight: 700; padding: 8px 10px; text-align: left;
  border-bottom: 1px solid var(--border);
}}
.history-table td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); color: var(--muted); }}
.history-table tr:last-child td {{ border-bottom: none; }}
.history-table td:first-child {{ color: var(--text); font-weight: 500; }}
.td-hit  {{ color: var(--green) !important; font-weight: 600; }}
.td-over {{ color: var(--red)   !important; font-weight: 600; }}

/* ── PROFILE ── */
.info-card {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; overflow: hidden; margin-bottom: 10px;
}}
.info-row {{
  display: flex; justify-content: space-between; align-items: center;
  padding: 11px 14px; border-bottom: 1px solid var(--border);
}}
.info-row:last-child {{ border-bottom: none; }}
.info-label {{ font-size: 13px; color: var(--muted); }}
.info-value {{ font-size: 13px; font-weight: 600; color: var(--text); text-align: right; max-width: 60%; }}
.analytics-card {{
  background: linear-gradient(135deg, rgba(59,130,246,0.06), rgba(59,130,246,0)), var(--surface);
  border: 1px solid var(--border); border-radius: 14px; padding: 14px; margin-bottom: 10px;
}}
.analytics-title {{ font-size: 11px; color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 10px; }}
.analytics-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }}
@media (min-width: 560px) {{ .analytics-grid {{ grid-template-columns: repeat(3, 1fr); }} }}
.analytic-item {{ background: var(--surface2); border-radius: 10px; padding: 10px; }}
.analytic-val {{ font-size: 18px; font-weight: 700; line-height: 1; }}
.analytic-lbl {{ font-size: 10px; color: var(--muted); margin-top: 3px; font-weight: 500; }}
.device-row {{
  display: flex; align-items: center; gap: 10px; padding: 12px 14px;
  border-bottom: 1px solid var(--border);
}}
.device-row:last-child {{ border-bottom: none; }}
.device-name {{ font-size: 13px; font-weight: 600; flex: 1; }}
.device-status {{ font-size: 12px; font-weight: 600; }}
.device-status.connected {{ color: var(--green); }}
.device-status.disconnected {{ color: var(--muted); }}

/* ── MISC ── */
footer {{ text-align: center; padding: 20px 16px; color: var(--dim); font-size: 11px; }}
@keyframes fadeIn {{ from {{ opacity:0; transform:translateY(5px); }} to {{ opacity:1; transform:translateY(0); }} }}
.fade-in {{ animation: fadeIn 0.3s ease; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
.spin {{ display:inline-block; animation:spin 1s linear infinite; }}
</style>
</head>
<body>

<header>
  <div class="logo">&#127947; Arnie</div>
  <div class="hdr-right">
    <span class="user-name" id="user-name"></span>
    <span id="goal-tag" class="goal-tag"></span>
    <button class="refresh-btn" onclick="refreshCurrent()" aria-label="Refresh" title="Refresh">&#8635;</button>
  </div>
</header>

<div class="tabs-bar" role="tablist">
  <button class="tab-btn active" role="tab" onclick="switchTab('day')" id="tab-day">Day</button>
  <button class="tab-btn" role="tab" onclick="switchTab('week')" id="tab-week">Week</button>
  <button class="tab-btn" role="tab" onclick="switchTab('profile')" id="tab-profile">Profile</button>
</div>

<main>
  <div id="app-loading">Loading your data&hellip;</div>

  <!-- ══ DAY TAB ══ -->
  <div class="tab-panel active" id="panel-day">

    <div class="date-nav">
      <button class="date-arrow" id="date-prev" onclick="navDate(-1)" aria-label="Previous day">&#8249;</button>
      <div class="date-chips-scroll" id="date-chips"></div>
      <button class="date-arrow" id="date-next" onclick="navDate(1)" aria-label="Next day">&#8250;</button>
    </div>

    <div class="section-title">&#10024; Coach insights <span class="badge-pill">AI</span></div>
    <div class="insights-card fade-in" id="insights-card">
      <div class="insights-loading"><span class="spin">&#9675;</span> Analyzing&hellip;</div>
    </div>

    <div class="section-title" id="day-label">Today</div>
    <div class="cards">
      <div class="card">
        <div class="card-label">Calories</div>
        <div class="card-value" id="cal-val">&mdash;</div>
        <div class="card-sub" id="cal-sub"></div>
        <div class="progress-track"><div class="progress-fill" id="cal-bar" style="background:var(--green);width:0%"></div></div>
      </div>
      <div class="card">
        <div class="card-label">Protein</div>
        <div class="card-value" id="pro-val">&mdash;</div>
        <div class="card-sub" id="pro-sub"></div>
        <div class="progress-track"><div class="progress-fill" id="pro-bar" style="background:var(--blue);width:0%"></div></div>
      </div>
      <div class="card">
        <div class="card-label">Carbs</div>
        <div class="card-value" id="carb-val">&mdash;</div>
        <div class="card-sub" style="color:var(--orange)">grams</div>
      </div>
      <div class="card">
        <div class="card-label">Fats</div>
        <div class="card-value" id="fat-val">&mdash;</div>
        <div class="card-sub" style="color:var(--purple)">grams</div>
      </div>
    </div>

    <div class="status-row">
      <span id="workout-badge" class="badge badge-gray"></span>
      <span id="cardio-badge" class="badge badge-gray"></span>
      <span id="water-badge" class="badge badge-blue" style="display:none"></span>
    </div>

    <div class="section-title">Food log</div>
    <div class="log-card" id="food-log"><div class="log-empty">Loading&hellip;</div></div>

    <div class="section-title">Workouts</div>
    <div class="log-card" id="ex-log"><div class="log-empty">Loading&hellip;</div></div>

    <div id="health-section" style="display:none">
      <div class="section-title">Wearable snapshot</div>
      <div class="health-grid" id="health-grid"></div>
    </div>

  </div>

  <!-- ══ WEEK TAB ══ -->
  <div class="tab-panel" id="panel-week">
    <div class="charts-2col">
      <div class="chart-card">
        <div class="chart-title">Calories &mdash; 30 days</div>
        <div class="chart-wrap"><canvas id="calChart"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Protein &mdash; 30 days</div>
        <div class="chart-wrap"><canvas id="proChart"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Weight trend (lbs)</div>
        <div class="chart-wrap"><canvas id="weightChart"></canvas></div>
      </div>
    </div>
    <div class="section-title">Last 14 days</div>
    <div class="info-card" id="hist-table-wrap"><div class="log-empty">Loading&hellip;</div></div>
  </div>

  <!-- ══ PROFILE TAB ══ -->
  <div class="tab-panel" id="panel-profile">
    <div class="section-title">Your info</div>
    <div class="info-card" id="profile-info"></div>

    <div class="section-title">Targets</div>
    <div class="info-card" id="profile-targets"></div>

    <div class="section-title">Science</div>
    <div class="analytics-card">
      <div class="analytics-title">Analytics</div>
      <div class="analytics-grid" id="analytics-grid"></div>
    </div>

    <div class="section-title">Connected devices</div>
    <div class="info-card" id="devices-card"></div>
  </div>

</main>

<footer>Arnie &middot; auto-refresh 5 min</footer>

<script>
// ── Constants ────────────────────────────────────────────────────────────
const TOKEN = '{token}';
const STATS_BASE  = '/api/stats/'   + TOKEN;
const INSIGHTS_API = '/api/insights/' + TOKEN;

// ── State ────────────────────────────────────────────────────────────────
let _baseData    = null;
let _dayCache    = {{}};
let _viewingDate = null;
let _todayStr    = null;
let _availDates  = [];
let _activeTab   = 'day';
let calChart, proChart, weightChart;

// ── Utils ────────────────────────────────────────────────────────────────
function esc(s) {{
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
}}
function escAttr(s) {{ return String(s ?? '').replace(/"/g, '&quot;'); }}
function pct(val, tgt) {{ return (!tgt || val == null) ? 0 : Math.min(100, Math.round(val / tgt * 100)); }}
function fmt(n)  {{ return n != null ? Number(n).toLocaleString() : '—'; }}
function fmtDate(d) {{
  const [, m, day] = d.split('-');
  return ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+m-1] + ' ' + +day;
}}

// ── API ──────────────────────────────────────────────────────────────────
async function fetchStats(dateStr) {{
  const url = dateStr ? STATS_BASE + '?date=' + dateStr : STATS_BASE;
  const r = await fetch(url);
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}}
async function fetchInsights() {{
  try {{
    const r = await fetch(INSIGHTS_API);
    if (!r.ok) return [];
    return (await r.json()).insights || [];
  }} catch(e) {{ return []; }}
}}

// ── Tab switching ─────────────────────────────────────────────────────────
function switchTab(name) {{
  _activeTab = name;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('tab-'   + name).classList.add('active');
  document.getElementById('panel-' + name).classList.add('active');
  if (name === 'week'    && _baseData) renderWeekTab(_baseData);
  if (name === 'profile' && _baseData) renderProfileTab(_baseData);
}}

// ── Boot ──────────────────────────────────────────────────────────────────
async function init() {{
  try {{
    const data = await fetchStats(null);
    _baseData    = data;
    _todayStr    = data.viewing_date || data.day?.date || new Date().toISOString().slice(0,10);
    _viewingDate = _todayStr;

    const histDates = (data.history || []).map(h => h.date);
    _availDates = [...new Set([...histDates, _todayStr])].sort();
    _dayCache[_todayStr] = data;

    document.getElementById('user-name').textContent = data.profile?.name || '';
    document.getElementById('goal-tag').textContent  = data.profile?.primary_goal || '';
    document.getElementById('app-loading').style.display = 'none';

    renderDateNav();
    renderDayTab(data);
    fetchInsights().then(renderInsights);
  }} catch(e) {{
    document.getElementById('app-loading').textContent = 'Failed to load — tap ↻ to retry.';
  }}
}}

async function refreshCurrent() {{
  delete _dayCache[_viewingDate];
  if (_viewingDate === _todayStr) {{
    try {{
      const data = await fetchStats(null);
      _baseData = data;
      _dayCache[_todayStr] = data;
      renderDayTab(data);
      if (_activeTab === 'week')    renderWeekTab(data);
      if (_activeTab === 'profile') renderProfileTab(data);
    }} catch(e) {{}}
  }} else {{
    await loadDayData(_viewingDate);
  }}
}}

// ── Date nav ──────────────────────────────────────────────────────────────
function renderDateNav() {{
  const chipsEl = document.getElementById('date-chips');
  chipsEl.innerHTML = '';
  const ci    = _availDates.indexOf(_viewingDate);
  let start   = Math.max(0, ci - 2);
  let end     = Math.min(_availDates.length - 1, ci + 2);
  while (end - start < 4 && start > 0) start--;
  while (end - start < 4 && end < _availDates.length - 1) end++;

  for (let i = start; i <= end; i++) {{
    const d    = _availDates[i];
    const chip = document.createElement('button');
    chip.className = 'date-chip' + (d === _viewingDate ? ' active' : '');

    const txt = document.createTextNode(fmtDate(d));
    chip.appendChild(txt);
    if (d === _todayStr) {{
      const tag = document.createElement('span');
      tag.className = 'today-tag';
      tag.textContent = 'Today';
      chip.appendChild(tag);
    }}
    const capturedDate = d;
    chip.onclick = () => selectDate(capturedDate);
    chipsEl.appendChild(chip);
  }}

  document.getElementById('date-prev').disabled = ci <= 0;
  document.getElementById('date-next').disabled = ci >= _availDates.length - 1;
}}

async function navDate(dir) {{
  const ci = _availDates.indexOf(_viewingDate);
  const ni = ci + dir;
  if (ni < 0 || ni >= _availDates.length) return;
  await selectDate(_availDates[ni]);
}}

async function selectDate(dateStr) {{
  _viewingDate = dateStr;
  renderDateNav();
  if (_dayCache[dateStr]) {{
    renderDayTab(_dayCache[dateStr]);
  }} else {{
    await loadDayData(dateStr);
  }}
}}

async function loadDayData(dateStr) {{
  document.getElementById('food-log').innerHTML = '<div class="log-empty">Loading…</div>';
  document.getElementById('ex-log').innerHTML   = '<div class="log-empty">Loading…</div>';
  try {{
    const data = await fetchStats(dateStr);
    _dayCache[dateStr] = data;
    renderDayTab(data);
  }} catch(e) {{
    document.getElementById('food-log').innerHTML = '<div class="log-empty">Failed to load.</div>';
  }}
}}

// ── Day tab ───────────────────────────────────────────────────────────────
function renderDayTab(d) {{
  const isToday = _viewingDate === _todayStr;
  document.getElementById('day-label').textContent = isToday ? 'Today' : fmtDate(_viewingDate);

  const day = d.day || {{}};
  const tgt = d.targets || {{}};
  const calP = pct(day.calories, tgt.calories);
  const proP = pct(day.protein,  tgt.protein);

  document.getElementById('cal-val').textContent  = fmt(day.calories);
  document.getElementById('cal-sub').textContent  = tgt.calories ? `/ ${{tgt.calories}} (${{calP}}%)` : 'kcal';
  document.getElementById('cal-bar').style.width  = calP + '%';
  document.getElementById('pro-val').textContent  = day.protein  != null ? day.protein  + 'g' : '—';
  document.getElementById('pro-sub').textContent  = tgt.protein  ? `/ ${{tgt.protein}}g (${{proP}}%)` : 'grams';
  document.getElementById('pro-bar').style.width  = proP + '%';
  document.getElementById('carb-val').textContent = day.carbs != null ? day.carbs + 'g' : '—';
  document.getElementById('fat-val').textContent  = day.fats  != null ? day.fats  + 'g' : '—';

  const wb = document.getElementById('workout-badge');
  wb.className = 'badge ' + (day.workout_completed ? 'badge-green' : 'badge-gray');
  wb.textContent = day.workout_completed ? '💪 Workout done' : '⬜ No workout';

  const cb = document.getElementById('cardio-badge');
  cb.className = 'badge ' + (day.cardio_completed ? 'badge-green' : 'badge-gray');
  cb.textContent = day.cardio_completed ? '🏃 Cardio done' : '⬜ No cardio';

  const wb2 = document.getElementById('water-badge');
  if (day.water_ml > 0) {{
    wb2.style.display = 'inline-flex';
    wb2.textContent = '💧 ' + (day.water_ml >= 1000 ? (day.water_ml/1000).toFixed(1) + 'L' : day.water_ml + 'ml');
  }} else {{
    wb2.style.display = 'none';
  }}

  // Food
  const foodEl = document.getElementById('food-log');
  const fe = day.food_entries || [];
  if (fe.length === 0) {{
    foodEl.innerHTML = '<div class="log-empty">Nothing logged' + (isToday ? ' yet' : '') + '</div>';
  }} else {{
    foodEl.innerHTML = fe.map(f => renderFoodRow(f)).join('');
  }}

  // Exercise
  const exEl = document.getElementById('ex-log');
  const ee = day.exercise_entries || [];
  if (ee.length === 0) {{
    exEl.innerHTML = '<div class="log-empty">No exercises logged' + (isToday ? ' yet' : '') + '</div>';
  }} else {{
    exEl.innerHTML = ee.map(e => renderExerciseRow(e)).join('');
  }}

  // Health
  const healthList  = d.health || [];
  const healthToday = healthList.find(h => h.date === _viewingDate) || null;
  const hs = document.getElementById('health-section');
  if (healthToday) {{
    hs.style.display = 'block';
    renderHealthGrid(healthToday);
  }} else {{
    hs.style.display = 'none';
  }}
}}

function renderHealthGrid(h) {{
  const tiles = [];
  function rc(s) {{ return s >= 67 ? '#22c55e' : s >= 34 ? '#eab308' : '#ef4444'; }}
  if (h.recovery_score != null) tiles.push([h.recovery_score + '%',         'Recovery', rc(h.recovery_score)]);
  if (h.hrv            != null) tiles.push([h.hrv + 'ms',                   'HRV',      '#a855f7']);
  if (h.resting_hr     != null) tiles.push([h.resting_hr + 'bpm',           'Rest HR',  '#3b82f6']);
  if (h.sleep_hours    != null) tiles.push([(+h.sleep_hours).toFixed(1)+'h','Sleep',    '#22c55e']);
  if (h.strain         != null) tiles.push([(+h.strain).toFixed(1),         'Strain',   '#f97316']);
  if (h.steps          != null) tiles.push([(+h.steps).toLocaleString(),    'Steps',    '#eab308']);
  document.getElementById('health-grid').innerHTML = tiles.map(([v,l,c]) =>
    `<div class="health-tile"><div class="ht-val" style="color:${{c}}">${{esc(v)}}</div><div class="ht-lbl">${{esc(l)}}</div></div>`
  ).join('');
}}

// ── Week tab ──────────────────────────────────────────────────────────────
function renderWeekTab(d) {{
  const hist = (d.history || []).slice(-30);
  const tgt  = d.targets  || {{}};
  const labels  = hist.map(h => h.date.slice(5));
  const calData = hist.map(h => h.calories ?? 0);
  const proData = hist.map(h => h.protein  ?? 0);

  const baseOpts = {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ display: false }}, ticks: {{ color:'#475569', font:{{size:9}}, maxRotation:0, autoSkip:true, maxTicksLimit:8 }} }},
      y: {{ grid: {{ color:'#2e334755' }}, ticks: {{ color:'#475569', font:{{size:10}} }}, beginAtZero:true }}
    }}
  }};

  if (calChart) calChart.destroy();
  calChart = new Chart(document.getElementById('calChart'), {{
    type: 'bar',
    data: {{
      labels,
      datasets: [
        {{
          data: calData,
          backgroundColor: calData.map(v => tgt.calories && v > tgt.calories ? 'rgba(239,68,68,.7)' : 'rgba(34,197,94,.7)'),
          borderRadius: 3,
        }},
        ...(tgt.calories ? [{{
          type:'line', data: Array(labels.length).fill(tgt.calories),
          borderColor:'rgba(255,255,255,.3)', borderDash:[4,4], borderWidth:1.5,
          pointRadius:0, fill:false,
        }}] : [])
      ]
    }},
    options: baseOpts,
  }});

  if (proChart) proChart.destroy();
  proChart = new Chart(document.getElementById('proChart'), {{
    type: 'bar',
    data: {{
      labels,
      datasets: [
        {{
          data: proData,
          backgroundColor: proData.map(v => tgt.protein && v >= tgt.protein ? 'rgba(59,130,246,.8)' : 'rgba(59,130,246,.35)'),
          borderRadius: 3,
        }},
        ...(tgt.protein ? [{{
          type:'line', data: Array(labels.length).fill(tgt.protein),
          borderColor:'rgba(255,255,255,.3)', borderDash:[4,4], borderWidth:1.5,
          pointRadius:0, fill:false,
        }}] : [])
      ]
    }},
    options: baseOpts,
  }});

  if (weightChart) weightChart.destroy();
  const wData = (d.weights || []).slice(-30);
  weightChart = new Chart(document.getElementById('weightChart'), {{
    type: 'line',
    data: {{
      labels: wData.map(w => w.date.slice(5)),
      datasets: [
        {{
          data: wData.map(w => w.lbs),
          borderColor:'#f97316', backgroundColor:'rgba(249,115,22,.08)',
          borderWidth:2, pointRadius:2.5, pointBackgroundColor:'#f97316',
          fill:true, tension:0.35,
        }},
        ...(d.profile?.goal_weight_lbs && wData.length ? [{{
          type:'line', data: Array(wData.length).fill(d.profile.goal_weight_lbs),
          borderColor:'rgba(34,197,94,.4)', borderDash:[4,4], borderWidth:1.5,
          pointRadius:0, fill:false,
        }}] : [])
      ]
    }},
    options: {{ ...baseOpts, scales: {{ ...baseOpts.scales, y: {{ ...baseOpts.scales.y, beginAtZero:false }} }} }},
  }});

  // History table
  const rows = hist.slice(-14).reverse();
  const tableHtml = rows.length === 0
    ? '<div class="log-empty">No history yet</div>'
    : `<table class="history-table"><thead><tr>
        <th>Date</th><th>Calories</th><th>Protein</th><th>Workout</th>
       </tr></thead><tbody>` +
      rows.map(h => {{
        const calCls = tgt.calories
          ? (h.calories >= tgt.calories*0.9 && h.calories <= tgt.calories*1.1 ? 'td-hit'
              : h.calories > tgt.calories*1.1 ? 'td-over' : '')
          : '';
        const proCls = tgt.protein ? (h.protein >= tgt.protein*0.9 ? 'td-hit' : '') : '';
        return `<tr>
          <td>${{esc(h.date.slice(5))}}</td>
          <td class="${{calCls}}">${{h.calories ?? '—'}}</td>
          <td class="${{proCls}}">${{h.protein != null ? h.protein + 'g' : '—'}}</td>
          <td>${{h.workout ? '✓' : '✗'}}</td>
        </tr>`;
      }}).join('') +
      '</tbody></table>';
  document.getElementById('hist-table-wrap').innerHTML = tableHtml;
}}

// ── Profile tab ───────────────────────────────────────────────────────────
function renderProfileTab(d) {{
  const p  = d.profile  || {{}};
  const tgt = d.targets || {{}};
  const an = p.analytics || {{}};

  const infoRows = [
    ['Name',           p.name],
    ['Age',            p.age ? p.age + ' yrs' : null],
    ['Sex',            p.sex],
    ['Height',         p.height_ft || (p.height_cm ? p.height_cm + ' cm' : null)],
    ['Current weight', p.current_weight_lbs ? p.current_weight_lbs + ' lbs' : null],
    ['Goal weight',    p.goal_weight_lbs    ? p.goal_weight_lbs    + ' lbs' : null],
    ['Goal',           p.primary_goal],
    ['Experience',     p.training_experience],
    ['Diet',           p.dietary_preferences && p.dietary_preferences !== 'none' ? p.dietary_preferences : null],
    ['Injuries',       p.injuries && p.injuries !== 'none' ? p.injuries : null],
    ['Timezone',       p.timezone],
    ['Coaching style', p.coaching_style],
  ].filter(([, v]) => v != null && v !== '');

  document.getElementById('profile-info').innerHTML = infoRows.map(([l, v]) =>
    `<div class="info-row"><span class="info-label">${{esc(l)}}</span><span class="info-value">${{esc(String(v))}}</span></div>`
  ).join('') || '<div class="log-empty">No profile data</div>';

  document.getElementById('profile-targets').innerHTML =
    `<div class="info-row"><span class="info-label">Calorie target</span><span class="info-value" style="color:var(--green)">${{tgt.calories ? tgt.calories.toLocaleString() + ' kcal/day' : '—'}}</span></div>` +
    `<div class="info-row"><span class="info-label">Protein target</span><span class="info-value" style="color:var(--blue)">${{tgt.protein ? tgt.protein + 'g/day' : '—'}}</span></div>`;

  const items = [
    ['TDEE estimate',  an.tdee_estimate   != null ? an.tdee_estimate.toLocaleString() + ' kcal' : null, '#22c55e'],
    ['BMR',            an.bmr             != null ? an.bmr.toLocaleString() + ' kcal'            : null, '#3b82f6'],
    ['Daily diff',     an.daily_vs_tdee   != null ? (an.daily_vs_tdee>0?'+':'') + an.daily_vs_tdee + ' kcal' : null,
      an.pace_label === 'surplus' ? '#f97316' : '#22c55e'],
    ['Target pace',    an.pace_lbs_per_week    != null ? an.pace_lbs_per_week + ' lbs/wk'    : null, '#22c55e'],
    ['Actual pace',    an.actual_lbs_per_week  != null ? an.actual_lbs_per_week + ' lbs/wk'  : null, '#94a3b8'],
    ['Weeks to goal',  an.weeks_to_goal        != null ? an.weeks_to_goal + ' wks'           : null, '#eab308'],
    ['Rec. protein',   (an.rec_protein_min && an.rec_protein_max)
        ? an.rec_protein_min + '–' + an.rec_protein_max + 'g' : null, '#a855f7'],
  ].filter(([, v]) => v != null);

  document.getElementById('analytics-grid').innerHTML = items.map(([l, v, c]) =>
    `<div class="analytic-item"><div class="analytic-val" style="color:${{c}}">${{esc(String(v))}}</div><div class="analytic-lbl">${{esc(l)}}</div></div>`
  ).join('') || '<div style="color:var(--muted);font-size:13px;grid-column:1/-1">No analytics data yet</div>';

  document.getElementById('devices-card').innerHTML =
    `<div class="device-row">
      <span style="font-size:18px">&#8987;</span>
      <span class="device-name">Whoop</span>
      <span class="device-status ${{p.whoop_connected ? 'connected' : 'disconnected'}}">
        ${{p.whoop_connected ? '✓ Connected' : '⚠ Not connected'}}
      </span>
     </div>`;
}}

// ── Insights ──────────────────────────────────────────────────────────────
function renderInsights(insights) {{
  const el = document.getElementById('insights-card');
  if (!insights || insights.length === 0) {{
    el.innerHTML = '<div class="insights-empty">Not enough data yet — keep logging and check back tomorrow.</div>';
    return;
  }}
  el.innerHTML = insights.map(text =>
    `<div class="insight-row fade-in"><div class="insight-icon">▸</div><div class="insight-text">${{esc(text)}}</div></div>`
  ).join('');
}}

// ── Food row ──────────────────────────────────────────────────────────────
function renderFoodRow(f) {{
  const est = f.estimated ? ' <span style="color:var(--dim);font-size:10px;font-weight:400">~est</span>' : '';
  return `<div class="log-row" id="food-row-${{f.id}}">
    <div class="log-name">${{esc(f.name)}}${{est}}</div>
    <div class="log-qty">${{esc(f.quantity || '')}}</div>
    <div class="log-macros">
      <span><b>${{f.calories ?? 0}}</b> cal</span>
      <span><b>${{f.protein ?? 0}}g</b> P</span>
      <span><b>${{f.carbs ?? 0}}g</b> C</span>
      <span><b>${{f.fats ?? 0}}g</b> F</span>
    </div>
    <div class="row-actions">
      <button class="icon-btn" onclick="editFood(${{f.id}})" aria-label="Edit">✎</button>
      <button class="icon-btn danger" onclick="deleteFood(${{f.id}})" aria-label="Delete">×</button>
    </div>
  </div>`;
}}

// ── Exercise row ──────────────────────────────────────────────────────────
function renderExerciseRow(e) {{
  let detail = '';
  if (e.sets && e.reps) detail = `${{e.sets}}×${{e.reps}}${{e.weight ? ' @ ' + e.weight + 'lb' : ''}}`;
  else if (e.duration_minutes) detail = `${{e.duration_minutes}} min`;
  return `<div class="ex-row" id="ex-row-${{e.id}}">
    <div class="ex-content">
      <div class="ex-name">${{esc(e.name)}}</div>
      <div class="ex-detail">${{esc(detail)}}</div>
    </div>
    <div class="row-actions">
      <button class="icon-btn" onclick="editExercise(${{e.id}})" aria-label="Edit">✎</button>
      <button class="icon-btn danger" onclick="deleteExercise(${{e.id}})" aria-label="Delete">×</button>
    </div>
  </div>`;
}}

// ── Inline edit: food ─────────────────────────────────────────────────────
function findFood(id) {{
  return (_dayCache[_viewingDate]?.day?.food_entries || []).find(f => f.id === id);
}}
function findExercise(id) {{
  return (_dayCache[_viewingDate]?.day?.exercise_entries || []).find(e => e.id === id);
}}

function editFood(id) {{
  const f = findFood(id);
  if (!f) return;
  document.getElementById('food-row-' + id).innerHTML =
    `<div class="edit-form">
      <input type="text" id="ef-name-${{id}}" value="${{escAttr(f.name)}}" placeholder="Food name">
      <input type="text" id="ef-qty-${{id}}"  value="${{escAttr(f.quantity || '')}}" placeholder="Quantity">
      <div class="edit-macros">
        <div class="edit-macro-cell"><label>Cal</label><input type="number" id="ef-cal-${{id}}"  value="${{f.calories ?? ''}}" inputmode="numeric"></div>
        <div class="edit-macro-cell"><label>P (g)</label><input type="number" id="ef-pro-${{id}}"  value="${{f.protein ?? ''}}" inputmode="numeric"></div>
        <div class="edit-macro-cell"><label>C (g)</label><input type="number" id="ef-carb-${{id}}" value="${{f.carbs ?? ''}}"   inputmode="numeric"></div>
        <div class="edit-macro-cell"><label>F (g)</label><input type="number" id="ef-fat-${{id}}"  value="${{f.fats ?? ''}}"    inputmode="numeric"></div>
      </div>
      <div class="edit-actions">
        <button class="save-btn"   onclick="saveFood(${{id}})">Save</button>
        <button class="cancel-btn" onclick="cancelEdit()">Cancel</button>
      </div>
    </div>`;
}}

async function saveFood(id) {{
  const body = {{
    food_name: document.getElementById('ef-name-'  + id).value,
    quantity:  document.getElementById('ef-qty-'   + id).value,
    calories:  parseFloat(document.getElementById('ef-cal-'  + id).value) || 0,
    protein:   parseFloat(document.getElementById('ef-pro-'  + id).value) || 0,
    carbs:     parseFloat(document.getElementById('ef-carb-' + id).value) || 0,
    fats:      parseFloat(document.getElementById('ef-fat-'  + id).value) || 0,
  }};
  const btn = document.querySelector('#food-row-' + id + ' .save-btn');
  if (btn) {{ btn.disabled = true; btn.textContent = '…'; }}
  const r = await fetch(`/api/food/${{id}}?token=${{TOKEN}}`, {{
    method: 'PATCH', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(body),
  }});
  if (!r.ok) {{ alert('Save failed — please try again.'); if (btn) {{ btn.disabled=false; btn.textContent='Save'; }} return; }}
  delete _dayCache[_viewingDate];
  await loadDayData(_viewingDate);
}}

async function deleteFood(id) {{
  const f = findFood(id);
  if (!confirm('Delete "' + (f ? f.name : 'this item') + '"?')) return;
  const r = await fetch(`/api/food/${{id}}?token=${{TOKEN}}`, {{ method: 'DELETE' }});
  if (!r.ok) {{ alert('Delete failed — please try again.'); return; }}
  delete _dayCache[_viewingDate];
  await loadDayData(_viewingDate);
}}

// ── Inline edit: exercise ─────────────────────────────────────────────────
function editExercise(id) {{
  const e = findExercise(id);
  if (!e) return;
  document.getElementById('ex-row-' + id).innerHTML =
    `<div class="edit-form">
      <input type="text" id="ee-name-${{id}}" value="${{escAttr(e.name)}}" placeholder="Exercise name">
      <div class="edit-macros" style="grid-template-columns:repeat(3,1fr)">
        <div class="edit-macro-cell"><label>Sets</label><input type="number" id="ee-sets-${{id}}"   value="${{e.sets ?? ''}}" inputmode="numeric"></div>
        <div class="edit-macro-cell"><label>Reps</label><input type="text"   id="ee-reps-${{id}}"   value="${{escAttr(e.reps ?? '')}}"></div>
        <div class="edit-macro-cell"><label>Weight (lb)</label><input type="number" id="ee-weight-${{id}}" value="${{e.weight ?? ''}}" inputmode="decimal"></div>
      </div>
      <div class="edit-actions">
        <button class="save-btn"   onclick="saveExercise(${{id}})">Save</button>
        <button class="cancel-btn" onclick="cancelEdit()">Cancel</button>
      </div>
    </div>`;
}}

async function saveExercise(id) {{
  const body = {{
    exercise_name: document.getElementById('ee-name-'   + id).value || null,
    sets:          parseInt(document.getElementById('ee-sets-'   + id).value) || null,
    reps:          document.getElementById('ee-reps-'   + id).value || null,
    weight:        parseFloat(document.getElementById('ee-weight-' + id).value) || null,
  }};
  Object.keys(body).forEach(k => body[k] == null && delete body[k]);
  const btn = document.querySelector('#ex-row-' + id + ' .save-btn');
  if (btn) {{ btn.disabled = true; btn.textContent = '…'; }}
  const r = await fetch(`/api/exercise/${{id}}?token=${{TOKEN}}`, {{
    method: 'PATCH', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(body),
  }});
  if (!r.ok) {{ alert('Save failed — please try again.'); if (btn) {{ btn.disabled=false; btn.textContent='Save'; }} return; }}
  delete _dayCache[_viewingDate];
  await loadDayData(_viewingDate);
}}

async function deleteExercise(id) {{
  const e = findExercise(id);
  if (!confirm('Delete "' + (e ? e.name : 'this exercise') + '"?')) return;
  const r = await fetch(`/api/exercise/${{id}}?token=${{TOKEN}}`, {{ method: 'DELETE' }});
  if (!r.ok) {{ alert('Delete failed — please try again.'); return; }}
  delete _dayCache[_viewingDate];
  await loadDayData(_viewingDate);
}}

function cancelEdit() {{
  const d = _dayCache[_viewingDate];
  if (d) renderDayTab(d);
}}

// ── Start ─────────────────────────────────────────────────────────────────
init();
setInterval(() => {{
  delete _dayCache[_todayStr];
  if (_viewingDate === _todayStr) refreshCurrent();
}}, 5 * 60 * 1000);
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
        await upsert_health_snapshot(db, user.id, snap_date, **data)

    return {"status": "ok", "date": str(snap_date)}
