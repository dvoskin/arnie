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

@app.get("/api/stats/{token}")
async def get_stats(token: str):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        prefs = user.preferences
        today_log = await get_today_log(db, user.id, user.timezone or "UTC")
        history = await get_recent_logs(db, user.id, days=30)
        weights = await get_recent_weights(db, user.id, days=60)

        # Today
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

        # 30-day history (closed days only)
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

        # Weight trend
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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Arnie Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg: #0f1117; --surface: #1a1d27; --surface2: #22263a;
    --border: #2e3347; --green: #22c55e; --blue: #3b82f6;
    --orange: #f97316; --purple: #a855f7; --red: #ef4444;
    --text: #f1f5f9; --muted: #94a3b8; --dim: #475569;
  }}
  body {{ font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; padding: 0; }}

  header {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 24px;
            display: flex; align-items: center; justify-content: space-between; }}
  .logo {{ font-size: 20px; font-weight: 700; color: var(--green); letter-spacing: -0.5px; }}
  .user-badge {{ display: flex; align-items: center; gap: 10px; }}
  .goal-tag {{ background: var(--surface2); color: var(--muted); font-size: 12px;
               padding: 4px 10px; border-radius: 20px; border: 1px solid var(--border); text-transform: capitalize; }}
  .refresh-btn {{ background: none; border: 1px solid var(--border); color: var(--muted);
                  padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; font-family: inherit; }}
  .refresh-btn:hover {{ background: var(--surface2); color: var(--text); }}

  main {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px; }}

  /* Loading state */
  #loading {{ text-align: center; padding: 80px; color: var(--muted); }}
  #content {{ display: none; }}

  /* Section heading */
  .section-title {{ font-size: 11px; font-weight: 600; color: var(--dim);
                    text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; margin-top: 32px; }}
  .section-title:first-child {{ margin-top: 0; }}

  /* Stat cards */
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
  @media (max-width: 700px) {{ .cards {{ grid-template-columns: repeat(2, 1fr); }} }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }}
  .card-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
  .card-value {{ font-size: 26px; font-weight: 700; line-height: 1; }}
  .card-sub {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
  .progress-track {{ background: var(--surface2); border-radius: 4px; height: 5px; margin-top: 10px; overflow: hidden; }}
  .progress-fill {{ height: 100%; border-radius: 4px; transition: width 0.6s ease; }}

  /* Charts */
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 700px) {{ .charts {{ grid-template-columns: 1fr; }} }}
  .chart-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
  .chart-title {{ font-size: 13px; font-weight: 600; margin-bottom: 16px; color: var(--muted); }}
  .chart-wrap {{ position: relative; height: 180px; }}

  /* Food log */
  .log-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
  .log-row {{ display: grid; grid-template-columns: 1fr auto; align-items: center;
              padding: 12px 16px; border-bottom: 1px solid var(--border); gap: 16px; }}
  .log-row:last-child {{ border-bottom: none; }}
  .log-name {{ font-size: 14px; font-weight: 500; }}
  .log-qty {{ font-size: 12px; color: var(--muted); }}
  .log-macros {{ display: flex; gap: 10px; font-size: 12px; }}
  .log-macros span {{ color: var(--muted); }}
  .log-macros b {{ color: var(--text); }}
  .log-empty {{ padding: 24px 16px; color: var(--muted); font-size: 14px; text-align: center; }}

  /* Exercise log */
  .ex-row {{ display: grid; grid-template-columns: 1fr auto; align-items: center;
             padding: 12px 16px; border-bottom: 1px solid var(--border); gap: 16px; }}
  .ex-row:last-child {{ border-bottom: none; }}
  .ex-name {{ font-size: 14px; font-weight: 500; }}
  .ex-detail {{ font-size: 12px; color: var(--green); font-weight: 600; }}

  /* Status badges */
  .badge {{ display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
  .badge-green {{ background: rgba(34,197,94,.15); color: var(--green); }}
  .badge-gray {{ background: var(--surface2); color: var(--muted); }}

  /* Workout dots */
  .workout-row {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 4px; }}
  .workout-dot {{ width: 28px; height: 28px; border-radius: 6px; display: flex; align-items: center;
                  justify-content: center; font-size: 11px; font-weight: 600; }}

  footer {{ text-align: center; padding: 32px 16px; color: var(--dim); font-size: 12px; }}
</style>
</head>
<body>
<header>
  <div class="logo">🏋️ Arnie</div>
  <div class="user-badge">
    <span id="user-name" style="font-weight:600"></span>
    <span id="goal-tag" class="goal-tag"></span>
    <button class="refresh-btn" onclick="load()">↻ Refresh</button>
  </div>
</header>

<main>
  <div id="loading">Loading your data…</div>
  <div id="content">

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
        <div class="card-sub"></div>
        <div class="progress-track"><div class="progress-fill" id="carb-bar" style="background:var(--orange); width:0%"></div></div>
      </div>
      <div class="card">
        <div class="card-label">Fats</div>
        <div class="card-value" id="fat-val">—</div>
        <div class="card-sub"></div>
        <div class="progress-track"><div class="progress-fill" id="fat-bar" style="background:var(--purple); width:0%"></div></div>
      </div>
    </div>

    <!-- WORKOUT STATUS -->
    <div style="display:flex; gap:10px; margin-top:12px;">
      <span id="workout-badge"></span>
      <span id="cardio-badge"></span>
      <span id="water-badge" style="font-size:13px; color:var(--muted)"></span>
    </div>

    <!-- CHARTS -->
    <div class="section-title">30-Day Trends</div>
    <div class="charts">
      <div class="chart-card">
        <div class="chart-title">Calories / day</div>
        <div class="chart-wrap"><canvas id="calChart"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Weight (lbs)</div>
        <div class="chart-wrap"><canvas id="weightChart"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Protein / day</div>
        <div class="chart-wrap"><canvas id="proChart"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Workout days</div>
        <div class="chart-wrap" id="workout-dots-wrap">
          <div class="workout-row" id="workout-dots"></div>
        </div>
      </div>
    </div>

    <!-- TODAY'S FOOD LOG -->
    <div class="section-title">Today's food log</div>
    <div class="log-card" id="food-log"></div>

    <!-- TODAY'S EXERCISE LOG -->
    <div class="section-title">Today's workouts</div>
    <div class="log-card" id="ex-log"></div>

  </div><!-- /content -->
</main>

<footer>Arnie · Read-only view · Updates every 5 minutes</footer>

<script>
const TOKEN = '{token}';
const API = '/api/stats/' + TOKEN;
let calChart, weightChart, proChart;

const chartDefaults = {{
  responsive: true,
  maintainAspectRatio: false,
  plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{}} }} }},
  scales: {{
    x: {{ grid: {{ color: '#2e3347' }}, ticks: {{ color: '#475569', font: {{ size: 10 }} }} }},
    y: {{ grid: {{ color: '#2e3347' }}, ticks: {{ color: '#475569', font: {{ size: 10 }} }} }},
  }}
}};

