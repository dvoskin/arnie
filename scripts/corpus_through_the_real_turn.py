"""⭐ STEP 3-4 OF THE §0 PROGRAM — the preregistered corpus, through the REAL turn.

Directive §0 froze the rule that no phase may block on organic traffic VOLUME
when the evidence can be reproduced from historical traffic or a preregistered
corpus. This is the instrument that makes that rule cash out: it drives
`data/corpus/production_like_v1.json` through `core.chat_service.run_chat_turn`
— the same function the iOS API and the Telegram handler call — and reports
which rung real-shaped food actually reaches.

⛔ NOT A HARNESS THAT RESEMBLES A TURN. `prove_memory_addressing` calls
`stamp_canonical_identity` and `assemble` directly, one level BELOW the turn,
which is why it can prove the rung addresses a row and still say nothing about
whether an ordinary turn reaches it. This script enters at `run_chat_turn` and
observes only the DATABASE afterwards. Nothing is read from reply text.

⛔⛔ THE TRAP THIS INSTRUMENT IS BUILT AROUND — IT WOULD OTHERWISE MEASURE ITS
OWN SIDE EFFECT. The legacy path CACHES a seated candidate into
`user_food_matches` during the turn. So asking `_memory()` after the turn
returns evidence for almost every entry, and the instrument would report ~100%
MEMORY — a number produced entirely by the measurement being taken too late.
The settle read happens BEFORE the cache write, so this script snapshots the
addressable memory keys BEFORE each turn and counts MEMORY only when the rung
returns evidence AND the key existed beforehand. Evidence under a key the turn
itself created is reported separately as `cached_by_this_turn`, which is a
different fact and is the mechanism by which the NEXT log reaches MEMORY.

⭐ THE BUCKET IS NEVER READ FROM THE CORPUS. `declared` is a PREDICTION. The
realized bucket comes from `scripts.measure_identity_coverage.classify` applied
to the name the interpreter ACTUALLY produced — production's `_looks_branded`
and production's non-ASCII test. A disagreement is REPORTED as a divergence,
never resolved in favour of either side.

⭐⭐ MEMORY COVERAGE IS EARNED BY REPETITION, NEVER BY SEEDING. Not one row is
inserted by hand. If the covered fraction fails to appear, that is a finding
about the retrieval-and-cache loop, not a corpus defect to be patched with an
INSERT.

⚠ REAL MODEL CALLS, REAL RETRIEVAL, REAL ROWS. This is EVIDENCE, not a gate,
and it must never join the suite. Point it at a SCRATCH database.

    ARNIE_CORPUS_DB=postgresql+psycopg://$(whoami)@localhost:5432/arnie_migcheck \\
        ../arnie/.venv/bin/python -m scripts.corpus_through_the_real_turn --mode off

    # the comparison the whole step exists for
    ... --mode off --write && ... --mode shadow --write && ... --compare
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import pathlib
import statistics
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

CORPUS_PATH = (pathlib.Path(__file__).resolve().parents[1]
               / "data" / "corpus" / "production_like_v1.json")
RECORD_DIR = pathlib.Path(__file__).resolve().parents[1] / "data" / "corpus"

#: Every bucket must land within this many POINTS of the production weight for
#: the corpus to be called production-like. Chosen before the first run: the
#: rolling-window wobble between the 691-entry and 687-entry production
#: measurements was itself about half a point, so anything tighter would be
#: claiming precision the baseline does not have.
MIX_TOLERANCE_PTS = 3.0


def _load_key() -> None:
    """The API key from the environment, or from the gitignored ../arnie/.env.

    NEVER a literal in this file — same rule as every other script here, and
    the credential ratchet enforces it.
    """
    if os.getenv("ANTHROPIC_API_KEY"):
        return
    env = pathlib.Path(__file__).resolve().parents[2] / "arnie" / ".env"
    for line in (env.read_text().splitlines() if env.exists() else ()):
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip("\"' ")
            return
    raise SystemExit("no ANTHROPIC_API_KEY, and none in ../arnie/.env")


async def _fresh_user(session, handle: str, mode: str, run_id: str):
    """One synthetic user, created through the models the app uses.

    ⭐ RE-RUNNABLE BY CREATING, NEVER BY DELETING. The first version of this
    function deleted the previous run's user and died on
    `achievements_user_id_fkey` — a turn writes to more tables than the food
    lane's own, so hand-rolled teardown is a growing list of foreign keys that
    is wrong again the next time a turn learns to write somewhere new. The
    handle carries a RUN ID instead, so every run gets users nobody has touched
    and nothing needs deleting.

    ⚠ THE MODE IS IN THE HANDLE TOO, and that is not cosmetic: an `off` run and
    a `shadow` run sharing a user would let the first run's cached memory rows
    decide the second run's rung mix, which is the one comparison this whole
    instrument exists to make.

    ⚠ SCRATCH DBs ACCUMULATE USERS. That is the intended trade — a stale row in
    a scratch database costs nothing, and per-user memory means an old user
    cannot contaminate a new one.
    """
    from db.models import User, UserPreferences
    from db.queries import get_or_create_today_log

    telegram_id = f"corpus:{mode}:{run_id}:{handle}"
    async with session() as db:
        user = User(
            telegram_id=telegram_id, name="Corpus", age=37, sex="male",
            height_cm=178.0, current_weight_kg=86.0, goal_weight_kg=80.0,
            primary_goal="cut", training_experience="advanced", injuries="none",
            timezone="America/New_York", onboarding_completed=True)
        db.add(user)
        db.add(UserPreferences(user=user, calorie_target=2126, protein_target=190,
                               coaching_style="direct", accountability_level="high",
                               wake_time="07:00", sleep_time="23:30"))
        await db.flush()
        uid = user.id
        await get_or_create_today_log(db, uid, "America/New_York")
        await db.commit()
    return uid


async def _roll_the_day(session, user_id: int, days_back: int) -> None:
    """Move this user's finished day into the past, so the next turn opens a new one.

    ⛔⛔ WITHOUT THIS THE CORPUS CANNOT REACH PRODUCTION'S MEMORY RATE, AND THE
    FIRST FULL RUN PROVED IT: 100 turns wrote 45 rows, and 39 of the 44
    memory-declared entries never produced one. Every missing row was a REPEAT.
    Nothing was mis-parsed — `rows_the_corpus_did_not_predict` was empty — the
    rows simply do not exist.

    ⭐ AND THE DEDUP GUARD IS RIGHT. Production's 43.7% is earned ACROSS THIRTY
    DAYS: a user logs their staple again TOMORROW. The guard is scoped to
    TODAY's log, and it exists precisely to stop the shape a compressed corpus
    creates — the same food, the same user, minutes apart. So the corpus was
    wrong on an axis no amount of rephrasing fixes. A one-day corpus cannot
    reproduce a thirty-day memory rate, by construction.

    ⭐⭐ THE MECHANISM IS THE DAY, NOT THE CLOCK. `core.clock` is process-wide
    and the one-clock migration exists to stop code inventing its own time, so
    moving it here would be the exact habit that document forbids. Instead the
    COMPLETED day is re-dated into the past. What that changes is precisely what
    a real next day changes:

        dedup snapshot   scoped to today's log   -> resets, as it would tomorrow
        user_food_matches   NOT day-scoped       -> persists, as it does tomorrow

    ⚠ AND IT IS STATED AS A LIMIT, NOT HIDDEN. Days are SIMULATED by re-dating a
    finished day, not by waiting. What that faithfully models is dedup scope and
    memory persistence. What it does NOT model is anything keyed to real elapsed
    time — a staleness window, a streak, a rollover job.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from db.models import DailyLog

    async with session() as db:
        log = (await db.execute(
            select(DailyLog).where(DailyLog.user_id == user_id)
            .order_by(DailyLog.date.desc()).limit(1))).scalar_one_or_none()
        if log is None:
            return
        log.date = log.date - timedelta(days=days_back)
        await db.commit()


