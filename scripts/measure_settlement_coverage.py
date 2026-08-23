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
import inspect
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
    memory_audit: dict = {}
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
            if population and population.get("rows"):
                total_rows = ledgered = len(population["rows"])
            else:
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
            # ⛔⛔ M1.1 — FROZEN MEANS FROZEN: A FIXTURE FREEZES INPUT FACTS,
            # NOT POINTERS TO MUTABLE ROWS *(Danny, P1, 2026-08-18)*. The first
            # p16b_0817 froze a list of food_entries ids. Two of them (3016,
            # 3017) were deleted LIVE by the user the next day, the "frozen"
            # population shrank 232 -> 230 meals, and the M1 commit explained
            # the resulting 20.3 -> 20.0 as "memory drift" — over the top of the
            # instrument's own population_drift report. A fixture that can
            # shrink between preregistration and result is not a fixture.
            #
            # So a fixture that carries `rows` (the facts: entry id, turn,
            # writer, food name, quantity, user) is measured FROM THOSE FACTS
            # and never touches food_entries. The immutable ledger `created`
            # events are the source of truth for reconstruction, and they held
            # all 361 rows including the two the mutable table lost.
            if population and population.get("rows"):
                rows = [(int(r["entry_id"]), r.get("turn_id"), r.get("source"),
                         r.get("food_name"), r.get("quantity"),
                         int(r["user_id"])) for r in population["rows"]]
                population_drift = None                # cannot drift, by construction
            else:
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
            # assumed. (Unreachable for a facts-carrying fixture — the point.)
            population_drift = None if (population and population.get("rows")) \
                else None
            if population and not population.get("rows"):
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
            memory_audit = await audit_supported_memory(
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
             "checksum": population.get("checksum"),
             # ⭐ M1.1 — a fixture is only frozen if it carries FACTS.
             "self_contained": bool(population.get("rows")),
             "kind": ("input_facts — cannot drift"
                      if population.get("rows")
                      else "row POINTERS — can shrink; NOT a valid "
                           "preregistration fixture")}
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
        "M1_supported_memory_audit": memory_audit,
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

#: The tranche §NEXT selected. The conditional-marginal ranking is computed
#: RELATIVE TO THIS, because a standalone ceiling cannot rank a second tranche
#: once meals are blocked by more than one mechanism.

# ══ MISS ATTRIBUTION, POST-P17g ═══════════════════════════════════════════
#
# ⛔⛔⛔ THE OLD MACHINERY WAS SILENTLY DEAD, AND ITS ZEROS READ AS FINDINGS.
# `_COUNTERFACTUAL` flipped `has_mass`/`has_artifact`/`has_memory`, and P17g
# replaced those in `decide()` with `selected_rung_authoritative`. Every flip
# became INERT, so all eight mechanisms reported 0.0 recoverable points — which
# is not "no tranche is worth anything", it is "this instrument can no longer
# move the predicate". `_mechanism` went stale the same way: it branched on
# `has_mass`, so 310 of 313 declining items fired ONE predicate branch while
# being spread across eight differently-named buckets.
#
# ⭐ AN INSTRUMENT THAT APPROXIMATES ITS SUBJECT CANNOT DISCOVER THAT ITS
# SUBJECT IS BROKEN. So classification now reads the REAL selected rung, and a
# counterfactual is only reported when it can be EXECUTED against concrete
# evidence through the real selector and the real predicate.

#: A recovery that could not be measured. ⛔ NOT ZERO AND NOT AN INT — zero
#: reads "this tranche recovers nothing" and the sole-blocked count reads "it
#: recovers everything"; both are answers, and the honest state is that there
#: is none. Kept unsummable so it cannot be quietly aggregated or ranked.
UNMEASURED = "UNMEASURED"

#: ⛔ TERMINAL MECHANISMS — every analyzed item lands in EXACTLY ONE.
#: Taxonomy supplied by Danny, 2026-08-22. `MULTIPLE_BLOCKERS` is a MEAL-level
#: verdict, not an item one: it is what a meal gets when its declining items do
#: not agree, and such meals are EXCLUDED from tranche ranking because no
#: single tranche recovers them.
MECHANISMS = (
    "BOUND_UNPRICEABLE",
    "NO_CANONICAL_IDENTITY",
    "NO_STATED_QUANTITY",
    "NO_LOCAL_EVIDENCE",
    "MEMORY_WINNER_NONAUTHORITATIVE",
    "ARTIFACT_WINNER_NONAUTHORITATIVE",
    "MEMORY_PRESENT_NO_WINNER",
    "ARTIFACT_PRESENT_NO_WINNER",
    "LOCAL_EVIDENCE_PRESENT_NO_WINNER",
    "OTHER_WINNER_NONAUTHORITATIVE",
    "MULTIPLE_BLOCKERS",
)


def mechanism_for(facts) -> str:
    """The ONE terminal mechanism that stopped this item. PURE.

    ⛔⛔ IT READS THE SELECTOR'S OWN RESULT. `facts.selected_rung` is written by
    `look()` from `select_priced_rung` — the loop `price()` runs — so this
    reports which rung the pricer would commit rather than re-deriving it from
    `has_memory`/`has_artifact`. A third opinion about "which rung wins" would
    drift from the pricer on exactly the inputs nobody tested, which is the
    defect P17g closed inside `decide()`.

    ⚠ MASS IS DELIBERATELY ABSENT. Whether a mass happens to be present is a
    FACT about the item, reported beside the mechanism and never as one. The
    old classifier branched on it and returned mass-shaped buckets, which split
    a single tranche into three (`count_only_quantity`,
    `mass_stated_but_unit_unparsed`, `mass_present_but_not_read`) while every
    one of them fired the same predicate branch.
    """
    if getattr(facts, "product_bound", False):
        return "BOUND_UNPRICEABLE"
    if not facts.has_identity:
        return "NO_CANONICAL_IDENTITY"
    if not facts.has_quantity:
        return "NO_STATED_QUANTITY"
    rung = str(getattr(facts, "selected_rung", "") or "")
    if rung == "memory":
        return "MEMORY_WINNER_NONAUTHORITATIVE"
    if rung == "artifact":
        return "ARTIFACT_WINNER_NONAUTHORITATIVE"
    if rung:
        # ⚠ MUST STAY EMPTY TODAY: `look()` offers the selector memory, a None
        # product, and artifact. A count here means the rung set changed and a
        # tranche is going unranked — declared so totality holds and so the
        # change is VISIBLE rather than absorbed by whichever leaf came last.
        return "OTHER_WINNER_NONAUTHORITATIVE"
    # ⛔⛔⛔ WHICH EVIDENCE FAILED IS THE TRANCHE *(Danny, review of `d8113d5`)*.
    # This returned `ARTIFACT_PRESENT_NO_WINNER` for anything with evidence, so
    # a MEMORY candidate that would not build — with no artifact anywhere in
    # sight — was filed as an artifact-RANKING defect. The name IS the repair:
    # artifact selection and memory usability are different work, and the table
    # would have looked well-attributed while pointing at the wrong one.
    if facts.has_memory and facts.has_artifact:
        # ⭐ NEITHER WON AND BOTH WERE PRESENT, so no single repair is
        # implicated. Naming one would be inventing an attribution; this is the
        # item-level analogue of MULTIPLE_BLOCKERS.
        return "LOCAL_EVIDENCE_PRESENT_NO_WINNER"
    if facts.has_memory:
        return "MEMORY_PRESENT_NO_WINNER"
    if facts.has_artifact:
        return "ARTIFACT_PRESENT_NO_WINNER"
    return "NO_LOCAL_EVIDENCE"


