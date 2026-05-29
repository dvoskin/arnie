"""
Proactive messaging scheduler.
Runs every 30 minutes, checks each user's local time, and sends
LLM-generated nudges within their wake/sleep window.
Reminders are ON by default for all onboarded users.

Touchpoints (all relative to user local time):
  wake+30   — morning weight + breakfast check-in (wearable-aware)
  10:00     — late-morning nudge if nothing logged yet
  12:00     — midday pacing (nutrition velocity vs time-of-day target)
  15:30     — pre-workout fuel + readiness check (recovery-aware)
  16:30     — afternoon workout follow-up if not yet done
  19:00     — evening full-day pacing + dinner prompt
  21:00     — night closeout nudge
  22:00     — end-of-day performance report (all users, template-based)

Whoop sync runs every 2 hours.
"""
import logging
import os
from datetime import datetime, date, timezone

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

_whoop_notified: dict = {}
_new_user_sent: dict = {}  # user_id_str -> set of slot keys already sent

# Nudge slots: (hour, minute_start, minute_end, slot_key)
_NUDGE_SLOTS = [
    # morning slot is dynamic (wake+30), handled separately
    (10, 0,  30, "late_morning_nolog"),
    (12, 0,  30, "midday_pacing"),
    (15, 30, 60, "preworkout"),
    (16, 30, 60, "workout_check"),
    (19, 0,  30, "evening_pacing"),
    (21, 0,  30, "night_closeout"),
]

_NUDGE_SYSTEM = """You are Arnie — a direct, no-fluff fitness coach sending a quick check-in text to your athlete.

Rules:
- 1–3 sentences MAX. Never write a paragraph.
- Sound like a human, not a notification. Conversational, direct.
- Reference actual numbers from the data provided — be specific.
- Use the athlete's first name at most once if it flows naturally.
- No generic filler: no "Great job!", "Keep it up!", "You've got this!"
- If wearable data is available, weave it in naturally (recovery, sleep, HRV, strain).
- If they're on track, say so briefly with the number. If behind, say exactly what needs to happen.
- Never sound robotic or template-like.
- LANGUAGE: Write in the user's preferred language if provided in the context. Default to English if unknown.
- Return ONLY the message text. No prefix, no label, no explanation."""

_SLOT_INSTRUCTIONS = {
    "morning_checkin": (
        "It's morning — greet them and prompt them to log weight (if they haven't) "
        "and tell you about breakfast. If recovery data is present, reference it naturally "
        "(e.g. if recovery is red, note they should fuel well; if green, match their energy)."
    ),
    "late_morning_nolog": (
        "It's 10am and nothing has been logged today. Check in — "
        "did they skip breakfast or just forget to log? Keep it short and curious, not accusatory."
    ),
    "midday_pacing": (
        "It's noon. Calculate where they should be at this point in the day "
        "(roughly 35-40% through their calorie and protein targets). "
        "Tell them specifically what to prioritize at lunch based on the gap. "
        "If water is low, mention it. If they're already on track, say so with the numbers."
    ),
    "preworkout": (
        "It's 3:30pm. They haven't trained yet today. "
        "Check if they're still training. If recovery data shows red (<34%), "
        "suggest going lighter or active recovery. If yellow (34-66%), note the moderate readiness. "
        "If green (67+%) or no data, just check in. Also mention if they need pre-workout fuel."
    ),
    "workout_check": (
        "It's 4:30pm. Workout not logged yet. Be direct — "
        "is it still happening today? Factor in recovery if available. "
        "If it's a rest day by their plan, acknowledge that's fine."
    ),
    "evening_pacing": (
        "It's 7pm. Do a full evening audit: calories remaining, protein remaining, "
        "water intake, whether workout was done. Tell them exactly what dinner needs to look like "
        "to close the day well. If everything is on track, say so simply. "
        "Reference wearable data if available (e.g. high strain = need more fuel)."
    ),
    "night_closeout": (
        "It's 9pm. Day is still open. Prompt them to log anything they missed "
        "and close out the day. Be brief. If they're close to their targets, "
        "tell them specifically what's left."
    ),
}


