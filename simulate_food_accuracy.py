"""
FOOD-LOGGING CALORIE-ACCURACY SIM
=================================
Drives the REAL `run_turn` pipeline with the LIVE LLM and the production system
prompt across all three `food_logging_mode`s (quick / moderate / strict), against a
curated dataset of real foods with published/USDA ground-truth calories. Measures
the two things that matter for "is Arnie accurate when logging calories":

  1. BIAS   — mean signed error. Negative = systematic UNDER-counting (the reported
              failure). We want this near 0, and NOT meaningfully negative.
  2. MAE    — mean absolute error. Lower = tighter. Should DECREASE with strictness
              (strict ≤ moderate ≤ quick), because a stricter posture gathers more
              truth (asks) while quick pads for the unknown.

For ambiguous items ("a burrito bowl"), strict is expected to ask one question; the
sim feeds the realistic `clarify` answer and lets it log, so we measure the mode's
true accuracy posture, not "did it happen to ask".

Run from arnie/ (needs the .venv deps + ANTHROPIC_API_KEY in .env):
    .venv/bin/python simulate_food_accuracy.py            # full dataset, 3 modes
    .venv/bin/python simulate_food_accuracy.py --n 10     # first 10 items only
    .venv/bin/python simulate_food_accuracy.py --selfcheck  # metrics math only, NO LLM

The dataset ground-truth values are real published figures (chain nutrition pages,
USDA FoodData Central) for a normal adult portion — floors, not maxima. Sources are
noted inline; adjust if a chain updates its menu.
"""
import argparse
import asyncio
import statistics
import sys

# ── ANSI ──────────────────────────────────────────────────────────────────────
G = "\033[92m"; R = "\033[91m"; C = "\033[96m"; Y = "\033[93m"; B = "\033[1m"; X = "\033[0m"; D = "\033[90m"

MODES = ["quick", "moderate", "strict"]

# ── Ground-truth dataset ──────────────────────────────────────────────────────
# (description, truth_calories, category, clarify_answer)
#   clarify_answer = the realistic detail a strict-mode question would elicit for an
#   AMBIGUOUS item; None = the item is specific enough that no mode should need to ask.
DATASET = [
    # ── specific items: every mode should land close (published values) ──
    ("a medium banana",                                             105, "snack",     None),
    ("6 oz grilled chicken breast",                                 280, "protein",   None),
    ("a cup of cooked white rice",                                  205, "side",      None),
    ("a handful of almonds",                                        170, "snack",     None),
    ("greek yogurt with berries and honey",                         260, "breakfast", None),
    ("2 eggs and 2 slices of toast with butter",                    430, "breakfast", None),
    ("a big mac",                                                   563, "fastfood",  None),   # McDonald's
    ("medium mcdonald's fries",                                     320, "fastfood",  None),   # McDonald's
    ("an in-n-out double-double",                                   670, "fastfood",  None),   # In-N-Out
    ("a chick-fil-a spicy chicken sandwich",                        450, "fastfood",  None),   # Chick-fil-A
    ("a slice of pepperoni pizza",                                  310, "restaurant",None),
    ("a grande caramel macchiato with whole milk",                  250, "beverage",  None),   # Starbucks
    ("a starbucks blueberry muffin",                                360, "pastry",    None),   # Starbucks
    ("a footlong subway italian b.m.t.",                            800, "fastfood",  None),   # Subway footlong
    ("a chipotle chicken burrito with rice, black beans, cheese, and guac", 1075, "restaurant", None),  # Chipotle
    ("a protein shake with a scoop of whey, a banana, and 12oz whole milk", 400, "beverage", None),
    ("avocado toast with two eggs",                                 450, "breakfast", None),
    ("pad thai takeout with chicken",                              1050, "restaurant",None),
    ("chicken tikka masala with rice and a piece of naan",         1150, "restaurant",None),
    ("5 buffalo wings with blue cheese",                            500, "restaurant",None),
    ("a chicken caesar salad at a restaurant",                      700, "restaurant",None),
    ("a turkey club sandwich with fries",                           900, "restaurant",None),

    # ── ambiguous items: quick PADS, strict ASKS (clarify given), moderate between ──
    ("a burrito bowl",           850, "restaurant", "chicken, white rice, black beans, cheese, sour cream, and guac"),
    ("some pasta with red sauce",650, "dinner",     "about 2 cups, with parmesan and a drizzle of olive oil"),
    ("a salad for lunch",        550, "lunch",      "grilled chicken, cheese, croutons, and ranch dressing"),
    ("a bowl of cereal",         300, "breakfast",  "about 1.5 cups of honey nut cheerios with whole milk"),
    ("a smoothie",               400, "beverage",   "banana, peanut butter, a scoop of whey, and almond milk"),
    ("a stir fry",               700, "dinner",     "chicken and veggies over rice, cooked in oil with a soy sauce glaze"),
    ("a sandwich",               550, "lunch",      "turkey and cheese on a sub roll with mayo"),
    ("chicken and rice",         650, "dinner",     "about 8oz chicken thigh and 1.5 cups rice, cooked in oil"),
]


