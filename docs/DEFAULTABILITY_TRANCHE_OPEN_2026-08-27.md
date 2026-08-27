# TRANCHE — DEFAULTABILITY — **OPEN**

**Authorized population = 8.** Opened 2026-08-27 on
`STABILITY_BASELINE_V2_PRODCONFIG_2026-08-27.md` and its 60-turn confirmation.
Supersedes `DEFAULTABILITY_EVIDENCE_CONTRACT_DRAFT.md`, whose criteria were
drafted against invalid-config evidence.

## The question

**When may a well-identified meal be logged under a STATED assumption instead
of asked about?**

Not "ask less". The 8 cases below produce *good* questions. The question is
whether a defensible default exists that a user would rather receive than be
asked for.

## The population

Frozen `LOG_COMPLETE`, observed **8/8 ASK** across both production-config runs
(2 reps + 6 reps, same instrument, same config guard):

| case | meal |
|---:|---|
| 2 | Five Guys Little Cheeseburger and a small fries |
| 3 | Panda Express Bigger Plate: Orange Chicken, Teriyaki Chicken… |
| 12 | Panera Bacon Turkey Bravo and a bag of chips |
| 14 | Shake Shack SmokeShack and fries |
| 17 | A chicken Caesar wrap and an apple |
| 23 | A Greek yogurt parfait with granola, berries, honey, and almonds |
| 24 | A homemade turkey burger on a brioche bun with… |
| 25 | A large poke bowl with salmon, tuna, rice… |

**Case 16** shows the identical pattern at 8/8 but **remains OILS-owned**
(`MATERIALITY_TRANCHE_CLOSED_2026-08-27.md:111,156`). It is evidence, not a
member.

**Case 8** (Popeyes) flipped `AAALAA` and LEAVES the population. Its single LOG
was structurally CORRECT — 3 rows in `[2,3]`, 860 kcal in `[742,1238]` — so it
is a boundary case, not counter-evidence.

P(8/8 one way | true coin-flip) ≈ 0.4 %. This is no longer a fragile shortlist.

## ⛔⛔⛔ NO CRITERION MAY BE WRITTEN BEFORE HELD-OUT DISCRIMINATION

**Three criteria have now died to the same error — a rule inferred from the
cases it was tested on:**

1. **magnitude / span thresholds** — disproved, retired. `impact_cal` overlaps
   almost completely across asking and logging cases.
2. **"dish vs vessel"** — fitted to three fixtures, then declared falsified on
   **n=1**, and the falsification itself did not survive n=8.
3. **the four-criterion evidence contract** — drafted entirely on
   invalid-config behaviour.

The shape currently visible is: **the primary item is priced confidently and
the question targets an unspecified SECONDARY component.**

> *"SmokeShack I've got at 550 cal, 29g protein. Fries are sitting open —
> regular or…"*
> *"Panera Bacon Turkey Bravo is sitting at 840 cal, 45g protein. The chips
> are…"*
> *"Apple is around 95, the wrap is the one I need to pin down…"*

It was observed on the corpus it would be derived from. **It is a hypothesis.**

## The held-out discrimination set (next work, before any criterion)

Out-of-sample cases, written fresh, scored through the SAME instrument and
config guard (`ONLY_CASES` on a new corpus file):

- **arm A — the shape**: confident primary + unspecified secondary component.
  *Predicted: ASK.*
- **arm B — negative control, should LOG**: fixed/named items with no
  unspecified secondary, where a default is unnecessary.
- **arm C — positive control, should ASK**: genuine ambiguity that is NOT the
  secondary-component shape (unstated preparation, unstated identity).

**If the set separates cleanly, the criterion earns policy status. If it does
not, decomposition goes one layer lower.** Arms B and C exist so the set can
FAIL — an arm-A-only set would confirm anything.

## Standing constraints

- **The magnitude result stays retired.** Do not encode "normal range" as
  food-specific calorie tolerances (Danny, 2026-08-27).
- **Frozen terminal labels unchanged** by this tranche.
- **A second materiality implementation is forbidden** —
  `skills/nutrition/materiality.py` is the one policy
  (`test_there_is_exactly_ONE_materiality_POLICY`).
- **Case 20 is NOT in this tranche.** It is an inconsistency defect (`CF28`);
  folding it in would let a policy question absorb a determinism question.
