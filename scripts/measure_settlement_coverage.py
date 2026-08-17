"""P11 — HOW MUCH OF REAL FOOD CAN THE GENERAL SETTLEMENT OWNER ACTUALLY OWN?

Three numbers, published together, and the third is the only one that describes
the product:

    A  routing rate     structured-route / ORDINARY FOOD-CHAT meals
    B  support rate     supported meals / STRUCTURED-ROUTE meals  <- flattering
    C  ownership rate   supported / ORDINARY FOOD-CHAT meals  =  A x B

⛔⛔ NO SUPPORT RATE PUBLISHES WITHOUT ITS ROUTING RATE *(Danny, 2026-08-16)*.
The owner only ever sees turns routed as STRUCTURED_FOOD, and on 2026-08-15
three of four ordinary food turns never reached that lane. B is the number this
slice can move on its own, so B is the number a later reader will quote — and B
alone describes a quarter of the product while looking like all of it. Each of
the three can be individually correct while the population underneath changes:
the quiet form of the `16 of 15 (106.7%)` error.

⭐ THE MEAL IS THE UNIT, NOT THE ENTRY, because A11 declines the WHOLE meal when
any item lacks local evidence. A 44.6% addressable ENTRY rate does not imply a
44.6% supported MEAL rate, and measuring per entry would overstate coverage by
construction. Meals are grouped by `ledger_events.turn_id`, the same
correlation key the corpus attribution repair is built on.

⛔ AND THE PREDICATE IS EXECUTED, NEVER MODELLED. `coverage_for` is imported and
called — the same function routing calls. An instrument that approximates its
subject cannot discover that its subject is broken, and this project has
already paid for that once: a coverage number said memory carried 44.6% while
the rung it described returned nothing for all 836 rows.

⚠ READ-ONLY. No writes, no model, no network beyond the database.

    ARNIE_PROD_DATABASE_URL=... ../arnie/.venv/bin/python -m \\
        scripts.measure_settlement_coverage --days 30
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import dataclasses
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

ROOT = pathlib.Path(__file__).resolve().parent.parent


def predicate_commit() -> str:
    """⛔⛔ NO COVERAGE FIGURE PUBLISHES WITHOUT THE COMMIT IT WAS TAKEN AT
    *(Danny, 2026-08-17)*.

    `36.9%` was published at `beac35a` on 08-15; the count-only/mass branch
    entered `decide()` at `951b90e` on 08-16; re-running the SAME instrument on
    the SAME window then gave 20.2%. For a day the program was sequenced on a
    number the system could no longer produce. The directive now requires every
    figure to name its predicate, and a requirement that lives only in prose is
    a requirement the next run forgets — so the instrument stamps itself.

    ⚠ AND A DIRTY TREE IS NOT A COMMIT. A measurement taken over uncommitted
    edits cannot be reproduced from the sha, so it says so in the string rather
    than quietly naming a commit that did not produce it.
    """
    def _git(*args) -> str:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                             text=True, timeout=30)
        return out.stdout.strip() if out.returncode == 0 else ""

    sha = _git("rev-parse", "--short", "HEAD")
    if not sha:
        return "UNKNOWN — git unavailable, so this figure names no predicate"
    dirty = _git("status", "--porcelain", "--", "core", "skills", "db")
    return f"{sha}-DIRTY" if dirty else sha

# ⛔⛔ `ledger_events.source` NAMES THE WRITER, NOT THE ROUTE, and the first
# version of this instrument treated the two as one. `canonical_writer` says it
# outright: *"`ledger_source` names the mutation LANE and its owner
# (`canonical:create`, matching the existing `structured_food:*` / `legacy:ios`
# / `quick_log:ios` convention)"*.
#
# So `source.startswith("structured_food")` else "legacy" was an INVERSION
# waiting to happen: `write_canonical_meal` emits `canonical:create`, so a
# structured-ROUTED turn settled canonically would be filed as a routing
# failure — and ADOPTION WOULD DRIVE THE MEASURED ROUTING RATE DOWN. Not
# hypothetical: 36 rows in the 21-day window are already `canonical:create`
# (the B-1 answer path), and all 36 were counted as legacy.
#
# ⚠ AND THE DENOMINATOR HAS TO BE ORDINARY FOOD-CHAT TURNS. `quick_log:*` and
# `dashboard:*` are not chat turns at all; counting them as turns that failed
# to reach the structured lane would blame the lane for traffic that never went
# near it.
CANONICAL_ROUTE_PREFIXES = ("structured_food",)
NOT_A_CHAT_TURN_PREFIXES = ("quick_log", "dashboard")
LEGACY_PREFIXES = ("legacy",)

#: Which canonical OWNER an operation id names. `canonical:create` is emitted by
#: every canonical lane, so the source cannot say — only the operation can.
CHAT_OPERATION_FAMILIES = ("general", "chat_quantity")
NOT_CHAT_OPERATION_FAMILIES = ("quick_log", "dashboard", "direct")


def meal_key(user_id, turn_id) -> str:
    """⛔⛔ USER-SCOPED, AND THIS IS THE SECOND TIME.

    A client turn id is NOT globally unique — `make_turn_id` returns
    `f"{channel}:{cid}"` verbatim, with no user in it. P10g fixed exactly this
    in SETTLEMENT (`operation_id_for`) and the measurement then made the same
    mistake one file over, keying meals on the turn id alone.

    Its effect here is worse than a miscount: two users sharing `ios:X` merge
    into ONE synthetic meal, `user_id` is overwritten by whichever row lands
    last, `coverage_for` evaluates BOTH users' foods against ONE user's memory,
    and the merged meal inherits BOTH users' operations — so a single
    general-settled row would paint the whole thing as general settlement and
    the canary would over-report itself.
    """
    return f"{int(user_id)}:{turn_id}"


def operations_by_entry(commits) -> dict:
    """`entry_id -> operation_id`, read from what each commit actually wrote.

    ⭐ THIS IS THE CANARY'S ONLY EYE. Every canonical lane emits
    `canonical:create`, so the ledger source cannot distinguish the general
    settlement owner from the B-1 answer path; `meal_commits.operation_id` can,
    and this is the join that reaches it. The payload nests under `result` —
    read defensively, because a reader that silently finds nothing here reports
    "legacy settled it" about canonical writes.
    """
    out: dict = {}
    for operation_id, payload in commits or ():
        try:
            body = json.loads(payload or "{}") if isinstance(
                payload, str) else (payload or {})
        except (TypeError, ValueError):
            continue
        body = body.get("result") if isinstance(
            body.get("result"), dict) else body
        for entry in (body or {}).get("committed_items") or []:
            if entry.get("entry_id") is not None:
                out[int(entry["entry_id"])] = str(operation_id or "")
    return out


def classify_meal(sources, operations) -> str:
    """Which bucket this meal belongs to. PURE, so it can be gated.

    ⛔ THE OPERATION DECIDES A CANONICAL ROW, NOT THE SOURCE. Every canonical
    lane emits `canonical:create`, so treating any `canonical:*` as
    structured-chat put a canonical QUICK-LOG into the ordinary-chat numerator.
    The operation family is the only thing that can tell them apart, and it is
    now consulted first for canonical rows.

    ⛔⛔ AND "I COULD NOT TELL" IS ITS OWN ANSWER. A canonical row whose
    MealCommit payload could not be mapped is UNKNOWN ownership — never
    evidence that legacy settled it. Calling it legacy is how the canary would
    go invisible again, in the one branch this whole measurement depends on.
    """
    sources = {s for s in (sources or ()) if s}
    operations = {o for o in (operations or ()) if o}

    if any(s.startswith(NOT_A_CHAT_TURN_PREFIXES) for s in sources):
        return "not_a_chat_turn"
    if any(s.startswith("canonical") for s in sources):
        if operations & set(CHAT_OPERATION_FAMILIES):
            return "structured"
        if operations & set(NOT_CHAT_OPERATION_FAMILIES):
            return "not_a_chat_turn"
        return "unclassified_canonical"
    if any(s.startswith(CANONICAL_ROUTE_PREFIXES) for s in sources):
        return "structured"
    if any(s.startswith(LEGACY_PREFIXES) for s in sources):
        return "legacy"
    return "unknown_writer"


def _database_url() -> str:
    """Production, read-only. NEVER a literal in this file."""
    url = os.getenv("ARNIE_PROD_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        env = pathlib.Path(__file__).resolve().parents[2] / "arnie" / ".env"
        if not env.exists():
            raise SystemExit(
                "no ARNIE_PROD_DATABASE_URL and no ../arnie/.env to read")
        found = re.search(r"^DATABASE_URL=(.+)$", env.read_text(), re.M)
        if not found:
            raise SystemExit("../arnie/.env carries no DATABASE_URL")
        url = found.group(1).strip().strip('"\'')
    return url.replace("+psycopg", "").replace("+asyncpg", "")


async def measure(*, days: int, limit: int, population: dict = None) -> dict:
    """`population` pins the EXACT rows to measure, replacing the rolling clock.

    ⛔⛔ A ROLLING WINDOW CANNOT TELL A PREDICATE GAIN FROM A TRAFFIC DRIFT
    *(Danny, 2026-08-17)*. `now() - days` selects a different population every
    time it runs, so "ownership went from 20.2% to X" after P17 would confound
    what the predicate learned with what people happened to eat that fortnight.
    P16b freezes one exact historical meal population; the post-P17 re-measure
    runs against THIS list and against fresh production, and the two together
    are what separate the two explanations. Either alone cannot.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.general_settlement import Supported, coverage_for
    from db.database import make_engine

    # The population predicate, and the ONE place the clock is chosen.
    if population:
        entry_ids = [int(i) for i in population["entry_ids"]]
        where, params = "fe.id = ANY(:ids)", {"ids": entry_ids}
    else:
        where = "fe.timestamp > now() - make_interval(days => :days)"
        params = {"days": days}

    engine = make_engine(_database_url().replace("postgresql://",
                                                 "postgresql+psycopg://"))
    meals: dict = collections.defaultdict(
        lambda: {"items": [], "sources": set(), "user_id": None,
                 "operations": set()})
    #: ⚠ AN EMPTY DICT, NEVER A MISSING NAME. If the window is withheld the
    #: function returns before attribution runs, and a NameError there would
    #: read as an instrument crash rather than as "not computed".
    attribution_result: dict = {}
    try:
        session = async_sessionmaker(engine, expire_on_commit=False)
        async with session() as db:
            # ⛔⛔ POPULATION COMPLETENESS FIRST, AND IT REFUSES RATHER THAN
            # DROPS. Meals are grouped by `ledger_events.turn_id`, so an entry
            # with no `created` event cannot be grouped — and an INNER JOIN
            # would silently compute every percentage below over the survivors.
            # Measured 2026-08-16 at days=30: 448 of 676 entries had an event,
            # so a third of the population was disappearing without a word.
            # The missing ones all predate 2026-07-24 — a pre-ledger era, not a
            # live gap — which is exactly the kind of thing a silent drop hides.
            coverage_of_population = (await db.execute(text(
                "SELECT count(*), count(*) FILTER (WHERE EXISTS ("
                "  SELECT 1 FROM ledger_events le WHERE le.entry_id = fe.id "
                "  AND le.event_type = 'created')) "
                "FROM food_entries fe "
                f"WHERE {where}"
            ), params)).one()
            total_rows, ledgered = int(coverage_of_population[0]), int(
                coverage_of_population[1])
            if total_rows and ledgered != total_rows:
                return {
                    "window_days": days,
                    "PUBLISHED": False,
                    "why_withheld": (
                        f"{total_rows - ledgered} of {total_rows} entries in "
                        f"this window carry no `created` ledger event, so they "
                        f"cannot be grouped into meals. Every rate would be "
                        f"computed over the survivors. Narrow the window to "
                        f"where the ledger is complete."),
                    "rows_in_window": total_rows,
                    "rows_groupable": ledgered,
                }
            # ⭐ THE JOIN IS THE POINT. `ledger_events` carries both the turn a
            # row belongs to AND the writer that produced it, so grouping and
            # routing come from the same authoritative record rather than from
            # two guesses.
            rows = (await db.execute(text(
                "SELECT fe.id, le.turn_id, le.source, fe.parsed_food_name, "
                "       fe.quantity, dl.user_id "
                "FROM food_entries fe "
                "JOIN daily_logs dl ON dl.id = fe.daily_log_id "
                "JOIN ledger_events le ON le.entry_id = fe.id "
                "     AND le.event_type = 'created' "
                f"WHERE {where} "
                "ORDER BY fe.timestamp DESC LIMIT :limit"
            ), {**params, "limit": limit})).all()

            # ⛔ A FROZEN POPULATION THAT SILENTLY SHRANK IS NOT FROZEN. A row
            # deleted since the freeze would quietly change every denominator
            # below, which is precisely the drift the freeze exists to remove —
            # so the count is checked against the manifest and reported, never
            # assumed.
            population_drift = None
            if population:
                found = {int(r[0]) for r in rows}
                missing = sorted(set(entry_ids) - found)
                if missing:
                    population_drift = {
                        "frozen_entry_ids": len(entry_ids),
                        "found_now": len(found),
                        "missing": missing[:50],
                        "note": "rows in the frozen population no longer "
                                "select — deleted, or their created event went "
                                "away. Every rate below is over the survivors.",
                    }

            # ⭐ WHICH CANONICAL OWNER SETTLED IT. Every canonical lane emits
            # `canonical:create` — B-1, quick_log and the general settlement
            # owner alike — so the SOURCE cannot tell them apart and the moment
            # P12 ships, the canary would be invisible to this instrument.
            # `meal_commits.operation_id` carries the lane: `chat_quantity:*`
            # is the B-1 answer path, `general:*` is the settlement owner
            # (`operation_id_for("general", user, turn)`). Mapped through the
            # committed entry ids the result payload already records.
            # ⛔⛔ NO TIME WINDOW HERE, AND THAT IS THE FIX RATHER THAN AN
            # OVERSIGHT. This filtered `meal_commits.created_at` by the SAME
            # number of days as the entries — but the entries are selected by
            # `fe.timestamp`, which is the MEAL time and which a user can
            # backdate ("that was dinner last night"), while `created_at` is
            # the WRITE time. Two different clocks on one window, so 12 of the
            # 36 canonical entries had their commit fall outside it and became
            # `unclassified_canonical` — an instrument reporting "I cannot
            # attribute this" about rows it had simply declined to look up.
            #
            # Verified: with the window removed, 36 of 36 map. The table holds
            # 92 rows all-time; when that stops being cheap, filter by the
            # entry ids in play rather than by a clock that does not match.
            commits = (await db.execute(text(
                "SELECT operation_id, result_payload FROM meal_commits"
            ))).all()
            operation_of = operations_by_entry(commits)

            turnless: list = []
            for entry_id, turn_id, source, name, quantity, user_id in rows:
                # ⛔ A TURNLESS ROW GETS ITS OWN KEY, NEVER A SHARED ONE.
                # `__no_turn__:{user_id}` collapsed every turnless row for one
                # user across the whole window into ONE giant meal — which the
                # predicate would then decline wholesale on a single missing
                # item. Measured here at 0 rows (406 of 406 carry a turn id),
                # and reported rather than assumed.
                if turn_id:
                    key = meal_key(user_id, turn_id)
                else:
                    turnless.append(int(user_id))
                    key = meal_key(user_id, f"__no_turn__:{len(turnless)}")
                meal = meals[key]
                meal["user_id"] = user_id
                meal["sources"].add(str(source or ""))
                meal["items"].append({"food_name": str(name or ""),
                                      "quantity": str(quantity or "")})
                operation = operation_of.get(int(entry_id), "")
                if operation:
                    meal.setdefault("operations", set()).add(
                        operation.split(":")[0])

            verdicts = {}
            for key, meal in meals.items():
                verdicts[key] = await coverage_for(
                    db, user_id=int(meal["user_id"]), items=meal["items"])

            # ⛔ P16 RUNS HERE, INSIDE THE SESSION, OVER THESE MEALS AND THESE
            # VERDICTS. Attribution needs the same database handle the predicate
            # used; computing it after `finally` would need a second session and
            # a re-selected population, which is exactly the second instrument
            # the directive forbids. `classify_meal` is pure, so the structured
            # set can be derived here without waiting for the buckets below.
            # ⭐ THE DENOMINATOR IS COMPUTED HERE, not passed in later. Ownership
            # POINTS are meals-recovered over ORDINARY FOOD-CHAT meals — the
            # same denominator as C — and a rollup scored against any other
            # population would produce percentages that cannot be added to
            # 20.2%. `classify_meal` is pure, so this costs nothing.
            _class = {k: classify_meal(m["sources"], m.get("operations"))
                      for k, m in meals.items()}
            attribution_result = await attribute_misses(
                db, meals=meals, verdicts=verdicts,
                structured=[k for k, c in _class.items() if c == "structured"],
                chat_meals=sum(1 for c in _class.values()
                               if c in ("structured", "legacy")))
    finally:
        await engine.dispose()

    buckets: dict = collections.defaultdict(list)
    for key, meal in meals.items():
        buckets[classify_meal(meal["sources"],
                              meal.get("operations"))].append(key)
    structured = buckets["structured"]
    legacy = buckets["legacy"]
    not_chat = buckets["not_a_chat_turn"]
    unknown = buckets["unknown_writer"]
    unclassified = buckets["unclassified_canonical"]

    # WHO SETTLED EACH MEAL, named rather than collapsed. `general` appearing
    # here at all is the canary's first visible sign.
    settled_by = collections.Counter()
    for key, meal in meals.items():
        ops = meal.get("operations") or set()
        if "general" in ops:
            settled_by["general_settlement_owner"] += 1
        elif "chat_quantity" in ops:
            settled_by["b1_answer_path"] += 1
        elif ops:
            settled_by[f"canonical:{sorted(ops)[0]}"] += 1
        else:
            settled_by["legacy_executor"] += 1

    supported_structured = [k for k in structured
                            if isinstance(verdicts[k], Supported)]
    # ⚠ REPORTED, NEVER USED AS THE HEADLINE. What the predicate WOULD support
    # on the legacy-routed meals says what the ceiling costs, but those turns do
    # not reach the owner and counting them as coverage would be a claim about
    # a path that does not exist.
    supported_legacy = [k for k in legacy if isinstance(verdicts[k], Supported)]

    # ⭐ THE DENOMINATOR IS ORDINARY FOOD-CHAT MEALS — not every food row.
    chat_meals = len(structured) + len(legacy)
    all_meals = max(chat_meals, 1)
    routing = 100.0 * len(structured) / all_meals
    support = (100.0 * len(supported_structured) / len(structured)
               if structured else None)
    ownership = 100.0 * len(supported_structured) / all_meals

    declines = collections.Counter(
        getattr(verdicts[k], "reason", "") for k in structured
        if not isinstance(verdicts[k], Supported))
    attribution = attribution_result or {}
    expected = collections.Counter(
        getattr(verdicts[k], "expected_source", "")
        for k in supported_structured)

    return {
        "window_days": days,
        # ⛔⛔ THE FIGURE NAMES ITS PREDICATE OR IT IS NOT A FIGURE. See
        # `predicate_commit` — 36.9% cost a day of sequencing for want of this
        # one string, and the directive's rule lived only in prose until now.
        "predicate_commit": predicate_commit(),
        "population": (
            {"frozen": True, "name": population.get("name"),
             "frozen_at": population.get("frozen_at"),
             "entry_ids": len(population.get("entry_ids") or []),
             "checksum": population.get("checksum")}
            if population else
            {"frozen": False,
             "selector": f"rolling: fe.timestamp > now() - {days} days",
             "WARNING": "a rolling window re-selects a different population "
                        "every run, so a change in this number cannot be "
                        "attributed to the predicate. Freeze one with "
                        "--freeze before using it as a baseline."}),
        "population_drift": population_drift,
        # ⭐ THE EXACT ROWS THIS RUN MEASURED, so a freeze is the SAME selection
        # rather than a second query that resembles it — the join and the LIMIT
        # both narrow the population, and a manifest built independently would
        # differ from the numbers it claims to pin. `main` consumes and removes
        # this; it never reaches the recorded report.
        "_selected_entry_ids": sorted(int(r[0]) for r in rows),
        "rows": len(rows),
        "meals": len(meals),
        "rows_without_a_turn_id": len(turnless),
        "A_routing_rate_pct": round(routing, 1),
        "B_support_rate_within_structured_pct": (round(support, 1)
                                                 if support is not None
                                                 else None),
        "C_ownership_rate_pct": round(ownership, 1),
        "identity": "C = A x B, and C is the only one that describes the "
                    "product. B alone flatters this slice by the size of the "
                    "routing ceiling.",
        "structured_meals": len(structured),
        "legacy_meals": len(legacy),
        "not_a_chat_turn_meals_EXCLUDED": len(not_chat),
        "unrecognised_writer_meals": len(unknown),
        # ⛔ THE CANARY VERDICT IS WITHHELD WHILE THIS IS NON-ZERO. A canonical
        # row nobody can attribute is unknown ownership, and the general
        # bucket is the thing this measurement exists to watch.
        "unclassified_canonical_meals": len(unclassified),
        # ⛔⛔ UNKNOWN_WRITER WITHHOLDS TOO *(Danny, 2026-08-16)*. An
        # unrecognised ledger source is the same class of ignorance as an
        # unattributable canonical row: the instrument cannot say which lane
        # wrote it, and a new writer appearing is exactly the event that would
        # make these numbers wrong. Publishing around it would let a fourth
        # settlement path arrive unnoticed — which is the thing this
        # measurement exists to catch.
        "canary_verdict_publishable": (len(unclassified) == 0
                                       and len(unknown) == 0),
        "writer_note": "A is derived from the WRITER (ledger_events.source) as "
                       "a proxy for the route, because no per-meal routing "
                       "record is persisted. `canonical:*` counts as "
                       "structured-route: in this window every canonical write "
                       "carries a `chat_quantity` operation id (the B-1 answer "
                       "path). If quick_log or general settlement later emit "
                       "`canonical:create` too, this proxy needs the operation "
                       "id to disambiguate them.",
        "supported_structured_meals": len(supported_structured),
        "supported_legacy_meals_NOT_COVERAGE": len(supported_legacy),
        "expected_rung_of_supported": dict(expected),
        "settled_by": dict(settled_by),
        "why_structured_meals_decline": dict(declines.most_common()),
        "P16_miss_attribution": attribution,
        "limits": [
            "meals are grouped by ledger_events.turn_id; a row with no created "
            "event cannot be grouped and is counted as its own meal",
            "food_entries carries NO canonical_entity_id, so the predicate is "
            "asked with an empty identity — this is coverage WITHOUT identity "
            "stamping, which is what the fleet has today",
            "the predicate is EXECUTED, not modelled; memory is read per item "
            "at measurement time, which is later than settle time and can only "
            "OVERSTATE memory",
            "read-only: no writes, no model, no network beyond the database",
        ],
    }


