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
RETRIEVAL_COVERAGE = "no better representative was retrieved for this identity"
#: ⭐ PROMOTED TO A BLOCKING CAUSE 2026-08-13. Filing these under
#: AS_EATEN_REWORK was a MISFILE: the as-eaten preference was never going to
#: touch shiitake-vs-white or glutinous-vs-plain, so the hold named a blocker
#: that could not unblock it. A hold whose stated cause cannot resolve it is
#: indistinguishable from a hold nobody understands.
SPECIALTY_BEATS_GENERIC_CAUSE = "a specialty variant outranks the generic form"
BLOCKING_CAUSES = frozenset({COOKING_YIELD_COVERAGE, AS_EATEN_REWORK,
                             RETRIEVAL_COVERAGE, SPECIALTY_BEATS_GENERIC_CAUSE})

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
    # ⭐ ADDED BY THE POST-REBUILD RE-REVIEW. Both are cases where a reviewer
    # named a better generic representative and THE RANKER SEATS SOMETHING
    # ELSE. The freeze records what production DOES; the hold records what a
    # reviewer WANTED and why. Overriding the freeze instead would assert a
    # row production never seats — the split-brain authority this whole phase
    # removed — and changing the ranker would reopen frozen architecture on
    # the eve of closure.
    ("egg|", "usda:172185", SPECIALTY_BEATS_GENERIC,
     "omelet 154 kcal is seated; poached 143 is the cleaner generic for a "
     "preparation-unspecified egg — omelet is more transformed and can imply "
     "added fat or milk. Admission unchanged: an omelet is an egg"),
    # ⛔ THE MATERIAL ONE. 305 vs 205 is a 49% OVERSTATEMENT, and the ranker
    # prefers salted only because it is a shorter, closer lexical match to a
    # bare "mackerel" query than "Atlantic, raw" is. Nothing about nutrition
    # decided it. This is precisely what B-1.7b materiality policy should
    # surface rather than tolerate silently.
    ("mackerel|", "usda:168149", SPECIALTY_BEATS_GENERIC,
     "salted 305 kcal is seated; raw 205 is the better generic baseline — "
     "salting materially changes sodium and water state and is a narrower "
     "form. 49% OVERSTATEMENT. Admission unchanged: salting is preservation, "
     "not a different food"),
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
#: ⭐ PHASE 0.9b — THE EIGHT-ROW DELTA the captured-source build exposed.
#:
#: Populating the store gave the artifact annotations it did not have when its
#: candidate lists were written on 08-08, so the live build derives a SMALLER
#: universe than the artifact holds. Eight rows disagree, and five of them are
#: the RESOLVER being wrong in a way a reviewer already ruled on.
#:
#: ⭐⭐ THE MACKEREL THREE ARE THE IMPORTANT CORRECTION. The model marked king,
#: spanish and Pacific-and-jack mackerel DIFFERENT_IDENTITY for
#: `mackerel|roasted` — while the SAME model marked chinook, chum, pink,
#: sockeye and Atlantic salmon admissible for `salmon|roasted`, and a reviewer
#: signed those by hand as "same_base_food + species_specialization +
#: preparation_compatible". A species specialization of the requested fish is
#: the base food. Letting the model's inconsistency stand would use admission
#: to solve representativeness, which is exactly what the standing rule
#: forbids: if a specialized row is legitimate but undesirable as the generic
#: winner, ADMIT it and let ranking decide.
ADMISSION_OVERRIDES = (
    ("mackerel|roasted", "usda:174236", bs.ADMIT,
     "same_base_food + species_specialization + preparation_compatible",
     "king mackerel, cooked dry heat — the identical class signed ADMIT for "
     "five salmon species; the model contradicted its own salmon verdicts"),
    ("mackerel|roasted", "usda:173674", bs.ADMIT,
     "same_base_food + species_specialization + preparation_compatible",
     "spanish mackerel, cooked dry heat — same class"),
    ("mackerel|roasted", "usda:171994", bs.ADMIT,
     "same_base_food + species_specialization + preparation_compatible",
     "Pacific and jack mackerel, cooked dry heat — same class"),
    ("chicken|fried", "usda:171448", bs.ADMIT,
     "same_base_food + form_specialization",
     "battered fried chicken — admissible because the request ITSELF asks "
     "for fried, the same reasoning that admitted breaded shrimp for "
     "shrimp|fried and rejected it for bare shrimp|"),
    ("chicken|grilled", "usda:171536", bs.ADMIT,
     "same_base_food + form_specialization",
     "grilled skinless breast WITH ADDED SOLUTION — a brine treatment of the "
     "same chicken, on the treatment side of the line that admits salting "
     "and smoking while refusing breading"),
    # ⭐ CORRECTED. This was a semantic REJECT and should not have been:
    # canned shrimp IS shrimp. Calling it "not shrimp" to keep it off the
    # generic ladder would use ADMISSION to solve REPRESENTATIVENESS, the
    # thing the standing rule forbids — and it would write a durable
    # falsehood to fix a ranking preference. ADMIT, and let the winner review
    # hold it if it is a poor generic representative.
    ("shrimp|", "usda:171972", bs.ADMIT, "same_base_food + form_specialization",
     "canned shrimp is still shrimp; canning is a preservation form, not a "
     "different food. It may be a poor GENERIC representative, which is a "
     "ranking question and not an admission one"),
)

