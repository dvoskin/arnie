"""
Proactive messaging scheduler.
Runs every 30 minutes, checks each user's local time, and sends
contextual nudges within their wake/sleep window.
Only fires for users with proactive_messaging_enabled = True.
"""
import logging
import os
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


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
    _scheduler.start()
    logger.info("Proactive scheduler started (every 30 min)")


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
