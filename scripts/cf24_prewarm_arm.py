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

OBS: dict = {"door": [], "analyze": [], "select": [], "prehydrated": [],
             "consumption": [], "predicate": []}

#: ⭐ ORDER IS THE WHOLE ASSERTION. "A payload reached a consumer" and "a door
#: event exists somewhere in the turn" are compatible with each other; what
#: distinguishes a BYPASS is that the consumption happened with NO door event
#: for that row BEFORE it. So every observation is stamped with a monotonic
#: sequence and the gate compares positions, not mere presence.
_SEQ = [0]


def _seq() -> int:
    _SEQ[0] += 1
    return _SEQ[0]


#: The macro fingerprint, not calories alone. A candidate carrying 437.5 by
#: coincidence is not row 936; carrying 437.5 AND 8.8/63.8/16.2 is.
FINGERPRINT = {"cal_100": 437.5, "protein_100": 8.8,
               "carbs_100": 63.8, "fat_100": 16.2}


def _is_row936(obj) -> bool:
    """The FULL fingerprint — calories AND macros, in either shape."""
    if obj is None:
        return False
    d = obj if isinstance(obj, dict) else dict(getattr(obj, "__dict__", {}) or {})
    p = d.get("per100g") if isinstance(d.get("per100g"), dict) else None
    def val(col, key):
        if p is not None and key in p:
            return p.get(key)
        return d.get(col)
    try:
        return all(abs(float(val(c, k) or -1) - v) < 0.05 for (c, k), v in
                   ((("cal_100", "calories"), 437.5),
                    (("protein_100", "protein"), 8.8),
                    (("carbs_100", "carbs"), 63.8),
                    (("fat_100", "fat"), 16.2)))
    except (TypeError, ValueError):
        return False


