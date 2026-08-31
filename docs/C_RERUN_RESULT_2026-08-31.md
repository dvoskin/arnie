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

---

## ⚠ AMENDMENT — 2026-08-31: VALID CAUSAL RESULT; PRODUCTION-EQUIVALENCE CLAIM WITHDRAWN

The E arms carry **two** claims. One survives intact; the other is retracted.

### Claim A — causal. **SURVIVES.**

> Under the measured environment, switching C on caused asks to rise:
> E1 44% / E2 46% → E3 60%, effect +7.5 outside a null envelope of 1.

All three arms shared one `_code_sha` and one configuration, and differed in
exactly one declared variable. The experiment still isolates C **within that
environment**. Nothing here weakens it.

### Claim B — production equivalence. **FALSE / UNPROVEN. Retracted.**

The `_config` block on every E arm reads `TURN_COORDINATOR_MODE: new_observe`
as though that were production truth. It is not:

```
                                render.yaml   E arms        PRODUCTION
TURN_COORDINATOR_MODE           new_observe   new_observe   new_execute
ENTITY_RESOLUTION_MODE          (absent)      (absent)      consume
ENTITY_RESOLUTION_ALLOWLIST     (absent)      (absent)      [26]
TURN_COORDINATOR_ALLOWLIST      (absent)      (absent)      [26]
NUTRITION_ACCURACY_V2           (absent)      (absent)      allowlist [26]
FOOD_COMPOSER_MODEL             (absent)      (absent)      claude-sonnet-5
```

`pin_config` could not see the last five: **they are not in the manifest it
compares against.** It reported a clean pin over flags it had never enumerated.

**The E arms therefore ran in a `new_observe`, non-consume, non-enrolled
environment** — a legitimate executable configuration, but not the current
production one.

### What the result now says, exactly

- ~~C harms production behaviour.~~ *(too strong)*
- **C causally harms the measured configuration, and therefore failed
  adoption. Whether the +15-point raw shift reproduces under production cohort
  configuration is UNMEASURED.**

### ⛔ C STAYS REJECTED

A candidate that produced **measured harm under a legitimate executable
configuration** is not resurrected because the environment label was too
strong. No threshold tuning, no reversal. What changed is the breadth of the
conclusion, not its direction.

### The cheap discharge, when it matters

Not a 150-turn re-run. A small preregistered **config-sensitivity control**,
C OFF throughout:

```text
same frozen inputs · same code · C OFF
    A = the historical E config
    B = true production config, production-equivalent ENROLLED subject
```

Asking only: *does correcting those runtime flags materially alter the path or
state relevant to C's mechanism?* If A ≈ B the generalisation caveat is largely
discharged without re-running E. If A ≠ B, E is valid only for its original
environment. **C is already rejected, so this is not on the critical path.**

## Scope of the damage — classified, not panicked

| class | verdict |
|---|---|
| **same-config causal comparisons** (the E arms, the null pair, the C effect) | **SURVIVE**, with the production-equivalence caveat above |
| **absolute "production baseline" numbers** | need remeasurement or an equivalence proof before being quoted as production truth |
| **experiments whose PATH ELIGIBILITY depends on these flags** | potentially VOID until eligibility is proven — a synthetic user in no allowlist does not reach the same code |
| **CF24 production arm A** | **UNAFFECTED.** It ran in production, as user 26, through Telegram |

⭐ The distinction matters: a real instrumentation defect must not trigger an
equally bad overreaction that throws away valid causal evidence.
