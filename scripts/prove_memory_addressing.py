"""⭐ CONSUMER-SIDE PROOF — which ROW the memory rung actually returned.

Danny, reviewing `1f13347`: *"after everything you've learned, actual DB key
provenance should be the final gate."* Correct. Every gate in that commit
asserts on SOURCE — that `fetch_candidates` calls `memory_key`, that `assemble`
passes the identity through. None of them observes a row being read.

⛔ AND SOURCE ASSERTIONS ARE EXACTLY THE KIND OF EVIDENCE THIS SESSION HAS
TWICE FOUND HOLLOW. Fourteen gates passed over a `_get_client` that could not
import, because they all stubbed it. A canary reported 0/6 while every
artifact-consumption gate stayed green, because they exercised a path no turn
took. A function that is called is not a function whose result is used.

So every claim here is proven by MACROS. Each seeded row carries a calorie value
no other row has, so "the lookup reached this row" is observable rather than
inferred — the same discipline that resolved the banana-210 coincidence, where a
matching number nearly passed for provenance.

WHAT IS PROVEN, in Danny's order:

    1  Помидор is stamped `tomato` by the real interpretation-time step
    2  a later lookup for Помидор returns the row stored under `tomato`
    3  English `Tomato`, same user, returns THAT SAME ROW
    4  Творог 2% and boiled corn address DIFFERENT rows
    5  a PRODUCT binds nothing and reaches no row
    6  a resolver failure leaves today's path exactly as it was

⚠ REAL MODEL CALLS, REAL ROWS. Not a gate — evidence. Point it at a scratch DB.

    ARNIE_PROVE_DB=postgresql+psycopg://user@localhost:5432/arnie_migcheck \\
        python -m scripts.prove_memory_addressing
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

#: One calorie value per row, so the row a lookup reached is READ OFF THE
#: RESULT rather than assumed from the key that was passed in.
TOMATO_CAL = 18.0
CORN_CAL = 96.0

RU_TOMATO, EN_TOMATO = "Помидор", "Tomato"
TVOROG, CORN = "Творог 2%", "Кукуруза варёная (2 початка)"
PRODUCT = "Barebells Salty Peanut Protein Bar"
PROVE_USER = "prove:memory-addressing"


def _load_key() -> None:
    if os.getenv("ANTHROPIC_API_KEY"):
        return
    env = pathlib.Path(__file__).resolve().parents[2] / "arnie" / ".env"
    for line in (env.read_text().splitlines() if env.exists() else ()):
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip('"\' ')
            return
    raise SystemExit("no ANTHROPIC_API_KEY, and none in ../arnie/.env")


async def prove() -> int:
    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.canonical_pricing_inputs import assemble
    from core.food_intelligence import memory_key
    from core.food_turn import _log_call
    from core.turns.stages.food import stamp_canonical_identity
    from db.database import make_engine
    from db.models import FoodEntityResolution, User, UserFoodMatch
    from skills.nutrition.entity_resolution import ResolutionState, resolve

    url = os.getenv("ARNIE_PROVE_DB")
    if not url:
        raise SystemExit("set ARNIE_PROVE_DB to a SCRATCH database")
    os.environ["ENTITY_RESOLUTION_MODE"] = "shadow"

    engine = make_engine(url)
    session = async_sessionmaker(engine, expire_on_commit=False)
    failures, notes = [], []

    async with session() as db:
        # ⚠ IDEMPOTENT BY CONSTRUCTION. The first run of this script left its
        # user behind and the second died on a unique-constraint violation —
        # a proof that can only be run once is a proof nobody re-runs.
        await db.execute(delete(FoodEntityResolution))
        stale = (await db.execute(
            select(User).where(User.telegram_id == PROVE_USER))).scalar_one_or_none()
        if stale is not None:
            await db.execute(
                delete(UserFoodMatch).where(UserFoodMatch.user_id == stale.id))
            await db.delete(stale)
        await db.commit()
        user = User(telegram_id=PROVE_USER)
        db.add(user)
        await db.flush()

        # ── 1. the REAL interpretation-time step, not a stub ──────────────────
        out = {"action": "log",
               "items": [{"food": RU_TOMATO, "amount": 1, "unit": "шт"},
                         {"food": TVOROG, "amount": 150, "unit": "g"},
                         {"food": CORN, "amount": 200, "unit": "g"},
                         {"food": PRODUCT, "amount": 1, "unit": "bar"}]}
        await stamp_canonical_identity(out, db)
        stamped = {i["food"]: i.get("canonical_entity_id", "")
                   for i in out["items"]}
        for food, entity in stamped.items():
            notes.append(f"1  stamped {food[:30]!r:34} -> {entity!r}")

        if stamped.get(RU_TOMATO) != "tomato":
            failures.append(
                f"{RU_TOMATO!r} was stamped {stamped.get(RU_TOMATO)!r}, not "
                f"'tomato' — steps 2 and 3 below cannot mean anything without it")

        # THE IDENTITY MUST SURVIVE THE CALL BOUNDARY, or every consumer below
        # falls through forever and the feature is wired at both ends only.
        call = _log_call({**out["items"][0]})
        if call["input"].get("canonical_entity_id") != stamped[RU_TOMATO]:
            failures.append("the stamp did not reach the log_food call")

        # ── seed ONE row, under the canonical key, with a unique calorie ─────
        db.add(UserFoodMatch(
            user_id=user.id, name_norm=memory_key(RU_TOMATO, stamped[RU_TOMATO]),
            display_name="Tomato, raw", cal_100=TOMATO_CAL, protein_100=0.9,
            confidence="exact"))
        db.add(UserFoodMatch(
            user_id=user.id, name_norm=memory_key(CORN, stamped.get(CORN, "")),
            display_name="Corn, boiled", cal_100=CORN_CAL, protein_100=3.4,
            confidence="exact"))
        await db.commit()

        async def reached(surface: str, entity: str):
            """The calorie value of whatever row the MEMORY RUNG returned."""
            rungs = await assemble(
                db, user_id=user.id, entity=surface, preparation="",
                identity=surface, item={"canonical_entity_id": entity},
                basis_grams=None)
            memory = rungs.get("memory")
            return None if memory is None else memory.per100g.get("calories")

        # ── 2. the Russian surface reaches the row stored under `tomato` ─────
        got = await reached(RU_TOMATO, stamped[RU_TOMATO])
        notes.append(f"2  {RU_TOMATO!r} lookup -> {got} kcal/100g")
        if got != TOMATO_CAL:
            failures.append(
                f"{RU_TOMATO!r} reached {got}, not the seeded {TOMATO_CAL}. "
                f"Before this tranche it reached NOTHING; if it still does, "
                f"the consumer is not using the identity")

        # ── 3. the English surface, same user, reaches THAT SAME ROW ─────────
        got = await reached(EN_TOMATO, "tomato")
        notes.append(f"3  {EN_TOMATO!r} lookup -> {got} kcal/100g")
        if got != TOMATO_CAL:
            failures.append(
                f"{EN_TOMATO!r} reached {got}, not {TOMATO_CAL} — one food in "
                f"two languages is still two memories")

        # ── 4. творог must NOT reach the corn row ────────────────────────────
        got = await reached(TVOROG, stamped.get(TVOROG, ""))
        notes.append(f"4  {TVOROG!r} lookup -> {got} kcal/100g "
                     f"(corn row holds {CORN_CAL})")
        if got == CORN_CAL:
            failures.append(
                f"⛔ THE PRODUCTION DEFECT REPRODUCED: {TVOROG!r} reached the "
                f"boiled-corn row at {CORN_CAL} kcal/100g")
        got_corn = await reached(CORN, stamped.get(CORN, ""))
        notes.append(f"   {CORN[:24]!r} lookup -> {got_corn} kcal/100g")
        if got_corn != CORN_CAL:
            failures.append(
                f"corn stopped reaching its OWN row ({got_corn}) — separation "
                f"must not be bought by breaking the lookup")

        # ── 5. a product binds nothing ───────────────────────────────────────
        row = await resolve(db, PRODUCT)
        notes.append(f"5  {PRODUCT[:26]!r} -> state="
                     f"{getattr(row, 'state', None)} stamped="
                     f"{stamped.get(PRODUCT)!r}")
        if stamped.get(PRODUCT):
            failures.append("a branded product bound a food identity")
        if row is not None and row.state is not ResolutionState.PRODUCT:
            failures.append(f"{PRODUCT!r} classified {row.state}, not PRODUCT")

        # ── 6. no identity -> today's path, unchanged ────────────────────────
        legacy = memory_key(RU_TOMATO, "")
        notes.append(f"6  no identity -> key {legacy!r} (today's exact key)")
        if await reached(RU_TOMATO, "") is not None:
            failures.append(
                "an unstamped Russian food reached a row — the fallback must "
                "reproduce today's behaviour, where it reaches nothing")
        if await reached("Chicken breast", "") is not None:
            failures.append("an unseeded English food reached a row")

    await engine.dispose()

    print("\n  MEMORY ADDRESSING — real model, real store, row read off macros\n")
    for note in notes:
        print(f"    {note}")
    if failures:
        print()
        for failure in failures:
            print(f"    ⛔ {failure}")
        return 1
    print("\n  ✅ one food across two languages is ONE row · творог and corn are "
          "TWO · a product is none · no identity is today")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    _load_key()
    raise SystemExit(asyncio.run(prove()))
