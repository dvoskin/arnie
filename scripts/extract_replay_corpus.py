"""Replay-corpus extraction — READ-ONLY pull of real prod turns into
tests/corpus/replay_cases.jsonl.

Selects the turns most worth replaying against any new pipeline:
  • thumbs-down turns (labeled dissatisfaction)
  • regenerated turns (superseded_by set — "this reply failed")
  • blocked-write turns (dedup/carryover readbacks in the reply)
  • quick-correction pairs (update/delete ≤15 min after a log = we got it wrong)
  • turn-health-flagged turns (phantom_log_claim, total_mismatch, …)
  • a random healthy-log sample (the NO-REGRESSION set)

Each case carries the user message, the prior user message (clarify-answer
context), what fired, and the stored reply — `expected` starts null and gets
authored per case as the harness comes up. Private repo; beta-user text stays
in-repo by design (it IS the test data).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


def _prod_url() -> str:
    env_path = Path(__file__).resolve().parent.parent.parent / "arnie" / ".env"
    url = ""
    for line in env_path.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            url = line.split("=", 1)[1].strip()
    return re.sub(r"^[a-z]+\+[a-z0-9]+://", "postgresql://", url)


BASE_COLS = "id, user_id, timestamp, platform, source_type, raw_message, response, skills_fired, parsed_intent"


def _case(row, category, note=""):
    (id_, uid, ts, plat, src, raw, resp, skills, intent) = row
    return {
        "id": f"prod-{id_}",
        "category": category,
        "note": note,
        "user_id": uid,
        "ts": ts.isoformat() if ts else None,
        "platform": plat,
        "source_type": src,
        "user_msg": raw,
        "prior_user_msg": None,   # filled below
        "reply": resp,
        "skills_fired": skills,
        "health_flags": intent,
        "expected": None,          # authored per-case as the harness lands
    }


def run(limit_per_bucket: int = 25, healthy_sample: int = 20) -> list[dict]:
    import psycopg

    cases: dict[str, dict] = {}

    with psycopg.connect(_prod_url()) as conn, conn.cursor() as cur:
        def grab(sql, args, category, note=""):
            cur.execute(sql, args)
            for row in cur.fetchall():
                c = _case(row, category, note)
                cases.setdefault(c["id"], c)

        grab(f"SELECT {BASE_COLS} FROM conversation_logs WHERE feedback = 'down' "
             f"ORDER BY timestamp DESC LIMIT %s", (limit_per_bucket,),
             "thumbs_down", "user rated this reply down")
        grab(f"SELECT {BASE_COLS} FROM conversation_logs WHERE superseded_by IS NOT NULL "
             f"ORDER BY timestamp DESC LIMIT %s", (limit_per_bucket,),
             "regenerated", "user regenerated this reply")
        grab(f"SELECT {BASE_COLS} FROM conversation_logs WHERE "
             f"(response LIKE '%%Already on the board%%' OR response LIKE '%%already on the board%%' "
             f" OR response LIKE '%%nothing new logged%%') "
             f"ORDER BY timestamp DESC LIMIT %s", (limit_per_bucket,),
             "blocked_write", "dedup/carryover blocked a write this turn")
        grab(f"SELECT {BASE_COLS} FROM conversation_logs WHERE parsed_intent LIKE '%%phantom%%' "
             f"OR parsed_intent LIKE '%%mismatch%%' OR parsed_intent LIKE '%%frustrated%%' "
             f"ORDER BY timestamp DESC LIMIT %s", (limit_per_bucket,),
             "health_flagged", "turn-health flagged")
        # Quick-correction pairs: the LOG turn that needed correcting.
        grab(f"""SELECT {', '.join('c1.' + c for c in BASE_COLS.split(', '))}
                 FROM conversation_logs c1
                 JOIN conversation_logs c2
                   ON c2.user_id = c1.user_id
                  AND c2.timestamp > c1.timestamp
                  AND c2.timestamp <= c1.timestamp + interval '15 minutes'
                 WHERE c1.skills_fired LIKE '%%log_food%%'
                   AND (c2.skills_fired LIKE '%%update_food_entry%%'
                        OR c2.skills_fired LIKE '%%delete_food_entry%%')
                 ORDER BY c1.timestamp DESC LIMIT %s""", (limit_per_bucket,),
             "quick_corrected", "user corrected this log within 15 min")
        # Healthy no-regression sample: log turns with no flags, no blocks.
        grab(f"SELECT {BASE_COLS} FROM conversation_logs WHERE skills_fired LIKE '%%log_food%%' "
             f"AND (parsed_intent IS NULL OR parsed_intent = '') "
             f"AND response NOT LIKE '%%Already on the board%%' "
             f"ORDER BY random() LIMIT %s", (healthy_sample,),
             "healthy", "no-regression control case")

        # Prior user message per case (clarify-answer context).
        for c in cases.values():
            cur.execute(
                "SELECT raw_message FROM conversation_logs WHERE user_id = %s "
                "AND timestamp < %s AND raw_message IS NOT NULL AND raw_message != '' "
                "ORDER BY timestamp DESC LIMIT 1",
                (c["user_id"], c["ts"]))
            r = cur.fetchone()
            c["prior_user_msg"] = r[0] if r else None

    return sorted(cases.values(), key=lambda c: (c["category"], c["ts"] or ""))


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "tests" / "corpus"
    out.mkdir(parents=True, exist_ok=True)
    rows = run()
    path = out / "replay_cases.jsonl"
    path.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in rows) + "\n")
    by_cat: dict[str, int] = {}
    for c in rows:
        by_cat[c["category"]] = by_cat.get(c["category"], 0) + 1
    print(f"{len(rows)} cases → {path}")
    for k, v in sorted(by_cat.items()):
        print(f"  {k}: {v}")
