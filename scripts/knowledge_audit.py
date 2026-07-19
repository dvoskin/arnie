"""Arnie knowledge audit — what does Arnie know, and where are the gaps?

Layers implemented (of the 4-layer design):
  1. COVERAGE — every knowledge store vs a checklist of coach-critical facts:
     present / missing / stale / conflicting.
  2. RETENTION — mine conversation_logs for the smoking guns: questions Arnie
     asked more than once (didn't retain the answer) and user corrections
     ("I already told you", "as I said").

Read-only. Direct psycopg against DATABASE_URL (async engine hangs on
one-shot prod reads — session lesson). Usage:

    python scripts/knowledge_audit.py [user_id] [> report.md]
"""
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta

import psycopg


def _url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        for line in open(os.path.join(os.path.dirname(__file__), "..", "..",
                                      "arnie", ".env")):
            if line.startswith("DATABASE_URL"):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
    return re.sub(r"^[a-z]+\+[a-z0-9]+://", "postgresql://", url)


# ── Layer 1: the coach-critical checklist ────────────────────────────────────
# (fact, where it should live, SQL fetch) — one row per fact in the report.

def coverage(cur, uid: int) -> list[dict]:
    rows: list[dict] = []

    def add(fact, source, value, stale_days=None):
        status = "present" if value not in (None, "", [], {}) else "MISSING"
        if status == "present" and stale_days is not None and stale_days > 30:
            status = f"stale ({stale_days}d)"
        rows.append({"fact": fact, "source": source,
                     "value": str(value)[:80] if value else "—",
                     "status": status})

    cur.execute("""SELECT name, timezone, primary_goal, goal_weight_kg,
                          current_weight_kg, height_cm, age, sex,
                          training_experience, brain_dump
                   FROM users WHERE id = %s""", (uid,))
    u = cur.fetchone()
    for fact, val in zip(("name", "timezone", "primary goal", "goal weight",
                          "current weight", "height", "age", "sex",
                          "training experience", "brain dump"), u):
        add(fact, "users", val)

    cur.execute("""SELECT calorie_target, protein_target, food_logging_mode
                   FROM user_preferences WHERE user_id = %s""", (uid,))
    p = cur.fetchone() or (None, None, None)
    add("calorie target", "preferences", p[0])
    add("protein target", "preferences", p[1])
    add("food logging mode", "preferences", p[2])

    cur.execute("""SELECT program_json, updated_at FROM workout_programs
                   WHERE user_id = %s""", (uid,))
    w = cur.fetchone()
    if w:
        prog = json.loads(w[0]) if w[0] else {}
        age = (datetime.utcnow() - w[1]).days if w[1] else None
        add("training program", "workout_programs",
            prog.get("split_name"), stale_days=age)
        n_target = sum(1 for d in prog.get("days", [])
                       for e in d.get("exercises", []) if e.get("sets"))
        add("program targets (sets/reps)", "workout_programs",
            f"{n_target} exercises with targets" if n_target else None)
    else:
        add("training program", "workout_programs", None)

    # Attribute brain: lanes present + the coach-critical ones by key.
    cur.execute("""SELECT attribute_key, value, category
                   FROM user_attributes WHERE user_id = %s""", (uid,))
    attrs = cur.fetchall()
    by_key = {a[0]: a for a in attrs}
    rows.append({"fact": f"attribute brain ({len(attrs)} rows)",
                 "source": "user_attributes",
                 "value": ", ".join(sorted({a[2] or "?" for a in attrs}))[:80],
                 "status": "present" if attrs else "MISSING"})
    for want, label in (("injur", "injuries / limitations"),
                        ("equipment", "equipment / gym access"),
                        ("diet", "dietary constraints"),
                        ("allerg", "allergies"),
                        ("supplement", "supplements"),
                        ("schedule", "schedule / routine")):
        hits = [k for k in by_key if want in k.lower()]
        v = "; ".join(f"{k}={by_key[k][1]}" for k in hits[:2]) if hits else None
        add(label, "user_attributes", v)

    cur.execute("""SELECT COUNT(*) FROM user_threads
                   WHERE user_id = %s AND status = 'open'""", (uid,))
    t = cur.fetchone()
    add("open threads", "user_threads",
        f"{t[0]} open" if t and t[0] else None)

    # Conflict check: goal in users vs any goal-ish attribute.
    goal_attrs = [f"{k}={by_key[k][1]}" for k in by_key if "goal" in k.lower()]
    if goal_attrs and u[2]:
        joined = "; ".join(goal_attrs)[:60]
        if u[2].lower() not in joined.lower():
            rows.append({"fact": "goal consistency", "source": "users vs attributes",
                         "value": f"users={u[2]} / attrs={joined}",
                         "status": "CONFLICT?"})
    return rows