# ══ P16 — MISS ATTRIBUTION ══════════════════════════════════════════════════
#
# ⛔⛔ A ROW BELONGS TO A MECHANISM, NOT A LANGUAGE *(Danny, 2026-08-17)*.
# "Russian" stopped being the defect when the interpretation boundary fixed
# ADDRESSABILITY. If `Сметана 5%` resolves correctly and then no compatible
# candidate can be seated, the defect is CACHEABILITY — evidence retrieval — and
# a tranche aimed at "non-English support" would land at the wrong layer. So the
# primary axis is the mechanism that failed and the script is a TAG.
#
# ⭐ SAME POPULATION, SAME PREDICATE, BY CONSTRUCTION. This runs inside `measure`
# over the meals it already built and the verdicts it already computed. A second
# instrument that re-selected the population could not be ranked against P11 —
# and an instrument that approximates its subject cannot discover that its
# subject is broken.
#
# ⚠ FIRST MATCH WINS, AND THE ORDER IS THE CONTRACT. Every declining item lands
# in exactly one leaf, checked cheapest-and-most-specific first, so the counts
# sum to the number of declining items rather than double-counting a row that
# fails two ways.

#: The typed declines the predicate itself names — these are not "no evidence".
_TYPED = {
    "no canonical identity": "TYPED:no_canonical_identity",
    "no stated quantity": "TYPED:no_stated_quantity",
    "count-only quantity": "TYPED:count_only_quantity",
}

