"""⛔ THE RICE TRIPLE, OFFLINE: what does a repeated food message answer?

Production, user 26, 2026-08-17 02:39-02:40 UTC on `8f5501d`:

    02:39:46  7864ms  '100g of white rice'  -> logged 365 cal (#3014)
    02:40:23     6ms  '100g of white rice'  -> "Something went sideways…"
    02:40:34     7ms  '100g of white rice'  -> "Something went sideways…"

⭐ THE SAME GESTURE, DRIVEN HERE, so the answer is an object rather than a
production absence. Three sends of one message; the first must LOG and the rest
must say it is already logged — never a recovery bubble, which is the product's
word for "this failed, send it again" and instructs a retry that cannot succeed.

⭐⭐ AND IT PRINTS THE `turn_metrics` ROW EACH TURN COST. The production
duplicates recorded `total_ms=6` with `stages_json={}` — no `llm` leaf at all,
though the native lane runs the interpreter before it can reach the claim. That
is the one fact the offline drive can settle that the database could not: if the
duplicate here records an `llm` stage, production's empty one is a SECOND
question and not the same layer.

⚠ SCRATCH DB ONLY (`ARNIE_PROVE_DB`). It creates users and drives real turns
against a real model.
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ⛔ BEFORE ANY `db` IMPORT. `db.database` resolves DATABASE_URL at import time
# and builds the app-global engine from it, and `RequestTrace.persist_isolated`
# writes through THAT engine rather than through the session the turn was given.
# Without this the turns run against the scratch database while their own
# `turn_metrics` rows go to `arnie.db` — the metric the drive exists to read,
# written somewhere the drive is not looking. (The same app-global hazard
# `tests/conftest.py` names.)
if os.getenv("ARNIE_PROVE_DB"):
    os.environ["DATABASE_URL"] = os.environ["ARNIE_PROVE_DB"]

#: The message, verbatim as Danny sent it.
TEXT = "100g of white rice"

#: Sends. The first logs; every one after it is a duplicate.
SENDS = 3


def _mirror_production(uid: int) -> None:
    """The five gates, set exactly as `reproduce_the_bare_phrasing_failure`
    sets them — a repro that silently runs legacy proves nothing about the
    native lane's claim.

    ⭐ EXCEPT THE SETTLEMENT COHORT, WHICH IS A KNOB HERE, because it decides
    WHICH exactly-once mechanism the turn gets and therefore whether the
    refusal under repair is reachable at all:

        canonical settlement  `_canonical_route` returns an owner and
                              `NativeExecutionStage` takes NO legacy claim —
                              `commit_or_load_existing` is the claim, and it is
                              keyed on `source_turn_id`, so a RETYPED identical
                              message is a different turn and logs again.
        legacy branch         `_claim` -> `claim_processed_turn` on
                              (user, text, plan), which is what refuses a
                              retyped duplicate inside the 60-minute window and
                              raises `ExactlyOnceRefusal`.

    Production's rice turn took the LEGACY branch (a hashed `processed_turns`
    row with an empty `result_summary`, 2026-08-17 02:39:38 UTC), which is why
    its duplicates were refused. Set `PROVE_SETTLEMENT=1` to drive the other.
    """
    os.environ["TURN_COORDINATOR_MODE"] = "new_execute"
    os.environ["TURN_COORDINATOR_LANES"] = "structured_food"
    os.environ["TURN_COORDINATOR_ALLOWLIST"] = str(uid)
    os.environ["ENTITY_RESOLUTION_MODE"] = "consume"
    os.environ["ENTITY_RESOLUTION_CONSUME_ALLOWLIST"] = str(uid)
    if os.getenv("PROVE_SETTLEMENT") == "1":
        os.environ["GENERAL_SETTLEMENT_ALLOWLIST"] = str(uid)
    else:
        os.environ.pop("GENERAL_SETTLEMENT_ALLOWLIST", None)


async def _board(session, uid: int) -> list:
    """Every food row on today's board, so a double write is visible."""
    from sqlalchemy import select

    from db.models import DailyLog, FoodEntry
    async with session() as db:
        rows = (await db.execute(
            select(FoodEntry.id, FoodEntry.parsed_food_name, FoodEntry.calories)
            .join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
            .where(DailyLog.user_id == uid)
            .order_by(FoodEntry.id))).all()
    return [tuple(r) for r in rows]


