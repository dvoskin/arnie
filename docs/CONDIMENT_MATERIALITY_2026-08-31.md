# Condiment materiality: what the policy itself scores — and why C removed the ask

**Zero model turns.** Every number is either read from a frozen capture or
computed by the shipped policy functions. Instrument:
`scripts/characterise_condiment_materiality.py`. Frozen output:
`data/condiment_materiality_2026-08-31.json`.

## The rule, frozen before looking (Danny, 2026-08-31)

| outcome | consequence |
|---|---|
| condiment unknown scores **below** the ask threshold | C's suppression agrees with policy; extras adoption may proceed |
| scores **above** the threshold | C suppresses a question the system itself calls material → **C fails adoption as implemented** |
| **cannot be scored** | that is the blocker; register the missing representation, keep C held |

Both c1 and c4 were to be evaluated, not just mayo.

## Answer

**c1 scores ABOVE the threshold. c4 cannot be scored.** Both branches say hold.

Probe identity, verbatim from the census harness (`_make_identity`):
`calorie_target=2600, protein_target=190`, no mode set → `moderate`.
Through the real `_daily_targets`: **calories 2510, protein 171, carbs 308,
fat 66.**

| dial (moderate) | value | in calories |
|---|---|---|
| `DAY_FRACTIONS` | 0.01 | 25.1 |
| `MIN_ITEM_SHARE` | 0.02 | 50.2 |
| `DAY_SHARE_OVERRIDE` | 0.125 | 313.8 |
| `MATERIAL_FRACTIONS` (of item) | 0.30 | — |

### c1 — Subway mayo, `impact_cal = 120`

Captured at `producer_census_both_authorities_2026-08-28.jsonl`, case 1 rep 1
(`_code_sha 12f9d38`). This is the exact field both materiality entry points
consume for the calorie span — no mayo estimate was invented here.

`is_material` = **True at every item size from 0 to 400 cal.** It only turns
false at ≥500, which is not a condiment.

- `of_day` = 120 / 2510 = **4.78%** — **4.8× the 1% dial**
- `MIN_ITEM_SHARE` ceiling = 120+ vs a 50.2 bar — **cleared by 2.4×**
- `of_item` ≥ 0.30 for any mayo under 400 cal

### The other condiment shapes — all material, none split

| capture | span | verdict |
|---|---|---|
| c8 Blackened Ranch sauce | 100 | MATERIAL at 40/80/140/200 cal |
| c8 Popeyes Blackened Ranch Sauce | 80 | MATERIAL at 40/80/140/200 cal |
| c25 Spicy mayo | 150 | MATERIAL at 40/80/140/200 cal |

Danny's "one immaterial, one material → the blanket policy is too coarse"
outcome **did not occur**. Every captured condiment span is material.

### c4 — Polynesian sauce: UNSCOREABLE

**No frozen run captured an interpreter ambiguity for case 4 at all** —
`n_captures = 0` across all 30 case-4 records in every corpus. The span exists
(the ambiguity is `CONSUMED_QUANTITY`/`quantity`, the shape only
`attach_ambiguities` produces, and that reads `impact_cal`) but was never
recorded, because the capture hangs off `_ask_types_from` and the staged
authority won every case-4 turn.

Registered as a measurement gap, **not** classified by hand.

Its baseline ask was **1 of 2 reps**, so c4 was already unstable before C
touched it.

## ⛔ The condiment gate does not exclude these condiments

`MIN_ITEM_SHARE` exists expressly to stop this — its docstring records the
production sweep that found the two proportions asking about **honey (21 cal),
soy sauce (10), pickled turnips (10), a hot-sauce drizzle (20)**.

Those are 10–21 calories. The model reports **80–150** for mayo, ranch and
Polynesian. The gate's bar is 50.2 calories of ceiling. **Every captured
condiment span clears it on the span alone, before the item is even counted.**

The gate was calibrated against condiments an order of magnitude smaller than
the ones in this corpus. It is not wrong; it is aimed elsewhere.

## ⚠ A hypothesis I had, and the measurement that refuted it

The two materiality entry points **are** different predicates:

```
skills.nutrition.materiality.is_material    day-fraction → MIN_ITEM_SHARE
  (interpreter path, turn-level, ANY)       → DAY_SHARE_OVERRIDE → of_item
skills.nutrition.ambiguity.materiality      day-fraction / of_item, and
  (→ FoodAmbiguity.is_material, the         NEITHER of the middle two
   per-question staged gate)
```