#: ⛔ NOT SEMANTIC DECISIONS, AND THE DISTINCTION MUST SURVIVE THE REBUILD.
#: The two HOUSE FOODS tofu rows were nearly signed as human REJECTs. They
#: should not be: the architecture already has a typed BRANDED_FOR_GENERIC
#: exclusion, and on the CURRENT retrieval contract — Foundation + SR Legacy
#: only — branded rows never arrive at all.
#:
#: So their absence from a rebuilt artifact has a PROVENANCE, and it is
#: neither "a reviewer ruled they are not tofu" nor "a veto refused them". It
#: is RETRIEVAL NO LONGER SUPPLYING THEM. Recording them as semantic rejects
#: would have written down that a tofu product is not tofu — false, durable,
#: and an answer to a question nobody asked.
NOT_SEMANTIC_ABSENCES = (
    ("tofu|", "usda:173788", "retrieval_no_longer_supplies_branded_rows",
     "HOUSE FOODS Premium Firm Tofu — branded; the retrieval contract is "
     "Foundation + SR Legacy, so it is not returned. If it ever were, "
     "BRANDED_FOR_GENERIC is the typed mechanical exclusion, not a reviewer"),
    ("tofu|", "usda:173787", "retrieval_no_longer_supplies_branded_rows",
     "HOUSE FOODS Premium Soft Tofu — same provenance"),
)

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
        ("banana|", "usda:173944", "raw; the only alternative on the ladder is overripe"),
        ("chicken|grilled", "usda:171534",
         "skinless boneless breast is the canonical read of grilled chicken"),

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
        # ⭐ RE-ADJUDICATED FROM HELD TO SIGNED against ea771c9. It was held as
        # a "lab sample" awaiting the as-eaten rework — and that label was
        # WRONG: "ribs prepared, fast roasted" is an ordinary row, not a
        # lean-only reference, so the preference was never going to move it.
        # Measured against the reworked regime it is now STABLE IN BOTH modes,
        # and it is the row a reviewer read and signed ADMIT by hand.
        ("beef|roasted", "usda:173089",
         "NZ 'ribs prepared, cooked, fast roasted' 197; semantically signed by "
         "hand, and stable under both the canonical-safe and reworked regimes"),
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
    # ⭐⭐ AND THE HAND-LIST WAS THREE TIMES TOO SHORT. Deriving the set from
    # `cooked_preference_state` instead of from the rows whose kcal gap I
    # happened to notice gives SIX, not two: a bare identity, on an undecided
    # axis, WHOSE LADDER HOLDS BOTH RAW AND COOKED ROWS — because that is
    # exactly where a missing policy silently decided something.
    #
    #   asparagus|  1 raw / 4 cooked      mackerel|  3 raw / 4 cooked
    #   broccoli|   4 raw / 6 cooked      potato|    1 raw / 3 cooked
    #   cauliflower| 1 raw / 4 cooked     tilapia|   1 raw / 1 cooked
    #
    # I caught the two fish because their kcal gap was obvious (205 vs 262,
    # 96 vs 128) and missed three vegetables where the gap is small and the
    # defect identical. Raw may well be right for a bare vegetable — the point
    # is that NOTHING DECIDED IT, so it cannot be frozen as though something
    # had. `banana|`, `egg|`, `mushrooms|`, `oats|`, `rice|` and `tofu|` are
    # also undecided and are NOT held: their ladders carry one state only, so
    # the missing policy had nothing to decide between.
    for identity, evidence, ladder in [
        ("asparagus|", "usda:168389", "1 raw / 4 cooked"),
        ("broccoli|", "usda:747447", "4 raw / 6 cooked"),
        ("cauliflower|", "usda:169986", "1 raw / 4 cooked"),
        ("tilapia|", "usda:175176", "1 raw / 1 cooked; cooked dry heat is 128"),
    ]:
        hold(identity, evidence, COOKING_YIELD_COVERAGE,
             f"a raw row wins on an UNDECIDED cooked axis ({ladder}); "
             f"cooking_yield states nothing for this food, and the table "
             f"already carries 'fish' — the query simply never contains it")

    # ⭐⭐ RE-ADJUDICATED AGAINST ea771c9, AND SEVEN OF THE EIGHT ORIGINAL
    # as_eaten HOLDS NAMED A BLOCKER THAT CANNOT UNBLOCK THEM.
    #
    # Measured, per identity: does the reworked preference move this winner,
    # and does the ladder even CONTAIN an as-eaten row comparable to it?
    #
    #   chicken|roasted   MOVES     -> the rework resolves it; still held only
    #                                  because the preference is OFF in the
    #                                  regime Phase 0 freezes against
    #   beef|grilled      no move   -> NO comparable as-eaten row EXISTS. The
    #   chicken|fried     no move      preference can never help; the ladder
    #                                  simply has no as-eaten form of that cut
    #   beef|fried        no move   -> winner is NOT a trimmed reference. My
    #   beef|roasted      no move      "lab sample" label was WRONG for these
    #                                  two: NZ knuckle and NZ ribs-prepared are
    #                                  ordinary rows, not lean-only samples
    #
    # A hold whose stated cause cannot resolve it is a hold nobody can act on.
    # Re-filed under what would actually change the answer.
    hold("chicken|roasted", "usda:172395", AS_EATEN_REWORK,
         "'meat only' 167; the reworked preference DOES move this to meat and "
         "skin 223 — it is held only because the preference is off in the "
         "regime Phase 0 freezes against, so it clears with that canary")

    for identity, evidence, note in [
        ("beef|grilled", "usda:174702",
         "ribeye filet 'separable lean only, trimmed to 0\" fat' 208 — and NO "
         "comparable as-eaten ribeye was retrieved, so no preference can fix "
         "it; the ladder's lean-and-fat rows are a different CUT"),
        ("chicken|fried", "usda:171053",
         "'meat only' 219 — the only as-eaten sibling is BATTERED, which is a "
         "different coating and correctly not comparable"),
        ("beef|fried", "usda:173085",
         "New Zealand knuckle 178 on a ladder that is ENTIRELY New Zealand "
         "imported; no domestic beef row was retrieved at all"),
    ]:
        hold(identity, evidence, RETRIEVAL_COVERAGE, note)

    # ⭐⭐⭐ ADMITTED AND STILL NOT THE REPRESENTATIVE. Each IS the requested
    # food, so admission cannot touch them — the class the standing rule
    # exists for. Now carrying the cause that describes them.
    for identity, evidence, _c, note in RANKING_DEFECTS:
        hold(identity, evidence, SPECIALTY_BEATS_GENERIC_CAUSE, note)

    # ⭐⭐⭐⭐ NO RANKING POLICY CAN FIX THIS ONE. `beef|` has exactly one
    # candidate, so there is nothing to rank; the row IS beef, so there is
    # nothing to reject. RETRIEVAL never surfaced an ordinary beef row.
    hold("beef|", "usda:174730", RETRIEVAL_COVERAGE,
         "'manufacturing beef, cooked, boiled' 126 is the ONLY candidate; the "
         "signed sibling usda:173086 is UNRESOLVED for exactly this reason")

    # ⭐ `potato|` AFTER THE REBUILD. The part-of-food row is gone, and the
    # ladder rose to "skin with salt" 132 rather than boiled flesh 87 — a
    # legitimate whole potato already signed ADMIT in the frozen 77, so
    # admission cannot touch it either. Exactly the class the standing rule
    # exists for: REJECT the evidence, then HOLD the successor.
    hold("potato|", "usda:170115", SPECIALTY_BEATS_GENERIC_CAUSE,
         "microwaved skin-on 132 kcal wins after the part-of-food row was "
         "removed; boiled flesh at 87 is on the same ladder and is closer to "
         "what a bare 'potato' means. 58 -> 132 is an admission fix, not a "
         "good winner")

    # ⛔ NOTE FOR THE RECORD. Its current winner is "Potatoes,
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