_NEW_USER_SYSTEM = """You are Arnie — a direct, genuinely curious fitness coach reaching out to a brand new athlete.

Rules:
- 1–3 sentences MAX. Coach texting a new client, not a notification bot.
- You reached out first — sound interested, not automated.
- Reference their specific goal, weight, or experience level from context to show you know them.
- Ask ONE specific, useful question. Their answer helps you coach them better.
- Don't recap what they told you during onboarding. Move forward.
- Warm but not gushy — coaches don't over-compliment.
- LANGUAGE: Write in the user's preferred language if known. Default to English.
- Return ONLY the message text. No prefix, no label, no explanation."""

_NEW_USER_SLOT_INSTRUCTIONS = {
    "warmup_1h": (
        "It's about an hour since they finished onboarding. Ask a short, direct question about "
        "their typical training schedule — what days they tend to train and roughly what time. "
        "Frame it as something that helps you time your check-ins and coaching cues. "
        "Reference their goal (cut/bulk/maintain) briefly if it flows naturally."
    ),
    "warmup_3h": (
        "About 3 hours in. Ask about their typical daily eating pattern — "
        "roughly how many meals, whether they follow any eating window, and "
        "what a normal day of food usually looks like for them. One casual question. "
        "This helps you give better food coaching."
    ),
    "warmup_6h": (
        "It's been ~6 hours since they signed up. Check on two things: "
        "First, if they have NOT logged any food yet, make it super easy — just tell them to text "
        "you whatever they've eaten today and you'll handle the rest. No format required. "
        "If they HAVE already logged something, briefly acknowledge what you see and "
        "make one useful coaching observation about it (protein pacing, calories, etc.)."
    ),
    "warmup_24h": (
        "Day 1 wrap-up check-in, about 24 hours after onboarding. "
        "If they logged food: pull the actual calories and protein numbers and give them "
        "one specific coaching note — are they on track, short on protein, over on cals? Be precise. "
        "If they logged nothing: keep it light, ask one question about what got in the way, "
        "and tell them the goal for today is just one logged meal. "
        "Close with what to focus on for day 2 based on their goal."
    ),
    "warmup_48h": (
        "48 hours in. Brief check-in. "
        "If they've been logging: call out one specific data point — protein trend, calorie consistency, "
        "workout vs no workout — and give a direct coaching cue. "
        "If they haven't logged at all: don't lecture. Ask one honest question: 'What's getting in the way?' "
        "Keep it under 2 sentences. Human and direct."
    ),
}


def _hours_since_created(user) -> float:
    """Hours elapsed since user.created_at (UTC). Returns 999 if unknown."""
    if not user.created_at:
        return 999.0
    created = (
        user.created_at.replace(tzinfo=timezone.utc)
        if user.created_at.tzinfo is None
        else user.created_at
    )
    return (datetime.now(timezone.utc) - created).total_seconds() / 3600.0


async def _llm_new_user_nudge(user, log, prefs, slot: str, name: str) -> str:
    """Generate a new-user engagement message via Claude Haiku."""
    from core.llm import chat

    cal = round(log.total_calories) if log else 0
    pro = round(log.total_protein) if log else 0
    foods_logged = len(log.food_entries) if log and log.food_entries else 0
    exercises_logged = len(log.exercise_entries) if log and log.exercise_entries else 0

    lang = getattr(prefs, "preferred_language", None) or "English"
    cal_t = prefs.calorie_target if prefs else None
    pro_t = prefs.protein_target if prefs else None
    instr = _NEW_USER_SLOT_INSTRUCTIONS.get(slot, "Send a brief, personal coaching check-in.")

    prompt = (
        f"New athlete: {name}, goal={user.primary_goal or '?'}, "
        f"exp={user.training_experience or '?'}, "
        f"height={user.height_cm:.0f}cm, weight={user.current_weight_kg:.1f}kg, "
        f"language={lang}\n"
        f"Targets: {cal_t or '?'} cal / {pro_t or '?'}g protein\n"
        f"Today so far: {cal} cal, {pro}g protein, {foods_logged} food entries, {exercises_logged} exercises\n"
        f"Task: {instr}"
    )

    try:
        result = await chat(
            [{"role": "user", "content": prompt}],
            system=_NEW_USER_SYSTEM,
            tools=False,
            max_tokens=130,
            model="claude-haiku-4-5-20251001",
        )
        return (result.get("text") or "").strip()
    except Exception as e:
        logger.error(f"New user nudge ({slot}) failed: {e}")
        return ""


