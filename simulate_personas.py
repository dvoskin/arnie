"""
Multi-persona test: populates 4 realistic user profiles with 2 days of data each.
Generates dashboard links, no LLM calls needed.

Run from arnie/:
    .venv/bin/python test_personas.py
"""
import asyncio
import os
import sys
from datetime import date, timedelta
from dotenv import load_dotenv
load_dotenv(override=True)

GREEN  = "\033[92m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
YELLOW = "\033[93m"
RESET  = "\033[0m"

def info(s): print(f"{YELLOW}[INFO]{RESET} {s}")
def ok(s):   print(f"{GREEN}{BOLD}[OK  ]{RESET} {s}")
def sep():   print(f"\n{'─'*60}")

PERSONAS = [
    {
        "tg_id": "TEST_001",
        "name": "Marcus", "age": 28, "sex": "male",
        "height_cm": 182.9, "weight_kg": 88.5, "goal_kg": 81.0,
        "goal": "cut", "exp": "advanced",
        "diet": "none", "injuries": "none",
        "cal": 2100, "pro": 200,
        "days": [
            {  # Day 1 — solid day
                "foods": [
                    ("Oats + whey + blueberries", "1 bowl", 520, 42, 65, 8),
                    ("Greek yogurt", "200g", 140, 18, 12, 3),
                    ("Chicken + rice + veg", "meal prep", 620, 55, 65, 8),
                    ("Quest bar", "1 bar", 190, 21, 22, 7),
                    ("Salmon + sweet potato + broccoli", "dinner", 640, 48, 52, 18),
                ],
                "exercises": [
                    ("Squat", 4, "5,5,5,4", 140.0, False),
                    ("Romanian Deadlift", 3, "8,8,8", 100.0, False),
                    ("Leg Press", 3, "12,12,10", 180.0, False),
                    ("Leg Curl", 3, "12,12,12", 50.0, False),
                ],
                "water_ml": 2800,
                "workout": True,
                "cardio": False,
            },
            {  # Day 2 — lighter intake, cardio
                "foods": [
                    ("3 eggs scrambled + toast", "breakfast", 420, 30, 38, 15),
                    ("Protein shake", "1 scoop whey", 170, 30, 8, 3),
                    ("Turkey wrap", "lunch", 490, 40, 48, 12),
                    ("Apple + almond butter", "snack", 230, 6, 32, 10),
                    ("Chicken stir fry + rice", "dinner", 560, 45, 55, 12),
                ],
                "exercises": [
                    ("Incline Walk", None, None, None, True, "incline walk", 35),
                ],
                "water_ml": 3200,
                "workout": False,
                "cardio": True,
            },
        ],
    },
    {
        "tg_id": "TEST_002",
        "name": "Sarah", "age": 32, "sex": "female",
        "height_cm": 165.1, "weight_kg": 67.2, "goal_kg": 62.0,
        "goal": "cut", "exp": "intermediate",
        "diet": "vegetarian", "injuries": "none",
        "cal": 1650, "pro": 130,
        "days": [
            {  # Day 1 — protein struggle
                "foods": [
                    ("Overnight oats", "1 jar", 380, 15, 60, 8),
                    ("Latte", "medium oat milk", 150, 4, 22, 5),
                    ("Salad + chickpeas + feta", "lunch", 420, 22, 45, 14),
                    ("Hummus + veggies", "snack", 180, 6, 22, 8),
                    ("Pasta + marinara + parmesan", "dinner", 520, 20, 78, 12),
                ],
                "exercises": [
                    ("Bench Press", 3, "8,8,7", 47.7, False),
                    ("Incline Dumbbell Press", 3, "10,10,9", 18.1, False),
                    ("Cable Fly", 3, "12,12,12", 11.3, False),
                    ("Overhead Press", 3, "10,9,8", 29.5, False),
                ],
                "water_ml": 2000,
                "workout": True,
                "cardio": False,
            },
            {  # Day 2 — better protein, rest day
                "foods": [
                    ("Tofu scramble + toast", "breakfast", 350, 22, 30, 14),
                    ("Protein smoothie", "banana + pea protein + spinach", 310, 30, 38, 6),
                    ("Lentil soup + bread", "lunch", 480, 28, 65, 8),
                    ("Cottage cheese + pineapple", "snack", 180, 18, 22, 2),
                    ("Veggie stir fry + edamame + rice", "dinner", 530, 28, 72, 10),
                ],
                "exercises": [],
                "water_ml": 2400,
                "workout": False,
                "cardio": False,
            },
        ],
    },
    {
        "tg_id": "TEST_003",
        "name": "Jake", "age": 24, "sex": "male",
        "height_cm": 177.8, "weight_kg": 75.0, "goal_kg": 82.0,
        "goal": "bulk", "exp": "beginner",
        "diet": "none", "injuries": "right shoulder tightness",
        "cal": 3100, "pro": 180,
        "days": [
            {  # Day 1 — first serious gym day, underweight on cals
                "foods": [
                    ("Eggs + bacon + toast", "3 eggs 3 strips", 580, 38, 35, 28),
                    ("Protein bar", "Clif Builder", 270, 20, 34, 8),
                    ("Chicken breast + rice", "meal prep", 550, 48, 58, 8),
                    ("Peanut butter sandwich", "2 tbsp PB", 380, 14, 42, 16),
                    ("Ground beef tacos x3", "dinner", 720, 42, 60, 28),
                ],
                "exercises": [
                    ("Bench Press", 3, "8,7,6", 60.0, False),
                    ("Pull-ups", 3, "5,4,4", None, False),
                    ("Barbell Row", 3, "8,8,7", 60.0, False),
                    ("Dumbbell Curl", 3, "12,12,10", 15.9, False),
                ],
                "water_ml": 2200,
                "workout": True,
                "cardio": False,
            },
            {  # Day 2 — higher intake, push day
                "foods": [
                    ("Oatmeal + PB + banana", "large bowl", 620, 22, 85, 18),
                    ("Mass gainer shake", "1 scoop", 620, 40, 90, 10),
                    ("Chicken + pasta + cheese", "lunch", 780, 58, 80, 18),
                    ("Mixed nuts + dried fruit", "snack", 320, 8, 30, 20),
                    ("Steak + mashed potato + green beans", "dinner", 860, 58, 75, 30),
                    ("Casein pudding", "bedtime snack", 180, 25, 16, 2),
                ],
                "exercises": [
                    ("Overhead Press", 4, "6,6,5,5", 52.2, False),
                    ("Dumbbell Lateral Raise", 3, "15,15,12", 9.1, False),
                    ("Skull Crusher", 3, "10,10,9", 29.5, False),
                    ("Rope Pushdown", 3, "12,12,12", 18.1, False),
                ],
                "water_ml": 3000,
                "workout": True,
                "cardio": False,
            },
        ],
    },
    {
        "tg_id": "TEST_004",
        "name": "Priya", "age": 37, "sex": "female",
        "height_cm": 162.6, "weight_kg": 61.5, "goal_kg": 58.0,
        "goal": "performance", "exp": "advanced",
        "diet": "none", "injuries": "none",
        "cal": 1900, "pro": 155,
        "days": [
            {  # Day 1 — race week prep, high carb
                "foods": [
                    ("Bagel + cream cheese + smoked salmon", "breakfast", 480, 28, 58, 14),
                    ("Banana + peanut butter", "pre-run snack", 280, 8, 38, 12),
                    ("Post-run shake", "whey + dextrose", 250, 30, 28, 3),
                    ("Chicken + pasta + olive oil", "lunch", 680, 52, 72, 16),
                    ("Tuna + quinoa + spinach", "dinner", 480, 44, 42, 10),
                ],
                "exercises": [
                    ("10km Run", None, None, None, True, "outdoor run", 52),
                    ("Hip Flexor Stretch", None, None, None, False, None, 10),
                ],
                "water_ml": 3500,
                "workout": False,
                "cardio": True,
            },
            {  # Day 2 — strength training + light cardio
                "foods": [
                    ("Egg white omelette + avocado toast", "breakfast", 420, 32, 38, 14),
                    ("Greek yogurt + granola + berries", "snack", 280, 18, 36, 6),
                    ("Salmon + rice + miso soup", "lunch", 560, 44, 55, 14),
                    ("Apple + string cheese", "snack", 150, 8, 20, 4),
                    ("Chicken thigh + roasted veg + farro", "dinner", 580, 46, 52, 16),
                ],
                "exercises": [
                    ("Deadlift", 4, "3,3,3,3", 100.0, False),
                    ("Hip Thrust", 3, "10,10,10", 80.0, False),
                    ("Bulgarian Split Squat", 3, "8,8,8", 27.2, False),
                    ("20min Easy Jog", None, None, None, True, "easy jog", 20),
                ],
                "water_ml": 3200,
                "workout": True,
                "cardio": True,
            },
        ],
    },
]


