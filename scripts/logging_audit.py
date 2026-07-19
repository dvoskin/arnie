"""Logging-reliability baseline scorecard — READ-ONLY sweep over prod.

The measuring stick for the talker/scribe migration (and every prompt or
pipeline change before it): run BEFORE a change lands, run nightly after,
compare. No writes, no ORM (raw psycopg — the async engine hangs against
prod; see project memory), aggregates only — no message bodies leave the DB.

Usage:
    python scripts/logging_audit.py            # last 14 days
    python scripts/logging_audit.py --days 30

Outputs a markdown scorecard to stdout and a JSON snapshot to
audits/baseline_<date>.json (committed as the comparison artifact).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path


def _prod_url() -> str:
    env_path = Path(__file__).resolve().parent.parent.parent / "arnie" / ".env"
    url = ""
    for line in env_path.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            url = line.split("=", 1)[1].strip()
    return re.sub(r"^[a-z]+\+[a-z0-9]+://", "postgresql://", url)


LOG_TOOLS = ("log_food", "log_exercise", "log_water", "log_body_weight")


def run(days: int) -> dict:
    import psycopg

    since = datetime.utcnow() - timedelta(days=days)
    m: dict = {"window_days": days, "since_utc": since.isoformat(),
               "generated_utc": datetime.utcnow().isoformat()}

    with psycopg.connect(_prod_url()) as conn, conn.cursor() as cur:
        def one(sql, *args):
            cur.execute(sql, args or None)
            return cur.fetchone()[0]

        # ── Volume ──────────────────────────────────────────────────────────
        m["turns"] = one(
            "SELECT count(*) FROM conversation_logs WHERE timestamp >= %s", since)
        m["active_users"] = one(
            "SELECT count(DISTINCT user_id) FROM conversation_logs WHERE timestamp >= %s",
            since)
        m["log_turns"] = one(
            "SELECT count(*) FROM conversation_logs WHERE timestamp >= %s "
            "AND (" + " OR ".join(["skills_fired LIKE %s"] * len(LOG_TOOLS)) + ")",
            since, *[f"%{t}%" for t in LOG_TOOLS])
        m["tool_error_turns"] = one(
            "SELECT count(*) FROM conversation_logs WHERE timestamp >= %s "
            "AND skills_fired LIKE %s", since, "%:error%")

        # ── Blocked writes (dedup / carryover readbacks in the stored reply) ─
        m["blocked_write_turns"] = one(
            "SELECT count(*) FROM conversation_logs WHERE timestamp >= %s "
            "AND (response LIKE %s OR response LIKE %s OR response LIKE %s)",
            since, "%Already on the board%", "%already on the board%",
            "%nothing new logged%")

        # ── Correction rate: an update/delete within 15 min of a log turn ────
        cur.execute(
            """
            SELECT count(DISTINCT c2.id)
            FROM conversation_logs c1
            JOIN conversation_logs c2
              ON c2.user_id = c1.user_id
             AND c2.timestamp > c1.timestamp
             AND c2.timestamp <= c1.timestamp + interval '15 minutes'
            WHERE c1.timestamp >= %s
              AND c1.skills_fired LIKE %s
              AND (c2.skills_fired LIKE %s OR c2.skills_fired LIKE %s)
            """,
            (since, "%log_food%", "%update_food_entry%", "%delete_food_entry%"))
        m["quick_correction_turns"] = cur.fetchone()[0]

        # ── Feedback + regenerates (near-zero pre-deploy; the point is the
        #    baseline snapshot the post-deploy numbers get compared against) ──
        m["thumbs_up"] = one(
            "SELECT count(*) FROM conversation_logs WHERE timestamp >= %s AND feedback = 'up'",
            since)
        m["thumbs_down"] = one(
            "SELECT count(*) FROM conversation_logs WHERE timestamp >= %s AND feedback = 'down'",
            since)
        m["regenerated_turns"] = one(
            "SELECT count(*) FROM conversation_logs WHERE timestamp >= %s "
            "AND superseded_by IS NOT NULL", since)

        # ── Turn-health flags (parsed_intent carries the CSV on flagged turns) ─
        cur.execute(
            "SELECT parsed_intent, count(*) FROM conversation_logs "
            "WHERE timestamp >= %s AND parsed_intent IS NOT NULL "
            "AND parsed_intent != '' GROUP BY parsed_intent ORDER BY count(*) DESC LIMIT 15",
            (since,))
        m["health_flag_distribution"] = {r[0]: r[1] for r in cur.fetchall()}

        # ── Activity shape ───────────────────────────────────────────────────
        cur.execute(
            "SELECT source_type, count(*) FROM conversation_logs "
            "WHERE timestamp >= %s GROUP BY source_type ORDER BY count(*) DESC",
            (since,))
        m["turns_by_source"] = {r[0] or "text": r[1] for r in cur.fetchall()}
        cur.execute(
            "SELECT platform, count(*) FROM conversation_logs "
            "WHERE timestamp >= %s GROUP BY platform ORDER BY count(*) DESC",
            (since,))
        m["turns_by_platform"] = {r[0] or "?": r[1] for r in cur.fetchall()}
        m["food_entries_written"] = one(
            "SELECT count(*) FROM food_entries fe JOIN daily_logs dl "
            "ON fe.daily_log_id = dl.id WHERE fe.timestamp >= %s", since)
        cur.execute(
            "SELECT count(*) FROM (SELECT dl.user_id, dl.date FROM food_entries fe "
            "JOIN daily_logs dl ON fe.daily_log_id = dl.id "
            "WHERE fe.timestamp >= %s GROUP BY dl.user_id, dl.date) t", (since,))
        m["logging_user_days"] = cur.fetchone()[0]

    # ── Derived rates ────────────────────────────────────────────────────────
    lt = max(1, m["log_turns"])
    m["rates"] = {
        "blocked_write_per_log_turn": round(m["blocked_write_turns"] / lt, 4),
        "quick_correction_per_log_turn": round(m["quick_correction_turns"] / lt, 4),
        "tool_error_per_log_turn": round(m["tool_error_turns"] / lt, 4),
        "log_turn_share_of_all": round(m["log_turns"] / max(1, m["turns"]), 4),
        "entries_per_logging_user_day": round(
            m["food_entries_written"] / max(1, m["logging_user_days"]), 2),
    }
    return m


def render(m: dict) -> str:
    r = m["rates"]
    lines = [
        f"# Logging baseline — last {m['window_days']}d (generated {m['generated_utc'][:16]}Z)",
        "",
        f"Turns {m['turns']} · active users {m['active_users']} · log turns "
        f"{m['log_turns']} ({r['log_turn_share_of_all']:.0%} of all) · food entries "
        f"written {m['food_entries_written']} across {m['logging_user_days']} user-days "
        f"({r['entries_per_logging_user_day']}/day)",
        "",
        "## Reliability",
        f"- Blocked-write readbacks: {m['blocked_write_turns']} "
        f"({r['blocked_write_per_log_turn']:.1%} of log turns)",
        f"- Quick corrections (≤15 min after a log): {m['quick_correction_turns']} "
        f"({r['quick_correction_per_log_turn']:.1%})",
        f"- Tool-error turns: {m['tool_error_turns']} ({r['tool_error_per_log_turn']:.1%})",
        f"- Thumbs: {m['thumbs_up']} up / {m['thumbs_down']} down · regenerated turns: "
        f"{m['regenerated_turns']}  (near-zero pre-deploy — these are the new signals)",
        "",
        "## Health-flag distribution (top)",
    ]
    for flag, n in list(m["health_flag_distribution"].items())[:10]:
        lines.append(f"- {flag}: {n}")
    lines += ["", "## Shape",
              f"- By source: {m['turns_by_source']}",
              f"- By platform: {m['turns_by_platform']}"]
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args()
    metrics = run(args.days)
    out_dir = Path(__file__).resolve().parent.parent / "audits"
    out_dir.mkdir(exist_ok=True)
    snap = out_dir / f"baseline_{datetime.utcnow().date().isoformat()}.json"
    snap.write_text(json.dumps(metrics, indent=2))
    print(render(metrics))
    print(f"\nsnapshot: {snap}", file=sys.stderr)
