# STABILITY SWEEP — FROZEN 2026-08-27

**Tree `834924b`. 25 cases × 4 reps = 100 turns. Zero UNMEASURED.
Turn-level pass 54/100.** Raw: `data/corpus/stability_sweep_v1_2026-08-27.jsonl`.
Instrument: `scripts/sweep_case_stability.py`. Classifier:
`scripts/classify_case_stability.py`.

⭐⭐⭐ **THIS SWEEP CHANGED THE DIAGNOSIS.** It was authorized to find the
population for a DEFAULTABILITY policy tranche. It found that that population
has **one member**, and that the largest unambiguous defect population in the
corpus is determinism, not policy. It is frozen so the determinism tranche has
a real before/after authority and so a later run cannot quietly redefine the
population.

## Instrument validity

- **Zero UNMEASURED across 100 turns.** No outage contaminated the run.
- **SELFTEST OK** — before any turn, the harness seeds a real `FoodEntry` and
  reads it back through the SAME extractor. "Nothing logged" therefore means
  the model did not log, never that the reader could not see it.
- ⛔⛔ **THE FIRST VERSION OF THIS INSTRUMENT WAS BIASED AND GREEN.** Its reader
  touched `FoodEntry.food_name`, which does not exist — but only when rows
  EXISTED. Every LOG raised and was recorded `UNMEASURED`; every ASK recorded
  cleanly. **An instrument that cannot observe one of its two outcomes, while
  reporting the other confidently.** It ran 4 turns before the class was
  spotted. Hence the self-test, and hence TWO error classes that are never
  merged: TURN faults (API/outage) → `UNMEASURED`, excluded; READER faults
  (instrument bug) → fatal, exit 3, **no rates printed**.
- **Reps are interleaved OUTER** (rep-major, not case-major) so any drift over
  the run hits every case equally instead of confounding drift with case.
- **One fresh identity per TURN.** A shared identity previously taught the model
  history and it began refusing meals outright.
- ⚠ **n=4 CANNOT CERTIFY STABILITY.** A true 50/50 case shows 4/4 one way 12.5%
  of the time. "Stable" here means *did not flip in four* — a shortlist
  criterion, not a proof. The asymmetry is the point: **one flip already proves
  instability, and one prose-only ask already proves a correctness bug**, but a
  stable-ASK claim needs members. Only case 23 carries n=8 (from the targeted
  11/23/18 check the same day).

## The 25 cases

