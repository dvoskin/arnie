"""
Proactive messaging scheduler.
Runs every 30 minutes, checks each user's local time, and sends
contextual nudges within their wake/sleep window.
Only fires for users with proactive_messaging_enabled = True.
"""
import logging
import os
from datetime import datetime, date

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Track which (user_id, date) pairs we've already sent a Whoop notification for
# so we don't spam users on every 2-hour sync cycle.
_whoop_notified: dict = {}


async def _send(telegram_id: str, text: str):
    from telegram import Bot
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=telegram_id, text=text, parse_mode="HTML")
        await bot.close()
    except Exception as e:
        logger.error(f"Proactive send failed → {telegram_id}: {e}")


def _in_window(hhmm: str, wake: str, sleep: str) -> bool:
    return wake <= hhmm <= sleep


async def _run_reminders():
    from db.database import AsyncSessionLocal
    from db.queries import get_all_active_users, get_today_log

    async with AsyncSessionLocal() as db:
        users = await get_all_active_users(db)

        for user in users:
            prefs = user.preferences
            try:
                tz = pytz.timezone(user.timezone or "UTC")
                now = datetime.now(tz)
                hhmm = now.strftime("%H:%M")
                hour = now.hour
                minute = now.minute
                log = await get_today_log(db, user.id, user.timezone or "UTC")
                name = user.name or "hey"

                # ── End-of-day report (22:00–22:30) — ALL active users ─────────
                if hour == 22 and minute < 30 and log and log.total_calories > 0:
                    report = _fmt_day_report(log, prefs, name)
                    await _send(user.telegram_id, report)
                    continue  # don't also send proactive nudge at 10pm

            except Exception as e:
                logger.error(f"Day report error for user {user.id}: {e}")

            # Proactive nudges are opt-in only
            if not prefs or not prefs.proactive_messaging_enabled:
                continue

            try:
                tz = pytz.timezone(user.timezone or "UTC")
                now = datetime.now(tz)
                hhmm = now.strftime("%H:%M")
                hour = now.hour
                minute = now.minute

                wake = prefs.wake_time or "07:00"
                sleep = prefs.sleep_time or "23:00"
                if not _in_window(hhmm, wake, sleep):
                    continue

                log = await get_today_log(db, user.id, user.timezone or "UTC")
                name = user.name or "hey"

                # ── Morning check-in (30 min after wake time) ─────────────────
                wake_h, wake_m = int(wake.split(":")[0]), int(wake.split(":")[1])
                target_morning_h = wake_h
                target_morning_m = wake_m + 30
                if target_morning_m >= 60:
                    target_morning_h += 1
                    target_morning_m -= 60

                if hour == target_morning_h and 0 <= minute - target_morning_m < 30:
                    if not log or log.total_calories == 0:
                        await _send(
                            user.telegram_id,
                            f"Morning, {name}. Log your weight if you have it, then tell me what you had for breakfast."
                        )

                # ── Midday protein check (12:00–12:30) ────────────────────────
                elif hour == 12 and minute < 30 and prefs.protein_target:
                    current_p = log.total_protein if log else 0
                    pct = int(current_p / prefs.protein_target * 100)
                    if pct < 35:
                        await _send(
                            user.telegram_id,
                            f"Midday check — {current_p:.0f}g protein so far ({pct}% of {prefs.protein_target}g).\n"
                            f"You're behind. Prioritize protein at lunch."
                        )
                    elif pct >= 35:
                        rem = prefs.protein_target - current_p
                        await _send(
                            user.telegram_id,
                            f"Halfway through the day — {current_p:.0f}g protein down, {rem:.0f}g to go. On track."
                        )

                # ── Afternoon workout nudge (16:00–16:30) ─────────────────────
                elif hour == 16 and minute < 30:
                    if log and not log.workout_completed:
                        await _send(
                            user.telegram_id,
                            f"4pm — workout not logged yet, {name}. Still happening today?"
                        )

                # ── Evening pacing (19:00–19:30) ──────────────────────────────
                elif hour == 19 and minute < 30 and log:
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
                        await _send(
                            user.telegram_id,
                            "Evening check:\n" + "\n".join(f"• {p}" for p in parts) +
                            "\n\nWhat's dinner looking like?"
                        )
                    elif log.total_calories > 0:
                        await _send(
                            user.telegram_id,
                            f"Looking solid today, {name}. Log dinner when you have it."
                        )

                # ── Night closeout nudge (21:00–21:30) ────────────────────────
                elif hour == 21 and minute < 30:
                    if log and log.status == "open" and log.total_calories > 0:
                        await _send(
                            user.telegram_id,
                            "Day still open. Done eating? Send me anything you missed and close it out."
                        )

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

    # Coaching note
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
    # Prune stale notification records (keep only today's)
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
                # Snapshot before sync — did we already have recovery data?
                old_snaps = await get_recent_health_snapshots(db, user.id, days=1)
                old_recovery = old_snaps[0].recovery_score if old_snaps else None

                synced = await sync_user_whoop(db, user, days=2)
                total += synced

                if synced > 0 and user.telegram_id:
                    new_snaps = await get_recent_health_snapshots(db, user.id, days=1)
                    if new_snaps:
                        snap = new_snaps[0]
                        notif_key = f"{user.id}:{snap.date}"
                        # Only notify if recovery just became available for the first time today
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
    # Whoop sync every 2 hours — frequent enough to catch new recovery data
    # (Whoop scores recovery after the night's sleep, usually available by ~9am)
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