def pct_err(est: float, truth: float) -> float:
    return (est - truth) / truth * 100.0


# ── Metrics + report (pure — exercised by --selfcheck) ────────────────────────
def summarize(mode_rows: dict) -> dict:
    """mode -> list of (desc, truth, est, category, asked). Returns per-mode stats."""
    stats = {}
    for mode, rows in mode_rows.items():
        scored = [(t, e) for (_, t, e, _, _) in rows if e is not None and e > 0]
        if not scored:
            stats[mode] = None
            continue
        signed = [pct_err(e, t) for (t, e) in scored]
        absl = [abs(s) for s in signed]
        n = len(scored)
        stats[mode] = {
            "n": n,
            "bias": statistics.mean(signed),                       # <0 = undercount
            "mae": statistics.mean(absl),
            "under": sum(1 for (t, e) in scored if e < t * 0.90) / n,   # >10% low
            "over": sum(1 for (t, e) in scored if e > t * 1.15) / n,    # >15% high
            "asked": sum(1 for (_, _, e, _, a) in rows if a and e) ,
            "missed": sum(1 for (_, _, e, _, _) in rows if not e),      # never logged
        }
    return stats


def print_report(mode_rows: dict) -> dict:
    stats = summarize(mode_rows)
    print(f"\n{B}{C}{'═'*74}{X}")
    print(f"{B}{C} FOOD-LOGGING CALORIE ACCURACY — by mode{X}")
    print(f"{B}{C}{'═'*74}{X}")
    print(f"  {B}{'mode':<10}{'n':>4}{'bias%':>9}{'MAE%':>8}{'under%':>9}{'over%':>8}{'asked':>7}{'missed':>8}{X}")
    print(f"  {D}{'-'*72}{X}")
    for mode in MODES:
        s = stats.get(mode)
        if not s:
            print(f"  {mode:<10}{'—':>4}  (no results)")
            continue
        bias_c = G if s["bias"] >= -5 else (Y if s["bias"] >= -12 else R)
        print(f"  {mode:<10}{s['n']:>4}{bias_c}{s['bias']:>+8.1f}{X}{s['mae']:>8.1f}"
              f"{s['under']*100:>8.0f}%{s['over']*100:>7.0f}%{s['asked']:>7}{s['missed']:>8}")
    print(f"  {D}{'-'*72}{X}")
    print(f"  {D}bias<0 = undercount (the bug). MAE should fall as strictness rises.{X}")

    # ── verdicts ──
    print()
    ok = True
    have = [m for m in MODES if stats.get(m)]

    def verdict(label, cond, detail=""):
        nonlocal ok
        mark = f"{G}✓{X}" if cond else f"{R}✗{X}"
        if not cond:
            ok = False
        print(f"  {mark} {label}" + (f"  {D}{detail}{X}" if detail else ""))

    for m in have:
        s = stats[m]
        verdict(f"[{m}] not systematically undercounting (bias ≥ -8%)",
                s["bias"] >= -8.0, f"bias {s['bias']:+.1f}%")
        verdict(f"[{m}] undercount rate < 30%",
                s["under"] < 0.30, f"{s['under']*100:.0f}%")
    if stats.get("strict") and stats.get("quick"):
        verdict("accuracy rises with strictness (strict MAE ≤ quick MAE)",
                stats["strict"]["mae"] <= stats["quick"]["mae"] + 1.0,
                f"strict {stats['strict']['mae']:.1f} vs quick {stats['quick']['mae']:.1f}")
    if stats.get("strict") and stats.get("moderate"):
        verdict("strict ≤ moderate MAE (within noise)",
                stats["strict"]["mae"] <= stats["moderate"]["mae"] + 2.0,
                f"strict {stats['strict']['mae']:.1f} vs moderate {stats['moderate']['mae']:.1f}")
    print()
    print(f"  {B}{(G+'PASS') if ok else (R+'REVIEW')}{X}\n")
    return {"stats": stats, "ok": ok}


# ── Live-LLM run (needs .venv + key) ──────────────────────────────────────────
async def _run_one(Maker, run_turn, build_context, get_or_create_today_log,
                   log_conversation, reload_user, delete_today_food, uid, system_base,
                   desc, clarify):
    """One food message through run_turn; if the model asks (no log_food + '?') and
    we have a clarify answer, answer once and log. Returns (est_calories, asked)."""
    def _sum_food(tcs):
        return sum(float(tc.get("input", {}).get("calories") or 0)
                   for tc in tcs if tc.get("name") == "log_food")

    async with Maker() as db:
        user = await reload_user(db, uid)
        today = await get_or_create_today_log(db, uid, user.timezone)
        ctx = await build_context(user, today, db, platform="telegram", user_message=desc)
        system = f"{system_base}\n\n{ctx}"
        messages = [{"role": "user", "content": desc}]
        turn = await run_turn(user, db, messages, system, platform="telegram",
                              in_onboarding=False, was_onboarding=False,
                              today_log=today, source_type="text")
        est = _sum_food(turn.tool_calls)
        asked = False
        if est == 0 and clarify:
            bubbles = turn.response.bubbles
            if any("?" in b for b in bubbles):
                asked = True
                messages.append({"role": "assistant", "content": "|||".join(bubbles)})
                messages.append({"role": "user", "content": clarify})
                turn2 = await run_turn(user, db, messages, system, platform="telegram",
                                       in_onboarding=False, was_onboarding=False,
                                       today_log=today, source_type="text")
                est = _sum_food(turn2.tool_calls)
        await delete_today_food(db, uid)   # isolate the next item
        await db.commit()
        return est, asked