def memory_measures_counterfactual(*, item: dict, facts, memory_per100g):
    """The item's facts as they would be if the MEMORY rung carried sourced
    measures — or **None when the intervention cannot be simulated**.

    ⛔⛔⛔ EXECUTABLE, AND FROM CONCRETE EVIDENCE ON BOTH SIDES. The nutrition
    is THIS USER'S OWN memory row; the measures are the ones the COMMITTED
    ARTIFACT already holds for the same entity. Nothing is fabricated — the
    tranche relocates an existing fact onto the rung that lacks it, and that is
    exactly what is simulated.

    ⛔ AND THE FIRST VERSION OF THIS FUNCTION GOT IT WRONG IN A WAY WORTH
    RECORDING. It took the per-100 g numbers from the ARTIFACT as well, which
    silently simulates "the artifact rung wins" — a different tranche
    altogether, and a more generous one. A counterfactual that supplies more
    than its tranche delivers measures a capability nobody is building.

    ⭐ IT RUNS THE REAL SELECTOR. `select_priced_rung` is the function `price()`
    calls; the caller then re-decides with the real `decide()`. Neither the
    selection rule nor the predicate is recreated here.

    ⛔ None IS NOT False. A food the artifact holds no measures for, or a user
    with no usable memory row, cannot be simulated. Reporting that as "the
    tranche does not recover it" would be an absent answer wearing a negative
    one — and it is the whole reason this returns three states.
    """
    from core.canonical_pricing import (Rung, _from_artifact, _profile,
                                        _ranker_query, select_priced_rung)
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.pricing_artifact import evidence_for, split_identity
    from skills.nutrition.scaling import Per100g

    per100g = dict(memory_per100g or {})
    if not per100g:
        return None                                      # no row to carry them

    identity = str(item.get("food_name") or "").strip()
    quantity = str(item.get("quantity") or "").strip()
    entity, preparation = split_identity(identity)
    if not entity or not quantity:
        return None

    evidence = evidence_for(entity, preparation)
    if evidence is None:
        return None
    try:
        built = _from_artifact(evidence,
                               query=_ranker_query(entity, preparation))
    except Exception:                                    # noqa: BLE001
        return None
    if not built or not built[5]:
        return None                                      # nothing to relocate
    measures = built[5]

    # A memory rung shaped exactly as `_from_memory` builds one, differing ONLY
    # in the field the tranche would supply.
    def _build(_ev):
        return (_profile(per100g, source="memory", source_id="memory:cf",
                         confidence=1.0, estimated=False),
                Rung.MEMORY, "memory:cf", dict(per100g), Per100g(), measures)

    try:
        selection = select_priced_rung(
            entity=entity, preparation=preparation,
            consumed=normalize_quantity(quantity, identity),
            rungs=((object(), _build),), bound=False)
    except Exception:                                    # noqa: BLE001
        return None
    return dataclasses.replace(
        facts,
        selected_rung=(selection.rung.value if selection.rung else ""),
        selected_rung_authoritative=bool(selection.authoritative))


# ══ THE AUTHORIZED ARTIFACT-EXTENSION COUNTERFACTUAL ══════════════════════
#
# ⛔⛔⛔ AUTHORIZED SCOPE, VERBATIM *(Danny, 2026-08-22)*: a READ-ONLY USDA FDC
# 15.3 artifact-extension counterfactual over `NO_LOCAL_EVIDENCE`, using the
# existing canonical identity, real USDA candidates, the real ranker, actual
# sourced portions, the shared selector and the real `decide()`.
#
# FORBIDDEN, and none of it happens here: translations, restaurant estimates,
# recipe decomposition, OFF, aliases, generated evidence.
#
# ⭐ QUALIFICATION IS INCLUDED, AND THAT IS A DECISION WORTH NAMING. The
# artifact stores QUALIFIED candidates — `ArtifactEvidence.candidates` is the
# subset a resolver judged admissible, and `_from_artifact` ranks over exactly
# that. Feeding raw `/foods/search` hits to the ranker would model an artifact
# that no builder produces and would be strictly MORE generous, so the measured
# recovery would overstate what extending the artifact actually buys. The
# resolver judges IDENTITY ELIGIBILITY; it generates no nutrition, so it is not
# "generated evidence". Its outages route to INFRASTRUCTURE, never to a
# negative verdict.
#
# ⛔ OFF BY DEFAULT. This is the only network in the instrument, so the routine
# run stays pure and `NO_LOCAL_EVIDENCE` reports UNMEASURED exactly as before
# unless `--artifact-extension` is passed.

#: Why the extension failed to make an item settleable. Danny's list, and every
#: analyzed item lands in exactly one — including recovery itself.
EXTENSION_OUTCOMES = (
    "RECOVERED",
    "no USDA match",
    "no defensible winner",
    "no nutrition",
    "no required portion/conversion",
    "higher-priority heuristic rung still wins",
    "infrastructure UNMEASURED",
)