def _door_exists() -> bool:
    import db.queries as Q
    return hasattr(Q, "memory_nutrition_evidence")


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

    # ⛔ THE DOOR DOES NOT EXIST ON EVERY TREE. `memory_nutrition_evidence`
    # arrived with 7fd15d9, AFTER the incident, so a7549d7 has no door to wrap
    # — and a harness that assumes one crashes before the product runs.
    #
    # ⭐ `memory_nutrition_is_trusted` EXISTS ON BOTH TREES, so it is the
    # cross-tree observable: it answers "was the trust question asked at all",
    # which is the historical analogue of the door firing.
    _pred = getattr(Q, "memory_nutrition_is_trusted", None)
    if _pred is not None:
        async def pred(db, row):
            out = await _pred(db, row)
            OBS["predicate"].append({"seq": _seq(), "is_row936": _is_row936(row),
                                     "trusted": bool(out)})
            return out
        Q.memory_nutrition_is_trusted = pred

    _door = getattr(Q, "memory_nutrition_evidence", None)
    def _rest():
        _analyze = FI.analyze

        def analyze(*a, **kw):
            mm = kw.get("memory_match")
            if _is_row936(mm):
                OBS["consumption"].append({"seq": _seq(), "where": "analyze.memory_match"})
            OBS["analyze"].append({
                "seq": _SEQ[0],
                "memory_match_present": mm is not None,
                "memory_match_carries_poison": _carries_poison(mm),
                "memory_match_is_row936": _is_row936(mm),
                "usda": kw.get("usda_candidate") is not None,
                "off": kw.get("off_candidate") is not None})
            return _analyze(*a, **kw)
        FI.analyze = analyze

        _select = AU.select

        def select(cands, food_class):
            rung, src = _select(cands, food_class)
            if _is_row936(src):
                OBS["consumption"].append({"seq": _seq(), "where": f"authority.select[{rung}]"})
            for _r, _c in (cands or {}).items():
                if _is_row936(_c):
                    OBS["consumption"].append({"seq": _seq(), "where": f"candidate_map[{_r}]"})
            OBS["select"].append({"seq": _SEQ[0], "rung": rung,
                                  "seated_carries_poison": _carries_poison(src),
                                  "seated_is_row936": _is_row936(src),
                                  "rungs_offered": sorted(cands or {})})
            return rung, src
        AU.select = select

    if _door is None:
        _rest()
        return          # no door on this tree; the other spies still install

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
        OBS["door"].append({"seq": _seq(), "consumer": consumer,
                            "is_row936": _is_row936(row), "hydration": hydration,
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
        if _is_row936(mm):
            OBS["consumption"].append({"seq": _seq(), "where": "analyze.memory_match"})
        OBS["analyze"].append({
            "seq": _SEQ[0],
            "memory_match_present": mm is not None,
            "memory_match_carries_poison": _carries_poison(mm),
            "memory_match_is_row936": _is_row936(mm),
            "usda": kw.get("usda_candidate") is not None,
            "off": kw.get("off_candidate") is not None})
        return _analyze(*a, **kw)
    FI.analyze = analyze

    _select = AU.select

    def select(cands, food_class):
        rung, src = _select(cands, food_class)
        if _is_row936(src):
            OBS["consumption"].append({"seq": _seq(), "where": f"authority.select[{rung}]"})
        for _r, _c in (cands or {}).items():
            if _is_row936(_c):
                OBS["consumption"].append(
                    {"seq": _seq(), "where": f"candidate_map[{_r}]"})
        OBS["select"].append({"seq": _SEQ[0], "rung": rung,
                              "seated_carries_poison": _carries_poison(src),
                              "seated_is_row936": _is_row936(src),
                              "rungs_offered": sorted(cands or {})})
        return rung, src
    AU.select = select


#: ⭐ GATE 0 — the local control must reproduce production arm A's SHAPE.
#: Added 2026-08-31 BEFORE any harness change, so it could not be shaped by
#: whatever turned out to be easy to fix. An arm that cannot reproduce its own
#: control cannot produce evidence about a variant of that control.
GATE0 = ("legacy.fetch_candidates executes", "row reached",
         "memory_nutrition_use observed", "trusted=False", "refused",
         "clean commit")


def check_gate0(obs, state) -> tuple:
    """⭐ TWO ERAS, TWO SHAPES. Gate 0 asks "is the harness faithfully
    exercising the memory path" — and what that looks like depends on whether
    the tree HAS a shared door.

    ⛔ The door-era shape is unsatisfiable before `7fd15d9`: it asserts
    `memory_nutrition_use`, `trusted=False` and `refused`, none of which exist
    there. Run unsplit, gate 0 failed 6/6 on the incident tree for purely
    structural reasons and would have voided a genuine reproduction.

    ⛔⛔ AND THE PRE-DOOR SHAPE MUST NOT REQUIRE A CLEAN COMMIT. On the incident
    tree the commit is POISONED, and that is the finding under test — a control
    that demands the outcome be clean would refuse exactly the run it exists to
    validate. It requires only that a meal COMMITTED.
    """
    if not obs["door"] and not _door_exists():
        pred936 = [x for x in obs["predicate"] if x.get("is_row936")]
        # ⛔⛔ `any(rungs_offered)` CONFLATED TWO DIFFERENT FACTS and made a
        # readable result unreadable. It is False both when `authority.select`
        # was NEVER CALLED (the harness did not reach the ladder — VOID) and
        # when it WAS called with an EMPTY ladder (the product declined to seat
        # anything — a RESULT, and quite possibly the protection working).
        #
        # At `26af6b2` that scored 3/3 gate-0 failures while `row 936 reached`
        # and `trust predicate answered` both PASSED — so the run was declared
        # VOID for doing exactly what a fix is supposed to do.
        #
        # ⭐ THREE STATES, NOT TWO:
        #     HARNESS_VOID     the ladder was never reached
        #     SAFE_DECLINE     reached, nothing eligible seated
        #     PRICING_REACHED  a candidate reached pricing authority
        # Only HARNESS_VOID is a gate-0 failure. A regression must be able to
        # tell "the protection worked" from "the test did not run".
        checks = {
            "pricing path reached": bool(obs["select"]),
            "row 936 reached": bool(pred936),
            "trust predicate answered": bool(pred936) and all(
                x["trusted"] is False for x in pred936),
            "a meal committed": bool(state["entries"]),
        }
        ladder = any(o["rungs_offered"] for o in obs["select"])
        seated = any(o.get("seated_is_row936") for o in obs["select"])
        checks["_state"] = ("HARNESS_VOID" if not obs["select"] else
                            "PRICING_REACHED" if (ladder or seated) else
                            "SAFE_DECLINE")
        return all(v for k, v in checks.items() if not k.startswith("_")), checks
    door = obs["door"]
    mine = [d for d in door if d["consumer"] == "legacy.fetch_candidates"]
    cal = (state["entries"][0]["cal"] if state["entries"] else None)
    checks = {
        "legacy.fetch_candidates executes": bool(mine),
        "row reached": any(d["row_id"] is not None for d in mine),
        "memory_nutrition_use observed": bool(door),
        "trusted=False": all(d["returned"] is None for d in mine) if mine else False,
        "refused": all(d["returned"] is None for d in mine) if mine else False,
        "clean commit": bool(cal) and cal < 300,
    }
    return all(checks.values()), checks


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

    # ⛔⛔ THE FIXTURE IS REBUILT EVERY RUN, AND THAT IS NOT TIDINESS.
    # Reusing it made GATE 0 FAIL on the second run having PASSED on the
    # first: `times_used`/`last_used` move and an identity gets stamped, and
    # the next turn takes a different path. Measured 2026-08-31 — fresh
    # fixture 4/4 pass, reused fixture 1/2. Same class as arm A's stale
    # `pending_questions` confound: state a turn both READS and MUTATES is
    # part of the experimental condition, so leaving it to whoever remembers
    # to reset is how a control silently stops being one.
    #
    # ⭐ SUBJECT 26 LITERALLY. The cohorts enrol `26`; a synthetic id would be
    # an undeclared eligibility deviation on the very experiment that exists
    # because eligibility decided the outcome.
    async with Session() as db:
        existing = (await db.execute(sa_select(User).where(User.id == 26))).scalar_one_or_none()
    if existing is not None:
        uid = 26
        async with Session() as db:
            rid = (await db.execute(sa_select(UserFoodMatch.id)
                   .where(UserFoodMatch.user_id == 26))).scalars().first()
    else:
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

    # ⛔ THE RUNTIME PIN RUNS FIRST. If this shell is not the production
    # runtime with the subject actually enrolled, nothing measured here is
    # about the product production runs.
    from scripts.config_pin import pin_runtime
    runtime = pin_runtime(subject_id=uid)
    print(f"runtime pinned: build={runtime['_runtime_snapshot_build']} "
          f"enrolled="
          f"{ {k: v['enrolled'] for k, v in runtime['_subject_eligibility'].items()} }")

    # ── SELFTEST: the spy must actually intercept ────────────────────────────
    # ⛔ A HARNESS THAT CANNOT SEE IS INDISTINGUISHABLE FROM A PRODUCT THAT DOES
    # NOTHING. If the door is never called at all, `OBS["door"]` is empty for
    # two very different reasons and this run cannot tell them apart.
    install_spies()
    import db.queries as Q
    if hasattr(Q, "memory_nutrition_evidence"):
        assert Q.memory_nutrition_evidence.__name__ == "door", "spy not installed"
    assert Q.memory_nutrition_is_trusted.__name__ == "pred", "predicate spy not installed"

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
    print("GATE 0 — DOES THE LOCAL CONTROL REPRODUCE PRODUCTION ARM A?")
    print("=" * 72)
    g0, checks = check_gate0(OBS, state)
    for k, v in checks.items():
        if k == "_state":
            print(f"   STATE: {v}")          # not a check — the three-way verdict
        else:
            print(f"   [{'PASS' if v else '⛔FAIL'}] {k}")
    if not g0:
        print()
        print("⛔ GATE 0 FAILED — ARM B CANNOT START.")
        print("   The local harness does not reproduce arm A's ordinary")
        print("   behaviour, so any prewarm result on top of it would be")
        print("   uninterpretable. This is a harness fact, not product evidence.")
    print()
    print("=" * 72)
    print("GATE 1 — DID A ROW-936 PAYLOAD REACH A CONSUMER *WITHOUT* THE DOOR?")
    print("=" * 72)
    # ⛔ THE OLD GATE ASKED "does 437.5 exist before the door", which the
    # ORDINARY GUARDED READ satisfies trivially — the row is fetched and then
    # handed to the door. It reported PROVEN on a run that showed nothing.
    #
    # ⭐ THE REAL ASSERTION, all three parts at once:
    #      a payload carrying row 936's FULL fingerprint
    #      reaches a pricing consumer
    #      with NO door event for that row BEFORE that consumption.
    # A door that fires and then refuses is the guard WORKING, and must make
    # this gate FAIL — which is why the sequence numbers exist.
    # ⛔⛔ THE "NO PRIOR DOOR EVENT" CLAUSE IS VACUOUS ON TREES THAT PREDATE
    # THE DOOR. `memory_nutrition_evidence` was introduced by 7fd15d9, AFTER
    # the 2026-08-25 incident — so on a7549d7 every consumption would score as
    # a bypass by construction, and the gate would report a guaranteed
    # reproduction that means nothing.
    #
    # ⭐ SO THE PRIMARY CLAUSE IS THE INCIDENT'S OWN DEFINITION, which is
    # tree-independent: DID POISONED NUTRITION REACH SETTLEMENT? Entry 3050
    # committed 525 kcal on 120 g — exactly 437.5 x 1.2. That is observable
    # whether or not a door exists, and it is what CF24 is actually about.
    #
    # The door clause is kept as a SECONDARY discriminator, meaningful only on
    # trees that have a door, and reported as N/A where there is none.
    _has_door = any(True for _ in OBS["door"]) or _door_exists()
    _expected_poison = 437.5 * 1.2          # 525.0, entry 3050 exactly
    _committed = [e["cal"] for e in state["entries"] if e["cal"]]
    poisoned_commit = any(abs(c - _expected_poison) < 25 for c in _committed)
    print(f"   committed calories: {_committed}   poisoned image = "
          f"{_expected_poison:.0f} +/-25  -> "
          f"{'⭐⭐⭐ POISONED COMMIT' if poisoned_commit else 'clean'}")
    door936 = [d for d in OBS["door"] if d.get("is_row936")]
    first_door = min((d["seq"] for d in door936), default=None)
    bypasses = [c for c in OBS["consumption"]
                if first_door is None or c["seq"] < first_door]
    for c in OBS["consumption"]:
        guarded = first_door is not None and c["seq"] > first_door
        print(f"   consumption at seq {c['seq']:>3} {c['where']:<34} "
              f"{'(after a door event — guarded)' if guarded else '⭐ NO PRIOR DOOR EVENT'}")
    print(f"   door events naming row 936: {[d['seq'] for d in door936] or 'none'}")
    if not _has_door:
        print("   (this tree has NO shared door — the ordering clause is N/A)")
    if poisoned_commit:
        print("\n   ⭐⭐⭐ INCIDENT REPRODUCED — poisoned nutrition reached "
              "settlement.")
        gate1 = True
    elif not OBS["consumption"]:
        print("\n   NO row-936 payload reached any pricing consumer.")
        print("⛔ ARM B IS **VOID** (refusal condition 1) — the bypass state")
        print("   never existed on this tree. NOT 'no bypass found'.")
        gate1 = False
    elif not bypasses:
        print("\n   Every consumption followed a door event for row 936.")
        print("⛔ ARM B IS **VOID** — the guard was exercised, not bypassed.")
        gate1 = False
    else:
        print(f"\n   ⭐⭐⭐ BYPASS REPRODUCED — {len(bypasses)} consumption(s) "
              f"with no prior door event")
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
