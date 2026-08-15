"""⭐ THE ONE PROOF THE UNIT GATES CANNOT GIVE — reuse, end to end, for real.

Danny, reviewing `d24868a`: *"the most consequential new behavior in this
commit — semantic reuse — is currently proven by unit/mutation gates, but not
yet by the actual producer→store flow."* He is right, and the reason is
specific: the earlier live probe called `interpret()` directly, and the reuse
step lives one level up in `ensure_resolved`. So the step ran zero times against
a real model and a real store.

⛔ WHY A STUB CANNOT SETTLE THIS. Every unit gate here dictates what the model
returns, so they prove the CONTRACT — what the producer does with each shape of
reply — and say nothing about whether a real model, shown identities it has
actually established, makes the judgement the design depends on. That judgement
is the whole feature. This session already paid for the general version of that
lesson once: fourteen gates passed over a `_get_client` that could not import,
because every one of them stubbed it.

WHAT IS PROVEN, in Danny's own order:

    1  Творог 5%          establishes ONE distinct identity
    2  Творог 5% жирности REUSES it — the same food said differently
    3  Творог 2%          does NOT reuse it — a different food
    4  a branded product  binds nothing AND never enters the distinct set

⭐ 3 IS THE ONE THAT MATTERS MOST. A reuse step that merged everything would
satisfy 2 perfectly and quietly price 2% curd from 5% forever after. Duplicate
identities are cheap; a false collapse is permanent, and it is the failure this
whole boundary exists to prevent.

⚠ THIS MAKES REAL MODEL CALLS AND WRITES REAL ROWS. It is not part of the
suite and must never be: a proof that costs money and depends on a provider is
evidence, not a gate. Point it at a scratch database.

    ARNIE_PROVE_DB=postgresql+psycopg://user@localhost:5432/arnie_migcheck \\
        python -m scripts.prove_distinct_reuse
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

#: Deliberately NOT the frozen fixtures from the suite. These are surface forms
#: a real user could type, and the pair in 1/2 differs only in wording — which
#: is exactly the distinction a typographic normalizer cannot make.
ESTABLISH = "Творог 5%"
SAME_FOOD_SAID_DIFFERENTLY = "Творог 5% жирности"
MATERIALLY_DIFFERENT = "Творог 2%"
A_PRODUCT = "Barebells Salty Peanut Protein Bar"


def _load_key() -> None:
    """The provider key from the gitignored env file — never a literal."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return
    env = pathlib.Path(__file__).resolve().parents[2] / "arnie" / ".env"
    for line in (env.read_text().splitlines() if env.exists() else ()):
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip('"\' ')
            return
    raise SystemExit("no ANTHROPIC_API_KEY, and none in ../arnie/.env")


async def prove() -> int:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from db.database import make_engine
    from db.models import FoodEntityResolution
    from skills.nutrition.entity_resolution import (ResolutionState,
                                                    distinct_entities, resolve)
    from skills.nutrition.entity_resolver import ensure_resolved

    url = os.getenv("ARNIE_PROVE_DB")
    if not url:
        raise SystemExit("set ARNIE_PROVE_DB to a SCRATCH database — this "
                         "writes rows and must not touch production")
    engine = make_engine(url)
    session = async_sessionmaker(engine, expire_on_commit=False)
    failures, notes = [], []

    async with session() as db:
        # ⚠ A CLEAN SLATE IS PART OF THE PROOF. Reuse against identities left
        # by an earlier run would prove that the store remembers, not that the
        # judgement works — and the second is the claim under test.
        await db.execute(delete(FoodEntityResolution))
        await db.commit()

        first = await ensure_resolved(db, [ESTABLISH])
        established = first.get(ESTABLISH, "")
        notes.append(f"1  {ESTABLISH!r} -> {established!r}")
        row = await resolve(db, ESTABLISH)
        if row is None or row.state is not ResolutionState.DISTINCT:
            failures.append(
                f"{ESTABLISH!r} did not come back DISTINCT "
                f"(state={getattr(row, 'state', None)}) — the premise of every "
                f"step below, so the rest of this run proves nothing")
            established = ""

        second = await ensure_resolved(db, [SAME_FOOD_SAID_DIFFERENTLY])
        reused = second.get(SAME_FOOD_SAID_DIFFERENTLY, "")
        notes.append(f"2  {SAME_FOOD_SAID_DIFFERENTLY!r} -> {reused!r}")
        if established and reused != established:
            failures.append(
                f"REUSE FAILED: {SAME_FOOD_SAID_DIFFERENTLY!r} minted "
                f"{reused!r} beside {established!r}. One food said two ways is "
                f"now two identities — the fragmentation this boundary exists "
                f"to remove, one layer down")

        third = await ensure_resolved(db, [MATERIALLY_DIFFERENT])
        separate = third.get(MATERIALLY_DIFFERENT, "")
        notes.append(f"3  {MATERIALLY_DIFFERENT!r} -> {separate!r}")
        if established and separate == established:
            failures.append(
                f"⛔ FALSE COLLAPSE: {MATERIALLY_DIFFERENT!r} reused "
                f"{established!r}. 2% curd would be priced from 5% forever "
                f"after. A duplicate identity is cheap; this is permanent")

        fourth = await ensure_resolved(db, [A_PRODUCT])
        product_row = await resolve(db, A_PRODUCT)
        known = await distinct_entities(db)
        notes.append(f"4  {A_PRODUCT!r} -> state="
                     f"{getattr(product_row, 'state', None)} bound={fourth!r}")
        if fourth:
            failures.append(f"a branded product bound a food identity: {fourth}")
        if product_row is None or product_row.state is not ResolutionState.PRODUCT:
            failures.append(
                f"{A_PRODUCT!r} was classified "
                f"{getattr(product_row, 'state', None)}, not PRODUCT")
        elif product_row.canonical_entity_id in known:
            failures.append(
                f"the product entered the DISTINCT candidate set as "
                f"{product_row.canonical_entity_id!r} — every later reuse "
                f"judgement would be offered it as a food")

        notes.append(f"   distinct identities established: {sorted(known)}")

    await engine.dispose()

    print("\n  LIVE REUSE PROOF — real model, real store\n")
    for note in notes:
        print(f"    {note}")
    if failures:
        print()
        for failure in failures:
            print(f"    ⛔ {failure}")
        return 1
    print("\n  ✅ reuse reuses · a different food stays different · a product "
          "binds nothing and is offered to nobody")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    _load_key()
    raise SystemExit(asyncio.run(prove()))