#: identity -> (ArtifactEvidence | None, outcome). One USDA round trip per
#: DISTINCT identity: 202 declining items carry 155 of them, and asking twice
#: about the same food would cost twice and could answer differently.
_EXTENSION_CACHE: dict = {}


#: ⛔⛔⛔ A PROVIDER THAT IS DOWN FOR THE WHOLE RUN IS ONE FACT, NOT N FACTS
#: *(Danny, 2026-08-22)*. The Anthropic account ran out of credit mid-tranche
#: and every affected item reported `infrastructure UNMEASURED` — 80 separate
#: rows that LOOK like eighty findings about eighty foods and are one finding
#: about a billing state. A per-item bucket cannot represent a run-level
#: outage, so the run itself is withheld: PUBLISHED=False, no item outcomes.
EXTENSION_RUN_OUTAGE: dict = {"outage": None}


async def artifact_extension_preflight() -> dict:
    """ONE USDA search and ONE qualification, before any item work.

    ⛔ FAIL FAST, BECAUSE THE ALTERNATIVE IS A TABLE OF FALSE FINDINGS. Run 3
    spent its whole budget discovering, 152 times, that the resolver had no
    credit — and produced a report whose dominant bucket was an account state.
    Two calls up front answer that for the price of two calls.

    ⭐ AND IT PROBES BOTH SEAMS SEPARATELY, because they fail differently and
    need different repairs: USDA flakes transiently (retried), the resolver
    fails deterministically on billing (not retryable at all).
    """
    from api import usda
    from skills.nutrition.evidence_qualification import qualify_usda_rows

    report = {"usda": "unknown", "resolver": "unknown", "ok": False,
              "reason": ""}

    try:
        rows = await _with_retry(
            lambda: usda.search_food("cucumber", page_size=3, strict=True),
            what="preflight USDA search")
    except Exception as exc:                             # noqa: BLE001
        report["usda"] = f"UNAVAILABLE — {type(exc).__name__}"
        report["reason"] = "USDA search did not answer after retries"
        return report
    if not rows:
        report["usda"] = "answered, but returned nothing for a control query"
        report["reason"] = ("USDA answered with no rows for 'cucumber' — the "
                            "control food. A provider that cannot find a "
                            "cucumber cannot measure coverage.")
        return report
    report["usda"] = f"ok — {len(rows)} row(s) for the control query"

    try:
        qualification = await qualify_usda_rows("Cucumber", list(rows)[:1])
    except Exception as exc:                             # noqa: BLE001
        report["resolver"] = f"UNAVAILABLE — {type(exc).__name__}: {exc}"
        report["reason"] = f"qualification raised: {exc}"
        return report
    disposition = getattr(qualification, "disposition", "")
    if qualification is None or disposition == "resolver_down_no_candidates":
        report["resolver"] = f"UNAVAILABLE — disposition={disposition!r}"
        report["reason"] = (
            "the qualification resolver is down, so no USDA candidate can be "
            "judged admissible. Every item would report infrastructure and the "
            "run would describe an outage rather than the tranche.")
        return report

    report["resolver"] = f"ok — disposition={disposition!r}"
    report["ok"] = True
    return report


#: ⛔⛔⛔ MEASURED 2026-08-22: the IDENTICAL USDA search returns 200 or a 404
#: HTML error page roughly HALF the time, with rate-limit budget untouched
#: (3104 of 3600 remaining) and even when paced at one request per second. Two
#: full runs of this measurement disagreed wildly — 9 recovered vs 2, 132 "no
#: USDA match" vs 99 — because every flake was silently filed as "this food is
#: not in USDA".
#:
#: ⭐ SO THE FLAKE IS ABSORBED HERE, WHERE IT IS VISIBLE, rather than in a
#: bucket where it is indistinguishable from evidence. At ~50% per attempt,
#: five attempts leaves ~3% unanswered, and whatever remains is reported as
#: INFRASTRUCTURE — never as a fact about the food.
#: ⭐ PATIENCE SIZED TO THE GATE, NOT TO TASTE *(Danny: coverage is not
#: authorized unless infrastructure UNMEASURED reaches ZERO)*. Five attempts
#: left 20 of 152 items unanswered — 13%, against the ~3% a 50% per-attempt
#: flake predicts, because the failure rate WORSENS under sustained traffic:
#: the same run absorbed 197 recovered 404s. Twelve attempts with a capped
#: backoff, plus a pace between calls to stop provoking the throttle, is what
#: a zero-residual gate actually costs.
#:
#: ⛔ THIS IS NOT RETRYING UNTIL GREEN. Each attempt asks the SAME question of
#: a server that answers non-deterministically; nothing about the measurement
#: is re-rolled. The residual is still reported, and a non-zero one still fails
#: the gate.
_RETRY_ATTEMPTS = 12
_RETRY_BACKOFF = 1.2
_RETRY_BACKOFF_CAP = 8.0
#: A small gap between provider calls. The flake is load-dependent, so the
#: cheapest way to reduce it is to stop hammering.
_PROVIDER_PACE = 0.35


async def _with_retry(call, *, what: str):
    """Bounded retry around one provider call. Raises if it never answers."""
    import asyncio as _aio

    last = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            if _PROVIDER_PACE:
                await _aio.sleep(_PROVIDER_PACE)
            return await call()
        except Exception as exc:                         # noqa: BLE001
            last = exc
            if attempt + 1 < _RETRY_ATTEMPTS:
                await _aio.sleep(min(_RETRY_BACKOFF * (attempt + 1),
                                     _RETRY_BACKOFF_CAP))
    print(f"    ⚠ {what}: no answer after {_RETRY_ATTEMPTS} attempts")
    raise last if last else RuntimeError(what)


