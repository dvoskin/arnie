"""Read-only review dump: Danny's last ~3h of conversation + workout entries.

Pulls from whatever DATABASE_URL is configured (production Postgres). Writes
nothing. Identifies Danny by name match, prints an interleaved timeline of
conversation turns and logged exercise/food/weight rows so we can eyeball
glitches, dup logs, and whether pacing/session-state coaching surfaced.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, or_, func
from db.database import AsyncSessionLocal
from db.models import (
    User, ConversationLog, DailyLog, FoodEntry, ExerciseEntry, BodyMetric,
)

HOURS = float(os.environ.get("REVIEW_HOURS", "3.5"))


async def main():
    async with AsyncSessionLocal() as db:
        # Find Danny — name ILIKE, prefer the most active recent account.
        res = await db.execute(
            select(User).where(
                or_(User.name.ilike("%danny%"), User.name.ilike("%daniel%"))
            )
        )
        users = res.scalars().all()
        if not users:
            print("No user matching danny/daniel found.")
            return

        print(f"Matched {len(users)} candidate user(s):")
        for u in users:
            cnt = await db.scalar(
                select(func.count(ConversationLog.id)).where(ConversationLog.user_id == u.id)
            )
            print(f"  id={u.id} name={u.name!r} tg={u.telegram_id!r} "
                  f"goal={u.primary_goal} convs={cnt} tz={u.timezone}")

        # Pick the candidate with the most recent conversation activity.
        best = None
        best_ts = None
        for u in users:
            last = await db.scalar(
                select(func.max(ConversationLog.timestamp)).where(ConversationLog.user_id == u.id)
            )
            if last and (best_ts is None or last > best_ts):
                best_ts, best = last, u
        user = best or users[0]
        print(f"\n=== Reviewing user id={user.id} ({user.name}) tz={user.timezone} ===")
        print(f"latest conversation ts (UTC): {best_ts}")

        cutoff = (best_ts or datetime.now(timezone.utc)) - timedelta(hours=HOURS)
        # Normalize cutoff to naive UTC if stored timestamps are naive.
        if best_ts is not None and best_ts.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=None)

        # Conversation turns in window
        convs = (await db.execute(
            select(ConversationLog)
            .where(ConversationLog.user_id == user.id, ConversationLog.timestamp >= cutoff)
            .order_by(ConversationLog.timestamp)
        )).scalars().all()

        # Exercise + food + weight rows in window (join through daily_logs for entries)
        ex_rows = (await db.execute(
            select(ExerciseEntry)
            .join(DailyLog, ExerciseEntry.daily_log_id == DailyLog.id)
            .where(DailyLog.user_id == user.id, ExerciseEntry.timestamp >= cutoff)
            .order_by(ExerciseEntry.timestamp)
        )).scalars().all()
        food_rows = (await db.execute(
            select(FoodEntry)
            .join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
            .where(DailyLog.user_id == user.id, FoodEntry.timestamp >= cutoff)
            .order_by(FoodEntry.timestamp)
        )).scalars().all()
        wt_rows = (await db.execute(
            select(BodyMetric)
            .where(BodyMetric.user_id == user.id, BodyMetric.timestamp >= cutoff)
            .order_by(BodyMetric.timestamp)
        )).scalars().all()

        # Build a merged timeline
        events = []
        for c in convs:
            events.append((c.timestamp, "CONV", c))
        for e in ex_rows:
            events.append((e.timestamp, "EXLOG", e))
        for f in food_rows:
            events.append((f.timestamp, "FOODLOG", f))
        for w in wt_rows:
            events.append((w.timestamp, "WEIGHT", w))
        events.sort(key=lambda x: (x[0] or datetime.min.replace(tzinfo=timezone.utc)))

        print(f"\nwindow: last {HOURS}h  |  {len(convs)} conv turns, "
              f"{len(ex_rows)} exercise rows, {len(food_rows)} food rows, {len(wt_rows)} weight rows\n")
        print("=" * 100)

        def ts(t):
            return t.strftime("%H:%M:%S") if t else "??:??:??"

        for t, kind, obj in events:
            if kind == "CONV":
                src = obj.source_type or "text"
                skills = obj.skills_fired or "-"
                raw = (obj.raw_message or "").replace("\n", " ⏎ ")
                resp = (obj.response or "").replace("\n", " ⏎ ")
                if src == "proactive":
                    print(f"[{ts(t)}] 🔔 PROACTIVE (slot={skills}):")
                    print(f"           ARNIE: {resp}")
                else:
                    print(f"[{ts(t)}] 👤 DANNY ({src}): {raw}")
                    print(f"           🤖 ARNIE [{skills}]: {resp}")
            elif kind == "EXLOG":
                print(f"   └─[{ts(t)}] 🏋️  EX#{obj.id}: name={obj.exercise_name!r} "
                      f"sets={obj.sets} reps={obj.reps!r} wt={obj.weight} rir={obj.rir} "
                      f"dur={obj.duration_minutes} cardio={obj.cardio_type} src={obj.source_type}"
                      + (f" notes={obj.notes!r}" if obj.notes else ""))
            elif kind == "FOODLOG":
                print(f"   └─[{ts(t)}] 🍽️  FOOD#{obj.id}: {obj.parsed_food_name!r} qty={obj.quantity!r} "
                      f"cal={obj.calories} P={obj.protein} C={obj.carbs} F={obj.fats} "
                      f"est={obj.estimated_flag} conf={obj.confidence_score} src={obj.source_type} "
                      f"photo={obj.from_photo} meal={obj.meal_type}")
            elif kind == "WEIGHT":
                print(f"   └─[{ts(t)}] ⚖️  WEIGHT#{obj.id}: {obj.weight_kg}kg ctx={obj.context}")
        print("=" * 100)


if __name__ == "__main__":
    asyncio.run(main())
