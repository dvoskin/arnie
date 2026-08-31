# Branded retrieval — what actually blocks canonical admission

Probe work, n=15 branded queries. **Mechanism only.** The forward census
(`event=identity_assessment`) is the sole authority on prevalence; nothing here
is a rate.

## Final bucket split

```
resolved                        10/15   winner already resolves the SKU
B_recall (query missed it)       1/15   Kind Bar — the record exists under a
                                        rephrasing the user's words did not reach
PRICEABILITY GATE rejection      2/15   ⭐ NEW — Coke Zero, Gatorade Zero
still unexplained                2/15   Ben & Jerry's pint, Muscle Milk 40g
C_selection                      0/15   ⛔ WITHDRAWN — see instrument errors
```

## ⭐⭐⭐ THE FINDING: a plausibility floor is eating a whole product class

`skills/nutrition/off.py::_per100g`

```python
# Plausibility: 100g of real food is ~10-900 kcal. Reject sentinels (0, 9999).
if not (10 <= cal <= 900):
    return None
```

The premise — *"100g of real food is ~10–900 kcal"* — is true of **food** and
false of **drinks**. Complete, correctly-populated OFF records are discarded:

```
Coca-Cola Zero             0.2 kcal/100g   all four macros present   REJECTED
Coca-Cola Zero Caffeine    0.3                   "                   REJECTED
Gatorade Zero Glacier      0.0                   "                   REJECTED
Zero Sugar Thirst Quencher 0.0                   "                   REJECTED
```

⛔ **The gate conflates "implausible" with "missing".** It was written to reject
sentinels — a `0` meaning *nobody filled this in*, a `9999` meaning garbage —
but a genuine zero is indistinguishable from an absent zero under a MAGNITUDE
test. So it throws away diet sodas, zero sports drinks, sugar-free drinks, black
coffee and most seltzers: every one structurally unpriceable by the OFF lane.

This is the same shape as the `times_used` defect earlier today: **a value that
means one thing being read as evidence of another.** Absence and zero are not
the same fact, and OFF already distinguishes them — all four macro fields are
populated on these records.

⛔ **NO REPAIR AUTHORIZED.** The obvious one (distinguish absent from zero) is
plausible and untested, and the gate's sentinel purpose is real.

## The structural claim that survives: `_overlap` is not an identity metric

```python
return len(q & p) / len(q)          # QUERY-token coverage
```

Faithfully optimising the wrong objective. Two consequences, both arithmetic:

```
discriminator loss is priced like redundant-token loss
  'Muscle Milk Pro Series Vanilla' -> 'Muscle Milk pro series'   0.80  (-vanilla)
  'Chobani ... Plain Nonfat'       -> '... Plain, Whole Milk'    0.80  (-nonfat)
  'Gatorade Zero Glacier Cherry'   -> 'Gatorade Thirst Quencher…' 0.75  (-zero)

candidate specialization is FREE — the denominator is the QUERY's tokens
  'Oreo'        -> 'Oreo Double Stuf'           1.00
  'Cheerios'    -> 'Honey Nut Cheerios'         1.00
  'Coke'        -> 'Coke Zero'                  1.00
  'Muscle Milk' -> 'Muscle Milk Pro Series'     1.00
  'Barebells'   -> 'Barebells Soft Protein Bar' 1.00
```

⭐ But the measured consequence is **precision, not ranking**: when a resolving
candidate is in the pool it ranks **first, 10 times out of 10**. So the defect
admits wrong supersets; it does not bury right answers. Same family as the
Barebells false positive at the identity layer.

## ⛔ INSTRUMENT ERRORS — two, both mine, both corrected

**1. `_resolves` checked the product name only.** `_overlap` unions name AND
`brands`; my check did not. So `'Pro Series Vanilla Protien Powder'`
(brands=`Muscle Milk`) scored as NOT resolving `'Muscle Milk Pro Series Vanilla'`
— a record retrieved by barcode `0660016534113` an hour earlier in the same
session.

It produced **two published bucket counts, both wrong**: first "C is the
exciting bucket", then "C is small at 13%". C is **zero**. Caught only by
contradicting an earlier result — nothing in either run flagged it.

**2. A hardcoded denominator.** After reducing the coverage probe from nine
queries to five, its summary still printed `1/9` and `8/9`. Per-row output was
correct; the total was arithmetic on a stale constant.

⚠ **And a comparability caveat:** the corrected pool run reports `legacy` where
the earlier one reported `sal`, because the OFF breaker was open then and closed
now. Part of the improvement is a **different backend with a different selection
rule** (`require_anchor=True` on the fallback), not only the fix. Not
disentangled, and not claimed as disentangled.

## Board

```
CANDIDATE SELECTION (ranking)    NOT SUPPORTED — 0/15, resolving candidates
                                 rank 1 whenever present
SELECTION OBJECTIVE (precision)  STRUCTURALLY INADEQUATE — demonstrated
                                 arithmetically; supersets score 1.00
PRICEABILITY FLOOR               ⭐ LEADING DEFECT — a magnitude test cannot
                                 tell a genuine zero from a missing one
BRANDED RECALL                   1/15
THRESHOLD CALIBRATION            NULL
RELATIONSHIP FALSE POSITIVE      Barebells, separate
REPAIR                           NOT AUTHORIZED anywhere in this document
```