# ── Layer 2: retention mining ────────────────────────────────────────────────

_QUESTION_NORM = re.compile(r"[^a-z ]")
_CORRECTION = re.compile(
    r"i (already )?(told|said|mentioned)|as i said|again[,.]? i|"
    r"i keep (telling|saying)|why (do i|are you) (have to|asking)", re.I)


def retention(cur, uid: int, days: int = 30) -> dict:
    since = datetime.utcnow() - timedelta(days=days)
    cur.execute("""SELECT raw_message, response, timestamp
                   FROM conversation_logs
                   WHERE user_id = %s AND timestamp >= %s
                   ORDER BY id""", (uid, since))
    turns = cur.fetchall()

    # Questions Arnie asked, normalized to a crude fingerprint.
    q_counter: Counter = Counter()
    q_example: dict = {}
    for _, resp, ts in turns:
        for sent in re.split(r"[.!\n]|\|\|\|", resp or ""):
            sent = sent.strip()
            if not sent.endswith("?") or len(sent) < 12:
                continue
            fp = " ".join(sorted(set(
                _QUESTION_NORM.sub("", sent.lower()).split()))[:8])
            q_counter[fp] += 1
            q_example.setdefault(fp, sent[:110])
    repeated = [(q_example[fp], n) for fp, n in q_counter.most_common(12)
                if n >= 3]

    corrections = [(m or "")[:140] for m, _, _ in turns
                   if m and _CORRECTION.search(m)]
    return {"turns": len(turns), "repeated_questions": repeated,
            "corrections": corrections[:10]}


def main() -> None:
    uid = int(sys.argv[1]) if len(sys.argv) > 1 else 26
    conn = psycopg.connect(_url())
    cur = conn.cursor()

    print(f"# Arnie Knowledge Audit — user {uid}")
    print(f"_Generated {datetime.utcnow():%Y-%m-%d %H:%M} UTC. Read-only._\n")

    print("## Layer 1 · Coverage\n")
    print("| Fact | Source | Value | Status |")
    print("|---|---|---|---|")
    missing = 0
    for r in coverage(cur, uid):
        if r["status"] != "present":
            missing += 1
        print(f"| {r['fact']} | {r['source']} | {r['value']} | "
              f"**{r['status']}**" if r["status"] != "present"
              else f"| {r['fact']} | {r['source']} | {r['value']} | ok", end=" |\n")
    print(f"\n**{missing} gaps/flags** in the checklist.\n")

    print("## Layer 2 · Retention (last 30 days)\n")
    ret = retention(cur, uid)
    print(f"{ret['turns']} turns analyzed.\n")
    if ret["repeated_questions"]:
        print("### Questions asked 3+ times (didn't retain the answer?)\n")
        for q, n in ret["repeated_questions"]:
            print(f"- ({n}×) “{q}”")
    else:
        print("No question asked 3+ times — retention looks clean.")
    print()
    if ret["corrections"]:
        print("### User corrections (\"I already told you\")\n")
        for c in ret["corrections"]:
            print(f"- “{c}”")
    else:
        print("No 'I already told you' style corrections found.")

    conn.close()


if __name__ == "__main__":
    main()