# ══ THE MASS-LESS SPLIT ═════════════════════════════════════════════════════
#
# ⛔⛔ "COUNT-ONLY QUANTITY" WAS ONE PREDICATE BRANCH DESCRIBING FOUR DEFECTS
# *(2026-08-17, found by driving the REAL normalizer over the frozen rows)*.
# P16 read `facts.has_mass == False` and named the whole bucket for the shape it
# assumed was underneath. Measured on p16b_0817, 183 mass-less rows:
#
#     118   64.5%   genuinely count-only          '1 piece'  '1 bar'
#      63   34.4%   A STATED MASS, unit unparsed  '300 г'  '200 мл'  '150 г'
#       2    1.1%   no quantity at all
#
# A third of the dominant mechanism is GRAMS WRITTEN IN CYRILLIC that the unit
# parser does not recognise. `150 г` is a mass, stated plainly — it is not a
# missing serving basis, and no amount of serving-basis evidence would price it.
# The two need different tranches, and a bucket that merges them sends the
# larger one to the wrong layer.
#
# ⭐ AND THIS IS THE `non_latin` TAG EARNING ITS KEEP RATHER THAN BECOMING A
# BUCKET. P16 recorded that 67 of 142 were non-Latin and correctly refused to
# call the tranche "non-English". That was right: the non-Latin rows are not ONE
# mechanism, they are two — an unparsed unit token and a genuine count — and
# only executing the parser over them could tell which.