def _is_recovery(result) -> bool:
    """Did this turn come back as the canned apology rather than as a turn?

    ⭐ ASKED OF THE REPLY, USING THE APP'S OWN PREDICATE. `core.recovery`
    derives the signatures from the bubble pool itself, so a reworded bubble
    cannot silently stop being recognised here — the same reason
    `chat_service` refuses to keep a transcribed copy of that list.
    """
    from core.recovery import is_recovery_text

    response = getattr(result, "response", None)
    bubbles = getattr(response, "bubbles", None) or []
    return any(is_recovery_text(bubble) for bubble in bubbles)


async def _addressable_memory_keys(db, user_id: int) -> set:
    """The keys this user can reach RIGHT NOW — the pre-turn snapshot.

    `cal_100 IS NOT NULL` is not a stylistic filter: `_memory()` discards a row
    without it, so a row lacking it is not reachable and must not count as one.
    """
    from sqlalchemy import select

    from db.models import UserFoodMatch
    rows = (await db.execute(
        select(UserFoodMatch.name_norm).where(
            UserFoodMatch.user_id == user_id,
            UserFoodMatch.cal_100.isnot(None)))).scalars().all()
    return set(rows)


async def _entries_after(db, user_id: int, after_id: int):
    """The food rows THIS turn wrote, identified by id watermark."""
    from sqlalchemy import select

    from db.models import DailyLog, FoodEntry
    return (await db.execute(
        select(FoodEntry)
        .join(DailyLog, DailyLog.id == FoodEntry.daily_log_id)
        .where(DailyLog.user_id == user_id, FoodEntry.id > after_id)
        .order_by(FoodEntry.id))).scalars().all()


async def _max_entry_id(db, user_id: int) -> int:
    from sqlalchemy import func, select

    from db.models import DailyLog, FoodEntry
    got = (await db.execute(
        select(func.coalesce(func.max(FoodEntry.id), 0))
        .select_from(FoodEntry)
        .join(DailyLog, DailyLog.id == FoodEntry.daily_log_id)
        .where(DailyLog.user_id == user_id))).scalar()
    return int(got or 0)


async def _identity_for(db, name: str) -> str:
    """The identity a CONSUMER would address this surface form by.

    ⚠ NOT READ OFF THE FOOD ROW — `food_entries` HAS NO IDENTITY COLUMN. The
    stamp rides the tool-call input and is never persisted on the entry, so the
    only honest way to ask "what would settlement have addressed this by" after
    the fact is to make the call settlement makes: `entity_id_for_surface`.

    ⭐ AND ITS EMPTY STRING IS THE CONTRACT, NOT A MISS. No row, a stale
    contract and an UNRESOLVED judgement all arrive as `""`, which means "keep
    today's behaviour" — so passing it straight through reproduces off-mode
    exactly, which is what makes the two runs comparable.
    """
    from skills.nutrition.entity_resolution import entity_id_for_surface

    try:
        return await entity_id_for_surface(db, name)
    except Exception:                    # noqa: BLE001
        return ""


async def _rung_for(db, user_id: int, name: str, entity_id: str,
                    pre_keys: set) -> str:
    """Which rung this entry reached, EXECUTED — with the temporal guard.

    ⭐ THE LADDER'S OWN ORDER, because that is what `price()` does: memory
    first, artifact second. Asking the artifact in isolation is the mistake
    that once made "28 priceable" read as the artifact's contribution when a
    higher rung already owned 15 of them.

    ⛔ AND THE GUARD IS THE WHOLE POINT. `_memory()` is executed — no
    reimplementation of the predicate — but its answer only counts as MEMORY
    when the key was addressable BEFORE this turn ran. Otherwise the number
    being reported is the turn's own cache write coming back around.
    """
    from core.canonical_pricing_inputs import _memory
    from core.food_intelligence import memory_key
    from skills.nutrition.pricing_artifact import evidence_for, split_identity

    key = memory_key(name, entity_id)
    evidence = await _memory(db, user_id, name, entity_id)
    if evidence is not None:
        return "MEMORY" if key in pre_keys else "CACHED_BY_THIS_TURN"
    entity, preparation = split_identity(name)
    if evidence_for(entity, preparation) is not None:
        return "ARTIFACT"
    return "ESTIMATE_OR_REFUSE"