async def _usda_extension(identity: str, entity: str, preparation: str):
    """The artifact entry USDA FDC 15.3 would yield for this identity.

    Returns `(evidence, outcome)`. `evidence` is an `ArtifactEvidence` built
    from REAL qualified candidates carrying REAL `foodPortions`; `outcome` is
    None when it is usable, else the bucket that stopped it.
    """
    from api import usda
    from core.canonical_pricing import ArtifactEvidence
    from skills.nutrition.evidence_qualification import qualify_usda_rows

    if identity in _EXTENSION_CACHE:
        return _EXTENSION_CACHE[identity]

    async def _finish(evidence, outcome):
        # ⛔⛔ AN OUTAGE IS NOT A PROPERTY OF THE FOOD, so it is never cached.
        # Caching it let ONE transient 404 become a permanent verdict for that
        # identity for the rest of the run — which is how a 50% provider flake
        # turned into 45 "unmeasurable" items in the second run and 0 in the
        # first, from the same inputs.
        if outcome != "infrastructure UNMEASURED":
            _EXTENSION_CACHE[identity] = (evidence, outcome)
        return evidence, outcome

    # 1 — REAL USDA CANDIDATES, for the identity EXACTLY AS THE USER WROTE IT.
    # No translation: a Cyrillic surface searched as-is is what an
    # untranslated extension would actually find, and translating here would
    # measure a different tranche than the one authorized.
    try:
        rows = await _with_retry(
            lambda: usda.search_food(identity, page_size=10, strict=True),
            what=f"search {identity!r}")
    except Exception:                                    # noqa: BLE001
        print(f"    ⚠ USDA search failed for {identity!r} — UNMEASURED")
        return await _finish(None, "infrastructure UNMEASURED")
    if not rows:
        return await _finish(None, "no USDA match")

    # 2 — QUALIFICATION, the same seam the builder runs. An outage is
    # INFRASTRUCTURE, never "this food has no evidence".
    try:
        qualified = await qualify_usda_rows(identity, rows)
    except Exception:                                    # noqa: BLE001
        print(f"    ⚠ qualification raised for {identity!r} — UNMEASURED")
        return await _finish(None, "infrastructure UNMEASURED")
    if qualified is None or (
            getattr(qualified, "disposition", "") == "resolver_down_no_candidates"
            and not qualified.rows):
        # ⛔⛔ THE RESOLVER GOING DOWN IS NOT A FACT ABOUT THIS FOOD. It is the
        # same fact for every remaining item, so it is recorded ONCE at run
        # level and the run is withheld — rather than accumulating one
        # indistinguishable row per item, which is what made run 3 unreadable.
        EXTENSION_RUN_OUTAGE["outage"] = (
            "the qualification resolver became unavailable mid-run "
            f"(disposition={getattr(qualified, 'disposition', '')!r})")
        return await _finish(None, "infrastructure UNMEASURED")
    candidates = [dict(r) for r in (qualified.rows or ())]
    if not candidates:
        return await _finish(None, "no USDA match")

    # 3 — ACTUAL SOURCED PORTIONS, stamped with the release the caller names.
    # `enrich_artifact_measures` does exactly this at build time; a portion
    # with no release yields no `ConversionEvidence` and is not authoritative.
    for candidate in candidates:
        fdc_id = candidate.get("fdc_id")
        if not fdc_id:
            continue
        try:
            measures = await _with_retry(
                lambda: usda.food_portions(fdc_id, strict=True),
                what=f"portions {fdc_id}")
        except Exception:                                # noqa: BLE001
            print(f"    ⚠ portions failed for {fdc_id} — UNMEASURED")
            return await _finish(None, "infrastructure UNMEASURED")
        for measure in measures or ():
            measure["dataset_version"] = USDA_RELEASE
        if measures:
            candidate["measures"] = measures

    return await _finish(ArtifactEvidence(candidates=tuple(candidates),
                                          fingerprint="extension:usda15.3"),
                         None)


#: The FDC release the committed artifact was hydrated at (P17c.3b). Stamped,
#: never derived — a fabricated release in a durable conversion record is the
#: defect P17c.3a exists to prevent, and the counterfactual must not simulate
#: evidence the real build could not produce.
USDA_RELEASE = "15.3"


async def artifact_extension_counterfactual(*, item: dict, facts,
                                            memory_per100g=None):
    """The item's facts if the artifact were extended from USDA FDC 15.3.

    Returns updated `ItemFacts`, or **None when the outcome is UNMEASURED**.
    The bucket for every item is recorded in `EXTENSION_LEDGER` so failures can
    be reported by cause rather than as one undifferentiated zero.
    """
    from core.canonical_pricing import (_from_artifact, _ranker_query,
                                        select_priced_rung)
    from core.food_intelligence import best_candidate
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.pricing_artifact import split_identity

    identity = str(item.get("food_name") or "").strip()
    quantity = str(item.get("quantity") or "").strip()
    entity, preparation = split_identity(identity)

    def _record(outcome, updated=None):
        EXTENSION_LEDGER.append({"identity": identity, "outcome": outcome,
                                 "non_latin": _non_latin(identity)})
        return updated

    if not entity or not quantity:
        return _record("no USDA match")

    evidence, outcome = await _usda_extension(identity, entity, preparation)
    if outcome == "infrastructure UNMEASURED":
        return _record(outcome)                          # None -> UNMEASURED
    if outcome:
        return _record(outcome, dataclasses.replace(facts))

    query = _ranker_query(entity, preparation)
    # ⭐ THE REAL RANKER, ASKED DIRECTLY ONLY TO ATTRIBUTE. `_from_artifact`
    # calls this same function, so there is no second ranking rule — this
    # separates "the ranker chose nobody" from "it chose a row with no
    # nutrition", which are different repairs and would otherwise collapse.
    try:
        winner, _confidence = best_candidate(query, list(evidence.candidates))
    except Exception:                                    # noqa: BLE001
        return _record("infrastructure UNMEASURED")
    if not winner:
        return _record("no defensible winner", dataclasses.replace(facts))
    if not (winner.get("per100g") or {}):
        return _record("no nutrition", dataclasses.replace(facts))

    consumed = normalize_quantity(quantity, identity)
    try:
        selection = select_priced_rung(
            entity=entity, preparation=preparation, consumed=consumed,
            rungs=((evidence, lambda e: _from_artifact(e, query=query)),),
            bound=False)
    except Exception:                                    # noqa: BLE001
        return _record("infrastructure UNMEASURED")

    if selection.priced is None:
        return _record("no defensible winner", dataclasses.replace(facts))
    if not selection.authoritative:
        # ⚠ THE RUNG PRICES AND THE QUANTITY STILL CANNOT BE SCALED WITHOUT
        # GUESSING — no user-stated exact mass, no directly compatible basis,
        # no sourced conversion matching the stated unit. Extending coverage
        # does not answer a conversion question.
        return _record("no required portion/conversion",
                       dataclasses.replace(facts))

    updated = dataclasses.replace(
        facts, selected_rung=selection.rung.value if selection.rung else "",
        selected_rung_authoritative=True, has_artifact=True)
    return _record("RECOVERED", updated)