I expected the per-question path skipping `MIN_ITEM_SHARE` to be why condiment
asks got raised. Over a 12,000-cell grid they disagree on **23.3%** — but
**2,793 of 2,794 disagreements are the `DAY_SHARE_OVERRIDE` branch** (big spans
on big items). Exactly **one** cell is the condiment case, and it needs a
ceiling under 50 cal. In the region these asks actually live, the two predicates
**agree**.

The divergence is real and worth its own tranche. It is **not** what produced
these asks.

## ⭐⭐⭐ What C actually did: it moved the denominator

Read off `staged_state` in the frozen runs:

```
baseline c1  TWO staged items — the sandwich, and `Mayo` as its own item.
             mayo item: CONSUMED_QUANTITY/`quantity`, material=True  → ASK 2/2
under C      ONE staged item. The mayo is not a row any more; it is an
             `extras` ambiguity ON THE SANDWICH, material=False      → ASK 0/4
             (both the C run and its null twin, all four observations)
```

The ask did not fail a materiality test. **It changed which row it hangs off,
and `of_item` divides by that row.** `of_item` is the gate that made the mayo
material — a ~120-cal span is most of a mayo and a seventh of a sandwich.

| span | mayo as its own item (90 cal) | `extras` on the sandwich (800 cal) |
|---|---|---|
| 40 | MATERIAL | immaterial |
| 80 | MATERIAL | immaterial |
| 100 | MATERIAL | immaterial |
| **120** | **MATERIAL** | **immaterial** |
| 150 | MATERIAL | immaterial |
| 200 | MATERIAL | immaterial |
| 240 | MATERIAL | MATERIAL |

**7 of 8 spans flip on the denominator alone**, and every captured condiment
span (80, 100, 120, 150) is among them. On the sandwich, an `extras` unknown
must reach **240 cal** to be material; as its own row, **27**.

The conclusion does not rest on C's own span, which was never captured — the
flip holds across the whole plausible range.

### This is the boundary Danny froze on 2026-08-30, arriving from underneath

> *Representing an unresolved semantic subject must not alter whether that
> subject is defaultable. Representation and resolution permission are
> independent state.*

Under C they are **not** independent. Re-representing the mayo as a property of
the sandwich silently moved the denominator, and the denominator decided. C was
built to satisfy this boundary at the prompt layer; it violates it at the
scoring layer, one level down, where nothing was watching.

## ⛔ C is not consistent about condiments

| case | shape | baseline | under C |
|---|---|---|---|
| c1 | "How much of the Subway Mayo?" | 2/2 ASK | **0/4 — removed** |
| c4 | "How much of the …Polynesian Sauce" | 1/2 ASK | **0/4 — removed** |
| c8 | "How much of the Popeyes Blackened Ranch?" | 2/2 ASK | **2/4 — kept** |

Same shape, same authority, same phrasing template. C removes it twice and
keeps it once. That is a distribution shift, not a policy.

## Board

```
C / unstated_extras          north-star experiment PASS (unchanged)
                             ADOPTION FAILS — branch 2 on c1
condiment materiality        MEASURED. Above threshold: of_day 4.78% vs a 1%
                             dial; every captured condiment span is material
c4 materiality               UNSCOREABLE — no interpreter ambiguity captured in
                             any frozen run. Registered, not classified
MIN_ITEM_SHARE               calibrated for 10–21 cal condiments; these are
                             80–150. Aimed elsewhere, not wrong
predicate divergence         REAL (23.3%) but NOT causal here — DAY_SHARE_
                             OVERRIDE, not MIN_ITEM_SHARE. Own tranche
C's mechanism                DENOMINATOR CHANGE, not suppression. Violates the
                             2026-08-30 frozen boundary at the scoring layer
C consistency                FAILS — removes c1/c4, keeps c8
```

## What this does not say

- It does not say the mayo question is a **good** question. It says the system's
  own policy scores it material, and C removed it without consulting that policy.
- It does not settle whether `impact_cal = 120` is a truthful span. The policy
  consumes the model's number and has no independent check on it. If the model
  overstates condiment spans, the defect is upstream of materiality — and that
  is a different tranche with a different instrument.
- The c1 span was captured on `12f9d38`, the C baseline is `407ed03`. Same
  harness config, same corpus, same model. Cross-SHA, and recorded as such.
