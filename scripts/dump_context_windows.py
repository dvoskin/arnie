"""READ-ONLY: dump conversation + food-entry context around specific incidents."""
import asyncio, os
from datetime import datetime, timedelta
from sqlalchemy import select, or_
from db.database import AsyncSessionLocal
from db.models import User, ConversationLog, DailyLog, FoodEntry

# (label, ISO timestamp center, minutes-window)
WINDOWS = [
    ("FORGET-THE-ROYO (turn#4895)", "2026-06-26 02:17:13", 12),
    ("ROYO CHALLAH double-log 06-07", "2026-06-07", None),   # whole-day food scan
    ("ROYO TOAST double-log 06-28", "2026-06-28 00:49:15", 25),
]

async def danny_ids(db):
    res = await db.execute(select(User).where(or_(User.name.ilike("%danny%"), User.name.ilike("%daniel%"))))
    return sorted({u.id for u in res.scalars().all()})

async def main():
    async with AsyncSessionLocal() as db:
        ids = await danny_ids(db)
        for label, center, win in WINDOWS:
            print("=" * 90); print(label); print("=" * 90)
            if win is not None:
                c = datetime.fromisoformat(center)
                lo, hi = c - timedelta(minutes=win), c + timedelta(minutes=win)
                res = await db.execute(
                    select(ConversationLog).where(
                        ConversationLog.user_id.in_(ids),
                        ConversationLog.timestamp >= lo,
                        ConversationLog.timestamp <= hi,
                    ).order_by(ConversationLog.timestamp.asc())
                )
                seen = set()
                for t in res.scalars().all():
                    k = (t.timestamp, (t.raw_message or "")[:80])
                    if k in seen: continue
                    seen.add(k)
                    print(f"\n  {t.timestamp} [{t.platform}] skills=[{t.skills_fired}]")
                    print(f"  U: {(t.raw_message or '')[:260]}")
                    print(f"  A: {(t.response or '')[:340]}")
                    if t.cards_json:
                        print(f"  cards: {t.cards_json[:200]}")
            else:
                # whole-day food entries
                day = datetime.fromisoformat(center).date()
                res = await db.execute(select(DailyLog).where(DailyLog.user_id.in_(ids), DailyLog.date == day))
                dl_ids = [d.id for d in res.scalars().all()]
                res = await db.execute(
                    select(FoodEntry).where(FoodEntry.daily_log_id.in_(dl_ids)).order_by(FoodEntry.timestamp.asc())
                )
                for f in res.scalars().all():
                    print(f"  {f.timestamp} id={f.id} dl={f.daily_log_id} '{f.parsed_food_name}' "
                          f"qty={f.quantity} {f.calories}kcal P{f.protein} raw={(f.raw_input or '')[:60]!r}")
            print()

if __name__ == "__main__":
    asyncio.run(main())
