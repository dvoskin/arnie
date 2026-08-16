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
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

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
CANONICAL_ROUTE_PREFIXES = ("structured_food", "canonical")
NOT_A_CHAT_TURN_PREFIXES = ("quick_log", "dashboard")
LEGACY_PREFIXES = ("legacy",)


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


async def measure(*, days: int, limit: int) -> dict:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.general_settlement import Supported, coverage_for
    from db.database import make_engine

    engine = make_engine(_database_url().replace("postgresql://",
                                                 "postgresql+psycopg://"))
    meals: dict = collections.defaultdict(
        lambda: {"items": [], "sources": set(), "user_id": None})
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
                "WHERE fe.timestamp > now() - make_interval(days => :days)"
            ), {"days": days})).one()
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
                "SELECT le.turn_id, le.source, fe.parsed_food_name, "
                "       fe.quantity, dl.user_id "
                "FROM food_entries fe "
                "JOIN daily_logs dl ON dl.id = fe.daily_log_id "
                "JOIN ledger_events le ON le.entry_id = fe.id "
                "     AND le.event_type = 'created' "
                "WHERE fe.timestamp > now() - make_interval(days => :days) "
                "ORDER BY fe.timestamp DESC LIMIT :limit"
            ), {"days": days, "limit": limit})).all()

            turnless: list = []
            for turn_id, source, name, quantity, user_id in rows:
                # ⛔ A TURNLESS ROW GETS ITS OWN KEY, NEVER A SHARED ONE.
                # `__no_turn__:{user_id}` collapsed every turnless row for one
                # user across the whole window into ONE giant meal — which the
                # predicate would then decline wholesale on a single missing
                # item. Measured here at 0 rows (406 of 406 carry a turn id),
                # and reported rather than assumed.
                if turn_id:
                    key = str(turn_id)
                else:
                    turnless.append(int(user_id))
                    key = f"__no_turn__:{user_id}:{len(turnless)}"
                meal = meals[key]
                meal["user_id"] = user_id
                meal["sources"].add(str(source or ""))
                meal["items"].append({"food_name": str(name or ""),
                                      "quantity": str(quantity or "")})

            verdicts = {}
            for key, meal in meals.items():
                verdicts[key] = await coverage_for(
                    db, user_id=int(meal["user_id"]), items=meal["items"])
    finally:
        await engine.dispose()

    structured, legacy, not_chat, unknown = [], [], [], []
    for key, meal in meals.items():
        sources = {s for s in meal["sources"] if s}
        if any(s.startswith(NOT_A_CHAT_TURN_PREFIXES) for s in sources):
            not_chat.append(key)
        elif any(s.startswith(CANONICAL_ROUTE_PREFIXES) for s in sources):
            structured.append(key)
        elif any(s.startswith(LEGACY_PREFIXES) for s in sources):
            legacy.append(key)
        else:
            # ⛔ NOT SILENTLY BINNED. An unrecognised writer is a finding — the
            # binary this replaced would have called it legacy and reported a
            # routing failure that may not exist.
            unknown.append(key)

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
    expected = collections.Counter(
        getattr(verdicts[k], "expected_source", "")
        for k in supported_structured)

    return {
        "window_days": days,
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
        "why_structured_meals_decline": dict(declines.most_common()),
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


def render(report: dict) -> str:
    if report.get("PUBLISHED") is False:
        return ("\n  P11 — SETTLEMENT COVERAGE\n\n    ⛔⛔ WITHHELD\n"
                f"    {report['why_withheld']}\n"
                f"    {report['rows_groupable']} of {report['rows_in_window']} "
                f"rows groupable over {report['window_days']} days\n")
    out = ["\n  P11 — SETTLEMENT COVERAGE, AT MEAL LEVEL\n",
           f"    {report['rows']} rows in {report['meals']} meals over "
           f"{report['window_days']} days\n"]
    b = report["B_support_rate_within_structured_pct"]
    out.append(f"    A  routing rate    {report['A_routing_rate_pct']:5.1f}%   "
               f"structured-route / ORDINARY FOOD-CHAT meals")
    out.append(f"    B  support rate    "
               f"{(f'{b:5.1f}%' if b is not None else '    — ')}   "
               f"supported / STRUCTURED   <- flattering")
    out.append(f"    C  OWNERSHIP RATE  {report['C_ownership_rate_pct']:5.1f}%"
               f"   supported / ORDINARY FOOD-CHAT meals  =  A x B")
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
    out.append("\n    LIMITS")
    for limit in report["limits"]:
        out.append(f"      · {limit}")
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    report = asyncio.run(measure(days=args.days, limit=args.limit))
    print(render(report))
    if args.write:
        path = (pathlib.Path(__file__).resolve().parents[1] / "data"
                / "corpus" / "settlement_coverage.json")
        path.write_text(json.dumps(report, indent=1, ensure_ascii=False))
        print(f"  recorded -> {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
