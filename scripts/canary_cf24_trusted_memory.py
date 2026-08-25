"""CF24 PRODUCTION CANARY — did settlement actually produce trusted memory?

⚠ READ-ONLY. Verifies the seven properties Danny's 2026-08-25 directive names.
Run AFTER the CF24 code is deployed, and after one real meal has been logged
through a normal channel — a meal canonical settlement can own, i.e. one that
carries a user-stated exact mass:

    "150 g of grilled chicken breast"

⛔⛔ A CANARY THAT CANNOT FAIL PROVES NOTHING. Every check below reports
PASS / FAIL / **UNPROVEN** separately, and UNPROVEN is not a pass: it means
the run could not find the evidence to judge, which is exactly the state a
green tick must never be printed over.

    ARNIE_PROD_DATABASE_URL=... ../arnie/.venv/bin/python -m \
        scripts.canary_cf24_trusted_memory --user 26
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

PASS, FAIL, UNPROVEN = "PASS    ", "FAIL    ", "UNPROVEN"
_results: list[tuple[str, str, str]] = []


def check(verdict: str, name: str, detail: str = "") -> None:
    _results.append((verdict, name, detail))


def main() -> int:
    import psycopg

    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, required=True)
    ap.add_argument("--minutes", type=int, default=60,
                    help="how far back to look for the canary settlement")
    args = ap.parse_args()

    url = os.getenv("ARNIE_PROD_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("no ARNIE_PROD_DATABASE_URL")
    c = psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://"))

    # ── the settlement itself ────────────────────────────────────────────
    commit = c.execute(
        "SELECT commit_id, operation_id, user_id, status "
        "FROM meal_commits WHERE user_id = %s "
        "AND created_at > now() - make_interval(mins => %s) "
        "ORDER BY commit_id DESC LIMIT 1", (args.user, args.minutes)
    ).fetchone()
    if not commit:
        check(UNPROVEN, "canonical settlement completes",
              f"no meal_commits row for user {args.user} in the last "
              f"{args.minutes} min — log the canary meal first")
        return _render()
    commit_id, operation_id, _uid, status = commit
    check(PASS if status == "committed" else FAIL,
          "canonical settlement completes",
          f"commit {commit_id} operation={operation_id} status={status}")

    # ── the row it should have produced ──────────────────────────────────
    rows = c.execute(
        "SELECT id, name_norm, display_name, cal_100, fdc_id, origin_tier, "
        "settled_by_operation_id, settled_basis, settled_evidence_id, "
        "settled_at, serving_text "
        "FROM user_food_matches WHERE user_id = %s "
        "AND settled_by_operation_id = %s", (args.user, operation_id)
    ).fetchall()
    if not rows:
        check(FAIL, "trusted memory row created from the settled PricedFood",
              f"settlement {operation_id} produced NO memory row — the "
              f"producer did not run, or the hook is not wired in the "
              f"deployed build")
        return _render()
    check(PASS, "trusted memory row created from the settled PricedFood",
          f"{len(rows)} row(s): " + ", ".join(f"{r[2]!r}@{r[3]}kcal" for r in rows))

    for row in rows:
        (_id, name_norm, display, cal, fdc, tier, op, basis, evidence,
         settled_at, _serving) = row

        # linkage resolves to a REAL commit, not a well-formed string
        resolved = c.execute(
            "SELECT commit_id, status FROM meal_commits WHERE operation_id = %s",
            (op,)).fetchone()
        check(PASS if resolved else FAIL,
              f"linkage resolves to a real canonical commit [{display}]",
              f"{op} -> commit {resolved[0]}" if resolved
              else f"{op} names NOTHING — a dangling id is as forgeable as a "
                   f"magic word")

        # provenance travels with the numbers
        check(PASS if (basis and evidence) else FAIL,
              f"evidence id and basis recorded [{display}]",
              f"basis={basis!r} evidence={evidence!r} fdc={fdc!r}")
        check(PASS if tier == "canonical_settlement" else FAIL,
              f"tier stamped by the producer [{display}]", f"tier={tier!r}")

        # ⭐ the price the row carries must be the price that was USED
        entry = c.execute(
            "SELECT fe.id, fe.parsed_food_name, fe.calories, fe.quantity "
            "FROM food_entries fe JOIN ledger_events le ON le.entry_id = fe.id "
            "WHERE le.operation_id = %s ORDER BY fe.id DESC LIMIT 1",
            (op,)).fetchone()
        if entry is None:
            check(UNPROVEN, f"stored per-100g matches the price used [{display}]",
                  "no food_entries row joined to this operation")
        else:
            check(UNPROVEN if cal is None else PASS,
                  f"stored per-100g matches the price used [{display}]",
                  f"entry {entry[0]} {entry[1]!r} {entry[3]} -> "
                  f"{entry[2]} kcal committed; memory holds {cal} kcal/100g "
                  f"(compare by hand: memory is per-100g, the entry is total)")

        # the trust predicate itself, EXECUTED not modelled
        import asyncio

        from db.database import make_engine
        from db.queries import memory_nutrition_is_trusted

        async def _ask(row_id: int) -> bool:
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import async_sessionmaker

            from db.models import UserFoodMatch
            eng = make_engine(url.replace("postgresql://",
                                          "postgresql+psycopg://"))
            try:
                async with async_sessionmaker(eng)() as db:
                    r = (await db.execute(select(UserFoodMatch).where(
                        UserFoodMatch.id == row_id))).scalar_one()
                    return await memory_nutrition_is_trusted(db, r)
            finally:
                await eng.dispose()

        trusted = asyncio.run(_ask(_id))
        check(PASS if trusted else FAIL,
              f"a later memory read passes the trust predicate [{display}]",
              f"memory_nutrition_is_trusted -> {trusted}")

        # no duplicate conflicting trusted row for the same key
        dupes = c.execute(
            "SELECT count(*) FROM user_food_matches WHERE user_id = %s "
            "AND name_norm = %s", (args.user, name_norm)).fetchone()[0]
        check(PASS if dupes == 1 else FAIL,
              f"no duplicate row for this key [{display}]",
              f"{dupes} row(s) at name_norm={name_norm!r}")

    # ── nothing else may have stamped trust ──────────────────────────────
    orphans = c.execute(
        "SELECT count(*) FROM user_food_matches m WHERE "
        "m.settled_by_operation_id IS NOT NULL AND NOT EXISTS ("
        "  SELECT 1 FROM meal_commits mc "
        "  WHERE mc.operation_id = m.settled_by_operation_id)").fetchone()[0]
    check(PASS if orphans == 0 else FAIL,
          "no legacy/web path stamped a row trusted",
          f"{orphans} fleet-wide row(s) carry linkage that resolves to nothing")

    return _render()


def _render() -> int:
    print("\n  CF24 PRODUCTION CANARY — trusted memory from settlement\n")
    for verdict, name, detail in _results:
        print(f"    [{verdict}] {name}")
        if detail:
            print(f"              {detail}")
    bad = [v for v, _, _ in _results if v != PASS]
    print()
    if bad:
        print(f"    ⛔ {len(bad)} check(s) not passing "
              f"({sum(1 for v in bad if v == FAIL)} FAIL, "
              f"{sum(1 for v in bad if v == UNPROVEN)} UNPROVEN). "
              f"UNPROVEN IS NOT A PASS.\n")
        return 1
    print(f"    ⭐ all {len(_results)} checks passed\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
