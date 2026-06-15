"""Force-run Danny's profile synthesis against prod (bypasses the 3h throttle).

Runs the live extraction with all current optimizations (behavioral signals,
lane guards, classification, inference prompt), upserts, prunes, regenerates bio.
"""
import asyncio
from dotenv import load_dotenv
load_dotenv(override=True)

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from db.database import AsyncSessionLocal
from db.models import User
from memory.profile_updater import maybe_update_profile


async def main():
    async with AsyncSessionLocal() as db:
        user = (await db.execute(
            select(User).options(selectinload(User.preferences)).where(User.id == 2)
        )).scalar_one()
        print(f"Force-syncing {user.name} (id={user.id})...")
        changed = await maybe_update_profile(user, db, force=True)
        print(f"Synthesis ran. attributes upserted: {changed}")


if __name__ == "__main__":
    asyncio.run(main())
