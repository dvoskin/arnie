"""PRODUCER CHARACTERISATION — what does the interpreter ACTUALLY emit?

⛔ MEASUREMENT, NOT REPAIR. Before any fix to producer completeness, establish:

  1. what `ambiguities[].field` each semantic subject arrives as;
  2. whether a COMPOUND question emits MULTIPLE ambiguity records or one;
  3. whether the interpreter emits ANY other distinguishing signal my mapper
     is discarding (points, questions, requested_fields, item flags).

(3) decides the tranche's shape. The food prompt is FROZEN, so if the
interpreter already carries distinguishing information, this is a code fix. If
it emits one undifferentiated `quantity` with nothing else, producer
completeness is NOT achievable under the freeze.
"""
import asyncio, json, os, pathlib, sys, uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
for line in pathlib.Path("/Users/danielvoskin/Code Learn/arnie/.env").read_text().splitlines():
    if line.startswith("ANTHROPIC_API_KEY="):
        os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"')

import core.food_turn as FT
from scripts.config_pin import pin_config
from scripts.measure_real_meal_completion import _make_identity, _cleanup

REPS = int(os.environ.get("REPS", "3"))
OUT = pathlib.Path(os.environ["OUTJSONL"])
CASES = [int(x) for x in (os.environ.get("ONLY_CASES") or "").replace(",", " ").split()]
# ⭐ SELECTABLE CORPUS, ONE INSTRUMENT. Hardcoding this made an entire
# 24-turn run return KeyError on every case; the CONTROLS caught it,
# which is why a discrimination set carries known-good emitters.
CONFIG = pin_config()   # ⛔ refuses to run on undeclared drift
_CORPUS_FILE = os.environ.get("CORPUS_FILE",
                              "data/corpus/real_meal_expectations_v1.json")
CORPUS = json.load(open(_CORPUS_FILE))
BY_ID = {c["id"]: c for c in (CORPUS["cases"] if isinstance(CORPUS, dict) else CORPUS)}

CAP = []
_orig = FT._ask_types_from
def _spy(data):
    d = data or {}
    items = {str((i or {}).get("food") or "").lower(): bool((i or {}).get("branded"))
             for i in (d.get("items") or []) if isinstance(i, dict)}
    CAP.append({
        "n_ambiguities": len(d.get("ambiguities") or []),
        "ambiguities": [{"item": a.get("item"), "field": a.get("field"),
                         "impact_cal": a.get("impact_cal")}
                        for a in (d.get("ambiguities") or []) if isinstance(a, dict)],
        # ⭐ EVERYTHING ELSE THAT MIGHT DISTINGUISH A SUBJECT
        "data_keys": sorted(k for k in d.keys()),
        "points": [ (p if isinstance(p, str) else
                     {"label": p.get("label"), "qs": p.get("qs")})
                    for p in (d.get("points") or []) ][:4],
        "requested_fields": d.get("requested_fields"),
        "questions": d.get("questions"),
        "branded_items": items,
    })
    return _orig(data)
FT._ask_types_from = _spy


async def main():
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy.orm import selectinload
    from core.chat_service import run_chat_turn
    from db.database import make_engine
    from db.models import PendingQuestion, User

    engine = make_engine(os.environ["ARNIE_DATABASE_URL"])
    session = async_sessionmaker(engine, expire_on_commit=False)
    fh = OUT.open("w"); run = uuid.uuid4().hex[:6]; n = 0
    fh.write(json.dumps({"_config": CONFIG, "_reps": REPS,
                         "_corpus": _CORPUS_FILE,
                         "_only_cases": CASES}) + "\n")
    fh.flush()
    for rep in range(1, REPS + 1):
        for cid in CASES:
            CAP.clear(); n += 1
            uid = await _make_identity(session, f"pc:{run}:{cid}:{rep}")
            rec = {"case": cid, "rep": rep}
            try:
                async with session() as db:
                    u = (await db.execute(select(User)
                         .options(selectinload(User.preferences))
                         .where(User.id == uid))).scalar_one()
                    await run_chat_turn(db, u, BY_ID[cid]["message"],
                                        platform="ios", schedule_background=False)
                async with session() as db:
                    qs = [q for q in (await db.execute(select(PendingQuestion)
                          .where(PendingQuestion.user_id == uid))).scalars().all()
                          if not getattr(q, "answered_at", None)]
                    rec["question"] = (str(getattr(qs[0], "question", "") or "")[:260]
                                       if qs else "")
                    # ⛔⛔ THE D1 DENOMINATOR IS `food_structured_ask` ONLY.
                    # Without this the harness counted `conversation_hook` rows
                    # -- general conversational follow-ups, not food
                    # clarifications -- as zero-record food asks, inflating D1
                    # from 14 to 19. `food_clarification` (the
                    # note_food_clarification tool path) is its OWN bucket: it
                    # carries no ask_types by design, since that payload write
                    # was reverted to avoid raising the pending-mutation
                    # ratchet. Neither is an omission defect.
                    rec["q_kinds"] = [str(getattr(q, "kind", "") or "") for q in qs]
                    rec["is_d1_population"] = any(
                        k == "food_structured_ask" for k in rec["q_kinds"])
                    at = []
                    for q in qs:
                        try:
                            at += list((json.loads(q.payload_json or "{}") or {}
                                        ).get("ask_types") or [])
                        except Exception:
                            pass
                    rec["ask_types"] = at
                rec["captures"] = list(CAP)
            except Exception as e:
                rec["error"] = f"{type(e).__name__}: {e}"[:200]
            finally:
                try:
                    await _cleanup(session, uid)
                except Exception:
                    pass
            fh.write(json.dumps(rec) + "\n"); fh.flush()
            amb = [a for c in rec.get("captures", []) for a in c["ambiguities"]]
            print(f"[{n}/{REPS*len(CASES)}] c{cid} rep{rep} "
                  f"ask_types={rec.get('ask_types')} "
                  f"n_amb={[c['n_ambiguities'] for c in rec.get('captures',[])]} "
                  f"fields={[a['field'] for a in amb]}", flush=True)
    fh.close(); await engine.dispose()

asyncio.run(main())
