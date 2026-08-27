# CF28 — REGISTERED: a mechanically identified packaged product is priced at ONE serving of a MULTI-serving package

**Registered 2026-08-27 from the frozen stability sweep
(`STABILITY_SWEEP_FROZEN_2026-08-27.md`, case 20). NOT implemented. Rule-0
only: no fix in this pass.**

Pulled out of the family-B range-calibration discussion deliberately. A ~20 %
miss on a packaged item with a printed label is qualitatively different from a
2 kcal or 1–3 g disagreement with a hand-drawn range. **You do not need the
range methodology solved to know that a mechanically identified packaged
product materially disagreeing with its own label deserves attribution.**

## The observation

Utterance: *"Trader Joe's Butter Chicken and a Garlic Naan"*. Four reps, tree
`834924b`, isolated identities.

| rep | Butter Chicken | Garlic Naan | total | frozen expectation |
|---:|---|---|---|---|
| 1 | 330 kcal / 17.0 g | 280 kcal / 7.0 g | 610 / 24.0 | cal `[698,1162]` |
| 2 | 340 kcal / 18.0 g | 220 kcal / 6.0 g | 560 / 24.0 | protein `[26,44]` |
| 3 | 330 kcal / 17.0 g | 280 kcal / 7.0 g | 610 / 24.0 | rows `[2,2]` |
| 4 | 420 kcal / 27.0 g | 220 kcal / 6.0 g | 640 / 33.0 | |

**Identity is CORRECT and STABLE all four times.** Row count is correct all four
times. The terminal is correct all four times. **Only the magnitude is wrong,
and it is wrong in the same direction every time** — 4/4 below the floor, worst
miss −138 kcal (−19.8 %).

## ⭐⭐⭐ THE ARITHMETIC NAMES THE DEFECT

Double the entrée and BOTH dimensions land inside the frozen range at once:

```
calories   330 × 2  +  280   =  940    ∈ [698, 1162]   ✅
protein     17 × 2  +    7   =   41    ∈ [ 26,   44]   ✅
```

Two independent dimensions resolving on the same single correction is not
coincidence. This is the **per-serving vs per-package** signature on a
multi-serving frozen tray: the user means the package they ate, the number
priced is one *serving* off the label. This is the PRODUCT/per-serving family
already measured at **69 % of declines (142/207)** in
`project_arnie_p16_miss_attribution_0817` — the layer P17's serving-basis work
exists for.

⚠ **Stated as the leading hypothesis, not as proven.** The actual Trader Joe's
label has not been read in this pass. Confirming it requires the label, not the
arithmetic — the arithmetic only says a servings factor of exactly 2 reconciles
both dimensions.

## ⭐⭐ ZERO RETRIEVAL

**`search_food_database` was called 0 times in all four reps.** The numbers were
recalled, not looked up. So the serving basis was never *retrieved and
misapplied* — it was never retrieved at all. Whatever the fix is, it cannot be
a basis-conversion repair downstream of a lookup that does not happen.

## Why this is not family B

Family B is contaminated by hand-drawn expectation bounds (case 8 misses by
**2 kcal**; case 15 logs 585 exactly four times, 30 kcal under a drafted floor).
Case 20 is not near a boundary, is consistent 4/4, is a **packaged product with
a knowable printed ground truth**, and has a specific mechanical hypothesis that
predicts both dimensions. It is attributable now; family B is not.

## Rule-0 status

Registered only. No code change, no test, no label change in this pass.
Sequencing authority: the determinism/decomposition tranche runs first
(`DETERMINISM_DECOMPOSITION_TRANCHE_2026-08-27.md`). Related: `CF20`
(wrong nutrition), `CF25`, `CF26`, `CF27`, and
`docs/CANONICAL_MIGRATION_DIRECTIVE.md` §P17-UE.
