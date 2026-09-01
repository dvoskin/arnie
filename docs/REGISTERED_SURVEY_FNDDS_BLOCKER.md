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
