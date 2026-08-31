# TRANCHE — INVARIANT IMPACT BASIS

**Opened 2026-08-31 by Danny. Must land BEFORE DEFAULTABILITY reopens.**

## The requirement

> **Materiality must consume an invariant representation of the unresolved
> component, not whatever parent item happens to contain it.**
>
> An unresolved `Mayo ~120 cal` must get the same materiality decision whether
> it is
>
>     StagedFoodItem("Mayo")
>     Sandwich.ambiguity(extras="Mayo")
>
> The parent representation may change for logging and decomposition purposes;
> **the unknown's own impact basis may not.**

## How this tranche was found

Shape C passed its north-star exit test and was **rejected for adoption
anyway**, because measuring *why* it passed produced this:

```
baseline c1  TWO staged items — the sandwich, and `Mayo` as its own row.
             mayo: CONSUMED_QUANTITY/`quantity`, material=True   -> ASK 2/2
under C      ONE staged item. The mayo is not a row; it is an `extras`
             ambiguity ON THE SANDWICH, material=False           -> ASK 0/4
             (the C run and its null twin, all four observations)
```

`of_item` divides by the row the ambiguity hangs off, and C moved the row.
Nothing about the unknown changed.

| span | mayo as its own row (90 cal) | `extras` on the sandwich (800 cal) |
|---|---|---|
| 40 → 200 | MATERIAL | immaterial |
| 240 | MATERIAL | MATERIAL |

**7 of 8 tested spans flip on the denominator alone**, and all four captured
condiment spans (80, 100, 120, 150) are among them. As its own row the mayo is
material from **27** calories; on the sandwich it needs **240**.

That is architectural, not a mayo edge case.

## ⭐ The general shape

This is the 2026-08-30 boundary — *representation and resolution permission are
independent state* — **arriving one layer below where it was enforced.** Shape C
was built to hold that line in the prompt: the model may NAME an unknown without
gaining permission to resolve it. It does hold it there. It then breaks it in
the scorer, where nobody was looking, because naming the unknown differently
changed which row it was sized against.

The generalisation worth carrying out of this tranche:

> **A separation enforced at one layer is not enforced.** Permission-to-default
> was policed in the prompt; the denominator granted it anyway.

## The exit test — frozen, and mechanical

`tests/test_materiality_is_representation_invariant.py`

Take the same unresolved component and span, encode it in **both**
representations, and require **identical materiality decisions across the full
policy grid**.

It runs the real `FP.attach_ambiguities` — not a reimplementation of the scorer
— because `attach_ambiguities` is the function that chose the denominator in
production.

Current state: **3 passed, 2 strict xfail.**

| test | role |
|---|---|
| `test_both_encodings_actually_produce_an_ambiguity` | ⛔ anti-vacuity: a dropped encoding would agree with anything |
| `test_the_denominator_is_the_parent_row_today` | pins the MECHANISM, so the repair cannot be mistaken for a tuning |
| `test_c1_gets_the_same_decision_under_both_representations` | **xfail(strict)** — the exit test, one case |
| `test_the_decision_is_invariant_across_the_WHOLE_policy_grid` | **xfail(strict)** — the exit test, full grid |
| `test_the_flip_is_real_and_this_file_is_measuring_it` | asserts the flip POSITIVELY; must be **deleted**, not edited, on repair |

`strict=True` is deliberate: it is green while the defect lives and goes **RED
the moment the repair lands**, which forces promotion to a plain assertion
rather than leaving a passing xfail behind.

### ⭐ Mutation-validated, because a green strict-xfail proves nothing

Mutation: force `item_calories=None` at the `build_ambiguity` call site — the
repair, crudely faked. Result:

```
FAILED test_the_denominator_is_the_parent_row_today          (mechanism moved)
FAILED test_c1_gets_the_same_decision_under_both_representations   XPASS strict
FAILED test_the_decision_is_invariant_across_the_WHOLE_policy_grid XPASS strict
FAILED test_the_flip_is_real_and_this_file_is_measuring_it   (demands deletion)
4 failed, 1 passed
```

Four failures, each with the failure NAME the mutation predicts. Reachability,
observability and causality all confirmed.

## What this tranche must NOT do

- **Do not decide whether the mayo question is a good question.** This pins only
  independence: whatever the policy decides about an unknown, it must decide the
  same thing about that same unknown under a different parent.
- **Do not wait on `impact_cal` truthfulness.** Registered separately and
  upstream. Even if the model overestimates mayo, the same 120-cal uncertainty
  receiving different resolution permission by representation alone is wrong on
  its own terms (Danny, 2026-08-31).
- **Do not fix the `DAY_SHARE_OVERRIDE` predicate divergence here.** Real —
  23.3% of a 12,000-cell grid — and registered, but measured NOT to be causal
  for these asks.

## After the repair

Re-run C. **If C still improves the north star without deleting material asks,
it can earn adoption again.** That re-run needs a held-out corpus; the
invariant itself does not.

## Board

```
C / unstated_extras            FAIL adoption
north-star experimental result PRESERVED AS PASS — the measurement was valid
failure mechanism              representation changes the materiality denominator
c1                             CONFIRMED MATERIAL under current policy
c4                             UNSCOREABLE — measurement gap, registered
c8                             ask RETAINED — evidence behaviour is not uniform
DAY_SHARE_OVERRIDE divergence  separate registered tranche
condiment-span truthfulness    separate upstream question, NOT a prerequisite
INVARIANT IMPACT BASIS         ⭐ THIS TRANCHE — next, before DEFAULTABILITY
DEFAULTABILITY                 blocked behind it
27983be                        still DEPLOY HOLD. Nothing deployed.
```