#: Every extension attempt, in order, so failures report by CAUSE.
EXTENSION_LEDGER: list = []


def _extension_report(addressable=None, sole_blocked=None):
    """Extension attempts by outcome, or None when it was never armed.

    ⛔ NOT AN EMPTY TABLE WHEN DISARMED. Zeros in every bucket would read as
    "the extension was tried and recovered nothing"; `None` says it was not
    run, which is the same distinction UNMEASURED draws one level up.
    """
    if EXTENSION_RUN_OUTAGE.get("outage"):
        # ⛔ WITHHELD, NOT ZEROED. Publishing buckets from a run whose provider
        # was down would put an outage into the tranche ranking, and a reader
        # cannot tell that table from a real one.
        return {"PUBLISHED": False,
                "why_withheld": EXTENSION_RUN_OUTAGE["outage"],
                "items_attempted_before_withholding": len(EXTENSION_LEDGER)}
    if not EXTENSION_LEDGER:
        return None
    by_outcome = collections.Counter(e["outcome"] for e in EXTENSION_LEDGER)
    unreachable = [o for o in EXTENSION_OUTCOMES if o not in by_outcome]
    return {
        "PUBLISHED": True,
        "release": f"USDA FDC {USDA_RELEASE}",
        # ⭐ THE POPULATION, RECONCILED TO THE REPAIRED INSTRUMENT *(Danny)*.
        # An earlier pre-filter figure of 202 items counted every declining
        # NO_LOCAL_EVIDENCE item in the whole frozen set; this counterfactual
        # only ever runs on the SOLE-BLOCKED meals, because a meal blocked by
        # two mechanisms is recovered by neither alone. 202 is retired — it
        # describes a population this measurement never had.
        "addressable_items": addressable,
        "sole_blocked_meals_entering_this_counterfactual": sole_blocked,
        "items_attempted": len(EXTENSION_LEDGER),
        "distinct_identities": len({e["identity"] for e in EXTENSION_LEDGER}),
        "by_outcome": {o: by_outcome.get(o, 0) for o in EXTENSION_OUTCOMES},
        # ⭐ LANGUAGE AS A LENS, NEVER AS A BUCKET — the rule this instrument
        # already applies to mechanisms. "Is this a non-English problem?" is a
        # question to ask OF each outcome; making it an outcome would let a
        # Cyrillic surface with an ordinary coverage gap be filed as a language
        # defect, and the repair would go to the wrong place.
        "non_latin_within_each_outcome": {
            o: sum(1 for e in EXTENSION_LEDGER
                   if e["outcome"] == o and e["non_latin"])
            for o in EXTENSION_OUTCOMES if by_outcome.get(o)},
        "non_latin_items": sum(1 for e in EXTENSION_LEDGER if e["non_latin"]),
        "buckets_not_observed": unreachable,
        # The per-identity ledger, so a follow-up question does not cost
        # another 124 provider round trips.
        "ledger": sorted(({"identity": e["identity"], "outcome": e["outcome"]}
                          for e in EXTENSION_LEDGER),
                         key=lambda e: (e["outcome"], e["identity"])),
        "scope": ("existing canonical identity · real USDA candidates · real "
                  "qualification · real ranker · actual sourced portions · "
                  "shared selector · real decide(). No translations, "
                  "restaurant estimates, recipe decomposition, OFF, aliases, "
                  "or generated evidence."),
    }


#: mechanism -> the EXECUTABLE counterfactual for its tranche, or None.
#:
#: ⛔ None MEANS UNMEASURED, NOT ZERO. `NO_LOCAL_EVIDENCE`'s tranche is "the
#: artifact covers this food", and there is no concrete evidence to supply, so
#: its recovery is unknown. Scoring it zero would read "coverage is worthless";
#: scoring it the sole-blocked count would read "coverage recovers all of them"
#: — an upper bound wearing a measurement's clothes. Both are answers where
#: none exists.
INTERVENTIONS = {
    "NO_LOCAL_EVIDENCE": None,
    "MEMORY_WINNER_NONAUTHORITATIVE": memory_measures_counterfactual,
    "ARTIFACT_WINNER_NONAUTHORITATIVE": None,
    "MEMORY_PRESENT_NO_WINNER": None,
    "ARTIFACT_PRESENT_NO_WINNER": None,
    "LOCAL_EVIDENCE_PRESENT_NO_WINNER": None,
    "OTHER_WINNER_NONAUTHORITATIVE": None,
    "BOUND_UNPRICEABLE": None,
    "NO_CANONICAL_IDENTITY": None,
    "NO_STATED_QUANTITY": None,
}


