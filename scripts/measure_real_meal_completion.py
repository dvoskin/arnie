"""FULL-TURN COMPLETION — the authoritative product metric.

Danny's definition, signed off 2026-08-26:

    A meal is COMPLETE when the user's turn reaches a correct durable product
    outcome: correct log, correct clarification, or correct refusal, with no
    wrong committed nutrition, missing material component, duplicate mutation,
    or ownership violation.

⛔⛔⛔ SCORED ON THE DURABLE OUTCOME, NEVER ON REPLY TEXT OR TOOL CALLS. The
pass-1 gate counts `log_food` calls; a call is an intention, not an outcome.
This drives `core.chat_service.run_chat_turn` — the same function the iOS API
and the Telegram handler call — and then reads the DATABASE. A turn that
called `log_food` and committed nothing is NO_ACTION here, and rightly.

⛔⛔ EXACTLY ONE TERMINAL OUTCOME PER CASE, from a closed vocabulary. A case
that could be counted twice is a case whose rate means nothing.

⚠ NAMESPACED TEST IDENTITY. Twenty-five meals is a lot of food; this never
runs as a real user. The identity is obvious and per-run.

⭐ `may_ask` IS A PRODUCT JUDGEMENT, DECLARED PER CASE AND VISIBLE. A turn
that asks about a genuinely underspecified meal is progressing; one that asks
about an ordinary specified meal is interrogating. Encoding that as data —
rather than inferring it — is what lets `ASK_CORRECT` and
`WRONG_CLARIFICATION` be different outcomes instead of one fuzzy bucket.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

EXPECTATIONS = pathlib.Path(__file__).resolve().parent.parent / (
    "data/corpus/real_meal_expectations_v1.json")

OUTCOMES = ("LOG_COMPLETE", "ASK_CORRECT", "REFUSE_CORRECT", "NO_ACTION",
            "WRONG_COMPONENTS", "WRONG_NUTRITION", "WRONG_IDENTITY",
            "WRONG_CLARIFICATION", "WRONG_REFUSAL", "DUPLICATE_MUTATION",
            "OWNERSHIP_FAILURE")
#: Which outcomes count as the meal having COMPLETED.
COMPLETE = frozenset({"LOG_COMPLETE", "ASK_CORRECT", "REFUSE_CORRECT"})


async def _score_one(session, user_id, case, run_id):
    """Drive one turn, then read the database. Returns `(outcome, detail)`.

    ⛔ ONE SESSION PER TURN, AND THE USER IS RE-LOADED INSIDE IT. Sharing a
    session between `run_chat_turn` and the scorer's own reads raised
    `MissingGreenlet`: `build_context` reads `user.preferences` outside the try
    that guards the clarification fetch, so a lazy relationship load there
    kills the turn. The turn owns its session; scoring reads open their own.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from core.chat_service import run_chat_turn
    from db.models import (DailyLog, FoodEntry, LedgerEvent, PendingOperation,
                           PendingQuestion, User)

    cid = case["id"]
    msg = case["message"]
    imin, imax = case["expected_component_range"]
    cal_lo, cal_hi = case["expected_calorie_range"]
    expected = case["expected_terminal"]
    want_field = case.get("expected_clarification_field")

    async with session() as db:
        before = set((await db.execute(
            select(FoodEntry.id)
            .join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
            .where(DailyLog.user_id == user_id))).scalars().all())

    async with session() as db:
        user = (await db.execute(
            select(User).options(selectinload(User.preferences))
            .where(User.id == user_id))).scalar_one()
        await run_chat_turn(db, user, msg, platform="ios",
                            schedule_background=False,
                            idempotency_key=f"rmc:{run_id}:{cid}")

    async with session() as db:
        rows = list((await db.execute(
            select(FoodEntry).join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
            .where(DailyLog.user_id == user_id))).scalars().all())
        fresh = [r for r in rows if r.id not in before]

        # ── nothing durable committed ────────────────────────────────────
        if not fresh:
            asked = [q for q in (await db.execute(select(PendingQuestion).where(
                PendingQuestion.user_id == user_id))).scalars().all()
                if not getattr(q, "answered_at", None)]
            # ⭐⭐⭐ THE ASK RULE. A question is only progress if the turn left
            # DURABLE STATE THAT CAN BE ANSWERED. A nice-sounding question
            # with nothing to resume is not a clarification, it is a dead end
            # wearing one — and scoring it as success would let the lane game
            # the metric by asking about everything.
            resumable = [o for o in (await db.execute(
                select(PendingOperation).where(
                    PendingOperation.user_id == user_id)))
                .scalars().all()
                if str(getattr(o, "status", "")).lower() not in
                ("committed", "terminal", "expired", "cancelled")]
            if not asked and not resumable:
                return "NO_ACTION", "no committed row, no question, no operation"
            if not resumable:
                return ("WRONG_CLARIFICATION",
                        f"asked with NO resumable operation: "
                        f"{str(getattr(asked[-1], 'question', ''))[:52]!r}")
            if expected != "ASK_CORRECT":
                return ("WRONG_CLARIFICATION",
                        f"asked, but this meal should {expected}: "
                        f"{str(getattr(asked[-1] if asked else resumable[-1], 'question', ''))[:44]!r}")
            unresolved = str(getattr(resumable[-1], "unresolved_fields", "") or "")
            if want_field and want_field not in unresolved:
                return ("WRONG_CLARIFICATION",
                        f"asked about {unresolved[:40]!r}, expected "
                        f"{want_field!r}")
            return ("ASK_CORRECT",
                    f"resumable operation, unresolved={unresolved[:44]!r}")

    # ── something committed ──────────────────────────────────────────────
        n = len(fresh)
        cal = sum(float(r.calories or 0) for r in fresh)
        names = [(r.parsed_food_name or "").strip().lower() for r in fresh]

        dupes = {x for x in names if names.count(x) > 1}
        if dupes:
            return "DUPLICATE_MUTATION", f"same component twice: {sorted(dupes)}"

        created = (await db.execute(select(LedgerEvent).where(
            LedgerEvent.entry_id.in_([r.id for r in fresh]),
            LedgerEvent.event_type == "created"))).scalars().all()
        sources = {str(e.source or "") for e in created}
        canonical = {x for x in sources if x.startswith("canonical")}
        legacy = sources - canonical
        if canonical and legacy:
            return ("OWNERSHIP_FAILURE",
                    f"one meal, two owners: {sorted(canonical)} + {sorted(legacy)}")

        if expected == "ASK_CORRECT":
            return ("WRONG_CLARIFICATION",
                    f"logged {n} components where a {want_field or 'clarification'} "
                    f"question was expected")

        if n < imin or n > imax:
            return ("WRONG_COMPONENTS",
                    f"{n} components (expected {imin}-{imax}): {names}")
        if not (cal_lo <= cal <= cal_hi):
            return ("WRONG_NUTRITION",
                    f"{cal:.0f} kcal committed, expected {cal_lo}-{cal_hi}")
        return "LOG_COMPLETE", f"{n} components, {cal:.0f} kcal"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keep", action="store_true",
                    help="do not delete this run's synthetic identity")
    args = ap.parse_args()

    import json
    spec = json.loads(EXPECTATIONS.read_text())
    frozen = bool(spec.get("frozen"))
    cases = spec["cases"][:args.limit] if args.limit else spec["cases"]

    for line in pathlib.Path(
            "/Users/danielvoskin/Code Learn/arnie/.env").read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
    os.environ["PROACTIVE_MESSAGING_ENABLED"] = "false"

    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from db.database import make_engine
    from db.models import (DailyLog, FoodEntry, LedgerEvent, PendingOperation,
                           PendingQuestion, User, UserPreferences)
    from db.queries import get_or_create_today_log

    # ⛔⛔ NEVER THE APP-GLOBAL `AsyncSessionLocal` — a standing rule here, and
    # it bites exactly this script: the global is bound to an engine this
    # process never initialised.
    url = (os.getenv("ARNIE_DATABASE_URL") or os.getenv("DATABASE_URL") or "")
    if not url:
        raise SystemExit("set ARNIE_DATABASE_URL")
    engine = make_engine(url.replace("postgresql://", "postgresql+psycopg://"))
    session = async_sessionmaker(engine, expire_on_commit=False)

    run_id = uuid.uuid4().hex[:8]
    handle = f"rmc:{run_id}"
    print(f"\n  corpus={spec['name']}  frozen={frozen}  cases={len(cases)}"
          f"  identity={handle}\n")

    results: dict = {}
    try:
        async with session() as db:
            user = User(telegram_id=handle, name="RealMeal", age=37, sex="male",
                        height_cm=178.0, current_weight_kg=86.0,
                        timezone="America/New_York", onboarding_completed=True)
            db.add(user)
            db.add(UserPreferences(user=user, calorie_target=2600,
                                   protein_target=190,
                                   proactive_messaging_enabled=False))
            await db.flush()
            await get_or_create_today_log(db, user.id, "America/New_York")
            await db.commit()
            user_id = user.id

        for case in cases:
            cid = case["id"]
            try:
                outcome, detail = await _score_one(session, user_id, case, run_id)
            except Exception as e:                          # noqa: BLE001
                outcome, detail = "ERROR", f"{type(e).__name__}: {e}"
            assert outcome in OUTCOMES or outcome == "ERROR", outcome
            forbidden = case.get("forbidden_outcomes") or []
            flag = "  ⛔FORBIDDEN" if outcome in forbidden else ""
            results[cid] = (outcome, detail, outcome in forbidden)
            print(f"  [{cid:>2}] {outcome:<20} {detail[:70]}{flag}")
    finally:
        # ⭐ CLEAN ONLY THIS IDENTITY. Twenty-five meals of synthetic food must
        # not accumulate, and must never touch another user's rows.
        if not args.keep:
            async with session() as db:
                logs = (await db.execute(select(DailyLog.id).where(
                    DailyLog.user_id == user_id))).scalars().all()
                if logs:
                    ids = (await db.execute(select(FoodEntry.id).where(
                        FoodEntry.daily_log_id.in_(logs)))).scalars().all()
                    if ids:
                        await db.execute(delete(LedgerEvent).where(
                            LedgerEvent.entry_id.in_(ids)))
                        await db.execute(delete(FoodEntry).where(
                            FoodEntry.id.in_(ids)))
                # ⛔ DISCOVER THE USER-LINKED TABLES, NEVER HAND-LIST THEM.
                # A hand-written list missed `achievements` and the delete
                # died on its foreign key — and the next table added would
                # break it again silently. Reverse dependency order so
                # children go before parents.
                from db.models import Base
                for table in reversed(Base.metadata.sorted_tables):
                    if table.name == "users":
                        continue
                    col = table.c.get("user_id")
                    if col is not None:
                        await db.execute(table.delete().where(col == user_id))
                await db.execute(delete(User).where(User.id == user_id))
                await db.commit()
            print(f"\n  cleaned identity {handle}")
        await engine.dispose()

    # ⛔⛔ NO RATE OVER A PARTIAL SET.
    assert len(results) == len(cases), (
        f"{len(results)} of {len(cases)} scored — refusing to publish a rate")

    tally: dict = {}
    for outcome, _, _ in results.values():
        tally[outcome] = tally.get(outcome, 0) + 1
    n = len(cases)
    complete = sum(v for k, v in tally.items() if k in COMPLETE)
    violations = [c for c, (_, _, bad) in results.items() if bad]

    print("\n  ==== TERMINAL OUTCOMES ====")
    for k in sorted(tally):
        print(f"    {k:<22} {tally[k]}")
    print(f"\n  scored                    {len(results)}/{n}")
    if violations:
        print(f"  ⛔ FORBIDDEN OUTCOMES      cases {violations}")
    print(f"  FULL-TURN COMPLETION      {complete}/{n} = {100*complete/n:.0f}%")
    print(f"    LOG_COMPLETE alone      {tally.get('LOG_COMPLETE', 0)}/{n}")
    print(f"    ASK_CORRECT             {tally.get('ASK_CORRECT', 0)}/{n}"
          f"   (durable resumable operation required)")

    if not frozen:
        print("\n  ⛔⛔⛔ UNPUBLISHED — THIS NUMBER IS NOT AUTHORITATIVE.")
        print(f"      {EXPECTATIONS.name} has frozen=false. The labels were "
              f"DRAFTED\n      from corpus intent and not yet reviewed. "
              f"Review the cases carrying a\n      label_note, set "
              f"frozen=true with frozen_at, then re-run.\n")
    else:
        print(f"\n  ⭐ AUTHORITATIVE — labels frozen at "
              f"{spec.get('frozen_at')}\n")
    return 0 if "ERROR" not in tally else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
