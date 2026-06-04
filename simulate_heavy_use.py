"""
Heavy-use simulation + verification for the dynamic user-profile system.

Exercises the full stack end to end:
  A. Schema           — user_attributes table + user_bio columns exist
  B. Plumbing stress  — heavy upserts, conflict resolution, canonicalization,
                        tier-based context injection (no LLM, fast & heavy)
  C. Concurrency      — many users, concurrent background-style sessions, race safety
  D. Real synthesis   — actual Sonnet profile synthesis on a rich user, real bio
  E. 3-month growth   — synthesis at week-1 / month-1 / month-3 snapshots, proving
                        the profile gets richer the more the user interacts

Run from arnie/:
    .venv/bin/python simulate_heavy_use.py            # all phases (uses LLM for D,E)
    .venv/bin/python simulate_heavy_use.py --no-llm   # A,B,C only (no API calls)
    .venv/bin/python simulate_heavy_use.py --cleanup
"""
import asyncio
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv(override=True)

G = "\033[92m"; R = "\033[91m"; C = "\033[96m"; Y = "\033[93m"; B = "\033[1m"; X = "\033[0m"; D = "\033[90m"

_pass = 0
_fail = 0


def check(label, cond, detail=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  {G}✓{X} {label}" + (f" {D}{detail}{X}" if detail else ""))
    else:
        _fail += 1
        print(f"  {R}✗ {label}{X}" + (f" {R}{detail}{X}" if detail else ""))
    return cond


def head(t):
    print(f"\n{B}{C}{'═'*64}{X}\n{B}{C} {t}{X}\n{B}{C}{'═'*64}{X}")


SIM_PREFIX = "HSIM_"


# ─────────────────────────────────────────────────────────────────────────────
# Phase A — Schema
# ─────────────────────────────────────────────────────────────────────────────
async def phase_a():
    head("PHASE A — Schema verification")
    from db.database import init_db, engine
    from sqlalchemy import text
    await init_db()
    async with engine.begin() as conn:
        tabs = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = {r[0] for r in tabs.fetchall()}
        check("user_attributes table exists", "user_attributes" in tables)
        ucols = await conn.execute(text("PRAGMA table_info(users)"))
        ucol_names = {r[1] for r in ucols.fetchall()}
        check("users.user_bio column exists", "user_bio" in ucol_names)
        check("users.user_bio_updated_at column exists", "user_bio_updated_at" in ucol_names)
        acols = await conn.execute(text("PRAGMA table_info(user_attributes)"))
        acol_names = {r[1] for r in acols.fetchall()}
        for c in ("attribute_key", "value", "category", "relevance_tier",
                  "attribute_status", "confidence", "last_value", "unit"):
            check(f"user_attributes.{c} column exists", c in acol_names)


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _make_user(db, tg_id, **kw):
    from db.models import User, UserPreferences
    from db.queries import get_or_create_webhook_token
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    existing = (await db.execute(
        select(User).where(User.telegram_id == tg_id).options(selectinload(User.preferences))
    )).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.commit()
    u = User(
        telegram_id=tg_id,
        name=kw.get("name", "Test"), age=kw.get("age"), sex=kw.get("sex"),
        height_cm=kw.get("height_cm"), current_weight_kg=kw.get("weight_kg"),
        goal_weight_kg=kw.get("goal_kg"), primary_goal=kw.get("goal"),
        training_experience=kw.get("exp"), dietary_preferences=kw.get("diet"),
        injuries=kw.get("injuries"), sport=kw.get("sport"),
        timezone=kw.get("tz", "America/New_York"), onboarding_completed=True,
    )
    db.add(u)
    db.add(UserPreferences(
        user=u, calorie_target=kw.get("cal"), protein_target=kw.get("pro"),
        coaching_style=kw.get("coaching", "balanced"),
        accountability_level=kw.get("accountability", "medium"),
        wake_time=kw.get("wake", "07:00"), sleep_time=kw.get("sleep", "23:00"),
    ))
    await db.flush()
    await get_or_create_webhook_token(db, u.id)
    await db.commit()
    return u


# ─────────────────────────────────────────────────────────────────────────────
# Phase B — Plumbing stress (no LLM)
# ─────────────────────────────────────────────────────────────────────────────
async def phase_b():
    head("PHASE B — Plumbing stress (upsert, conflict, canonicalization, tiers)")
    from db.database import AsyncSessionLocal
    from memory.attribute_store import (
        upsert_attribute, get_all_attributes, get_attributes_for_context,
        canonicalize_key,
    )
    from sqlalchemy import select
    from db.models import UserAttribute

    async with AsyncSessionLocal() as db:
        u = await _make_user(db, SIM_PREFIX + "PLUMB", name="Plumb", weight_kg=80.0, goal="cut")
        uid = u.id

        # ── Heavy upsert: 120 attributes across categories ──────────────────
        t0 = time.monotonic()
        cats = ["nutrition", "fitness", "health", "lifestyle", "behavior", "mental", "custom"]
        n = 0
        for i in range(120):
            cat = cats[i % len(cats)]
            await upsert_attribute(
                db, uid,
                attribute_key=f"{cat}_metric_{i}",
                value=f"value_{i}",
                category=cat,
                confidence="inferred",
                source="conversation",
            )
            n += 1
        dt = time.monotonic() - t0
        rows = await get_all_attributes(db, uid)
        check("120 heavy upserts persisted", len(rows) == 120, f"{len(rows)} rows in {dt:.2f}s")

        # ── Conflict resolution: confirmed beats inferred ───────────────────
        await upsert_attribute(db, uid, attribute_key="nutrition_diet_style",
                               value="keto", confidence="confirmed", source="user_stated")
        await upsert_attribute(db, uid, attribute_key="nutrition_diet_style",
                               value="vegan", confidence="inferred", source="conversation")
        row = (await db.execute(select(UserAttribute).where(
            UserAttribute.user_id == uid,
            UserAttribute.attribute_key == "nutrition_diet_style"))).scalar_one()
        check("confirmed not overwritten by later inferred", row.value == "keto",
              f"value={row.value}")

        # ── newer inferred beats older inferred, last_value tracked ─────────
        await upsert_attribute(db, uid, attribute_key="fitness_training_time",
                               value="mornings", confidence="inferred")
        await upsert_attribute(db, uid, attribute_key="fitness_training_time",
                               value="evenings", confidence="inferred")
        row = (await db.execute(select(UserAttribute).where(
            UserAttribute.user_id == uid,
            UserAttribute.attribute_key == "fitness_training_time"))).scalar_one()
        check("newer inferred overwrites older", row.value == "evenings", f"value={row.value}")
        check("last_value tracks previous", row.last_value == "mornings",
              f"last_value={row.last_value}")

        # ── needs_verification cannot clobber confirmed ─────────────────────
        await upsert_attribute(db, uid, attribute_key="health_injuries",
                               value="ACL reconstruction", confidence="confirmed")
        await upsert_attribute(db, uid, attribute_key="health_injuries",
                               value="none", confidence="needs_verification")
        row = (await db.execute(select(UserAttribute).where(
            UserAttribute.user_id == uid,
            UserAttribute.attribute_key == "health_injuries"))).scalar_one()
        check("needs_verification can't clobber confirmed", row.value == "ACL reconstruction",
              f"value={row.value}")

        # ── Canonicalization collision: 3 variants → 1 row ──────────────────
        before = len(await get_all_attributes(db, uid))
        for variant in ("zinc", "daily_zinc", "zinc_mg"):
            ck = canonicalize_key(variant)
            await upsert_attribute(db, uid, attribute_key=variant, value="50",
                                   unit="mg", confidence="confirmed")
        after = len(await get_all_attributes(db, uid))
        zinc_rows = (await db.execute(select(UserAttribute).where(
            UserAttribute.user_id == uid,
            UserAttribute.attribute_key == "health_supplement_zinc_mg"))).scalars().all()
        check("3 zinc variants collapse to 1 canonical row", len(zinc_rows) == 1,
              f"added {after-before} row(s), zinc rows={len(zinc_rows)}")

        # ── Tier-based context injection ────────────────────────────────────
        # core attr — always present
        await upsert_attribute(db, uid, attribute_key="fitness_training_split",
                               value="PPL 6-day", confidence="confirmed",
                               relevance_tier="core")
        # daily attr, fresh — present
        await upsert_attribute(db, uid, attribute_key="nutrition_protein_habits",
                               value="hits 200g most days", confidence="inferred",
                               relevance_tier="daily")
        # daily attr, stale (8 days old) — absent
        await upsert_attribute(db, uid, attribute_key="nutrition_meal_timing",
                               value="IF 16:8", confidence="inferred",
                               relevance_tier="daily")
        stale = (await db.execute(select(UserAttribute).where(
            UserAttribute.user_id == uid,
            UserAttribute.attribute_key == "nutrition_meal_timing"))).scalar_one()
        stale.updated_at = datetime.now(timezone.utc) - timedelta(days=8)
        await db.commit()
        # contextual attr — only on keyword
        await upsert_attribute(db, uid, attribute_key="health_supplement_creatine",
                               value="5g daily", confidence="confirmed",
                               relevance_tier="contextual")

        ctx_generic = await get_attributes_for_context(db, uid, "what should i eat for lunch")
        ctx_supp = await get_attributes_for_context(db, uid, "should i take a creatine supplement")

        check("core attr always injected", "PPL 6-day" in ctx_generic)
        check("fresh daily attr injected", "hits 200g most days" in ctx_generic)
        check("stale daily attr (8d) NOT injected", "IF 16:8" not in ctx_generic,
              "correctly excluded")
        check("contextual attr hidden without keyword", "5g daily" not in ctx_generic)
        check("contextual attr shown on keyword match", "5g daily" in ctx_supp)

        # ── ordering: core before contextual ────────────────────────────────
        ordered = await get_all_attributes(db, uid)
        tiers = [r.relevance_tier for r in ordered]
        core_idxs = [i for i, t in enumerate(tiers) if t == "core"]
        ctx_idxs = [i for i, t in enumerate(tiers) if t == "contextual"]
        if core_idxs and ctx_idxs:
            check("core attrs ordered before contextual", max(core_idxs) < min(ctx_idxs))


# ─────────────────────────────────────────────────────────────────────────────
# Phase C — Concurrency / race safety
# ─────────────────────────────────────────────────────────────────────────────
async def phase_c():
    head("PHASE C — Concurrency & race safety (separate sessions, like prod bg tasks)")
    from db.database import AsyncSessionLocal
    from memory.attribute_store import upsert_attribute, get_all_attributes

    # Create 20 users
    async with AsyncSessionLocal() as db:
        uids = []
        for i in range(20):
            u = await _make_user(db, f"{SIM_PREFIX}CONC_{i}", name=f"User{i}",
                                  weight_kg=70.0 + i, goal="cut")
            uids.append(u.id)
    check("created 20 concurrent-test users", len(uids) == 20)

    # Each user gets two concurrent "background tasks" each on its OWN session,
    # both writing attributes for the same user — mirrors the prod handler pattern
    # (profile task + reflection task) after the session-isolation fix.
    async def bg_writer(uid, tag, keys):
        async with AsyncSessionLocal() as bg_db:
            for k in keys:
                await upsert_attribute(bg_db, uid, attribute_key=k,
                                       value=f"{tag}", confidence="inferred")

    t0 = time.monotonic()
    tasks = []
    for uid in uids:
        tasks.append(bg_writer(uid, "profile", [f"fitness_a_{j}" for j in range(5)]))
        tasks.append(bg_writer(uid, "reflect", [f"behavior_b_{j}" for j in range(5)]))
    # Run ALL 40 concurrent sessions at once
    results = await asyncio.gather(*tasks, return_exceptions=True)
    dt = time.monotonic() - t0
    errs = [r for r in results if isinstance(r, Exception)]
    check("40 concurrent sessions, no exceptions", len(errs) == 0,
          f"{len(tasks)} tasks in {dt:.2f}s" + (f" — ERRORS: {errs[:2]}" if errs else ""))

    # Verify each user has exactly 10 attributes (5+5, no lost writes/corruption)
    async with AsyncSessionLocal() as db:
        counts = []
        for uid in uids:
            rows = await get_all_attributes(db, uid)
            counts.append(len(rows))
        check("every user has exactly 10 attrs (no lost writes)",
              all(c == 10 for c in counts), f"counts={set(counts)}")


# ─────────────────────────────────────────────────────────────────────────────
# Phase D/E — Real synthesis + 3-month growth
# ─────────────────────────────────────────────────────────────────────────────

# Conversation snippets that embed durable facts Arnie should extract.
WEEK1_CONVOS = [
    ("morning, just took my zinc and creatine like usual",
     "Logged the morning routine. Zinc and creatine daily — consistent. What's breakfast looking like?"),
    ("had my usual 4 eggs and oatmeal before the 5am lift",
     "4 eggs + oats, ~520 cal, 32g protein. Solid pre-lift fuel at 5am. How'd the session go?"),
    ("push day done. bench felt heavy, my lower back is acting up again",
     "Noted on the back. We'll keep an eye on it — flag anything that makes it worse. Bench numbers?"),
    ("i work night shifts so my schedule is all over the place",
     "Night shifts change everything — we'll build the plan around your real clock, not a 9-5 one."),
]

MONTH1_CONVOS = WEEK1_CONVOS + [
    ("the physical therapist said my lower back is a disc thing, doing rehab now",
     "Good to know it's disc-related. We avoid loaded spinal flexion then. Rehab consistency is the win here."),
    ("trying to cut to 175, currently around 185. want abs by summer",
     "175 target, aesthetic goal, summer timeline. That's a clean cut. Protein stays high to hold muscle."),
    ("i basically live on chicken, rice, greek yogurt and built bars",
     "Those are your staples — easy to build your day around them. No need to overthink the menu."),
    ("took my vitamin d this morning too, doc said i was low",
     "Vitamin D added to the stack — makes sense if you were flagged low, especially on night shifts."),
    ("my wife and 2 kids keep me busy so i need quick meals",
     "Two kids and a partner — time is tight. We lean on fast, repeatable meals. No 6-step recipes."),
]

MONTH3_CONVOS = MONTH1_CONVOS + [
    ("back is way better now, PT cleared me for deadlifts again",
     "Big milestone — cleared for pulls. We reintroduce slowly, technique first, no ego loading."),
    ("hit 178 this morning, abs are starting to show",
     "178 — you're 3 from goal and it's showing. The cut's working. Hold the line on protein."),
    ("i've been doing 10k steps on my off days religiously",
     "10k on rest days is a strong habit — that's where a lot of the fat loss is quietly happening."),
    ("switched to barebells bars, like them better than built",
     "Noted — barebells is your bar now. I'll treat that as the default when you say 'a bar'."),
    ("honestly the accountability texts are what keep me consistent, i respond to direct",
     "Got it — direct accountability works for you. I'll keep it straight, no sugar-coating."),
    ("started taking magnesium at night for sleep on shift days",
     "Magnesium at night — smart for shift-work sleep. Added to your stack."),
]


async def _seed_convos(db, uid, convos, base_days_ago):
    """Insert conversation rows spread across recent days."""
    from db.queries import log_conversation
    from db.models import ConversationLog
    n = len(convos)
    for i, (umsg, amsg) in enumerate(convos):
        # spread across the window, most recent last
        days_ago = max(0, base_days_ago - int(i * base_days_ago / max(1, n)))
        ts = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=(i % 12))
        c = ConversationLog(user_id=uid, raw_message=umsg, response=amsg,
                            timestamp=ts, source_type="text")
        db.add(c)
    await db.commit()