| case | frozen | seq | pass | rows seen | exp rows | family | prose-ask | meal |
|---:|---|---|---:|---|---|---|:-:|---|
| 1 | LOG_COMPLETE | `LA·L` | 1/4 | 5,1 | [1, 1] | D repr-unstable | ⛔ 1 | Subway Footlong Turkey on Italian Herbs & Chee |
| 2 | LOG_COMPLETE | `LLLL` | 4/4 | 2,2,2,2 | [2, 2] | A stable pass |  | Five Guys Little Cheeseburger and a small frie |
| 3 | LOG_COMPLETE | `LLLL` | 3/4 | 3,3,3,3 | [2, 3] | B off-range |  | Panda Express Bigger Plate: Orange Chicken, Te |
| 4 | LOG_COMPLETE | `LLLL` | 4/4 | 3,3,3,3 | [2, 3] | A stable pass |  | Chick-fil-A 12-count nuggets, medium fries, an |
| 5 | LOG_COMPLETE | `LLLL` | 4/4 | 1,1,1,1 | [1, 1] | A stable pass |  | Jersey Mike's Regular #7 Turkey and Provolone, |
| 6 | LOG_COMPLETE | `LLLL` | 4/4 | 3,3,3,3 | [2, 3] | A stable pass |  | Taco Bell Crunchwrap Supreme, a Beefy 5-Layer, |
| 7 | LOG_COMPLETE | `LLLL` | 4/4 | 2,2,2,2 | [2, 2] | A stable pass |  | Wendy's Dave's Single and a small fries |
| 8 | LOG_COMPLETE | `LLLL` | 3/4 | 3,3,3,3 | [2, 3] | B off-range |  | Popeyes 3-piece tenders, Cajun fries, and a Bl |
| 9 | LOG_COMPLETE | `AL·A` | 0/4 | 5 | [1, 1] | E term-unstable | ⛔ 1 | CAVA Greens and Grains bowl with steak, hummus |
| 10 | LOG_COMPLETE | `LLLL` | 4/4 | 1,1,1,1 | [1, 1] | A stable pass |  | Sweetgreen Chicken Pesto Parm bowl |
| 11 | LOG_COMPLETE | `·LAL` | 2/4 | 1,1 | [1, 1] | E term-unstable | ⛔ 1 | Chipotle burrito with chicken, white rice, bla |
| 12 | LOG_COMPLETE | `LLLL` | 0/4 | 2,2,2,2 | [2, 2] | B off-range |  | Panera Bacon Turkey Bravo and a bag of chips |
| 13 | LOG_COMPLETE | `LLLL` | 4/4 | 2,2,2,2 | [2, 2] | A stable pass |  | Starbucks Double-Smoked Bacon sandwich and a V |
| 14 | LOG_COMPLETE | `LLAL` | 2/4 | 1,2,2 | [2, 2] | D repr-unstable |  | Shake Shack SmokeShack and fries |
| 15 | LOG_COMPLETE | `LLLL` | 0/4 | 3,3,3,3 | [3, 3] | B off-range |  | A California roll, a spicy tuna roll, and miso |
| 16 | LOG_COMPLETE | `AAAA` | 0/4 | — | [3, 3] | C stable ASK |  | 8 oz sirloin, a loaded baked potato, and a Cae |
| 17 | LOG_COMPLETE | `LAAA` | 1/4 | 2 | [2, 2] | E term-unstable |  | A chicken Caesar wrap and an apple |
| 18 | ASK_CORRECT | `A·AA` | 3/4 | — | [1, 4] | E term-unstable | ⛔ 1 | A Mediterranean chicken platter with rice, pit |
| 19 | LOG_COMPLETE | `LLLL` | 4/4 | 1,1,1,1 | [1, 1] | A stable pass |  | 2 Costco pepperoni pizza slices |
| 20 | LOG_COMPLETE | `LLLL` | 0/4 | 2,2,2,2 | [2, 2] | B off-range |  | Trader Joe's Butter Chicken and a Garlic Naan |
| 21 | LOG_COMPLETE | `LLLL` | 2/4 | 3,3,3,3 | [3, 3] | B off-range |  | A Fairlife Core Power Elite, a Quest Bar, and  |
| 22 | ASK_CORRECT | `AAAA` | 4/4 | — | [4, 4] | A stable pass |  | 3 eggs, 2 turkey sausage patties, sourdough to |
| 23 | LOG_COMPLETE | `AAAA` | 0/4 | — | [1, 1] | C stable ASK |  | A Greek yogurt parfait with granola, berries,  |
| 24 | LOG_COMPLETE | `AA·L` | 0/4 | 3 | [2, 2] | E term-unstable | ⛔ 1 | A homemade turkey burger on a brioche bun with |
| 25 | LOG_COMPLETE | `LALL` | 1/4 | 1,5,5 | [1, 1] | D repr-unstable |  | A large poke bowl with salmon, tuna, rice, eda |

`L`=logged · `A`=asked (durable pending question) · `·`=NOTHING (no row, no
question). `pass` requires the frozen terminal AND, on a LOG, the row count
inside `expected_component_range` **and** calories and protein inside their
frozen ranges.

## Families

| family | n | members | character |
|---|---:|---|---|
| **A** stable pass | 9 | 2,4,5,6,7,10,13,19,22 | named fixed items / explicit counts |
| **B** deterministic, right structure, off-range numbers | 6 | 3,8,12,15,20,21 | logs every time; misses a frozen bound |
| **C** stable ASK under a `LOG_COMPLETE` label | 2 | 16 *(OILS)*, 23 | → defaultability population = **1** |
| **D** representation instability | 3 | 1,14,25 | rows move: `[5,1]`, `[1,2,2]`, `[1,5,5]` |
| **E** terminal instability | 5 | 9,11,17,18,24 | flips ASK↔LOG |
| **F** non-durable clarification | 5 turns | 1,9,11,18,24 | prose question, no answerable state |

## ⭐⭐⭐ ALL FIVE PROSE-ONLY ASKS FALL INSIDE THE UNSTABLE POPULATION

`{1,9,11,18,24}` ⊂ the 8 unstable cases. **Zero of the 17 stable cases produced
one.** Non-durable clarification is therefore almost certainly not an
independent defect but a symptom of the same lane indecision as family E: the
turn commits to neither logging nor recording an answerable ask. It remains a
correctness bug in its own right — the user cannot complete the interaction at
all — but it is likely the SAME repair.

