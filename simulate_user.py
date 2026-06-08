"""
Simulate a realistic 3-day user interaction with Arnie.
Creates a user, 3 days of food/exercise logs, and realistic conversation history
so the admin panel shows a full picture of how the product works.

Run from arnie/:
    .venv/bin/python simulate_user.py
    .venv/bin/python simulate_user.py --cleanup
"""
import asyncio
import os
import sys
from datetime import date, timedelta, datetime, timezone
from dotenv import load_dotenv
load_dotenv(override=True)

TG_ID = "SIM_ALEX_001"

# ── 3-day scenario: Alex, 26M, intermediate cut ────────────────────────────────
PROFILE = {
    "name": "Alex", "age": 26, "sex": "male",
    "height_cm": 180.3, "weight_kg": 90.7, "goal_kg": 82.0,
    "goal": "cut", "exp": "intermediate",
    "diet": "none", "injuries": "none",
    "cal_target": 2200, "pro_target": 195,
}

# Each day: foods, exercises, conversation turns
DAYS = [
    {
        # Day 1 — leg day, solid eating, slightly over protein
        "label": "Leg day",
        "foods": [
            ("Greek yogurt + granola + honey",  "breakfast",  380, 28, 52, 6),
            ("Oats + whey protein",              "pre-workout", 310, 32, 40, 5),
            ("Chicken breast + rice + broccoli", "lunch",      620, 55, 65, 8),
            ("Apple + almond butter",            "snack",      240,  5, 34, 12),
            ("Ground beef + sweet potato + veg", "dinner",     680, 52, 58, 22),
            ("Casein shake",                     "bedtime",    190, 30,  8,  3),
        ],
        "exercises": [
            ("Squat",                  4, "6,6,5,5", 115.0, False, None, None),
            ("Romanian Deadlift",      3, "8,8,8",    90.0, False, None, None),
            ("Leg Press",              3, "12,12,10", 160.0, False, None, None),
            ("Walking Lunge",          3, "10,10,10",  40.0, False, None, None),
            ("Seated Calf Raise",      4, "15,15,12,12", 60.0, False, None, None),
        ],
        "water_ml": 3100,
        "workout": True, "cardio": False,
        "convos": [
            ("gm! had greek yogurt with granola and honey for breakfast",
             "🥛 <b>Greek Yogurt + Granola + Honey</b>\n<i>380 cal · 28g P · 52g C · 6g F</i>\n\n▰▰▰▱▱▱▱▱▱▱ <b>380</b>/2,200 cal\n▰▰▱▱▱▱▱▱▱▱ <b>28</b>/195g protein"),
            ("oats and whey before the gym",
             "🍞 <b>Oats + Whey Protein</b>\n<i>310 cal · 32g P · 40g C · 5g F</i>\n\n▰▰▰▰▱▱▱▱▱▱ <b>690</b>/2,200 cal\n▰▰▰▱▱▱▱▱▱▱ <b>60</b>/195g protein\n\nGood pre-workout stack. Hit the legs."),
            ("just finished leg day:\nsquat 255lb 4x6 (last 2 sets were 5)\nRDL 200lb 3x8\nleg press 350lb 3x12,12,10\nwalking lunges 2x45 3x10\ncalf raises 135lb 4x15,15,12,12",
             "🏋️ <b>Squat</b> · 4×6,6,5,5 @ <b>255</b>lb\n🏋️ <b>Romanian Deadlift</b> · 3×8 @ <b>200</b>lb\n🏋️ <b>Leg Press</b> · 3×12,12,10 @ <b>350</b>lb\n🚶 <b>Walking Lunge</b> · 3×10 @ <b>90</b>lb\n🏋️ <b>Seated Calf Raise</b> · 4×15,15,12,12 @ <b>135</b>lb\n\n<b>Solid session.</b> Squat volume is up — those last 2 sets dropping to 5 reps at that load is normal. If you're hitting consistent 4×6 next week, bump 5lb. RDLs looked clean from the numbers. Calves are an afterthought for most people — good that you're actually doing them."),
            ("chicken rice broc for lunch — meal prepped this week",
             "🍗 <b>Chicken Breast + Rice + Broccoli</b>\n<i>620 cal · 55g P · 65g C · 8g F</i>\n\n▰▰▰▰▰▰▱▱▱▱ <b>1,310</b>/2,200 cal\n▰▰▰▰▰▰▰▱▱▱ <b>147</b>/195g protein\n\nMeal prep paying off. 48g protein left, easy to close with dinner."),
            ("apple and almond butter snack",
             "🥜 <b>Apple + Almond Butter</b>\n<i>240 cal · 5g P · 34g C · 12g F</i>\n\n▰▰▰▰▰▰▰▱▱▱ <b>1,550</b>/2,200 cal\n▰▰▰▰▰▰▰▱▱▱ <b>152</b>/195g protein"),
            ("ground beef bowl with sweet potato for dinner",
             "🥩 <b>Ground Beef + Sweet Potato + Veg</b>\n<i>680 cal · 52g P · 58g C · 22g F</i>\n\n▰▰▰▰▰▰▰▰▰▱ <b>2,230</b>/2,200 cal\n▰▰▰▰▰▰▰▰▰▰ <b>204</b>/195g protein ✓\n\nSlightly over calories but protein target hit. Leg day earned it — not sweating 30 calories."),
            ("casein shake before bed. close the day",
             "🥛 <b>Casein Shake</b>\n<i>190 cal · 30g P · 8g C · 3g F</i>\n\nDay closed. <b>2,420 cal · 234g protein.</b> Slightly over on both but you trained legs hard — this is fine. Protein is locked in. Rest up."),
        ],
    },
    {
        # Day 2 — push day, tighter on carbs, short on protein
        "label": "Push day",
        "foods": [
            ("3 eggs + 2 turkey bacon + coffee", "breakfast",  310, 28, 4,  18),
            ("Protein bar",                       "snack",      220, 20, 26,  8),
            ("Turkey + avocado wrap",             "lunch",      510, 38, 48, 14),
            ("Protein shake post-workout",        "post-workout",160, 30,  6,  3),
            ("Salmon fillet + asparagus + rice",  "dinner",     590, 48, 52, 14),
        ],
        "exercises": [
            ("Bench Press",           4, "8,8,7,6",   90.0, False, None, None),
            ("Incline DB Press",      3, "10,10,9",   32.0, False, None, None),
            ("Cable Fly",             3, "12,12,12",  15.0, False, None, None),
            ("Overhead Press",        3, "8,8,7",     60.0, False, None, None),
            ("Tricep Pushdown",       3, "12,12,10",  22.5, False, None, None),
            ("Incline Walk",       None, None,        None,  True, "incline walk", 25),
        ],
        "water_ml": 2600,
        "workout": True, "cardio": True,
        "convos": [
            ("3 eggs 2 turkey bacon and a coffee this morning",
             "🍳 <b>3 Eggs + 2 Turkey Bacon + Coffee</b>\n<i>310 cal · 28g P · 4g C · 18g F</i>\n\n▰▰▱▱▱▱▱▱▱▱ <b>310</b>/2,200 cal\n▰▱▱▱▱▱▱▱▱▱ <b>28</b>/195g protein\n\nSolid protein start. Light on carbs — push day, you'll want fuel."),
            ("protein bar mid morning",
             "🍫 <b>Protein Bar</b>\n<i>220 cal · 20g P · 26g C · 8g F</i>\n\n▰▰▰▱▱▱▱▱▱▱ <b>530</b>/2,200 cal\n▰▰▱▱▱▱▱▱▱▱ <b>48</b>/195g protein"),
            ("turkey avocado wrap for lunch",
             "🍴 <b>Turkey + Avocado Wrap</b>\n<i>510 cal · 38g P · 48g C · 14g F</i>\n\n▰▰▰▰▰▱▱▱▱▱ <b>1,040</b>/2,200 cal\n▰▰▰▰▱▱▱▱▱▱ <b>86</b>/195g protein"),
            ("push day done:\nbench 4x8,8,7,6 @ 200lb\nincline db 3x10,10,9 @ 70lb\ncable fly 3x12 @ 33lb\nOHP 3x8,8,7 @ 132lb\ntricep pushdown 3x12,12,10 @ 50lb\nthen 25 min incline walk",
             "🏋️ <b>Bench Press</b> · 4×8,8,7,6 @ <b>200</b>lb\n🏋️ <b>Incline DB Press</b> · 3×10,10,9 @ <b>70</b>lb\n🏋️ <b>Cable Fly</b> · 3×12 @ <b>33</b>lb\n🏋️ <b>Overhead Press</b> · 3×8,8,7 @ <b>132</b>lb\n🏋️ <b>Tricep Pushdown</b> · 3×12,12,10 @ <b>50</b>lb\n🚶 <b>Incline Walk</b> · 25 min\n\n<b>Bench dropped off end of the set — that's a volume issue, not a strength one.</b> You're handling 200 fine for 2 sets then fading. Two options: drop to 195 and hit clean 4×8, or keep 200 and accept the fadeout. OHP at 132 for 3×8 is solid. Drop the incline walk to 20 min on push days if recovery matters."),
            ("protein shake after the gym",
             "🥛 <b>Protein Shake</b>\n<i>160 cal · 30g P · 6g C · 3g F</i>\n\n▰▰▰▰▰▰▱▱▱▱ <b>1,200</b>/2,200 cal\n▰▰▰▰▰▰▱▱▱▱ <b>116</b>/195g protein"),
            ("salmon with asparagus and rice for dinner",
             "🐟 <b>Salmon + Asparagus + Rice</b>\n<i>590 cal · 48g P · 52g C · 14g F</i>\n\n▰▰▰▰▰▰▰▰▱▱ <b>1,790</b>/2,200 cal\n▰▰▰▰▰▰▰▰▱▱ <b>164</b>/195g protein\n\n31g protein and 410 calories left. You've got room — add something before bed or you'll close short on protein."),
            ("how am i doing today overall",
             "1,790 cal of 2,200 — 410 left. <b>164g protein of 195g</b> — 31g short with dinner done. Push day + cardio and you're under on both. Either get a casein shake in or accept the deficit. Weight-wise this works but protein will hurt recovery if it's a pattern."),
        ],
    },
    {
        # Day 3 (today) — rest day, partial log, checking in
        "label": "Rest day (today)",
        "foods": [
            ("Overnight oats + protein powder + blueberries", "breakfast", 420, 35, 55, 7),
            ("Cottage cheese + pineapple",                    "snack",     180, 22, 18, 2),
            ("Grilled chicken Caesar salad",                  "lunch",     490, 42, 22, 24),
        ],
        "exercises": [],
        "water_ml": 1800,
        "workout": False, "cardio": False,
        "convos": [
            ("overnight oats with protein powder and blueberries",
             "🍞 <b>Overnight Oats + Protein Powder + Blueberries</b>\n<i>420 cal · 35g P · 55g C · 7g F</i>\n\n▰▰▱▱▱▱▱▱▱▱ <b>420</b>/2,200 cal\n▰▰▱▱▱▱▱▱▱▱ <b>35</b>/195g protein\n\nRest day — carbs are fine, use them for recovery."),
            ("cottage cheese with pineapple",
             "🍴 <b>Cottage Cheese + Pineapple</b>\n<i>180 cal · 22g P · 18g C · 2g F</i>\n\n▰▰▰▱▱▱▱▱▱▱ <b>600</b>/2,200 cal\n▰▰▰▱▱▱▱▱▱▱ <b>57</b>/195g protein"),
            ("grilled chicken caesar for lunch",
             "🥗 <b>Grilled Chicken Caesar Salad</b>\n<i>490 cal · 42g P · 22g C · 24g F</i>\n\n▰▰▰▰▰▱▱▱▱▱ <b>1,090</b>/2,200 cal\n▰▰▰▰▰▱▱▱▱▱ <b>99</b>/195g protein\n\nHalfway on protein at lunch, rest day — you're on pace. 96g left, easy to close with dinner."),
            ("what should i eat for dinner to hit my targets",
             "You need <b>96g protein, ~1,110 cal.</b> Options that fit:\n\n• Ground beef (8oz) + rice + veg — ~650 cal, 58g P. Add a shake for the rest.\n• Salmon (6oz) + potatoes + broc — ~580 cal, 46g P. Need a snack too.\n• Chicken thighs + pasta — ~700 cal, 55g P. Casein before bed to close.\n\nGround beef bowl is the easiest single-meal solution if you don't want to think about it."),
        ],
    },
]