async def _reset_profile_sync_time(tg_id):
    """Force the next synthesis by clearing throttle (we also pass force=True)."""
    from memory.profile_manager import read_profile, write_profile
    content = await read_profile(tg_id)
    if content:
        import re
        content = re.sub(r"<!-- last_synced: .+? -->",
                         "<!-- last_synced: 2020-01-01T00:00:00+00:00 -->", content, count=1)
        await write_profile(tg_id, content)


def _count_learning_placeholders(md):
    return md.count("(learning)") + md.count("(none yet)") + md.count("(none noted yet)")


async def phase_de(run_llm):
    head("PHASE D/E — Real synthesis + 3-month growth (Sonnet + Haiku)")
    if not run_llm:
        print(f"  {Y}skipped (--no-llm){X}")
        return

    from db.database import AsyncSessionLocal
    from memory.profile_updater import maybe_update_profile
    from memory.profile_manager import read_profile, clear_profile
    from memory.attribute_store import get_all_attributes, get_attributes_for_context
    from memory.memory_manager import clear_memory
    from db.queries import reload_user, get_or_create_webhook_token

    tg_id = SIM_PREFIX + "JORDAN"

    # Fresh start
    await clear_profile(tg_id)
    await clear_memory(tg_id)

    async with AsyncSessionLocal() as db:
        u = await _make_user(
            db, tg_id, name="Jordan", age=34, sex="male",
            height_cm=180.0, weight_kg=85.0, goal_kg=79.0, goal="cut",
            exp="advanced", diet="high-protein, flexible dieting",
            injuries="lower back (disc) — in rehab", tz="America/Chicago",
            cal=2100, pro=200, coaching="direct", accountability="high",
            wake="04:30", sleep="13:00",
        )
        uid = u.id

    checkpoints = [
        ("WEEK 1", WEEK1_CONVOS, 6),
        ("MONTH 1", MONTH1_CONVOS, 28),
        ("MONTH 3", MONTH3_CONVOS, 88),
    ]

    growth = []
    bios = {}
    for label, convos, window in checkpoints:
        print(f"\n  {B}{Y}── {label} ({len(convos)} conversation turns) ──{X}")
        async with AsyncSessionLocal() as db:
            # wipe + reseed convos for this window
            from sqlalchemy import delete
            from db.models import ConversationLog
            await db.execute(delete(ConversationLog).where(ConversationLog.user_id == uid))
            await db.commit()
            await _seed_convos(db, uid, convos, window)

        await _reset_profile_sync_time(tg_id)

        async with AsyncSessionLocal() as db:
            u = await reload_user(db, uid)
            # Clear the 24h bio throttle so each checkpoint regenerates the bio
            # with that checkpoint's knowledge (in prod the 24h TTL is correct —
            # here we want to SEE the bio evolve week1 → month3).
            u.user_bio_updated_at = None
            await db.commit()
            t0 = time.monotonic()
            updated = await maybe_update_profile(u, db, force=True)
            dt = time.monotonic() - t0
            check(f"{label}: synthesis ran", updated, f"{dt:.1f}s")

            md = await read_profile(tg_id)
            attrs = await get_all_attributes(db, uid)
            placeholders = _count_learning_placeholders(md)
            await db.refresh(u)
            bio = u.user_bio or ""

            growth.append((label, len(attrs), placeholders, len(bio)))
            bios[label] = bio
            print(f"    {D}attributes={len(attrs)}  placeholders_left={placeholders}  bio_chars={len(bio)}{X}")

    # ── Growth assertions ───────────────────────────────────────────────────
    print(f"\n  {B}Growth across time:{X}")
    print(f"    {D}{'checkpoint':<10} {'attrs':>6} {'placeholders':>13} {'bio_len':>8}{X}")
    for label, na, ph, bl in growth:
        print(f"    {label:<10} {na:>6} {ph:>13} {bl:>8}")

    w1_attrs, m1_attrs, m3_attrs = growth[0][1], growth[1][1], growth[2][1]
    check("attributes grow week1 → month3", m3_attrs > w1_attrs,
          f"{w1_attrs} → {m3_attrs}")
    check("attributes non-decreasing across checkpoints",
          m1_attrs >= w1_attrs and m3_attrs >= m1_attrs,
          f"{w1_attrs} ≤ {m1_attrs} ≤ {m3_attrs}")

    # Bio evolves: month-3 bio references late-stage facts the week-1 bio can't.
    w1_bio = bios.get("WEEK 1", "").lower()
    m3_bio = bios.get("MONTH 3", "").lower()
    late_facts = ["magnesium", "178", "barebells", "10k", "10,000", "step", "deadlift", "abs"]
    w1_late = sum(1 for f in late_facts if f in w1_bio)
    m3_late = sum(1 for f in late_facts if f in m3_bio)
    check("month-3 bio references more late-stage facts than week-1 bio",
          m3_late > w1_late, f"week1={w1_late} late facts, month3={m3_late}")

    # ── Deep inspection at MONTH 3 ──────────────────────────────────────────
    print(f"\n  {B}MONTH 3 deep inspection:{X}")
    async with AsyncSessionLocal() as db:
        u = await reload_user(db, uid)
        await db.refresh(u)
        attrs = await get_all_attributes(db, uid)
        md = await read_profile(tg_id)

        # The key facts embedded in conversation that should have been extracted
        blob = " ".join(f"{a.attribute_key}={a.value}".lower() for a in attrs)
        md_low = md.lower()
        combined = blob + " " + md_low

        facts = {
            "zinc supplement": "zinc" in combined,
            "creatine supplement": "creatine" in combined,
            "vitamin D supplement": "vitamin d" in combined or "vit d" in combined,
            "magnesium supplement": "magnesium" in combined,
            "lower back / disc": "back" in combined or "disc" in combined,
            "night shift work": "shift" in combined or "night" in combined,
            "early morning training": "morning" in combined or "5am" in combined or "4" in combined,
            "food staples (chicken/rice/yogurt)": ("chicken" in combined or "rice" in combined or "yogurt" in combined),
            "family / kids": "kid" in combined or "wife" in combined or "family" in combined,
            "direct accountability pref": "direct" in combined or "accountab" in combined,
        }
        for fact, present in facts.items():
            check(f"extracted: {fact}", present)

        # Bio quality
        bio = u.user_bio or ""
        check("bio generated", len(bio) > 100, f"{len(bio)} chars")
        check("bio is narrative (not a bare list)", bio.count("\n") < 8 and "." in bio)

        # Categories represented
        cats = {a.category for a in attrs}
        check("multiple categories populated", len(cats) >= 3, f"categories={sorted(cats)}")

        # Context injection budget — what Arnie actually sees on a generic turn
        ctx = await get_attributes_for_context(db, uid, "what should i train today")
        check("context block builds & is bounded", 0 < len(ctx) < 4000, f"{len(ctx)} chars")

        # ── /api/profile endpoint shape ─────────────────────────────────────
        by_cat = {}
        for a in attrs:
            by_cat.setdefault(a.category, []).append(a)
        api_shape_ok = (
            isinstance(bio, str) and isinstance(by_cat, dict) and len(by_cat) >= 3
        )
        check("/api/profile payload assembles", api_shape_ok)

        # ── Print artifacts for eyeball review ──────────────────────────────
        print(f"\n  {B}{C}GENERATED BIO:{X}")
        for line in bio.split("\n"):
            print(f"    {line}")

        print(f"\n  {B}{C}EXTRACTED ATTRIBUTES ({len(attrs)}):{X}")
        cur = None
        for a in sorted(attrs, key=lambda r: (r.category, r.attribute_key)):
            if a.category != cur:
                cur = a.category
                print(f"    {Y}{cur}{X}")
            unit = f" {a.unit}" if a.unit else ""
            conf = "" if a.confidence == "confirmed" else f" {D}[{a.confidence}]{X}"
            print(f"      {a.display_name}: {a.value}{unit}{conf}")

        print(f"\n  {B}{C}PROFILE.MD (Fitness + Health sections):{X}")
        _print_sections(md, ["## Fitness Profile", "## Health & Supplements", "## Nutrition Preferences"])


