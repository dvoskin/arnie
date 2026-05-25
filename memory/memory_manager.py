"""
Per-user markdown memory files stored at users/{telegram_id}/arnie_memory.md
These capture behavioral patterns, preferences, and coaching notes that aren't
otherwise derivable from the structured DB.
"""
import aiofiles
from pathlib import Path
from datetime import datetime
from db.models import User

USERS_DIR = Path("users")


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
