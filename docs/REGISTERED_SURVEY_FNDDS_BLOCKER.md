# REGISTERED — Survey (FNDDS) blocks the artifact rebuild

**Measured 2026-09-01.** Survey was added, found to be blocked, and reverted.
Held pending a decision. The tree is in a working state: catalog usable,
fingerprint matching, ownership unaffected.

## WHY SURVEY WAS WANTED

The 25-identity preload probe found `apple juice` retrieving only
*"Babyfood, juice, apple"* under `("Foundation", "SR Legacy")`. Qualification
correctly refused it — the identity guard was working and **retrieval** was the
gap. `Apple juice, 100%` lives in Survey (FNDDS), where many common consumer
foods do. 8 of 25 probe identities refused `IDENTITY_UNQUALIFIED` with 7–10 raw
rows retrieved and none qualified: a retrieval-coverage shape, not a
qualification defect.

## THE BLOCKER — deterministic, measured both ways

```
WITHOUT Survey   potato|grilled=no_evidence   egg|grilled=no_evidence   broccoli|grilled=no_evidence
WITH Survey      potato|grilled=failed        egg|grilled=failed        broccoli|grilled=failed
```

Identical across repeated attempts, and **always exactly 1 unresolved row** per
identity — a regularity that says structural, not statistical.

⭐ **THE MECHANISM.** FNDDS surfaces rows for preparation variants that the
resolver then leaves UNRESOLVED. `build_one` distinguishes:

    no rows at all               -> no_evidence   (clean, buildable)
    rows present, none annotated -> FAILED        (refuses to write)

and that distinction is correct: an unresolved row is not an authoritative
negative. So widening retrieval converted a clean absence into a failure.

⛔ **AND THE FAILURE IS NOT LOCAL.** `build_pricing_artifact` refuses to write
the artifact AT ALL when any identity fails — "a failure is not an
authoritative negative". 8 of 84 failed, so nothing was written. Without a
rebuild the new `retrieval_fingerprint` does not match the committed artifact,
`load()` raises `Stale`, `_artifact()` caches the failure, and **the artifact
rung goes dark for the whole process** — the 27 seeded foods lose canonical
coverage and ownership falls BELOW 9.0%.

Every failing identity is a preparation variant: `potato|grilled`,
`egg|grilled`, `cauliflower|grilled`, `cauliflower|roasted`, `mushrooms|roasted`,
`asparagus|roasted`, `asparagus|fried`, `broccoli|grilled`.

## OPTIONS

| | cost |
|---|---|
| **A. Find the unresolved row** — always exactly 1, so likely mechanical (a batch/parse boundary, or the new concurrent chunk partition). Fixing it unblocks Survey. | investigation of unknown size; the regularity suggests it is small |
| **B. Proceed without Survey** — load the 328 on Foundation + SR Legacy, measure, and treat FNDDS as a Phase 2B provider question driven by the decline population | loses `apple juice`-class coverage now; costs a full reload later, since a fingerprint change stales every row |
| **C. Split the retrieval config** — Survey for acquisition only, not for the artifact build | ⛔ REJECTED: two configs producing evidence into ONE rung, and `retrieval_fingerprint` stops describing what was retrieved. That is the drift the fingerprint exists to prevent. |

⚠ **The reprice question is unanswered and currently unanswerable.** Whether
adding Survey moves any of the 27 seeded foods cannot be checked without a
successful rebuild to compare against. It remains open under option A.

## NOT A REGRESSION

Nothing shipped. `DATA_TYPES` is back to `("Foundation", "SR Legacy")`, the
committed artifact verifies, and the 24 acquired rows remain readable under the
original fingerprint.

---

## RESOLVED 2026-09-01 — the unresolved row is LEGITIMATE. Option B taken.

The bounded causal investigation ran on a frozen fixed population, with a
**fresh `EvidenceContext` per trial** (a shared one is single-flight and would
have handed trial 2 trial 1's answer, manufacturing perfect determinism).

```
FIXED POPULATION for 'potato, grilled': 16 retrieved -> 2 reach the resolver
   2710790  Survey (FNDDS)  Potato, cooked, as ingredient
   2710794  Survey (FNDDS)  Sweet potato, cooked, as ingredient

A. same rows, same order, x3   identical every time    abstained=['2710790']
B. same rows, reversed          identical               abstained=['2710790']
C. 2710790 alone                abstained
   2710794 alone                clean, nothing abstained
```

⭐ **NOT model nondeterminism. NOT order sensitivity. NOT partition dependence.**
`2710790` abstains in every configuration.

⭐⭐ **AND THE ABSTENTION IS CORRECT.** *"Potato, cooked, as ingredient"* is
cooked by an UNSPECIFIED method, so against the identity "potato, grilled" it is
genuinely unsettleable. Abstaining is the honest answer — an absent answer must
never be representable as a negative one — and `build_one` is right to treat
rows-present-none-annotated as `failed` rather than an authoritative negative.

Every layer behaved as designed. FNDDS simply supplies rows that a
preparation-variant identity cannot settle, and no repair is warranted:
weakening the builder to admit them would trade a real guard for coverage.

**DECISION: option B.** `DATA_TYPES` stays `("Foundation", "SR Legacy")`. The
328 preload proceeds without FNDDS. Whether Survey deserves a Phase 2B design is
a question for the measured decline population after the frozen 222 is opened —
not a guess made now.

⚠ The 27-food reprice question stays permanently unanswered for this change,
because no rebuild was ever written. It is moot unless FNDDS returns.
