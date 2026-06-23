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
    L.append("")
    workout_done = today.get("workout_completed") or bool(today.get("exercise_entries"))
    L.append(f"TODAY ({today_iso}, STILL IN PROGRESS): "
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


def _sanitize_briefing(obj: dict) -> dict:
    """Coerce the LLM object into the wire shape: hero/focus/cards/starter, cards
    capped + sorted by priority desc. Missing pieces degrade gracefully."""
    def _s(v) -> str:
        return str(v).strip() if v is not None else ""

    hero_in = obj.get("hero") or {}
    hero = {
        "headline": (_s(hero_in.get("headline")) or None),
        "milestone": (_s(hero_in.get("milestone")) or None),
        "body": _s(hero_in.get("body")),
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
        cards.append({
            "emoji": _s(c.get("emoji")) or "✨",
            "title": _s(c.get("title")),
            "story": story,
            "priority": prio,
            "kind": kind,
        })
    cards.sort(key=lambda c: c["priority"], reverse=True)
    cards = cards[:5]

    return {"hero": hero, "focus": focus, "cards": cards, "starter": _s(obj.get("starter"))}


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
        "grows. Do NOT apologize for or dwell on how little they've logged."
    )
    tier = sig.get("tier", 0)
    if tier == 0:
        return base + (
            "\nSTAGE — NEW (profile only, no logs). This briefing is a PLAN, not an "
            "analysis. hero = their goal + a forward projection toward goal weight at "
            "their targets (directional, e.g. 'on track for ~mid-August' — never a past "
            "trend they don't have). focus = the ONE first move: log today's first meal "
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
    "headline": "<the single most striking status, e.g. '209.2 lbs' — or null if nothing striking>",
    "milestone": "<positive reinforcement IF genuinely earned by the data, e.g. 'Lowest weight in 6 weeks' — else null. No emoji.>",
    "body": "<1-2 short sentences: where they are + today's direction. e.g. 'Protein was 193g yesterday. Let's close the final 7 lbs.'>"
  }},
  "focus": {{
    "title": "<2-4 words>",
    "body": "<the SINGLE highest-leverage action for today, 1-2 sentences, grounded in a REAL pattern/number, ending actionable. e.g. 'You average 38g less protein on weekends. Let's get 50g in before noon.'>"
  }},
  "cards": [
    {{"kind": "<win|risk|opportunity|trend|noticed|prediction>", "title": "<a short, OPINIONATED coaching headline stating your judgment, in natural sentence case (NOT all-caps, no emoji) — e.g. 'On track for 205', 'The weekend leak', \\"Volume's slipping\\", \\"Protein's holding\\", \\"Scale's creeping back\\". NEVER a generic category (Protein, Weight) or a tone word (Win, Opportunity).>", "story": "<DIAGNOSIS + EVIDENCE + RECOMMENDATION in 2-3 tight sentences, scannable in ~2s — what's happening, why it matters, what to do. e.g. \\"Five straight days under 115g protein. That's the pattern driving the scale up. Break it today.\\">", "priority": <0-100>}}
  ],
  "starter": "<ONE personalized conversation question about today, e.g. 'What's dinner looking like?'>"
}}

COMPOSITION — match the substance to how much you actually know about {name}:
{tier_guidance}

RULES:
- SPEAK as Arnie — first person, present, warm. A coach talking TO them, not software reporting. "I've noticed your protein's staying remarkably consistent" — NOT "Protein remains high." "You're ahead of the pace I expected two weeks ago" — NOT "Weight trend improving." INTERPRET; never a bare metric.
- The hero is the LARGEST element. Lead with where they ARE and where they're HEADED. Milestone only if the data earns it (a real low, a real streak); else null.
- Exactly ONE focus: the single highest-leverage move today, tied to a real pattern, ending actionable.
- 2-4 cards. The TITLE is a short, OPINIONATED coaching headline stating your judgment, in natural sentence case (e.g. 'On track for 205', 'The weekend leak', "Volume's slipping", "Scale's creeping back"). NEVER a generic category (Protein, Weight) or a tone word (Win, Opportunity); never all-caps, no emoji. Each STORY is DIAGNOSIS + EVIDENCE + RECOMMENDATION in 2-3 tight sentences, scannable in ~2s — what happened, why it matters, what to do. Coaching with conviction, not reporting. "kind" sets the card's quiet tone-color. Set "kind" per card:
    win        — a genuine streak / PR / milestone (ALWAYS include at least one, for momentum)
    prediction — forward-looking ("at this pace you'll break 205 within 10 days"); FAVOR these, they're the highest value
    opportunity— an unlock if they change one thing
    risk       — a real warning (use sparingly)
    trend      — a neutral pattern
    noticed    — a personal observation ("I've noticed…")
  ROTATE the kinds for emotional contrast — don't make every card the same tone. ORDER by priority; the lead card is usually a prediction or a win.
- LOOK FORWARD more than back — users care where they're GOING. Lead with trajectory and what's next.
- MOMENTUM: every briefing must contain at least one piece of progress evidence (best streak, lowest weight, fastest pace, days logged).
- starter: ONE personal question about today.
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
            return _sanitize_briefing(obj)
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
