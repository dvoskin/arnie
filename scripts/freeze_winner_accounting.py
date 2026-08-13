"""PHASE 0 STEP 3 — FREEZE THE WINNER ACCOUNTING.

Each row binds six things, and every one of them exists because leaving it out
was survivable right up until it was not:

    identity_key                  what was asked for
    winner_evidence_id            SOURCE-QUALIFIED. `usda:173089`, never
                                  `173089` — the destructive path already
                                  proved a bare number merges two providers
    winner_status                 SIGNED | HELD
    reason                        why, in words, from a closed vocabulary
    ranking_policy_version        WHICH POLICY produced this winner. Nine
                                  identities once priced differently by user
                                  and nobody could say which regime decided
                                  any of them
    candidate_universe_fingerprint  WHAT THE WINNER BEAT. A winner is a
                                  statement about a field; the same row
                                  winning a different field is a different
                                  fact, and without this the signature would
                                  silently survive the field changing under it

⭐ THE FINGERPRINT IS THE ONE THAT MAKES A SIGNATURE EXPIRE HONESTLY. A
reviewer signed "this row is the representative one" while looking at a
specific ladder. Add a better candidate tomorrow and that sentence has not
become false — it has become UNVERIFIED, which is a different state and the
one this phase keeps insisting on. `stale_signatures()` reports it rather
than re-deriving agreement.

⭐⭐ AND IT IS COMPUTED UNDER A DECLARED REGIME, NOT AN INHERITED ONE. The
freeze runs inside `ranking_regime(PHASE_0_REGIME)`, so a developer's exported
flag cannot move what gets written down as frozen.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

from scripts import winner_review as wr
from skills.nutrition import pricing_artifact as art
from skills.nutrition.v2_gate import PHASE_0_REGIME, ranking_regime

FREEZE_PATH = (pathlib.Path(__file__).resolve().parents[1]
               / "data" / "baseline" / "phase_0_winner_freeze.json")

EXPECTED = {"identities": 27, "signed": 13, "held": 14}

#: ⭐ THE DELTA, RECONCILED ROW BY ROW RATHER THAN NARRATED.
#:
#: An earlier report read 15 SIGNED / 11 HELD over 26 identities. The freeze
#: reads 13 / 14 over 27. A counts change between two reports is exactly where
#: a SEMANTIC decision can be mistaken for a BOOKKEEPING one, so the movements
#: are enumerated and the arithmetic is checked — a delta nobody can reconstruct
#: is a delta that gets normalised.
PRIOR = {"identities": 26, "signed": 15, "held": 11}

MOVEMENTS = (
    ("potato|", None, "held",
     "ADDED. Absent from the earlier count because its winner was REJECTED "
     "evidence (the part-of-food raw-skin row) and a rejected row may hold no "
     "winner state. The artifact rebuild removed it; the successor at 132 kcal "
     "is held for representativeness. 26 identities -> 27."),
    ("asparagus|", "signed", "held",
     "SIGNED -> HELD. Deriving the undecided-cooked-axis population from "
     "`cooked_preference_state` instead of from the two rows whose kcal gap was "
     "obvious found six, not two. Raw may well be right for a bare vegetable — "
     "nothing DECIDED it."),
    # ⚠ "Same derivation." was the original text here, and the gate requiring
    # a movement to actually EXPLAIN itself rejected it. A cross-reference is
    # not a reason: whoever reads this row later has the row, not the one
    # above it.
    ("broccoli|", "signed", "held",
     "SIGNED -> HELD. Its ladder carries 4 raw and 6 cooked rows on an "
     "undecided cooked axis, so the raw winner was selected with no policy "
     "governing raw-vs-cooked for this food."),
    ("cauliflower|", "signed", "held",
     "SIGNED -> HELD. Its ladder carries 1 raw and 4 cooked rows on an "
     "undecided cooked axis, so the raw winner was selected with no policy "
     "governing raw-vs-cooked for this food."),
    ("beef|roasted", "held", "signed",
     "HELD -> SIGNED. Re-adjudicated against the reworked preference: the "
     "'lab sample' label was WRONG — 'ribs prepared, fast roasted' is an "
     "ordinary row, not a lean-only reference, so the preference was never "
     "going to move it. Stable under both regimes, and hand-signed ADMIT."),
)


def reconcile_delta() -> tuple:
    """Prove the counts moved by exactly the movements claimed."""
    failures = []
    signed = PRIOR["signed"]
    held = PRIOR["held"]
    identities = PRIOR["identities"]
    for identity, was, now, _why in MOVEMENTS:
        if was == "signed":
            signed -= 1
        elif was == "held":
            held -= 1
        elif was is None:
            identities += 1
        else:
            failures.append(f"{identity}: unknown prior state {was!r}")
        if now == "signed":
            signed += 1
        elif now == "held":
            held += 1
        else:
            failures.append(f"{identity}: unknown new state {now!r}")

    if signed != EXPECTED["signed"]:
        failures.append(f"movements imply {signed} signed, freeze says "
                        f"{EXPECTED['signed']}")
    if held != EXPECTED["held"]:
        failures.append(f"movements imply {held} held, freeze says "
                        f"{EXPECTED['held']}")
    if identities != EXPECTED["identities"]:
        failures.append(f"movements imply {identities} identities, freeze says "
                        f"{EXPECTED['identities']}")
    for identity, _was, _now, why in MOVEMENTS:
        if not why.strip():
            failures.append(f"{identity}: movement with no stated reason")
    return tuple(failures)


def candidate_universe_fingerprint(entry: dict) -> str:
    """The ORDERED, source-qualified field the winner was chosen from.

    Ordered because the ranker's tie-breaks read order, so a reshuffled field
    is a different field even with identical membership. Source-qualified
    because two providers' local ids collide and a fingerprint that merged
    them would call two different universes the same.
    """
    ids = [art.candidate_evidence_id(c) for c in (entry.get("candidates") or ())]
    return hashlib.sha256("␟".join(ids).encode()).hexdigest()[:16]


def build() -> dict:
    document = json.loads(art.ARTIFACT_PATH.read_text())
    entries = document.get("entries") or {}
    reviewed = wr.by_identity()
    rows = []

    with ranking_regime(PHASE_0_REGIME) as regime:
        import core.food_intelligence as fi
        from core.canonical_pricing import _ranker_query

        for identity in sorted(entries):
            entry = entries[identity]
            candidates = list(entry.get("candidates") or ())
            if not candidates:
                continue
            entity, _, preparation = identity.partition("|")
            winner, _conf = fi.best_candidate(_ranker_query(entity, preparation),
                                              candidates)
            if winner is None:
                raise SystemExit(
                    f"{identity} prices from nothing under {regime}; the "
                    f"reachability invariant must hold before a freeze")
            evidence = art.candidate_evidence_id(winner)
            if identity not in reviewed:
                raise SystemExit(f"{identity} has no winner-review state")
            signed_evidence, status, cause, note = reviewed[identity]
            if signed_evidence != evidence:
                raise SystemExit(
                    f"{identity}: the ranker seats {evidence} but the review "
                    f"covers {signed_evidence} — the regime moved under it")
            rows.append({
                "identity_key": identity,
                "winner_evidence_id": evidence,
                "winner_status": status,
                "reason": cause or note,
                "note": note,
                "ranking_policy_version": regime,
                "candidate_universe_fingerprint":
                    candidate_universe_fingerprint(entry),
                "candidate_count": len(candidates),
            })
    return {"regime": PHASE_0_REGIME, "rows": rows}


def verify(frozen: dict) -> tuple:
    """Every condition the freeze claims, recomputed rather than trusted."""
    failures = []
    rows = frozen.get("rows") or []
    counts = {"signed": 0, "held": 0}

    if len(rows) != EXPECTED["identities"]:
        failures.append(f"{len(rows)} identities, expected "
                        f"{EXPECTED['identities']}")
    seen = set()
    for row in rows:
        identity = row["identity_key"]
        if identity in seen:
            failures.append(f"{identity} appears twice")
        seen.add(identity)
        if ":" not in row["winner_evidence_id"]:
            failures.append(f"{identity}: winner evidence is not "
                            f"source-qualified: {row['winner_evidence_id']}")
        if row["winner_status"] not in wr.WINNER_STATES:
            failures.append(f"{identity}: {row['winner_status']!r}")
        else:
            counts[row["winner_status"]] += 1
        if not str(row.get("reason") or "").strip():
            failures.append(f"{identity}: no reason")
        if row["ranking_policy_version"] != PHASE_0_REGIME:
            failures.append(f"{identity}: frozen under "
                            f"{row['ranking_policy_version']}, not "
                            f"{PHASE_0_REGIME}")
        if len(row.get("candidate_universe_fingerprint") or "") != 16:
            failures.append(f"{identity}: no candidate universe fingerprint")
        if row["winner_status"] == wr.HELD and \
                row["reason"] not in wr.BLOCKING_CAUSES:
            failures.append(f"{identity}: HELD without a blocking cause")

    for state in ("signed", "held"):
        if counts[state] != EXPECTED[state]:
            failures.append(f"{counts[state]} {state}, expected "
                            f"{EXPECTED[state]}")
    return tuple(failures)


def stale_signatures(frozen: dict) -> tuple:
    """Rows whose candidate universe has moved since they were frozen.

    ⭐ NOT "WRONG" — UNVERIFIED. The reviewer's sentence was true about the
    field they saw. A changed field does not falsify it; it removes the thing
    that made it checkable, and reporting that is the whole point.
    """
    document = json.loads(art.ARTIFACT_PATH.read_text())
    entries = document.get("entries") or {}
    stale = []
    for row in frozen.get("rows") or []:
        entry = entries.get(row["identity_key"])
        if entry is None:
            stale.append((row["identity_key"], "identity gone"))
            continue
        now = candidate_universe_fingerprint(entry)
        if now != row["candidate_universe_fingerprint"]:
            stale.append((row["identity_key"],
                          f"{row['candidate_universe_fingerprint']} -> {now}"))
    return tuple(stale)


if __name__ == "__main__":
    frozen = build()
    failures = tuple(reconcile_delta()) + verify(frozen)
    print(f"  regime {frozen['regime']}   rows {len(frozen['rows'])}\n")
    for failure in failures:
        print(f"    ⛔ {failure}")
    if failures:
        raise SystemExit(1)

    counts = {"signed": 0, "held": 0}
    for row in frozen["rows"]:
        counts[row["winner_status"]] += 1
    print(f"  ✅ {len(frozen['rows'])}/27 · {counts['signed']} SIGNED · "
          f"{counts['held']} HELD · 0 failures")
    print(f"  every row binds identity · source-qualified evidence · status ·")
    print(f"  reason · ranking_policy_version · candidate_universe_fingerprint")
    print(f"\n  DELTA FROM 15 SIGNED / 11 HELD / 26, reconciled:")
    for identity, was, now, why in MOVEMENTS:
        print(f"    {identity:<14} {str(was or 'absent'):>7} -> {now:<7} "
              f"{why.split('.')[0]}")

    if "--write" in sys.argv:
        FREEZE_PATH.write_text(json.dumps(frozen, indent=1) + "\n")
        print(f"\n  -> {FREEZE_PATH.name}")
        print(f"  stale signatures: {len(stale_signatures(frozen))}")
