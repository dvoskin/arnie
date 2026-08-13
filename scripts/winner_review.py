"""PHASE 0.9 — THE SECOND SIGNATURE, and why one was never enough.

    ADMISSION      "is this legitimate evidence for this food identity?"
    WINNER REVIEW  "is this the representative row we want pricing to choose?"

The 24-row triage forced these apart. Several rows pass the first and fail the
second: "Mushrooms, shiitake, cooked" IS a mushroom, and it is not what a
person means by "mushrooms". "Chicken, roasting, meat only" IS roast chicken,
and it is a USDA lab sample rather than a meal.

⛔ DO NOT USE `REJECT` TO COMPENSATE FOR A RANKING WEAKNESS. Rejecting the
shiitake row to stop it winning would write down that shiitake is not a
mushroom — a durable semantic falsehood, kept forever, to work around a ranker
the next fix will change anyway. **A ranking-policy defect must never be
laundered into the semantic baseline.**

So a pair carries two independent states:

    semantic disposition   ADMIT | REJECT | UNRESOLVED   durable, about identity
    winner status          SIGNED | HELD                 provisional, about policy

`ADMIT + HELD` is the honest encoding for a row that is real evidence whose
selection as canonical winner rests on a policy known to be provisional. It is
what keeps the baseline true while the ranking regime is still moving — and it
is the difference between "we decided" and "we have not decided yet", which is
the same distinction `UNRESOLVED` draws one layer up.
"""
from __future__ import annotations

from scripts import baseline_signatures as bs

SIGNED, HELD = "signed", "held"
WINNER_STATES = frozenset({SIGNED, HELD})

#: Closed vocabulary. A hold must name the POLICY GAP that blocks it, so
#: "why is this still held" is answerable without re-deriving the triage —
#: and so a hold expires when its cause is fixed rather than by being
#: forgotten. There is deliberately no reason meaning "looks wrong": a hold
#: is a statement about a known defect, not about unease.
COOKING_YIELD_COVERAGE = "cooking_yield_has_no_entry_for_this_food"
AS_EATEN_REWORK = "as_eaten_preference_awaiting_cut_and_coating_controls"
#: ⚠ ADDED BEYOND THE TWO CAUSES THE TRIAGE ANTICIPATED, and flagged as such.
#: `beef|` has exactly ONE candidate — "manufacturing beef, cooked, boiled" —
#: so no ranking policy can improve it and no admission call is owed: the row
#: IS beef. The gap is that RETRIEVAL never surfaced an ordinary beef row.
#: That is neither a ranking defect nor an identity question, and collapsing
#: it into either would misfile it, so it gets its own cause.
RETRIEVAL_COVERAGE = "the only retrieved candidate is a poor representative"
BLOCKING_CAUSES = frozenset({COOKING_YIELD_COVERAGE, AS_EATEN_REWORK,
                             RETRIEVAL_COVERAGE})

#: Ranking defects, filed rather than fixed by admission. Each names a row
#: that is legitimately the requested food and is still the wrong
#: representative — the class admission must NOT be used to solve.
SPECIALTY_BEATS_GENERIC = "a specialty variant outranks the generic form"

RANKING_DEFECTS = (
    ("mushrooms|", "usda:170097", SPECIALTY_BEATS_GENERIC,
     "shiitake cooked 56 kcal wins; white mushrooms cooked 28 are on the same "
     "ladder and are what an unqualified 'mushrooms' means"),
    ("rice|", "usda:169711", SPECIALTY_BEATS_GENERIC,
     "white GLUTINOUS 97 kcal wins; three medium/short-grain rows at 130 are "
     "on the same ladder and are what plain cooked white rice is"),
    ("salmon|", "usda:171999", SPECIALTY_BEATS_GENERIC,
     "chinook — the fattiest salmon — 231 kcal wins; Atlantic farmed cooked "
     "206 is on the same ladder and is the salmon most people eat"),
)


# ── SEMANTIC DECISIONS THIS ROUND PRODUCED, KEPT SEPARATE ────────────────
#
# ⭐ THE FROZEN 77 ARE NOT AMENDED. `potato|`'s winner, `usda:170032`, is not
# among them — the Phase 1.5 population was the consequence frontier, and this
# row never reached it. Adding it to `baseline_signatures.SIGNATURES` would
# change a population that was signed, gated and closed behind
# `baseline_migration`, so the record would no longer say what was signed.
# That is the same class of error as amending a pushed migration.
#
# So Phase 0.9's semantic decisions are ADDITIVE and attributable to their own
# round. The frozen 77 stay exactly as they were signed.
ADMISSION_DECISIONS = (
    ("potato|", "usda:170032", bs.REJECT, "part_of_food_not_the_food",
     "\"Potatoes, raw, SKIN\" is the SKIN — a part of the potato, not a "
     "whole-potato record. An admission defect, not a ranking preference: the "
     "ladder holds boiled flesh at 87 and microwaved flesh at 100, and this "
     "row cannot legitimately describe 'potato' at any ranking."),
)


