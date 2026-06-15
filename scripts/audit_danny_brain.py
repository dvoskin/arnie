"""READ-ONLY audit of Danny's full 'brain' state in prod Postgres.

Writes nothing. Dumps: profile columns, preferences, bio, every UserAttribute
node (with staleness/confidence/source/tier), body-metric history, workout
program, and activity volumes (convs/food/exercise/daily logs/health snapshots/
pending questions/food matches/memory updates). Lets us judge what's stored,
what's stale, what's missing, and where the brain is over/under-learning.
"""
import asyncio
import os
from collections import Counter
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
load_dotenv(override=True)

from sqlalchemy import select, or_, func
from db.database import AsyncSessionLocal
from db.models import (
    User, UserPreferences, UserAttribute, DailyLog, FoodEntry, ExerciseEntry,
    BodyMetric, ConversationLog, HealthSnapshot, PendingQuestion, MemoryUpdate,
    UserFoodMatch, WorkoutProgram,
)


def _age(dt):
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    if days < 1:
        return f"{days*24:.1f}h"
    return f"{days:.0f}d"


async def main():
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(User).where(
                or_(User.name.ilike("%danny%"), User.name.ilike("%daniel%"))
            )
        )
        users = res.scalars().all()
        # Prefer the most active account.
        best = None
        best_cnt = -1
        for u in users:
            cnt = await db.scalar(
                select(func.count(ConversationLog.id)).where(ConversationLog.user_id == u.id)
            )
            print(f"candidate id={u.id} name={u.name!r} convs={cnt} goal={u.primary_goal}")
            if cnt > best_cnt:
                best, best_cnt = u, cnt
        u = best
        print(f"\n========== AUDITING user_id={u.id} ({u.name}) ==========\n")

        # ---- PROFILE COLUMNS ----
        print("---- USER PROFILE COLUMNS ----")
        cols = [
            "age", "sex", "height_cm", "current_weight_kg", "goal_weight_kg",
            "timezone", "city", "primary_goal", "training_experience",
            "non_training_activity", "dietary_preferences", "injuries", "sport",
            "units_preference", "onboarding_completed", "subscription_status",
            "channel_preference", "active_mission", "mission_metric", "mission_target",
            "user_bio_updated_at", "created_at",
        ]
        for c in cols:
            print(f"  {c:24} = {getattr(u, c, None)!r}")
        print(f"\n  user_bio ({_age(u.user_bio_updated_at)} old):")
        print(f"    {(u.user_bio or '(none)')[:600]}")

        # ---- PREFERENCES ----
        prefs = (await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == u.id)
        )).scalar_one_or_none()
        print("\n---- USER PREFERENCES ----")
        if prefs:
            for c in ["coaching_style", "accountability_level", "reminder_frequency",
                      "preferred_response_length", "preferred_language", "food_logging_mode",
                      "calorie_target", "protein_target", "carb_target", "fat_target",
                      "wake_time", "sleep_time", "proactive_messaging_enabled"]:
                print(f"  {c:26} = {getattr(prefs, c, None)!r}")
        else:
            print("  (no preferences row)")

        # ---- ATTRIBUTES (brain nodes) ----
        attrs = (await db.execute(
            select(UserAttribute).where(UserAttribute.user_id == u.id)
        )).scalars().all()
        active = [a for a in attrs if a.attribute_status == "active"]
        print(f"\n---- USER ATTRIBUTES (brain nodes): {len(attrs)} total, "
              f"{len(active)} active ----")
        by_status = Counter(a.attribute_status for a in attrs)
        by_cat = Counter(a.category for a in active)
        by_tier = Counter(a.relevance_tier for a in active)
        by_conf = Counter(a.confidence for a in active)
        by_src = Counter(a.source for a in active)
        print(f"  status: {dict(by_status)}")
        print(f"  active by category: {dict(by_cat)}")
        print(f"  active by tier:     {dict(by_tier)}")
        print(f"  active by confidence:{dict(by_conf)}")
        print(f"  active by source:   {dict(by_src)}")
        # staleness of active attrs
        stale_30 = [a for a in active if a.updated_at and
                    (datetime.now(timezone.utc) - (a.updated_at.replace(tzinfo=timezone.utc)
                     if a.updated_at.tzinfo is None else a.updated_at)).days > 30]
        print(f"  active not-updated >30d: {len(stale_30)}")
        print("\n  ALL ACTIVE ATTRIBUTES (cat | key | tier | conf | src | age | value):")
        for a in sorted(active, key=lambda x: (x.category, x.relevance_tier, x.attribute_key)):
            val = (a.value or "")[:70]
            print(f"   {a.category:9} | {a.attribute_key:34} | {a.relevance_tier:10} | "
                  f"{a.confidence:17} | {a.source:14} | {_age(a.updated_at):>5} | {val}")
        disc = [a for a in attrs if a.attribute_status != "active"]
        if disc:
            print(f"\n  DISCONTINUED/HISTORICAL ({len(disc)}):")
            for a in sorted(disc, key=lambda x: x.attribute_key):
                print(f"   [{a.attribute_status}] {a.attribute_key:34} = {(a.value or '')[:50]}")

        # ---- WORKOUT PROGRAM ----
        wp = (await db.execute(
            select(WorkoutProgram).where(WorkoutProgram.user_id == u.id)
        )).scalar_one_or_none()
        print("\n---- WORKOUT PROGRAM ----")
        if wp:
            print(f"  updated {_age(wp.updated_at)} ago; program_json len="
                  f"{len(wp.program_json or '')}")
            print(f"    {(wp.program_json or '')[:400]}")
        else:
            print("  (none saved)")

        # ---- BODY METRICS ----
        bms = (await db.execute(
            select(BodyMetric).where(BodyMetric.user_id == u.id).order_by(BodyMetric.timestamp)
        )).scalars().all()
        print(f"\n---- BODY METRICS: {len(bms)} entries ----")
        if bms:
            print(f"  first {_age(bms[0].timestamp)} ago = {bms[0].weight_kg}kg")
            print(f"  last  {_age(bms[-1].timestamp)} ago = {bms[-1].weight_kg}kg "
                  f"(ctx={bms[-1].context}, bf={bms[-1].bodyfat_estimate}, waist={bms[-1].waist_cm})")

        # ---- ACTIVITY VOLUMES ----
        async def cnt(model, *where):
            q = select(func.count(model.id))
            for w in where:
                q = q.where(w)
            return await db.scalar(q)

        # food/exercise entries join through daily_logs
        dl_ids = (await db.execute(
            select(DailyLog.id).where(DailyLog.user_id == u.id)
        )).scalars().all()
        n_food = await db.scalar(
            select(func.count(FoodEntry.id)).where(FoodEntry.daily_log_id.in_(dl_ids))
        ) if dl_ids else 0
        n_exe = await db.scalar(
            select(func.count(ExerciseEntry.id)).where(ExerciseEntry.daily_log_id.in_(dl_ids))
        ) if dl_ids else 0
        n_conv = await cnt(ConversationLog, ConversationLog.user_id == u.id)
        n_daily = len(dl_ids)
        n_health = await cnt(HealthSnapshot, HealthSnapshot.user_id == u.id)
        n_pend = await cnt(PendingQuestion, PendingQuestion.user_id == u.id)
        n_pend_open = await cnt(PendingQuestion, PendingQuestion.user_id == u.id,
                                PendingQuestion.answered_at.is_(None))
        n_mem = await cnt(MemoryUpdate, MemoryUpdate.user_id == u.id)
        n_fm = await cnt(UserFoodMatch, UserFoodMatch.user_id == u.id)

        # conv date span + recency
        first_conv = await db.scalar(
            select(func.min(ConversationLog.timestamp)).where(ConversationLog.user_id == u.id))
        last_conv = await db.scalar(
            select(func.max(ConversationLog.timestamp)).where(ConversationLog.user_id == u.id))
        last_food = await db.scalar(
            select(func.max(FoodEntry.timestamp)).where(FoodEntry.daily_log_id.in_(dl_ids))
        ) if dl_ids else None
        last_exe = await db.scalar(
            select(func.max(ExerciseEntry.timestamp)).where(ExerciseEntry.daily_log_id.in_(dl_ids))
        ) if dl_ids else None
        last_health = await db.scalar(
            select(func.max(HealthSnapshot.received_at)).where(HealthSnapshot.user_id == u.id))

        print("\n---- ACTIVITY VOLUMES ----")
        print(f"  conversations:    {n_conv}  (first {_age(first_conv)} ago, last {_age(last_conv)} ago)")
        print(f"  daily logs:       {n_daily}")
        print(f"  food entries:     {n_food}  (last {_age(last_food)} ago)")
        print(f"  exercise entries: {n_exe}  (last {_age(last_exe)} ago)")
        print(f"  body metrics:     {len(bms)}")
        print(f"  health snapshots: {n_health}  (last {_age(last_health)} ago)")
        print(f"  user_food_matches:{n_fm}")
        print(f"  pending questions:{n_pend}  ({n_pend_open} open)")
        print(f"  memory updates:   {n_mem}")

        # ---- FOOD MATCH learning quality ----
        fms = (await db.execute(
            select(UserFoodMatch).where(UserFoodMatch.user_id == u.id)
            .order_by(UserFoodMatch.times_used.desc()).limit(15)
        )).scalars().all()
        if fms:
            print("\n---- TOP USER FOOD MATCHES (learned foods) ----")
            for f in fms:
                print(f"   {f.times_used:3}x | conf={f.confidence:13} | confirmed={f.user_confirmed} "
                      f"| {f.display_name or f.name_norm} ({f.cal_100}cal/100)")

        # ---- recent open pending questions ----
        opq = (await db.execute(
            select(PendingQuestion).where(
                PendingQuestion.user_id == u.id,
                PendingQuestion.answered_at.is_(None),
            ).order_by(PendingQuestion.asked_at.desc()).limit(10)
        )).scalars().all()
        if opq:
            print("\n---- OPEN PENDING QUESTIONS ----")
            for q in opq:
                print(f"   [{q.kind}/{q.tier}] asked {_age(q.asked_at)} ago, "
                      f"follow_ups={q.follow_up_count}: {(q.question or '')[:70]}")


if __name__ == "__main__":
    asyncio.run(main())