async def rank_mechanisms(db, *, declining_meals: dict) -> dict:
    """The three quantities, per mechanism *(Danny, 2026-08-22)*.

        addressable population        declining items carrying this mechanism
        meals blocked solely by it    every declining item agrees on it
        measured recovered meals      re-decided by the REAL predicate after
                                      the REAL selector ran the intervention,
                                      or UNMEASURED

    ⛔ THE THIRD NUMBER IS NEVER INFERRED FROM THE SECOND. A sole-blocked count
    is an addressable population, not a recovery: it says how many meals this
    mechanism is the only thing standing in front of, and says nothing about
    whether the tranche would actually clear them.
    """
    from core.general_settlement import Supported, decide

    items = collections.Counter()
    with_mass = collections.Counter()             # ⭐ orthogonal, reported apart
    solely: dict = collections.defaultdict(list)
    multiple = 0

    for key, records in declining_meals.items():
        mechs = {r["mechanism"] for r in records}
        for record in records:
            items[record["mechanism"]] += 1
            if getattr(record["facts"], "has_mass", False):
                with_mass[record["mechanism"]] += 1
        if len(mechs) > 1:
            multiple += 1
            continue
        solely[next(iter(mechs))].append(key)

    out: dict = {}
    for mechanism in items:
        blocked = solely.get(mechanism, [])
        intervention = INTERVENTIONS.get(mechanism)
        entry = {
            "addressable_items": items[mechanism],
            "items_with_mass": with_mass[mechanism],
            "meals_blocked_solely": len(blocked),
        }
        if intervention is None:
            entry["measured_recovered_meals"] = UNMEASURED
            entry["why_unmeasured"] = (
                "no executable counterfactual: the tranche's deliverable "
                "cannot be supplied from concrete evidence, so its recovery "
                "is unknown rather than zero")
        else:
            recovered = not_recovered = unmeasured = 0
            for key in blocked:
                # ⛔⛔ THE REAL PREDICATE JUDGES RECOVERY. The selector's
                # `authoritative` flag is an INPUT to `decide()`, not a verdict:
                # treating it as one would recreate the predicate here and stop
                # tracking it the moment another branch changed.
                # ⭐ SYNC OR ASYNC, BECAUSE THE TRANCHES DIFFER. The memory
                # counterfactual is pure and needs no I/O; the artifact
                # extension has to reach USDA. Awaiting only what is awaitable
                # keeps the pure one pure rather than making every
                # counterfactual pay for the one that needs a network.
                updated = []
                for r in declining_meals[key]:
                    got = intervention(item=r["item"], facts=r["facts"],
                                       memory_per100g=r.get("memory_per100g"))
                    if inspect.isawaitable(got):
                        got = await got
                    updated.append(got)
                # ⛔⛔⛔ A DEFINITE NO OUTRANKS AN UNKNOWN *(Danny, review of
                # `d8113d5`)*. This asked `any(unsimulatable)` FIRST, so a meal
                # holding one unsimulatable item AND one simulated item that
                # still declines was filed UNMEASURED — throwing away a settled
                # answer. The simulated item blocks the meal on its own,
                # whatever the other would have done, so the outcome is KNOWN.
                # Ordering it the other way inflates the unknown column and
                # shrinks the evaluable denominator, making a tranche look less
                # measurable than it is.
                simulated = [u for u in updated if u is not None]
                if any(not isinstance(decide(u), Supported) for u in simulated):
                    not_recovered += 1
                elif len(simulated) != len(updated):
                    unmeasured += 1
                else:
                    recovered += 1
            entry["measured_recovered_meals"] = recovered
            # ⭐ THE DENOMINATOR IS REPORTED, NOT IMPLIED. "0 recovered
            # (43 unsimulatable)" leaves "zero out of what" to the reader, and
            # the two available readings differ by a factor of forty.
            entry["evaluable_meals"] = recovered + not_recovered
            entry["meals_unmeasured"] = unmeasured
        out[mechanism] = entry

    out["MULTIPLE_BLOCKERS"] = {
        "meals": multiple,
        "EXCLUDED_FROM_RANKING": "declining items disagree, so no single "
                                 "tranche recovers the meal and no sole-cause "
                                 "attribution is available",
    }
    return out


# ══ M1 — THE MECHANISM OWNERSHIP CANNOT SEE ═══════════════════════════════
#
# ⛔⛔ A POISONED MEMORY ROW IS SUPPORTED AND WRONG *(found in production
# 2026-08-18, user 26)*. "Grilled chicken breast, 10 oz" settled canonically at
# 383 kcal / 37 g CARBS — chicken has none. The P17f receipt made it one query
# to diagnose: rung=memory, evidence fdc 1941501, and that user_food_matches row
# (cached 06-28) holds 135 kcal / 13.2 C per 100 g. Canonical faithfully reused
# a bad memory row, and every downstream number was correct RELATIVE TO IT.
#
# ⭐ NEITHER OWNERSHIP NOR THE P17 REMEASURE CAN SEE THIS. `decide()` supports a
# memory row on EXISTENCE; ownership = routing x support; so a wrong memory row
# is counted as a WIN. P16's attribution runs only over DECLINING items — a
# supported meal never enters it. This is a fourth memory mechanism beside the
# three P16 names, and it needs its own pass, over the SUPPORTED meals.
#
# ⛔ THE PREDICATE IS EVIDENCE-SHAPED, NOT A FOOD-NAME LIST. The zero-rule
# forbids name branches and it is right; "chicken has no carbs" is a hand list.
# The test is SAME IDENTITY, TWO SOURCES: does the memory row for entity E
# disagree materially with the committed artifact's evidence for entity E? No
# taxonomy, no category — the artifact's own per-100g profile is the reference,
# and where the artifact has no evidence for E the row is UNJUDGEABLE, reported
# as such rather than passed.

#: Disagreement tolerances, per 100 g, for the same identity. Deliberately
#: coarse: a memory row 20% off the artifact on calories is a rounding/prep
#: difference; 40 g of carbs where the artifact says 0.5 is a different food.
_MEMORY_DIVERGENCE = {"calories": (0.35, 40.0),   # (relative, absolute floor)
                      "carbs": (0.50, 8.0),
                      "protein": (0.40, 8.0),
                      "fat": (0.50, 6.0)}


def memory_row_diverges(memory: dict, artifact: dict) -> tuple:
    """(diverges: bool, worst_field, detail). PURE.

    A field diverges when |memory - artifact| exceeds BOTH the relative and
    the absolute tolerance — relative alone flags 0.5 vs 1.2 g carbs; absolute
    alone flags nothing on high-calorie foods. Any one field diverging marks
    the row: a chicken breast with the right calories and 13 g of carbs is
    still not chicken.
    """
    worst = None
    for field, (rel, floor) in _MEMORY_DIVERGENCE.items():
        m = memory.get(field)
        a = artifact.get(field)
        if m is None or a is None:
            continue
        gap = abs(float(m) - float(a))
        base = max(abs(float(a)), 1.0)
        if gap > floor and gap / base > rel:
            score = gap / base
            if worst is None or score > worst[1]:
                worst = (field, score, float(m), float(a))
    if worst is None:
        return False, "", {}
    field, score, m, a = worst
    return True, field, {"field": field, "memory": m, "artifact": a,
                         "ratio": round(score, 2)}