#: A quantity that is ENTIRELY a number plus a mass/volume word. The unit tokens
#: are the ones observed unparsed in production; a token that already parses can
#: never reach here, because `has_mass` would be true.
_MASS_ONLY = re.compile(
    r"^\s*[\d]+(?:[.,][\d]+)?\s*"
    r"(г|гр|грамм\w*|г\.|кг|килограмм\w*|мл|миллилитр\w*|л|литр\w*)"
    r"\s*\.?\s*$", re.I | re.UNICODE)

#: A mass stated SOMEWHERE in the string but not as the whole of it —
#: '1 piece (~120g)'. The number exists and was not read.
_MASS_EMBEDDED = re.compile(
    r"[\d]+(?:[.,][\d]+)?\s*(g|г|гр|kg|кг|ml|мл|oz)\b", re.I | re.UNICODE)

#: '180 cal' — an ENERGY claim, which is not a quantity at all and cannot be
#: scaled against any basis. A different defect again.
_ENERGY = re.compile(r"^\s*[\d]+(?:[.,][\d]+)?\s*(cal|ккал|kcal|калор\w*)\s*$",
                     re.I | re.UNICODE)


def mass_less_shape(quantity_text: str) -> str:
    """WHY this quantity produced no gram mass. Executed, never assumed."""
    text = str(quantity_text or "").strip()
    if not text:
        return "TYPED:no_stated_quantity"
    if _ENERGY.match(text):
        return "TYPED:energy_stated_not_a_quantity"
    if _MASS_ONLY.match(text):
        return "TYPED:mass_stated_but_unit_unparsed"
    if _MASS_EMBEDDED.search(text):
        return "TYPED:mass_present_but_not_read"
    return "TYPED:count_only_quantity"


