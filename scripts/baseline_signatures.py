"""PHASE 1.5 — THE SIGNED BASELINE, and the gate that proves it adds up.

77 (identity, evidence) pairs were adjudicated by hand: every pair priced in
production, plus every pair ten cold starts surfaced. This module is the
signature sheet. It is DATA, deliberately — a person read each record and
ruled, and that ruling is now durable semantic fact rather than a model output
that varies per build.

⭐ WHY A MACHINE CHECK EXISTS FOR A HUMAN PROCESS. The narrative report of this
review said 77 rows and described its categories in prose. The prose was
wrong: eight rows were described as "quick REJECT" in the triage and never
actually signed, and no amount of re-reading the summary would have found it,
because the summary was the thing that was wrong. `accounting()` recomputes
the population from the worksheet and refuses anything that does not reconcile
exactly. It caught those eight.

⭐⭐ THE ADMISSION QUESTION, WHICH IS NARROWER THAN IT LOOKS.

    Admission answers "can this evidence legitimately describe the requested
    semantic food state?" It does not answer "is this the most representative
    candidate?"

Those are different questions with different owners. The first is admission —
here. The second is RANKING, downstream, deterministic. Collapsing them is how
a reviewer starts hand-picking winners, which is the stochastic authority this
whole phase removes rather than relocates.
"""
from __future__ import annotations

from skills.nutrition import semantic_annotations as sa

ADMIT, REJECT, UNRESOLVED = "admit", "reject", "unresolved"
TERMINAL = frozenset({ADMIT, REJECT, UNRESOLVED})

#: A signature is not a sample. A reviewer who has read the record has not
#: produced a probability, so signed rows carry full confidence and UNRESOLVED
#: carries none — the reviewer declined to rule, which is not low confidence in
#: a ruling. Recorded provenance says `human`, never a model name.
REVIEWER = "human:phase_1_5_baseline_review"

_ADMIT_REASONS = {
    "same_base_food + preparation_match",
    "same_base_food + preparation_unspecified",
    "same_base_food + subtype_specialization + preparation_match",
    "same_base_food + species_specialization + preparation_compatible",
    "same_base_food + preservation_not_preparation",
    "same_base_food + form_specialization",
    "same_food",
}
_REJECT_REASONS = {
    "wrong_base_food",
    "different_base_food",
    "wrong_form_or_product",
    "wrong_preparation",
    "derived_or_composite_product",
    "consumed_state_mismatch",
}

S, C, D, U = (sa.SAME_IDENTITY, sa.COMPATIBLE_SPECIALIZATION,
              sa.DIFFERENT_IDENTITY, sa.UNRESOLVED)


