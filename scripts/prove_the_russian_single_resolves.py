"""⭐ THE RUSSIAN SINGLE — the case that truncated in production, re-measured.

On 2026-08-15 the first shadow canary logged, on a batch of ONE:

    WARNING event=entity_resolution_truncated foods=1
    INFO    event=entity_identity_recorded attempted=1 recorded=0 absent=1

`max_tokens` was `220 * 1` with adaptive thinking left on, so the tokens
reserved for JSON were spent on reasoning nobody reads. The food it cut was the
NON-ENGLISH one — the population this boundary exists to serve.

WHAT THIS PROVES, and neither half can be proven by a stub:

    1  a valid Russian single WRITES A DURABLE ROW
    2  the reply is READABLE — no truncation at the repaired budget
    3  reuse still refuses a false collapse (Творог 5% vs Творог 2%)
    4  an unusable reply is an ABSENCE, never a semantic negative
       — forced by clamping the budget, not by waiting for luck

⭐ 4 IS FORCED, NOT OBSERVED. Waiting for a truncation to happen again would
make the proof depend on the defect recurring. Instead the budget is clamped to
the value that failed, the failure is reproduced deliberately, and the
assertion is that it produces NOTHING rather than an `unresolved` verdict.

⚠ REAL MODEL CALLS. Evidence, not a gate. Scratch DB only.

    ARNIE_PROVE_DB=postgresql+psycopg://$(whoami)@localhost:5432/arnie_migcheck \
        ../arnie/.venv/bin/python -m scripts.prove_the_russian_single_resolves
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

RU_SINGLE = "Творог 3%"          # the exact food that truncated in production
RU_TOMATO = "Помидор"
TVOROG_5 = "Творог 5%"
TVOROG_2 = "Творог 2%"


def _load_key() -> None:
    if os.getenv("ANTHROPIC_API_KEY"):
        return
    env = pathlib.Path(__file__).resolve().parents[2] / "arnie" / ".env"
    for line in (env.read_text().splitlines() if env.exists() else ()):
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip("\"' ")
            return
    raise SystemExit("no ANTHROPIC_API_KEY, and none in ../arnie/.env")


async def prove() -> int:
    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import skills.nutrition.entity_resolver as resolver
    from db.database import make_engine
    from db.models import FoodEntityResolution
    from skills.nutrition.entity_resolver import ensure_resolved

    url = os.getenv("ARNIE_PROVE_DB")
    if not url:
        raise SystemExit("set ARNIE_PROVE_DB to a SCRATCH database")
    os.environ["ENTITY_RESOLUTION_MODE"] = "shadow"

    engine = make_engine(url)
    session = async_sessionmaker(engine, expire_on_commit=False)
    failures, notes = [], []

    try:
        async with session() as db:
            await db.execute(delete(FoodEntityResolution))
            await db.commit()

        # ── 1 & 2. the single that truncated, at the repaired budget ────────
        async with session() as db:
            resolved = await ensure_resolved(db, [RU_SINGLE])
            rows = (await db.execute(select(FoodEntityResolution))).scalars().all()
        notes.append(f"1  {RU_SINGLE!r} -> {resolved.get(RU_SINGLE)!r}")
        for row in rows:
            notes.append(f"   row: surface={row.surface_form!r} "
                         f"state={getattr(row.state, 'value', row.state)} "
                         f"entity={str(row.canonical_entity_id or '')!r}")
        if not rows:
            failures.append(
                f"⛔ {RU_SINGLE!r} STILL WRITES NO ROW — the production "
                f"truncation reproduces at the repaired budget")

        # ── 3. reuse must not collapse two curds ────────────────────────────
        async with session() as db:
            await ensure_resolved(db, [TVOROG_5])
            await ensure_resolved(db, [TVOROG_2])
            rows = (await db.execute(select(FoodEntityResolution))).scalars().all()
        by_surface = {r.surface_form: str(r.canonical_entity_id or "") for r in rows}
        five, two = by_surface.get(TVOROG_5), by_surface.get(TVOROG_2)
        notes.append(f"3  {TVOROG_5!r} -> {five!r} · {TVOROG_2!r} -> {two!r}")
        if five and two and five == two:
            failures.append(
                f"⛔ FALSE COLLAPSE: {TVOROG_5!r} and {TVOROG_2!r} share the "
                f"identity {five!r} — a permanent misprice, and the exact "
                f"failure the reuse step exists to prevent")

        # ── 4. FORCE the failure: clamp the budget to what broke ────────────
        #
        # ⭐ REPRODUCED DELIBERATELY, so the proof does not depend on the defect
        # recurring by luck. What must hold is that an unreadable reply leaves
        # NO ROW — not an `unresolved` verdict derived from a transport failure.
        async with session() as db:
            await db.execute(delete(FoodEntityResolution))
            await db.commit()
        original = resolver._MIN_TOKENS
        resolver._MIN_TOKENS = 1
        resolver._TOKENS_PER_FOOD = 1
        try:
            async with session() as db:
                starved = await ensure_resolved(db, [RU_TOMATO])
                rows = (await db.execute(
                    select(FoodEntityResolution))).scalars().all()
        finally:
            resolver._MIN_TOKENS = original
            resolver._TOKENS_PER_FOOD = 220
        notes.append(f"4  starved budget: {RU_TOMATO!r} -> {starved.get(RU_TOMATO)!r}"
                     f", rows written = {len(rows)}")
        for row in rows:
            notes.append(f"   ⛔ row: state="
                         f"{getattr(row.state, 'value', row.state)} "
                         f"entity={str(row.canonical_entity_id or '')!r}")
        if rows:
            failures.append(
                "⛔⛔ AN UNREADABLE REPLY BECAME A ROW. A transport failure has "
                "been recorded as a judgement about the food")
        if starved.get(RU_TOMATO):
            failures.append(
                f"a starved call returned an identity {starved.get(RU_TOMATO)!r} "
                f"— it cannot have read one")
    finally:
        await engine.dispose()

    print("\n  THE RUSSIAN SINGLE — real model, real rows\n")
    for note in notes:
        print(f"    {note}")
    if failures:
        print("\n  ⛔ FAILURES\n")
        for failure in failures:
            print(f"    · {failure}")
        print()
        return 1
    print("\n  -> a Russian single resolves and persists; an unreadable reply "
          "records nothing.\n")
    return 0


if __name__ == "__main__":
    _url = os.getenv("ARNIE_PROVE_DB")
    if _url:
        os.environ.setdefault("DATABASE_URL", _url)
    _load_key()
    import logging
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("skills.nutrition.entity_resolver").setLevel(logging.INFO)
    raise SystemExit(asyncio.run(prove()))