async def _send(telegram_id: str, text: str):
    """
    Send a proactive message to the user regardless of platform.
    telegram_id prefixed with "im:" → BlueBubbles iMessage
    otherwise → Telegram bot
    """
    if telegram_id.startswith("im:"):
        # iMessage user — send via BlueBubbles
        from bot.imessage_handler import bb_send_text, _to_plain
        import re
        # Derive chat GUID from address stored as "im:+15551234567"
        address = telegram_id[3:]  # strip "im:" prefix
        chat_guid = f"iMessage;-;{address}"
        plain = _to_plain(text)
        try:
            await bb_send_text(chat_guid, plain)
        except Exception as e:
            logger.error(f"Proactive iMessage send failed → {telegram_id}: {e}")
        return

    from telegram import Bot
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=telegram_id, text=text, parse_mode="HTML")
        await bot.close()
    except Exception as e:
        logger.error(f"Proactive send failed → {telegram_id}: {e}")


def _in_window(hhmm: str, wake: str, sleep: str) -> bool:
    return wake <= hhmm <= sleep


def _pacing_pct(hour: int, minute: int, wake: str, sleep: str) -> float:
    """Fraction of the waking day elapsed (0.0–1.0)."""
    wh, wm = int(wake.split(":")[0]), int(wake.split(":")[1])
    sh, sm = int(sleep.split(":")[0]), int(sleep.split(":")[1])
    wake_min = wh * 60 + wm
    sleep_min = sh * 60 + sm
    now_min = hour * 60 + minute
    day_len = sleep_min - wake_min
    if day_len <= 0:
        return 0.5
    return max(0.0, min(1.0, (now_min - wake_min) / day_len))


async def _llm_nudge(user, log, prefs, health_snap, slot: str, name: str) -> str:
    """Generate a personalized nudge via Claude Haiku. Returns '' on failure."""
    from core.llm import chat

    cal = round(log.total_calories) if log else 0
    pro = round(log.total_protein) if log else 0
    water = round(log.total_water_ml) if log else 0
    workout_done = log.workout_completed if log else False
    cardio_done = log.cardio_completed if log else False
    cal_t = prefs.calorie_target if prefs else None
    pro_t = prefs.protein_target if prefs else None

    health_str = ""
    if health_snap:
        parts = []
        if health_snap.recovery_score is not None:
            rec = health_snap.recovery_score
            label = "green" if rec >= 67 else ("yellow" if rec >= 34 else "red")
            parts.append(f"recovery={rec}% ({label})")
        if health_snap.hrv is not None:
            parts.append(f"HRV={health_snap.hrv:.0f}ms")
        if health_snap.resting_hr is not None:
            parts.append(f"RHR={health_snap.resting_hr:.0f}bpm")
        if health_snap.sleep_hours is not None:
            parts.append(f"sleep={health_snap.sleep_hours:.1f}h")
        if health_snap.strain is not None:
            parts.append(f"strain={health_snap.strain:.1f}")
        if health_snap.steps is not None:
            parts.append(f"steps={health_snap.steps:,}")
        if parts:
            src = getattr(health_snap, "source", "wearable")
            health_str = f"Wearable ({src}): {', '.join(parts)}"

    foods_logged = len(log.food_entries) if log and log.food_entries else 0
    exercises_logged = len(log.exercise_entries) if log and log.exercise_entries else 0

    instr = _SLOT_INSTRUCTIONS.get(slot, "Send a brief coaching check-in about their day.")

    lang = getattr(prefs, "preferred_language", None) or "English"
    prompt = (
        f"Athlete: {name}, goal={user.primary_goal or '?'}, "
        f"exp={user.training_experience or '?'}, diet={user.dietary_preferences or 'none'}, "
        f"language={lang}\n"
        f"Today: {cal} cal"
        f"{' / ' + str(cal_t) + ' target' if cal_t else ''} | "
        f"{pro}g protein"
        f"{' / ' + str(pro_t) + 'g target' if pro_t else ''} | "
        f"water {water}ml | "
        f"workout {'✓' if workout_done else '✗'} | cardio {'✓' if cardio_done else '✗'} | "
        f"{foods_logged} food entries | {exercises_logged} exercises\n"
        f"{health_str}\n"
        f"Task: {instr}"
    )

    try:
        result = await chat(
            [{"role": "user", "content": prompt}],
            system=_NUDGE_SYSTEM,
            tools=False,
            max_tokens=130,
            model="claude-haiku-4-5-20251001",
        )
        return (result.get("text") or "").strip()
    except Exception as e:
        logger.error(f"LLM nudge ({slot}) failed: {e}")
        return ""