async def audit_supported_memory(db, *, meals: dict, verdicts: dict,
                                 structured: list, chat_meals: int) -> dict:
    """Every SUPPORTED structured meal whose items were priced from MEMORY:
    is the memory row consistent with the artifact's own evidence for the
    same identity? Reports meals that would have been supported-and-wrong."""
    from core.canonical_pricing import _ranker_query, _from_artifact
    from core.canonical_pricing_inputs import _memory
    from core.general_settlement import Supported, decide, look
    from skills.nutrition.pricing_artifact import evidence_for, split_identity

    denominator = max(int(chat_meals), 1)
    supported = [k for k in structured if isinstance(verdicts.get(k), Supported)]
    memory_priced_meals = 0
    unjudgeable_meals = 0
    diverging_meals = []
    examples = []
    for key in supported:
        meal = meals[key]
        meal_memory = False
        meal_unjudgeable = False
        meal_diverges = None
        for item in meal["items"]:
            facts = await look(db, user_id=int(meal["user_id"]), item=item)
            verdict = decide(facts)
            if not (isinstance(verdict, Supported)
                    and verdict.expected_source == "memory"):
                continue
            meal_memory = True
            identity = str(item.get("food_name") or "")
            entity, prep = split_identity(identity)
            try:
                memory = await _memory(db, int(meal["user_id"]), identity, "")
            except Exception:                            # noqa: BLE001
                memory = None
            per100 = dict(getattr(memory, "per100g", None) or {}) if memory else {}
            art = evidence_for(entity, prep)
            chosen = _from_artifact(art, query=_ranker_query(entity, prep)) if art else None
            if not per100 or not chosen:
                meal_unjudgeable = True
                continue
            _profile, _rung, _eid, raw_art, _basis, _measures = chosen
            diverges, field, detail = memory_row_diverges(per100, raw_art or {})
            if diverges:
                meal_diverges = {"identity": identity[:48], **detail,
                                 "memory_source_id": getattr(memory, "source_id", "")}
                break
        if not meal_memory:
            continue
        memory_priced_meals += 1
        if meal_diverges:
            diverging_meals.append(key)
            if len(examples) < 8:
                examples.append(meal_diverges)
        elif meal_unjudgeable:
            unjudgeable_meals += 1
    return {
        "mechanism": "MEMORY:row_present_but_implausible",
        "supported_structured_meals": len(supported),
        "memory_priced_supported_meals": memory_priced_meals,
        "diverging_meals": len(diverging_meals),
        "ownership_points_that_are_WRONG": round(
            100.0 * len(diverging_meals) / denominator, 1),
        "unjudgeable_meals_no_artifact_reference": unjudgeable_meals,
        "examples": examples,
        "predicate": "same identity, two sources — the memory row vs the "
                     "committed artifact's own per-100g evidence for that "
                     "entity; a row diverging past BOTH a relative and an "
                     "absolute tolerance on any macro is implausible. No "
                     "food-name list.",
        "reading": "These meals are COUNTED AS OWNED by C and are priced from "
                   "a memory row the artifact contradicts. Ownership cannot see "
                   "them; the P17 remeasure inherits them; a canary would find "
                   "them. Rank against Δ(M|P17) like any other mechanism.",
    }


def enable_artifact_extension() -> None:
    """Arm the ONE networked counterfactual. Explicit, and off by default.

    ⛔⛔ THE ROUTINE INSTRUMENT MUST STAY PURE. Every other intervention is
    database-free and deterministic; this one reaches USDA and a resolver, so a
    default-on version would make the ranking depend on two providers being up
    and would quietly change what "UNMEASURED" means between runs. Armed only
    by `--artifact-extension`, and only for the tranche it was authorized for.
    """
    INTERVENTIONS["NO_LOCAL_EVIDENCE"] = artifact_extension_counterfactual