async def run_body(*, mode: str, limit: int, url: str) -> dict:
    """Drive the corpus body through the real turn path and observe the DB."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.chat_service import run_chat_turn
    from db.database import make_engine
    from db.queries import reload_user
    from scripts.measure_identity_coverage import classify

    corpus = json.loads(CORPUS_PATH.read_text())
    body = corpus["body"][:limit] if limit else corpus["body"]

    os.environ["ENTITY_RESOLUTION_MODE"] = mode
    engine = make_engine(url)
    session = async_sessionmaker(engine, expire_on_commit=False)

    # ⛔ THE RESOLUTION STORE IS GLOBAL, NOT PER-USER, so a fresh user does not
    # give a fresh experiment. Rows left by an earlier run (or by
    # `prove_distinct_reuse`) would let this run REUSE identities it never
    # established, and an `off` run would report resolutions it did not write.
    # Cleared here, and it is the reason this must point at a scratch DB.
    async with session() as db:
        from sqlalchemy import delete

        from db.models import FoodEntityResolution
        await db.execute(delete(FoodEntityResolution))
        await db.commit()

    run_id = time.strftime("%Y%m%dT%H%M%S")
    users: dict = {}
    for handle in dict.fromkeys(e["user"] for e in body):
        users[handle] = await _fresh_user(session, handle, mode, run_id)

    # ⭐ THE DAY IS DERIVED, NOT DECLARED: an item's day is how many times that
    # user has already logged that food. Establishers land on day 0, first
    # repeats on day 1, and so on — which is the shape production has, where a
    # staple recurs across days rather than within one.
    occurrences: collections.Counter = collections.Counter()
    for item in body:
        signature = (item["user"], item["food"])
        item["_day"] = occurrences[signature]
        occurrences[signature] += 1
    total_days = max((i["_day"] for i in body), default=0) + 1

    entries_seen, latencies, failures, recovered = [], [], [], []
    try:
        for day in range(total_days):
            todays_items = [(i, item) for i, item in enumerate(body)
                            if item["_day"] == day]
            for index, item in todays_items:
                uid = users[item["user"]]
                async with session() as db:
                    pre_keys = await _addressable_memory_keys(db, uid)
                    watermark = await _max_entry_id(db, uid)

                async with session() as db:
                    user = await reload_user(db, uid)
                    started = time.monotonic()
                    try:
                        result = await run_chat_turn(db, user, item["text"],
                                                     platform="ios",
                                                     schedule_background=False)
                        await db.commit()
                        error = None
                        # ⛔⛔ A TURN THAT NEVER REACHED THE MODEL DOES NOT RAISE.
                        # It returns a recovery bubble, so `except` sees nothing and
                        # the run reports "0 turn failures" over an empty mix — a
                        # provider outage wearing the shape of a coverage finding.
                        # This is how the run knows the difference between "no
                        # coverage" and "no run", and it cost a 16-turn run to learn:
                        # the API key's credit balance was exhausted and every
                        # number came back a clean, confident zero.
                        if _is_recovery(result):
                            recovered.append({"index": index, "text": item["text"]})
                    except Exception as exc:          # noqa: BLE001 — recorded, not swallowed
                        await db.rollback()
                        error = repr(exc)[:200]
                    elapsed_ms = (time.monotonic() - started) * 1000
                latencies.append(elapsed_ms)
                if error:
                    failures.append({"index": index, "text": item["text"],
                                     "error": error})

                # ⛔⛔ ROWS ARE NOT ATTRIBUTED TO THE TURN THAT WAS RUNNING WHEN THEY
                # APPEARED. Measured on the first 14 turns: turn 0 ('200g chicken
                # breast') produced no row of its own, and turn 1 ('a cup of white
                # rice') produced TWO — 'Chicken breast' 200 g and 'White rice' 1
                # cup. Held food rides `deferred_calls` and commits on the FOLLOWING
                # turn, so a watermark taken around a single turn mis-attributes it,
                # and an instrument that drove one turn per user would never see the
                # row at all.
                #
                # ⭐ WHAT IS TIME-SENSITIVE IS THE RUNG, NOT THE LABEL. `pre_keys`
                # must be the snapshot from the turn the row actually landed in, or
                # the memory guard is meaningless — so the rung is computed HERE,
                # now, and only the corpus label is deferred to the reconciliation
                # pass below.
                async with session() as db:
                    rows = await _entries_after(db, uid, watermark)
                    for row in rows:
                        name = str(row.parsed_food_name or "")
                        entity_id = await _identity_for(db, name)
                        rung = await _rung_for(db, uid, name, entity_id, pre_keys)
                        entries_seen.append({
                            "landed_on_turn": index, "user": item["user"],
                            "parsed_food_name": name,
                            "canonical_entity_id": entity_id, "rung": rung,
                            # The bucket is only meaningful for an entry that
                            # reached no evidence — exactly as the production
                            # instrument counts it.
                            "bucket": (classify(name)
                                       if rung == "ESTIMATE_OR_REFUSE" else None),
                            "calories": row.calories, "quantity": row.quantity,
                            "latency_ms": round(elapsed_ms)})

            # ⛔ THE LAST TURN'S FOOD IS STILL HELD WHEN THE CORPUS ENDS. Held food
            # rides `deferred_calls` and commits on the FOLLOWING turn, so without
            # this every user's final entry would be missing and would be reported
            # as a coverage gap. One neutral turn per user flushes it — the same way
            # production flushes it, by there being a next turn.
            #
            # ⚠ IT IS NEUTRAL ON PURPOSE: it must commit what is held and log
            # nothing of its own, so any row it produces shows up in
            # `rows_the_corpus_did_not_predict` rather than quietly joining the mix.
            for handle, uid in users.items():
                async with session() as db:
                    pre_keys = await _addressable_memory_keys(db, uid)
                    watermark = await _max_entry_id(db, uid)
                async with session() as db:
                    user = await reload_user(db, uid)
                    try:
                        await run_chat_turn(db, user, "thanks", platform="ios",
                                            schedule_background=False)
                        await db.commit()
                    except Exception:                # noqa: BLE001
                        await db.rollback()
                async with session() as db:
                    for row in await _entries_after(db, uid, watermark):
                        name = str(row.parsed_food_name or "")
                        entity_id = await _identity_for(db, name)
                        entries_seen.append({
                            "landed_on_turn": -1, "user": handle,
                            "parsed_food_name": name,
                            "canonical_entity_id": entity_id,
                            "rung": await _rung_for(db, uid, name, entity_id, pre_keys),
                            "bucket": None, "calories": row.calories,
                            "quantity": row.quantity, "latency_ms": None,
                            "flushed": True})
            # The bucket for a flushed row is filled in during reconciliation, once
            # it is known which corpus item it belongs to.
            for entry in entries_seen:
                if entry.get("flushed") and entry["rung"] == "ESTIMATE_OR_REFUSE":
                    entry["bucket"] = classify(entry["parsed_food_name"])

            # ⭐ THE DAY ENDS HERE. Re-date the finished log into the past so the
            # next day opens a fresh one — dedup resets, memory persists. The
            # offset counts DOWN so days stay in chronological order and no two
            # logs collide on `uq_daily_log_user_date`.
            if day < total_days - 1:
                for uid in users.values():
                    await _roll_the_day(session, uid, total_days - day)

        async with session() as db:
            resolutions = await _resolution_rows(db)
    finally:
        await engine.dispose()

    observations, unmatched = _reconcile(body, entries_seen)
    return _report(corpus, observations, unmatched, latencies, failures,
                   recovered, resolutions, mode=mode, turns=len(body))


def _reconcile(body, entries_seen):
    """Attach each written row to the corpus item it came from.

    ⭐ BY FOOD AND BY USER, IN ORDER — NEVER BY TURN INDEX, because the turn
    path defers commits. Matching is on `normalize_name`, the production
    normalizer, so 'Chicken Breast' and 'chicken breast' are the same food here
    for exactly the reason they are the same food to the lookup.

    ⚠ AND BOTH LEFTOVERS ARE REPORTED. A corpus item with no row is an entry
    missing from every percentage below it; a row with no corpus item is the
    turn writing something the corpus never predicted — a multi-item split, or
    the interpreter naming a food differently. Silently dropping either is how
    a mix gets computed over a survivor set and read as a population.
    """
    from core.food_intelligence import normalize_name

    pending: dict = collections.defaultdict(list)
    for position, item in enumerate(body):
        pending[item["user"]].append([position, item, None])

    unmatched_rows = []
    for entry in entries_seen:
        candidates = pending[entry["user"]]
        target = normalize_name(entry["parsed_food_name"])
        slot = next((c for c in candidates
                     if c[2] is None and normalize_name(c[1]["food"]) == target), None)
        if slot is None:
            # A looser pass before giving up: the interpreter renames
            # ('grilled eggplant' -> 'Grilled eggplant', 'Eggs' -> 'Egg').
            slot = next((c for c in candidates
                         if c[2] is None
                         and (target in normalize_name(c[1]["food"])
                              or normalize_name(c[1]["food"]) in target)), None)
        if slot is None:
            unmatched_rows.append(entry)
            continue
        slot[2] = entry

    observations = []
    for user_slots in pending.values():
        for position, item, entry in user_slots:
            base = {"position": position, "user": item["user"],
                    "text": item["text"], "declared": item["declared"],
                    "role": item["role"], "predicted_food": item["food"]}
            if entry is None:
                observations.append({**base, "parsed_food_name": None,
                                     "canonical_entity_id": "",
                                     "rung": "NO_ROW_WRITTEN", "bucket": None,
                                     "calories": None, "quantity": None,
                                     "latency_ms": None})
            else:
                observations.append({**base, **entry})
    observations.sort(key=lambda o: o["position"])
    return observations, unmatched_rows


async def _resolution_rows(db) -> list:
    """Everything the interpretation boundary wrote, as plain dicts.

    ⭐ THE CONSUMER VIEW RIDES ALONG, because "did a PRODUCT bind anything" is a
    question for `entity_id_for_surface` and not for the raw column —
    `MAY_NAME_AN_ENTITY` deliberately lets a PRODUCT row CARRY an id while
    `binds` excludes it.
    """
    from sqlalchemy import select

    from db.models import FoodEntityResolution
    from skills.nutrition.entity_resolution import entity_id_for_surface

    rows = (await db.execute(select(FoodEntityResolution))).scalars().all()
    out = []
    for row in rows:
        out.append({
            "surface_form": row.surface_form,
            "surface_key": row.surface_key,
            "canonical_entity_id": str(row.canonical_entity_id or ""),
            "state": getattr(row.state, "value", str(row.state)),
            "consumer_binds": await entity_id_for_surface(db, row.surface_form),
        })
    return out


def _resolution_quality(resolutions, observations, body) -> dict:
    """⭐ THE FIVE THINGS STEP 5 MUST MEASURE *(Danny, 2026-08-15)*.

    Quality of the STORE, not reachability of the seam — the seam is proven and
    this is the question that decides whether consume mode is safe to turn on.
    """
    import collections
    import re

    non_ascii = re.compile(r"[^\x00-\x7f]")

    by_state = collections.Counter(r["state"] for r in resolutions)

    # ⛔ FRAGMENTATION: several DISTINCT ids for what is plainly one food family.
    # Measured live on 2026-08-15: `tvorog 3pct`, `tvorog 5percent`,
    # `tvorog 2percent`, `smetana 5percent` — two suffix conventions across four
    # samples. Harmless while ids are stored per surface; under CONSUME the id
    # becomes the memory key, so a family that fragments is a family whose
    # memory fragments with it.
    #
    # ⚠ THE FAMILY IS THE FIRST TOKEN, WHICH IS A HEURISTIC AND IS LABELLED AS
    # ONE. It groups `tvorog *` correctly and would group two genuinely
    # different foods sharing a first word. It is an indicator, not a verdict.
    # ⛔ TWO CORRECTIONS THE FIRST FULL RUN FORCED.
    #
    # 1  FRAGMENTATION CROSSES STATES. The first version filtered to
    #    `distinct`, and missed `ground turkey 96 percent lean` (RESOLVED)
    #    sitting beside `ground turkey 94 lean pan cooked` (DISTINCT). A family
    #    does not split along the state column.
    # 2  PRODUCTS ARE EXCLUDED. `barebells caramel cashew` and `barebells salty
    #    peanut` share a first token because they share a BRAND — two different
    #    products, correctly two identities. Counting them as fragmentation
    #    reported 4 families when only 2 were real, which is a metric crying
    #    wolf at exactly the moment its number decides a rollout.
    families = collections.defaultdict(set)
    for row in resolutions:
        entity = row["canonical_entity_id"]
        if entity and row["state"] != "product":
            families[entity.split()[0]].add(entity)
    fragmented = {family: sorted(ids) for family, ids in families.items()
                  if len(ids) > 1}

    # ⛔ THE DENOMINATOR IS WHAT THE CORPUS DROVE, NOT WHAT COMMITTED. The
    # first version divided resolutions by foods that produced a FOOD ROW and
    # reported "16 of 15 (106.7%)" and "driven without a row: -2" — impossible
    # numbers, because resolution happens at interpretation time and every ASK
    # turn resolves a food that has not committed yet. Numerator and
    # denominator were counting different populations.
    #
    # ⭐ SO THE POPULATION IS THE CORPUS ITSELF: the foods this run set out to
    # drive. That is knowable up front, does not move with settlement, and is
    # the only denominator under which "success" means what it sounds like.
    driven = {str(item.get("food") or "") for item in body if item.get("food")}
    ru_driven = {name for name in driven if non_ascii.search(name)}
    ru_resolved = {r["surface_form"] for r in resolutions
                   if non_ascii.search(r["surface_form"] or "")}

    # PRODUCT must bind NOTHING to a consumer, whatever it carries.
    products = [r for r in resolutions if r["state"] == "product"]
    bound_products = [r for r in products if r["consumer_binds"]]

    # ⭐ CONVERGENCE IS THE POINT, SO IT IS MEASURED. Two surfaces reaching ONE
    # identity is the whole purpose of the boundary — and its absence is the
    # failure `Листья салата` -> `lettuce leaves` vs `Lettuce leaves` ->
    # `lettuce` shows. Reporting only fragmentation would count the cost and
    # never the benefit.
    converged = collections.defaultdict(list)
    for row in resolutions:
        if row["canonical_entity_id"]:
            converged[row["canonical_entity_id"]].append(row["surface_form"])
    shared = {entity: surfaces for entity, surfaces in converged.items()
              if len(surfaces) > 1}

    return {
        "states": dict(by_state),
        "identities_reached_by_more_than_one_surface": shared,
        "non_english_driven": len(ru_driven),
        "non_english_with_a_row": len(ru_resolved),
        "non_english_success_pct": (
            round(100 * len(ru_resolved) / len(ru_driven), 1)
            if ru_driven else None),
        # ⚠ ABSENCE IS INFERRED HERE, not read from the producer's telemetry:
        # foods driven that never produced a row. Truncation is one cause among
        # several (unresolved, a surface the interpreter renamed), so this is an
        # UPPER BOUND on the truncation rate and the log is the tiebreaker.
        "driven_without_a_resolution": max(
            0, len(driven) - len({r["surface_form"] for r in resolutions})),
        "distinct_families_fragmented": fragmented,
        "products": len(products),
        "products_binding_something": [r["surface_form"] for r in bound_products],
    }


def _report(corpus, observations, unmatched_rows, latencies, failures,
            recovered, resolutions, *, mode: str, turns: int) -> dict:
    entries = [o for o in observations if o["rung"] != "NO_ROW_WRITTEN"]
    rungs = collections.Counter(o["rung"] for o in entries)
    buckets = collections.Counter(o["bucket"] for o in entries if o["bucket"])
    total = max(len(entries), 1)

    realized = {name: round(100 * count / total, 1)
                for name, count in {**rungs, **buckets}.items()}

    # ⛔⛔ THE PRODUCTION BASELINE HAS NO TEMPORAL GUARD, AND COMPARING THE
    # GUARDED NUMBER TO IT WOULD BE THE §1e ERROR AGAIN — two populations read
    # as one result.
    #
    # `measure_identity_coverage` asks `_memory()` about 30-day-old entries,
    # long after the turn that wrote them cached its own candidate. So an entry
    # whose food was FIRST SEEN on that turn still reads as MEMORY there,
    # because by measurement time the row exists. Production's 43.7% is
    # therefore "these entries' foods are addressable in memory TODAY", not
    # "these entries were priced from memory AT SETTLE TIME".
    #
    # ⭐ SO BOTH NUMBERS ARE REPORTED, AND THE COMPARABLE ONE IS THE UNGUARDED
    # ONE. MEMORY + CACHED_BY_THIS_TURN is what the production instrument would
    # have said about these same rows, and it is what the drift check uses.
    # The guarded number is the sharper fact and is stated alongside — it is
    # what settlement actually had, and no existing baseline can see it.
    unguarded = dict(rungs)
    unguarded["MEMORY"] = (rungs.get("MEMORY", 0)
                           + rungs.get("CACHED_BY_THIS_TURN", 0))
    unguarded.pop("CACHED_BY_THIS_TURN", None)
    realized_comparable = {name: round(100 * count / total, 1)
                           for name, count in {**unguarded, **buckets}.items()}

    # ⛔ THE BUCKET NAMES AND THE TARGET NAMES ARE NOT THE SAME STRINGS, and the
    # first full run reported every bucket as 0.0% and flagged all four ⛔
    # because of it — while the tally directly above showed 24 · 22 · 7. A drift
    # table that reads a missing key as a measured zero does not under-report,
    # it INVENTS a finding. Keyed off the target names, which are the short ones.
    for short in list(corpus["target_mix_pct"]):
        if short in realized_comparable:
            continue
        head = short.split("+")[0].strip()
        for long, value in list(realized_comparable.items()):
            if long.startswith(head) and long not in corpus["target_mix_pct"]:
                realized_comparable[short] = value
                break
        realized_comparable.setdefault(short, 0.0)

    target = corpus["target_mix_pct"]
    drift = {name: round(realized_comparable.get(name, 0.0) - pct, 1)
             for name, pct in target.items()}

    # ⛔ THE PREDICTION IS NEVER RESOLVED IN ITS OWN FAVOUR. `declared` said
    # what this entry would do; the executed rung and the production classifier
    # said what it did. Where they differ, both are printed.
    divergences = []
    for observation in entries:
        actual = (observation["bucket"] or observation["rung"])
        if actual != observation["declared"]:
            divergences.append({
                "text": observation["text"], "role": observation["role"],
                "declared": observation["declared"], "actual": actual,
                "parsed_food_name": observation["parsed_food_name"]})

    return {
        "corpus_version": corpus["corpus_version"],
        "mode": mode,
        "turns_driven": turns,
        "entries_written": len(entries),
        "corpus_items_with_no_row": sum(
            1 for o in observations if o["rung"] == "NO_ROW_WRITTEN"),
        "rows_the_corpus_did_not_predict": unmatched_rows,
        "turn_failures": failures,
        "turns_that_returned_a_recovery_bubble": recovered,
        "driven_through": "core.chat_service.run_chat_turn",
        "rungs": dict(rungs),
        "uncovered_buckets": dict(buckets),
        "realized_mix_pct": realized,
        "realized_mix_pct_comparable": realized_comparable,
        "memory_at_settle_pct": realized.get("MEMORY", 0.0),
        "memory_addressable_after_pct": realized_comparable.get("MEMORY", 0.0),
        "why_two_memory_numbers": (
            "settle-time MEMORY is what pricing actually had; the addressable-"
            "after number is what scripts.measure_identity_coverage would report "
            "on these same rows, because it measures long after each turn cached "
            "its own candidate. Only the second is comparable to production's "
            "43.7%."),
        "target_mix_pct": target,
        "drift_pts": drift,
        "mix_within_tolerance": all(
            abs(value) <= MIX_TOLERANCE_PTS for value in drift.values()),
        "mix_tolerance_pts": MIX_TOLERANCE_PTS,
        "resolution_rows": len(resolutions),
        "resolution_states": dict(collections.Counter(
            r["state"] for r in resolutions)),
        "resolution_quality": _resolution_quality(
            resolutions, observations, corpus["body"]),
        "latency_ms": {
            "p50": round(statistics.median(latencies)) if latencies else None,
            "p95": (round(sorted(latencies)[int(len(latencies) * 0.95) - 1])
                    if len(latencies) >= 20 else None),
            "max": round(max(latencies)) if latencies else None,
        },
        "declared_vs_actual_divergences": divergences,
        "anti_vacuity": _anti_vacuity(entries, rungs, resolutions, mode,
                                      recovered, turns),
        "observations": observations,
        "instrument_limits": [
            "the MEMORY count is guarded by a PRE-TURN key snapshot; without it "
            "the turn's own cache write reads as coverage",
            "CACHED_BY_THIS_TURN is not a rung — it is the mechanism the NEXT "
            "log reaches MEMORY by, reported separately so neither is inflated",
            "one item per body turn, so entries ~= turns; production averages more",
            "synthetic phrasing around real production food names",
            "latency is this machine against the real providers, not production",
        ],
    }


def _anti_vacuity(entries, rungs, resolutions, mode: str,
                  recovered, turns: int) -> dict:
    """⭐ THE CHECKS THAT STOP A HOLLOW RUN FROM READING AS A RESULT.

    A green run means nothing until something proves the run happened at all.
    Each of these has a specific way of failing silently, and each has cost this
    project a session at least once.
    """
    memory_by_repeat = sum(
        1 for o in entries if o["role"].startswith("repeat")
        and o["rung"] == "MEMORY")
    checks = {
        # ⛔ FIRST, BECAUSE IT EXPLAINS EVERY OTHER FAILURE BELOW IT. A turn that
        # cannot reach the model returns a recovery bubble and raises nothing,
        # so an outage reports as a clean zero across the board.
        # ⚠ A MAJORITY, NOT A PERFECT RECORD. This was `turns // 4` and it read
        # a FOUR-turn run with ONE 60-second turn-budget timeout as "the run
        # never happened" — while all four rows had been written. A guard that
        # cries outage at a single slow turn gets ignored, and then it is not a
        # guard. What it must separate is an outage from a bad day.
        "turns_reached_the_model": len(recovered) < max(turns // 2, 1),
        # A corpus that wrote no rows would report a beautifully empty mix.
        "rows_were_actually_written": len(entries) > 0,
        # If retrieval never seats a candidate, nothing caches, and every
        # "covered" entry silently becomes ESTIMATE — the mix would then be
        # measuring the provider outage, not the corpus.
        "memory_was_earned_by_repetition": memory_by_repeat > 0,
        # The rung must be reachable at all, or MEMORY=0 is ambiguous between
        # "no coverage" and "the rung is dead again" — which is exactly the
        # ambiguity that hid a dead rung for the life of the canonical lane.
        "memory_rung_returned_evidence": rungs.get("MEMORY", 0) > 0,
        "artifact_rung_returned_evidence": rungs.get("ARTIFACT", 0) > 0,
    }
    if mode == "shadow":
        # ⛔ THE MODE FLAG MUST BE PROVEN TO BITE. A shadow run that wrote no
        # resolutions is indistinguishable from an off run, and would otherwise
        # be reported as "no behaviour change" — the strongest possible result,
        # produced by the feature never running.
        checks["shadow_actually_resolved_something"] = len(resolutions) > 0
    else:
        checks["off_wrote_no_resolutions"] = len(resolutions) == 0
    return {"checks": checks, "all_passed": all(checks.values()),
            "memory_hits_on_repeat_turns": memory_by_repeat}


def render(report: dict) -> str:
    out = [f"\n  CORPUS `{report['corpus_version']}` · mode={report['mode']} · "
           f"through {report['driven_through']}\n",
           f"    {report['turns_driven']} turns driven · "
           f"{report['entries_written']} entries written · "
           f"{len(report['turn_failures'])} turn failures\n"]

    for name in ("MEMORY", "ARTIFACT", "CACHED_BY_THIS_TURN",
                 "ESTIMATE_OR_REFUSE"):
        count = report["rungs"].get(name, 0)
        pct = report["realized_mix_pct"].get(name, 0.0)
        out.append(f"    {count:5d}  {pct:5.1f}%   {name}")
    out.append("")
    for name, count in sorted(report["uncovered_buckets"].items(),
                              key=lambda kv: -kv[1]):
        out.append(f"    {count:5d}  "
                   f"{report['realized_mix_pct'].get(name, 0.0):5.1f}%   {name}")

    out.append(f"\n    MEMORY, TWO WAYS — at settle "
               f"{report['memory_at_settle_pct']:.1f}%  ·  addressable after "
               f"{report['memory_addressable_after_pct']:.1f}%")
    out.append("    (production's 43.7% is the SECOND kind — it measures rows "
               "long after their\n     own turn cached them, so only the second "
               "is comparable)")

    out.append("\n    REALIZED vs PRODUCTION (comparable basis, points of drift)")
    for name, value in report["drift_pts"].items():
        flag = " " if abs(value) <= report["mix_tolerance_pts"] else "⛔"
        out.append(f"    {flag}  {name:18} "
                   f"{report['realized_mix_pct_comparable'].get(name, 0.0):5.1f}%"
                   f"  vs {report['target_mix_pct'][name]:5.1f}%   {value:+.1f}")
    verdict = "PRODUCTION-LIKE" if report["mix_within_tolerance"] else "NOT PRODUCTION-LIKE"
    out.append(f"\n    -> {verdict} "
               f"(tolerance ±{report['mix_tolerance_pts']} pts)")

    latency = report["latency_ms"]
    out.append(f"\n    latency  p50 {latency['p50']} ms · p95 {latency['p95']} ms "
               f"· max {latency['max']} ms")
    out.append(f"    resolutions written {report['resolution_rows']} "
               f"{report['resolution_states'] or ''}")
    quality = report.get("resolution_quality") or {}
    if quality:
        out.append("\n    RESOLUTION QUALITY — the step-5 questions")
        out.append(f"      states                {quality['states']}")
        out.append(f"      non-English           "
                   f"{quality['non_english_with_a_row']} of "
                   f"{quality['non_english_driven']} got a row"
                   f"  ({quality['non_english_success_pct']}%)")
        out.append(f"      no resolution at all  "
                   f"{quality['driven_without_a_resolution']}   (upper bound on "
                   f"truncation — read the log to split it)")
        out.append(f"      PRODUCT rows          {quality['products']}, "
                   f"binding something: "
                   f"{quality['products_binding_something'] or 'none'}")
        fragmented = quality["distinct_families_fragmented"]
        out.append(f"      DISTINCT fragmentation {len(fragmented)} famil(ies) "
                   f"with >1 id")
        for family, ids in list(fragmented.items())[:6]:
            out.append(f"        {family}: {ids}")

    # ⛔ A TURN THAT WROTE NO ROW IS NOT A NEUTRAL EVENT — it silently removes an
    # entry from every percentage below it. Named, never just counted.
    silent = [o for o in report["observations"] if o["rung"] == "NO_ROW_WRITTEN"]
    if silent:
        out.append(f"\n    ⛔ {len(silent)} CORPUS ITEM(S) NEVER PRODUCED A ROW — "
                   f"each is an entry missing from the mix")
        for item in silent[:14]:
            out.append(f"      {item['role']:22} {item['text'][:52]!r}")
        if len(silent) > 14:
            out.append(f"      … {len(silent) - 14} more (see the JSON record)")
    stray = report["rows_the_corpus_did_not_predict"]
    if stray:
        out.append(f"\n    ⚠ {len(stray)} ROW(S) THE CORPUS DID NOT PREDICT")
        for row in stray[:8]:
            out.append(f"      turn {row['landed_on_turn']:3}  "
                       f"{row['rung']:20} {(row['parsed_food_name'] or '?')[:38]!r}")

    out.append("\n    ANTI-VACUITY")
    for name, passed in report["anti_vacuity"]["checks"].items():
        out.append(f"      {'PASS' if passed else '⛔ FAIL'}  {name}")

    divergences = report["declared_vs_actual_divergences"]
    out.append(f"\n    DECLARED vs ACTUAL — {len(divergences)} divergence(s)")
    for item in divergences[:12]:
        out.append(f"      {item['declared']:16} -> {item['actual']:20} "
                   f"{(item['parsed_food_name'] or '?')[:34]!r}")
    if len(divergences) > 12:
        out.append(f"      … {len(divergences) - 12} more (see the JSON record)")

    out.append("\n    LIMITS")
    for limit in report["instrument_limits"]:
        out.append(f"      · {limit}")
    return "\n".join(out) + "\n"


async def run_probes(*, mode: str, url: str) -> dict:
    """The named invariants, driven through the same real turn path.

    ⭐ THE PROSE IN THE CORPUS IS THE PREREGISTRATION; THIS IS ITS EXECUTABLE
    FORM. Each probe states an expectation for BOTH modes, written down before
    the run, so neither outcome can be read afterwards as the one that was
    predicted. The checks below are deliberately per-probe and explicit rather
    than parsed out of that prose — a check derived from the text it is meant to
    verify is not a check.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.canonical_pricing_inputs import _memory
    from core.chat_service import run_chat_turn
    from db.database import make_engine
    from db.queries import reload_user
    from skills.nutrition.entity_resolution import (ResolutionState, resolve,
                                                    entity_id_for_surface)
    from skills.nutrition.pricing_artifact import evidence_for, split_identity

    corpus = json.loads(CORPUS_PATH.read_text())
    os.environ["ENTITY_RESOLUTION_MODE"] = mode
    engine = make_engine(url)
    session = async_sessionmaker(engine, expire_on_commit=False)
    run_id = time.strftime("%Y%m%dT%H%M%S")

    async with session() as db:
        from sqlalchemy import delete

        from db.models import FoodEntityResolution
        await db.execute(delete(FoodEntityResolution))
        await db.commit()

    results = []
    try:
        for probe in corpus["probes"]:
            uid = await _fresh_user(session, probe["user"], mode, run_id)
            for text in probe["turns"]:
                async with session() as db:
                    user = await reload_user(db, uid)
                    try:
                        await run_chat_turn(db, user, text, platform="ios",
                                            schedule_background=False)
                        await db.commit()
                    except Exception:            # noqa: BLE001
                        await db.rollback()
            # One flush turn, for the same reason the body run needs one.
            async with session() as db:
                user = await reload_user(db, uid)
                try:
                    await run_chat_turn(db, user, "thanks", platform="ios",
                                        schedule_background=False)
                    await db.commit()
                except Exception:                # noqa: BLE001
                    await db.rollback()

            async with session() as db:
                observed = await _probe_observations(
                    db, uid, probe, _memory, resolve, entity_id_for_surface,
                    ResolutionState, evidence_for, split_identity)
            results.append({"id": probe["id"], "invariant": probe["invariant"],
                            "expected": probe[f"expect_{mode}"],
                            "kills": probe["kills"], **observed})
    finally:
        await engine.dispose()

    return {"corpus_version": corpus["corpus_version"], "mode": mode,
            "driven_through": "core.chat_service.run_chat_turn",
            "probes": results,
            "limits": [
                "each probe is a handful of turns — it demonstrates the "
                "invariant, it does not measure a rate",
                "a probe that writes no row proves nothing either way, and says "
                "so rather than passing quietly",
            ]}