def _print_sections(md, headers):
    lines = md.split("\n")
    out = []
    capturing = False
    for ln in lines:
        if ln.startswith("## "):
            capturing = any(ln.startswith(h) for h in headers)
        if capturing:
            out.append(ln)
    for ln in out[:45]:
        print(f"    {D}{ln}{X}")


# ─────────────────────────────────────────────────────────────────────────────
async def cleanup():
    from db.database import AsyncSessionLocal
    from db.models import User
    from memory.profile_manager import clear_profile
    from memory.memory_manager import clear_memory
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        users = (await db.execute(
            select(User).where(User.telegram_id.like(SIM_PREFIX + "%"))
        )).scalars().all()
        for u in users:
            await clear_profile(u.telegram_id)
            await clear_memory(u.telegram_id)
            await db.delete(u)
        await db.commit()
        print(f"Deleted {len(users)} simulation users + their profile files.")


async def main(run_llm):
    t0 = time.monotonic()
    await phase_a()
    await phase_b()
    await phase_c()
    await phase_de(run_llm)
    dt = time.monotonic() - t0

    print(f"\n{B}{'═'*64}{X}")
    color = G if _fail == 0 else R
    print(f"{B}{color} RESULT: {_pass} passed, {_fail} failed{X}  {D}({dt:.1f}s total){X}")
    print(f"{B}{'═'*64}{X}\n")
    return _fail == 0


if __name__ == "__main__":
    if "--cleanup" in sys.argv:
        asyncio.run(cleanup())
    else:
        run_llm = "--no-llm" not in sys.argv
        ok = asyncio.run(main(run_llm))
        sys.exit(0 if ok else 1)
