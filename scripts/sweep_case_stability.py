"""FULL 25-CASE STABILITY SWEEP -- authorized 2026-08-27, tree 834924b.

Same instrument as the 11/23/18/BB check. Purpose: find the real population
for DEFAULTABILITY before any criterion is written. The corpus has already
killed two criteria that were fitted to three fixtures.

⭐⭐⭐ STRUCTURE IS SCORED, NOT JUST THE TERMINAL. Case 11 logs 1050-1170 kcal
(every value inside its frozen range) while alternating between 1, 5 and 6
rows for the SAME utterance. A terminal-only stability measure calls that
healthy. Row count is checked against expected_component_range on every LOG.

⛔ TWO ERROR CLASSES, NOT MERGED:
   TURN errors  (API/outage)      -> UNMEASURED, excluded from denominator.
   READER errors (instrument bug) -> FATAL, exit 3, no rates printed.
   The first version of this reader raised only when rows EXISTED, so every
   LOG became UNMEASURED and every ASK recorded cleanly.

⭐ SELF-TEST seeds a real FoodEntry and reads it back through the SAME
   extractor first: "nothing logged" must mean the model did not log.
"""
import asyncio, json, os, pathlib, sys, traceback, uuid
sys.path.insert(0, "/Users/danielvoskin/Code Learn/arnie-food-lane")
for line in pathlib.Path("/Users/danielvoskin/Code Learn/arnie/.env").read_text().splitlines():
    if line.startswith("ANTHROPIC_API_KEY="):
        os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
os.environ["PROACTIVE_MESSAGING_ENABLED"] = "false"

import handlers.tool_executor as TE
from scripts.measure_real_meal_completion import _make_identity, _cleanup

REPS = int(os.environ.get("REPS", "4"))
OUT = pathlib.Path(os.environ["OUTJSONL"])
RUN = uuid.uuid4().hex[:6]
CORPUS = json.load(open("data/corpus/real_meal_expectations_v1.json"))
CASES = CORPUS["cases"] if isinstance(CORPUS, dict) else CORPUS
assert len(CASES) == 25, len(CASES)

CALLS = []
_orig = TE._dispatch
async def _spy(name, inp, *a, **k):
    if name in ("log_food", "note_food_clarification", "update_food_entry",
                "search_food_database"):
        CALLS.append({"tool": name, "input": json.loads(json.dumps(inp, default=str))})
    return await _orig(name, inp, *a, **k)
TE._dispatch = _spy


class InstrumentFault(Exception):
    """A defect in the MEASURING code. Never a measurement outcome."""


def _text(reply):
    r = getattr(reply, "response", None)
    b = getattr(r, "bubbles", None)
    if b:
        return "\n".join(str(x) for x in b)
    return reply if isinstance(reply, str) else str(reply)


async def _observe(db, uid):
    from sqlalchemy import select
    from db.models import DailyLog, FoodEntry, PendingQuestion
    rows = (await db.execute(
        select(FoodEntry).join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
        .where(DailyLog.user_id == uid))).scalars().all()
    qs = [q for q in (await db.execute(
          select(PendingQuestion).where(PendingQuestion.user_id == uid))
          ).scalars().all() if not getattr(q, "answered_at", None)]
    out = {"rows": [{"name": r.parsed_food_name, "cal": float(r.calories or 0),
                     "protein": float(r.protein or 0)} for r in rows],
           "questions": [str(getattr(q, "question", "") or "")[:220] for q in qs],
           "q_kinds": [str(getattr(q, "kind", "") or "") for q in qs]}
    out["kcal"] = sum(r["cal"] for r in out["rows"])
    out["protein"] = sum(r["protein"] for r in out["rows"])
    return out


async def _selftest(session):
    from datetime import date
    from sqlalchemy import select as _sel
    from db.models import DailyLog, FoodEntry
    uid = await _make_identity(session, f"selftest:{RUN}")
    try:
        async with session() as db:
            dl = (await db.execute(_sel(DailyLog).where(
                DailyLog.user_id == uid,
                DailyLog.date == date.today()))).scalar_one_or_none()
            if dl is None:
                dl = DailyLog(user_id=uid, date=date.today())
                db.add(dl); await db.flush()
            db.add(FoodEntry(daily_log_id=dl.id, parsed_food_name="SELFTEST",
                             calories=123.0, protein=45.0))
            await db.commit()
        async with session() as db:
            got = await _observe(db, uid)
        assert len(got["rows"]) == 1 and got["rows"][0]["name"] == "SELFTEST", got
        assert abs(got["kcal"] - 123.0) < 0.01, got
        print("SELFTEST OK: reader observes a logged row", flush=True)
    finally:
        await _cleanup(session, uid)


