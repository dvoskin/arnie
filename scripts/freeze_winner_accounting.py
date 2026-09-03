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

EXPECTED = {"identities": 37, "signed": 12, "held": 25}

#: ⭐ THE DELTA, RECONCILED ROW BY ROW RATHER THAN NARRATED.
#:
#: An earlier report read 15 SIGNED / 11 HELD over 26 identities. The freeze
#: reads 13 / 14 over 27. A counts change between two reports is exactly where
#: a SEMANTIC decision can be mistaken for a BOOKKEEPING one, so the movements
#: are enumerated and the arithmetic is checked — a delta nobody can reconstruct
#: is a delta that gets normalised.
#: 2026-09-03 (IR-PUBLISH): the freeze before this one read 12 SIGNED / 15 HELD
#: over 27. Ten identities entered the artifact (query expansion + the restored
#: human annotation layer); every prior winner still seats the row its review
#: covers (checked in build()), so the ten are the whole delta.
PRIOR = {"identities": 27, "signed": 12, "held": 15}

MOVEMENTS = (
    ("butter|", None, "held",
     "NEW under IR-PUBLISH 2026-09-03. Seats usda:173410 (Butter, salted 717 kcal) under rank_v2; no reviewer has looked, held as UNREVIEWED_NEW_IDENTITY."),
    ("chicken|", None, "held",
     "NEW under IR-PUBLISH 2026-09-03. Seats usda:172395 (Chicken, roasting, meat only, cooked, roasted 167 kcal) under rank_v2; no reviewer has looked, held as UNREVIEWED_NEW_IDENTITY."),
    ("coconut oil|", None, "held",
     "NEW under IR-PUBLISH 2026-09-03. Seats usda:171412 (Oil, coconut 892 kcal) under rank_v2; no reviewer has looked, held as UNREVIEWED_NEW_IDENTITY."),
    ("mayonnaise|", None, "held",
     "NEW under IR-PUBLISH 2026-09-03. Seats usda:171009 (Salad dressing, mayonnaise, regular 680 kcal) under rank_v2; no reviewer has looked, held as UNREVIEWED_NEW_IDENTITY."),
    ("mushrooms|fried", None, "held",
     "NEW under IR-PUBLISH 2026-09-03. Seats usda:169253 (Mushrooms, white, stir-fried 26 kcal) under rank_v2; no reviewer has looked, held as UNREVIEWED_NEW_IDENTITY."),
    ("olive oil|", None, "held",
     "NEW under IR-PUBLISH 2026-09-03. Seats usda:171413 (Oil, olive, salad or cooking 884 kcal) under rank_v2; no reviewer has looked, held as UNREVIEWED_NEW_IDENTITY."),
    ("salmon|grilled", None, "held",
     "NEW under IR-PUBLISH 2026-09-03. Seats usda:171999 (Fish, salmon, chinook, cooked, dry heat 231 kcal) under rank_v2; no reviewer has looked, held as UNREVIEWED_NEW_IDENTITY."),
    ("salmon|roasted", None, "held",
     "NEW under IR-PUBLISH 2026-09-03. Seats usda:171999 (Fish, salmon, chinook, cooked, dry heat 231 kcal) under rank_v2; no reviewer has looked, held as UNREVIEWED_NEW_IDENTITY."),
    ("shrimp|fried", None, "held",
     "NEW under IR-PUBLISH 2026-09-03. Seats usda:171970 (Crustaceans, shrimp, mixed species, cooked, breaded 242 kcal) under rank_v2; no reviewer has looked, held as UNREVIEWED_NEW_IDENTITY."),
    ("vegetable oil|", None, "held",
     "NEW under IR-PUBLISH 2026-09-03. Seats usda:172370 (Oil, vegetable, soybean, refined 884 kcal) under rank_v2; no reviewer has looked, held as UNREVIEWED_NEW_IDENTITY."),
    # ⭐ THE POST-REBUILD RE-FREEZE. The seam-capture rebuild grew six ladders
    # and moved two winners; the reviewer kept both old representatives, and
    # the RANKER SEATS NEITHER. The freeze records what production does — a
    # signature naming a row production never seats would be the split-brain
    # authority this phase removed — so the reviewer's preference is carried
    # as the HOLD'S REASON instead.
    # (the 2026-08 egg| SIGNED->HELD movement is already inside PRIOR)
)

#: ⭐⭐ RE-STAMPED, NOT RE-DECIDED. Their ladders grew, so every signature
#: expired as UNVERIFIED — and the winner did not move, so the decision itself
#: still stands and is simply re-asserted over the fuller universe.
#: 2026-09-03 (IR-PUBLISH): thirteen prior ladders grew under query expansion and
#: the restored human annotation layer — and NOT ONE winner moved (the two-mode
#: publication gate and build() both check it), so all thirteen are re-asserted
#: over the fuller universe. Measured, not narrated.
RESTAMPED = ("asparagus|", "banana|", "beef|fried", "beef|grilled", "beef|roasted",
             "broccoli|", "chicken|fried", "chicken|roasted", "mackerel|", "oats|",
             "rice|", "salmon|", "shrimp|")

#: ⛔ AND ONE HOLD CHANGED ITS CAUSE WITHOUT CHANGING ITS COUNT. `mackerel|`
#: was held because `cooking_yield` says nothing about mackerel, so a raw row
#: won an undecided axis. The rebuild seats SALTED instead — 305 kcal against
#: raw's 205, a 49% OVERSTATEMENT — for no reason but that "salted" is a
#: shorter lexical match to a bare query. The blocker is now the ranking
#: defect, not the missing yield entry, and filing it under the old cause
#: would leave it waiting on a fix that cannot reach it.
RECAUSED = (("mackerel|", "cooking_yield_has_no_entry_for_this_food",
             "a specialty variant outranks the generic form"),)


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
    print(f"  ✅ {len(frozen['rows'])}/{EXPECTED['identities']} · {counts['signed']} SIGNED · "
          f"{counts['held']} HELD · 0 failures")
    print(f"  every row binds identity · source-qualified evidence · status ·")
    print(f"  reason · ranking_policy_version · candidate_universe_fingerprint")
    print(f"\n  DELTA FROM {PRIOR['signed']} SIGNED / {PRIOR['held']} HELD / {PRIOR['identities']}, reconciled:")
    for identity, was, now, why in MOVEMENTS:
        print(f"    {identity:<14} {str(was or 'absent'):>7} -> {now:<7} "
              f"{why.split('.')[0]}")

    if "--write" in sys.argv:
        FREEZE_PATH.write_text(json.dumps(frozen, indent=1) + "\n")
        print(f"\n  -> {FREEZE_PATH.name}")
        print(f"  stale signatures: {len(stale_signatures(frozen))}")