async def _probe_observations(db, uid, probe, _memory, resolve,
                              entity_id_for_surface, ResolutionState,
                              evidence_for, split_identity) -> dict:
    """What the database says after a probe's turns — never the reply text."""
    from sqlalchemy import select

    from core.food_intelligence import memory_key
    from db.models import DailyLog, FoodEntry, UserFoodMatch

    rows = (await db.execute(
        select(FoodEntry.parsed_food_name, FoodEntry.quantity,
               FoodEntry.calories)
        .join(DailyLog, DailyLog.id == FoodEntry.daily_log_id)
        .where(DailyLog.user_id == uid).order_by(FoodEntry.id))).all()
    memory_rows = (await db.execute(
        select(UserFoodMatch.name_norm, UserFoodMatch.display_name,
               UserFoodMatch.cal_100)
        .where(UserFoodMatch.user_id == uid))).all()

    surfaces = {}
    for surface in probe["turns"]:
        entity = await entity_id_for_surface(db, surface)
        resolution = await resolve(db, surface)
        evidence = await _memory(db, uid, surface, entity)
        base, preparation = split_identity(surface)
        surfaces[surface] = {
            "canonical_entity_id": entity,
            "resolution_state": (getattr(resolution.state, "value",
                                         str(resolution.state))
                                 if resolution is not None else None),
            "memory_key": memory_key(surface, entity),
            "memory_reached_kcal_100g": (
                None if evidence is None
                else evidence.per100g.get("calories")),
            "artifact_key": f"{base}|{preparation}",
            "artifact_has_evidence": evidence_for(base, preparation) is not None,
        }
    return {
        "rows_written": [{"food": r[0], "quantity": r[1], "calories": r[2]}
                         for r in rows],
        "memory_rows": [{"key": m[0], "display": m[1], "cal_100": m[2]}
                        for m in memory_rows],
        "surfaces": surfaces,
        "wrote_nothing": not rows,
    }


