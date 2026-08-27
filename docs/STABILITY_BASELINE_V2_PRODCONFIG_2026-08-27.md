# STABILITY BASELINE v2 — PRODUCTION CONFIG — 2026-08-27

**SUPERSEDES `STABILITY_SWEEP_FROZEN_2026-08-27.md`, which was measured under
an unpinned configuration and is retained only as evidence of that failure.**

Tree `834924b`. 25 cases × **2 reps = 50 turns**. Zero UNMEASURED. SELFTEST OK.
Turn-level pass **17/50 (34 %)**.
Raw: `data/corpus/stability_sweep_v2_prodconfig_2026-08-27.jsonl` — its FIRST
LINE is the resolved configuration.

```
FOOD_GATE_MODEL   = 'true'      (dashboard-confirmed by Danny 2026-08-27)
NUTRITION_RESOLVER_MODE = 'live'
DEFAULT_MODEL     = 'claude-sonnet-4-6'
TURN_COORDINATOR_MODE = 'new_observe'
FOOD_COMPOSER     = 'true'
declared deviations: PROACTIVE_MESSAGING_ENABLED=false (no outbound messages
for synthetic identities) · TURN_COORDINATOR_OBSERVE_DEEP=false (read-only
second interpreter pass; cost, not fidelity) · 6 unused surface flags
```

## ⚠ n=2 — THIS IS DETECTION, NOT CERTIFICATION

A truly unstable case shows `AA` half the time. **A flip proves instability; a
prose-only ask proves a correctness bug; agreement proves nothing.** The
stable-ASK population below is a SHORTLIST. A 60-turn confirmation (10 cases ×
6 reps) is queued against it and must land before any tranche is frozen on it.

## The 25 cases

| case | frozen | seq | pass | rows | exp rows | bucket | meal |
|---:|---|---|---:|---|---|---|---|
| 1 | LOG_COMPLETE | `·A` | 0/2 | — | [1, 1] | unstable | Subway Footlong Turkey on Italian Herbs & Ch |
| 2 | LOG_COMPLETE | `AA` | 0/2 | — | [2, 2] | stable failure | Five Guys Little Cheeseburger and a small fr |
| 3 | LOG_COMPLETE | `AA` | 0/2 | — | [2, 3] | stable failure | Panda Express Bigger Plate: Orange Chicken,  |
| 4 | LOG_COMPLETE | `LL` | 1/2 | 3,3 | [2, 3] | stable failure | Chick-fil-A 12-count nuggets, medium fries,  |
| 5 | LOG_COMPLETE | `LL` | 2/2 | 1,1 | [1, 1] | stable pass | Jersey Mike's Regular #7 Turkey and Provolon |
| 6 | LOG_COMPLETE | `LL` | 2/2 | 3,3 | [2, 3] | stable pass | Taco Bell Crunchwrap Supreme, a Beefy 5-Laye |
| 7 | LOG_COMPLETE | `LL` | 2/2 | 2,2 | [2, 2] | stable pass | Wendy's Dave's Single and a small fries |
| 8 | LOG_COMPLETE | `AA` | 0/2 | — | [2, 3] | stable failure | Popeyes 3-piece tenders, Cajun fries, and a  |
| 9 | LOG_COMPLETE | `AL` | 0/2 | 5 | [1, 1] | unstable | CAVA Greens and Grains bowl with steak, humm |
| 10 | LOG_COMPLETE | `LL` | 2/2 | 1,1 | [1, 1] | stable pass | Sweetgreen Chicken Pesto Parm bowl |
| 11 | LOG_COMPLETE | `··` | 0/2 | — | [1, 1] | SILENT | Chipotle burrito with chicken, white rice, b |
| 12 | LOG_COMPLETE | `AA` | 0/2 | — | [2, 2] | stable failure | Panera Bacon Turkey Bravo and a bag of chips |
| 13 | LOG_COMPLETE | `LL` | 2/2 | 2,2 | [2, 2] | stable pass | Starbucks Double-Smoked Bacon sandwich and a |
| 14 | LOG_COMPLETE | `AA` | 0/2 | — | [2, 2] | stable failure | Shake Shack SmokeShack and fries |
| 15 | LOG_COMPLETE | `LL` | 0/2 | 3,3 | [3, 3] | stable failure | A California roll, a spicy tuna roll, and mi |
| 16 | LOG_COMPLETE | `AA` | 0/2 | — | [3, 3] | stable failure | 8 oz sirloin, a loaded baked potato, and a C |
| 17 | LOG_COMPLETE | `AA` | 0/2 | — | [2, 2] | stable failure | A chicken Caesar wrap and an apple |
| 18 | ASK_CORRECT | `AA` | 2/2 | — | [1, 4] | stable pass | A Mediterranean chicken platter with rice, p |
| 19 | LOG_COMPLETE | `LL` | 0/2 | 1,1 | [1, 1] | stable failure | 2 Costco pepperoni pizza slices |
| 20 | LOG_COMPLETE | `AL` | 0/2 | 2 | [2, 2] | unstable | Trader Joe's Butter Chicken and a Garlic Naa |
| 21 | LOG_COMPLETE | `LL` | 2/2 | 3,3 | [3, 3] | stable pass | A Fairlife Core Power Elite, a Quest Bar, an |
| 22 | ASK_CORRECT | `AA` | 2/2 | — | [4, 4] | stable pass | 3 eggs, 2 turkey sausage patties, sourdough  |
| 23 | LOG_COMPLETE | `AA` | 0/2 | — | [1, 1] | stable failure | A Greek yogurt parfait with granola, berries |
| 24 | LOG_COMPLETE | `AA` | 0/2 | — | [2, 2] | stable failure | A homemade turkey burger on a brioche bun wi |
| 25 | LOG_COMPLETE | `AA` | 0/2 | — | [1, 1] | stable failure | A large poke bowl with salmon, tuna, rice, e |

