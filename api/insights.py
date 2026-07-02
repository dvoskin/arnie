"""
AI-generated dashboard insights.
Calls Claude with a compact data summary, returns 3-5 short coaching observations.
Cached per-user for 1 hour to keep cost down.
"""
import asyncio
import json
import logging
import time
from statistics import mean
from typing import List, Optional

logger = logging.getLogger(__name__)

# In-memory cache: {user_id: (timestamp, insights_list)}
_CACHE: dict = {}
_TTL = 10800  # 3 hours — analysis stays stable until it auto-refreshes (or a manual refresh forces it)

# Per-key guard so a burst of requests on a stale briefing kicks off only ONE
# background regeneration, not one per request.
_briefing_refreshing: set = set()


def invalidate_briefing(user_id: int) -> None:
    """Drop a user's cached briefing so the next open regenerates with fresh
    context. Called after a chat turn so a plan the client JUST stated ('with
    family tonight') is reflected immediately, not up to 3h later. Cheap + safe:
    iOS paints its own last-good brief instantly and swaps in the fresh one, so a
    cold regen never blocks the UI."""
    _CACHE.pop((user_id, "__briefing__"), None)


def _build_summary(stats: dict) -> str:
    """Compact text summary focused on the viewed day for the LLM."""
    user = stats.get("user", {})
    targets = stats.get("targets") or {}
    today = stats.get("today") or {}
    history = stats.get("history") or []
    weights = stats.get("weights") or []
    health = stats.get("health") or []
    viewing_date = stats.get("viewing_date", "today")

    # ── Day being analysed ──────────────────────────────────
    cal = today.get("calories") or 0
    pro = today.get("protein") or 0
    carb = today.get("carbs") or 0
    fat = today.get("fats") or 0
    tgt_cal = targets.get("calories") or 0
    tgt_pro = targets.get("protein") or 0
    has_food = bool(today.get("food_entries"))
    has_workout = today.get("workout_completed") or bool(today.get("exercise_entries"))

    day_lines = [
        f"DATE BEING ANALYSED: {viewing_date}",
        f"Targets: {tgt_cal} cal / {tgt_pro}g protein",
        "",
        "FOOD & MACROS FOR THIS DAY:",
    ]
    if has_food:
        pct_cal = f"{round(cal/tgt_cal*100)}% of target" if tgt_cal else ""
        pct_pro = f"{round(pro/tgt_pro*100)}% of target" if tgt_pro else ""
        day_lines.append(f"  Calories: {cal} cal {pct_cal}")
        day_lines.append(f"  Protein:  {pro}g {pct_pro}")
        day_lines.append(f"  Carbs: {carb}g  |  Fats: {fat}g")
        # List food items
        for fe in (today.get("food_entries") or [])[:8]:
            day_lines.append(f"  - {fe.get('name','')} {fe.get('quantity','')} ({fe.get('calories',0)} cal, {fe.get('protein',0)}g P)")
    else:
        day_lines.append("  No food logged for this day.")

    day_lines.append("")
    day_lines.append("WORKOUTS FOR THIS DAY:")
    exercises = today.get("exercise_entries") or []
    if exercises:
        for ex in exercises[:6]:
            sets_str = f"{ex.get('sets','?')}×{ex.get('reps','?')}" if ex.get('sets') else ""
            wt_str = f"@ {ex.get('weight','')}lb" if ex.get('weight') else ""
            dur_str = f"{ex.get('duration_minutes','')}min" if ex.get('duration_minutes') else ""
            day_lines.append(f"  - {ex.get('name','')} {sets_str} {wt_str} {dur_str}".strip())
    elif has_workout:
        day_lines.append("  Workout completed (no exercise details)")
    else:
        day_lines.append("  No workout logged for this day.")

    # ── Wearable data for this day ──────────────────────────
    snap = next((h for h in health if h.get("date") == viewing_date), None)
    if not snap and health:
        snap = health[0]
    if snap and snap.get("source") == "whoop":
        day_lines.append("")
        day_lines.append("WEARABLE (Whoop):")
        if snap.get("recovery_score") is not None:
            day_lines.append(f"  Recovery: {snap['recovery_score']}%")
        if snap.get("strain") is not None:
            day_lines.append(f"  Strain: {snap['strain']:.1f}/21")
        if snap.get("hrv") is not None:
            day_lines.append(f"  HRV: {snap['hrv']:.0f}ms")
        if snap.get("sleep_hours") is not None:
            day_lines.append(f"  Sleep: {snap['sleep_hours']:.1f}h")
        if snap.get("resting_hr") is not None:
            day_lines.append(f"  RHR: {snap['resting_hr']:.0f}bpm")

    # ── Recent context (last 7 logged days) for pacing ─────
    # Past days only — the day being viewed (or today) is still in flight.
    past = [h for h in history if h.get("date") and h.get("date") < viewing_date]
    if past:
        day_lines.append("")
        day_lines.append("RECENT LOGGED DAYS (for pacing context, last 7):")
        for h in past[-7:]:
            day_lines.append(
                f"  {h['date']}: {h['calories']} cal, {h['protein']}g P, "
                f"workout={'✓' if h.get('workout') else '✗'}"
            )

    # Current weight context
    if weights:
        latest_w = weights[-1]
        goal_w = user.get("goal_weight_lbs")
        day_lines.append("")
        if goal_w:
            diff = round(abs(latest_w["lbs"] - goal_w), 1)
            day_lines.append(f"WEIGHT: {latest_w['lbs']}lb (goal {goal_w}lb — {diff}lb to go)")
        else:
            day_lines.append(f"WEIGHT: {latest_w['lbs']}lb")

    return "\n".join(day_lines)