def _non_latin(text: str) -> bool:
    """A tag, never a bucket. Recorded so a mechanism can be cross-tabulated by
    script — which is the question "is this a non-English problem?" asked in a
    form that can actually be answered."""
    return any(ord(ch) > 0x24F for ch in (text or "") if ch.isalpha())


async def _mechanism(db, *, user_id: int, item: dict, facts) -> str:
    """The one mechanism that stopped this item, from LOCAL reads only."""
    from core.canonical_pricing_inputs import _address_has_one_authority
    from core.food_intelligence import memory_key
    from db.queries import get_user_food_match
    from skills.nutrition.entity_resolution import resolve as resolve_entity
    from skills.nutrition.pricing_artifact import evidence_for, split_identity

    identity = str(item.get("food_name") or "").strip()
    entity, preparation = split_identity(identity)

    # 1-3: the predicate's own typed declines, before any evidence question.
    if not facts.has_identity:
        return _TYPED["no canonical identity"]
    if not facts.has_quantity:
        return _TYPED["no stated quantity"]
    if not facts.has_mass:
        # ⛔ THE PREDICATE SAYS "no mass"; ONLY THE STRING SAYS WHY. Splitting
        # here rather than in `decide()` is deliberate: the predicate's branch
        # is correct as it stands — none of these can be scaled today — and the
        # instrument's job is to say which TRANCHE would fix each one.
        return mass_less_shape(item.get("quantity"))

    # 4: the interesting bucket — priceable shape, no local evidence.
    #
    # ⭐ IDENTITY STATE FIRST, because a surface that never resolved cannot have
    # a memory address worth asking about, and `product` / `distinct` are
    # DELIBERATE refusals rather than misses.
    try:
        row = await resolve_entity(db, identity)
    except Exception:                                    # noqa: BLE001
        row = None
    state = getattr(getattr(row, "state", None), "value", None) or (
        str(getattr(row, "state", "")) or "")
    if row is None:
        return "IDENTITY:no_resolution_row"
    if state == "unresolved":
        return "IDENTITY:resolver_declined"
    if state == "product":
        return "BRANDED:product_recognised_but_non_binding"
    if state == "distinct":
        return "IDENTITY:distinct_refused_a_false_collapse"

    # Memory: a row may EXIST and still be inadmissible. That distinction is the
    # whole reason this phase exists — it separates "we have never seen this
    # food" from "we have seen it and cannot trust the address".
    key = memory_key(identity, "")
    if not key:
        return "IDENTITY:key_not_addressable"
    try:
        memory_row = await get_user_food_match(db, user_id, key)
    except Exception:                                    # noqa: BLE001
        memory_row = None
    if memory_row is not None:
        if not getattr(memory_row, "cal_100", None):
            return "MEMORY:row_unusable_no_per100g"
        if not await _address_has_one_authority(db, key):
            return "CACHEABILITY:memory_quarantined_ambiguous_address"
        return "MEMORY:present_but_predicate_declined_UNEXPECTED"

    # Artifact: absent for the stated preparation, or absent entirely? The two
    # are different tranches — a vocabulary gap versus an uncovered food.
    if entity and evidence_for(entity, "") is not None:
        return "QUALIFIED:preparation_vocabulary_miss"
    return "BARE:artifact_entity_absent"


# ══ P16b — THE MEAL-LEVEL ROLLUP ════════════════════════════════════════════
#
# ⛔⛔ ITEM COUNTS ARE NOT OWNERSHIP POINTS *(Danny, 2026-08-17)*. Ownership is a
# MEAL rate and A11 declines the whole meal on ONE unsupported item, so a
# mechanism spread thinly across many multi-item meals recovers far fewer points
# than its item count implies. P16 said PRODUCT leads with 142 of 207 items;
# that is a PREDICTION about points until this runs.
#
# ⭐ THE COUNTERFACTUAL IS EXECUTED, NOT MODELLED. `ItemFacts` is frozen, so a
# mechanism is "satisfied" by `dataclasses.replace`-ing exactly the fact it names
# and re-running the REAL `decide()`. Nothing here re-implements the predicate —
# the same objection that killed the modelled-coverage instrument applies with
# full force to a counterfactual, which is even easier to make flattering.
#
# ⛔ AND SATISFYING A MECHANISM DOES NOT IMPLY SUPPORT. This is the whole reason
# the rollup can surprise: flipping `has_mass` on a count-only item moves it PAST
# the mass branch and straight into the evidence branches, where it may decline
# again for "no local evidence". An item recovered is not a meal recovered, and a
# mechanism satisfied is not an item recovered.

