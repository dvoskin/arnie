# Local replay — the threshold hypothesis, refuted

**Diagnostic, not prevalence.** `data/corpus/branded_identity_truth_v1.json`
(26 pairs, labelled from product knowledge **before** any confidence existed),
run through the shipped `resolve` at the live threshold of 0.80.
`scripts/replay_branded_identity.py`, output
`data/branded_identity_replay_2026-08-31.json`.

## Confusion against the live bar

```
                       QUALIFIED   refused
TRUE_SAME_PRODUCT           9          0
TRUE_DIFFERENT_PRODUCT      1         13
AMBIGUOUS                   2          1

TRUE_SAME       0.85 0.85 0.90 ×5 0.95 0.95        lowest = 0.85
TRUE_DIFFERENT  0.70 ×3  0.75 ×7  0.85 ×2  0.90 ×2
.70–.79 band    10 cases, ALL of them true mismatches
```

## The three findings, kept separate

### 1. THRESHOLD CALIBRATION — NULL, hypothesis refuted

> **No evidence that the 0.80 threshold is responsible for the observed
> adoption failure; lowering it is contradicted by the labelled replay.**

⛔ Deliberately NOT "0.80 is correctly calibrated". n=26 cannot support a global
claim about a threshold. What it supports is the negative: zero true matches
fell below the bar, and every case in `.70–.79` was a true mismatch, so moving
the bar down would admit only false positives.

**No threshold change authorized.**

### 2. BRANDED ADOPTION — working hypothesis: candidate evidence too coarse

Case 4 is the OFF row production actually retrieved:

```
requested   Muscle Milk Pro Series Vanilla
candidate   Muscle Milk pro series
verdict     SAME_IDENTITY   confidence 0.55   refused
```

Labelled **AMBIGUOUS** before that number was visible — the candidate does not
establish the flavour. ⭐ **Canonical behaved correctly.** The model agreed on
the line and was honestly unsure about the SKU, at 0.55, nowhere near the bar.

So the producer question is **not** qualification tuning:

> Why did OFF/product retrieval fail to produce a variant-resolved candidate
> when the user's input contained the variant?

To trace — **as a class, not as a Muscle Milk fix**: barcode/SKU availability ·
flavour/variant fields in OFF · whether retrieval discards those attributes ·
ranking when several variants exist · whether identity normalization collapses
`Vanilla` · whether an exact candidate was available and not selected.

**Production prevalence: UNMEASURED** until the forward census accumulates.

### 3. RELATIONSHIP FALSE POSITIVE — registered, do not fold in

```
#18  Barebells Caramel Cashew  ->  Barebells Soft Protein Bar Caramel Cashew
     SAME_IDENTITY   0.85   QUALIFIED     nutrition_relevant_difference: yes
```

A separate line with different macros, admitted **above** the threshold. One
false positive in fourteen near neighbours.

⭐ **And it is the strongest argument against touching 0.80.** The false
positive already sits above the bar, so no threshold movement addresses it.
This is a relationship-classification / identity-boundary defect and needs its
own fixture and its own repair.

## ⛔ What this cannot say

n=26, synthetic pairs, one candidate per intent. It establishes **mechanism and
calibration shape**, never **how often users hit each failure class**. The
production forward census (`event=identity_assessment`) is the sole authority on
prevalence, and the two must never be merged into one number.