async def main_live(limit):
    from dotenv import load_dotenv
    load_dotenv(override=True)
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"{R}ANTHROPIC_API_KEY not set — run with .venv + a real key.{X}")
        sys.exit(2)

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import StaticPool
    from sqlalchemy import delete
    from db.database import Base, _migrate
    from db import models  # noqa
    from db.models import User, UserPreferences, FoodEntry, DailyLog
    from db.queries import (get_or_create_webhook_token, get_or_create_today_log,
                            log_conversation, reload_user)
    from core.context_builder import build_context
    from core.prompts import build_arnie_system
    from core.conversation import run_turn

    engine = create_async_engine("sqlite+aiosqlite://",
                                 connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
    Maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    system_base = build_arnie_system(platform="telegram")

    async with Maker() as db:
        u = User(telegram_id="FOODSIM_001", name="Sam", age=30, sex="male",
                 height_cm=178.0, current_weight_kg=82.0, goal_weight_kg=77.0,
                 primary_goal="cut", training_experience="intermediate",
                 timezone="America/New_York", onboarding_completed=True)
        db.add(u)
        db.add(UserPreferences(user=u, calorie_target=2200, protein_target=185,
                               food_logging_mode="moderate"))
        await db.flush()
        await get_or_create_webhook_token(db, u.id)
        uid = u.id
        await db.commit()

    async def delete_today_food(db, user_id):
        # zero the day so each item is measured in isolation (context doesn't accrete)
        user = await reload_user(db, user_id)
        today = await get_or_create_today_log(db, user_id, user.timezone)
        await db.execute(delete(FoodEntry).where(FoodEntry.daily_log_id == today.id))
        today.total_calories = today.total_protein = today.total_carbs = today.total_fats = 0
        await db.flush()

    async def set_mode(mode):
        async with Maker() as db:
            u = await reload_user(db, uid)
            u.preferences.food_logging_mode = mode
            await db.commit()

    items = DATASET[:limit] if limit else DATASET
    mode_rows = {m: [] for m in MODES}
    for mode in MODES:
        await set_mode(mode)
        print(f"\n{B}{Y}── {mode.upper()} ──{X}")
        for desc, truth, cat, clarify in items:
            try:
                est, asked = await _run_one(
                    Maker, run_turn, build_context, get_or_create_today_log,
                    log_conversation, reload_user, delete_today_food, uid,
                    system_base, desc, clarify)
            except Exception as e:  # one bad item never kills the run
                print(f"  {R}! {desc[:40]}: {type(e).__name__}: {e}{X}")
                est, asked = None, False
            mode_rows[mode].append((desc, truth, est, cat, asked))
            if est:
                e = pct_err(est, truth)
                col = G if abs(e) <= 12 else (Y if abs(e) <= 25 else R)
                flag = " (asked)" if asked else ""
                print(f"  {col}{e:>+6.0f}%{X}  {desc[:44]:<44} est {est:>5.0f} vs {truth:>5.0f}{D}{flag}{X}")
            else:
                print(f"  {R}   ——{X}  {desc[:44]:<44} {D}no log_food{X}")

    res = print_report(mode_rows)
    sys.exit(0 if res["ok"] else 1)


def selfcheck():
    """Validate the metrics + report with synthetic data — proves the harness logic
    WITHOUT the LLM. quick undercounts, moderate mild, strict tight → gradient holds."""
    import random
    rng = random.Random(7)
    rows = {m: [] for m in MODES}
    profile = {"quick": (-3, 9), "moderate": (-1, 6), "strict": (0.5, 4)}  # (bias%, spread%)
    for desc, truth, cat, clarify in DATASET:
        for m in MODES:
            b, sp = profile[m]
            est = round(truth * (1 + (b + rng.uniform(-sp, sp)) / 100.0))
            rows[m].append((desc, truth, est, cat, bool(clarify) and m == "strict"))
    res = print_report(rows)
    # the synthetic profile is engineered to satisfy the gradient — assert the harness agrees
    assert res["ok"], "selfcheck: report logic rejected a known-good synthetic profile"
    print(f"  {G}selfcheck OK — metrics + gradient logic sound.{X}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0, help="limit to first N dataset items")
    ap.add_argument("--selfcheck", action="store_true", help="metrics math only, no LLM")
    args = ap.parse_args()
    if args.selfcheck:
        selfcheck()
    else:
        asyncio.run(main_live(args.n or 0))