function pct(val, target) {{
  if (!target) return 0;
  return Math.min(100, Math.round(val / target * 100));
}}

function fmt(n) {{ return n != null ? n.toLocaleString() : '—'; }}

async function load() {{
  try {{
    const r = await fetch(API);
    if (!r.ok) throw new Error('bad response');
    const d = await r.json();
    render(d);
    document.getElementById('loading').style.display = 'none';
    document.getElementById('content').style.display = 'block';
  }} catch(e) {{
    document.getElementById('loading').textContent = 'Failed to load — try refreshing.';
  }}
}}

function render(d) {{
  // Header
  document.getElementById('user-name').textContent = d.user.name;
  document.getElementById('goal-tag').textContent = d.user.goal;

  const t = d.today || {{}};
  const targets = d.targets || {{}};

  // Stat cards
  const calPct = pct(t.calories, targets.calories);
  const proPct = pct(t.protein, targets.protein);
  document.getElementById('cal-val').textContent = fmt(t.calories);
  document.getElementById('cal-sub').textContent = targets.calories ? `/ ${{targets.calories}} kcal (${{calPct}}%)` : 'kcal';
  document.getElementById('cal-bar').style.width = calPct + '%';
  document.getElementById('pro-val').textContent = (t.protein ?? '—') + (t.protein != null ? 'g' : '');
  document.getElementById('pro-sub').textContent = targets.protein ? `/ ${{targets.protein}}g (${{proPct}}%)` : 'grams';
  document.getElementById('pro-bar').style.width = proPct + '%';
  document.getElementById('carb-val').textContent = (t.carbs ?? '—') + (t.carbs != null ? 'g' : '');
  document.getElementById('fat-val').textContent = (t.fats ?? '—') + (t.fats != null ? 'g' : '');

  // Workout badges
  const wb = document.getElementById('workout-badge');
  wb.className = 'badge ' + (t.workout_completed ? 'badge-green' : 'badge-gray');
  wb.textContent = t.workout_completed ? '💪 Workout done' : '⬜ No workout yet';
  const cb = document.getElementById('cardio-badge');
  cb.className = 'badge ' + (t.cardio_completed ? 'badge-green' : 'badge-gray');
  cb.textContent = t.cardio_completed ? '🏃 Cardio done' : '⬜ No cardio';
  if (t.water_ml > 0) {{
    document.getElementById('water-badge').textContent = '💧 ' + (t.water_ml >= 1000 ? (t.water_ml/1000).toFixed(1) + 'L' : t.water_ml + 'ml') + ' water';
  }}

  // Charts
  const hist = d.history || [];
  const labels = hist.map(h => h.date.slice(5)); // MM-DD
  const calData = hist.map(h => h.calories);
  const proData = hist.map(h => h.protein);

  // Calorie bar chart
  if (calChart) calChart.destroy();
  calChart = new Chart(document.getElementById('calChart'), {{
    type: 'bar',
    data: {{
      labels,
      datasets: [{{
        data: calData,
        backgroundColor: calData.map(v => targets.calories && v > targets.calories ? 'rgba(239,68,68,.7)' : 'rgba(34,197,94,.7)'),
        borderRadius: 4,
      }}]
    }},
    options: {{
      ...chartDefaults,
      plugins: {{
        ...chartDefaults.plugins,
        annotation: {{}}
      }},
      scales: {{
        ...chartDefaults.scales,
        y: {{ ...chartDefaults.scales.y, beginAtZero: true }}
      }}
    }}
  }});
  if (targets.calories) {{
    calChart.data.datasets.push({{
      type: 'line', data: Array(labels.length).fill(targets.calories),
      borderColor: 'rgba(255,255,255,.2)', borderDash: [4,4], borderWidth: 1,
      pointRadius: 0, fill: false, label: 'Target'
    }});
    calChart.update();
  }}

  // Weight line chart
  if (weightChart) weightChart.destroy();
  const wData = d.weights || [];
  weightChart = new Chart(document.getElementById('weightChart'), {{
    type: 'line',
    data: {{
      labels: wData.map(w => w.date.slice(5)),
      datasets: [{{
        data: wData.map(w => w.lbs),
        borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,.1)',
        borderWidth: 2, pointRadius: 3, pointBackgroundColor: '#3b82f6', fill: true, tension: 0.3
      }}]
    }},
    options: {{
      ...chartDefaults,
      scales: {{ ...chartDefaults.scales, y: {{ ...chartDefaults.scales.y, beginAtZero: false }} }}
    }}
  }});
  if (d.user.goal_weight_lbs && wData.length) {{
    weightChart.data.datasets.push({{
      type: 'line', data: Array(wData.length).fill(d.user.goal_weight_lbs),
      borderColor: 'rgba(34,197,94,.4)', borderDash: [4,4], borderWidth: 1,
      pointRadius: 0, fill: false, label: 'Goal'
    }});
    weightChart.update();
  }}

  // Protein line chart
  if (proChart) proChart.destroy();
  proChart = new Chart(document.getElementById('proChart'), {{
    type: 'line',
    data: {{
      labels,
      datasets: [{{
        data: proData,
        borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,.1)',
        borderWidth: 2, pointRadius: 3, pointBackgroundColor: '#3b82f6', fill: true, tension: 0.3
      }}]
    }},
    options: {{
      ...chartDefaults,
      scales: {{ ...chartDefaults.scales, y: {{ ...chartDefaults.scales.y, beginAtZero: true }} }}
    }}
  }});
  if (targets.protein) {{
    proChart.data.datasets.push({{
      type: 'line', data: Array(labels.length).fill(targets.protein),
      borderColor: 'rgba(255,255,255,.2)', borderDash: [4,4], borderWidth: 1,
      pointRadius: 0, fill: false
    }});
    proChart.update();
  }}

  // Workout dots (last 30 days)
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
      dot.textContent = h.date.slice(8); // day number
      dot.style.fontSize = '10px';
    }}
    dotsEl.appendChild(dot);
  }});

  // Food log
  const foodEl = document.getElementById('food-log');
  if (!t.food_entries || t.food_entries.length === 0) {{
    foodEl.innerHTML = '<div class="log-empty">Nothing logged today yet</div>';
  }} else {{
    foodEl.innerHTML = t.food_entries.map(f => `
      <div class="log-row">
        <div>
          <div class="log-name">${{f.name}}${{f.estimated ? ' <span style="color:var(--dim);font-size:11px">~est</span>' : ''}}</div>
          <div class="log-qty">${{f.quantity}}</div>
        </div>
        <div class="log-macros">
          <span><b>${{f.calories}}</b> cal</span>
          <span><b>${{f.protein}}g</b> P</span>
          <span><b>${{f.carbs}}g</b> C</span>
          <span><b>${{f.fats}}g</b> F</span>
        </div>
      </div>
    `).join('');
  }}

  // Exercise log
  const exEl = document.getElementById('ex-log');
  if (!t.exercise_entries || t.exercise_entries.length === 0) {{
    exEl.innerHTML = '<div class="log-empty">No workouts logged today</div>';
  }} else {{
    exEl.innerHTML = t.exercise_entries.map(e => {{
      let detail = '';
      if (e.sets && e.reps) detail = `${{e.sets}}×${{e.reps}}${{e.weight ? ' @ ' + e.weight + ' lbs' : ''}}`;
      else if (e.duration_minutes) detail = `${{e.duration_minutes}} min`;
      return `
        <div class="ex-row">
          <div class="ex-name">${{e.name}}</div>
          <div class="ex-detail">${{detail}}</div>
        </div>
      `;
    }}).join('');
  }}
}}

load();
setInterval(load, 5 * 60 * 1000); // refresh every 5 min
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
