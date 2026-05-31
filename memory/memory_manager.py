"""
Per-user markdown memory files stored at users/{telegram_id}/arnie_memory.md
These capture behavioral patterns, preferences, and coaching notes that aren't
otherwise derivable from the structured DB.
"""
import os
import logging
import aiofiles
from pathlib import Path
from datetime import datetime
from db.models import User

logger = logging.getLogger(__name__)


def resolve_users_dir() -> Path:
    """
    Pick a PERSISTENT base dir for per-user memory/profile files.

    Previously a relative "users" dir = ephemeral on Render, wiped on every deploy,
    silently erasing Arnie's accumulated understanding of each user. Now defaults to
    the same persistent disk as the database (e.g. /data/users when DATABASE_URL
    points at /data/arnie.db), honors ARNIE_USERS_DIR if set, with a /tmp fallback
    mirroring db/database.py's logic.
    """
    explicit = os.getenv("ARNIE_USERS_DIR")
    candidates = [explicit] if explicit else []
    if not explicit:
        db_url = os.getenv("DATABASE_URL", "")
        if "sqlite" in db_url and "///" in db_url:
            db_path = db_url.split("///")[-1]
            if db_path.startswith("/"):
                candidates.append(str(Path(db_path).parent / "users"))
        candidates.append("users")  # local-dev relative fallback
    candidates.append("/tmp/arnie_users")
    for d in candidates:
        try:
            Path(d).mkdir(parents=True, exist_ok=True)
            return Path(d)
        except (PermissionError, OSError) as e:
            logger.warning(f"Users dir {d} not usable ({e}); trying next.")
    return Path("users")


USERS_DIR = resolve_users_dir()
logger.info(f"Per-user memory dir: {USERS_DIR}")


def _path(telegram_id: str) -> Path:
    d = USERS_DIR / str(telegram_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / "arnie_memory.md"


async def read_memory(telegram_id: str) -> str:
    p = _path(telegram_id)
    if not p.exists():
        return ""
    async with aiofiles.open(p, "r") as f:
        return await f.read()


async def write_memory(telegram_id: str, content: str):
    async with aiofiles.open(_path(telegram_id), "w") as f:
        await f.write(content)


async def init_memory(user: User) -> str:
    """Create the initial memory file after onboarding completes."""
    existing = await read_memory(user.telegram_id)
    if existing:
        return existing

    content = f"""# Arnie Memory — {user.name or "User"} ({user.telegram_id})
Created: {datetime.now().strftime("%Y-%m-%d")}

## Profile Summary
- Name: {user.name or "Unknown"}
- Goal: {user.primary_goal or "Not set"}
- Training experience: {user.training_experience or "Not set"}
- Dietary preferences: {user.dietary_preferences or "None"}
- Injuries / limitations: {user.injuries or "None"}

## Goals
- Primary: {user.primary_goal or "Not set"}
- Target weight: {user.goal_weight_kg or "Not set"} kg

## Coaching Preferences
- Style: {getattr(user.preferences, "coaching_style", "balanced") if user.preferences else "balanced"}
- Accountability: {getattr(user.preferences, "accountability_level", "medium") if user.preferences else "medium"}
- Response length: {getattr(user.preferences, "preferred_response_length", "medium") if user.preferences else "medium"}

## Nutrition Tendencies
(No data yet)

## Training Tendencies
(No data yet)

## Adherence Notes
(No data yet)

## Common Foods
(No data yet)

## Successful Interventions
(No data yet)

## Recurring Struggles
(No data yet)

## Behavioral Notes
(No data yet)
"""
    await write_memory(user.telegram_id, content)
    return content


async def append_memory_update(telegram_id: str, update: str, reasoning: str):
    """Append a concise, timestamped note to the memory file."""
    existing = await read_memory(telegram_id)
    if not existing:
        existing = f"# Arnie Memory — {telegram_id}\n\n"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    block = f"\n---\n*{ts} — {reasoning}*\n{update.strip()}\n"
    await write_memory(telegram_id, existing + block)


async def clear_memory(telegram_id: str):
    """Delete the memory file entirely (used on full account reset)."""
    import shutil
    p = USERS_DIR / str(telegram_id)
    if p.exists():
        shutil.rmtree(p)
