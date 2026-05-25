"""
Proactive messaging scheduler.
Only fires for users who have explicitly enabled proactive_messaging_enabled.
Respects timezone, wake/sleep window, and reminder frequency preference.
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
        await bot.send_message(chat_id=telegram_id, text=text)
        await bot.close()
    except Exception as e:
        logger.error(f"Proactive send failed → {telegram_id}: {e}")


async def _run_reminders():
    """Evaluate all active users and send time-appropriate nudges."""
    from db.database import AsyncSessionLocal
    from db.queries import get_all_active_users, get_today_log

    async with AsyncSessionLocal() as db:
        users = await get_all_active_users(db)

        for user in users:
            prefs = user.preferences
            if not prefs or not prefs.proactive_messaging_enabled:
                continue

            tz = pytz.timezone(user.timezone or "UTC")
            now = datetime.now(tz)
            hhmm = now.strftime("%H:%M")

            wake = prefs.wake_time or "07:00"
            sleep = prefs.sleep_time or "23:00"
            if hhmm < wake or hhmm > sleep:
                continue

            hour = now.hour

            try:
                log = await get_today_log(db, user.id, user.timezone or "UTC")

                # Midday protein check (~12:00)
                if hour == 12 and prefs.protein_target:
                    current_p = log.total_protein if log else 0
                    remaining = prefs.protein_target - current_p
                    if remaining > prefs.protein_target * 0.65:
                        await _send(
                            user.telegram_id,
                            f"Midday check — {current_p:.0f}g protein logged so far. "
                            f"Still need {remaining:.0f}g. Stay on top of it.",
                        )

                # Evening protein/calorie check (~19:00)
                elif hour == 19 and log:
                    msgs = []
                    if prefs.protein_target:
                        rem_p = prefs.protein_target - log.total_protein
                        if rem_p > 35:
                            msgs.append(f"{rem_p:.0f}g protein still needed")
                    if prefs.calorie_target:
                        rem_c = prefs.calorie_target - log.total_calories
                        if rem_c > 300:
                            msgs.append(f"{rem_c:.0f} cal remaining")
                    if msgs:
                        await _send(
                            user.telegram_id,
                            "Evening check: " + " · ".join(msgs) + ". Plan dinner accordingly.",
                        )

                # Workout reminder (~16:00 if not yet logged)
                elif hour == 16 and log and not log.workout_completed:
                    await _send(
                        user.telegram_id,
                        f"Workout not logged yet today, {user.name or 'hey'}. Still on?",
                    )

                # Closeout reminder (~21:00 if day still open)
                elif hour == 21 and log and log.status == "open":
                    await _send(
                        user.telegram_id,
                        "Day still open — send me a closeout when you're done.",
                    )

            except Exception as e:
                logger.error(f"Reminder error for user {user.id}: {e}")


def start_scheduler():
    if _scheduler.running:
        return
    _scheduler.add_job(
        _run_reminders,
        IntervalTrigger(minutes=60),
        id="proactive_reminders",
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info("Proactive scheduler started (hourly)")


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