def render_probes(report: dict) -> str:
    out = [f"\n  PROBES · mode={report['mode']} · through "
           f"{report['driven_through']}\n"]
    for probe in report["probes"]:
        out.append(f"    {probe['id']}  {probe['invariant']}")
        out.append(f"        expected: {probe['expected']}")
        if probe["wrote_nothing"]:
            out.append("        ⛔ NO ROW WAS WRITTEN — this probe proves "
                       "nothing either way")
        for surface, seen in probe["surfaces"].items():
            out.append(
                f"        {surface[:38]:40} entity={seen['canonical_entity_id'] or '—'!s:14}"
                f" state={seen['resolution_state'] or '—'!s:12}")
            out.append(
                f"        {'':40} key={seen['memory_key'] or '(non-addressable)'!r:26}"
                f" memory={seen['memory_reached_kcal_100g']} kcal"
                f"  artifact={seen['artifact_key']}"
                f"{' HIT' if seen['artifact_has_evidence'] else ' miss'}")
        out.append(f"        rows: {[r['food'] for r in probe['rows_written']]}")
        out.append("")
    for limit in report["limits"]:
        out.append(f"      · {limit}")
    return "\n".join(out) + "\n"


def compare_runs() -> int:
    """off vs shadow, on the ONE question the interpretation boundary exists for.

    ⭐ THE HEADLINE IS NOT THE OVERALL MIX — it is what happens to the
    NON-ENGLISH population specifically. Under `off`, a non-Latin food's memory
    key loses its letters and the containment refuses it, so those entries can
    never reach the rung however often the user logs them. Under `shadow`, the
    key is the resolved identity. Everything else in the corpus is a control:
    if the English buckets move too, something other than the boundary changed.

    ⚠ AND A ZERO ON EITHER SIDE IS REPORTED, NEVER DIVIDED THROUGH. A shadow run
    that wrote no resolutions has not shown "no behaviour change"; it has shown
    that the feature did not run, and those two readings differ by everything.
    """
    off_path, shadow_path = RECORD_DIR / "run_off.json", RECORD_DIR / "run_shadow.json"
    for path in (off_path, shadow_path):
        if not path.exists():
            raise SystemExit(f"missing {path} — run both modes with --write first")
    off = json.loads(off_path.read_text())
    shadow = json.loads(shadow_path.read_text())

    def non_english_reaching_memory(report):
        from scripts.measure_identity_coverage import NON_ASCII

        rows = [o for o in report["observations"]
                if o.get("parsed_food_name")
                and NON_ASCII.search(o["parsed_food_name"])]
        reached = [o for o in rows if o["rung"] in ("MEMORY", "CACHED_BY_THIS_TURN")]
        return len(reached), len(rows)

    off_hits, off_total = non_english_reaching_memory(off)
    shadow_hits, shadow_total = non_english_reaching_memory(shadow)

    out = ["\n  off vs shadow — the interpretation boundary, measured\n"]
    out.append(f"    resolutions written      {off['resolution_rows']:5d}"
               f"  ->  {shadow['resolution_rows']:5d}")
    out.append(f"    MEMORY at settle         "
               f"{off['memory_at_settle_pct']:5.1f}%  ->  "
               f"{shadow['memory_at_settle_pct']:5.1f}%")
    out.append(f"    evidence-backed          "
               f"{off['realized_mix_pct'].get('MEMORY', 0) + off['realized_mix_pct'].get('ARTIFACT', 0):5.1f}%"
               f"  ->  "
               f"{shadow['realized_mix_pct'].get('MEMORY', 0) + shadow['realized_mix_pct'].get('ARTIFACT', 0):5.1f}%")
    out.append(f"\n    ⭐ NON-ENGLISH entries reaching the memory rung")
    out.append(f"       off     {off_hits:3d} of {off_total:3d}")
    out.append(f"       shadow  {shadow_hits:3d} of {shadow_total:3d}")
    out.append(f"\n    latency p50   {off['latency_ms']['p50']} ms  ->  "
               f"{shadow['latency_ms']['p50']} ms")
    out.append(f"    latency p95   {off['latency_ms']['p95']} ms  ->  "
               f"{shadow['latency_ms']['p95']} ms")

    if shadow["resolution_rows"] == 0:
        out.append("\n    ⛔⛔ THE SHADOW RUN WROTE NO RESOLUTIONS. This is NOT "
                   "'no behaviour change' —\n        the producer did not run. "
                   "Nothing below it can be read as evidence\n        about the "
                   "boundary, in either direction.")
    print("\n".join(out) + "\n")
    return 0 if shadow["resolution_rows"] > 0 else 1