async def _run_reminders():
    from db.database import AsyncSessionLocal
    from db.queries import get_all_active_users, get_today_log, get_recent_health_snapshots

    async with AsyncSessionLocal() as db:
        users = await get_all_active_users(db)

        for user in users:
            prefs = user.preferences
            # ── End-of-day report (22:00–22:30) — ALL onboarded users ─────────
            try:
                tz = pytz.timezone(user.timezone or "UTC")
                now = datetime.now(tz)
                hour, minute = now.hour, now.minute

                if hour == 22 and minute < 30:
                    log = await get_today_log(db, user.id, user.timezone or "UTC")
                    if log and log.total_calories > 0:
                        name = user.name or "hey"
                        report = _fmt_day_report(log, prefs, name)
                        await _send(user.telegram_id, report)
                        continue
            except Exception as e:
                logger.error(f"Day report error for user {user.id}: {e}")

            # Proactive nudges — default ON for all onboarded users
            if not prefs or not prefs.proactive_messaging_enabled:
                continue

            try:
                tz = pytz.timezone(user.timezone or "UTC")
                now = datetime.now(tz)
                hhmm = now.strftime("%H:%M")
                hour, minute = now.hour, now.minute

                wake = prefs.wake_time or "07:00"
                sleep = prefs.sleep_time or "23:00"
                if not _in_window(hhmm, wake, sleep):
                    continue

                log = await get_today_log(db, user.id, user.timezone or "UTC")
                name = user.name or "hey"

                # Get latest health snapshot (today's if available, else most recent)
                health_snaps = await get_recent_health_snapshots(db, user.id, days=2)
                health_snap = health_snaps[0] if health_snaps else None

                day_pct = _pacing_pct(hour, minute, wake, sleep)

                # ── New user engagement burst (first 72 hours post-onboarding) ──
                # Fires at fixed intervals after account creation. Independent of
                # daily time slots. Uses a separate LLM persona focused on learning
                # about the user and building early engagement. Falls off after 48h.
                if user.onboarding_completed and user.created_at:
                    hours_since = _hours_since_created(user)

                    if hours_since <= 72.0:
                        uid_key = str(user.id)
                        sent_slots = _new_user_sent.get(uid_key, set())

                        new_slot = None
                        if 1.0 <= hours_since < 2.0 and "warmup_1h" not in sent_slots:
                            new_slot = "warmup_1h"
                        elif 3.0 <= hours_since < 4.0 and "warmup_3h" not in sent_slots:
                            new_slot = "warmup_3h"
                        elif 5.5 <= hours_since < 7.0 and "warmup_6h" not in sent_slots:
                            new_slot = "warmup_6h"
                        elif 23.0 <= hours_since < 25.0 and "warmup_24h" not in sent_slots:
                            new_slot = "warmup_24h"
                        elif 47.0 <= hours_since < 50.0 and "warmup_48h" not in sent_slots:
                            new_slot = "warmup_48h"

                        if new_slot:
                            msg = await _llm_new_user_nudge(user, log, prefs, new_slot, name)
                            if msg:
                                await _send(user.telegram_id, msg)
                                sent_slots.add(new_slot)
                                _new_user_sent[uid_key] = sent_slots
                            logger.info(f"New user nudge '{new_slot}' sent to user {user.id} ({hours_since:.1f}h in)")
                            continue  # skip normal slots this tick — avoid message flood

                # ── Morning check-in (30 min after wake) ──────────────────────
                wake_h, wake_m = int(wake.split(":")[0]), int(wake.split(":")[1])
                morn_h, morn_m = wake_h, wake_m + 30
                if morn_m >= 60:
                    morn_h += 1
                    morn_m -= 60

                if hour == morn_h and 0 <= minute - morn_m < 30:
                    if not log or log.total_calories == 0:
                        msg = await _llm_nudge(user, log, prefs, health_snap, "morning_checkin", name)
                        if not msg:
                            rec = health_snap.recovery_score if health_snap else None
                            if rec is not None:
                                emoji = "🟢" if rec >= 67 else ("🟡" if rec >= 34 else "🔴")
                                msg = (
                                    f"Morning {name}. Recovery at {rec}% today {emoji}. "
                                    f"Log your weight if you have it, then tell me breakfast."
                                )
                            else:
                                msg = f"Morning {name}. Log your weight if you have it, then tell me what you had for breakfast."
                        await _send(user.telegram_id, msg)

                # ── Late morning (10:00–10:30, only if nothing logged) ─────────
                elif hour == 10 and minute < 30:
                    if not log or log.total_calories < 50:
                        msg = await _llm_nudge(user, log, prefs, health_snap, "late_morning_nolog", name)
                        if not msg:
                            msg = f"10am and nothing logged yet, {name}. Skipped breakfast or just haven't told me?"
                        await _send(user.telegram_id, msg)

                # ── Midday pacing (12:00–12:30) ────────────────────────────────
                elif hour == 12 and minute < 30:
                    if prefs.calorie_target or prefs.protein_target:
                        cal = log.total_calories if log else 0
                        pro = log.total_protein if log else 0
                        cal_pct = (cal / prefs.calorie_target) if prefs.calorie_target else None
                        pro_pct = (pro / prefs.protein_target) if prefs.protein_target else None

                        # Only nudge if meaningfully off-pacing
                        cal_behind = cal_pct is not None and cal_pct < day_pct - 0.12
                        cal_ahead = cal_pct is not None and cal_pct > day_pct + 0.20
                        pro_behind = pro_pct is not None and pro_pct < day_pct - 0.12

                        if cal_behind or cal_ahead or pro_behind:
                            msg = await _llm_nudge(user, log, prefs, health_snap, "midday_pacing", name)
                            if not msg:
                                parts = []
                                if pro_behind:
                                    rem = prefs.protein_target - pro
                                    parts.append(f"{pro:.0f}g protein so far — {rem:.0f}g left, hit it at lunch")
                                if cal_behind:
                                    rem_c = prefs.calorie_target - cal
                                    parts.append(f"only {cal:.0f} cal in, need ~{rem_c:.0f} more")
                                if cal_ahead:
                                    parts.append(f"already at {cal:.0f} cal — pace yourself through the afternoon")
                                msg = ", ".join(parts).capitalize() + "."
                            await _send(user.telegram_id, msg)
                        elif log and log.total_calories > 0:
                            # On track — brief positive
                            msg = await _llm_nudge(user, log, prefs, health_snap, "midday_pacing", name)
                            if msg:
                                await _send(user.telegram_id, msg)

                # ── Pre-workout readiness (15:30–16:00) ───────────────────────
                elif hour == 15 and 30 <= minute < 60:
                    # Skip if workout done or exercises are already being logged (mid-workout)
                    exercises_in_progress = log and len(log.exercise_entries or []) > 0
                    if log and not log.workout_completed and not exercises_in_progress:
                        msg = await _llm_nudge(user, log, prefs, health_snap, "preworkout", name)
                        if not msg:
                            rec = health_snap.recovery_score if health_snap else None
                            if rec is not None and rec < 34:
                                msg = (
                                    f"Recovery's in the red today ({rec}%), {name}. "
                                    f"Still training? Might be worth going lighter."
                                )
                            else:
                                msg = f"3:30 — workout not logged yet, {name}. Still on for today?"
                        await _send(user.telegram_id, msg)

                # ── Afternoon workout check (16:30–17:00) ────────────────────
                elif hour == 16 and 30 <= minute < 60:
                    # Skip if workout done or exercises are already being logged (mid-workout)
                    exercises_in_progress = log and len(log.exercise_entries or []) > 0
                    if log and not log.workout_completed and not exercises_in_progress:
                        msg = await _llm_nudge(user, log, prefs, health_snap, "workout_check", name)
                        if not msg:
                            msg = f"4:30 — workout still hasn't happened, {name}. Happening today or are we calling it a rest day?"
                        await _send(user.telegram_id, msg)

                # ── Evening pacing (19:00–19:30) ──────────────────────────────
                elif hour == 19 and minute < 30 and log and log.total_calories > 0:
                    msg = await _llm_nudge(user, log, prefs, health_snap, "evening_pacing", name)
                    if not msg:
                        parts = []
                        if prefs.calorie_target:
                            rem_c = prefs.calorie_target - log.total_calories
                            if abs(rem_c) > 100:
                                parts.append(f"<b>{rem_c:+.0f} cal</b>")
                        if prefs.protein_target:
                            rem_p = prefs.protein_target - log.total_protein
                            if rem_p > 20:
                                parts.append(f"<b>{rem_p:.0f}g protein</b> still needed")
                        if parts:
                            msg = (
                                "Evening check:\n" +
                                "\n".join(f"• {p}" for p in parts) +
                                "\n\nWhat's dinner looking like?"
                            )
                        else:
                            msg = f"Looking solid today, {name}. Log dinner when you have it."
                    await _send(user.telegram_id, msg)

                # ── Night closeout (21:00–21:30) ──────────────────────────────
                elif hour == 21 and minute < 30:
                    if log and log.status == "open" and log.total_calories > 0:
                        msg = await _llm_nudge(user, log, prefs, health_snap, "night_closeout", name)
                        if not msg:
                            msg = "Day still open. Done eating? Send me anything you missed and close it out."
                        await _send(user.telegram_id, msg)

            except Exception as e:
                logger.error(f"Reminder error for user {user.id}: {e}")


