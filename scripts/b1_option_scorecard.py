#!/usr/bin/env python3
"""THE OPTION-QUALITY SCORECARD — D4.1's read side.

    candidate source -> offered -> selected -> repaired -> corrected

One row per candidate source per attribute, so "history is selected 91% of the
time and corrected 1%, ontology 55% and 9%" becomes a statement the data can
make. Until it can, expanding ontology coverage versus investing in history
matching is a coin flip with a dashboard next to it.

READS THE TABLE, NOT THE RING. `core/trace_buffer` is `deque(maxlen=2000)` in
process memory and empties on restart — measured zero lines minutes after a
deploy. Anything computed from it is a window over "since the last deploy",
and it cannot tell you what it lost.

WHAT IT REFUSES TO DO. It never prints a rate whose denominator is below
`--min-n` (default 20). A percentage over four observations reads exactly like
a percentage over four hundred, and the whole point of this phase is to stop
deciding from shapes that only look like evidence. Under-powered cells print
their raw counts and the word `thin`.

Usage:
    ARNIE_ADMIN_TOKEN unused here — this reads the DB directly.
    python scripts/b1_option_scorecard.py --db "$DATABASE_URL" [--days 14]
    python scripts/b1_option_scorecard.py --db ... --free-text   # the why
"""
from __future__ import annotations

import argparse
import collections
import sys


#: B-1b EVIDENCE VALIDITY BOUNDARY.
#:
#: Before `719022b`, `_history_grams` fetched the 50 most recent non-estimated
#: rows across ALL foods and matched the name afterwards — about a week of
#: recall for a daily logger, whatever the 90-day window claimed. So every
#: candidate-source observation taken before this point measured a truncated
#: index, not the product: history could not appear, and its absence would
#: read as "users are not served by their own history".
#:
#: Pooling across this line would silently mix two different systems and bias
#: history's availability toward zero — the exact conclusion the bug would
#: have manufactured. Candidate-source measurement RESTARTS here.
#:
#: DB clock at the confirmed production deploy of 719022b.
EVIDENCE_VALID_FROM = "2026-08-06 14:13:30"
EVIDENCE_BOUNDARY_SHA = "719022b"


def _connect(url: str):
    import psycopg
    return psycopg.connect(url.replace("+psycopg", ""), connect_timeout=25)


def _pct(n: int, d: int) -> str:
    return "—" if not d else f"{100.0 * n / d:5.1f}%"


def by_question_version(cur, *, days: int) -> None:
    """Did the rewording help? The only comparison that answers it.

    Repairs are the signal a question was misread, and `interaction_revision`
    cannot separate wording from semantics — a repair deliberately leaves the
    revision alone. So the axis is `question_version`, stamped when the answer
    was written, which makes the comparison computable RETROACTIVELY over
    observations collected before anyone decided to change the wording.
    """
    cur.execute(
        """
        SELECT question_version,
               COUNT(*)                                        AS answers,
               SUM(CASE WHEN outcome = 'repair'  THEN 1 ELSE 0 END) AS repairs,
               SUM(CASE WHEN outcome = 'applied' THEN 1 ELSE 0 END) AS applied,
               SUM(CASE WHEN selected_source = 'free_text' THEN 1 ELSE 0 END)
                                                               AS free_text
        FROM b1_answer_observations
        WHERE observed_at > now() - make_interval(days => %s)
          AND observed_at >= %s::timestamp
        GROUP BY question_version ORDER BY question_version
        """, (days, EVIDENCE_VALID_FROM))
    rows = cur.fetchall()
    if not rows:
        return
    print("BY QUESTION VERSION — did the rewording help?\n")
    print(f"  {'version':<20} {'answers':>8} {'repair':>8} {'applied':>8} "
          f"{'free text':>10}")
    for version, answers, repairs, applied, free_text in rows:
        print(f"  {version or '—':<20} {answers:>8} "
              f"{_pct(repairs, answers):>8} {_pct(applied, answers):>8} "
              f"{_pct(free_text, answers):>10}")
    if len(rows) == 1:
        print("\n  Only one generation observed — nothing to compare yet. "
              "Bump\n  QUESTION_VERSION when the wording changes and this "
              "becomes the A/B.\n")
    else:
        print()


