# SHAPE C — DECIDED. SMALLEST SLICE: `unstated_extras`

**Danny, 2026-08-30.** Chosen not for being smallest — it is not — but because
it is **the only option that removes the coupling instead of rearranging it.**

## The ranking, and why

```
C  model reports, code decides    PREFERRED
B  per-entry `resolved` flag      tempting but DANGEROUS — still asks the model
                                  both "what is uncertain?" and "may I resolve
                                  it?". If `resolved:true` becomes a learned
                                  default, the same failure returns under a
                                  cleaner schema.
A  second array                   WEAKEST — correlated structured outputs the
                                  model must keep consistent, after repeated
                                  evidence that adding prompt structure moves
                                  behaviour; and it risks a THIRD vocabulary.
```

The interpreter currently does two jobs: **describing uncertainty** and
**deciding whether that uncertainty may be resolved without asking.**
`skills/nutrition/materiality.py` already exists to make the second decision.

> **Leaving permission in the prompt means two authorities can independently
> decide whether Arnie should ask** — precisely the architecture four days
> proved cannot be measured safely. It is the four-tables condition again, one
> layer up.

## ⛔⛔⛔ THREE BOUNDARIES — FROZEN BEFORE IMPLEMENTATION

```
1. `materiality.py` becomes the SOLE authority for whether represented
   uncertainty may be defaulted.
2. The model MAY report uncertainty, but its output MUST NOT itself authorize
   suppression of a question.
3. `portion_multiplier` stays COMPLETELY OUTSIDE this tranche.
   No producer means no policy.
```

## The slice

**One subject. `unstated_extras`.** Not "implement C everywhere."

```
UNCHANGED   `ambiguities[]` keeps its resolution meaning and its existing five
            fields. `extras` NEVER enters that vocabulary — that is exactly the
            change already measured and rejected (asks 30 -> 24, c17 -> 0.00).

UNCHANGED   materiality.py. Not touched. The code-side decision is the control
            variable, not part of the experiment.

NEW         an explicitly OBSERVATIONAL channel: the model reports that extras
            are unstated, WITHOUT any language granting permission to assume
            them, and with the system named as the decider of whether to ask.
```

⚠ **This is structurally similar to shape A but semantically C.** The difference
is not the presence of a second structure — it is that the new channel carries
**no resolution permission**, while A would leave the permission sentence
intact and add alongside it. The distinction is the whole experiment.

## ⭐ THE NORTH-STAR EXPERIMENT — BINARY

> **Adding `unstated_extras` representation must create real `unstated_extras`
> observations WITHOUT moving asking behaviour beyond the same-SHA null.**

```
PASS   extras observed  AND  clarification rate + material asks inside the
       variant's OWN same-SHA null
       -> evidence C actually broke the coupling

FAIL   asking moves materially merely because the model CAN name the subject
       -> the problem is DEEPER: prompt-side representation itself influences
          reasoning, even with no permission language.
          STOP. Do not expand C.
```

Named canaries: **c17** (primary-item wrap size) and **c1** — the two asks the
rejected changes suppressed most cleanly. c17 went 1.00 → 0.25 → 0.00 across
the two failed variants.

## Prior odds, stated honestly

**Four prompt changes have been measured this session. All four moved asking
behaviour.** That is not proof the fifth must, and C differs from all four by
removing permission rather than extending it — but the base rate is 4/4 and
should temper expectation.

---

# RESULT — **THE FROZEN EXIT TEST PASSES**

```
run                        sha       asks  staged  extras  assumed-leak
BASELINE                   4049778     30     10       0        0
C SLICE run1               79ece8a     29      6      10        0
C SLICE run2 (null twin)   79ece8a     27      7       6        0

THIS SHA'S OWN NULL:  asks Δ2 · staged Δ1 · extras Δ4
```

## The exit test, as frozen

```
1. real unstated_extras observations
   10 and 6, with ZERO `assumed` leakage across both runs        ✅ PASS

2. clarification rate AND material asks inside this SHA's null
   ask rate    effect Δ1  vs  null Δ2                            ✅ INSIDE
   material    c17  1.00 · 1.00 · 1.00                           ✅ INTACT
```

## ⭐⭐⭐ THE CANARY THAT MATTERS

```
c17 (primary-item wrap size)   baseline 1.00 · C 1.00 · C 1.00
      rejected exception 0.25 · rejected one-word variant 0.00

c1  (mayo — SECONDARY condiment)  baseline 1.00 · C 0.00 · C 0.00
```

**Both rejected variants destroyed c17. The C slice preserves it across both
runs while dropping only the secondary condiment question.** That is the
discrimination the whole tranche was aiming at: representation gained,
*material* uncertainty kept.

⚠ c1's loss is consistent (0.00 twice) and is a real behaviour change. It was
classified secondary; **that classification was mine and has not been reviewed.**

## ⚠⚠ ONE OBSERVATION THAT WAS **NOT** IN THE FROZEN TEST

```
staged-raised   baseline 10 -> 6 and 7      effect Δ4  vs  null Δ1   EXCEEDS
```

**Authority migration.** Interpreter-raised went 20 → 23/20 while staged went
10 → 6/7. Given the authorities are SEQUENTIAL — interpreter first, staged only
if the interpreter stays silent — the mechanism is plausibly that **extras
reporting gives the interpreter something to raise on turns it previously left
to staged.**

⛔ **I am NOT folding this into the pass/fail.** It was not in the frozen test,
and adding a criterion after seeing the result is how a pass gets manufactured
or destroyed to taste. It is reported as a separate finding requiring its own
decision.

⚠ Round 1 showed authority migration changes what the user sees. Total asking
barely moved, but **which producer speaks did**, and that is exactly the class
of change this session has repeatedly found to matter more than aggregate
counts.

## ⚠ Variance on the capability itself

`extras` reports were **10 and 6** — a null Δ of 4 on the very quantity being
established. Both non-zero and leakage-free, so condition 1 holds, but the
capability's rate is not stable and should not be quoted as a figure.

## Status

```
C slice, frozen exit test          PASS
authority migration                OUT-OF-TEST FINDING, exceeds null, undecided
c1 secondary-ask loss              consistent, classification unreviewed
extras rate                        unstable (10 vs 6)
adoption                           NOT AUTHORIZED — a passing slice is not an
                                   adoption decision
```