async def generate_insights(stats: dict) -> List[str]:
    """Call Claude to produce 3-5 short coaching insights."""
    from core.llm import _get_anthropic, DEFAULT_MODEL, ANTHROPIC_API_KEY

    if not ANTHROPIC_API_KEY():
        return []

    summary = _build_summary(stats)
    prompt = f"""You are Arnie, a direct fitness coach analysing a specific day's data. Write 3 to 5 SHORT coaching observations — each one sentence, 10-22 words.

STRICT RULES:
- Analyse ONLY the day shown (food logged, workouts done, Whoop data, pacing vs targets)
- DO NOT comment on overall logging habits, how many days they've tracked, or data gaps
- DO NOT project timelines from missing data or lecture about consistency
- If a day has limited data, comment on what IS there — or note one specific gap without dwelling on it
- Reference actual numbers: "192g protein hit the target" not "protein looks good"
- Use recent days only for direct pacing comparison ("down from yesterday's 2200 cal")
- If Whoop data exists, factor recovery into workout/nutrition recommendations

GOOD examples:
- "2063 cal and 192g protein — calories at target, protein solid for muscle preservation"
- "Recovery at 71% with Strain 14.2 — moderate day done right, sleep well tonight"
- "Grilled chicken bowl and protein bar covered 78g protein by lunch — strong start"
- "Skipped workout but hit the calorie floor — one rest day won't stall the cut"

BAD (never write these):
- "Only 1 logged day in 30 — can't coach without data" (meta-commentary)
- "Zero tracking history makes projections impossible" (irrelevant)
- "Consistency is key to your cut" (filler)

Return ONLY a valid JSON array of strings. No prose.

DATA:
{summary}
"""

    try:
        client = _get_anthropic()
        response = await client.messages.create(
            model=DEFAULT_MODEL(),
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Strip markdown code fences if Claude wrapped the JSON
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if text.startswith("json"):
            text = text[4:].strip()

        insights = json.loads(text)
        if isinstance(insights, list):
            return [str(s) for s in insights if s][:4]
    except Exception as e:
        logger.error(f"Insight generation failed: {e}")

    return []


def _build_week_summary(stats: dict) -> str:
    """Compact 7-day rollup for the WEEKLY analysis — averages, consistency,
    weight movement, and Whoop weekly averages."""
    user = stats.get("user", {})
    targets = stats.get("targets") or {}
    history = stats.get("history") or []
    weights = stats.get("weights") or []
    health = stats.get("health") or []
    tgt_cal = targets.get("calories") or 0
    tgt_pro = targets.get("protein") or 0

    # Past days only — today's totals are still moving until bedtime. The
    # history list is already sorted by date ascending; the last entry is today
    # (or empty if the user hasn't logged today). Drop today via date comparison.
    from datetime import date as _date
    today_iso = _date.today().isoformat()
    past = [h for h in history if h.get("date") and h["date"] < today_iso]
    last7 = past[-7:]
    lines = ["ANALYSIS PERIOD: last 7 logged days (analyse WEEKLY trends, not one day)",
             f"Daily targets: {tgt_cal} cal / {tgt_pro}g protein", ""]

    if last7:
        cals = [h.get("calories") or 0 for h in last7]
        pros = [h.get("protein") or 0 for h in last7]
        workouts = sum(1 for h in last7 if h.get("workout"))
        avg_cal = round(mean(cals)) if cals else 0
        avg_pro = round(mean(pros)) if pros else 0
        over = sum(1 for c in cals if tgt_cal and c > tgt_cal)
        under = sum(1 for c in cals if tgt_cal and c < tgt_cal * 0.7)
        lines.append("NUTRITION (7-day):")
        lines.append(f"  Avg calories: {avg_cal}/day"
                     + (f" ({round(avg_cal / tgt_cal * 100)}% of target)" if tgt_cal else ""))
        lines.append(f"  Avg protein: {avg_pro}g/day"
                     + (f" ({round(avg_pro / tgt_pro * 100)}% of target)" if tgt_pro else ""))
        lines.append(f"  Days logged: {len(last7)}/7  |  over target: {over} day(s)  |  well under (<70%): {under} day(s)")
        lines.append(f"  Workouts completed: {workouts}")
        lines.append("  Daily calories: " + ", ".join(str(c) for c in cals))
    else:
        lines.append("No prior days logged in the past week.")

    if len(weights) >= 2:
        recent = weights[-7:] if len(weights) >= 7 else weights
        first, last = recent[0], recent[-1]
        delta = round(last["lbs"] - first["lbs"], 1)
        goal_w = user.get("goal_weight_lbs")
        wl = f"WEIGHT (7-day): {first['lbs']}lb -> {last['lbs']}lb ({'+' if delta >= 0 else ''}{delta}lb)"
        if goal_w:
            wl += f"  |  goal {goal_w}lb ({round(abs(last['lbs'] - goal_w), 1)}lb to go)"
        lines += ["", wl]

    wsnaps = [h for h in health if h.get("source") == "whoop"][-7:]
    if wsnaps:
        def _avg(key):
            vals = [h.get(key) for h in wsnaps if h.get(key) is not None]
            return mean(vals) if vals else None
        rec, strn, slp, hrv = _avg("recovery_score"), _avg("strain"), _avg("sleep_hours"), _avg("hrv")
        wl = ["", f"WEARABLE (Whoop, {len(wsnaps)}-day avg):"]
        if rec is not None: wl.append(f"  Recovery: {rec:.0f}%")
        if strn is not None: wl.append(f"  Strain: {strn:.1f}/21")
        if slp is not None: wl.append(f"  Sleep: {slp:.1f}h/night")
        if hrv is not None: wl.append(f"  HRV: {hrv:.0f}ms")
        lines += wl

    return "\n".join(lines)


async def generate_week_insights(stats: dict) -> List[str]:
    """Call Claude for 3-4 WEEKLY trend observations consolidating the week's data."""
    from core.llm import _get_anthropic, DEFAULT_MODEL, ANTHROPIC_API_KEY

    if not ANTHROPIC_API_KEY():
        return []

    summary = _build_week_summary(stats)
    prompt = f"""You are Arnie, a direct fitness coach reviewing a client's WEEKLY data. Write 3 to 4 SHORT coaching observations — each ONE sentence, 10-22 words — that consolidate the week into a data-driven read.

STRICT RULES:
- Analyse the WEEK as a whole: averages, consistency, weight movement, and Whoop recovery/strain/sleep patterns
- Reference real weekly numbers ("averaged 2240 cal, ~140 over target across 6 logged days")
- Connect the dots: tie nutrition adherence to weight movement, recovery to training load
- Make ONE of them a forward-looking call for next week
- Do NOT lecture about how many days were tracked; work with what's there. No greetings, no filler.

GOOD examples:
- "Averaged 2180 cal and 195g protein over 6 days — deficit held, protein dialed in for the cut"
- "Weight down 0.8lb on a 78% recovery average — sustainable pace, sleep is doing its job"
- "Three of seven days ran 300+ over target, all weekends — that's the lever for next week"

Return ONLY a valid JSON array of 3-4 strings. No prose.

DATA:
{summary}
"""
    try:
        client = _get_anthropic()
        response = await client.messages.create(
            model=DEFAULT_MODEL(),
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if text.startswith("json"):
            text = text[4:].strip()
        result = json.loads(text)
        if isinstance(result, list):
            return [str(s) for s in result if s][:4]
    except Exception as e:
        logger.error(f"Week insight generation failed: {e}")

    return []



async def generate_chat_analysis(stats: dict) -> List[str]:
    """Richer coaching analysis for the /ai bot command — 3-5 items, each 2-3 sentences."""
    from core.llm import _get_anthropic, DEFAULT_MODEL, ANTHROPIC_API_KEY

    if not ANTHROPIC_API_KEY():
        return []

    summary = _build_summary(stats)
    prompt = f"""You are Arnie, a direct fitness and nutrition coach. Give a sharp coaching analysis in 75-125 words total — no more.

Write 3-4 punchy observations covering calories, protein, training, and trends. Each one is 1-2 sentences max. Reference real numbers. No fluff, no greetings, no sign-off.

Return ONLY a valid JSON array of strings, one string per observation. No prose before or after.

DATA:
{summary}
"""

    try:
        client = _get_anthropic()
        response = await client.messages.create(
            model=DEFAULT_MODEL(),
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if text.startswith("json"):
            text = text[4:].strip()
        result = json.loads(text)
        if isinstance(result, list):
            return [str(s) for s in result if s][:5]
    except Exception as e:
        logger.error(f"Chat analysis generation failed: {e}")

    return []


# ─────────────────────────────────────────────────────────────────────────────
# Daily BRIEFING — the structured, prioritized home-screen briefing. Unlike the
# flat insight bullets, this is the full "coach already reviewed everything"
# package: a hero status, ONE focus, narrative feed cards (prioritized), and a
# conversation starter. The coach does the thinking; the user does the doing.
# ─────────────────────────────────────────────────────────────────────────────

def _build_briefing_summary(stats: dict) -> str:
    """Organized raw material for the briefing LLM — recent daily history with
    weekday labels (so it can see weekend patterns + streaks), the weight series
    (milestones + pace), and recent wearable data. We give it the data; it finds
    the meaning."""
    from datetime import date as _date, datetime as _dt
    user = stats.get("user", {})
    targets = stats.get("targets") or {}
    today = stats.get("today") or {}
    history = stats.get("history") or []
    weights = stats.get("weights") or []
    health = stats.get("health") or []
    tgt_cal = targets.get("calories") or 0
    tgt_pro = targets.get("protein") or 0
    today_iso = _date.today().isoformat()

    L = [f"CLIENT: {user.get('name','')} — goal: {user.get('goal','')}"]
    cw, gw = user.get("current_weight_lbs"), user.get("goal_weight_lbs")
    if cw:
        L.append(f"Current weight: {cw}lb"
                 + (f", goal {gw}lb ({round(abs(cw - gw), 1)}lb to go)" if gw else ""))
    L.append(f"Daily targets: {tgt_cal} cal / {tgt_pro}g protein")
    brain = (stats.get("brain") or "").strip()
    if brain:
        L.append("")
        L.append("WHAT I KNOW (durable traits + preferences I've learned about this client, grouped by category):")
        L.append(brain)
    L.append("")

    # RECENT CONVERSATION — the live-turn context the brief was previously blind to.
    # Lets the directive respect what the client JUST said (a stated plan, a rest
    # day, a competing commitment) instead of contradicting it.
    convo = stats.get("recent_conversation") or []
    if convo:
        L.append("RECENT CONVERSATION (oldest→newest — what the client JUST told me. "
                 "Treat these stated near-term plans as CURRENT TRUTH and never contradict them):")
        for m in convo[-8:]:
            when = (m.get("when") or "").replace("T", " ")
            u = (m.get("user") or "").strip().replace("\n", " ")
            a = (m.get("arnie") or "").strip().replace("\n", " ")
            if u:
                L.append(f"  [{when}] them: {u}")
            if a:
                L.append(f"  [{when}] me: {a[:160]}")
        L.append("")
    workout_done = today.get("workout_completed") or bool(today.get("exercise_entries"))
    # Local weekday + a clock-position hint, so the model knows whether "no
    # workout yet" means "it's 6am and the day's barely started" or "it's 10pm
    # and they skipped." Without this, the LLM has been inventing "today's a
    # rest day" from inference whenever workout_done is false.
    try:
        _today_dt = _dt.strptime(today_iso, "%Y-%m-%d")
        _today_weekday = _today_dt.strftime("%A")
    except Exception:
        _today_weekday = "today"
    # USER-LOCAL clock — `datetime.now()` is the SERVER's local time (UTC on
    # Render), not the user's. That made the briefing claim "local 13:30" when
    # the user was actually at 09:30 NY time and broke the real-time read.
    # Use the user's saved tz; fall back to UTC if missing.
    from datetime import datetime as _datetime
    try:
        import pytz as _pytz
        _tz_name = ((stats.get("profile") or {}).get("timezone")
                    or stats.get("timezone") or "UTC")
        _user_tz = _pytz.timezone(_tz_name)
        _now_local = _datetime.now(_pytz.utc).astimezone(_user_tz)
    except Exception:
        _now_local = _datetime.utcnow()
    _h = _now_local.hour
    _phase = (
        "the MIDDLE OF THE NIGHT — the client is up very late; TODAY IS OVER, they should be winding down to sleep, NOT eating a meal or chasing macros" if _h < 5 else
        "early morning — the day is just starting" if _h < 10 else
        "mid-day" if _h < 17 else
        "late afternoon / evening — typical training window" if _h < 21 else
        "late evening — the day is mostly over, winding down toward bed"
    )
    L.append(f"TODAY ({today_iso}, {_today_weekday}, STILL IN PROGRESS, user-local {_now_local.hour:02d}:{_now_local.minute:02d} — {_phase}): "
             f"{today.get('calories', 0)} cal, {today.get('protein', 0)}g protein so far; "
             f"workout {'done' if workout_done else 'not yet'}")
    L.append("")

    past = [h for h in history if h.get("date") and h["date"] < today_iso][-21:]
    if past:
        L.append("LOGGED DAYS (oldest→newest) — date (weekday): cal, protein, workout:")
        for h in past:
            try:
                wd = _dt.strptime(h["date"], "%Y-%m-%d").strftime("%a")
            except Exception:
                wd = "?"
            L.append(f"  {h['date']} ({wd}): {h.get('calories', 0)} cal, "
                     f"{h.get('protein', 0)}g P, workout={'Y' if h.get('workout') else 'N'}")
        L.append("")

    if weights:
        L.append("WEIGHT (lb), oldest→newest — find milestones (lowest in N weeks) + pace:")
        L.append("  " + ", ".join(f"{w['date']}:{w['lbs']}" for w in weights[-30:]))
        L.append("")

    wsnaps = [h for h in health if h.get("source") == "whoop"][-5:]
    if wsnaps:
        L.append("WEARABLE (Whoop), recent:")
        for h in wsnaps:
            parts = []
            if h.get("recovery_score") is not None:
                parts.append(f"recovery {h['recovery_score']}%")
            if h.get("sleep_hours") is not None:
                parts.append(f"sleep {h['sleep_hours']:.1f}h")
            if h.get("strain") is not None:
                parts.append(f"strain {h['strain']:.1f}")
            L.append(f"  {h.get('date', '')}: " + ", ".join(parts))

    return "\n".join(L)


def _weight_eta(rows, goal_lbs) -> Optional[str]:
    """A short goal-date label ('Aug 3') projected from the windowed weigh-ins —
    a real reference point for the spark. Returns None when the trend is flat,
    moving AWAY from goal, or so slow the date is past a year out (better to show
    nothing than a fantasy date)."""
    from datetime import datetime, timedelta
    if not rows or len(rows) < 2:
        return None
    try:
        d0 = datetime.strptime(rows[0]["date"], "%Y-%m-%d")
        d1 = datetime.strptime(rows[-1]["date"], "%Y-%m-%d")
    except Exception:
        return None
    days = (d1 - d0).days
    if days < 5:
        return None
    v0, v1 = float(rows[0]["lbs"]), float(rows[-1]["lbs"])
    rate = (v1 - v0) / days                    # lbs/day
    remaining = goal_lbs - v1
    if rate == 0 or remaining == 0:
        return None
    days_to = remaining / rate                 # >0 only when trend heads toward goal
    if days_to <= 0 or days_to > 365:
        return None
    eta = d1 + timedelta(days=round(days_to))
    return f"{eta:%b} {eta.day}"


def _resolve_viz(stats: dict, req) -> Optional[dict]:
    """Turn the LLM's viz REQUEST ({type, metric, window}) into a concrete wire
    viz filled from the user's REAL data — never the model's numbers, so the
    strip can never disagree with the card's own prose. Returns None when the
    requested metric has no usable series/target (the card degrades to text).

    Wire shape consumed by iOS (BriefingResponse.Card.Viz):
      spark / bars → {"type", "metric", "series": [...], "baseline"?: float}
      bar          → {"type", "metric", "value": float, "target": float}
    """
    if not isinstance(req, dict):
        return None
    vtype = str(req.get("type", "")).lower().strip()
    metric = str(req.get("metric", "")).lower().strip()
    if vtype not in {"spark", "bar", "bars"}:
        return None
    try:
        window = int(req.get("window", 7))
    except Exception:
        window = 7
    window = max(3, min(window, 8))

    history = stats.get("history") or []
    weights = stats.get("weights") or []
    health = stats.get("health") or []
    targets = stats.get("targets") or {}
    today = stats.get("today") or {}
    user = stats.get("user") or {}

    def _num(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    def _last(rows, key, n):
        return [float(r[key]) for r in rows if _num(r.get(key))][-n:]

    # ── bar: a single today-vs-target progress fill (macros only) ────────────
    if vtype == "bar":
        if metric in {"protein", "calories", "carbs", "fats"}:
            val, tgt = today.get(metric), targets.get(metric)
            if _num(val) and _num(tgt) and tgt > 0:
                return {"type": "bar", "metric": metric,
                        "value": round(float(val), 1), "target": round(float(tgt), 1)}
        return None

    # ── spark / bars: a short series, optionally a dashed baseline ────────────
    series: list = []
    baseline: Optional[float] = None
    caption: Optional[str] = None
    if metric == "weight":
        rows = [w for w in weights if _num(w.get("lbs"))][-window:]
        series = [float(w["lbs"]) for w in rows]
        gw = user.get("goal_weight_lbs")
        baseline = float(gw) if _num(gw) else None
        if baseline is not None:
            caption = _weight_eta(rows, baseline)   # e.g. "Aug 3" — the goal date
    elif metric in {"protein", "calories", "carbs", "fats"}:
        series = _last(history, metric, window)
        tgt = targets.get(metric)
        baseline = float(tgt) if _num(tgt) and tgt > 0 else None
    elif metric == "steps":
        series = _last(health, "steps", window)
        baseline = 10000.0
    elif metric == "sleep":
        series = _last(health, "sleep_hours", window)
        baseline = 8.0
    elif metric == "adherence":
        tgt = targets.get("protein")
        if _num(tgt) and tgt > 0:
            series = [round(min((h.get("protein") or 0) / tgt, 1.5), 2)
                      for h in history[-window:] if _num(h.get("protein"))]
        baseline = 1.0
    else:
        return None

    if len(series) < 2:
        return None
    out = {"type": vtype, "metric": metric, "series": [round(float(x), 2) for x in series]}
    if baseline is not None:
        out["baseline"] = round(baseline, 2)
    if caption:
        out["caption"] = caption
    return out


def _sanitize_briefing(obj: dict, stats: Optional[dict] = None) -> dict:
    """Coerce the LLM object into the wire shape: hero/focus/cards/starter, cards
    capped + sorted by priority desc. Missing pieces degrade gracefully."""
    def _s(v) -> str:
        s = str(v).strip() if v is not None else ""
        # Arnie's voice avoids em/en dashes; swap any to a comma (a dash reads as a
        # pause) so the iOS copy never shows one even if the model slips.
        s = (s.replace(" — ", ", ").replace(" – ", ", ")
              .replace("—", ", ").replace("–", ", "))
        return s

    hero_in = obj.get("hero") or {}
    hero = {
        "headline": (_s(hero_in.get("headline")) or None),
        "milestone": (_s(hero_in.get("milestone")) or None),
        "stats": (_s(hero_in.get("stats")) or None),
        "body": _s(hero_in.get("body")),
        "next": (_s(hero_in.get("next")) or None),
    }
    focus_in = obj.get("focus") or {}
    focus = {"title": _s(focus_in.get("title")), "body": _s(focus_in.get("body"))}

    cards = []
    for c in (obj.get("cards") or []):
        if not isinstance(c, dict):
            continue
        story = _s(c.get("story"))
        if not story:
            continue
        try:
            prio = int(c.get("priority", 50))
        except Exception:
            prio = 50
        kind = _s(c.get("kind")).lower()
        if kind not in {"win", "risk", "opportunity", "trend", "noticed", "prediction"}:
            kind = "noticed"
        card = {
            "emoji": _s(c.get("emoji")) or "✨",
            "title": _s(c.get("title")),
            "story": story,
            "priority": prio,
            "kind": kind,
        }
        # Optional micro-viz: the model names the shape + metric; we fill the real
        # series from `stats` (never the model's numbers). Dropped silently when the
        # metric has no usable data, so the card just renders text-only.
        viz = _resolve_viz(stats, c.get("viz")) if stats else None
        if viz:
            card["viz"] = viz
        cards.append(card)
    cards.sort(key=lambda c: c["priority"], reverse=True)
    cards = cards[:5]

    # Cap the starter at 90 chars — long enough for a natural short question
    # ("What's lunch looking like today?"), short enough that it never wraps to
    # a third line on the card. Trim at the last word boundary, then ensure it
    # closes with a "?" since it should always read as a question.
    starter = _s(obj.get("starter"))
    if len(starter) > 90:
        cut = starter[:90]
        sp = cut.rfind(" ")
        starter = (cut[:sp] if sp > 40 else cut).rstrip(" ,.;:")
    if starter and not starter.endswith("?"):
        starter = starter.rstrip(".!,;:") + "?"

    return {"hero": hero, "focus": focus, "cards": cards, "starter": starter}


def _engagement_signal(stats: dict) -> dict:
    """How much the user has given Arnie so far, so the briefing can match its
    substance + confidence to the evidence. Counts logged days, weigh-ins, and
    workouts (plus whether today's been touched). Returns a tier 0-3:

      0 NEW      — profile only, no logs            → plan / projection / teach
      1 EARLY    — a little data (today / 1-3 days)  → real-time + first reflections
      2 BUILDING — several days logged               → emerging patterns
      3 RICH     — weeks of data                     → patterns + foresight

    The brief is the SAME shape at every tier; only the mix of content shifts, so
    it's always full and useful — never an empty dashboard waiting for data."""
    today = stats.get("today") or {}
    history = stats.get("history") or []
    weights = stats.get("weights") or []

    logged_days = sum(1 for h in history
                      if (h.get("calories") or 0) > 0 or h.get("workout"))
    weigh_ins = len(weights)
    workouts = sum(1 for h in history if h.get("workout"))
    today_logged = ((today.get("calories") or 0) > 0
                    or bool(today.get("food_entries"))
                    or bool(today.get("exercise_entries")))

    if logged_days >= 10 and weigh_ins >= 5:
        tier = 3
    elif logged_days >= 4:
        tier = 2
    elif logged_days >= 1 or today_logged:
        tier = 1
    else:
        tier = 0

    return {
        "tier": tier,
        "logged_days": logged_days,
        "weigh_ins": weigh_ins,
        "workouts": workouts,
        "today_logged": today_logged,
    }


def _briefing_tier_guidance(sig: dict) -> str:
    """Composition rules handed to the briefing LLM for the user's current tier.
    Always demands a COMPLETE brief; shifts WHAT fills it as data grows."""
    base = (
        "Always return a COMPLETE, useful briefing: a hero, one focus, 3-4 cards, and "
        "a starter. NEVER leave a section empty or padded with filler — when data is "
        "light, fill with the client's goal, plan, projection, and concrete coaching "
        "from their profile (a sharp plan is as useful as a trend). Match your "
        "CONFIDENCE to the evidence: hedge when thin ('first signs…'), sharpen as it "
        "grows. Do NOT apologize for or dwell on how little they've logged. "
        "GROUNDING RULE: any RATE or DATE/ETA projection ('~X lb/week', 'by August', "
        "'within 10 days', 'on track for <month>') MUST be backed by real measured data "
        "below — at least 2 weigh-ins forming an actual trend. With fewer, or a flat / "
        "moving-away trend, give the PLAN (what their targets imply) or a concrete next "
        "step instead — NEVER invent a calendar date or pace you can't see in the data."
    )
    tier = sig.get("tier", 0)
    if tier == 0:
        return base + (
            "\nSTAGE — NEW (profile only, no logs). This briefing is a PLAN, not an "
            "analysis. hero = their goal + what their TARGETS imply per week as a PLAN "
            "framing (e.g. 'these numbers set up a ~0.7 lb/week cut') — NOT a confident "
            "calendar date or ETA ('on track for ~mid-August' is banned here: zero "
            "weigh-ins can't back a date). focus = the ONE first move: log today's first meal "
            "(a photo, a voice note, or just telling you). cards = goal-specific coaching "
            "+ what a good day looks like for them + ONE forward 'next unlock' card naming "
            "the reward for logging (e.g. 'Log 3 days and I'll start mapping your trend'). "
            "starter = an inviting, goal-aware opener. Make day one feel like a sharp plan."
        )
    if tier == 1:
        return base + (
            "\nSTAGE — EARLY (a little data). hero = today vs target (real-time). focus = "
            "today's next move. cards = your FIRST real reflections on what they logged "
            "(hedged) + goal/plan coaching to round it out + ONE forward 'next unlock' "
            "card. Blend fresh observation with the plan."
        )
    if tier == 2:
        return base + (
            "\nSTAGE — BUILDING (several days logged). hero = a short trend or today. "
            "focus = a real emerging pattern. cards = patterns + adherence + a rate-based "
            "projection. Mostly observed; add a little plan only if needed to stay full. "
            "Drop the 'next unlock' card now."
        )
    return base + (
        "\nSTAGE — RICH (weeks of data). The full 'I know you' read: trajectory, what's "
        "working, predictions, comparisons, risks. No getting-started or progress card — "
        "this is pure interpreted coaching."
    )


async def generate_briefing(stats: dict) -> dict:
    """Call Claude for the structured home briefing — interpreted, prioritized.
    The composition adapts to the user's engagement tier (see `_engagement_signal`)
    so a brand-new user gets a full, useful PLAN and it enriches into pattern-based
    coaching as they log + chat — same shape throughout, never an empty dashboard."""
    from core.llm import _get_anthropic, DEFAULT_MODEL, ANTHROPIC_API_KEY

    if not ANTHROPIC_API_KEY():
        return {}

    name = (stats.get("user", {}) or {}).get("name", "") or "your client"
    summary = _build_briefing_summary(stats)
    tier_guidance = _briefing_tier_guidance(_engagement_signal(stats))
    prompt = f"""You are Arnie, a sharp personal fitness coach writing today's BRIEFING for {name}. You have ALREADY reviewed all of their data. Hand back a briefing that answers, within seconds: "Am I winning? What matters today? What should I do?" INTERPRET the data into meaning — NEVER list raw metrics.

Return ONLY a valid JSON object with EXACTLY this shape:
{{
  "hero": {{
    "headline": "<3 to 7 words, a single REAL-TIME directive — the move to make right now, in imperative/confident voice, grounded in TODAY's live numbers. Slightly longer is fine when the extra words add genuine PERSONALIZATION ('Lock in the strong finish', 'Cut 150 to break the plateau') vs a generic one. e.g. 'Hit 32g protein', 'Lock in the strong finish', 'Protect the 5-day streak', 'Fuel the cut with breakfast'. NEVER a bare number ('209 lbs') — translate the number into the action. NO second clause. null only if nothing actionable.>",
    "milestone": "<positive reinforcement IF genuinely earned by the data, e.g. 'Lowest weight in 6 weeks' — else null. No emoji.>",
    "stats": "<the 1-2 numbers that GROUND the directive, as a compact scannable line joined by ' · ' — pick what matters MOST. When they're a completed day's totals, tag the line with a short time anchor so it's never ambiguous, e.g. '198g protein · 1,939 cal yesterday', '184 lbs · down 1.2 this week'. Otherwise today's live numbers, e.g. '2 workouts · 8,400 steps'. Real logged numbers only; null if there's nothing meaningful to show yet.>",
    "body": "<ONE short, confident status sentence (~5-12 words) — a read on where they stand, NOT a paragraph and NOT a restatement of the numbers. e.g. 'You're right where I want you.', 'Ahead of pace, keep it steady.', 'Protein's the only gap today.'>",
    "next": "<ONE crisp instruction for the single next move: a sharp coach cue, NOT a sentence. About 4 to 7 words, ONE clause only, no second comma-clause. Time-anchor it ONLY when the anchor is still in the future, and a short frame like 'First move:' or 'Tonight:' often helps. Vary it, e.g. 'Weigh in first thing tomorrow.', 'Tonight: wind down, lights out by 11.', 'Get the session in after work.', 'First move: protein at breakfast.', 'Hold steady, no late snacking.' It MUST fit on one short line, so NEVER a long two-part instruction like 'Front-load a protein snack by 10am, close the gap at dinner.' null only if the headline already fully IS the instruction.>"
  }},
  "focus": {{
    "title": "",
    "body": ""
  }},
  "cards": [
    {{"kind": "<win|risk|opportunity|trend|noticed|prediction>", "title": "<a short, OPINIONATED coaching headline stating your judgment, in natural sentence case (NOT all-caps, no emoji) — e.g. 'On track for 205', 'The weekend leak', \\"Volume's slipping\\", \\"Protein's holding\\", \\"Scale's creeping back\\". NEVER a generic category (Protein, Weight) or a tone word (Win, Opportunity).>", "story": "<DIAGNOSIS + EVIDENCE + RECOMMENDATION in 2-3 tight sentences, scannable in ~2s — what's happening, why it matters, what to do. e.g. \\"Five straight days under 115g protein. That's the pattern driving the scale up. Break it today.\\">", "priority": <0-100>, "viz": {{"type": "<spark|bar|bars>", "metric": "<weight|protein|calories|carbs|fats|steps|sleep|adherence>", "window": <3-8>}}}}
  ],
  "starter": "<ONE natural conversational question — a normal short sentence, roughly 8 to 14 words, fills almost a full line on the card. NOT a one-word fragment. e.g. \"What's lunch looking like today?\", \"Did you get a workout in this morning?\", \"How's training feeling this week?\", \"What's standing between you and dinner?\">"
}}

COMPOSITION — match the substance to how much you actually know about {name}:
{tier_guidance}

RULES:
- SPEAK as Arnie — first person, present, warm. A coach talking TO them, not software reporting. "I've noticed your protein's staying remarkably consistent" — NOT "Protein remains high." "You're ahead of the pace I expected two weeks ago" — NOT "Weight trend improving." INTERPRET; never a bare metric.
- The hero is THE element on the screen and reads top-to-bottom as a scannable directive, NOT a paragraph: headline = the real-time directive (a confident imperative, no second clause) → stats = the 1-2 grounding numbers ('198g protein · 1,939 cal') → body = ONE short confident status line ('You're right where I want you.') → next = ONE crisp cue for the single next move, a sharp instruction not a sentence, fitting one short line ('First move: protein before 10am.', 'Tonight: water, walk, sleep.'). Each is short and skimmable; never merge them into prose. Never a bare number as the headline; never an editorial header. Milestone only if the data earns it (a real low, a real streak); else null. stats/next are null only when there's genuinely nothing to put there.
- TIME-AWARE + REALISTIC: read the user-local clock in TODAY and make the headline + next fit reality. Protein matters, but NEVER tell them to eat a big meal or hit a large remaining macro target late at night or right before bed, and never imply hitting most of a day's target in a short window (chasing 135g of protein in 15 minutes is absurd advice). If it's LATE EVENING and a macro is short, at most suggest a small light option, or just let the day stand and pivot to tomorrow. If it's OVERNIGHT / past midnight (the middle-of-the-night phase), TODAY IS OVER: give NO "today" pacing cue and NEVER reference a deadline that already passed ("before midnight" at 1am is nonsense) — the only sane move is sleep, or tomorrow's first step (weigh in, breakfast protein).
- VARY THE LEVER — do NOT default to a protein-pacing reminder. Across days the single directive must rotate to whatever ACTUALLY matters most right now: a morning weigh-in, getting the training session in, recovery / sleep, hydration, protecting a streak or consistency, a step toward goal weight, or nutrition ONLY when the clock makes it realistic. Read the data + clock and pick the one real lever, not protein by reflex.
- RESPECT THE LIVE CONVERSATION: the RECENT CONVERSATION section (when present) is what the client JUST told you, and it OVERRIDES any default assumption from the data. If they stated a near-term commitment or plan (family time, travel, an event, dinner out, an intentional rest day, an injury, being slammed at work), do NOT push a directive that fights it. NEVER tell them to train, "get the session in", or do anything they just said they can't or won't. Instead, either (a) suggest something that FITS the moment (a walk while out, light movement, a bit of mobility, "a family walk still counts") or (b) pivot the single directive to a lever that doesn't conflict (protein/hydration/sleep/recovery/tomorrow's first move). Complement the moment; never contradict it.
- NEVER claim "today is a rest day" unless: (a) the user said so in the RECENT CONVERSATION above, or (b) the day is mostly over (late evening) AND the user has a long-running weekly pattern of skipping THIS weekday (4+ weeks of N on this exact weekday in the LOGGED DAYS section). "Workout not yet" early in the day means it's early — not a rest day. When uncertain, treat today as a normal TRAINING day and frame nutrition + recovery accordingly.
- focus.title and focus.body must be empty strings — the iOS app no longer renders a separate Focus pane; the hero now carries the single most important action. Anything you'd put in focus goes into the cards below, not focus.
- 2-4 cards. The TITLE is a short, OPINIONATED coaching headline stating your judgment, in natural sentence case (e.g. 'On track for 205', 'The weekend leak', "Volume's slipping", "Scale's creeping back"). NEVER a generic category (Protein, Weight) or a tone word (Win, Opportunity); never all-caps, no emoji. Each STORY is DIAGNOSIS + EVIDENCE + RECOMMENDATION in 2-3 tight sentences, scannable in ~2s — what happened, why it matters, what to do. Coaching with conviction, not reporting. "kind" sets the card's quiet tone-color. Set "kind" per card:
    win        — a genuine streak / PR / milestone (include one when it's REAL; if there's no honest win yet, use a concrete next-step card instead of manufacturing one)
    prediction — forward-looking, but ONLY when a real measured trend backs the pace/date ("at this pace you'll break 205 within 10 days" needs ≥2 weigh-ins showing that pace). High value when earned; never invent a rate or date from profile/thin data — fall back to the plan or an opportunity card
    opportunity— an unlock if they change one thing
    risk       — a real warning (use sparingly)
    trend      — a neutral pattern
    noticed    — a personal observation ("I've noticed…")
  ROTATE the kinds for emotional contrast — don't make every card the same tone. ORDER by priority; the lead card is usually a prediction or a win.
- viz (OPTIONAL per card — a tiny monochrome strip under the story): add "viz" ONLY when a real series in DATA backs the card's point, and pick the shape that fits: "spark" = a trend over time (bodyweight drifting, a metric climbing); "bars" = day-by-day comparison (protein per day, where weekends spike); "bar" = today-so-far vs target (protein/calories progress). "metric" must be one you can actually see in DATA below (weight, protein, calories, carbs, fats, steps, sleep, adherence). You give ONLY type + metric + window — the app fills the real numbers, so NEVER put numbers in viz and keep stating them in the story. Put viz on the 1-3 cards where a shape sharpens the point; OMIT it entirely (drop the key) on pure observations or predictions with no underlying series. A wrong or unavailable metric is dropped silently, so when unsure, omit.
- LOOK FORWARD more than back — users care where they're GOING. Lead with trajectory and what's next.
- MOMENTUM: every briefing must contain at least one piece of progress evidence (best streak, lowest weight, fastest pace, days logged).
- PERSONAL: ground every insight in THIS client's real numbers AND the durable traits you've learned about them (their habits, what works for them, their lifestyle + constraints) under WHAT I KNOW below. Specific to them, never generic advice.
- VOICE: never use em dashes or en dashes. Use commas, periods, or colons. Write in complete sentences. The app shows only the FIRST 2 sentences of each card story, the focus body, and the hero body, so make your point in exactly 2 tight sentences and never trail into a third.
- starter: ONE short, personal question about today — UNDER 125 characters, a single clean sentence. Never a paragraph.
- CURATED, not assembled — you reviewed everything and chose THESE for today. Real numbers when you have them; no greetings (the app adds "Good morning"); no filler. When data's thin, lean on goal/plan/projection; one forward-looking "next unlock" card is welcome.

DATA:
{summary}
"""
    try:
        client = _get_anthropic()
        response = await client.messages.create(
            model=DEFAULT_MODEL(),
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if text.startswith("json"):
            text = text[4:].strip()
        obj = json.loads(text)
        if isinstance(obj, dict):
            return _sanitize_briefing(obj, stats)
    except Exception as e:
        logger.error(f"Briefing generation failed: {e}")

    return {}


def _schedule_briefing_refresh(user_id: int, stats: dict, cache_key: tuple) -> None:
    """Fire-and-forget background regen of a stale briefing (stale-while-
    revalidate). No-op if a refresh for this key is already in flight, or if
    there's no running event loop to host the task (e.g. a sync caller / tests)."""
    if cache_key in _briefing_refreshing:
        return
    _briefing_refreshing.add(cache_key)

    async def _run() -> None:
        try:
            briefing = await generate_briefing(stats)
            if briefing and (briefing.get("hero", {}).get("body") or briefing.get("cards")):
                _CACHE[cache_key] = (time.time(), briefing)
        except Exception:
            logger.exception("background briefing refresh failed")
        finally:
            _briefing_refreshing.discard(cache_key)

    try:
        asyncio.create_task(_run())
    except RuntimeError:
        _briefing_refreshing.discard(cache_key)  # no loop; let a later call retry


def invalidate_briefing(user_id: int) -> None:
    """Drop EVERY cached read for `user_id` — briefing AND the daily/insight
    caches. Call this on any mutation that changes the day's read (food log,
    weight log, workout log, water) so the next Coach fetch regenerates against
    the fresh state instead of serving pre-log copy. Cheap dict scan; safe
    from any thread/coro."""
    # Pop the briefing entry and discard its refresh marker.
    _CACHE.pop((user_id, "__briefing__"), None)
    _briefing_refreshing.discard((user_id, "__briefing__"))
    # ANY other cache key whose first element matches this user — covers the
    # per-date insight caches `(user_id, "YYYY-MM-DD")` so the day's insights
    # also regenerate after a log. Walks the dict once; fine for the scale.
    stale_keys = [k for k in _CACHE.keys()
                  if isinstance(k, tuple) and len(k) == 2 and k[0] == user_id]
    for k in stale_keys:
        _CACHE.pop(k, None)


async def get_briefing(user_id: int, stats: dict, force: bool = False) -> dict:
    """Cached daily briefing per user, with stale-while-revalidate.

    Fresh cache → served instantly. Stale cache (older than the TTL) → the stale
    copy is served instantly AND a background refresh is kicked off, so a user
    returning after a few hours never waits on the ~15s LLM regen: they see the
    last brief and the next open is fresh. Only a cold cache (first ever, or after
    a restart wipes the in-memory store) blocks on generation. `force` always
    regenerates synchronously (manual pull-to-refresh)."""
    now = time.time()
    cache_key = (user_id, "__briefing__")
    cached = _CACHE.get(cache_key)

    if not force and cached:
        if (now - cached[0]) < _TTL:
            return cached[1]                       # fresh — serve as-is
        _schedule_briefing_refresh(user_id, stats, cache_key)  # stale — refresh behind
        return cached[1]

    briefing = await generate_briefing(stats)
    if briefing and (briefing.get("hero", {}).get("body") or briefing.get("cards")):
        _CACHE[cache_key] = (now, briefing)
    return briefing


async def get_insights(user_id: int, stats: dict, force: bool = False,
                       date_key: str = "") -> List[str]:
    """Cached insights per (user_id, date) — regenerates if older than 1 hour."""
    now = time.time()
    cache_key = (user_id, date_key)
    cached = _CACHE.get(cache_key)
    if not force and cached and (now - cached[0]) < _TTL:
        return cached[1]

    insights = await generate_insights(stats)
    if insights:
        _CACHE[cache_key] = (now, insights)
    return insights


async def get_week_insights(user_id: int, stats: dict, force: bool = False) -> List[str]:
    """Cached WEEKLY insights per user — regenerates if older than the TTL."""
    now = time.time()
    cache_key = (user_id, "__week__")
    cached = _CACHE.get(cache_key)
    if not force and cached and (now - cached[0]) < _TTL:
        return cached[1]

    insights = await generate_week_insights(stats)
    if insights:
        _CACHE[cache_key] = (now, insights)
    return insights