async def _metrics(session, uid: int) -> list:
    from sqlalchemy import select

    from db.models import TurnMetric
    async with session() as db:
        rows = (await db.execute(
            select(TurnMetric.turn_id, TurnMetric.outcome, TurnMetric.total_ms,
                   TurnMetric.stages_json)
            .where(TurnMetric.user_id == uid)
            .order_by(TurnMetric.id))).all()
    return [tuple(r) for r in rows]


async def main() -> int:
    url = os.getenv("ARNIE_PROVE_DB")
    if not url:
        print("set ARNIE_PROVE_DB to a SCRATCH database url")
        return 2

    from scripts.corpus_through_the_real_turn import _fresh_user, _load_key
    _load_key()

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from db.database import make_engine
    engine = make_engine(url)
    session = async_sessionmaker(engine, expire_on_commit=False)

    from db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # ⚠ A RUN ID PER RUN, OR THE SECOND RUN DIES ON `ix_users_telegram_id`.
    # `_fresh_user` is re-runnable by CREATING, never by deleting — so the
    # handle has to differ. Pass `PROVE_RUN_ID` to re-drive.
    run_id = os.getenv("PROVE_RUN_ID") or "duptriple"
    uid = await _fresh_user(session, "rice", "consume", run_id)
    _mirror_production(uid)

    from core.chat_service import run_chat_turn
    from core.recovery import is_recovery_text
    from db.queries import reload_user

    print(f"user={uid}  gates=production-mirror  sends={SENDS}\n")

    outcomes = []
    for attempt in range(SENDS):
        async with session() as db:
            user = await reload_user(db, uid)
            try:
                result = await run_chat_turn(
                    db, user, TEXT, platform="ios", schedule_background=False,
                    client_msg_id=f"dup-{attempt}")
                await db.commit()
            except Exception:                        # noqa: BLE001
                await db.rollback()
                outcomes.append(("RAISED", traceback.format_exc()[-400:]))
                continue
        bubbles = [b for b in
                   (getattr(getattr(result, "response", None), "bubbles", None)
                    or []) if (b or "").strip()]
        if any(is_recovery_text(b) for b in bubbles):
            verdict = "RECOVERY"
        elif not bubbles:
            verdict = "EMPTY"
        else:
            verdict = "OK"
        outcomes.append((verdict, " | ".join(bubbles)[:200]))

    print("=" * 74)
    for i, (verdict, detail) in enumerate(outcomes, 1):
        print(f"send {i}: {verdict}\n    {detail}\n")

    board = await _board(session, uid)
    print("=" * 74)
    print(f"board rows: {len(board)}")
    for row in board:
        print(f"    {row}")

    print("\n=== turn_metrics ===")
    for turn_id, outcome, ms, stages in await _metrics(session, uid):
        print(f"    {str(ms):>7}ms  {outcome:<10} stages={stages}  {turn_id}")

    print("\n" + "=" * 74)
    ok = outcomes and outcomes[0][0] == "OK"
    dups = [v for v, _ in outcomes[1:]]
    said_logged = all("already logged" in d.lower() for v, d in outcomes[1:])
    if not ok:
        print("FIRST SEND DID NOT LOG — the repro is not exercising the lane.")
    elif set(dups) == {"OK"} and said_logged and len(board) == 1:
        print("FIXED — the first send logged ONE row, and every duplicate said "
              "it was already logged rather than telling the user to resend.")
    elif "RECOVERY" in dups:
        print("REPRODUCED — a duplicate is still answered with a recovery "
              "bubble, which instructs a retry that cannot succeed.")
    else:
        print(f"UNEXPECTED — duplicates={dups}, board rows={len(board)}. "
              "Read the rows above before concluding anything.")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
