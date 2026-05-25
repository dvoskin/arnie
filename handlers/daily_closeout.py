"""
Generates the end-of-day coaching summary.
"""
from db.models import User, DailyLog
from memory.memory_manager import read_memory
from core.llm import chat

_SYSTEM = """You are Arnie. Write a concise end-of-day coaching summary.

Format:
Line 1: "Day closed — [date]"
Macros vs targets (if targets are set)
Workout/cardio status
1–2 sentence coaching observation (honest, direct)
One concrete recommendation for tomorrow

Max 8 lines. No headers. No tables. Direct tone."""


async def generate_closeout(user: User, log: DailyLog, db) -> str:
    memory = await read_memory(user.telegram_id)
    prefs = user.preferences

    cal_target = prefs.calorie_target if prefs else None
    pro_target = prefs.protein_target if prefs else None

    context = (
        f"User: {user.name}  Goal: {user.primary_goal}\n"
        f"Targets: {cal_target or 'none'} cal / {pro_target or 'none'}g protein\n\n"
        f"Totals:\n"
        f"  Calories: {log.total_calories:.0f}\n"
        f"  Protein:  {log.total_protein:.0f}g\n"
        f"  Carbs:    {log.total_carbs:.0f}g\n"
        f"  Fats:     {log.total_fats:.0f}g\n"
        f"  Water:    {log.total_water_ml:.0f}ml\n"
        f"  Workout:  {'done' if log.workout_completed else 'not logged'}\n"
        f"  Cardio:   {'done' if log.cardio_completed else 'not logged'}\n"
        f"  Sleep logged: {log.sleep_hours or 'no'}\n"
        f"  Food entries: {len(log.food_entries) if log.food_entries else 0}\n"
        f"  Exercise entries: {len(log.exercise_entries) if log.exercise_entries else 0}\n\n"
        f"Memory excerpt:\n{memory[:600] if memory else 'none'}"
    )

    result = await chat(
        messages=[{"role": "user", "content": f"Close out today:\n{context}"}],
        system=_SYSTEM,
        tools=False,
        max_tokens=350,
    )
    return result["text"]