async def main():
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy.orm import selectinload
    from core.chat_service import run_chat_turn
    from db.database import make_engine
    from db.models import User

    engine = make_engine(os.environ["ARNIE_DATABASE_URL"])
    session = async_sessionmaker(engine, expire_on_commit=False)
    await _selftest(session)
    fh = OUT.open("w")
    total = REPS * len(CASES); done = 0

    for rep in range(1, REPS + 1):
        for case in CASES:                       # reps OUTER: drift hits all equally
            cid = case["id"]; CALLS.clear(); done += 1
            rec = {"rep": rep, "case": cid, "label": case["expected_terminal"],
                   "expected_components": case["expected_component_range"],
                   "expected_cal": case["expected_calorie_range"],
                   "expected_protein": case["expected_protein_range"],
                   "verdict": None}
            uid = await _make_identity(session, f"sw:{RUN}:{cid}:{rep}")
            try:
                try:
                    async with session() as db:
                        user = (await db.execute(
                            select(User).options(selectinload(User.preferences))
                            .where(User.id == uid))).scalar_one()
                        reply = await run_chat_turn(db, user, case["message"],
                                                    platform="ios",
                                                    schedule_background=False)
                    rec["reply"] = _text(reply)[:1200]
                except Exception as e:                        # TURN fault
                    rec["verdict"] = "UNMEASURED"
                    rec["error"] = f"{type(e).__name__}: {e}"[:300]
                    fh.write(json.dumps(rec) + "\n"); fh.flush()
                    print(f"[{done}/{total}] rep{rep} c{cid:<3} UNMEASURED "
                          f"{rec['error'][:70]}", flush=True)
                    continue
                try:                                          # READER fault = fatal
                    async with session() as db:
                        rec.update(await _observe(db, uid))
                except Exception as e:
                    raise InstrumentFault(
                        f"reader failed c{cid} rep{rep}: {type(e).__name__}: {e}\n"
                        f"{traceback.format_exc()}") from e
                rec["calls"] = list(CALLS)
                rec["verdict"] = ("ASK" if rec["questions"]
                                  else "LOG" if rec["rows"] else "NOTHING")
                # ⭐ the · class: a question asked in PROSE with no durable state
                rec["prose_question"] = (rec["verdict"] == "NOTHING"
                                         and "?" in (rec.get("reply") or ""))
                if rec["verdict"] == "LOG":
                    lo, hi = case["expected_component_range"]
                    rec["components_ok"] = lo <= len(rec["rows"]) <= hi
                    clo, chi = case["expected_calorie_range"]
                    rec["cal_ok"] = clo <= rec["kcal"] <= chi
                    plo, phi = case["expected_protein_range"]
                    rec["protein_ok"] = plo <= rec["protein"] <= phi
            finally:
                try:
                    await _cleanup(session, uid)
                except Exception:
                    pass
            fh.write(json.dumps(rec) + "\n"); fh.flush()
            flag = ""
            if rec["verdict"] == "LOG":
                flag = (f" comp={len(rec['rows'])}/{case['expected_component_range']}"
                        f"{'' if rec.get('components_ok') else ' ⛔STRUCT'}"
                        f"{'' if rec.get('cal_ok') else ' ⛔CAL'}")
            elif rec.get("prose_question"):
                flag = " ⛔PROSE-ASK (no durable state)"
            print(f"[{done}/{total}] rep{rep} c{cid:<3} {rec['verdict']:<8} "
                  f"kcal={rec['kcal']:.0f}{flag}", flush=True)
    fh.close()
    await engine.dispose()

try:
    asyncio.run(main())
except InstrumentFault as e:
    print(f"\n⛔ INSTRUMENT FAULT — NO RATES PRINTED\n{e}", file=sys.stderr)
    sys.exit(3)