def _rows():
    """(identity, evidence, winner_status, cause, note)."""
    out = []

    def sign(identity, evidence, note):
        out.append((identity, evidence, SIGNED, "", note))

    def hold(identity, evidence, cause, note):
        out.append((identity, evidence, HELD, cause, note))

    # ── SIGNED — the plain form of the requested food ────────────────────
    for identity, evidence, note in [
        ("asparagus|", "usda:168389", "raw is the generic form of a bare vegetable"),
        ("banana|", "usda:173944", "raw; the only alternative on the ladder is overripe"),
        ("broccoli|", "usda:747447", "raw is the generic form"),
        ("cauliflower|", "usda:169986", "raw is the generic form"),
        ("chicken|grilled", "usda:171534",
         "skinless boneless breast is the canonical read of grilled chicken"),
        ("egg|", "usda:172186", "poached; the ladder's cooked forms span 143-155"),
        ("egg|fried", "usda:173423", "the only candidate, and exactly the request"),
        ("mackerel|roasted", "usda:175120",
         "Atlantic cooked dry heat; already ADMITTED semantically, and dry "
         "heat is the preparation requested"),
        ("mushrooms|grilled", "usda:169243", "portabella grilled; matches directly"),
        ("oats|", "usda:173905", "oats cooked with water is what oats are eaten as"),
        ("potato|fried", "usda:170698", "the only candidate; french fried in oil"),
        ("shrimp|", "usda:175180", "shrimp cooked"),
        ("tilapia|roasted", "usda:175177",
         "cooked dry heat; already ADMITTED semantically, single candidate"),
        ("tofu|", "usda:174291", "hard tofu prepared with nigari is the generic block"),
        ("tofu|fried", "usda:172451", "fried tofu; matches the request directly"),
    ]:
        sign(identity, evidence, note)

    # ── HELD — real evidence, provisional selection ──────────────────────
    #
    # ⭐ THE FISH. `_cooked_pref` fires only when `cooking_yield(query) > 1.0`,
    # and the table returns 1.20 for salmon and shrimp but 1.00 for mackerel
    # and tilapia. So these two seat RAW rows while salmon seats a cooked one —
    # same food class, opposite outcome, decided by A TABLE'S COVERAGE rather
    # than by the food. Signing them would freeze a blind spot: a table's
    # silence read as an answer.
    hold("mackerel|", "usda:175119", COOKING_YIELD_COVERAGE,
         "raw 205 wins only because cooking_yield('mackerel') == 1.00; the "
         "ladder holds Atlantic cooked dry heat at 262")
    hold("tilapia|", "usda:175176", COOKING_YIELD_COVERAGE,
         "raw 96 wins only because cooking_yield('tilapia') == 1.00; the "
         "ladder holds cooked dry heat at 128")

    # ⭐⭐ THE LAB SAMPLES. The as-eaten preference was switched off because a
    # ±0.4 tie-break was deciding CUT and COATING, dimensions it never
    # evaluates. That was the right call and it has an honest cost: "meat
    # only" and "lean only, trimmed to 0\" fat" are USDA REFERENCE SAMPLES,
    # not meals. Signing these would freeze a transitional ranking outcome
    # already expected to move when the preference is reworked.
    for identity, evidence, note in [
        ("beef|grilled", "usda:174702",
         "ribeye filet 'separable lean only, trimmed to 0\" fat' 208"),
        ("beef|fried", "usda:173085",
         "New Zealand knuckle 178 — the leanest cut on a ladder that is "
         "entirely New Zealand imported"),
        ("chicken|fried", "usda:171053",
         "'meat only' 219 for a food normally eaten with skin"),
        ("chicken|roasted", "usda:172395",
         "'meat only' 167; the ladder holds meat and skin at 223"),
        # ⚠ A FIFTH ROW, EXTENDING THE RULE RATHER THAN THE LIST. This one is
        # already ADMITTED semantically (usda:173089, signed by hand), so it
        # was not among the four lab samples — but it IS one of the five
        # winners the as-eaten split reverted, so the reworked preference is
        # expected to move it too. Holding it for the same cause; flagged
        # because it is an extension of the call, not the call itself.
        ("beef|roasted", "usda:173089",
         "NZ 'ribs prepared, fast roasted' 197 — semantically signed, but "
         "one of the five winners the as-eaten split reverted"),
    ]:
        hold(identity, evidence, AS_EATEN_REWORK, note)

    # ⭐⭐⭐ ADMITTED AND STILL NOT THE REPRESENTATIVE. These are the rows the
    # standing rule exists for: each IS the requested food, so admission
    # cannot touch them, and each is the wrong pick. Filed as ranking defects
    # in RANKING_DEFECTS and held here — not rejected.
    for identity, evidence, _cause, note in RANKING_DEFECTS:
        hold(identity, evidence, AS_EATEN_REWORK,
             f"specialty variant beats the generic: {note}")

    # ⭐⭐⭐⭐ NO RANKING POLICY CAN FIX THIS ONE. `beef|` has exactly one
    # candidate, so there is nothing to rank; the row IS beef, so there is
    # nothing to reject. RETRIEVAL never surfaced an ordinary beef row.
    hold("beef|", "usda:174730", RETRIEVAL_COVERAGE,
         "'manufacturing beef, cooked, boiled' 126 is the ONLY candidate; the "
         "signed sibling usda:173086 is UNRESOLVED for exactly this reason")

    # ⛔ `potato|` IS DELIBERATELY ABSENT. Its current winner is "Potatoes,
    # raw, SKIN" — a part-of-food record, REJECTED as evidence. A rejected row
    # cannot hold a winner state in any form, so `accounting` will report the
    # contradiction until the artifact is rebuilt without it. That failure is
    # a true statement about the current artifact, not a gap in this review.

    return tuple(out)


