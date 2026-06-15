"""Validation sim — prove our brain optimizations actually improved consolidation
and learning. Runs against a THROWAWAY local sqlite (never prod).

Covers: live-metric guard, canonical synonym collapse, dedup-on-write, salience
spotlight/recall, behavioral-signal accuracy (incl. the incline-bench false-trend
regression), and a REAL synthesis pass proving durable patterns are inferred while
snapshots/lane-1 are not.
"""
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv(override=True)                       # API keys
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///sim_brain_validation.db"  # force local

# import db AFTER forcing the URL so the engine binds to sqlite
from db.database import init_db, engine, AsyncSessionLocal  # noqa: E402
from db.models import Base, User, UserPreferences, DailyLog, FoodEntry, ExerciseEntry  # noqa: E402

G = "\033[92m"; R = "\033[91m"; C = "\033[96m"; X = "\033[0m"; B = "\033[1m"
_p = _f = 0


def check(label, cond, detail=""):
    global _p, _f
    mark = f"{G}✓{X}" if cond else f"{R}✗{X}"
    print(f"  {mark} {label}" + (f"  {detail}" if detail else ""))
    if cond: _p += 1
    else: _f += 1
    return cond


def head(t):
    print(f"\n{B}{C}{'═'*60}\n {t}\n{'═'*60}{X}")


LB = 1 / 2.20462  # lb → kg


async def fresh_user(db, tg):
    u = User(telegram_id=tg, name="SimUser", primary_goal="cut",
             onboarding_completed=True, timezone="America/New_York")
    db.add(u)
    await db.flush()
    db.add(UserPreferences(user_id=u.id, calorie_target=2100, protein_target=190,
                           coaching_style="balanced"))
    await db.commit()
    return u


