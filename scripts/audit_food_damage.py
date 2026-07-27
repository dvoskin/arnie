"""READ-ONLY: is the account corrupted, or are the numbers just wrong?

Those are different questions and the difference decides what to do about it. This
script separates them, because "my logs are acting up" can mean either and the
fixes have nothing in common.

    CORRUPTION      the stored day disagrees with the rows it is made of.
                    `daily_logs.total_calories` != SUM of its `food_entries`.
                    Nothing can be trusted until it is rebuilt, and a rebuild
                    is safe because the entries are the source of truth.

    BAD VALUES      the day agrees with its rows perfectly. The rows are just
                    wrong, because something upstream computed a wrong number
                    and wrote it faithfully. Nothing is corrupt. The history
                    is simply not true, and only re-resolving the affected
                    entries fixes it.

Everything here is a SELECT. It writes nothing, and no message bodies or food
names leave the database except in the per-row samples, which are capped.

Usage:
    python scripts/audit_food_damage.py                 # last 30 days, all users
    python scripts/audit_food_damage.py --days 7
    python scripts/audit_food_damage.py --user 1
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

SAMPLE = 12


def _prod_url() -> str:
    """DATABASE_URL from the environment, else the sibling .env — same
    resolution order the other read-only prod scripts use."""
    url = os.getenv("DATABASE_URL", "")
    if not url:
        for candidate in (Path(__file__).resolve().parent.parent / ".env",
                          Path(__file__).resolve().parent.parent.parent
                          / "arnie" / ".env"):
            if candidate.exists():
                for line in candidate.read_text().splitlines():
                    if line.startswith("DATABASE_URL="):
                        url = line.split("=", 1)[1].strip()
                        break
            if url:
                break
    if not url:
        sys.exit("No DATABASE_URL in the environment or .env")
    # Raw psycopg, not the async engine: it hangs against prod.
    return re.sub(r"^[a-z]+\+[a-z0-9]+://", "postgresql://", url)


def _where(user_id, days):
    clauses, params = ["dl.date >= CURRENT_DATE - %s::int"], [days]
    if user_id is not None:
        clauses.append("dl.user_id = %s")
        params.append(user_id)
    return " AND ".join(clauses), params


def run(user_id, days):
    import psycopg

    where, params = _where(user_id, days)
    out = []
    with psycopg.connect(_prod_url()) as conn, conn.cursor() as cur:

        # ── 1. CORRUPTION: does each day equal the sum of its own rows? ──────
        cur.execute(f"""
            SELECT dl.id, dl.user_id, dl.date,
                   dl.total_calories,
                   COALESCE(SUM(fe.calories), 0)::int AS row_sum,
                   COUNT(fe.id)::int AS n
              FROM daily_logs dl
              LEFT JOIN food_entries fe ON fe.daily_log_id = dl.id
             WHERE {where}
             GROUP BY dl.id, dl.user_id, dl.date, dl.total_calories
            HAVING ABS(dl.total_calories - COALESCE(SUM(fe.calories), 0)) > 1
             ORDER BY dl.date DESC
        """, params)
        drift = cur.fetchall()

        # ── 2. the zero-calorie write (butter) ──────────────────────────────
        cur.execute(f"""
            SELECT dl.date, fe.parsed_food_name, fe.quantity,
                   fe.source_type, fe.confidence_score, fe.protein, fe.fats
              FROM food_entries fe
              JOIN daily_logs dl ON dl.id = fe.daily_log_id
             WHERE {where} AND COALESCE(fe.calories, 0) = 0
             ORDER BY dl.date DESC, fe.id DESC
        """, params)
        zeros = cur.fetchall()

        # ── 3. macros that do not reconcile with the calories on the row ────
        # 4/4/9 within 25% or 60 cal. A row outside that was assembled from
        # two sources that disagreed about what the food was.
        cur.execute(f"""
            SELECT dl.date, fe.parsed_food_name, fe.calories,
                   fe.protein, fe.carbs, fe.fats, fe.source_type
              FROM food_entries fe
              JOIN daily_logs dl ON dl.id = fe.daily_log_id
             WHERE {where} AND COALESCE(fe.calories, 0) > 0
               AND ABS((COALESCE(fe.protein,0)*4 + COALESCE(fe.carbs,0)*4
                        + COALESCE(fe.fats,0)*9) - fe.calories)
                   > GREATEST(60, fe.calories * 0.25)
             ORDER BY ABS((COALESCE(fe.protein,0)*4 + COALESCE(fe.carbs,0)*4
                           + COALESCE(fe.fats,0)*9) - fe.calories) DESC
        """, params)
        unreconciled = cur.fetchall()

        # ── 4. the same food written twice within two minutes ───────────────
        # The iOS rapid-fire shape: "chicken" / "and rice" / "for lunch" as
        # three turns became three writes.
        cur.execute(f"""
            SELECT dl.date, fe.parsed_food_name, COUNT(*)::int AS n,
                   MIN(fe.timestamp) AS first_at, MAX(fe.timestamp) AS last_at
              FROM food_entries fe
              JOIN daily_logs dl ON dl.id = fe.daily_log_id
             WHERE {where} AND fe.parsed_food_name IS NOT NULL
             GROUP BY dl.date, fe.parsed_food_name, dl.id
            HAVING COUNT(*) > 1
               AND MAX(fe.timestamp) - MIN(fe.timestamp) < INTERVAL '2 minutes'
             ORDER BY dl.date DESC
        """, params)
        rapid = cur.fetchall()

        # ── 5. a source named over a number it cannot have produced ─────────
        cur.execute(f"""
            SELECT dl.date, fe.parsed_food_name, fe.quantity, fe.source_type
              FROM food_entries fe
              JOIN daily_logs dl ON dl.id = fe.daily_log_id
             WHERE {where} AND COALESCE(fe.calories, 0) = 0
               AND fe.source_type IS NOT NULL
               AND fe.source_type NOT IN ('estimate', 'user')
             ORDER BY dl.date DESC
        """, params)
        misattributed = cur.fetchall()

        cur.execute(f"""
            SELECT COUNT(*)::int FROM food_entries fe
              JOIN daily_logs dl ON dl.id = fe.daily_log_id WHERE {where}
        """, params)
        total_rows = cur.fetchone()[0]

    # ── the verdict ─────────────────────────────────────────────────────────
    w = out.append
    w(f"# Food-log damage report — last {days} days"
      + (f", user {user_id}" if user_id is not None else ", all users"))
    w(f"\n{total_rows} food entries in scope.\n")

    w("## Is the account corrupted?\n")
    if not drift:
        w("**No.** Every daily total equals the sum of its own food entries.")
        w("The database is internally consistent: nothing was lost, nothing")
        w("double-counted, no total drifted from the rows behind it.\n")
    else:
        w(f"**Yes, on {len(drift)} day(s).** The stored total disagrees with")
        w("the rows it is made of. The entries are the source of truth, so")
        w("these days can be safely rebuilt by re-summing them.\n")
        w("| date | stored | sum of rows | delta | rows |")
        w("|---|---|---|---|---|")
        for _id, _uid, date, stored, rows, n in drift[:SAMPLE]:
            # `total_calories` is a Float column and SUM comes back Decimal,
            # so both are coerced before the arithmetic — a `:+d` over the raw
            # values raises, which is how this got caught.
            stored, rows = int(stored or 0), int(rows or 0)
            w(f"| {date} | {stored} | {rows} | {rows - stored:+d} | {n} |")
        if len(drift) > SAMPLE:
            w(f"\n...and {len(drift) - SAMPLE} more.")
        w("")

    w("## Wrong values that were written faithfully\n")
    w("Not corruption. The row is exactly what the pipeline computed; the")
    w("computation was wrong. Only re-resolving these entries fixes them.\n")

    w(f"### Zero-calorie entries — {len(zeros)}")
    if zeros:
        w("\nThe butter shape: the interpreter reported no calories and every")
        w("enrichment branch required `cal > 0`, so the row committed at zero.")
        w("Fixed forward in `a zero is an absence, and butter is a fat` —")
        w("these rows predate it and are still zero.\n")
        w("| date | food | qty | source | protein | fat |")
        w("|---|---|---|---|---|---|")
        for date, food, qty, src, conf, pro, fat in zeros[:SAMPLE]:
            w(f"| {date} | {food} | {qty or ''} | {src or ''} | {pro} | {fat} |")
        if len(zeros) > SAMPLE:
            w(f"\n...and {len(zeros) - SAMPLE} more.")
    else:
        w("\nNone.")

    w(f"\n### Entries whose macros do not reconcile — {len(unreconciled)}")
    if unreconciled:
        w("\n4/4/9 disagrees with the stored calories by more than 25%. A row")
        w("assembled from two sources that disagreed about what the food was.\n")
        w("| date | food | cal | 4/4/9 | P | C | F | source |")
        w("|---|---|---|---|---|---|---|---|")
        for date, food, cal, p, c, f, src in unreconciled[:SAMPLE]:
            implied = (p or 0) * 4 + (c or 0) * 4 + (f or 0) * 9
            w(f"| {date} | {food} | {cal} | {implied:.0f} | {p} | {c} | {f} "
              f"| {src or ''} |")
        if len(unreconciled) > SAMPLE:
            w(f"\n...and {len(unreconciled) - SAMPLE} more.")
    else:
        w("\nNone.")

    w(f"\n### Same food written twice inside two minutes — {len(rapid)}")
    if rapid:
        w("\nThe iOS rapid-fire shape: one thought sent as several messages")
        w("became several turns and several writes. `rapid-fire messages")
        w("coalesce into one turn` is the fix, and it is NOT on main.\n")
        w("| date | food | times |")
        w("|---|---|---|")
        for date, food, n, first, last in rapid[:SAMPLE]:
            w(f"| {date} | {food} | {n} |")
        if len(rapid) > SAMPLE:
            w(f"\n...and {len(rapid) - SAMPLE} more.")
    else:
        w("\nNone.")

    w(f"\n### Zero calories attributed to a real source — {len(misattributed)}")
    if misattributed:
        w("\nThe card said where the number came from, over a number that")
        w("source never produced. The worst of the set: it tells the user to")
        w("trust it.\n")
        for date, food, qty, src in misattributed[:SAMPLE]:
            w(f"- {date} · {food} ({qty or 'no qty'}) · source={src}")
        if len(misattributed) > SAMPLE:
            w(f"\n...and {len(misattributed) - SAMPLE} more.")
    else:
        w("\nNone.")

    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--user", type=int, default=None)
    args = ap.parse_args()
    print(run(args.user, args.days))


if __name__ == "__main__":
    main()
