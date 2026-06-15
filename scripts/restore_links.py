"""Restore cross-platform link pointers deleted by the user cleanup.

Fill MAPPING with the {telegram_id: linked_to_user_id} pairs recovered from the
Render backup (the rows whose linked_to_user_id was NON-null). For each:
  - if a User row with that telegram_id already exists (e.g. a phantom created
    when the user messaged post-break), repoint it at the canonical + move its
    stray conversations onto the canonical;
  - otherwise create a fresh pointer row.
Then verify resolve_user(telegram_id) lands on the canonical.

Read-only unless APPLY=1. Refuses to link to a non-existent or non-onboarded
canonical (prevents wiring an identity into the wrong / empty brain).
"""
import asyncio, os
from dotenv import load_dotenv
load_dotenv(override=True)
from sqlalchemy import select, update, func
from db.database import AsyncSessionLocal
from db.models import User, ConversationLog
from db.queries import resolve_user

APPLY = os.environ.get("APPLY") == "1"

# ── FILL FROM BACKUP (Step 2 query output): telegram_id -> canonical user id ──
MAPPING: dict[str, int] = {
    "6996307425": 2,   # Danny (confirmed — his Telegram)
    "1020819916": 4,   # Ryan
}


async def main():
    if not MAPPING:
        print("MAPPING is empty — paste the backup's telegram_id→linked_to_user_id "
              "pairs into this file first.")
        return
    async with AsyncSessionLocal() as db:
        for tg, canonical_id in MAPPING.items():
            can = (await db.execute(select(User).where(User.id == canonical_id))).scalar_one_or_none()
            if not can:
                print(f"  ✗ {tg} → id={canonical_id}: canonical MISSING, skipping")
                continue
            if not can.onboarding_completed:
                print(f"  ✗ {tg} → id={canonical_id} ({can.name}): canonical not onboarded, skipping")
                continue
            existing = (await db.execute(select(User).where(User.telegram_id == tg))).scalar_one_or_none()
            nconv = 0
            if existing:
                nconv = await db.scalar(select(func.count(ConversationLog.id))
                                        .where(ConversationLog.user_id == existing.id)) or 0
            action = (f"repoint existing id={existing.id} (+move {nconv} convs)"
                      if existing else "create new pointer row")
            print(f"  {tg} → canonical id={canonical_id} ({can.name}): {action}")

            if not APPLY:
                continue
            if existing:
                await db.execute(update(ConversationLog).where(ConversationLog.user_id == existing.id)
                                 .values(user_id=canonical_id))
                await db.execute(update(User).where(User.id == existing.id)
                                 .values(linked_to_user_id=canonical_id))
            else:
                db.add(User(telegram_id=tg, linked_to_user_id=canonical_id,
                            onboarding_completed=False))
            await db.commit()
            resolved = await resolve_user(db, tg)
            ok = resolved.id == canonical_id
            print(f"    {'✓' if ok else '✗'} resolve_user({tg}) → id={resolved.id} ({resolved.name})")

    print("\n[DRY RUN] APPLY=1 to commit." if not APPLY else "\n[APPLIED]")


if __name__ == "__main__":
    asyncio.run(main())
