"""⛔ A CONTROLLED PAIR: `150g of cucumber` failed, `I had 150g of cucumber` logged.

2026-08-16, user 26, seconds apart, same food, same account, deployed `3b03943`.
The bare noun phrase came back as "Arnie's temporarily unavailable"; the same
quantity in a sentence logged 20 kcal through legacy. Production recorded
NOTHING for the failure — no `conversation_logs` row, no `turn_metrics` row, no
`processed_turns` claim — so the cause is not recoverable from the database.

⭐ THE POINT OF DOING IT HERE: offline, the failure is an object rather than an
absence. Three outcomes are distinguishable, and production cannot tell them
apart:

    raised            an exception with a traceback, before anything was written
    recovery bubble   the turn RETURNED, carrying the canned apology
                      (`core.recovery`) — it never reached the model, and it
                      does NOT raise, so an `except` sees a clean run
    empty reply       a turn that produced no plan and no text at all

⚠ AND IT RUNS THE PAIR N TIMES. "Reproducible on phrasing" and "intermittent,
observed twice" are different defects with different fixes, and one run of each
cannot tell them apart — the same bare phrasing succeeded twice earlier in the
very transcript that reported it failing.

⚠ SCRATCH DB ONLY (`ARNIE_PROVE_DB`). It creates users and drives real turns
against a real model.
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: The controlled pair, verbatim as Danny sent them.
BARE = "150g of cucumber"
SENTENCE = "I had 150g of cucumber"

#: How many times each phrasing is driven. Determinism is the question.
REPEATS = 3


def _mirror_production(uid: int) -> None:
    """The five gates, read from `/health` on `3b03943` and set identically.

    ⛔ ALL OF THEM, OR THE REPRO IS A DIFFERENT LANE. Measured 2026-08-16:
    three of four gates left the turn on the legacy path while looking exactly
    like a working canonical turn. A repro that silently runs legacy would
    "fail to reproduce" and clear the wrong code.
    """
    os.environ["TURN_COORDINATOR_MODE"] = "new_execute"
    os.environ["TURN_COORDINATOR_LANES"] = "structured_food"
    os.environ["TURN_COORDINATOR_ALLOWLIST"] = str(uid)
    os.environ["GENERAL_SETTLEMENT_ALLOWLIST"] = str(uid)
    os.environ["ENTITY_RESOLUTION_MODE"] = "consume"
    os.environ["ENTITY_RESOLUTION_CONSUME_ALLOWLIST"] = str(uid)


async def _seed_the_ambiguous_address(session, uid: int, foil: int) -> None:
    """Two disagreeing authorities for `cucumber`, as production has.

    ⭐ FLEET-WIDE, NOT PER-USER, because `address_has_one_authority` is — and
    `user_id` is NOT NULL, so the disagreement needs a SECOND USER rather than
    an unowned row. The driving user carries production's own 179 kcal/100g
    row; the foil carries a real cucumber's ~15.

    ⭐⭐ IT IS THE DISAGREEMENT, NEVER THE IMPLAUSIBILITY. Nothing here asks
    whether 179 is a believable cucumber — that is the nutritional heuristic
    this design refused. Two authorities for one address is the whole test.
    """
    from db.models import UserFoodMatch

    async with session() as db:
        for owner, cal in ((uid, 179.0), (foil, 15.0)):
            db.add(UserFoodMatch(
                user_id=owner, name_norm="cucumber", display_name="Cucumber",
                cal_100=cal, protein_100=0.6, carbs_100=3.6, fat_100=0.1))
        await db.commit()


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

    # ⚠ SCHEMA FROM THE MODELS, WHICH PRODUCTION DOES NOT DO — it builds from
    # the migrations. Fine for a repro (no migration is under test here), and
    # named because a schema drift this cannot see has bitten before.
    from db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uid = await _fresh_user(session, "phrasing", "consume", "barefail")
    foil = await _fresh_user(session, "foil", "consume", "barefail")
    _mirror_production(uid)

    try:
        await _seed_the_ambiguous_address(session, uid, foil)
        seeded = True
    except Exception as exc:                            # noqa: BLE001
        # ⚠ NAMED, NEVER SKIPPED. A seed that silently did not apply is the
        # "fixture skipped for three runs" defect wearing a different hat.
        print(f"!! ambiguous-address seed FAILED: {exc!r}")
        print("!! the canonical decline may not reproduce — read with that in mind")
        seeded = False

    from core.chat_service import run_chat_turn
    from core.recovery import is_recovery_text
    from db.queries import reload_user

    print(f"user={uid}  gates=production-mirror  ambiguity_seeded={seeded}")
    print(f"driving each phrasing {REPEATS}x\n")

    results: dict = {BARE: [], SENTENCE: []}
    for attempt in range(REPEATS):
        for text in (BARE, SENTENCE):
            async with session() as db:
                user = await reload_user(db, uid)
                try:
                    result = await run_chat_turn(
                        db, user, text, platform="ios",
                        schedule_background=False,
                        client_msg_id=f"repro-{attempt}-{len(text)}")
                    await db.commit()
                except Exception:                       # noqa: BLE001
                    await db.rollback()
                    results[text].append(("RAISED", traceback.format_exc()))
                    continue

            response = getattr(result, "response", None)
            bubbles = list(getattr(response, "bubbles", None) or [])
            if any(is_recovery_text(b) for b in bubbles):
                results[text].append(("RECOVERY", " | ".join(bubbles)[:160]))
            elif not any((b or "").strip() for b in bubbles):
                results[text].append(("EMPTY", repr(bubbles)[:160]))
            else:
                results[text].append(("OK", " | ".join(bubbles)[:160]))

    print("=" * 74)
    for text, outcomes in results.items():
        verdicts = [v for v, _ in outcomes]
        print(f"\n{text!r}")
        print(f"  outcomes: {verdicts}")
        for verdict, detail in outcomes:
            if verdict != "OK":
                print(f"  --- {verdict} ---\n{detail}")
            else:
                print(f"  OK: {detail}")

    bare = [v for v, _ in results[BARE]]
    sentence = [v for v, _ in results[SENTENCE]]
    print("\n" + "=" * 74)
    if set(bare) == {"OK"} and set(sentence) == {"OK"}:
        print("NOT REPRODUCED — both phrasings succeeded every time. The cause "
              "is environmental (production config, data, or provider), not "
              "the input shape.")
    elif set(bare) != {"OK"} and set(sentence) == {"OK"}:
        print("REPRODUCED AND PHRASING-DETERMINISTIC — the bare noun phrase is "
              "the trigger.")
    else:
        print("INTERMITTENT — the outcome varies WITHIN a phrasing, so wording "
              "is not the whole cause. Do not fix a parser on this evidence.")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