# ⛔⛔ EVERY MECHANISM GETS THE SAME TREATMENT, OR THE TABLE IS NOT A RANKING.
# The first version of this map gave PRODUCT a band — mass only, then mass plus
# evidence — and silently handed every IDENTITY mechanism the optimistic end for
# free. That put PRODUCT's LOWER bound (12.6) in a column next to IDENTITY's
# UPPER bound (16.7) and read as an inversion of P16. It was an artifact of the
# map. **A number computed under one assumption, ranked against a number
# computed under another, is the exact failure that cost this program a day on
# 36.9%** — and a counterfactual is far easier to make flattering than a
# measurement, because nothing in production contradicts it.
#
# So: LOWER is what the tranche LITERALLY delivers into `ItemFacts`. UPPER adds
# the evidence that delivery might also bring. Where the two coincide the
# mechanism is TIGHT and the band collapses to a point.

#: mechanism -> (what the fix literally supplies, what it might also supply).
#: Flipping anything else would be inventing a capability the tranche does not
#: deliver; flipping less would be denying the one it does.
_COUNTERFACTUAL = {
    # ── TIGHT: the deliverable IS one of decide()'s five facts ──────────────
    "TYPED:no_canonical_identity": ({"has_identity": True},) * 2,
    "TYPED:no_stated_quantity": ({"has_quantity": True},) * 2,
    # The memory ROW EXISTS in both of these; the tranche makes it usable.
    "CACHEABILITY:memory_quarantined_ambiguous_address": (
        {"has_memory": True},) * 2,
    "MEMORY:row_unusable_no_per100g": ({"has_memory": True},) * 2,
    "MEMORY:present_but_predicate_declined_UNEXPECTED": (
        {"has_memory": True},) * 2,
    # These two ARE artifact-coverage tranches: the deliverable is the evidence.
    "QUALIFIED:preparation_vocabulary_miss": ({"has_artifact": True},) * 2,
    "BARE:artifact_entity_absent": ({"has_artifact": True},) * 2,
    "IDENTITY:key_not_addressable": ({"has_memory": True},) * 2,

    # ── BANDED: the fix supplies part of the answer, and evidence MAY follow ─
    # A per-serving basis certainly supplies the MASS. Whether the count-only
    # food also gains per-serving nutrition depends on what P17 ships.
    "TYPED:count_only_quantity": ({"has_mass": True},
                                  {"has_mass": True, "has_artifact": True}),
    # ⭐ THE SAME FLIP, A COMPLETELY DIFFERENT TRANCHE. A unit-alias table gives
    # `150 г` a real mass; a serving-basis producer gives `1 piece` one. Both
    # satisfy `has_mass`, so their counterfactuals are identical and their COSTS
    # are not — which is exactly why they must be counted apart.
    "TYPED:mass_stated_but_unit_unparsed": (
        {"has_mass": True}, {"has_mass": True, "has_artifact": True}),
    "TYPED:mass_present_but_not_read": (
        {"has_mass": True}, {"has_mass": True, "has_artifact": True}),
    # An energy claim names no amount of food. Nothing in `ItemFacts` can be
    # flipped to make "180 cal" scalable, so its LOWER bound is honestly zero
    # and its upper bound assumes the turn re-asks for a quantity.
    "TYPED:energy_stated_not_a_quantity": (
        {}, {"has_mass": True, "has_artifact": True}),
    # ⚠ RESOLUTION IS NOT EVIDENCE, AND THIS IS WHERE THAT BITES. A resolver row
    # supplies NONE of decide()'s five facts — the item already had mass and
    # still declined for "no local evidence". So the honest lower bound of an
    # identity tranche is ZERO recovered meals, and its upper bound assumes
    # resolution also lands evidence for the food it resolved.
    "IDENTITY:no_resolution_row": ({}, {"has_artifact": True}),
    "IDENTITY:resolver_declined": ({}, {"has_artifact": True}),
    "IDENTITY:distinct_refused_a_false_collapse": ({}, {"has_artifact": True}),
    "BRANDED:product_recognised_but_non_binding": ({}, {"has_artifact": True}),
}


def _meal_recovers(records: list, mechanism: str, *, flip: dict) -> bool:
    """Would this declining meal become Supported if `mechanism` were satisfied?

    ⛔ EVERY DECLINING ITEM MUST CLEAR, because one unsupported item declines
    the meal. Items whose mechanism is something else are left EXACTLY as they
    were — that is what makes the recoveries disjoint across mechanisms and the
    column summable.
    """
    from core.general_settlement import Supported, decide

    for record in records:
        facts = record["facts"]
        if record["mechanism"] == mechanism:
            facts = dataclasses.replace(facts, **flip)
        if not isinstance(decide(facts), Supported):
            return False
    return True


