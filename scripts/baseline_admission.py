"""PHASE 1.5 — BASELINE ADMISSION. Adjudicate the first semantic baseline.

    COMMITTED        candidates in the current production artifact
    COLD_DISCOVERY   union across N cold annotation runs
    SOURCE           the complete retrieved evidence universe

    REVIEW_SET = COMMITTED u COLD_DISCOVERY

⭐ MEMBERSHIP IN `REVIEW_SET` GRANTS NO PRICING AUTHORITY. Two things are
true at once and both matter:

    production presence     != automatic semantic admission
    cold-start appearance   != automatic semantic admission

Both merely cause a row to be REVIEWED. A row being in today's artifact does
not prove what semantic relationship should be recorded for it — reconstructing
annotations from historical membership would launder past behaviour into new
semantic truth. And a union of N stochastic runs trends, with enough runs,
toward "everything the model ever once thought might match", which hands
stochasticity a different kind of authority.

So the stochastic system is used as a DISCOVERY INSTRUMENT — it answers
"which rows are unstable enough to need adjudication?" — and never as an
authority. That is a legitimate role for it.

⭐⭐ THE COVERAGE FLOOR. The committed artifact is NON-DESTRUCTIVE during
review: a fresh baseline may not drop a production candidate silently. Only an
explicit reviewed `DIFFERENT_IDENTITY` or a deterministic mechanical veto may
reduce coverage. This converts retention's currently hidden repair behaviour
into explicit durable semantic data, which is the whole point of the step.

Phase 1 measured the gap this closes:

    mackerel|roasted   raw=1   final=4   retention added 3

After admission that must read `raw=4, final=4` — retention repairing nothing.
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ADMIT = "admit"
REJECT = "reject"
UNRESOLVED = "unresolved"

#: ⭐ THREE EXCLUSION CLASSES, NOT TWO. The first version of this report
#: called every unanimously-negative discovery row a "settled negative" and
#: excluded it from review. MEASURED 2026-08-12: of 91 sampled, only 28 (31%)
#: were mechanically vetoed — 63 (69%) were suppressed by MODEL CONSENSUS
#: ALONE, with no human ever seeing them.
#:
#: That is negative admission authority arriving through the back door. The
#: model cannot ADD a row, but ten unanimous calls were permanently removing
#: one. `an absent answer is never a negative` applies to CONSENSUS too, and
#: it had only been applied to single calls.
MECHANICALLY_REJECTED = "mechanically_rejected"   # code excluded it; no review
REVIEWED = "reviewed"                             # a human adjudicated it
UNREVIEWED_NEGATIVE = "unreviewed_negative"       # absent, NOT rejected

EXCLUSION_CLASSES = frozenset({MECHANICALLY_REJECTED, REVIEWED,
                               UNREVIEWED_NEGATIVE})


def exclusion_class(row, reviewed=None) -> str:
    """WHY a pair is absent from the admitted baseline.

    The distinction is load-bearing: an UNREVIEWED_NEGATIVE must never become
    equivalent to a reviewed REJECT in any context where its presence could
    affect pricing. One is a decision; the other is the absence of one.
    """
    key = (row["identity_key"], row["evidence_id"])
    if (reviewed or {}).get(key):
        return REVIEWED
    if row.get("mechanically_vetoed"):
        return MECHANICALLY_REJECTED
    return UNREVIEWED_NEGATIVE


def committed_sets(artifact: dict) -> dict:
    """identity_key -> {evidence_id} currently PRICED in production."""
    out = {}
    for key, entry in (artifact.get("entries") or {}).items():
        out[key] = {f"usda:{c.get('fdc_id')}"
                    for c in (entry.get("candidates") or ())}
    return out


def discovery_report(cold_runs, committed, vetoed_by_identity=None):
    """What review must look at, and why.

    `cold_runs` is a list of {identity_key: {evidence_id: relationship}} —
    one entry per cold annotation run. The report is per (identity, evidence)
    and states everything an adjudicator needs WITHOUT deciding anything.
    """
    vetoed_by_identity = vetoed_by_identity or {}
    seen = defaultdict(lambda: defaultdict(list))
    for run in cold_runs:
        for identity, pairs in run.items():
            for evidence_id, relationship in pairs.items():
                seen[identity][evidence_id].append(relationship)

    rows = []
    identities = set(seen) | set(committed)
    for identity in sorted(identities):
        in_production = committed.get(identity, set())
        observed = seen.get(identity, {})
        for evidence_id in sorted(set(observed) | in_production):
            relationships = observed.get(evidence_id, [])
            counts = {r: relationships.count(r) for r in set(relationships)}
            rows.append({
                "identity_key": identity,
                "evidence_id": evidence_id,
                "production_present": evidence_id in in_production,
                "times_seen": len(relationships),
                "of_runs": len(cold_runs),
                "relationships": counts,
                "mechanically_vetoed":
                    evidence_id in vetoed_by_identity.get(identity, set()),
                # A row is stable only if production and EVERY cold run agree.
                # Anything else is a question for a human.
                "review_required": not (
                    evidence_id in in_production
                    and len(relationships) == len(cold_runs)
                    and len(counts) == 1),
            })
    return rows


def coverage_floor_violations(committed, proposed, dispositions):
    """Production candidates a proposed baseline would DROP without a reason.

    A drop is legitimate only when review explicitly said REJECT, or a
    deterministic mechanical veto applies. Anything else is the silent
    coverage loss retention has been hiding.
    """
    out = []
    for identity, in_production in committed.items():
        keeping = proposed.get(identity, set())
        for evidence_id in sorted(in_production - keeping):
            decision = (dispositions.get(identity, {}) or {}).get(evidence_id)
            if decision not in (REJECT,):
                out.append({
                    "identity_key": identity,
                    "evidence_id": evidence_id,
                    "disposition": decision or "(none)",
                    "why": "production candidate dropped with no reviewed "
                           "REJECT and no mechanical veto",
                })
    return out


#: Relationships that could make a row compete to price.
_POSITIVE = frozenset({"SAME_IDENTITY", "COMPATIBLE_SPECIALIZATION"})


def summarise(rows, reviewed=None) -> dict:
    positive = lambda r: bool(set(r["relationships"]) & _POSITIVE)
    excluded = [r for r in rows if not r["production_present"]
                and r["times_seen"] and not positive(r)]
    classes = {}
    for r in excluded:
        c = exclusion_class(r, reviewed)
        classes[c] = classes.get(c, 0) + 1
    return {
        "pairs": len(rows),
        # ⚠ RENAMED. This counted 232 mechanically_rejected + 683
        # unreviewed_negative + 35 queue = 950 and called them all "review
        # required", while the report simultaneously said the queue was 35.
        # Both statements cannot be true. `review_required` is now reserved
        # for the actual queue; this is the population it is drawn FROM.
        "non_production_discovery": sum(1 for r in rows
                                        if r["review_required"]),
        "production_only": sum(1 for r in rows
                               if r["production_present"] and not r["times_seen"]),
        "unstable_relationship": sum(1 for r in rows
                                     if len(r["relationships"]) > 1),
        "positive_proposals": sum(1 for r in rows
                                  if not r["production_present"] and positive(r)),
        "review_required": sum(1 for r in rows
                               if len(r["relationships"]) > 1
                               or (not r["production_present"] and positive(r))),
        # ⭐ THE CORRECTED BREAKDOWN. "Settled negative" was never a category;
        # it conflated a deterministic rule with a model consensus.
        "excluded_total": len(excluded),
        MECHANICALLY_REJECTED: classes.get(MECHANICALLY_REJECTED, 0),
        REVIEWED: classes.get(REVIEWED, 0),
        UNREVIEWED_NEGATIVE: classes.get(UNREVIEWED_NEGATIVE, 0),
    }


def risk_columns(row, candidates_by_identity, rank):
    """What ADMITTING or REMOVING this row would actually do.

    ⭐ VOTE SPLIT IS NOT RISK. A 5/5 coin flip on a low-ranked row and a 2/10
    flip on the WINNER are the same instability and wildly different
    consequences. Review should be ranked by what changes, not by how
    uncertain the model was.
    """
    identity = row["identity_key"]
    present = list(candidates_by_identity.get(identity) or ())
    ev = row["evidence_id"]

    def kcal(winner):
        return ((winner or {}).get("per100g") or {}).get("calories")

    now, _ = rank(identity, present)
    without = [c for c in present
               if f"usda:{c.get('fdc_id')}" != ev]
    after, _ = rank(identity, without) if without else (None, None)

    is_winner = bool(now and f"usda:{now.get('fdc_id')}" == ev)
    return {
        "is_current_winner": is_winner,
        "winner_now": (now or {}).get("fdc_id"),
        "winner_if_removed": (after or {}).get("fdc_id"),
        "kcal_now": kcal(now),
        "kcal_if_removed": kcal(after),
        "price_delta_if_removed": (
            None if kcal(now) is None or kcal(after) is None
            else round(kcal(after) - kcal(now), 1)),
    }


def main() -> int:
    from skills.nutrition import pricing_artifact as art

    artifact = json.loads(art.ARTIFACT_PATH.read_text())
    committed = committed_sets(artifact)
    print(f"COMMITTED artifact: {len(committed)} identities, "
          f"{sum(len(v) for v in committed.values())} priced candidates")
    print("\nThis script is the REVIEW INSTRUMENT. It decides nothing.")
    print("Membership in the review set grants no pricing authority:")
    print("  production presence   != automatic semantic admission")
    print("  cold-start appearance != automatic semantic admission")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ── ⭐ THE CONSEQUENCE FRONTIER — why 683 rows may stay unreviewed ─────────
#
# An UNREVIEWED_NEGATIVE is not a rejection. Ten unanimous DIFFERENT_IDENTITY
# votes do not reject anything; they merely mean nothing NOMINATED the row for
# immediate human attention. That keeps "the model is discovery only, never
# authority" genuinely true rather than true-except-for-683-rows.
#
# THE DURABLE RULE:
#
#     An UNREVIEWED_NEGATIVE may remain unreviewed only while deterministic
#     analysis proves that admitting it cannot affect the current winner,
#     price, eligibility or fallback rung. The moment it becomes consequential
#     the build FAILS CLOSED into human review.
#
# ⭐⭐ AND THE INVERSE, FUTURE-RISK CONDITION. A row that is harmless only
# because a stronger candidate currently exists is NOT forever harmless. So
# the frontier is computed by LEAVE-ONE-OUT over higher-ranked candidates —
# modelling actual future artifact drift — rather than by guessing a calorie
# band. A kcal proxy would be an arbitrary threshold pretending to be a rule.

#: ⭐ IDENTITY STATE IS EVALUATED BEFORE ROW CONSEQUENCE. The first frontier
#: conflated "this identity has no coverage" with "this identity has ONE
#: candidate that would become decisive". Those are OPPOSITE states, and
#: treating them alike escalated 572 rows of noise: `asparagus|fried` has no
#: artifact entry at all, so every row under it reported "would price alone"
#: about an identity that prices nothing.
COVERED = "covered"
UNCOVERED = "uncovered"
UNKNOWN_COVERAGE = "unknown_coverage"

#: A row under an uncovered identity cannot affect a price that does not
#: exist. NOT "harmless" — out of scope FOR NOW, which is a different claim.
OUT_OF_SCOPE = "out_of_scope_for_current_pricing"

#: ⭐⭐ THE PREMISE A VERDICT RESTS ON IS RECORDED WITH IT, so that when the
#: premise stops holding the verdict is recomputed rather than inherited.
#:
#: Two premises, two triggers — and the second was a GAP found in review.
#: `identity_gained_coverage` covers an out-of-scope row whose identity later
#: starts pricing. But a row judged INERT was judged against TODAY'S candidate
#: set: if one existing candidate disappears, is replaced, re-ranks, or
#: becomes mechanically vetoed, that row can turn consequential WITHOUT the
#: identity ever transitioning uncovered -> covered. Coverage gain is a
#: special case of candidate-set change, not the general one.
COVERAGE_GAINED = "identity_gained_coverage"
CANDIDATE_SET_CHANGED = "candidate_set_fingerprint_change"


def candidate_set_fingerprint(candidates) -> str:
    """What an inert verdict was judged AGAINST.

    Membership AND order, because the ranker's choice depends on both. A
    re-rank with identical membership can change the winner, which is exactly
    the case a membership-only fingerprint would miss.
    """
    import hashlib

    material = "|".join(str(c.get("fdc_id")) for c in (candidates or ()))
    return "sha256:" + hashlib.sha256(material.encode()).hexdigest()[:16]


def revalidation_triggers(before, after) -> dict:
    """identity -> why its stored frontier verdicts must be recomputed."""
    out = {}
    for identity in sorted(set(before or {}) | set(after or {})):
        was, now = (before or {}).get(identity) or [], \
            (after or {}).get(identity) or []
        if not was and now:
            out[identity] = COVERAGE_GAINED
        elif candidate_set_fingerprint(was) != candidate_set_fingerprint(now):
            out[identity] = CANDIDATE_SET_CHANGED
    return out


def identity_state(identity_key, candidates_by_identity) -> str:
    """COVERED / UNCOVERED / UNKNOWN — decided before any row is judged."""
    if candidates_by_identity is None:
        return UNKNOWN_COVERAGE
    return COVERED if (candidates_by_identity.get(identity_key) or ()) \
        else UNCOVERED


def coverage_change_invalidates(before, after) -> tuple:
    """Identities that were UNCOVERED and now are COVERED.

    Every unreviewed negative under them must be re-run through the frontier:
    their `out_of_scope` verdict was true only while the identity priced
    nothing, and that premise has now changed.
    """
    return tuple(sorted(
        k for k in (after or {})
        if identity_state(k, after) == COVERED
        and identity_state(k, before or {}) != COVERED))


#: How many higher-ranked candidates may disappear before a row is considered
#: potentially winning. 1 models ordinary drift; raising it widens the
#: frontier and is a deliberate, versioned policy choice.
CONSEQUENCE_DEPTH = 1

#: Macro movement that counts as a price change, in kcal per 100 g.
PRICE_TOLERANCE_KCAL = 0.0


def consequential(row, present, rank, *, depth=CONSEQUENCE_DEPTH,
                  coverage=None):
    """Could admitting this row matter — now, or after bounded drift?

    Returns (bool, reason). Deterministic: same inputs, same answer, forever.
    """
    identity = row["identity_key"]
    ev = row["evidence_id"]
    candidate = row.get("record")

    # IDENTITY STATE FIRST. A row cannot change a price that does not exist.
    state = identity_state(identity, coverage)
    if state == UNKNOWN_COVERAGE:
        return True, "unknown_identity_coverage_fails_closed"
    if state == UNCOVERED:
        return False, OUT_OF_SCOPE

    if candidate is None:
        # We cannot evaluate it. That is UNKNOWN, and unknown fails CLOSED
        # into review rather than being assumed harmless — the same invariant
        # that governs every other absence in this system.
        return True, "unevaluable_row_fails_closed"

    now, _ = rank(identity, present)
    with_row, _ = rank(identity, list(present) + [candidate])
    if (now or {}).get("fdc_id") != (with_row or {}).get("fdc_id"):
        return True, "admitting_it_changes_the_winner_now"

    def kcal(w):
        return ((w or {}).get("per100g") or {}).get("calories")
    a, b = kcal(now), kcal(with_row)
    if a is not None and b is not None and abs(b - a) > PRICE_TOLERANCE_KCAL:
        return True, "admitting_it_changes_the_price_now"
    if not present:
        # Reachable only for a COVERED identity, i.e. one whose candidate list
        # is genuinely empty here — not the uncovered case, which returned
        # OUT_OF_SCOPE above.
        return True, "no_other_candidate_so_it_would_price_alone"

    # FUTURE RISK: could it win if higher-ranked candidates disappear?
    ordered = sorted(present, key=lambda c: 0 if now and
                     c.get("fdc_id") == now.get("fdc_id") else 1)
    for k in range(1, depth + 1):
        thinner = ordered[k:]
        w, _ = rank(identity, list(thinner) + [candidate])
        if w and str(w.get("fdc_id")) == ev.replace("usda:", ""):
            return True, f"would_win_after_{k}_candidate_removal"
    return False, "cannot_affect_outcome_within_the_frontier"


def frontier_report(unreviewed, candidates_by_identity, rank):
    """Split UNREVIEWED_NEGATIVE into may-stay-unreviewed vs must-be-reviewed."""
    stay, escalate = [], []
    for row in unreviewed:
        present = list(candidates_by_identity.get(row["identity_key"]) or ())
        hit, reason = consequential(row, present, rank,
                                    coverage=candidates_by_identity)
        record = {**row, "frontier_reason": reason,
                  "coverage_state": identity_state(row["identity_key"],
                                                   candidates_by_identity),
                  # The premise the verdict rests on. When it stops holding,
                  # the verdict must be recomputed rather than inherited.
                  # EVERY stay-unreviewed verdict records its premise. An
                  # out-of-scope row is premised on the identity pricing
                  # nothing; an inert row is premised on the candidate set it
                  # was judged against — and that set is fingerprinted so the
                  # premise is checkable rather than remembered.
                  "revalidate_on": (COVERAGE_GAINED if reason == OUT_OF_SCOPE
                                    else CANDIDATE_SET_CHANGED),
                  "judged_against": ("" if reason == OUT_OF_SCOPE
                                     else candidate_set_fingerprint(present))}
        (escalate if hit else stay).append(record)
    return stay, escalate


# ── THE ADJUDICATION WORKSHEET ────────────────────────────────────────────
#
# What a human reads and decides on. Two design rules, both learned the hard
# way in this phase:
#
#   ORDER BY CONSEQUENCE, NOT UNCERTAINTY. `mayonnaise| usda:173594` at a 5/5
#   vote split looks maximally alarming and moves nothing;
#   `mackerel|roasted usda:175120` at 8/2 IS the winner. Sorting by vote split
#   would put the reviewer's attention in exactly the wrong place.
#
#   EVERY DECISION CARRIES A REASON, NOT JUST A LABEL. Six months from now
#   "obviously the same food" and "kept for coverage continuity" must be
#   distinguishable — the second is the one that will need re-examining.

WORKSHEET_COLUMNS = (
    "identity_key", "evidence_id", "description",
    "kcal_per_100g", "protein_per_100g",
    "production_present", "vote_split", "mechanically_vetoed",
    "coverage_state", "source",
    "is_current_winner", "winner_now", "winner_if_removed",
    "price_delta_if_removed", "frontier_reason",
    # filled by the reviewer
    "disposition", "reason",
)


def worksheet(queue, frontier_escalations, candidates_by_identity, rank,
              records_by_identity=None):
    """One row per pair needing adjudication, ordered by consequence."""
    records_by_identity = records_by_identity or {}
    seen, out = set(), []
    for source, rows in (("unstable_or_proposed", queue),
                         ("frontier_escalation", frontier_escalations)):
        for row in rows:
            key = (row["identity_key"], row["evidence_id"])
            if key in seen:
                continue
            seen.add(key)
            record = (row.get("record")
                      or records_by_identity.get(row["identity_key"], {})
                      .get(row["evidence_id"]) or {})
            per = record.get("per100g") or {}
            risk = risk_columns({**row, "record": record},
                                candidates_by_identity, rank)
            out.append({
                "identity_key": row["identity_key"],
                "evidence_id": row["evidence_id"],
                "description": record.get("description", ""),
                "kcal_per_100g": per.get("calories"),
                "protein_per_100g": per.get("protein"),
                "production_present": row.get("production_present"),
                "vote_split": row.get("relationships") or {},
                "mechanically_vetoed": row.get("mechanically_vetoed"),
                "coverage_state": row.get(
                    "coverage_state",
                    identity_state(row["identity_key"], candidates_by_identity)),
                "source": source,
                "frontier_reason": row.get("frontier_reason", ""),
                **risk,
                "disposition": "",   # ADMIT | REJECT | UNRESOLVED
                "reason": "",        # required — a label alone is not a record
            })

    def consequence(r):
        return (0 if r["is_current_winner"] else 1,
                -abs(r["price_delta_if_removed"] or 0),
                0 if r["frontier_reason"].startswith("would_win") else 1,
                r["identity_key"], r["evidence_id"])

    return sorted(out, key=consequence)


def unsigned_rows(worksheet_rows) -> tuple:
    """Rows a reviewer has not finished. A disposition with no reason is NOT
    finished — that is the whole point of requiring both."""
    return tuple(r for r in worksheet_rows
                 if not r.get("disposition") or not r.get("reason"))