def validate_corpus() -> int:
    """⭐ THE PREREGISTRATION CHECK — no model, no database, no network.

    Everything about the corpus that can be checked WITHOUT running it, checked
    before a single token is spent: that the composition matches its own stated
    plan, that no two utterances are identical (which is how the first smoke run
    lost its repeats to dedup), and — the one that matters — that every
    `declared` bucket agrees with what PRODUCTION'S OWN CLASSIFIER says about the
    food name the entry predicts.

    ⛔ THE CLASSIFIER IS THE AUTHORITY, NEVER THE LABEL. `classify` is imported
    from the instrument that measured production, so it carries the same
    `_looks_branded` heuristic and the same non-ASCII test. A corpus whose
    labels disagree with it is not weighted by production's distributions; it is
    weighted by mine.

    ⚠ ITS HONEST LIMIT: this checks the PREDICTED food name. What the
    interpreter actually emits can differ, and only a run can say. This makes
    the corpus internally sound; it does not make it correct.
    """
    from scripts.measure_identity_coverage import classify

    corpus = json.loads(CORPUS_PATH.read_text())
    body, plan = corpus["body"], corpus["body_plan"]
    problems = []

    counts = collections.Counter(item["declared"] for item in body)
    if len(body) != plan["entries"]:
        problems.append(f"{len(body)} entries, plan says {plan['entries']}")
    for name, expected in plan.items():
        if isinstance(expected, int) and name != "entries":
            if counts[name] != expected:
                problems.append(
                    f"{name}: plan {expected}, corpus has {counts[name]}")

    repeated = [text for text, count in
                collections.Counter(i["text"] for i in body).items() if count > 1]
    for text in repeated:
        problems.append(f"duplicate utterance {text!r} — dedup will eat it")

    # Only entries the corpus predicts will MISS carry a bucket; MEMORY and
    # ARTIFACT are rung predictions and the classifier says nothing about them.
    mislabelled = []
    for item in body:
        if item["declared"] in ("MEMORY", "ARTIFACT"):
            continue
        actual = classify(item["food"])
        declared = item["declared"]
        if not actual.startswith(declared.split("+")[0].split(" ")[0]):
            mislabelled.append((item["food"], declared, actual))
    for food, declared, actual in mislabelled:
        problems.append(f"{food!r} declared {declared}, classifier says {actual}")

    print(f"\n  PREREGISTRATION CHECK — {corpus['corpus_version']} "
          f"· {len(body)} entries · no model, no DB\n")
    for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        target = corpus["target_mix_pct"].get(name)
        share = 100 * count / max(len(body), 1)
        against = f"  vs production {target:5.1f}%" if target else ""
        print(f"    {count:5d}  {share:5.1f}%   {name:18}{against}")
    print(f"\n    {len(body) - len(mislabelled)}/{len(body)} labels agree with "
          f"the production classifier")
    print(f"    {len(repeated)} duplicate utterance(s)")
    if problems:
        print("\n  ⛔ PROBLEMS\n")
        for problem in problems:
            print(f"    · {problem}")
        print()
        return 1
    print("\n  -> the corpus is internally sound and labelled the way production "
          "classifies.\n     What it cannot tell you is what the interpreter will "
          "actually emit.\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true",
                        help="check the corpus without running it (no model, no DB)")
    parser.add_argument("--compare", action="store_true",
                        help="compare the recorded off and shadow runs")
    parser.add_argument("--probes", action="store_true",
                        help="run the named-invariant probes instead of the body")
    parser.add_argument("--mode", choices=("off", "shadow"), default="off")
    parser.add_argument("--limit", type=int, default=0,
                        help="drive only the first N body entries (smoke)")
    parser.add_argument("--write", action="store_true",
                        help="record the run as JSON next to the corpus")
    args = parser.parse_args()

    if args.validate:
        return validate_corpus()
    if args.compare:
        return compare_runs()

    url = os.getenv("ARNIE_CORPUS_DB")
    if not url:
        raise SystemExit(
            "set ARNIE_CORPUS_DB to a SCRATCH database — this writes real rows")

    # ⛔ THE TURN DOES NOT WRITE EVERYTHING THROUGH THE SESSION IT IS HANDED,
    # AND THE FIRST SMOKE RUN PROVED IT. Food rows landed in Postgres while the
    # turn logged `no such table: turn_metrics (sqlite3.OperationalError)` — the
    # metrics write goes through the APP-GLOBAL engine, which falls back to
    # SQLite when DATABASE_URL is unset. Half the turn was being observed in one
    # database and half of it was failing, silently, in another.
    #
    # ⚠ SET BEFORE ANY APP MODULE IMPORTS, because the global engine binds at
    # import time — which is why this lives in main() and not in run_body().
    os.environ.setdefault("DATABASE_URL", url)
    _load_key()

    if args.probes:
        probe_report = asyncio.run(run_probes(mode=args.mode, url=url))
        print(render_probes(probe_report))
        if args.write:
            path = RECORD_DIR / f"probes_{args.mode}.json"
            path.write_text(json.dumps(probe_report, indent=1,
                                       ensure_ascii=False))
            print(f"  recorded -> {path}\n")
        return 0

    report = asyncio.run(run_body(mode=args.mode, limit=args.limit, url=url))
    print(render(report))
    if args.write:
        suffix = f"_limit{args.limit}" if args.limit else ""
        path = RECORD_DIR / f"run_{args.mode}{suffix}.json"
        path.write_text(json.dumps(report, indent=1, ensure_ascii=False))
        print(f"  recorded -> {path}\n")
    return 0 if report["anti_vacuity"]["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
