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
    get_today_log, get_recent_logs, get_recent_weights,
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

    tokens = await exchange_code(code, redirect_uri)
    if not tokens:
        return HTMLResponse(
            "<h2>Whoop token exchange failed.</h2>"
            "<p>Try /connect whoop again in Telegram.</p>",
            status_code=500,
        )

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

        # Pull the first batch right away
        synced = 0
        try:
            user_reloaded = await get_user_by_webhook_token(db, state)
            synced = await sync_user_whoop(db, user_reloaded, days=7)
        except Exception as e:
            pass

    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Whoop connected</title>
<style>body{{font-family:system-ui;text-align:center;padding:60px;background:#0f1117;color:#f1f5f9}}
.box{{max-width:480px;margin:auto;background:#1a1d27;border:1px solid #2e3347;border-radius:12px;padding:32px}}
.check{{font-size:48px;color:#22c55e}}h1{{font-size:24px;margin:16px 0}}p{{color:#94a3b8}}</style>
</head><body>
<div class="box">
  <div class="check">✓</div>
  <h1>Whoop connected</h1>
  <p>Synced {synced} days of recovery, sleep, and strain data.</p>
  <p>You can close this window and head back to Telegram. Arnie will reference your recovery score in coaching from now on.</p>
</div></body></html>""")


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


async def _build_stats_for_user(db, user):
    """Shared stats-building logic used by both /api/stats and /api/insights."""
    prefs = user.preferences
    today_log = await get_today_log(db, user.id, user.timezone or "UTC")
    history = await get_recent_logs(db, user.id, days=30)
    weights = await get_recent_weights(db, user.id, days=60)

    today_data = None
    if today_log:
        food_entries = [
            {
                "name": e.parsed_food_name or "?",
                "quantity": e.quantity or "",
                "calories": round(e.calories or 0),
                "protein": round(e.protein or 0),
                "carbs": round(e.carbs or 0),
                "fats": round(e.fats or 0),
                "estimated": e.estimated_flag,
            }
            for e in (today_log.food_entries or [])
        ]
        exercise_entries = [
            {
                "name": e.exercise_name or "?",
                "sets": e.sets,
                "reps": e.reps,
                "weight": round(e.weight * 2.20462, 1) if e.weight else None,
                "duration_minutes": e.duration_minutes,
            }
            for e in (today_log.exercise_entries or [])
        ]
        today_data = {
            "date": str(today_log.date),
            "status": today_log.status,
            "calories": round(today_log.total_calories or 0),
            "protein": round(today_log.total_protein or 0),
            "carbs": round(today_log.total_carbs or 0),
            "fats": round(today_log.total_fats or 0),
            "water_ml": round(today_log.total_water_ml or 0),
            "workout_completed": today_log.workout_completed,
            "cardio_completed": today_log.cardio_completed,
            "food_entries": food_entries,
            "exercise_entries": exercise_entries,
        }

    hist_data = []
    for log in sorted(history, key=lambda l: l.date):
        hist_data.append({
            "date": str(log.date),
            "calories": round(log.total_calories or 0),
            "protein": round(log.total_protein or 0),
            "carbs": round(log.total_carbs or 0),
            "fats": round(log.total_fats or 0),
            "workout": log.workout_completed,
            "status": log.status,
        })

    weight_data = [
        {"date": w.timestamp.strftime("%Y-%m-%d"),
         "kg": round(w.weight_kg, 1),
         "lbs": round(w.weight_kg * 2.20462, 1)}
        for w in sorted(weights, key=lambda w: w.timestamp)
    ]

    return {
        "user": {
            "name": user.name or "User",
            "goal": user.primary_goal or "—",
            "current_weight_lbs": round(user.current_weight_kg * 2.20462, 1) if user.current_weight_kg else None,
            "goal_weight_lbs": round(user.goal_weight_kg * 2.20462, 1) if user.goal_weight_kg else None,
        },
        "targets": {
            "calories": prefs.calorie_target if prefs else None,
            "protein": prefs.protein_target if prefs else None,
        },
        "today": today_data,
        "history": hist_data,
        "weights": weight_data,
    }


@app.get("/api/stats/{token}")
async def get_stats(token: str):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return await _build_stats_for_user(db, user)


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
    --bg: #0f1117; --surface: #1a1d27; --surface2: #22263a;
    --border: #2e3347; --green: #22c55e; --blue: #3b82f6;
    --orange: #f97316; --purple: #a855f7; --red: #ef4444; --yellow: #eab308;
    --text: #f1f5f9; --muted: #94a3b8; --dim: #475569;
  }}
  html, body {{ background: var(--bg); }}
  body {{
    font-family: 'Inter', -apple-system, system-ui, sans-serif;
    background: var(--bg); color: var(--text); min-height: 100vh;
    padding: env(safe-area-inset-top) env(safe-area-inset-right)
             env(safe-area-inset-bottom) env(safe-area-inset-left);
    -webkit-font-smoothing: antialiased;
  }}

  /* HEADER — sticky, compact on mobile */
  header {{
    background: rgba(15, 17, 23, 0.85);
    backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border);
    padding: 12px 16px;
    display: flex; align-items: center; justify-content: space-between;
    position: sticky; top: 0; z-index: 10;
  }}
  .logo {{ font-size: 18px; font-weight: 700; color: var(--green); letter-spacing: -0.5px; }}
  .user-badge {{ display: flex; align-items: center; gap: 8px; }}
  .user-name {{ font-weight: 600; font-size: 14px; }}
  .goal-tag {{
    background: var(--surface2); color: var(--muted); font-size: 11px;
    padding: 4px 9px; border-radius: 20px; border: 1px solid var(--border);
    text-transform: capitalize;
  }}
  .refresh-btn {{
    background: none; border: 1px solid var(--border); color: var(--muted);
    padding: 7px 12px; border-radius: 8px; cursor: pointer; font-size: 12px;
    font-family: inherit; min-height: 36px; min-width: 36px;
  }}
  .refresh-btn:active {{ background: var(--surface2); }}

  main {{ max-width: 920px; margin: 0 auto; padding: 16px 12px 60px; }}

  #loading {{ text-align: center; padding: 60px 20px; color: var(--muted); font-size: 14px; }}
  #content {{ display: none; }}

  .section-title {{
    font-size: 10px; font-weight: 700; color: var(--dim);
    text-transform: uppercase; letter-spacing: 1.2px;
    margin: 24px 4px 10px; display: flex; align-items: center; gap: 8px;
  }}
  .section-title:first-of-type {{ margin-top: 4px; }}
  .section-title .badge-pill {{
    background: var(--surface2); padding: 2px 8px; border-radius: 10px;
    font-size: 9px; letter-spacing: 0.5px; color: var(--muted);
  }}

  /* STAT CARDS */
  .cards {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }}
  @media (min-width: 600px) {{ .cards {{ grid-template-columns: repeat(4, 1fr); }} }}
  .card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 14px;
  }}
  .card-label {{ font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 6px; font-weight: 600; }}
  .card-value {{ font-size: 24px; font-weight: 700; line-height: 1; }}
  .card-sub {{ font-size: 11px; color: var(--muted); margin-top: 4px; }}
  .progress-track {{ background: var(--surface2); border-radius: 999px; height: 5px; margin-top: 10px; overflow: hidden; }}
  .progress-fill {{ height: 100%; border-radius: 999px; transition: width 0.6s ease; }}

  /* AI INSIGHTS */
  .insights-card {{
    background: linear-gradient(180deg, rgba(34,197,94,0.04), rgba(34,197,94,0)) , var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px; padding: 6px 4px;
  }}
  .insight-row {{
    display: grid; grid-template-columns: 28px 1fr; gap: 12px;
    padding: 12px 14px; border-bottom: 1px solid var(--border);
    align-items: flex-start;
  }}
  .insight-row:last-child {{ border-bottom: none; }}
  .insight-icon {{
    font-size: 13px; line-height: 1.5;
    width: 22px; height: 22px;
    background: rgba(34,197,94,.12); color: var(--green);
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
  }}
  .insight-text {{ font-size: 13.5px; line-height: 1.45; color: var(--text); }}
  .insights-loading {{ padding: 18px; color: var(--muted); font-size: 13px; text-align: center; }}
  .insights-empty {{ padding: 18px; color: var(--muted); font-size: 13px; text-align: center; }}

  /* BADGES ROW */
  .status-row {{
    display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap;
  }}
  .badge {{
    display: inline-flex; align-items: center; gap: 4px;
    padding: 6px 10px; border-radius: 8px; font-size: 12px; font-weight: 600;
  }}
  .badge-green {{ background: rgba(34,197,94,.15); color: var(--green); }}
  .badge-gray {{ background: var(--surface2); color: var(--muted); }}
  .badge-blue {{ background: rgba(59,130,246,.15); color: var(--blue); }}

  /* CHARTS */
  .charts {{ display: grid; grid-template-columns: 1fr; gap: 10px; }}
  @media (min-width: 700px) {{ .charts {{ grid-template-columns: 1fr 1fr; }} }}
  .chart-card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 16px;
  }}
  .chart-title {{ font-size: 12px; font-weight: 600; margin-bottom: 12px; color: var(--muted); }}
  .chart-wrap {{ position: relative; height: 160px; }}
  @media (min-width: 700px) {{ .chart-wrap {{ height: 180px; }} }}

  /* LOG CARDS */
  .log-card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; overflow: hidden;
  }}
  .log-row {{
    padding: 12px 14px; border-bottom: 1px solid var(--border);
  }}
  .log-row:last-child {{ border-bottom: none; }}
  .log-name {{ font-size: 14px; font-weight: 500; line-height: 1.3; word-break: break-word; }}
  .log-qty {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}
  .log-macros {{
    display: flex; gap: 12px; font-size: 12px; margin-top: 6px;
    flex-wrap: wrap;
  }}
  .log-macros span {{ color: var(--muted); }}
  .log-macros b {{ color: var(--text); font-weight: 600; }}
  .log-empty {{ padding: 20px 14px; color: var(--muted); font-size: 13px; text-align: center; }}

  /* EXERCISE LOG */
  .ex-row {{
    display: grid; grid-template-columns: 1fr auto; align-items: center;
    padding: 12px 14px; border-bottom: 1px solid var(--border); gap: 12px;
  }}
  .ex-row:last-child {{ border-bottom: none; }}
  .ex-name {{ font-size: 14px; font-weight: 500; word-break: break-word; }}
  .ex-detail {{ font-size: 12px; color: var(--green); font-weight: 600; white-space: nowrap; }}

  /* WORKOUT DOTS */
  .workout-row {{ display: flex; gap: 6px; flex-wrap: wrap; }}
  .workout-dot {{
    width: 26px; height: 26px; border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
    font-size: 10px; font-weight: 600;
  }}

  footer {{ text-align: center; padding: 24px 16px; color: var(--dim); font-size: 11px; }}

  /* Animations */
  @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(4px); }} to {{ opacity: 1; transform: translateY(0); }} }}
  .fade-in {{ animation: fadeIn 0.4s ease; }}
</style>
</head>
<body>
<header>
  <div class="logo">🏋️ Arnie</div>
  <div class="user-badge">
    <span class="user-name" id="user-name"></span>
    <span id="goal-tag" class="goal-tag"></span>
    <button class="refresh-btn" onclick="loadAll()" aria-label="Refresh">↻</button>
  </div>
</header>

<main>
  <div id="loading">Loading your data…</div>
  <div id="content">

    <!-- INSIGHTS (AI-generated) -->
    <div class="section-title">
      ✨ Coach insights
      <span class="badge-pill">AI</span>
    </div>
    <div class="insights-card fade-in" id="insights-card">
      <div class="insights-loading">Analyzing your last 30 days…</div>
    </div>

    <!-- TODAY -->
    <div class="section-title">Today</div>
    <div class="cards">
      <div class="card">
        <div class="card-label">Calories</div>
        <div class="card-value" id="cal-val">—</div>
        <div class="card-sub" id="cal-sub"></div>
        <div class="progress-track"><div class="progress-fill" id="cal-bar" style="background:var(--green)"></div></div>
      </div>
      <div class="card">
        <div class="card-label">Protein</div>
        <div class="card-value" id="pro-val">—</div>
        <div class="card-sub" id="pro-sub"></div>
        <div class="progress-track"><div class="progress-fill" id="pro-bar" style="background:var(--blue)"></div></div>
      </div>
      <div class="card">
        <div class="card-label">Carbs</div>
        <div class="card-value" id="carb-val">—</div>
        <div class="card-sub" id="carb-sub" style="color:var(--orange)">grams</div>
      </div>
      <div class="card">
        <div class="card-label">Fats</div>
        <div class="card-value" id="fat-val">—</div>
        <div class="card-sub" id="fat-sub" style="color:var(--purple)">grams</div>
      </div>
    </div>

    <div class="status-row">
      <span id="workout-badge"></span>
      <span id="cardio-badge"></span>
      <span id="water-badge" class="badge badge-blue" style="display:none"></span>
    </div>

    <!-- CHARTS -->
    <div class="section-title">30-day trends</div>
    <div class="charts">
      <div class="chart-card">
        <div class="chart-title">Calories</div>
        <div class="chart-wrap"><canvas id="calChart"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Weight (lbs)</div>
        <div class="chart-wrap"><canvas id="weightChart"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Protein</div>
        <div class="chart-wrap"><canvas id="proChart"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Workout history</div>
        <div class="chart-wrap" style="height:auto; padding-top:8px">
          <div class="workout-row" id="workout-dots"></div>
        </div>
      </div>
    </div>

    <!-- TODAY'S FOOD LOG -->
    <div class="section-title">Today's food</div>
    <div class="log-card" id="food-log"></div>

    <!-- TODAY'S EXERCISE LOG -->
    <div class="section-title">Today's workouts</div>
    <div class="log-card" id="ex-log"></div>

  </div>
</main>

<footer>Arnie · read-only · auto-refresh 5 min</footer>

<script>
const TOKEN = '{token}';
const STATS_API = '/api/stats/' + TOKEN;
const INSIGHTS_API = '/api/insights/' + TOKEN;
let calChart, weightChart, proChart;

const chartDefaults = {{
  responsive: true,
  maintainAspectRatio: false,
  plugins: {{ legend: {{ display: false }} }},
  scales: {{
    x: {{ grid: {{ color: '#2e3347', display: false }}, ticks: {{ color: '#475569', font: {{ size: 9 }}, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 }} }},
    y: {{ grid: {{ color: '#2e3347' }}, ticks: {{ color: '#475569', font: {{ size: 10 }} }} }},
  }}
}};

function pct(val, target) {{
  if (!target) return 0;
  return Math.min(100, Math.round(val / target * 100));
}}
function fmt(n) {{ return n != null ? n.toLocaleString() : '—'; }}

async function loadStats() {{
  const r = await fetch(STATS_API);
  if (!r.ok) throw new Error('stats failed');
  return r.json();
}}

async function loadInsights() {{
  try {{
    const r = await fetch(INSIGHTS_API);
    if (!r.ok) return [];
    const d = await r.json();
    return d.insights || [];
  }} catch(e) {{ return []; }}
}}

async function loadAll() {{
  try {{
    const stats = await loadStats();
    renderStats(stats);
    document.getElementById('loading').style.display = 'none';
    document.getElementById('content').style.display = 'block';
    // Load insights in background so dashboard doesn't wait
    loadInsights().then(renderInsights);
  }} catch(e) {{
    document.getElementById('loading').textContent = 'Failed to load — pull to refresh.';
  }}
}}

function renderInsights(insights) {{
  const el = document.getElementById('insights-card');
  if (!insights || insights.length === 0) {{
    el.innerHTML = '<div class="insights-empty">Not enough data yet — keep logging and check back tomorrow.</div>';
    return;
  }}
  el.innerHTML = insights.map(text => `
    <div class="insight-row fade-in">
      <div class="insight-icon">▸</div>
      <div class="insight-text">${{escapeHtml(text)}}</div>
    </div>
  `).join('');
}}

function escapeHtml(s) {{
  return String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
}}

function renderStats(d) {{
  document.getElementById('user-name').textContent = d.user.name;
  document.getElementById('goal-tag').textContent = d.user.goal;

  const t = d.today || {{}};
  const targets = d.targets || {{}};

  const calPct = pct(t.calories, targets.calories);
  const proPct = pct(t.protein, targets.protein);
  document.getElementById('cal-val').textContent = fmt(t.calories);
  document.getElementById('cal-sub').textContent = targets.calories ? `/ ${{targets.calories}} (${{calPct}}%)` : 'kcal';
  document.getElementById('cal-bar').style.width = calPct + '%';
  document.getElementById('pro-val').textContent = (t.protein ?? '—') + (t.protein != null ? 'g' : '');
  document.getElementById('pro-sub').textContent = targets.protein ? `/ ${{targets.protein}}g (${{proPct}}%)` : 'grams';
  document.getElementById('pro-bar').style.width = proPct + '%';
  document.getElementById('carb-val').textContent = (t.carbs ?? '—') + (t.carbs != null ? 'g' : '');
  document.getElementById('fat-val').textContent = (t.fats ?? '—') + (t.fats != null ? 'g' : '');

  const wb = document.getElementById('workout-badge');
  wb.className = 'badge ' + (t.workout_completed ? 'badge-green' : 'badge-gray');
  wb.textContent = t.workout_completed ? '💪 Workout' : '⬜ No workout';
  const cb = document.getElementById('cardio-badge');
  cb.className = 'badge ' + (t.cardio_completed ? 'badge-green' : 'badge-gray');
  cb.textContent = t.cardio_completed ? '🏃 Cardio' : '⬜ No cardio';
  const wat = document.getElementById('water-badge');
  if (t.water_ml > 0) {{
    wat.style.display = 'inline-flex';
    wat.textContent = '💧 ' + (t.water_ml >= 1000 ? (t.water_ml/1000).toFixed(1) + 'L' : t.water_ml + 'ml');
  }} else {{ wat.style.display = 'none'; }}

  const hist = d.history || [];
  const labels = hist.map(h => h.date.slice(5));
  const calData = hist.map(h => h.calories);
  const proData = hist.map(h => h.protein);

  if (calChart) calChart.destroy();
  calChart = new Chart(document.getElementById('calChart'), {{
    type: 'bar',
    data: {{
      labels,
      datasets: [{{
        data: calData,
        backgroundColor: calData.map(v => targets.calories && v > targets.calories ? 'rgba(239,68,68,.7)' : 'rgba(34,197,94,.7)'),
        borderRadius: 3,
      }}]
    }},
    options: {{
      ...chartDefaults,
      scales: {{ ...chartDefaults.scales, y: {{ ...chartDefaults.scales.y, beginAtZero: true }} }}
    }}
  }});
  if (targets.calories) {{
    calChart.data.datasets.push({{
      type: 'line', data: Array(labels.length).fill(targets.calories),
      borderColor: 'rgba(255,255,255,.25)', borderDash: [4,4], borderWidth: 1,
      pointRadius: 0, fill: false
    }});
    calChart.update();
  }}

  if (weightChart) weightChart.destroy();
  const wData = d.weights || [];
  weightChart = new Chart(document.getElementById('weightChart'), {{
    type: 'line',
    data: {{
      labels: wData.map(w => w.date.slice(5)),
      datasets: [{{
        data: wData.map(w => w.lbs),
        borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,.1)',
        borderWidth: 2, pointRadius: 2.5, pointBackgroundColor: '#3b82f6', fill: true, tension: 0.3
      }}]
    }},
    options: {{ ...chartDefaults, scales: {{ ...chartDefaults.scales, y: {{ ...chartDefaults.scales.y, beginAtZero: false }} }} }}
  }});
  if (d.user.goal_weight_lbs && wData.length) {{
    weightChart.data.datasets.push({{
      type: 'line', data: Array(wData.length).fill(d.user.goal_weight_lbs),
      borderColor: 'rgba(34,197,94,.4)', borderDash: [4,4], borderWidth: 1,
      pointRadius: 0, fill: false
    }});
    weightChart.update();
  }}

  if (proChart) proChart.destroy();
  proChart = new Chart(document.getElementById('proChart'), {{
    type: 'line',
    data: {{
      labels,
      datasets: [{{
        data: proData,
        borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,.1)',
        borderWidth: 2, pointRadius: 2.5, pointBackgroundColor: '#3b82f6', fill: true, tension: 0.3
      }}]
    }},
    options: {{ ...chartDefaults, scales: {{ ...chartDefaults.scales, y: {{ ...chartDefaults.scales.y, beginAtZero: true }} }} }}
  }});
  if (targets.protein) {{
    proChart.data.datasets.push({{
      type: 'line', data: Array(labels.length).fill(targets.protein),
      borderColor: 'rgba(255,255,255,.25)', borderDash: [4,4], borderWidth: 1,
      pointRadius: 0, fill: false
    }});
    proChart.update();
  }}

  const dotsEl = document.getElementById('workout-dots');
  dotsEl.innerHTML = '';
  hist.slice(-30).forEach(h => {{
    const dot = document.createElement('div');
    dot.className = 'workout-dot';
    dot.title = h.date;
    if (h.workout) {{
      dot.style.background = 'rgba(34,197,94,.2)';
      dot.style.color = '#22c55e';
      dot.textContent = '💪';
    }} else {{
      dot.style.background = '#1a1d27';
      dot.style.color = '#475569';
      dot.textContent = h.date.slice(8);
    }}
    dotsEl.appendChild(dot);
  }});

  const foodEl = document.getElementById('food-log');
  if (!t.food_entries || t.food_entries.length === 0) {{
    foodEl.innerHTML = '<div class="log-empty">Nothing logged today yet</div>';
  }} else {{
    foodEl.innerHTML = t.food_entries.map(f => `
      <div class="log-row">
        <div class="log-name">${{escapeHtml(f.name)}}${{f.estimated ? ' <span style="color:var(--dim);font-size:10px;font-weight:400">~est</span>' : ''}}</div>
        <div class="log-qty">${{escapeHtml(f.quantity)}}</div>
        <div class="log-macros">
          <span><b>${{f.calories}}</b> cal</span>
          <span><b>${{f.protein}}g</b> P</span>
          <span><b>${{f.carbs}}g</b> C</span>
          <span><b>${{f.fats}}g</b> F</span>
        </div>
      </div>
    `).join('');
  }}

  const exEl = document.getElementById('ex-log');
  if (!t.exercise_entries || t.exercise_entries.length === 0) {{
    exEl.innerHTML = '<div class="log-empty">No workouts logged today</div>';
  }} else {{
    exEl.innerHTML = t.exercise_entries.map(e => {{
      let detail = '';
      if (e.sets && e.reps) detail = `${{e.sets}}×${{e.reps}}${{e.weight ? ' @ ' + e.weight + 'lb' : ''}}`;
      else if (e.duration_minutes) detail = `${{e.duration_minutes}} min`;
      return `<div class="ex-row"><div class="ex-name">${{escapeHtml(e.name)}}</div><div class="ex-detail">${{detail}}</div></div>`;
    }}).join('');
  }}
}}

loadAll();
setInterval(loadAll, 5 * 60 * 1000);
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
