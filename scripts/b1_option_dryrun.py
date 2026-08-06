#!/usr/bin/env python3
"""OPTION-SET QUALITY, WITHOUT WAITING FOR TRAFFIC.

WHAT THIS CAN AND CANNOT ANSWER — read this before quoting a number from it.

CAN. Whether the option sets we generate are any good is a property of OUR
system, not of users. Given a real food name and a real logged history, the
producer is deterministic: how many options it offers, how far apart they are,
whether history contributes, whether the set degenerates. None of that needs a
person to answer a question.

CANNOT. Whether people ACCEPT those options. Acceptance, free-text rate and its
reasons, correction-within-ten-minutes and abandonment are facts about human
choice. Synthesising an answer measures our model of the user, not the user —
which is the exact failure that produced four defects in this slice, moved up
to the analysis layer. Those metrics stay open until real usage, and this
script deliberately reports none of them.

REAL FOODS, NOT INVENTED ONES. The corpus is the user's own logged history, so
the distribution of foods is the distribution that actually occurs. A synthetic
food list would test the ontology against our imagination of a diet.

The finding that motivated it: a chicken-breast question offered `6 oz` and
`16 oz` and nothing between — a 2.5x gap on a food eaten constantly. Under the
standing bias-high rule, "not sure" then commits 435 g. One instance is an
anecdote; this measures how common the shape is.

Usage:
    python scripts/b1_option_dryrun.py --db "$DATABASE_URL" --user 26
    python scripts/b1_option_dryrun.py --db ... --user 26 --limit 60 --verbose
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

# Run from anywhere: the repo root is this file's parent, and the producer
# under test lives there.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

#: A pair this far apart with nothing between is not a choice, it is a fork.
DEGENERATE_GAP = 2.0


def _connect(url: str):
    import psycopg
    return psycopg.connect(url.replace("+psycopg", ""), connect_timeout=25)


def _real_foods(cur, user_id: int, limit: int):
    """The foods this person actually eats, most-logged first."""
    cur.execute(
        """
        SELECT f.parsed_food_name, COUNT(*) AS n,
               COUNT(*) FILTER (WHERE f.estimated_flag = false) AS trusted
        FROM food_entries f JOIN daily_logs d ON d.id = f.daily_log_id
        WHERE d.user_id = %s AND d.date >= CURRENT_DATE - 90
          AND f.parsed_food_name IS NOT NULL
        GROUP BY 1 ORDER BY n DESC LIMIT %s
        """, (user_id, limit))
    return cur.fetchall()


def _history_grams_offline(cur, user_id: int, food_name: str):
    """`_history_grams`' rule, run through psycopg.

    Replicated rather than imported because the async engine hangs against
    production; the RULE is the part under test, so it is kept identical:
    >=2 content tokens, exact content-token-set equality, estimated_flag False,
    90 days — and no cross-food row cap, which is the bug this measures.
    """
    from handlers.tool_executor import _content_tokens
    from skills.nutrition.normalize import normalize_quantity

    tokens = _content_tokens(food_name)
    if len(tokens) < 2:
        return None, "name has fewer than two content tokens"
    cur.execute(
        """
        SELECT f.parsed_food_name, f.quantity
        FROM food_entries f JOIN daily_logs d ON d.id = f.daily_log_id
        WHERE d.user_id = %s AND d.date >= CURRENT_DATE - 90
          AND f.estimated_flag = false AND f.quantity IS NOT NULL
        ORDER BY d.date DESC, f.id DESC LIMIT 2000
        """, (user_id,))
    seen_name = False
    for name, quantity in cur.fetchall():
        if _content_tokens(name or "") != tokens:
            continue
        seen_name = True
        nq = normalize_quantity(quantity or "", name or "")
        if nq is not None and getattr(nq, "grams", None):
            return float(nq.grams), ""
    return None, ("matched a prior row but its quantity would not normalise"
                  if seen_name else "no exact trusted prior")


def _ontology_options(food_name: str, hist_grams=None):
    """What the user would actually SEE, collapsing included.

    THE FIRST VERSION OF THIS FUNCTION MEASURED THE WRONG STAGE. It reported
    the raw ontology anchors and skipped `_collapse_by_label`, so it printed
    "0 degenerate sets" while production had demonstrably just offered
    `6 oz` and `16 oz` for chicken breast. Collapsing is precisely where a
    three-anchor set becomes a two-option fork: `_everyday_labels` can render
    the lower and median anchors identically, or near enough that `_near`
    merges them, and the survivors are re-rendered afterwards.

    So the real `_collapse_by_label` runs here, over the real candidate
    objects, and what comes back is the option row as it reaches the screen.
    """
    from skills.nutrition.quantity_clarification import (MIN_USEFUL_SPREAD,
                                                        _collapse_by_label)
    from skills.nutrition.portions import distribution_for

    dist = distribution_for("some", food_name)
    if dist is None or not dist.lower_g:
        return (), None
    wide = dist.upper_g / max(dist.lower_g, 1e-6) >= MIN_USEFUL_SPREAD
    grams = [g for g in (((dist.lower_g, dist.median_g, dist.upper_g) if wide
                          else (dist.median_g,))) if g]
    # History outranks the ontology and joins the same collapse pass, which is
    # how it can absorb an anchor that says the same thing.
    if hist_grams:
        grams = [hist_grams] + [g for g in grams]
    grams.sort()

    class _C:
        def __init__(self, g):
            self.semantic_value = type("q", (), {"grams": g})()

    chosen = [_C(g) for g in grams]
    survivors, labels = _collapse_by_label(chosen, list(chosen), food_name)
    return tuple(zip(labels, [float(c.semantic_value.grams)
                              for c in survivors])), dist


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--user", type=int, required=True)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    shapes = collections.Counter()
    by_spec = collections.defaultdict(lambda: [0, 0])   # spec -> [foods, degenerate]
    degenerate, no_options, with_history = [], [], []
    rows_seen = 0

    with _connect(args.db) as conn, conn.cursor() as cur:
        foods = _real_foods(cur, args.user, args.limit)
        print(f"\nB-1 OPTION DRY RUN — {len(foods)} most-logged foods, user "
              f"{args.user}, last 90 days")
        print("  real foods, real history, deterministic producer. "
              "NO synthetic answers.\n")
        for name, n, trusted in foods:
            rows_seen += 1
            hist, why = _history_grams_offline(cur, args.user, name)
            options, dist = _ontology_options(name, hist)

            labels = [l for l, _g in options]
            grams = [g for _l, g in options]
            if hist:
                with_history.append(name)
            shapes[len(labels)] += 1

            spec = getattr(getattr(dist, "specificity", None), "value", "?")
            gap = (max(grams) / min(grams)) if len(grams) >= 2 else None
            bad = (not options) or (len(options) == 2 and gap
                                    and gap >= DEGENERATE_GAP)
            by_spec[spec][0] += 1
            if bad:
                by_spec[spec][1] += 1
            if not options:
                no_options.append(name)
            elif bad:
                degenerate.append((name, n, labels, gap))

            if args.verbose or bad:
                flag = "  <-- DEGENERATE" if bad else ""
                g = f" gap={gap:.1f}x" if gap else ""
                print(f"  {n:3}x {name[:40]:42} {labels}{g} spec={spec}{flag}")
                if not hist and args.verbose:
                    print(f"        history: {why}")

    print(f"\n  option-count distribution: "
          f"{dict(sorted(shapes.items()))}")
    print(f"  history contributed on {len(with_history)}/{rows_seen} foods")
    if with_history:
        print(f"    e.g. {', '.join(with_history[:5])}")
    print(f"  foods with NO options at all: {len(no_options)}")
    if no_options:
        print(f"    {', '.join(no_options[:6])}")
    print(f"  degenerate sets (2 options, >={DEGENERATE_GAP}x apart): "
          f"{len(degenerate)}")
    for name, n, labels, gap in degenerate[:10]:
        print(f"    {n:3}x {name[:40]:42} {labels} gap={gap:.1f}x")

    print("\n  BY ONTOLOGY SPECIFICITY — where the degeneracy actually lives:")
    for spec, (total, bad) in sorted(by_spec.items()):
        share = f"{100.0 * bad / total:4.0f}%" if total else "   —"
        note = ("  <- no ontology row; generic fallback bracket"
                if spec == "piece" else "")
        print(f"    {spec:10} {total:3} foods, {bad:2} degenerate ({share}){note}")

    print("\n  ELIGIBILITY IS NOT APPLIED. `is_eligible` needs a decision with")
    print("  staged items, which cannot be built from a food name — so this is")
    print("  the corpus of foods LOGGED, not the corpus B-1 would ASK about.")
    print("  A branded bar may be declined as identity_ambiguous and never")
    print("  reach a question. Read the per-specificity rates, not the total.")
    print("\n  NOT measured here, and not measurable without real usage: "
          "acceptance,\n  free-text rate and its reasons, correction rate, "
          "abandonment.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