async def build_sim_user(db) -> str:
    from db.models import User, UserPreferences, DailyLog, FoodEntry, ExerciseEntry, BodyMetric, ConversationLog
    from db.queries import get_or_create_webhook_token
    from sqlalchemy import select, delete
    from sqlalchemy.orm import selectinload

    # Wipe existing
    result = await db.execute(select(User).where(User.telegram_id == TG_ID).options(selectinload(User.preferences)))
    existing = result.scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.commit()

    user = User(
        telegram_id=TG_ID,
        name=PROFILE["name"], age=PROFILE["age"], sex=PROFILE["sex"],
        height_cm=PROFILE["height_cm"], current_weight_kg=PROFILE["weight_kg"],
        goal_weight_kg=PROFILE["goal_kg"], primary_goal=PROFILE["goal"],
        training_experience=PROFILE["exp"], dietary_preferences=PROFILE["diet"],
        injuries=PROFILE["injuries"], timezone="America/New_York",
        onboarding_completed=True,
    )
    db.add(user)
    prefs = UserPreferences(
        user=user,
        calorie_target=PROFILE["cal_target"],
        protein_target=PROFILE["pro_target"],
        coaching_style="balanced", accountability_level="high",
        proactive_messaging_enabled=True,
        wake_time="07:00", sleep_time="23:00",
    )
    db.add(prefs)
    await db.flush()

    db.add(BodyMetric(user_id=user.id, weight_kg=PROFILE["weight_kg"]))

    today = date.today()
    n_days = len(DAYS)

    for i, day_data in enumerate(DAYS):
        is_today = (i == n_days - 1)
        log_date = today - timedelta(days=n_days - 1 - i)

        total_cal  = sum(f[2] for f in day_data["foods"])
        total_pro  = sum(f[3] for f in day_data["foods"])
        total_carb = sum(f[4] for f in day_data["foods"])
        total_fat  = sum(f[5] for f in day_data["foods"])

        daily_log = DailyLog(
            user_id=user.id, date=log_date,
            total_calories=total_cal, total_protein=total_pro,
            total_carbs=total_carb, total_fats=total_fat,
            total_water_ml=day_data["water_ml"],
            workout_completed=day_data["workout"],
            cardio_completed=day_data["cardio"],
        )
        db.add(daily_log)
        await db.flush()

        for food in day_data["foods"]:
            db.add(FoodEntry(
                daily_log_id=daily_log.id,
                parsed_food_name=food[0], quantity=food[1],
                calories=food[2], protein=food[3], carbs=food[4], fats=food[5],
                estimated_flag=False, confidence_score=0.9, source_type="text",
            ))

        for ex in day_data["exercises"]:
            name, sets, reps, weight_lbs, is_cardio, cardio_type, duration = ex
            weight_kg = weight_lbs * 0.453592 if weight_lbs else None
            db.add(ExerciseEntry(
                daily_log_id=daily_log.id,
                exercise_name=name, sets=sets, reps=reps,
                weight=weight_kg, cardio_type=cardio_type,
                duration_minutes=duration, source_type="text",
            ))

        # Realistic conversation timestamps spread through the day
        convo_hours = [7, 9, 13, 14, 17, 19, 21]
        for j, (user_msg, arnie_resp) in enumerate(day_data["convos"]):
            hour = convo_hours[j] if j < len(convo_hours) else 20
            ts = datetime(log_date.year, log_date.month, log_date.day,
                          hour, [5,32,15,48,20,55,10][j % 7], 0,
                          tzinfo=timezone.utc)
            db.add(ConversationLog(
                user_id=user.id,
                raw_message=user_msg,
                response=arnie_resp,
                timestamp=ts,
                source_type="text",
            ))

    await db.commit()
    return await get_or_create_webhook_token(db, user.id)


async def main():
    from db.database import AsyncSessionLocal, init_db
    await init_db()

    base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000").rstrip("/")
    admin_token = os.getenv("ADMIN_TOKEN", "")

    async with AsyncSessionLocal() as db:
        token = await build_sim_user(db)

    print("\n" + "─" * 60)
    print(f"  Simulated user: {PROFILE['name']} ({TG_ID})")
    print(f"  3 days: Leg day → Push day → Rest day (today)")
    print("─" * 60)
    print(f"\n  Dashboard:  {base_url}/dashboard/{token}")
    if admin_token:
        print(f"  Admin:      {base_url}/admin?token={admin_token}")
        print(f"  Convos:     (find {PROFILE['name']} in admin → 💬 convo)")
    else:
        print("  Admin:      set ADMIN_TOKEN env var to access admin panel")
    print()


async def cleanup():
    from db.database import AsyncSessionLocal
    from db.models import User
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == TG_ID))
        user = result.scalar_one_or_none()
        if user:
            await db.delete(user)
            await db.commit()
            print(f"Deleted simulated user {PROFILE['name']}")
        else:
            print("User not found")


if __name__ == "__main__":
    if "--cleanup" in sys.argv:
        asyncio.run(cleanup())
    else:
        asyncio.run(main())
