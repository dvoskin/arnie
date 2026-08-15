"""⭐ WHICH RUNG REAL FOOD WOULD ACTUALLY REACH — the instrument, committed.

⛔ WHY THIS EXISTS. On 2026-08-14 the canary proved the general food lane does
not consume canonical pricing. The obvious next move was to wire it up. This
instrument was written first, and it changed the plan: measured against 691 real
production entries, the committed artifact is the DECIDING rung on **13 of
them — 1.9%**, because `Rung.MEMORY` outranks it and already owned 15 of the 28
it could have priced. All of Phase 0 — 77 signatures, 27 winners, the poisoned
rebuild, the accounting freeze — governs 1.9% of real logged food.

Nothing about that work was wrong. Nobody had the number.

⭐ SO THIS IS A SEQUENCING INSTRUMENT, and it is committed because the roadmap
now depends on rerunning it. "Materially reduce the non-English/modifier miss
bucket" is the exit criterion for the interpretation boundary, and an exit
criterion measured by a script in someone's scratchpad is not one.

⭐⭐ IT ASKS THE PRODUCTION FUNCTIONS, NEVER A REIMPLEMENTATION. Identity comes
from `pricing_artifact.split_identity`, evidence from
`pricing_artifact.evidence_for`, and the memory rung from the SAME exact
`name_norm` equality `db.queries.get_user_food_match` performs. An instrument
that re-derives the predicate it measures can disagree with the runtime, which
is the failure `/health` had reported for two canary runs.

⚠ ITS HONEST LIMITS, RECORDED IN THE OUTPUT AND NOT ONLY HERE:

  · it counts ENTRIES, not turns — a three-item meal is three rows
  · it reads `parsed_food_name`, which is what the writer persisted; settle
    time passes `identity`, and the two are the same string today but nothing
    enforces that
  · the BRANDED bucket uses `_looks_branded`, a production HEURISTIC, so that
    number is indicative and the others are not derived from it
  · it says which rung would be REACHED, never whether the number would be
    RIGHT. Reachability is not accuracy.

Usage:

    python -m scripts.measure_identity_coverage                 # print
    python -m scripts.measure_identity_coverage --write         # + JSON record
    python -m scripts.measure_identity_coverage --days 60
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

RECORD_DIR = pathlib.Path(__file__).resolve().parents[1] / "data" / "coverage"

#: Anything outside ASCII. NOT a language detector and deliberately not one —
#: a script test is a structural fact about the string, while "which language
#: is this" is a judgement that would need the very interpretation layer this
#: measurement exists to justify building.
NON_ASCII = re.compile(r"[^\x00-\x7f]")

#: The buckets. Ordered by what each one would take to fix, because that
#: ordering is the whole output of the instrument.
NON_ENGLISH = "NON-ENGLISH  (interpretation boundary)"
BRANDED = "BRANDED      (PRODUCT rung, no producer)"
QUALIFIED = "QUALIFIED    (identity boundary — modifiers)"
UNCOVERED = "BARE + UNCOVERED (a real artifact gap)"


def _database_url() -> str:
    """Production's URL from the environment, or from the gitignored .env.

    NEVER a literal in this file. `+psycopg` is stripped because psycopg's own
    `connect` does not take SQLAlchemy's driver suffix.
    """
    import os

    url = os.getenv("ARNIE_PROD_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        env = pathlib.Path(__file__).resolve().parents[2] / "arnie" / ".env"
        if not env.exists():
            raise SystemExit(
                "no ARNIE_PROD_DATABASE_URL and no ../arnie/.env to read")
        found = re.search(r"^DATABASE_URL=(.+)$", env.read_text(), re.M)
        if not found:
            raise SystemExit("../arnie/.env carries no DATABASE_URL")
        url = found.group(1).strip().strip('"').strip("'")
    return url.replace("+psycopg", "").replace("+asyncpg", "")


def _entries(url: str, days: int, limit: int) -> tuple:
    """(rows, memory keys). Two reads, no writes, no model, no network beyond
    the database.

    ⚠ THE MEMORY SET HERE IS ADDRESSABILITY, NOT CONTRIBUTION — see
    `measure_through_the_rung` below, which is what the roadmap now requires.
    """
    import psycopg

    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT fe.parsed_food_name, dl.user_id "
            "FROM food_entries fe JOIN daily_logs dl ON dl.id = fe.daily_log_id "
            "WHERE fe.timestamp > now() - make_interval(days => %s) "
            "ORDER BY fe.timestamp DESC LIMIT %s", (days, limit))
        rows = cur.fetchall()
        # THE SAME PREDICATE `get_user_food_match` USES: exact (user_id,
        # name_norm) equality, and `_memory()` discards a row with no cal_100.
        # Replicated as a set membership rather than N queries because the
        # predicate is exact equality — if that lookup ever becomes fuzzy this
        # instrument UNDERCOUNTS memory and this comment is where to start.
        cur.execute("SELECT user_id, name_norm FROM user_food_matches "
                    "WHERE cal_100 IS NOT NULL")
        memory = set(cur.fetchall())
    return rows, memory


def classify(name: str) -> str:
    """Which population an unpriceable name belongs to.

    ⚠ THE ORDER IS LOAD-BEARING and each test is narrower than the next.
    Non-ASCII first because a Russian brand is an interpretation problem before
    it is a product problem; branded before qualified because "Quest Protein
    Chips Sour Cream & Onion" is multi-word for a reason that is not a modifier.
    """
    from handlers.tool_executor import _looks_branded

    if NON_ASCII.search(name):
        return NON_ENGLISH
    if _looks_branded(name):
        return BRANDED
    if "," in name or len(name.split()) > 2:
        return QUALIFIED
    return UNCOVERED


def measure(*, days: int = 30, limit: int = 1000) -> dict:
    from skills.nutrition.pricing_artifact import (evidence_for, key,
                                                   split_identity)
    from core.food_intelligence import normalize_name

    rows, memory = _entries(_database_url(), days, limit)

    rungs = collections.Counter()
    buckets = collections.Counter()
    samples = collections.defaultdict(list)
    artifact_hits, both = collections.Counter(), 0

    for name, user_id in rows:
        name = str(name or "")
        entity, preparation = split_identity(name)
        has_artifact = evidence_for(entity, preparation) is not None
        # MEMORY IS ASKED FIRST BECAUSE THE LADDER ASKS IT FIRST. Measuring
        # artifact reachability in isolation is the mistake that made "28
        # priceable" read as the artifact's contribution when 15 of those were
        # already owned by a higher rung.
        if (user_id, normalize_name(name)) in memory:
            rungs["MEMORY"] += 1
            both += bool(has_artifact)
        elif has_artifact:
            rungs["ARTIFACT"] += 1
            artifact_hits[key(entity, preparation)] += 1
        else:
            rungs["ESTIMATE_OR_REFUSE"] += 1
            bucket = classify(name)
            buckets[bucket] += 1
            if len(samples[bucket]) < 10:
                samples[bucket].append(name)

    total = len(rows)
    evidence = rungs["MEMORY"] + rungs["ARTIFACT"]
    return {
        "entries": total,
        "window_days": days,
        "rungs": dict(rungs),
        "evidence_backed": evidence,
        "evidence_backed_pct": round(100 * evidence / max(total, 1), 1),
        # ⭐ THE HEADLINE, AND IT IS NOT `artifact_reachable`. What the artifact
        # could have priced is a capability; what it DECIDES is its adoption.
        "artifact_decides": rungs["ARTIFACT"],
        "artifact_decides_pct": round(100 * rungs["ARTIFACT"] / max(total, 1), 1),
        "artifact_outranked_by_memory": both,
        "artifact_identities": dict(artifact_hits),
        "uncovered_buckets": {
            b: {"count": c, "pct": round(100 * c / max(total, 1), 1),
                "samples": samples[b]}
            for b, c in buckets.most_common()},
        "instrument_limits": [
            "counts ENTRIES, not turns",
            "reads parsed_food_name; settle time passes `identity`",
            "the BRANDED bucket uses the _looks_branded HEURISTIC",
            "reports which rung is REACHED, never whether it would be RIGHT",
        ],
    }


def render(report: dict) -> str:
    out = [f"\n  {report['entries']} entries · {report['window_days']} days\n"]
    order = ("MEMORY", "ARTIFACT", "ESTIMATE_OR_REFUSE")
    for name in order:
        count = report["rungs"].get(name, 0)
        pct = 100 * count / max(report["entries"], 1)
        out.append(f"    {count:5d}  {pct:5.1f}%   {name}")
    out.append(f"   {'':─<48}")
    out.append(f"    {report['evidence_backed']:5d}  "
               f"{report['evidence_backed_pct']:5.1f}%   EVIDENCE-BACKED")
    out.append(f"\n    ARTIFACT DECIDES  {report['artifact_decides']}"
               f"  ({report['artifact_decides_pct']}%)"
               f"  · outranked by memory on "
               f"{report['artifact_outranked_by_memory']} more")
    out.append("\n  THE UNPRICEABLE POPULATION:")
    for bucket, data in report["uncovered_buckets"].items():
        out.append(f"    {data['count']:5d}  {data['pct']:5.1f}%   {bucket}")
        for sample in data["samples"][:4]:
            out.append(f"              · {sample[:62]}")
    out.append("\n  ⚠ limits: " + " · ".join(report["instrument_limits"]))
    return "\n".join(out)


if __name__ == "__main__":
    days = 30
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    report = measure(days=days)
    print(render(report))
    if "--write" in sys.argv:
        RECORD_DIR.mkdir(parents=True, exist_ok=True)
        # NAMED BY WINDOW, NOT BY DATE. A rerun of the same window after the
        # interpretation boundary lands must be COMPARABLE to this one, and a
        # date-stamped file makes two runs look like two measurements of
        # different things when they are the before and after of one.
        path = RECORD_DIR / f"coverage_last_{days}_days.json"
        previous = json.loads(path.read_text()) if path.exists() else None
        if previous:
            report["previous"] = {
                k: previous.get(k) for k in
                ("entries", "evidence_backed_pct", "artifact_decides_pct")}
        path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
        print(f"\n  written → {path}")


# ══ MEASURED THROUGH THE ACTUAL RUNG ════════════════════════════════════════
#
# ⛔ WHY THIS EXISTS AND WHY THE FUNCTION ABOVE IS NOT ENOUGH. On 2026-08-14 the
# `measure()` above reported MEMORY at 44.6% of production. That number was
# ADDRESSABILITY — a row exists under the key — computed directly against the
# table, and it was reported as though it were the canonical ladder's memory
# CONTRIBUTION. It was not. `_memory()` was raising `ValueError` on every row's
# string confidence and returning None, so the true contribution was 0%.
#
# ⭐ AN INSTRUMENT THAT APPROXIMATES ITS SUBJECT CANNOT DISCOVER THAT ITS
# SUBJECT IS BROKEN. This one calls `_memory()` itself, so what it reports is
# what a turn would get — and if the rung dies again, the number goes to zero
# instead of staying comfortably plausible.


async def measure_through_the_rung(*, days: int = 30, limit: int = 1000) -> dict:
    """Which rung a real entry would ACTUALLY reach, by executing the rung."""
    import collections

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.canonical_pricing_inputs import _memory
    from db.database import make_engine
    from db.models import DailyLog, FoodEntry
    from skills.nutrition.pricing_artifact import evidence_for, split_identity

    engine = make_engine(_database_url().replace("postgresql://",
                                                 "postgresql+psycopg://"))
    rungs, unpriced = collections.Counter(), []
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            rows = (await db.execute(
                select(FoodEntry.parsed_food_name, DailyLog.user_id)
                .join(DailyLog, DailyLog.id == FoodEntry.daily_log_id)
                .order_by(FoodEntry.timestamp.desc()).limit(limit))).all()
            for name, user_id in rows:
                name = str(name or "")
                # ⭐ THE LADDER'S OWN ORDER, and executed rather than modelled:
                # memory first, because that is what `price()` does.
                if await _memory(db, user_id, name) is not None:
                    rungs["MEMORY"] += 1
                    continue
                entity, preparation = split_identity(name)
                if evidence_for(entity, preparation) is not None:
                    rungs["ARTIFACT"] += 1
                else:
                    rungs["ESTIMATE_OR_REFUSE"] += 1
                    unpriced.append(name)
    finally:
        await engine.dispose()

    total = max(len(rows), 1)
    evidence = rungs["MEMORY"] + rungs["ARTIFACT"]
    return {
        "entries": len(rows), "measured_through": "canonical _memory() rung",
        "rungs": dict(rungs),
        "evidence_backed_pct": round(100 * evidence / total, 1),
        "memory_pct": round(100 * rungs["MEMORY"] / total, 1),
        "artifact_pct": round(100 * rungs["ARTIFACT"] / total, 1),
        "uncovered_buckets": {
            b: c for b, c in collections.Counter(
                classify(n) for n in unpriced).most_common()},
        "instrument_limits": [
            "the rung is EXECUTED, so this is contribution, not addressability",
            "no canonical_entity_id is passed — the store is not populated yet, "
            "so this measures the repaired rung on TODAY's keys",
            "counts ENTRIES, not turns",
        ],
    }