`L`=logged · `A`=asked (durable pending question) · `·`=NOTHING (no row, no
question). `pass` requires the frozen terminal AND, on a LOG, row count,
calories and protein all inside their frozen ranges.

## Buckets, and what changed against the invalid run

| bucket | invalid (unpinned) | **PRODUCTION CONFIG** |
|---|---:|---:|
| stable pass | 9 | **8** — `5,6,7,10,13,18,21,22` |
| stable failure | 8 | **13** — `2,3,4,8,12,14,15,16,17,19,23,24,25` |
| unstable | 8 | **3** — `1,9,20` |
| silent / broken | 0 | **1** — `11` |
| **representation instability** | 3 | **0** |
| **`LOG_COMPLETE` + stable ASK** | 2 (→1 after OILS) | **10** |
| turn-level pass | 54/100 | **17/50** |

## ⭐⭐⭐ REPRESENTATION INSTABILITY WAS AN ARTIFACT OF THE WRONG GATE

Zero cases produce differing row counts under production config. The `[5,1]`,
`[1,2,2]`, `[1,5,5]` decompositions that defined family D came from the LEGACY
free-tool fallback, which 23 of 25 cases fell into when `FOOD_GATE_MODEL` was
unset. Predicted by the case-11 divergence trace (`route_owner='gate_regex'`,
`legacy_escape_reason='no_food_shape'`, every rep) and confirmed here.

**The determinism/decomposition tranche as opened is largely dissolved.** What
remains is 3 unstable cases and 1 silent case, not 8 cases and 13 instances.

## ⭐⭐⭐ DEFAULTABILITY HAS A REAL POPULATION — 10 CANDIDATES

`2, 3, 8, 12, 14, 16, 17, 23, 24, 25` — all frozen `LOG_COMPLETE`, all `AA`.
It was closed at a population of 1 on the invalid run. **26 of 27 ASK turns
come through the STRUCTURED lane**, and the asks are specific and well-formed:

> *"SmokeShack I've got at 550 cal, 29g protein. Fries are sitting open —
> regular or…"*
> *"Panera Bacon Turkey Bravo is sitting at 840 cal, 45g protein. The chips
> are…"*

This is a genuine product-policy question — when may a well-identified meal be
logged under a stated assumption instead of asked about — not a defect.

## Revisions forced by this run

**1 — `c7d3ca8`'s premise is inverted.** Its docstring records *"23 of 25
clarifications arrived through the `note_food_clarification` TOOL"*, measured
under the same unpinned config. Under production config **1 of 27 ASK turns
used the tool; 26 used the structured lane.** The change is merged
(`27983be`) and **NOT deployed. Hold the deploy** until the premise is
re-established: it was built to fix a path carrying ~4 % of production
clarifications, not 92 %.

**2 — `CF28` overstates.** Case 20 is now `A L`, not 4/4 wrong. Its rep-1 ask
is *exactly* the per-package question — *"One package of the butter chicken,
or did you split it? And the naan, one piece or two?"* — so the defect is
INCONSISTENCY, not silent mis-pricing. The clean arithmetic no longer holds
either: doubling now yields protein 48 against a `[26,44]` ceiling. ⚠ Zero
`search_food_database` calls across all 50 turns even with the resolver live —
that observation survives, but it is a fact about the TOOL; the resolver is a
separate internal path and "zero retrieval" was more than was proved.

**3 — case 11 is deterministically broken**, `··`, both reps prose-only with no
answerable state. One of them CALLED `note_food_clarification` and still
produced no pending question. ⛔ **NOT caused by the materiality demotion** —
`_proposed_ask_is_material` returns True for the observed inputs
(`impact_cal=250`, `item_cal=950`) in all three modes. Cause unknown; needs a
targeted trace.

## The instrument

Unchanged from v1 except that it now **refuses to run under an unpinned
configuration** (`58e6413`): it parses `render.yaml`, compares every declared
flag, and raises `ConfigDrift` naming each mismatch unless the flag is listed
in `_ALLOWED_DEVIATIONS` WITH a written reason. The resolved config is the
output's first line; the classifier prints it before any numbers and warns when
a run predates pinning. `ONLY_CASES` runs a subset through the SAME instrument
and the SAME guard, so a confirmation pass is never a second instrument.

⭐ **THE LESSON.** v1 recorded the tree SHA and a self-tested reader. Both were
true. Neither pinned the product: all 18 declared flags were unset, including a
different `DEFAULT_MODEL`, the resolver off, and a gate that admitted 2 of 25
cases to the structured lane instead of 25 of 25.

## Re-running

```
source scripts/prodenv.sh
REPS=2 OUTJSONL=/tmp/sweep.jsonl python scripts/sweep_case_stability.py
python scripts/classify_case_stability.py /tmp/sweep.jsonl
```