async def attribute_misses(db, *, meals: dict, verdicts: dict,
                           structured: list, chat_meals: int) -> dict:
    """Every DECLINING item of every declining structured meal, by mechanism —
    and then the same misses rolled up to MEALS and to ownership POINTS."""
    from core.general_settlement import Supported, decide, look

    counts: collections.Counter = collections.Counter()
    tagged: collections.Counter = collections.Counter()
    examples: dict = {}
    items_seen = 0
    #: meal key -> the declining items of that meal, with facts and mechanism.
    #: Built ONCE: the rollup must not re-select a population or re-ask the
    #: predicate, or it could not be compared with the numbers above it.
    declining_meals: dict = {}
    for key in structured:
        if isinstance(verdicts.get(key), Supported):
            continue
        meal = meals[key]
        records = []
        for item in meal["items"]:
            facts = await look(db, user_id=int(meal["user_id"]), item=item)
            if isinstance(decide(facts), Supported):
                continue                       # this item was fine; another sank the meal
            items_seen += 1
            mechanism = await _mechanism(db, user_id=int(meal["user_id"]),
                                         item=item, facts=facts)
            counts[mechanism] += 1
            if _non_latin(str(item.get("food_name") or "")):
                tagged[mechanism] += 1
            examples.setdefault(mechanism, str(item.get("food_name") or "")[:48])
            records.append({"facts": facts, "mechanism": mechanism})
        if records:
            declining_meals[key] = records

    # ── the rollup ──────────────────────────────────────────────────────────
    denominator = max(int(chat_meals), 1)
    rollup: dict = {}
    for mechanism in counts:
        band = _COUNTERFACTUAL.get(mechanism)
        if band is None:
            # ⛔ AN UNMAPPED MECHANISM IS REPORTED, NEVER SCORED ZERO. A new
            # leaf in `_mechanism` with no counterfactual here would otherwise
            # silently recover nothing and read as "this tranche is worthless".
            rollup[mechanism] = {
                "declining_items": counts[mechanism],
                "meals_recovered_LOWER": None,
                "ownership_points_LOWER": None,
                "UNMAPPED": "no counterfactual defined for this mechanism — it "
                            "is NOT scored, and this is not a zero",
            }
            continue
        lower_flip, upper_flip = band
        containing = [k for k, r in declining_meals.items()
                      if any(x["mechanism"] == mechanism for x in r)]
        lower = [k for k in containing
                 if _meal_recovers(declining_meals[k], mechanism,
                                   flip=lower_flip)] if lower_flip else []
        upper = [k for k in containing
                 if _meal_recovers(declining_meals[k], mechanism,
                                   flip=upper_flip)]
        rollup[mechanism] = {
            "declining_items": counts[mechanism],
            "declining_meals_containing_it": len(containing),
            "meals_recovered_LOWER": len(lower),
            "ownership_points_LOWER": round(100.0 * len(lower) / denominator, 1),
            "meals_recovered_UPPER": len(upper),
            "ownership_points_UPPER": round(100.0 * len(upper) / denominator, 1),
            "tight": lower_flip == upper_flip,
            "delivers": {"lower": lower_flip or "nothing decide() can see",
                         "upper": upper_flip},
        }

    # ⭐ WHY THE COLUMNS DO NOT SUM TO THE ITEM COUNTS, STATED AS A NUMBER. A
    # meal recovers under M only if EVERY declining item is an M, so a meal
    # blocked by two mechanisms is recovered by NEITHER alone — and is invisible
    # in every row of the table above.
    blocked_by = collections.Counter(
        len({x["mechanism"] for x in r}) for r in declining_meals.values())
    multi = sum(c for n, c in blocked_by.items() if n > 1)
    low = [e["ownership_points_LOWER"] for e in rollup.values()
           if e.get("ownership_points_LOWER") is not None]
    high = [e["ownership_points_UPPER"] for e in rollup.values()
            if e.get("ownership_points_UPPER") is not None]

    return {
        "declining_items": items_seen,
        "by_mechanism": dict(counts.most_common()),
        "non_latin_within_each_mechanism": dict(tagged.most_common()),
        "one_example_each": examples,
        "reading": "Rank tranches by RECOVERABLE OWNERSHIP POINTS, not by "
                   "bucket name. `non_latin_within_each_mechanism` answers "
                   "'is this a non-English problem?' WITHOUT letting language "
                   "become the bucket — a resolved Cyrillic surface with an "
                   "unusable address is a cacheability defect.",
        "P16b_meal_rollup": {
            "declining_meals": len(declining_meals),
            "ordinary_food_chat_meals_DENOMINATOR": denominator,
            "by_mechanism": rollup,
            "meals_blocked_by_N_distinct_mechanisms": {
                str(n): c for n, c in sorted(blocked_by.items())},
            "meals_no_single_mechanism_can_recover": multi,
            "total_ownership_points_recoverable_LOWER": round(sum(low), 1),
            "total_ownership_points_recoverable_UPPER": round(sum(high), 1),
            # ⭐⭐ THE ROLLUP CHECKS ITSELF, AND THE CHECK IS EXACT. Under the
            # UPPER flip every mechanism supplies evidence, so a meal blocked by
            # exactly ONE mechanism must recover under that mechanism, and a
            # meal blocked by two must recover under NEITHER. Therefore the
            # UPPER recoveries must sum to exactly the number of
            # single-mechanism meals. If this disagrees, the counterfactual is
            # double-counting meals across mechanisms and every point in the
            # table above is wrong — which a plausible-looking table would never
            # otherwise reveal.
            "SELF_CHECK_upper_recoveries_equal_single_mechanism_meals": {
                "upper_recoveries_summed": sum(
                    e.get("meals_recovered_UPPER") or 0
                    for e in rollup.values()),
                "meals_blocked_by_exactly_one": blocked_by.get(1, 0),
                "holds": sum(e.get("meals_recovered_UPPER") or 0
                             for e in rollup.values()) == blocked_by.get(1, 0),
            },
            "method": "For each declining meal, the fact(s) each mechanism "
                      "names are flipped on the items it stopped and the REAL "
                      "decide() is re-run over every item. A meal recovers only "
                      "if all of its declining items clear, so recoveries are "
                      "DISJOINT across mechanisms and the points column sums.",
            "reading_the_band": "LOWER is what the tranche literally puts into "
                                "ItemFacts; UPPER adds the evidence that "
                                "delivery might also bring. RANK LOWER AGAINST "
                                "LOWER AND UPPER AGAINST UPPER — the first "
                                "version of this table compared one mechanism's "
                                "floor with another's ceiling and read as an "
                                "inversion that was not there. Where `tight` is "
                                "true the two ends coincide because the "
                                "deliverable IS one of decide()'s facts.",
        },
    }