⚠ **Case 18 carries the durability defect too**, despite being 8/8 durable ASK
in the targeted check hours earlier. The defect is not confined to cases that
fail their label; it also reaches the one case whose label the system reliably
meets.

## ⛔ FAMILY B IS PARTLY THE INSTRUMENT, NOT THE PRODUCT

The frozen calorie/protein ranges were drafted 2026-08-26. Several family-B
"stable failures" are boundary grazes against those drafted bounds:

| case | worst miss | reps failing |
|---|---|---|
| 8 | **−2 kcal (−0.3 %)** | 1 of 4 |
| 21 | −2.7 g protein (−5.3 %) | 2 of 4 |
| 3 | −4.0 g protein (−7.7 %) | 1 of 4 |
| 12 | +30 kcal (+2.6 %) | 4 of 4 |
| 15 | −30 kcal / −4.0 g protein | 4 of 4 |
| 20 | **−138 kcal (−19.8 %)** | 4 of 4 |

Case 15 logs **585 kcal exactly, four times of four** — perfect determinism, 30
kcal under a floor that was drawn by hand. **A measurement that cannot separate
"product wrong" from "range drawn 3 % too tight" is not evidence about the
product.** Family B ranges are to be validated against source data LATER; this
is explicitly NOT a prerequisite for the determinism tranche. Case 20 is pulled
out of this discussion entirely — see `CF28`.

## ⚠ THE FIXED-vs-CONFIGURABLE DISCRIMINATOR IS OBSERVATIONAL ONLY

All 9 stable passes are **named fixed menu items or explicit counts** (Jersey
Mike's *Regular #7*, Chick-fil-A *12-count*, *2* Costco slices, *3 eggs / 2
patties*). Seven of 8 unstable cases are **build-your-own, unbranded, or
homemade**. The minimal pair: Sweetgreen *"Chicken Pesto Parm bowl"* (named) is
4/4 stable pass; CAVA *"Greens and Grains bowl with steak, hummus"*
(build-your-own) is unstable. Two bowls, two fast-casual chains, opposite
behaviour.

⛔⛔ **THIS IS NOT POLICY AND MUST NOT BE ENCODED AS ONE.** It was discovered on
this same corpus and explains the data it was derived from. Two earlier
criteria died exactly this way — the last one, "dish vs vessel", was declared
falsified on n=1 and the falsification itself did not survive n=8. **The
criterion is earned only by held-out discrimination**: new configurable-but-
highly-specified items and new fixed-but-composition-heavy items, scored
out-of-sample. If configurability predicts instability out-of-sample, the
criterion is earned. If not, decomposition goes one layer lower.

## Decisions taken on this evidence

- **DEFAULTABILITY is NOT opened as a tranche.** One independent case is not a
  population. **Case 23 stays registered as a specific gap** until a second
  independent anchor appears. **Case 16 belongs to OILS**
  (`MATERIALITY_TRANCHE_CLOSED_2026-08-27.md:111,156`).
- **Case 20 is pulled out as its own registered nutrition defect — `CF28`.**
- **The magnitude/span-threshold result stays retired.** `impact_cal` on the
  targeted check overlapped almost completely across cases 11/23/18 and the
  burrito-bowl control (`[230,250,250]` / `[220×5,250×2]` /
  `[250,250,300,350,350]` / `[150…350]`). Resurrecting span thresholds would be
  regression-by-forgetting.
- **Next tranche: determinism / decomposition** (D+E+F — 8 cases, 13 defect
  instances). See `DETERMINISM_DECOMPOSITION_TRANCHE_2026-08-27.md`.

## Re-running

```
TEST_POSTGRES_URL=postgresql+psycopg://$(whoami)@localhost:5432/arnie_test \
ARNIE_DATABASE_URL=$TEST_POSTGRES_URL DATABASE_URL=$TEST_POSTGRES_URL \
REPS=4 OUTJSONL=/tmp/sweep.jsonl python scripts/sweep_case_stability.py
python scripts/classify_case_stability.py /tmp/sweep.jsonl
```

The rerun after the determinism repair compares against THIS file. The family
assignments above are the frozen population; a rerun may change outcomes but
must not silently redefine who is in which family.
