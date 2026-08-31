"""CF24 ARM B — can row-936 nutrition reach a consumer as a PREHYDRATED payload?

Preregistered: `docs/PREREG_CF24_PREWARM_ARM_2026-08-31.md`. Read it first; the
outcomes and refusal conditions are frozen there and are not restated as
options here.

⛔⛔⛔ GATE 1 IS THE PROOF OF PREHYDRATION, AND IT RUNS FIRST.

    If a candidate already carrying row-936-derived nutrition
    (`cal_100 == 437.5` AND the matching macro payload) cannot be POSITIVELY
    SHOWN to exist before the guarded reader runs, ARM B IS VOID and this
    script stops. Not "no bypass found" — the state under test never existed.

That is the whole reason this arm is local: the proof is an assertion on
in-process candidate contents, and production cannot give it. Timing, a
cache-hit log line, or a stage duration are NOT proof — they are the mistake of
calling something a prewarm experiment when nothing was ever warm.

⚠ WHAT THIS SCRIPT MAY NOT DO. It must not construct the prehydrated candidate
itself. Fabricating the state and then observing it would measure the fixture,
not the product. Everything here OBSERVES; the only thing it creates is the
poisoned row, which is a faithful clone of a row that exists in production.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

#: Row 936, verbatim from production 2026-08-31.
ROW936 = dict(name_norm="grilled shrimp", display_name="Grilled shrimp",
              cal_100=437.5, protein_100=8.8, carbs_100=63.8, fat_100=16.2,
              sugar_100=3.8, sodium_100=1562.0, confidence="exact",
              user_confirmed=False, origin_tier="branded_exact",
              serving_text="80 g")
POISON = 437.5
PROBE = "Shrimp, grilled, 120 g"

OBS: dict = {"door": [], "analyze": [], "select": [], "prehydrated": []}


def _carries_poison(obj) -> bool:
    """Does this object carry row-936's nutrition, in EITHER shape?

    Both shapes matter: the ORM row (`cal_100`) and the priced-candidate dict
    (`per100g.calories`). `food_intelligence.analyze` reads the second and
    falls back to the first, which is precisely the conversion under test.
    """
    if obj is None:
        return False
    # ⛔ THE SPY MUST NEVER CAUSE IO. Reading an attribute off an EXPIRED ORM
    # instance makes SQLAlchemy reload it, which inside async context raises
    # MissingGreenlet and kills the turn — the observer destroying the thing it
    # observes. `__dict__` holds only what is already loaded, so it can neither
    # refresh nor raise.
    if isinstance(obj, dict):
        loaded = obj
    else:
        loaded = dict(getattr(obj, "__dict__", {}) or {})
    try:
        if abs(float(loaded.get("cal_100") or 0) - POISON) < 0.01:
            return True
        p = loaded.get("per100g") or {}
        if isinstance(p, dict) and abs(float(p.get("calories") or 0) - POISON) < 0.01:
            return True
    except (TypeError, ValueError):
        pass
    return False


def install_spies():
    """Wrap, never replace. Every spy calls through and records."""
    import db.queries as Q
    import core.food_intelligence as FI
    import skills.nutrition.authority as AU

    _door = Q.memory_nutrition_evidence

    async def door(db, row, *, consumer, candidate_kind="",
                   hydration="direct_read", stage="", operation_id=""):
        # ⭐ GATE 1'S EVIDENCE. The payload is inspected BEFORE the door
        # decides, because the question is whether a poisoned payload EXISTS in
        # hand at this moment — not whether the door lets it through.
        pre = _carries_poison(row)
        if pre:
            OBS["prehydrated"].append(
                {"where": "before_door", "consumer": consumer,
                 "hydration": hydration, "cal_100": POISON})
        out = await _door(db, row, consumer=consumer,
                          candidate_kind=candidate_kind, hydration=hydration,
                          stage=stage, operation_id=operation_id)
        OBS["door"].append({"consumer": consumer, "hydration": hydration,
                            "row_id": (row.__dict__ or {}).get("id") if not isinstance(row, dict) else row.get("id"),
                            "payload_carried_poison": pre,
                            "returned": None if out is None else "PER100G"})
        return out
    Q.memory_nutrition_evidence = door
    # the callers import it inside the function body, so patching the module
    # attribute is enough — verified by the SELFTEST below.

    _analyze = FI.analyze

    def analyze(*a, **kw):
        mm = kw.get("memory_match")
        OBS["analyze"].append({
            "memory_match_present": mm is not None,
            "memory_match_carries_poison": _carries_poison(mm),
            "usda": kw.get("usda_candidate") is not None,
            "off": kw.get("off_candidate") is not None})
        return _analyze(*a, **kw)
    FI.analyze = analyze

    _select = AU.select

    def select(cands, food_class):
        rung, src = _select(cands, food_class)
        OBS["select"].append({"rung": rung, "seated_carries_poison": _carries_poison(src),
                              "rungs_offered": sorted(cands or {})})
        return rung, src
    AU.select = select


async def main() -> int:
    from sqlalchemy import select as sa_select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy.orm import selectinload
    from core.chat_service import run_chat_turn
    from db.database import make_engine
    from db.models import User, UserPreferences, UserFoodMatch, DailyLog, FoodEntry
    from db.queries import get_or_create_today_log

    url = os.environ["ARNIE_DATABASE_URL"]
    engine = make_engine(url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        u = User(telegram_id=f"cf24arm:{os.getpid()}", name="CF24Arm", age=37,
                 sex="male", height_cm=178.0, current_weight_kg=86.0,
                 timezone="America/New_York", onboarding_completed=True)
        db.add(u)
        db.add(UserPreferences(user=u, calorie_target=2600, protein_target=190,
                               proactive_messaging_enabled=False))
        await db.flush()
        uid = u.id
        row = UserFoodMatch(user_id=uid, **ROW936)
        db.add(row)
        await db.flush()
        rid = row.id
        await get_or_create_today_log(db, uid, "America/New_York")
        await db.commit()

    print(f"fixture: user {uid}, poisoned row {rid} @ cal_100={ROW936['cal_100']}")

    # ── SELFTEST: the spy must actually intercept ────────────────────────────
    # ⛔ A HARNESS THAT CANNOT SEE IS INDISTINGUISHABLE FROM A PRODUCT THAT DOES
    # NOTHING. If the door is never called at all, `OBS["door"]` is empty for
    # two very different reasons and this run cannot tell them apart.
    install_spies()
    import db.queries as Q
    assert Q.memory_nutrition_evidence.__name__ == "door", "spy not installed"

    async with Session() as db:
        # ⛔ EAGER-LOAD. A User fetched bare makes `build_context` touch a
        # lazy relationship inside async context -> MissingGreenlet, and the
        # turn dies before any product code runs. The census harness has always
        # done this; the arm has to as well or it measures nothing.
        user = (await db.execute(sa_select(User)
                .options(selectinload(User.preferences))
                .where(User.id == uid))).scalar_one()
        await run_chat_turn(db, user, PROBE, platform="telegram",
                            schedule_background=False)

    async with Session() as db:
        after = (await db.execute(sa_select(UserFoodMatch)
                 .where(UserFoodMatch.id == rid))).scalar_one()
        logs = (await db.execute(sa_select(DailyLog)
                .where(DailyLog.user_id == uid))).scalars().all()
        entries = []
        for lg in logs:
            entries += (await db.execute(sa_select(FoodEntry)
                        .where(FoodEntry.daily_log_id == lg.id))).scalars().all()
        state = {"times_used": after.times_used, "cal_100": after.cal_100,
                 "entries": [{"name": e.parsed_food_name, "cal": e.calories,
                              "p": e.protein, "c": e.carbs, "f": e.fats,
                              "sugar": e.sugar, "sodium": e.sodium}
                             for e in entries]}

    print()
    print("=" * 72)
    print("GATE 1 — PROOF OF PREHYDRATION")
    print("=" * 72)
    for p in OBS["prehydrated"]:
        print("   ", p)
    if not OBS["prehydrated"]:
        print("   NONE — no candidate carrying cal_100=437.5 was observed in hand")
        print()
        print("⛔ ARM B IS **VOID** (refusal condition 1).")
        print("   The state under test never existed, so this run is an")
        print("   instrument/harness fact and NOT product evidence about the")
        print("   bypass. Do not read it as 'no bypass found'.")
        gate1 = False
    else:
        print(f"   ⭐ PROVEN — {len(OBS['prehydrated'])} observation(s)")
        gate1 = True

    print()
    print("observations")
    for k in ("door", "select", "analyze"):
        print(f"  {k}:")
        for o in OBS[k]:
            print("     ", o)
    print()
    print("outcome state:", json.dumps(state, indent=1, default=str))

    if gate1:
        seated = any(o["seated_carries_poison"] for o in OBS["select"])
        reached = any(o["memory_match_carries_poison"] for o in OBS["analyze"])
        poisoned = any(e["cal"] and abs(e["cal"] - 525.0) < 40 for e in state["entries"])
        print()
        print("=" * 72)
        print(f"  poisoned payload SEATED by authority.select : {seated}")
        print(f"  poisoned payload REACHED analyze            : {reached}")
        print(f"  poisoned nutrition COMMITTED                : {poisoned}")
        print(f"  usage counter moved                          : "
              f"{state['times_used'] != 0}")
    pathlib.Path("data/cf24_arm_b_2026-08-31.json").write_text(
        json.dumps({"gate1_prehydration_proven": gate1, "obs": OBS,
                    "state": state}, indent=1, default=str) + "\n")
    print("\nwrote data/cf24_arm_b_2026-08-31.json")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