def render(report: dict) -> str:
    if report.get("PUBLISHED") is False:
        return ("\n  P11 — SETTLEMENT COVERAGE\n\n    ⛔⛔ WITHHELD\n"
                f"    {report['why_withheld']}\n"
                f"    {report['rows_groupable']} of {report['rows_in_window']} "
                f"rows groupable over {report['window_days']} days\n")
    pop = report.get("population") or {}
    out = ["\n  P11 — SETTLEMENT COVERAGE, AT MEAL LEVEL\n",
           f"    {report['rows']} rows in {report['meals']} meals over "
           f"{report['window_days']} days",
           f"    predicate {report.get('predicate_commit','?')}   population "
           f"{'FROZEN ' + str(pop.get('name')) if pop.get('frozen') else 'ROLLING (not a baseline)'}"]
    if report.get("population_drift"):
        d = report["population_drift"]
        out.append(f"    ⛔ POPULATION DRIFT — {d['found_now']} of "
                   f"{d['frozen_entry_ids']} frozen rows still select")
    out.append("")
    b = report["B_support_rate_within_structured_pct"]
    out.append(f"    A  routing rate    {report['A_routing_rate_pct']:5.1f}%   "
               f"structured-route / ORDINARY FOOD-CHAT meals")
    out.append(f"    B  support rate    "
               f"{(f'{b:5.1f}%' if b is not None else '    — ')}   "
               f"supported / STRUCTURED   <- flattering")
    out.append(f"    C  OWNERSHIP RATE  {report['C_ownership_rate_pct']:5.1f}%"
               f"   supported / ORDINARY FOOD-CHAT meals  =  A x B")
    if not report.get("canary_verdict_publishable", True):
        out.append(f"\n    ⛔⛔ CANARY VERDICT WITHHELD — "
                   f"{report['unclassified_canonical_meals']} unattributable "
                   f"canonical meal(s), "
                   f"{report['unrecognised_writer_meals']} unrecognised "
                   f"writer(s)")
    out.append(f"\n    {report['supported_structured_meals']} of "
               f"{report['structured_meals']} structured-route meals "
               f"supported; {report['legacy_meals']} legacy-written; "
               f"{report['not_a_chat_turn_meals_EXCLUDED']} excluded as "
               f"not-a-chat-turn; {report['unrecognised_writer_meals']} "
               f"unrecognised writer")
    if report["expected_rung_of_supported"]:
        out.append(f"    expected rung: {report['expected_rung_of_supported']}")
    out.append("\n    WHY STRUCTURED MEALS DECLINE")
    for reason, count in (report["why_structured_meals_decline"] or {}).items():
        out.append(f"      {count:5d}  {reason}")
    a = report.get("P16_miss_attribution") or {}
    if a.get("by_mechanism"):
        out.append(f"\n    P16 — MISS ATTRIBUTION BY MECHANISM "
                   f"({a['declining_items']} declining items)")
        nl = a.get("non_latin_within_each_mechanism") or {}
        ex = a.get("one_example_each") or {}
        for mech, count in a["by_mechanism"].items():
            out.append(f"      {count:5d}  {mech:<52} "
                       f"non-latin {nl.get(mech, 0):3d}   e.g. {ex.get(mech,'')}")
        out.append(f"\n      {a.get('reading','')}")
    roll = (a.get("P16b_meal_rollup") or {})
    if roll.get("by_mechanism"):
        out.append(f"\n    P16b — ROLLED UP TO MEALS, AND TO OWNERSHIP POINTS")
        out.append(f"      {roll['declining_meals']} declining meals over "
                   f"{roll['ordinary_food_chat_meals_DENOMINATOR']} ordinary "
                   f"food-chat meals\n")
        out.append(f"      {'MECHANISM':<52}{'ITEMS':>6}"
                   f"{'PTS LOWER':>11}{'PTS UPPER':>11}   rank LOWER vs LOWER")
        ordered = sorted(roll["by_mechanism"].items(),
                         key=lambda kv: -(kv[1].get("ownership_points_UPPER") or 0))
        for mech, e in ordered:
            if e.get("UNMAPPED"):
                out.append(f"      {mech:<52}{e['declining_items']:>6}"
                           f"{'   UNMAPPED':>11}")
                continue
            tight = "  (tight)" if e.get("tight") else ""
            out.append(f"      {mech:<52}{e['declining_items']:>6}"
                       f"{e['ownership_points_LOWER']:>10.1f}%"
                       f"{e['ownership_points_UPPER']:>10.1f}%{tight}")
        out.append(f"\n      {roll['total_ownership_points_recoverable_LOWER']:.1f}"
                   f" .. {roll['total_ownership_points_recoverable_UPPER']:.1f}"
                   f" ownership points recoverable by single mechanisms")
        out.append(f"      {roll['meals_no_single_mechanism_can_recover']} "
                   f"declining meals are blocked by MORE THAN ONE mechanism "
                   f"and no single tranche recovers them")
        out.append(f"      blocked by N distinct mechanisms: "
                   f"{roll['meals_blocked_by_N_distinct_mechanisms']}")
    out.append("\n    LIMITS")
    for limit in report["limits"]:
        out.append(f"      · {limit}")
    return "\n".join(out) + "\n"


def population_path(name: str) -> pathlib.Path:
    return ROOT / "data" / "corpus" / f"population_{name}.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--freeze", metavar="NAME",
                        help="record the exact rows this run measured as a "
                             "reusable frozen population")
    parser.add_argument("--population", metavar="NAME",
                        help="measure EXACTLY a previously frozen population "
                             "instead of a rolling window")
    args = parser.parse_args()

    frozen = None
    if args.population:
        path = population_path(args.population)
        if not path.exists():
            raise SystemExit(f"no frozen population at {path}")
        frozen = json.loads(path.read_text())

    report = asyncio.run(measure(days=args.days, limit=args.limit,
                                 population=frozen))
    selected = report.pop("_selected_entry_ids", [])
    print(render(report))

    if args.freeze:
        if report.get("PUBLISHED") is False:
            raise SystemExit("refusing to freeze a WITHHELD run — the "
                             "population it names is not the one measured")
        # ⭐ ABSOLUTE BOUNDS AND A CHECKSUM, NOT A DAY COUNT. "21 days" names a
        # different set every morning; a sorted id list with a digest names one
        # set forever, and the digest is what lets a later run prove it re-read
        # the same one rather than a manifest someone edited.
        digest = hashlib.sha256(
            ",".join(str(i) for i in selected).encode()).hexdigest()[:16]
        path = population_path(args.freeze)
        path.write_text(json.dumps({
            "name": args.freeze,
            "frozen_at": report.get("predicate_commit"),
            "frozen_from_window_days": args.days,
            "entry_ids": selected,
            "checksum": digest,
            "why": "P16b. A rolling window cannot separate a PREDICATE gain "
                   "from a drift in what people ate. Re-run with "
                   f"`--population {args.freeze}` to measure this exact set.",
        }, indent=1))
        print(f"  frozen {len(selected)} rows -> {path}  [{digest}]\n")

    if args.write:
        path = ROOT / "data" / "corpus" / "settlement_coverage.json"
        path.write_text(json.dumps(report, indent=1, ensure_ascii=False))
        print(f"  recorded -> {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