async def build_persona(db, persona: dict) -> str:
    """Create a full test user with 2 days of realistic data. Returns webhook token."""
    from db.models import (
        User, UserPreferences, DailyLog, FoodEntry,
        ExerciseEntry, BodyMetric,
    )
    from db.queries import get_or_create_webhook_token
    from sqlalchemy import select, delete
    from sqlalchemy.orm import selectinload

    tg_id = persona["tg_id"]

    # Clean up any existing test user
    result = await db.execute(
        select(User).where(User.telegram_id == tg_id)
        .options(selectinload(User.preferences))
    )
    existing = result.scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.commit()

    # Create user
    user = User(
        telegram_id=tg_id,
        name=persona["name"],
        age=persona["age"],
        sex=persona["sex"],
        height_cm=persona["height_cm"],
        current_weight_kg=persona["weight_kg"],
        goal_weight_kg=persona["goal_kg"],
        primary_goal=persona["goal"],
        training_experience=persona["exp"],
        dietary_preferences=persona["diet"],
        injuries=persona["injuries"],
        timezone="America/New_York",
        onboarding_completed=True,
    )
    db.add(user)
    prefs = UserPreferences(
        user=user,
        calorie_target=persona["cal"],
        protein_target=persona["pro"],
        coaching_style="balanced",
        accountability_level="high",
        wake_time="07:00",
        sleep_time="23:00",
    )
    db.add(prefs)
    await db.flush()

    # Add weight metric
    bm = BodyMetric(user_id=user.id, weight_kg=persona["weight_kg"])
    db.add(bm)

    today = date.today()

    # Create 2 days of logs
    for day_offset, day_data in enumerate(persona["days"]):
        log_date = today - timedelta(days=len(persona["days"]) - 1 - day_offset)

        # food tuple: (name, quantity, calories, protein, carbs, fats)
        total_cal = sum(f[2] for f in day_data["foods"]) if day_data["foods"] else 0
        total_pro = sum(f[3] for f in day_data["foods"]) if day_data["foods"] else 0
        total_carbs = sum(f[4] for f in day_data["foods"]) if day_data["foods"] else 0
        total_fats = sum(f[5] for f in day_data["foods"]) if day_data["foods"] else 0

        daily_log = DailyLog(
            user_id=user.id,
            date=log_date,
            total_calories=total_cal,
            total_protein=total_pro,
            total_carbs=total_carbs,
            total_fats=total_fats,
            total_water_ml=day_data["water_ml"],
            workout_completed=day_data["workout"],
            cardio_completed=day_data["cardio"],
        )
        db.add(daily_log)
        await db.flush()

        # Food entries — tuple: (name, quantity, calories, protein, carbs, fats)
        for food in day_data["foods"]:
            fe = FoodEntry(
                daily_log_id=daily_log.id,
                parsed_food_name=food[0],
                quantity=food[1],
                calories=food[2],
                protein=food[3],
                carbs=food[4],
                fats=food[5],
                estimated_flag=False,
                confidence_score=0.9,
                source_type="text",
            )
            db.add(fe)

        # Exercise entries — tuple: (name, sets, reps, weight_lbs, is_cardio, [cardio_type], [duration])
        for ex in day_data["exercises"]:
            name, sets, reps, weight_lbs = ex[0], ex[1], ex[2], ex[3]
            cardio_type = ex[5] if len(ex) > 5 else None
            duration = ex[6] if len(ex) > 6 else None
            weight_kg = weight_lbs * 0.453592 if weight_lbs else None
            ee = ExerciseEntry(
                daily_log_id=daily_log.id,
                exercise_name=name,
                sets=sets,
                reps=reps,
                weight=weight_kg,
                cardio_type=cardio_type,
                duration_minutes=duration,
                source_type="text",
            )
            db.add(ee)

    await db.commit()

    # Get / create webhook token
    token = await get_or_create_webhook_token(db, user.id)
    return token