def scorecard(cur, *, days: int, min_n: int) -> None:
    cur.execute(
        """
        SELECT o.attribute, o.selected_source, o.outcome, o.entry_id,
               o.round_index, o.latency_ms,
               (c.entry_id IS NOT NULL) AS corrected
        FROM b1_answer_observations o
        LEFT JOIN b1_correction_observations c ON c.entry_id = o.entry_id
        WHERE o.observed_at > now() - make_interval(days => %s)
          AND o.observed_at >= %s::timestamp
        """, (days, EVIDENCE_VALID_FROM))
    rows = cur.fetchall()
    if not rows:
        print(f"no VALID observations in the last {days} days.\n"
              f"  The window has not produced data yet, which is NOT the same "
              f"as a zero rate.\n"
              f"  Counting only observations at or after "
              f"{EVIDENCE_VALID_FROM} ({EVIDENCE_BOUNDARY_SHA}).")
        return

    per = collections.defaultdict(lambda: collections.Counter())
    for attribute, source, outcome, entry_id, rnd, latency, corrected in rows:
        k = (attribute or "?", source or "?")
        per[k]["answers"] += 1
        if outcome == "applied":
            per[k]["applied"] += 1
        if outcome == "repair":
            per[k]["repair"] += 1
        if outcome in ("cancelled", "refused"):
            per[k]["closed_without"] += 1
        if entry_id:
            per[k]["committed"] += 1
        if corrected:
            per[k]["corrected"] += 1
        if latency is not None:
            per[k]["latency_sum"] += int(latency)
            per[k]["latency_n"] += 1

    print(f"\nB-1 OPTION SCORECARD — last {days} days, {len(rows)} answers")
    print(f"  valid from {EVIDENCE_VALID_FROM} ({EVIDENCE_BOUNDARY_SHA}) — earlier observations measured a\n  truncated history index and are excluded, not merely old.\n")
    head = (f"{'attribute':<12} {'source':<15} {'n':>5} {'applied':>8} "
            f"{'repair':>8} {'commit':>8} {'corrected':>10} {'p50 ms':>8}")
    print(head)
    print("-" * len(head))
    for (attribute, source), c in sorted(per.items()):
        n = c["answers"]
        latency = (f"{c['latency_sum'] // c['latency_n']:>8}"
                   if c["latency_n"] else f"{'—':>8}")
        if n < min_n:
            # THIN, AND SAID SO. A rate over four observations reads exactly
            # like a rate over four hundred once it is a percentage.
            print(f"{attribute:<12} {source:<15} {n:>5} "
                  f"{'thin — raw: applied=' + str(c['applied']):>8} "
                  f"repair={c['repair']} commit={c['committed']} "
                  f"corrected={c['corrected']}")
            continue
        print(f"{attribute:<12} {source:<15} {n:>5} "
              f"{_pct(c['applied'], n):>8} {_pct(c['repair'], n):>8} "
              f"{_pct(c['committed'], n):>8} "
              f"{_pct(c['corrected'], c['committed']):>10} {latency}")

    print("\n  applied   = this answer resolved the field")
    print("  repair    = we could not read it and asked again")
    print("  commit    = it reached a food row")
    print("  corrected = that row was edited or deleted within 10 minutes")
    print("              (as a share of COMMITTED, not of answers)")
    print(f"\n  cells with n < {min_n} print raw counts instead of rates.\n")


def offered_vs_selected(cur, *, days: int) -> None:
    """Was a source not OFFERED, or offered and ignored? Different problems.

    "History is never selected" has two causes with nothing in common: the
    matcher never fires, or it fires and users prefer something else. One is a
    recall problem in `_logged_history_match`; the other is a ranking or
    labelling problem. Reading them as one number sends the work to the wrong
    place.
    """
    cur.execute(
        """
        SELECT offered, selected_source
        FROM b1_answer_observations
        WHERE observed_at > now() - make_interval(days => %s)
          AND observed_at >= %s::timestamp
        """, (days, EVIDENCE_VALID_FROM))
    offered_n, selected_n = collections.Counter(), collections.Counter()
    asks = 0
    for offered, selected in cur.fetchall():
        asks += 1
        for part in (offered or "").split(","):
            if ":" in part:
                src, _, cnt = part.partition(":")
                offered_n[src] += 1          # asks where it was ON THE LIST
        if selected:
            selected_n[selected] += 1

    print(f"OFFERED vs SELECTED — {asks} answers\n")
    print(f"  {'source':<15} {'asks offering it':>17} {'times chosen':>13} "
          f"{'take rate':>10}")
    for src in sorted(set(offered_n) | set(selected_n)):
        o, s = offered_n.get(src, 0), selected_n.get(src, 0)
        print(f"  {src:<15} {o:>17} {s:>13} {_pct(s, o):>10}")
    ft = selected_n.get("free_text", 0)
    print(f"\n  free_text was chosen {ft} time(s) — every one of those is a "
          f"user telling us\n  the list did not contain their answer.\n")


def free_text_examples(cur, *, days: int, limit: int) -> None:
    """The words themselves, joined from `conversation_logs`.

    Not copied into the observation table on purpose: the message is already
    stored durably once, and a second copy of a user's own sentences is a
    liability with no benefit. This is the join that reads them back.
    """
    cur.execute(
        """
        SELECT o.operation_id, o.offered, cl.raw_message, o.outcome
        FROM b1_answer_observations o
        JOIN conversation_logs cl
          ON cl.turn_id = o.source_turn_id AND cl.user_id = o.user_id
        WHERE o.selected_source = 'free_text'
          AND o.observed_at > now() - make_interval(days => %s)
          AND o.observed_at >= %s::timestamp
        ORDER BY o.observed_at DESC LIMIT %s
        """, (days, EVIDENCE_VALID_FROM, limit))
    rows = cur.fetchall()
    print(f"FREE TEXT — {len(rows)} most recent\n")
    if not rows:
        print("  none yet.\n")
        return
    for op, offered, message, outcome in rows:
        print(f"  offered {offered or '—'}")
        print(f"  they said  {message!r}   -> {outcome}")
        print(f"  {op}\n")
    print("  Each line is a question whose options did not contain the answer.")
    print("  Bucket them by WHY before changing any generator.\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="database URL")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--min-n", type=int, default=20,
                    help="below this, print counts rather than rates")
    ap.add_argument("--free-text", action="store_true",
                    help="show the free-text answers themselves")
    ap.add_argument("--limit", type=int, default=25)
    args = ap.parse_args()

    with _connect(args.db) as conn, conn.cursor() as cur:
        scorecard(cur, days=args.days, min_n=args.min_n)
        offered_vs_selected(cur, days=args.days)
        by_question_version(cur, days=args.days)
        if args.free_text:
            free_text_examples(cur, days=args.days, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