def _rows():
    """(identity, evidence, disposition, relationship, reason, note)."""
    out = []

    def sign(disposition, relationship, reason, note, pairs):
        for identity, evidence in pairs:
            out.append((identity, evidence, disposition, relationship,
                        reason, note))

    # ── ADMITTED ──────────────────────────────────────────────────────────
    sign(ADMIT, C, "same_base_food + preparation_match",
         "cut/origin specialization; the record states fast roasted",
         [("beef|roasted", "usda:173089")])

    sign(ADMIT, S, "same_food",
         "the food itself under USDA's own canonical filing; mayonnaise is "
         "filed under 'Salad dressing', which is naming, not identity",
         [("butter|", "usda:173410"), ("coconut oil|", "usda:171412"),
          ("coconut oil|", "usda:330458"), ("olive oil|", "usda:171413"),
          ("mayonnaise|", "usda:171009")])

    sign(ADMIT, C, "same_base_food + form_specialization",
         "whipped butter and two source oils; aeration and botanical source "
         "are forms of the food, and the basis is per WEIGHT",
         [("butter|", "usda:173411"), ("vegetable oil|", "usda:171422"),
          ("vegetable oil|", "usda:172370")])

    # ⭐ THE PRINCIPLE THE FISH ROWS ESTABLISH. "cooked, dry heat" does not
    # PROVE roasted or grilled, and it does not have to. Compatibility is the
    # admission standard; which candidate best represents the request is the
    # ranker's question, one layer down.
    sign(ADMIT, C, "same_base_food + species_specialization + "
                   "preparation_compatible",
         "dry heat is compatible with roasted/grilled, and species is a "
         "specialization of the requested fish",
         [("salmon|roasted", "usda:171999"), ("salmon|roasted", "usda:172000"),
          ("salmon|roasted", "usda:172001"), ("salmon|roasted", "usda:173692"),
          ("salmon|roasted", "usda:175168"), ("salmon|grilled", "usda:171999"),
          ("tilapia|roasted", "usda:175177"),
          ("mackerel|roasted", "usda:175120")])

    # ⭐⭐ THE LINE BETWEEN A TREATMENT AND A DERIVED FORM, which is what makes
    # this consistent with rejecting breaded shrimp for a BARE shrimp request:
    # salting and smoking treat the food itself, breading ADDS a different
    # food. The first is still the food; the second is a coated product.
    sign(ADMIT, C, "same_base_food + preservation_not_preparation",
         "salting and smoking preserve the fish; neither adds another food",
         [("mackerel|", "usda:168149"), ("salmon|", "usda:173687")])

    sign(ADMIT, C, "same_base_food + preparation_unspecified",
         "the request constrains no preparation, so a cooked record is a "
         "legitimate description of it",
         [("cauliflower|", "usda:169389"), ("cauliflower|", "usda:169390"),
          ("cauliflower|", "usda:169391"), ("egg|", "usda:172185"),
          ("egg|", "usda:172187"), ("potato|", "usda:170115"),
          ("shrimp|", "usda:171971")])

    sign(ADMIT, C, "same_base_food + subtype_specialization + "
                   "preparation_match",
         "a capon is a chicken, and the record states roasted",
         [("chicken|roasted", "usda:173646")])

    sign(ADMIT, C, "same_base_food + preparation_match",
         "ultraviolet exposure is a treatment applied to the mushroom, not a "
         "preparation competing with grilled; portabella specializes mushroom",
         [("mushrooms|grilled", "usda:169377")])

    sign(ADMIT, C, "same_base_food + form_specialization",
         "breading is admissible HERE because the request itself asks for "
         "fried — the same record is rejected for a bare shrimp request",
         [("shrimp|fried", "usda:171970")])

    # ── REJECTED ──────────────────────────────────────────────────────────
    sign(REJECT, D, "wrong_base_food",
         "the record is a different food entirely",
         [("chicken|grilled", "usda:169243"), ("beef|grilled", "usda:169243"),
          ("egg|fried", "usda:168199"), ("egg|fried", "usda:172451"),
          ("potato|fried", "usda:173423"), ("tilapia|roasted", "usda:167634"),
          ("tilapia|roasted", "usda:170686")])

    sign(REJECT, D, "different_base_food",
         "a neighbouring species is not the requested food; sweet potato is "
         "not potato and wild rice is not rice",
         [("potato|", "usda:168484"), ("potato|", "usda:170088"),
          ("potato|", "usda:170133"), ("rice|", "usda:168897")])

    sign(REJECT, D, "wrong_form_or_product",
         "right food, manufactured or branded product form — salami, "
         "sausage, spread, babyfood, restaurant platter",
         [("beef|", "usda:170198"), ("beef|", "usda:170199"),
          ("beef|", "usda:172012"), ("beef|", "usda:172935"),
          ("beef|", "usda:172936"), ("beef|", "usda:174579"),
          ("beef|", "usda:174618"), ("beef|roasted", "usda:172935"),
          ("beef|roasted", "usda:174597"), ("beef|grilled", "usda:172935"),
          ("banana|", "usda:167732"), ("chicken|fried", "usda:170343"),
          ("chicken|fried", "usda:170738"), ("chicken|fried", "usda:170350"),
          ("chicken|fried", "usda:169842"), ("chicken|grilled", "usda:172957"),
          ("egg|fried", "usda:169732"), ("shrimp|fried", "usda:172037")])

    # ⭐⭐⭐ THE ROW THAT PROVES ADMISSION IS PER-REQUEST, NOT PER-RECORD. The
    # SAME evidence is admitted above for `shrimp|fried` and rejected here for
    # bare `shrimp|`. Identity is a relation between a request and a record,
    # so a table keyed on the record alone could not express this.
    sign(REJECT, D, "wrong_form_or_product",
         "breading is a coated derived form and materially changes the "
         "nutrition of a BARE shrimp request",
         [("shrimp|", "usda:171970")])

    sign(REJECT, D, "wrong_preparation",
         "right food, but the request CONSTRAINS the preparation to fried",
         [("egg|fried", "usda:172185"), ("egg|fried", "usda:172187")])

    sign(REJECT, D, "derived_or_composite_product",
         "a dish containing the food, or an extract of it, is about the food "
         "without being it",
         [("egg|", "usda:172673"), ("egg|", "usda:172674"),
          ("egg|", "usda:172741"), ("egg|", "usda:174901"),
          ("potato|", "usda:167943"), ("potato|", "usda:168446"),
          ("potato|", "usda:168854"), ("potato|", "usda:170092"),
          ("potato|", "usda:173343"), ("rice|", "usda:168914"),
          ("rice|", "usda:173161"), ("salmon|", "usda:172343")])

    sign(REJECT, D, "consumed_state_mismatch",
         "an UNPREPARED frozen product is not a cooked fried serving",
         [("potato|fried", "usda:169764")])

    # ── UNRESOLVED, AND SIGNED AS SUCH ────────────────────────────────────
    #
    # ⭐ A REFUSAL TO RULE IS A RULING. These are not rows nobody reached.
    # Each was read and deliberately left open, which is why they carry a
    # review status: the annotation store treats a signed UNRESOLVED as
    # SETTLED and will not hand it back to a model on the next build, where a
    # sampled opinion would quietly replace a considered refusal.
    sign(UNRESOLVED, U, "split_vote_is_not_evidence",
         "the cold-start vote split on these two mayonnaise records; a split "
         "is an absence of agreement, not evidence in either direction",
         [("mayonnaise|", "usda:171443"), ("mayonnaise|", "usda:173594")])

    sign(UNRESOLVED, U, "poor_representative_but_not_a_different_food",
         "'manufacturing beef' is unquestionably beef, so DIFFERENT_IDENTITY "
         "is too strong — but it is a poor generic representative, and the "
         "system cannot yet express that distinction without a reviewer "
         "hand-picking winners",
         [("beef|", "usda:173086")])

    return tuple(out)