def _fmt_whoop_notification(snap) -> str:
    """Format a Whoop sync notification message."""
    if snap.recovery_score is None:
        return ""
    rec = snap.recovery_score
    emoji = "🟢" if rec >= 67 else ("🟡" if rec >= 34 else "🔴")
    lines = [f"<b>⚡ Whoop — {snap.date}</b>", ""]
    lines.append(f"{emoji} Recovery: <b>{rec}%</b>")
    detail = []
    if snap.hrv:
        detail.append(f"HRV {snap.hrv:.0f}ms")
    if snap.resting_hr:
        detail.append(f"RHR {snap.resting_hr:.0f}bpm")
    if detail:
        lines.append("  ".join(detail))
    if snap.sleep_hours:
        s = f"😴 Sleep: {snap.sleep_hours:.1f}h"
        extras = []
        if snap.sleep_deep_hours:
            extras.append(f"deep {snap.sleep_deep_hours:.1f}h")
        if snap.sleep_rem_hours:
            extras.append(f"REM {snap.sleep_rem_hours:.1f}h")
        if extras:
            s += f" ({', '.join(extras)})"
        lines.append(s)
    if snap.strain is not None:
        lines.append(f"💪 Strain: {snap.strain:.1f}")
    return "\n".join(lines)


def _fmt_day_report(log, prefs, user_name: str) -> str:
    """Template-based end-of-day performance recap."""
    name = user_name or "hey"
    cal = round(log.total_calories or 0)
    pro = round(log.total_protein or 0)
    cal_t = prefs.calorie_target if prefs else None
    pro_t = prefs.protein_target if prefs else None

    lines = [f"<b>📊 Day recap — {log.date}</b>", ""]

    if cal_t:
        pct = int(cal / cal_t * 100)
        diff = cal - cal_t
        icon = "✅" if abs(diff) <= cal_t * 0.1 else ("⚠️" if diff < 0 else "🔴")
        lines.append(f"Calories  {icon}  <b>{cal}</b> / {cal_t}  ({diff:+d})")
    else:
        lines.append(f"Calories  <b>{cal}</b>")

    if pro_t:
        pct_p = int(pro / pro_t * 100)
        icon_p = "✅" if pct_p >= 90 else ("⚠️" if pct_p >= 70 else "🔴")
        lines.append(f"Protein   {icon_p}  <b>{pro}g</b> / {pro_t}g  ({pct_p}%)")
    else:
        lines.append(f"Protein   <b>{pro}g</b>")

    wo = "✅" if log.workout_completed else "✗"
    ca = "✅" if log.cardio_completed else "✗"
    lines.append(f"Workout   {wo}   Cardio  {ca}")

    if log.total_water_ml:
        lines.append(f"Water     <b>{log.total_water_ml:.0f}ml</b>")

    notes = []
    if pro_t and pro < pro_t * 0.7:
        notes.append(f"Protein was {pro_t - pro:.0f}g short — prioritize it tomorrow")
    elif pro_t and pro >= pro_t * 0.9:
        notes.append("Protein nailed")
    if cal_t and abs(cal - cal_t) <= cal_t * 0.08:
        notes.append("calories on target")
    elif cal_t and cal < cal_t * 0.85:
        notes.append(f"calories {cal_t - cal:.0f} under — make sure it's intentional")
    if log.workout_completed:
        notes.append("workout done")

    if notes:
        lines.append("")
        lines.append("💡 " + ", ".join(notes).capitalize() + ".")

    if log.status == "open":
        lines.append("\nDone for the day? Close it out with /close")

    return "\n".join(lines)


