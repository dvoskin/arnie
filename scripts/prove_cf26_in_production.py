"""CF26 TARGETED PRODUCTION PROOF — the two halves Danny named.

    1. pre-settlement cache writes create NO nutrition
    2. canonical settlement CAN still create trusted memory
    3. a trusted row re-reads successfully

⚠ READ-ONLY. Run AFTER `63d926a` is live and after at least one food has been
logged on the instrumented build.

⛔⛔ EVERY CHECK REPORTS PASS / FAIL / **UNPROVEN**, and UNPROVEN IS NOT A
PASS. It means the run could not find the evidence to judge — the state a
green tick must never be printed over. Half 1 in particular is UNPROVEN, not
PASS, when no row was created after the cutoff: "nothing was written wrongly"
and "nothing was written" are different claims.

    ARNIE_PROD_DATABASE_URL=... ../arnie/.venv/bin/python -m \
        scripts.prove_cf26_in_production --user 26 --since-minutes 60
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
    ap.add_argument("--since-minutes", type=int, default=60)
    args = ap.parse_args()

    url = os.getenv("ARNIE_PROD_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("no ARNIE_PROD_DATABASE_URL")
    c = psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://"))
    mins = args.since_minutes

    # ══ HALF 1 — pre-settlement writes create no nutrition ═══════════════
    rows = c.execute(
        "SELECT id, name_norm, display_name, fdc_id, serving_text, times_used, "
        "       cal_100, protein_100, carbs_100, fat_100, fiber_100, "
        "       sugar_100, sodium_100, micros_100_json, settled_by_operation_id "
        "FROM user_food_matches WHERE user_id = %s "
        "AND created_at > now() - make_interval(mins => %s) "
        "ORDER BY id", (args.user, mins)).fetchall()

    fresh = [r for r in rows if not r[14]]        # no linkage = public writer
    if not fresh:
        check(UNPROVEN, "pre-settlement writes create no nutrition",
              f"no unlinked row created for user {args.user} in the last "
              f"{mins} min — log a food whose name has no cached row yet. "
              f"'nothing written wrongly' is not 'nothing written'")
    else:
        dirty = [r for r in fresh
                 if any(v is not None for v in r[6:14])]
        check(FAIL if dirty else PASS,
              "pre-settlement writes create no nutrition",
              (f"{len(dirty)} of {len(fresh)} public-writer row(s) carry "
               f"nutrition: " + ", ".join(f"row {r[0]} {r[1]!r}" for r in dirty))
              if dirty else
              (f"{len(fresh)} public-writer row(s), all nutrition NULL: "
               + ", ".join(f"row {r[0]} {r[1]!r}" for r in fresh[:4])))
        # ⭐ the negative invariant: fail-closed is not fail-always
        kept = [r for r in fresh if r[2] and (r[5] or 0) >= 1]
        check(PASS if kept else FAIL,
              "identity and usage still cached",
              f"{len(kept)} of {len(fresh)} carry a display name and usage "
              f"count; fdc_id present on "
              f"{sum(1 for r in fresh if r[3])}, serving on "
              f"{sum(1 for r in fresh if r[4])}")

    # ══ HALF 2 — settlement can still create trusted memory ══════════════
    linked = c.execute(
        "SELECT m.id, m.name_norm, m.cal_100, m.settled_by_operation_id, "
        "       m.settled_basis, m.settled_evidence_id, m.micros_100_json "
        "FROM user_food_matches m WHERE m.user_id = %s "
        "AND m.settled_by_operation_id IS NOT NULL "
        "ORDER BY m.settled_at DESC NULLS LAST LIMIT 5",
        (args.user,)).fetchall()
    if not linked:
        check(UNPROVEN, "canonical settlement creates trusted memory",
              "no row carries settlement linkage — log a meal canonical "
              "settlement can OWN (see the settleable-food sweep)")
    else:
        top = linked[0]
        resolved = c.execute(
            "SELECT commit_id, status FROM meal_commits WHERE operation_id = %s",
            (top[3],)).fetchone()
        check(PASS if resolved else FAIL,
              "settlement linkage resolves to a real commit",
              f"row {top[0]} {top[1]!r} -> {top[3]} -> "
              + (f"commit {resolved[0]} ({resolved[1]})" if resolved
                 else "NOTHING — a dangling id is as forgeable as a magic word"))
        check(PASS if (top[2] is not None and top[4] and top[5]) else FAIL,
              "the trusted row carries nutrition, basis and evidence",
              f"cal_100={top[2]} basis={top[4]!r} evidence={top[5]!r}")

        # ══ HALF 3 — a trusted row re-reads successfully ═════════════════
        import asyncio

        from db.database import make_engine
        from db.queries import memory_nutrition_evidence

        async def _reread(row_id: int):
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import async_sessionmaker

            from db.models import UserFoodMatch
            eng = make_engine(url.replace("postgresql://",
                                          "postgresql+psycopg://"))
            try:
                async with async_sessionmaker(eng)() as db:
                    r = (await db.execute(select(UserFoodMatch).where(
                        UserFoodMatch.id == row_id))).scalar_one()
                    return await memory_nutrition_evidence(
                        db, r, consumer="cf26_proof", stage="verification")
            finally:
                await eng.dispose()

        payload = asyncio.run(_reread(top[0]))
        check(PASS if payload else FAIL,
              "a trusted row re-reads as pricing evidence",
              f"memory_nutrition_evidence -> "
              + (f"{payload.get('calories')} kcal/100g" if payload
                 else "None — the row cannot be used by the rung that needs it"))

    # ══ fleet-wide: nothing minted trust it did not earn ═════════════════
    orphans = c.execute(
        "SELECT count(*) FROM user_food_matches m WHERE "
        "m.settled_by_operation_id IS NOT NULL AND NOT EXISTS ("
        "  SELECT 1 FROM meal_commits mc "
        "  WHERE mc.operation_id = m.settled_by_operation_id)").fetchone()[0]
    check(PASS if orphans == 0 else FAIL,
          "no row carries linkage that resolves to nothing",
          f"{orphans} fleet-wide")

    return _render()


def _render() -> int:
    print("\n  CF26 / CF24 TARGETED PRODUCTION PROOF\n")
    for verdict, name, detail in _results:
        print(f"    [{verdict}] {name}")
        if detail:
            print(f"              {detail}")
    bad = [v for v, _, _ in _results if v != PASS]
    print()
    if bad:
        print(f"    ⛔ {sum(1 for v in bad if v == FAIL)} FAIL, "
              f"{sum(1 for v in bad if v == UNPROVEN)} UNPROVEN. "
              f"UNPROVEN IS NOT A PASS.\n")
        return 1
    print(f"    ⭐ all {len(_results)} checks passed\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