SIGNATURES = _rows()

#: The population this review covers. Fixed, because a review that could
#: silently change size is not a baseline.
EXPECTED_POPULATION = 77


def by_pair() -> dict:
    return {(i, e): (d, rel, reason, note)
            for i, e, d, rel, reason, note in SIGNATURES}


def accounting(worksheet) -> tuple:
    """⭐ THE FINAL GATE BEFORE THE BASELINE FREEZES. Failures, in order.

    Six conditions, each one a way the narrative could disagree with the data:
    the population is exactly the expected size and has no duplicate pairs,
    every row carries exactly one terminal disposition, every ADMIT and REJECT
    states a reason from a closed vocabulary, every UNRESOLVED is explicitly
    signed, no pair is adjudicated twice, and no row is left unsigned.
    """
    failures = []
    pairs = [(r["identity_key"], r["evidence_id"]) for r in worksheet]
    unique = set(pairs)

    if len(pairs) != len(unique):
        failures.append(f"worksheet holds duplicate pairs: {len(pairs)} rows, "
                        f"{len(unique)} unique")
    if len(unique) != EXPECTED_POPULATION:
        failures.append(f"population is {len(unique)}, expected "
                        f"{EXPECTED_POPULATION}")

    seen, signed = set(), by_pair()
    for identity, evidence, disposition, relationship, reason, _ in SIGNATURES:
        pair = (identity, evidence)
        if pair in seen:
            failures.append(f"{pair} adjudicated more than once")
        seen.add(pair)

        if disposition not in TERMINAL:
            failures.append(f"{pair}: {disposition!r} is not terminal")
        if disposition == ADMIT and reason not in _ADMIT_REASONS:
            failures.append(f"{pair}: admit reason {reason!r} is not in the "
                            f"closed vocabulary")
        if disposition == REJECT and reason not in _REJECT_REASONS:
            failures.append(f"{pair}: reject reason {reason!r} is not in the "
                            f"closed vocabulary")
        if disposition in (ADMIT, REJECT) and not reason.strip():
            failures.append(f"{pair}: {disposition} with an empty reason")
        if disposition == UNRESOLVED and relationship != sa.UNRESOLVED:
            failures.append(f"{pair}: unresolved must spell UNRESOLVED")
        if disposition == ADMIT and relationship not in sa.PRICEABLE:
            failures.append(f"{pair}: admitted but {relationship} cannot price")
        if disposition == REJECT and relationship in sa.PRICEABLE:
            failures.append(f"{pair}: rejected but {relationship} would price")

    unsigned = sorted(unique - seen)
    if unsigned:
        failures.append(f"{len(unsigned)} unsigned rows, e.g. {unsigned[:5]}")
    stray = sorted(seen - unique)
    if stray:
        failures.append(f"{len(stray)} adjudications for rows not on the "
                        f"worksheet, e.g. {stray[:5]}")
    return tuple(failures)


def freeze(store, worksheet) -> dict:
    """Write every signature into `store` under an OPEN baseline migration.

    ⚠ `baseline_migration` is the CAUSE authorising replacement of a model
    verdict — an argument to `Store.record`. It is deliberately NOT written
    into the annotation's own `invalidation_reason`: `eligible()` refuses any
    annotation carrying one, so doing that would mark all 29 admitted rows
    invalid and empty the artifact this review exists to populate. A signature
    is not an invalidation.
    """
    failures = accounting(worksheet)
    if failures:
        raise SystemExit("baseline accounting failed:\n  " +
                         "\n  ".join(failures))

    counts = {ADMIT: 0, REJECT: 0, UNRESOLVED: 0}
    sa.open_baseline_migration()
    try:
        for identity, evidence, disposition, relationship, reason, _ in \
                SIGNATURES:
            prior = store.get(identity, evidence)
            store.record(sa.Annotation(
                identity_key=identity,
                evidence_id=evidence,
                relationship=relationship,
                # a signature is not a sample; UNRESOLVED means the reviewer
                # declined to rule, which is not weak belief in a ruling
                confidence=0.0 if disposition == UNRESOLVED else 1.0,
                resolver_model=REVIEWER,
                resolver_version=reason,
                # PRESERVED, never re-derived: the review is about the row as
                # it stood, so a republished source must still reopen it
                source_fingerprint=getattr(prior, "source_fingerprint", "")
                or "",
                review_status=sa.BASELINE_REVIEWED,
            ), cause=sa.BASELINE_MIGRATION)
            counts[disposition] += 1
    finally:
        sa.close_baseline_migration()
    return counts
