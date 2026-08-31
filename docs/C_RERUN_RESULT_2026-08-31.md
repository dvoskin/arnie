# C re-run result — the benefit was the artifact, and it was masking the opposite sign

Arms **E1 / E2 / E3**, `_code_sha 26ff8f5`, 150 turns.
Preregistration: `docs/PREREG_C_RERUN_2026-08-31.md` (+ amendment 1).
Analysis: `scripts/analyse_c_rerun.py`.

## Refusal conditions — ALL CLEAR

```
_code_sha            26ff8f5 · 26ff8f5 · 26ff8f5          identical
FOOD_EXTRAS_...      false   · false   · true             _arm recorded on each
E1 vs E2 comparable  True  []                             valid null pair
E1 vs E3 differs ONLY in the arm  True  []
basis field          37/37 · 47/47 · 23/26 filled, 0 MISSING   instrument live
```

The first attempt at this run was VOID on condition 1. This one is not.

## The headline

| arm | asks | rate |
|---|---|---|
| E1 (C off) | 22/50 | 44% |
| E2 (C off, null twin) | 23/50 | 46% |
| **E3 (C ON)** | **30/50** | **60%** |

```
NULL ENVELOPE  |E1 - E2|          = 1
EFFECT         E3 - mean(E1,E2)   = +7.5      OUTSIDE the envelope
```

**C does not reduce asking. It increases it, by 7.5 turns — 15 points — on a
null envelope of 1.**

Broad, not a handful: **8 of 25 cases moved**, six by a full ask or more
(c1 +2.0, c9 +1.5, c5 +1.0, c8 +1.0, c17 +1.0, c25 +1.0), all in the same
direction; the only negative is c20 at −0.5, inside the envelope.

## ⚠ MY PREREGISTRATION HAD A GAP, and the outcome landed in it

I enumerated two outcomes: *falls inside the envelope* (predicted), and *still
REDUCES by more than the envelope* (falsifying). The actual outcome —
**increases by more than the envelope** — is a third case I did not write down.

Naming it rather than retrofitting: the prediction's **first clause hit exactly**
(c1's mayo ask returned) and its **second clause was wrong in a way my
falsification conditions could not express**. A prediction that cannot name the
outcome it gets is weaker evidence than one that can, and this one is being
reported as partially unfalsifiable rather than as a hit.

## What actually happens — c1, both arms, same tree

```
C off   1 staged item.  `prep`, span 150, basis 960 (the sandwich)
        150/960 = 15.6% of item, under the 30% dial  -> material=False -> 0/2 asks

C ON    1 staged item.  `extras`, span 150, basis None (NOT ESTABLISHED)
        no item denominator, so the DAY fraction decides alone:
        150/2510 = 6.0% against a 1% dial            -> material=True  -> 2/2 asks
```

So C moves the unknown out of a channel where it was sized against **a parent
that is not its subject**, and into one where it **cannot be sized at all** —
and the policy treats an unsizeable unknown that can move the day as material.

**That is the correct treatment of an unknown you cannot size.** It produces
more questions, not fewer.

## The verdict

C's original measured benefit was an ask-rate **reduction**. With the
denominator artifact removed, C's effect is an ask-rate **increase** of
comparable magnitude.

> **The artifact was not part of the benefit. It WAS the benefit, and it was
> masking an effect of the opposite sign.**

There is therefore **no hidden second mechanism to hunt for** — Danny's
"if C still beats the null, find the other mechanism" branch does not apply,
because C does not beat the null in the beneficial direction. The benefit is
fully accounted for.

## ⭐ The repair is INERT in production as configured

```
E1 (C off)   0/37 facts carry a NOT-ESTABLISHED basis
E2 (C off)   0/47
E3 (C ON)    3/26
```

Without C's prompt the model emits no component-scoped field at all, so
`_COMPONENT_SCOPED_FIELDS` never fires and the repair changes nothing. Its
entire behavioural surface flows through C's `extras` channel — which is off.

⚠ The corollary, written down rather than assumed: this also means the repair's
effect on ask rate has been measured **only** in the presence of C. If another
producer ever emits a component-scoped field, that is a new measurement.

## Other pinned outcomes

- **c17 held.** E3 asked 2/2, against 1/2 in both C-off arms. Both previously
  rejected variants drove c17 to 0.25 and 0.00; C does not damage it.
- **Danny's second clause passes outright.** Zero extras facts carry a parent
  basis across all three arms — every component-scoped fact reads
  NOT-ESTABLISHED, as designed.
- **Component structure:** out-of-range counts 2 / 5 / 2. No systematic
  difference; c24 and c25 are off-range in every arm, which is a corpus-label
  question, not C's.

## ⛔ A claim of mine that this run CORRECTS

I reported on 2026-08-31 that C removed a staged row — c1 going from two staged
items (sandwich + `Mayo`) to one. **In these arms, C-off also produces one
staged item, in all four observations.** The 2-vs-1 split was run-to-run
variance in how the interpreter decomposes c1, not something C did.

What survives untouched is the **denominator defect itself**, which was never
corpus evidence: it was proven mechanically by
`test_the_denominator_is_the_parent_row_today` and by the policy
characterisation where 7 of 8 spans flip on the parent alone. What does not
survive is my narrative that C *re-parented a row*. C changes the FIELD the
unknown is reported under; the row count moved on its own.

## Board

```
C / unstated_extras       FAIL adoption — CONFIRMED, and for a stronger reason:
                          its effect reverses sign once the artifact is removed
north-star PASS (orig.)   preserved as a valid measurement, fully attributed
                          to the denominator artifact
second causal mechanism   DOES NOT EXIST — the branch does not apply
INVARIANT IMPACT BASIS    repaired, proven, and INERT with C off
c1 prediction             HIT — the mayo ask returned, 2/2
preregistration           partially unfalsifiable; gap recorded
DEFAULTABILITY            unblocked by this result — the question it now
                          faces is whether the asks C surfaces are WANTED,
                          which is the product question, not the scorer's
27983be                   still DEPLOY HOLD
```