async def _run_whoop_sync():
    """Pull latest Whoop data for all connected users and send notifications for new recovery data."""
    from db.database import AsyncSessionLocal
    from db.queries import get_users_with_whoop, get_recent_health_snapshots
    from api.whoop import sync_user_whoop

    today = date.today()
    stale = [k for k, v in _whoop_notified.items() if v != str(today)]
    for k in stale:
        del _whoop_notified[k]

    async with AsyncSessionLocal() as db:
        try:
            users = await get_users_with_whoop(db)
        except Exception as e:
            logger.error(f"Whoop sync: failed to get users: {e}")
            return

        total = 0
        for user in users:
            try:
                old_snaps = await get_recent_health_snapshots(db, user.id, days=1)
                old_recovery = old_snaps[0].recovery_score if old_snaps else None

                synced = await sync_user_whoop(db, user, days=2)
                total += synced

                if synced > 0 and user.telegram_id:
                    new_snaps = await get_recent_health_snapshots(db, user.id, days=1)
                    if new_snaps:
                        snap = new_snaps[0]
                        notif_key = f"{user.id}:{snap.date}"
                        if (snap.recovery_score is not None
                                and snap.recovery_score != old_recovery
                                and notif_key not in _whoop_notified):
                            _whoop_notified[notif_key] = str(today)
                            msg = _fmt_whoop_notification(snap)
                            if msg:
                                await _send(user.telegram_id, msg)
            except Exception as e:
                logger.error(f"Whoop sync/notify failed for user {user.id}: {e}")

    logger.info(f"Whoop sync complete: {total} user-days updated")


def start_scheduler():
    if _scheduler.running:
        return
    _scheduler.add_job(
        _run_reminders,
        IntervalTrigger(minutes=30),
        id="proactive_reminders",
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.add_job(
        _run_whoop_sync,
        IntervalTrigger(hours=2),
        id="whoop_sync",
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info("Proactive scheduler started (reminders every 30 min, Whoop sync every 2 hr)")


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
