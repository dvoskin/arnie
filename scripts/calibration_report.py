"""Measure Arnie's food-calorie estimation bias against database ground truth.

The "BIAS HIGH" guidance exists because Arnie systematically undercounts — but
it's qualitative. This measures it: for entries whose QUANTITY is an explicit
mass ("200g", "6 oz") AND whose food resolved to a per-100g profile in the
user's food memory (USDA/label-backed), the true calories are computable:

    true_cal = stated_grams * cal_100 / 100

The stored entry calories are the LLM's own estimate (enrichment backs grams
OUT of them, it never overwrites them), so stored_cal / true_cal is a clean
per-entry bias sample. ratio < 1.0 = undercount. The aggregate factor can
eventually replace the qualitative prompt with a calibrated correction.

Also reports macro-COMPOSITION bias (protein per kcal, LLM vs database) over
every matched entry, mass-stated or not — portion cancels out of the ratio.

Read-only. Works on local SQLite and prod Postgres (same engine bootstrap as
the other scripts — run on Render for the real fleet numbers):

  python scripts/calibration_report.py                 # Danny only, 90 days
  python scripts/calibration_report.py --all-users --days 180
"""
import argparse
import asyncio
import os
import re
import statistics
import sys

# Runnable as `python scripts/calibration_report.py` from the repo root —
# put the root on the import path (python puts scripts/ there, not cwd).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(".env", override=True)

from sqlalchemy import text
from db.database import AsyncSessionLocal
from core.food_intelligence import normalize_name

DANNY_IDS = (2, 20, 26)   # canonical + linked

_MASS = {"g": 1.0, "gram": 1.0, "grams": 1.0, "kg": 1000.0,
         "oz": 28.35, "ounce": 28.35, "ounces": 28.35,
         "lb": 453.6, "lbs": 453.6, "pound": 453.6, "pounds": 453.6}


def stated_grams(quantity: str):
    """Grams ONLY when the quantity is an explicit mass — pieces/cups are too
    rough to serve as calibration ground truth."""
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([a-z]+)\s*$", (quantity or "").lower())
    if not m:
        return None
    unit = m.group(2)
    return float(m.group(1)) * _MASS[unit] if unit in _MASS else None


def _summary(name: str, samples: list) -> str:
    if len(samples) < 3:
        return f"  {name:<28} n={len(samples)} (too few samples)"
    s = sorted(samples)
    q1, med, q3 = (s[len(s) // 4], statistics.median(s), s[3 * len(s) // 4])
    return (f"  {name:<28} n={len(s):<5} median {med:.3f}  "
            f"IQR [{q1:.3f}, {q3:.3f}]  mean {statistics.fmean(s):.3f}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--all-users", action="store_true", help="fleet-wide (default: Danny only)")
    args = ap.parse_args()

    async with AsyncSessionLocal() as db:
        user_filter = "" if args.all_users else f"AND d.user_id IN {DANNY_IDS}"
        rows = (await db.execute(text(f"""
            SELECT d.user_id, f.parsed_food_name, f.quantity, f.calories,
                   f.protein, f.confidence_score, f.source_type, f.from_photo
            FROM food_entries f JOIN daily_logs d ON f.daily_log_id = d.id
            WHERE f.calories > 0 AND f.parsed_food_name IS NOT NULL
              {user_filter}
        """))).fetchall()
        matches = (await db.execute(text("""
            SELECT user_id, name_norm, cal_100, protein_100
            FROM user_food_matches WHERE cal_100 IS NOT NULL AND cal_100 > 0
        """))).fetchall()

    per100 = {(m.user_id, m.name_norm): (m.cal_100, m.protein_100) for m in matches}

    cal_bias = []                 # stored_cal / true_cal  (mass-stated only)
    cal_bias_by_bucket = {}       # confidence tier / photo
    comp_bias = []                # (protein/cal) llm ÷ (protein_100/cal_100)
    matched = 0

    for r in rows:
        key = (r.user_id, normalize_name(r.parsed_food_name))
        prof = per100.get(key)
        if not prof:
            continue
        matched += 1
        cal_100, protein_100 = prof

        grams = stated_grams(r.quantity)
        if grams and grams >= 20:                     # tiny amounts are noise
            true_cal = grams * cal_100 / 100.0
            if true_cal >= 30:
                ratio = float(r.calories) / true_cal
                if 0.2 <= ratio <= 5.0:               # drop unit-confusion outliers
                    cal_bias.append(ratio)
                    conf = r.confidence_score or 0
                    bucket = ("photo" if r.from_photo else
                              "high-conf" if conf >= 0.85 else
                              "mid-conf" if conf >= 0.6 else "low-conf")
                    cal_bias_by_bucket.setdefault(bucket, []).append(ratio)

        if r.protein and protein_100 and cal_100:
            llm_density = float(r.protein) / float(r.calories)
            db_density = float(protein_100) / float(cal_100)
            if db_density > 0:
                ratio = llm_density / db_density
                if 0.2 <= ratio <= 5.0:
                    comp_bias.append(ratio)

    print(f"\n═══ Calorie calibration — LLM estimate vs database ground truth ═══")
    print(f"entries scanned: {len(rows)}, matched to a per-100g profile: {matched}\n")
    print("CALORIE BIAS (mass-stated portions; <1.0 = LLM undercounts):")
    print(_summary("all", cal_bias))
    for bucket in sorted(cal_bias_by_bucket):
        print(_summary(bucket, cal_bias_by_bucket[bucket]))
    print("\nPROTEIN-COMPOSITION BIAS (protein per kcal, LLM ÷ database):")
    print(_summary("all", comp_bias))
    if len(cal_bias) >= 10:
        med = statistics.median(cal_bias)
        print(f"\n→ measured correction factor: divide LLM calories by {med:.3f} "
              f"(i.e. {'raise' if med < 1 else 'lower'} estimates ~{abs(1 - med) * 100:.0f}%)")
    else:
        print("\n→ not enough mass-stated samples for a correction factor yet — "
              "rerun on prod (--all-users) for fleet coverage.", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
