#!/usr/bin/env python
"""REAL-TURN ACQUISITION CANARY — the production readout.

⛔⛔⛔ THIS READS PRODUCTION; IT DOES NOT SIMULATE A TURN. The earlier canary ran
as a SCRIPT, so it never carried the ambient `EvidenceContext` a real turn
carries — and that difference is exactly where the single-flight collision
lived. Its 47.8% was producer FEASIBILITY, never production turn completion.
Simulating the turn again, however carefully, would repeat the mistake with a
different excuse.

So the foods are logged by a real user through a real surface, and this script
only READS what production did.

⛔⛔ THE COLLISION GATE IS A PRECONDITION, NOT A METRIC. Under the collision,
chunks 2+ were silently declined, so an IN-TURN acquisition could never yield
more than `_QUALIFY_BATCH` (3) candidates. A SAME-TURN acquisition with >3
candidates therefore proves multiple qualification batches genuinely ran under
ambient context — and nothing else observable from the database does.

    NO RATE IS PUBLISHED UNLESS THAT GATE PASSES.

Without it a broken implementation still looks FAST — silently reusing batch
one's assessment is quick — and the canary would certify the defect it exists to
detect. `cod` does not satisfy the gate: it had 4 candidates but was acquired in
the BACKGROUND sweep, outside any turn, where no collision was possible.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

QUALIFY_BATCH = 3          # mirrors scripts/build_pricing_artifact._QUALIFY_BATCH


def _url():
    raw = subprocess.run(
        ["bash", "-c",
         "grep -m1 '^DATABASE_URL=' ../arnie/.env | cut -d= -f2- | tr -d '\"'\"'\"' '"],
        capture_output=True, text=True).stdout.strip()
    return raw.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgres://", "postgresql://")


def main(user_id, since):
    import psycopg

    with psycopg.connect(_url(), connect_timeout=20) as c, c.cursor() as cur:
        cur.execute("""select fe.id, fe.parsed_food_name, fe.quantity, fe.calories,
                              fe.pricing_rung, fe.nutrition_evidence_id,
                              fe.source_basis, fe.timestamp
                       from food_entries fe
                       join daily_logs dl on dl.id = fe.daily_log_id
                       where dl.user_id = %s and fe.timestamp >= %s
                       order by fe.id""", (user_id, since))
        entries = cur.fetchall()

        cur.execute("""select id, canonical_identity, source_identifier,
                              jsonb_array_length(candidates::jsonb),
                              identity_evidence, acquired_at
                       from acquired_evidence_records
                       where acquired_at >= %s order by id""", (since,))
        evidence = cur.fetchall()

        # ⛔⛔ NOT WINDOW-SCOPED, AND THAT IS A REPAIR. The first version filtered
        # jobs by `created_at >= since`, so `cod` — whose job was queued at
        # 14:49 and swept at 15:10 — vanished from a 15:00 window and was
        # classified SAME-TURN by absence. The gate PASSED on a background
        # acquisition, certifying the very collision it exists to detect.
        # Absence of a row inside an arbitrary window is not evidence about how
        # the evidence was acquired.
        cur.execute("""select dedup_key, status, attempts, created_at, completed_at
                       from background_jobs where kind='acquire_evidence'
                       order by id""")
        jobs = cur.fetchall()
        recent_jobs = [j for j in jobs if j[3] and str(j[3]) >= str(since)]

        # ⭐ WHO WROTE THE ROW — 'canonical:create' or a legacy source. The
        # ledger is the authority on settlement ownership; `pricing_rung` says
        # WHICH rung, and the two must agree.
        cur.execute("""select entry_id, source, event_type from ledger_events
                       where entry_id = any(%s) and event_type='created'""",
                    ([e[0] for e in entries] or [0],))
        owner = {r[0]: r[1] for r in cur.fetchall()}

    # ⭐ TWO INDEPENDENT SIGNALS, AND BOTH MUST AGREE. A job for this identity
    # means the turn deferred it; and a background acquisition lands MINUTES
    # after the entry, while a same-turn one lands inside the turn's own budget.
    # Either alone can be fooled — a job row could be missing, a clock could
    # drift — so a row counts as SAME-TURN only when neither signal says
    # otherwise.
    deferred = {j[0].replace("acquire:", "") for j in jobs}      # ALL jobs, ever
    entry_at = {}
    for e in entries:
        entry_at.setdefault(str(e[1]).strip().lower(), e[7])

    def _same_turn(v):
        identity = v[1].split("|")[0]
        if identity in deferred:
            return False
        logged = entry_at.get(identity.strip().lower())
        if logged is None:
            return False          # no entry to tie it to — cannot claim in-turn
        gap = abs((v[5] - logged).total_seconds())
        return gap <= 60          # comfortably outside any turn budget

    same_turn = [v for v in evidence if _same_turn(v)]
    jobs = recent_jobs

    print(f"=== entries (user {user_id}, since {since}) ===")
    for e in entries:
        print(f"  #{e[0]} {e[1][:28]:30} {e[2]!r:10} {e[3]}kcal  "
              f"rung={e[4]!r} evidence={e[5]!r} owner={owner.get(e[0],'?')}")
    print(f"\n=== acquired evidence ({len(evidence)}) ===")
    for v in evidence:
        route = "deferred" if v[1].split("|")[0] in deferred else "SAME-TURN"
        print(f"  {v[1][:28]:30} src={v[2]:10} candidates={v[3]:2}  {route}")
    print(f"\n=== deferred jobs ({len(jobs)}) ===")
    for j in jobs:
        print(f"  {j[0]:34} {j[1]:10} attempts={j[2]} done={j[4]}")

    # ── THE GATE ────────────────────────────────────────────────────────────
    proof = [v for v in same_turn if (v[3] or 0) > QUALIFY_BATCH]
    print("\n" + "=" * 66)
    print("COLLISION GATE — a SAME-TURN acquisition with more than "
          f"{QUALIFY_BATCH} candidates")
    if not proof:
        print("  ⛔ NOT SATISFIED — no rate published.")
        print("     Under the collision an in-turn acquisition could never")
        print("     exceed one batch, so a broken build would still look FAST.")
        print(f"     same-turn acquisitions seen: {len(same_turn)}; "
              f"max candidates: {max([v[3] or 0 for v in same_turn], default=0)}")
        print("     Log a food with a large USDA candidate set (e.g. 'sweet")
        print("     potato', 'brown rice') and re-run.")
        return 2
    print(f"  ✅ SATISFIED by {proof[0][1]!r} — {proof[0][3]} candidates in-turn")

    settled = [e for e in entries if e[4]]
    canonical = [e for e in entries if owner.get(e[0], "").startswith("canonical")]
    print("\n=== RATES (gate passed, so these are publishable) ===")
    print(json.dumps({
        "entries": len(entries),
        "canonically_owned": len(canonical),
        "with_pricing_rung": len(settled),
        "same_turn_acquisitions": len(same_turn),
        "deferred_acquisitions": len(jobs),
        "evidence_rows_created": len(evidence),
        # ⛔ THE HARD GATE: a row priced by canonical whose ledger owner is not
        # the canonical writer, or vice versa, is a provenance contradiction.
        "provenance_contradictions": sum(
            1 for e in entries
            if bool(e[4]) != owner.get(e[0], "").startswith("canonical")),
    }, indent=2))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, default=26)
    ap.add_argument("--since", default="2026-09-01 16:00:00")
    a = ap.parse_args()
    sys.exit(main(a.user, a.since))
