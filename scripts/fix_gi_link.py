"""Restore Gi's Telegram → canonical link, broken when cleanup deleted his pointer.

Gi's canonical account is id=5 (iMessage identity, full history). His Telegram
identity (telegram_id 5526578962) was a linked pointer row (deleted id=9). After
deletion his Telegram message today created phantom id=19 → welcome sequence.

Fix: repoint id=19 (which already carries telegram_id 5526578962) at canonical
id=5 via linked_to_user_id, and move its stray conversation into id=5's history.
Read-only unless APPLY=1.
"""
import asyncio, os
from dotenv import load_dotenv
load_dotenv(override=True)
from sqlalchemy import select, update
from db.database import AsyncSessionLocal
from db.models import User, ConversationLog
from db.queries import resolve_user

APPLY = os.environ.get("APPLY") == "1"
PHANTOM_ID = 19
CANONICAL_ID = 5


async def main():
    async with AsyncSessionLocal() as db:
        ph = (await db.execute(select(User).where(User.id == PHANTOM_ID))).scalar_one_or_none()
        can = (await db.execute(select(User).where(User.id == CANONICAL_ID))).scalar_one_or_none()
        assert ph and can, "phantom or canonical missing"
        assert ph.telegram_id == "5526578962", f"unexpected phantom tg {ph.telegram_id!r}"
        assert can.name == "Gi", f"unexpected canonical {can.name!r}"
        nconv = await db.scalar(select(__import__("sqlalchemy").func.count(ConversationLog.id))
                                .where(ConversationLog.user_id == PHANTOM_ID))
        print(f"phantom id={PHANTOM_ID} tg={ph.telegram_id} → link to canonical id={CANONICAL_ID} ({can.name})")
        print(f"  + move {nconv} stray conversation(s) to id={CANONICAL_ID}")

        if not APPLY:
            print("\n[DRY RUN] APPLY=1 to commit.")
            return

        await db.execute(update(User).where(User.id == PHANTOM_ID)
                         .values(linked_to_user_id=CANONICAL_ID))
        await db.execute(update(ConversationLog).where(ConversationLog.user_id == PHANTOM_ID)
                         .values(user_id=CANONICAL_ID))
        await db.commit()

        # verify resolution now lands on canonical
        resolved = await resolve_user(db, "5526578962")
        print(f"\n[APPLIED] resolve_user('5526578962') → id={resolved.id} "
              f"name={resolved.name!r} onboarded={resolved.onboarding_completed}")
        assert resolved.id == CANONICAL_ID, "resolution still wrong!"
        print("✓ Gi's Telegram now resolves to his canonical account.")


if __name__ == "__main__":
    asyncio.run(main())