async def main():
    from db.database import AsyncSessionLocal, init_db
    await init_db()

    base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000").rstrip("/")

    sep()
    print(f"{BOLD}  ARNIE — MULTI-PERSONA TEST BUILD{RESET}")
    sep()

    tokens = {}
    async with AsyncSessionLocal() as db:
        for persona in PERSONAS:
            token = await build_persona(db, persona)
            tokens[persona["tg_id"]] = (persona["name"], token)
            ok(f"{persona['name']} ({persona['tg_id']}) created — {len(persona['days'])} days of data")

    sep()
    print(f"\n{BOLD}Dashboard links:{RESET}\n")
    for tg_id, (name, token) in tokens.items():
        print(f"  {CYAN}{name:8s}{RESET}  {base_url}/dashboard/{token}")

    sep()
    print(f"\n{BOLD}Test complete. {len(PERSONAS)} personas created.{RESET}\n")
    print("To clean up: run `python test_personas.py --cleanup`\n")


async def cleanup():
    from db.database import AsyncSessionLocal
    from db.models import User
    from sqlalchemy import select
    import shutil
    from pathlib import Path

    async with AsyncSessionLocal() as db:
        for p in PERSONAS:
            result = await db.execute(select(User).where(User.telegram_id == p["tg_id"]))
            user = result.scalar_one_or_none()
            if user:
                await db.delete(user)
                info(f"Deleted {p['name']} ({p['tg_id']})")
        await db.commit()

    for p in PERSONAS:
        mem_dir = Path(f"users/{p['tg_id']}")
        if mem_dir.exists():
            shutil.rmtree(mem_dir)

    print("Cleanup complete.")


if __name__ == "__main__":
    if "--cleanup" in sys.argv:
        asyncio.run(cleanup())
    else:
        asyncio.run(main())