async def attribute_misses(db, *, meals: dict, verdicts: dict,
                           structured: list, chat_meals: int) -> dict:
    """Every DECLINING item of every declining structured meal, by mechanism,
    then the THREE quantities per mechanism.

    ⛔⛔ THE ROLLUP NO LONGER PUBLISHES AN OWNERSHIP-POINT COLUMN. The published
    11.3% is FROZEN historical evidence measured on `p16b_0817` at a named
    predicate commit; deriving fresh percentages here from a recovery count
    would produce a second, differently-computed ownership number that invites
    exactly the comparison it cannot support. Recovered MEALS are reported as
    meals, and the ownership rate stays where it was measured.
    """
    from core.canonical_pricing_inputs import _memory
    from core.general_settlement import Supported, decide, look

    counts: collections.Counter = collections.Counter()
    tagged: collections.Counter = collections.Counter()
    examples: dict = {}
    items_seen = 0
    #: meal key -> the declining items of that meal, with facts, item and
    #: mechanism. Built ONCE: the rollup must not re-select a population or
    #: re-ask the predicate, or it could not be compared with the numbers above.
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
            mechanism = mechanism_for(facts)
            counts[mechanism] += 1
            if _non_latin(str(item.get("food_name") or "")):
                tagged[mechanism] += 1
            examples.setdefault(mechanism, str(item.get("food_name") or "")[:48])
            # ⭐ THE USER'S OWN ROW, READ ONCE HERE. The counterfactual stays
            # PURE and database-free: a simulation that opened its own reads
            # could disagree with the facts it is simulating against.
            memory_per100g = None
            if mechanism == "MEMORY_WINNER_NONAUTHORITATIVE":
                try:
                    row = await _memory(db, int(meal["user_id"]),
                                        str(item.get("food_name") or ""), "")
                    memory_per100g = dict(getattr(row, "per100g", None) or {})
                except Exception:                        # noqa: BLE001
                    memory_per100g = None
            records.append({"facts": facts, "mechanism": mechanism,
                            "item": item, "memory_per100g": memory_per100g})
        if records:
            declining_meals[key] = records

    ranked = await rank_mechanisms(db, declining_meals=declining_meals)

    # ⭐ THE PARTITION CHECKS ITSELF. Every declining item carries exactly one
    # mechanism, so the addressable populations must sum to the item count. A
    # disagreement means a leaf was added without a home and its tranche is
    # going unranked — the silence this repair exists to make impossible.
    summed = sum(e["addressable_items"] for k, e in ranked.items()
                 if k != "MULTIPLE_BLOCKERS")
    partition_ok = (summed == items_seen)

    return {
        "declining_items": items_seen,
        "by_mechanism": dict(counts.most_common()),
        "non_latin_within_each_mechanism": dict(tagged.most_common()),
        "one_example_each": examples,
        "reading": ("Rank tranches by MEASURED RECOVERED MEALS. An UNMEASURED "
                    "recovery is not a zero and not the sole-blocked count — "
                    "it is the absence of a measurement, and a tranche cannot "
                    "be ranked on it. `non_latin_within_each_mechanism` "
                    "answers 'is this a non-English problem?' WITHOUT letting "
                    "language become the bucket."),
        "artifact_extension": _extension_report(
            addressable=ranked.get("NO_LOCAL_EVIDENCE", {}).get(
                "addressable_items"),
            sole_blocked=ranked.get("NO_LOCAL_EVIDENCE", {}).get(
                "meals_blocked_solely")),
        "meal_rollup": {
            "declining_meals": len(declining_meals),
            "ordinary_food_chat_meals_DENOMINATOR": max(int(chat_meals), 1),
            "by_mechanism": ranked,
            "partition_holds": partition_ok,
            "partition_check": (
                f"{summed} addressable items across mechanisms vs "
                f"{items_seen} declining items"),
            "ownership_rate": (
                "NOT recomputed here. The published 11.3% is frozen historical "
                "evidence on p16b_0817 at its named predicate commit."),
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
    roll = (a.get("meal_rollup") or {})
    if roll.get("by_mechanism"):
        out.append("\n    RANKED BY MEASURED RECOVERED MEALS")
        out.append(f"      {roll['declining_meals']} declining meals over "
                   f"{roll['ordinary_food_chat_meals_DENOMINATOR']} ordinary "
                   f"food-chat meals\n")
        out.append(f"      {'MECHANISM':<38}{'ITEMS':>6}{'w/ mass':>9}"
                   f"{'SOLE-BLOCKED':>14}{'RECOVERED (measured)':>34}")
        def _key(kv):
            v = kv[1].get("measured_recovered_meals")
            return (0 if isinstance(v, int) else -1, v if isinstance(v, int) else 0)
        for mech, e in sorted(roll["by_mechanism"].items(),
                              key=_key, reverse=True):
            if mech == "MULTIPLE_BLOCKERS":
                continue
            rec = e.get("measured_recovered_meals")
            if isinstance(rec, int):
                shown = (f"{rec} / {e.get('evaluable_meals', 0)} evaluable"
                         + (f"  · {e['meals_unmeasured']} UNMEASURED"
                            if e.get("meals_unmeasured") else ""))
            else:
                shown = str(rec)
            out.append(f"      {mech:<38}{e['addressable_items']:>6}"
                       f"{e['items_with_mass']:>9}"
                       f"{e['meals_blocked_solely']:>14}{shown:>34}")
        mb = roll["by_mechanism"].get("MULTIPLE_BLOCKERS") or {}
        out.append(f"\n      MULTIPLE_BLOCKERS: {mb.get('meals', 0)} meals — "
                   f"EXCLUDED from ranking (no sole-cause attribution)")
        out.append(f"      partition holds: {roll.get('partition_holds')} "
                   f"({roll.get('partition_check','')})")
        out.append(f"      ⛔ UNMEASURED is not zero and not the sole-blocked "
                   f"count — a tranche cannot be ranked on it")
        out.append(f"      {roll.get('ownership_rate','')}")
    ext = (a.get("artifact_extension") or None)
    if ext and ext.get("PUBLISHED") is False:
        out.append("\n    ⛔ ARTIFACT EXTENSION — WITHHELD, NOT MEASURED")
        out.append(f"      {ext['why_withheld']}")
        out.append(f"      {ext['items_attempted_before_withholding']} item(s) "
                   f"had been attempted when the run was withheld; no bucket "
                   f"from this run is publishable")
        ext = None
    if ext:
        out.append(f"\n    ARTIFACT EXTENSION — {ext['release']}")
        out.append(f"      population: {ext.get('addressable_items')} "
                   f"addressable items · "
                   f"{ext['items_attempted']} entering this counterfactual "
                   f"(in {ext.get('sole_blocked_meals_entering_this_counterfactual')} "
                   f"sole-blocked meals) · "
                   f"{ext['distinct_identities']} distinct identities")
        nl = ext.get("non_latin_within_each_outcome") or {}
        out.append(f"      {'OUTCOME':<44}{'N':>6}{'non-latin':>11}")
        for outcome, n in ext["by_outcome"].items():
            out.append(f"      {outcome:<44}{n:>6}{nl.get(outcome, 0):>11}")
        out.append(f"      {'(of which non-Latin identities)':<44}"
                   f"{ext.get('non_latin_items', 0):>6}")
        if ext["buckets_not_observed"]:
            out.append(f"      (not observed: "
                       f"{', '.join(ext['buckets_not_observed'])})")
        out.append(f"      scope: {ext['scope']}")
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
    parser.add_argument("--artifact-extension", action="store_true",
                        help="arm the READ-ONLY USDA FDC 15.3 artifact-"
                             "extension counterfactual over NO_LOCAL_EVIDENCE "
                             "(reaches USDA and the resolver; off by default)")
    parser.add_argument("--population", metavar="NAME",
                        help="measure EXACTLY a previously frozen population "
                             "instead of a rolling window")
    args = parser.parse_args()

    if args.artifact_extension:
        pre = asyncio.run(artifact_extension_preflight())
        print("  PREFLIGHT  usda:     " + str(pre["usda"]))
        print("  PREFLIGHT  resolver: " + str(pre["resolver"]))
        if not pre["ok"]:
            # ⛔ FAIL FAST. Spending the whole budget to discover the same
            # outage 152 times produces a table of false findings, which is
            # strictly worse than producing nothing.
            EXTENSION_RUN_OUTAGE["outage"] = (
                "PREFLIGHT FAILED — " + pre["reason"])
            print("\n  ⛔ ARTIFACT EXTENSION WITHHELD: " + pre["reason"])
            print("     The measurement is NOT run. No bucket from this "
                  "invocation is publishable.\n")
        else:
            enable_artifact_extension()
            print("  ⚠ artifact-extension counterfactual ARMED — this run "
                  "reaches USDA and the resolver")

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