async def main():
    # clean slate
    if os.path.exists("sim_brain_validation.db"):
        os.remove("sim_brain_validation.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from memory.attribute_store import (
        upsert_attribute, get_all_attributes, get_attributes_for_context,
        is_live_metric_key, decay_stale_attributes,
    )
    from memory.behavioral_signals import strength_progression, build_behavioral_block

    # ── 1. CONSOLIDATION: live-metric guard + canonical collapse + dedup ──────
    head("1. CONSOLIDATION — guards & dedup (deterministic)")
    async with AsyncSessionLocal() as db:
        u = await fresh_user(db, "SIMV1")

        # live/transient keys must be rejected at the source
        for k in ("health_biometric_hrv", "fitness_session_type_today",
                  "behavior_adherence_streak"):
            await upsert_attribute(db, u.id, attribute_key=k, value="x", category="health")
        active = await get_all_attributes(db, u.id)
        check("live/transient metrics rejected at write",
              not any(is_live_metric_key(a.attribute_key) for a in active),
              f"{len(active)} stored")

        # cardio synonyms collapse to one canonical row
        await upsert_attribute(db, u.id, attribute_key="fitness_cardio_preference",
                               value="spin bike", category="fitness")
        await upsert_attribute(db, u.id, attribute_key="fitness_cardio_type",
                               value="incline walk + spin", category="fitness")
        active = await get_all_attributes(db, u.id)
        cardio = [a for a in active if a.attribute_key.startswith("fitness_cardio")]
        check("cardio synonyms collapse to 1 canonical row",
              len(cardio) == 1 and cardio[0].attribute_key == "fitness_cardio_habits",
              f"{[a.attribute_key for a in cardio]}")

        # dedup-on-write: same value, new key, same category → skipped
        await upsert_attribute(db, u.id, attribute_key="nutrition_diet_style",
                               value="flexible dieting, tracks calories and protein",
                               category="nutrition")
        await upsert_attribute(db, u.id, attribute_key="nutrition_eating_approach",
                               value="flexible dieting, tracks calories and protein",
                               category="nutrition")
        active = await get_all_attributes(db, u.id)
        check("duplicate-value attribute under new key skipped",
              len([a for a in active if "flexible dieting" in (a.value or "")]) == 1)

    # ── 2. SALIENCE: spotlight relevant + recall archived ─────────────────────
    head("2. SALIENCE — spotlight & archive recall")
    async with AsyncSessionLocal() as db:
        u = await fresh_user(db, "SIMV2")
        await upsert_attribute(db, u.id, attribute_key="fitness_cardio_habits",
                               value="spin Zone 1-2, incline walk", category="fitness")
        await upsert_attribute(db, u.id, attribute_key="nutrition_diet_style",
                               value="flexible dieting", category="nutrition")
        await upsert_attribute(db, u.id, attribute_key="nutrition_alcohol_habits",
                               value="occasional Duvel beer", category="nutrition",
                               relevance_tier="archive")
        blk = await get_attributes_for_context(db, u.id, "how much cardio today?")
        check("spotlight surfaces the cardio fact for a cardio message",
              "[RELEVANT TO THIS MESSAGE" in blk and "spin" in blk.split("[FITNESS]")[0])
        beer = await get_attributes_for_context(db, u.id, "can I have a beer tonight?")
        check("archived fact RECALLED on topic match", "Duvel" in beer)
        notopic = await get_attributes_for_context(db, u.id, "what should I train?")
        check("archived fact hidden when off-topic", "Duvel" not in notopic)

    # ── 3. LEARNING: behavioral-signal accuracy incl. regression ─────────────
    head("3. LEARNING — behavioral signal accuracy")
    async with AsyncSessionLocal() as db:
        u = await fresh_user(db, "SIMV3")
        base = date(2026, 5, 20)
        # 3 incline-bench sessions: weight flat/up, with a FATIGUED last set each
        # (the exact shape that produced a false "declining" trend before the fix)
        plan = [
            (base,            [(200, 13), (205, 9)]),
            (base + timedelta(days=5),  [(205, 12), (200, 8)]),
            (base + timedelta(days=12), [(205, 15), (200, 10)]),  # top set is BEST, last is fatigued
        ]
        for d, sets in plan:
            dl = DailyLog(user_id=u.id, date=d, total_calories=1900,
                          total_protein=190 if d != base + timedelta(days=5) else 130,
                          workout_completed=True)
            db.add(dl); await db.flush()
            for i, (wt_lb, reps) in enumerate(sets):
                db.add(ExerciseEntry(daily_log_id=dl.id, exercise_name="Incline Bench Press",
                                     weight=wt_lb * LB, reps=str(reps),
                                     timestamp=datetime(d.year, d.month, d.day, 18, i)))
            # late-night meal each day
            db.add(FoodEntry(daily_log_id=dl.id, parsed_food_name="protein bar",
                             calories=200, protein=20, meal_type="snack",
                             meal_time=datetime(d.year, d.month, d.day, 23, 15)))
        # extra food-only days so meal-timing has ≥4 days of evidence (no inference on sparse data)
        for off in range(15, 20):
            d = base + timedelta(days=off)
            dl = DailyLog(user_id=u.id, date=d, total_calories=1850, total_protein=170,
                          workout_completed=False)
            db.add(dl); await db.flush()
            db.add(FoodEntry(daily_log_id=dl.id, parsed_food_name="late snack",
                             calories=180, protein=15, meal_type="snack",
                             meal_time=datetime(d.year, d.month, d.day, 23, 30)))
            db.add(FoodEntry(daily_log_id=dl.id, parsed_food_name="lunch",
                             calories=600, protein=45, meal_type="lunch",
                             meal_time=datetime(d.year, d.month, d.day, 12, 30)))
        await db.commit()

        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from db.queries import get_recent_logs
        u = (await db.execute(select(User).options(selectinload(User.preferences))
                              .where(User.id == u.id))).scalar_one()
        logs = await get_recent_logs(db, u.id, days=60)
        strength = strength_progression(logs)
        check("incline bench NOT falsely 'declining' (regression fix)",
              "Incline Bench" in strength and "↓" not in strength, strength)
        check("strength reported as real weight×reps (not e1RM)",
              "lb×" in strength)
        block = build_behavioral_block(logs, [], [], u.preferences, u)
        check("behavioral block surfaces late-night meal pattern",
              "after 10pm" in block)

    # ── 4. REAL SYNTHESIS: durable patterns inferred, snapshots NOT stored ────
    head("4. LEARNING — real synthesis (LLM)")
    if "--no-llm" in sys.argv:
        print("  (skipped — --no-llm)")
    else:
        from memory.profile_updater import maybe_update_profile
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            u = (await db.execute(select(User).options(selectinload(User.preferences))
                                  .where(User.telegram_id == "SIMV3"))).scalar_one()
            ok = await maybe_update_profile(u, db, force=True)
            active = await get_all_attributes(db, u.id)
            keys = {a.attribute_key for a in active}
            check("synthesis upserted attributes", ok and len(active) > 0,
                  f"{len(active)} active")
            check("inferred a durable behavioral pattern",
                  any(k in keys for k in ("fitness_strength_trends",
                      "nutrition_adherence_pattern", "nutrition_meal_timing")),
                  f"{sorted(k for k in keys if 'trend' in k or 'pattern' in k or 'timing' in k)}")
            check("did NOT store any live/transient snapshot as an attribute",
                  not any(is_live_metric_key(k) for k in keys))
            inferred = [a for a in active if a.confidence == "inferred"]
            check("new patterns honestly tagged 'inferred' (no confidence inflation)",
                  len(inferred) >= 1, f"{len(inferred)} inferred / {len(active)} total")

    print(f"\n{B}RESULT: {G}{_p} passed{X}, " +
          (f"{R}{_f} failed{X}" if _f else "0 failed") + f"{B}{X}")
    await engine.dispose()
    if os.path.exists("sim_brain_validation.db"):
        os.remove("sim_brain_validation.db")
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    asyncio.run(main())
