"""⭐ THE ADOPTION SEAM, PROVEN THROUGH THE REAL TURN — eight preregistered turns.

The unit gates beside this prove the CONTRACT: that the recorder is invoked on
the legacy path, that it records without annotating, that no condition guards
it. Every one of them stubs the resolver, so none can show that a real turn
fills the store — and a stub is a statement about the contract, never evidence
the stubbed thing exists.

⛔ THIS IS THE HALF THAT COULD ONLY BE MEASURED, and it is the exact experiment
that found the defect: on 2026-08-15 the same foods wrote FOUR resolutions when
the producer was called directly and ZERO through `run_chat_turn`.

EIGHT TURNS, NOT A HUNDRED *(Danny, 2026-08-15)*: "do not spend 120-turn runs on
architectural reachability questions. Use 4–12 preregistered turns to prove the
seam, then spend larger corpus budget only after the seam is proven reachable."

WHAT IS PROVEN, in Danny's own order:

    1  run_chat_turn('Помидор') in shadow produces a resolution for `tomato`
    2  Творог 2% and boiled corn resolve to DIFFERENT identities
    3  a branded product resolves PRODUCT and binds no generic entity
    4  the same four turns with resolution OFF log the same foods
    5  attempts > 0 AND rows > 0, or the run is INVALID — never PASS
    6  annotation-only: no memory row is written under an IDENTITY key

⭐ 6 IS THE ONE THAT KEEPS SHADOW HONEST. `memory_key(food, entity)` is what
turns an identity into a PRICE, so if shadow ever stamped, a
`user_food_matches` row would appear under a key that is not the plain
normalized surface. Reading the KEYS is how "annotation-only" becomes
observable instead of asserted.

⚠ REAL MODEL CALLS, REAL ROWS. Evidence, not a gate. Scratch DB only.

    ARNIE_PROVE_DB=postgresql+psycopg://$(whoami)@localhost:5432/arnie_migcheck \\
        ../arnie/.venv/bin/python -m scripts.prove_the_seam_is_reachable
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

RU_TOMATO = "один Помидор"
TVOROG = "150 г Творог 2%"
CORN = "Кукуруза варёная (2 початка)"
PRODUCT = "one Barebells Salty Peanut Protein Bar"
TURNS = [RU_TOMATO, TVOROG, CORN, PRODUCT]


def _load_key() -> None:
    if os.getenv("ANTHROPIC_API_KEY"):
        return
    env = pathlib.Path(__file__).resolve().parents[2] / "arnie" / ".env"
    for line in (env.read_text().splitlines() if env.exists() else ()):
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip("\"' ")
            return
    raise SystemExit("no ANTHROPIC_API_KEY, and none in ../arnie/.env")


async def _drive(session, mode: str, run_id: str) -> dict:
    """Drive the four turns through the REAL entry point and read the DB."""
    from sqlalchemy import select

    from core.chat_service import run_chat_turn
    from core.recovery import is_recovery_text
    from db.models import (DailyLog, FoodEntry, FoodEntityResolution, User,
                           UserFoodMatch, UserPreferences)
    from db.queries import get_or_create_today_log, reload_user

    os.environ["ENTITY_RESOLUTION_MODE"] = mode

    async with session() as db:
        user = User(telegram_id=f"seam:{mode}:{run_id}", name="Seam", age=37,
                    sex="male", height_cm=178.0, current_weight_kg=86.0,
                    goal_weight_kg=80.0, primary_goal="cut",
                    training_experience="advanced", injuries="none",
                    timezone="America/New_York", onboarding_completed=True)
        db.add(user)
        db.add(UserPreferences(user=user, calorie_target=2126,
                               protein_target=190, coaching_style="direct",
                               accountability_level="high",
                               wake_time="07:00", sleep_time="23:30"))
        await db.flush()
        uid = user.id
        await get_or_create_today_log(db, uid, "America/New_York")
        await db.commit()

    recovered = 0
    for text in TURNS + ["thanks"]:
        async with session() as db:
            reloaded = await reload_user(db, uid)
            try:
                result = await run_chat_turn(db, reloaded, text, platform="ios",
                                             schedule_background=False)
                await db.commit()
                bubbles = getattr(getattr(result, "response", None),
                                  "bubbles", None) or []
                recovered += any(is_recovery_text(b) for b in bubbles)
            except Exception:                    # noqa: BLE001
                await db.rollback()
                recovered += 1

    async with session() as db:
        rows = (await db.execute(
            select(FoodEntry.parsed_food_name, FoodEntry.calories)
            .join(DailyLog, DailyLog.id == FoodEntry.daily_log_id)
            .where(DailyLog.user_id == uid).order_by(FoodEntry.id))).all()
        memory = (await db.execute(
            select(UserFoodMatch.name_norm, UserFoodMatch.display_name)
            .where(UserFoodMatch.user_id == uid))).all()
        resolutions = (await db.execute(select(FoodEntityResolution))).scalars().all()

        # ⭐ WHAT A CONSUMER WOULD ACTUALLY GET, read HERE — inside the arm,
        # before the next arm clears the store. The first version asked this
        # afterwards and got `''` for everything, which looked exactly like a
        # store that fills and cannot be read; the table had simply been
        # emptied. An observation taken outside the window it describes is not
        # an observation.
        #
        # ⭐⭐ AND THIS IS THE ASSERTION THAT MATTERS FOR "BINDS NOTHING".
        # `MAY_NAME_AN_ENTITY` deliberately lets a PRODUCT row CARRY an id for
        # the tranche that will own it, while `binds` excludes it — so reading
        # the raw column answers a different question than the one settlement
        # asks. `entity_id_for_surface` IS the question settlement asks.
        from skills.nutrition.entity_resolution import entity_id_for_surface

        consumer = {r.surface_form: await entity_id_for_surface(db, r.surface_form)
                    for r in resolutions}

    return {
        "mode": mode, "user_id": uid, "recovered_turns": recovered,
        "foods": [str(r[0] or "") for r in rows],
        "memory_keys": [(str(m[0] or ""), str(m[1] or "")) for m in memory],
        "consumer_binds": consumer,
        "resolutions": [
            {"surface": r.surface_form, "entity": str(r.canonical_entity_id or ""),
             "state": getattr(r.state, "value", str(r.state))}
            for r in resolutions],
    }


async def prove() -> int:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.food_intelligence import normalize_name
    from db.database import make_engine
    from db.models import FoodEntityResolution

    url = os.getenv("ARNIE_PROVE_DB")
    if not url:
        raise SystemExit("set ARNIE_PROVE_DB to a SCRATCH database")

    engine = make_engine(url)
    session = async_sessionmaker(engine, expire_on_commit=False)
    run_id = time.strftime("%Y%m%dT%H%M%S")
    failures, notes = [], []

    try:
        # The store is GLOBAL, so a previous run's rows would let this one reuse
        # identities it never established — and would make the `off` arm report
        # resolutions it did not write.
        async with session() as db:
            await db.execute(delete(FoodEntityResolution))
            await db.commit()

        shadow = await _drive(session, "shadow", run_id)

        async with session() as db:
            await db.execute(delete(FoodEntityResolution))
            await db.commit()

        off = await _drive(session, "off", run_id)
    finally:
        await engine.dispose()

    # ── 5. VALIDITY FIRST. Zero is INVALID, never PASS ───────────────────────
    if shadow["recovered_turns"] >= 3:
        failures.append(
            f"{shadow['recovered_turns']} of 5 shadow turns returned a recovery "
            f"bubble — the provider, not the seam, decided this run. INVALID")
    if not shadow["foods"]:
        failures.append("the shadow run logged NO food at all — INVALID, and "
                        "every check below would pass vacuously")
    if not shadow["resolutions"]:
        failures.append(
            "⛔ THE SEAM WROTE NOTHING. This is the defect of 2026-08-15 "
            "reproducing: an ordinary turn does not reach the producer. "
            "INVALID — this is never a PASS")

    by_surface = {r["surface"]: r for r in shadow["resolutions"]}
    notes.append(f"5  shadow: {len(shadow['resolutions'])} resolution(s), "
                 f"{len(shadow['foods'])} food row(s), "
                 f"{shadow['recovered_turns']} recovery turn(s)")
    for row in shadow["resolutions"]:
        notes.append(f"   {row['surface'][:34]!r:36} -> "
                     f"{row['entity'] or '—'!s:22} {row['state']}")

    # ── 1. the tomato turn produces a BINDING tomato identity ────────────────
    #
    # ⚠ MATCHED ON THE ENTITY, NOT ON THE RUSSIAN SURFACE, and the reason is a
    # finding rather than a convenience: driven as 'один Помидор' inside an
    # otherwise-English conversation, the interpreter emitted the food name
    # 'Tomato' — it TRANSLATED. Production's `parsed_food_name` stays Russian
    # (30.4% of entries are non-ASCII), so this probe's phrasing, not the
    # system, produced the English surface. What must hold either way is that
    # the turn yields a binding tomato identity.
    tomato = next((r for r in shadow["resolutions"]
                   if "tomato" in (r["entity"] or "")), None)
    notes.append(f"1  tomato identity -> {tomato and tomato['surface']!r} "
                 f"-> {tomato and tomato['entity']!r} "
                 f"(consumer binds "
                 f"{tomato and shadow['consumer_binds'].get(tomato['surface'])!r})")
    if tomato is None:
        failures.append("no resolution named a tomato at all")
    elif not shadow["consumer_binds"].get(tomato["surface"]):
        failures.append(
            f"the tomato row exists but a CONSUMER binds nothing to "
            f"{tomato['surface']!r} — the store fills and cannot be read, "
            f"which is the dead-rung shape again")
    if any("омидор" in (r["surface"] or "") for r in shadow["resolutions"]):
        notes.append("   (the Russian surface survived interpretation here)")
    else:
        notes.append("   ⚠ the interpreter TRANSLATED the surface to English — "
                     "note it, do not read it as production behaviour")

    # ── 2. творог and corn are DIFFERENT identities ──────────────────────────
    tvorog = next((r for s, r in by_surface.items() if "ворог" in s), None)
    corn = next((r for s, r in by_surface.items() if "укуруз" in s), None)
    notes.append(f"2  творог -> {tvorog and tvorog['entity']!r} · "
                 f"corn -> {corn and corn['entity']!r}")
    if tvorog and corn and tvorog["entity"] and tvorog["entity"] == corn["entity"]:
        failures.append(
            "⛔ FALSE COLLAPSE: творог and boiled corn share one identity — "
            "this is the live misprice of 2026-08-14 reproducing")

    # ── 3. the product binds nothing ─────────────────────────────────────────
    product = next((r for s, r in by_surface.items()
                    if "arebells" in s or "rotein" in s), None)
    notes.append(f"3  product -> state={product and product['state']} "
                 f"entity={product and product['entity']!r}")
    if product is not None:
        if product["state"] != "product":
            failures.append(f"the branded product resolved "
                            f"{product['state']}, not PRODUCT")
        # ⚠ BINDS, NOT CARRIES. `MAY_NAME_AN_ENTITY` lets a PRODUCT row hold an
        # id for the tranche that will own it, and `binds` excludes PRODUCT — so
        # asserting the COLUMN is empty asserts a rule the design does not have.
        # What must be true is that settlement receives nothing.
        bound = shadow["consumer_binds"].get(product["surface"], "")
        notes.append(f"   consumer binds {bound!r} for the product")
        if bound:
            failures.append(
                f"a CONSUMER binds {bound!r} to a branded product — a label is "
                f"not a food identity, and this is the PRODUCT rung acquiring a "
                f"producer by accident")

    # ── 4. off logs the same foods, and writes no resolution ─────────────────
    notes.append(f"4  off: {len(off['resolutions'])} resolution(s), "
                 f"foods={off['foods']}")
    notes.append(f"   shadow foods={shadow['foods']}")
    if off["resolutions"]:
        failures.append(f"the OFF run wrote {len(off['resolutions'])} "
                        f"resolution(s) — off must reproduce today exactly")
    if len(off["foods"]) != len(shadow["foods"]):
        failures.append(
            f"off logged {len(off['foods'])} foods and shadow logged "
            f"{len(shadow['foods'])} — shadow changed what gets logged")

    # ── 6. ANNOTATION-ONLY, read off the memory KEYS ─────────────────────────
    # `memory_key(food, entity)` is what turns an identity into a price. If
    # shadow ever stamped, a row would appear under a key that is NOT the plain
    # normalized surface — so the keys are where annotation-only is observable.
    stamped_keys = [(key, display) for key, display in shadow["memory_keys"]
                    if key and key != normalize_name(display)]
    notes.append(f"6  shadow memory keys: {len(shadow['memory_keys'])} row(s), "
                 f"{len(stamped_keys)} keyed by something other than the surface")
    for key, display in stamped_keys:
        failures.append(
            f"⛔ NOT ANNOTATION-ONLY: memory row {display!r} is keyed {key!r}, "
            f"not {normalize_name(display)!r} — an identity reached memory_key, "
            f"which means shadow changed a PRICE")

    print("\n  THE ADOPTION SEAM — eight turns through core.chat_service.run_chat_turn\n")
    for note in notes:
        print(f"    {note}")
    if failures:
        print("\n  ⛔ FAILURES\n")
        for failure in failures:
            print(f"    · {failure}")
        print()
        return 1
    print("\n  -> the ordinary turn path reaches the producer, and shadow is "
          "annotation-only.\n")
    return 0


def _make_the_producer_audible() -> None:
    """⚠ THE SEAM'S OWN TELEMETRY IS `INFO`, AND SCRIPTS RUN AT `WARNING`.

    The first run of this proof showed one resolution and NOT ONE
    `event=entity_identity_recorded` line, which read as "the seam never ran" —
    when the seam had run four times and been inaudible three of them. An
    instrument nobody can hear is the same as one that is not there, and this
    session has already spent a run on that lesson twice.
    """
    import logging

    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("core.turns.stages.food").setLevel(logging.INFO)
    logging.getLogger("core.conversation").setLevel(logging.INFO)
    logging.getLogger("skills.nutrition.entity_resolver").setLevel(logging.INFO)
    logging.getLogger("skills.nutrition.entity_resolution").setLevel(logging.INFO)


if __name__ == "__main__":
    # ⚠ BEFORE ANY APP IMPORT. The app-global engine binds at import time and
    # falls back to SQLite when DATABASE_URL is unset, so setting this inside
    # `prove()` — where the first version had it — left half the turn writing to
    # a different database, silently. That defect was found once in the corpus
    # driver and reintroduced here within the hour, which is why it is now the
    # first statement in the program rather than a line inside a function.
    _url = os.getenv("ARNIE_PROVE_DB")
    if _url:
        os.environ.setdefault("DATABASE_URL", _url)
    _load_key()
    _make_the_producer_audible()
    raise SystemExit(asyncio.run(prove()))
