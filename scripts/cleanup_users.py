"""Prune junk accounts + deactivate dormant real users (prod).

DELETE (permanent, cascades): never-used + incomplete-onboarding single-touch signups.
DEACTIVATE (data preserved): real onboarded users idle >4d → proactive off + inactive flag.

Read-only by default. Set APPLY=1 to commit. A safety guard refuses to DELETE any
user who is onboarded AND has >5 conversations (so a shifted id can't nuke a real user).
"""
import asyncio
import os
from dotenv import load_dotenv
load_dotenv(override=True)

from sqlalchemy import select, delete, update, func
from db.database import AsyncSessionLocal
from db.models import (
    User, UserPreferences, DailyLog, FoodEntry, ExerciseEntry, BodyMetric,
    ConversationLog, MemoryUpdate, HealthSnapshot, WearableDevice, WearableMetric,
    PendingQuestion, Feedback, UserFoodMatch, WaterEntry, UserAttribute, WorkoutProgram,
)

APPLY = os.environ.get("APPLY") == "1"
DELETE_IDS = [1, 6, 7, 9, 11]
DEACTIVATE_IDS = [4, 8, 10, 14]

USER_KEYED = [
    BodyMetric, ConversationLog, MemoryUpdate, HealthSnapshot, WearableDevice,
    WearableMetric, PendingQuestion, Feedback, UserFoodMatch, WaterEntry,
    UserAttribute, WorkoutProgram,
]


async def _is_protected_link(db, user) -> bool:
    """True if `user` participates in a cross-platform link in EITHER direction —
    it points at a canonical (linked_to_user_id set) OR another row points at it
    (some secondary's linked_to_user_id == user.id). Such a row looks exactly
    like junk (no name, not onboarded, ~1 conv) because its real history lives on
    the canonical account; deleting it breaks that user's other platform (the
    Gi-Telegram incident). The delete loop must refuse it either way."""
    links_out = user.linked_to_user_id is not None
    links_in = await db.scalar(select(func.count(User.id))
                               .where(User.linked_to_user_id == user.id)) or 0
    return links_out or bool(links_in)


async def main():
    async with AsyncSessionLocal() as db:
        print(f"{'DRY RUN — no changes' if not APPLY else 'APPLYING CHANGES'}\n")

        # ---- DELETE group ----
        print("=== DELETE (permanent) ===")
        for uid in DELETE_IDS:
            u = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
            if not u:
                print(f"  id={uid}: not found, skipping")
                continue
            nconv = await db.scalar(select(func.count(ConversationLog.id))
                                    .where(ConversationLog.user_id == uid)) or 0
            # SAFETY GUARD — never delete an onboarded, conversation-rich account
            if u.onboarding_completed and nconv > 5:
                print(f"  id={uid} ({u.name}): REFUSED — onboarded with {nconv} convs. "
                      f"Not junk; skipping.")
                continue
            # SAFETY GUARD — never delete a cross-platform LINK identity. A linked
            # secondary pointer looks exactly like junk (no name, not onboarded, ~1
            # conv) because its real history lives on the canonical account. Deleting
            # it breaks that user's other platform (this is the Gi-Telegram incident).
            if await _is_protected_link(db, u):
                links_in = await db.scalar(select(func.count(User.id))
                                           .where(User.linked_to_user_id == uid)) or 0
                print(f"  id={uid} ({u.name}): REFUSED — cross-platform link "
                      f"(linked_to={u.linked_to_user_id}, linked_by={links_in}). Not junk.")
                continue

            log_ids = select(DailyLog.id).where(DailyLog.user_id == uid)
            counts = {
                "food": await db.scalar(select(func.count(FoodEntry.id))
                                        .where(FoodEntry.daily_log_id.in_(log_ids))) or 0,
                "exercise": await db.scalar(select(func.count(ExerciseEntry.id))
                                            .where(ExerciseEntry.daily_log_id.in_(log_ids))) or 0,
                "daily_logs": await db.scalar(select(func.count(DailyLog.id))
                                              .where(DailyLog.user_id == uid)) or 0,
                "convs": nconv,
                "attrs": await db.scalar(select(func.count(UserAttribute.id))
                                         .where(UserAttribute.user_id == uid)) or 0,
            }
            print(f"  id={uid} name={u.name!r} tg={u.telegram_id!r} onbd={u.onboarding_completed} "
                  f"→ DELETE  (children: {counts})")

            if APPLY:
                await db.execute(delete(FoodEntry).where(FoodEntry.daily_log_id.in_(log_ids)))
                await db.execute(delete(ExerciseEntry).where(ExerciseEntry.daily_log_id.in_(log_ids)))
                await db.execute(delete(DailyLog).where(DailyLog.user_id == uid))
                for model in USER_KEYED:
                    await db.execute(delete(model).where(model.user_id == uid))
                await db.execute(delete(UserPreferences).where(UserPreferences.user_id == uid))
                await db.execute(delete(User).where(User.id == uid))

        # ---- DEACTIVATE group ----
        print("\n=== DEACTIVATE (data preserved, proactive off) ===")
        for uid in DEACTIVATE_IDS:
            u = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
            if not u:
                print(f"  id={uid}: not found, skipping")
                continue
            print(f"  id={uid} name={u.name!r} → proactive_messaging_enabled=False, "
                  f"subscription_status='inactive'")
            if APPLY:
                await db.execute(update(UserPreferences)
                                 .where(UserPreferences.user_id == uid)
                                 .values(proactive_messaging_enabled=False))
                await db.execute(update(User).where(User.id == uid)
                                 .values(subscription_status="inactive"))

        if APPLY:
            await db.commit()
            remaining = await db.scalar(select(func.count(User.id)))
            print(f"\n[APPLIED] users remaining: {remaining}")
        else:
            print("\n[DRY RUN] Re-run with APPLY=1 to commit.")


if __name__ == "__main__":
    asyncio.run(main())