WINNERS = _rows()


def by_identity() -> dict:
    return {identity: (evidence, status, cause, note)
            for identity, evidence, status, cause, note in WINNERS}


def accounting(canonical_winners, signatures=None) -> tuple:
    """Every canonical winner has a status; every HELD names a policy gap.

    `canonical_winners` maps identity -> evidence_id, as produced by the
    ranker under the regime being frozen. Checked against, never derived
    from, this module: a review that silently tracked whatever the ranker
    currently does would not be a review.
    """
    signatures = bs.by_pair() if signatures is None else signatures
    failures, reviewed = [], by_identity()

    for identity, evidence in sorted(canonical_winners.items()):
        if identity not in reviewed:
            failures.append(f"{identity}: canonical winner {evidence} has no "
                            f"winner-review state")
            continue
        signed_evidence, status, cause, note = reviewed[identity]
        if signed_evidence != evidence:
            failures.append(
                f"{identity}: the ranker now seats {evidence} but the review "
                f"covers {signed_evidence} — the regime moved under the review")
        if status not in WINNER_STATES:
            failures.append(f"{identity}: {status!r} is not a winner state")
        if status == HELD and cause not in BLOCKING_CAUSES:
            failures.append(f"{identity}: HELD without a blocking cause from "
                            f"the closed vocabulary (got {cause!r})")
        if status == SIGNED and cause:
            failures.append(f"{identity}: SIGNED rows carry no blocking cause")
        if not note.strip():
            failures.append(f"{identity}: {status} with an empty reason")

        # ⛔ A WINNER MUST BE ADMISSIBLE EVIDENCE FIRST. Signing or holding a
        # row the semantic layer REJECTED would put the two signatures in
        # contradiction — the ranker cannot legitimately seat what identity
        # review has ruled is not this food.
        pair = (identity, evidence)
        if pair in signatures and signatures[pair][0] == bs.REJECT:
            failures.append(
                f"{identity}: {evidence} is semantically REJECTED and cannot "
                f"be a canonical winner in any state")

    missing = sorted(set(reviewed) - set(canonical_winners))
    if missing:
        failures.append(f"{len(missing)} reviewed identities the ranker no "
                        f"longer produces: {missing[:5]}")
    return tuple(failures)


def held() -> tuple:
    return tuple((i, e, c) for i, e, s, c, _ in WINNERS if s == HELD)


def frozen_winners() -> tuple:
    """The identities whose canonical winner may enter the frozen baseline."""
    return tuple((i, e) for i, e, s, _c, _n in WINNERS if s == SIGNED)
