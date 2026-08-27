# TRANCHE — DETERMINISM / DECOMPOSITION

**Opened 2026-08-27 on the evidence of `STABILITY_SWEEP_FROZEN_2026-08-27.md`.
Supersedes DEFAULTABILITY as the next clarification-adjacent tranche.**

DEFAULTABILITY is **not** opened: its population is one case (23). Case 16
belongs to OILS. One independent case is not a population.

## What is authorized, and what is not

**Authorized: a ROOT-CAUSE tranche.** Reproduce, trace, find the first
divergence, repair the mechanism, rerun the frozen sweep.

**NOT authorized: a new identity policy.** The hypothesis below is the
strongest current explanation, **not a proven root**, and it was discovered on
the same corpus it explains.

## The hard evidence (this, and only this, is established)

1. **8 cases show representation or terminal instability** — `1,9,11,14,17,18,
   24,25` — across otherwise identical runs on one tree, isolated identities,
   zero UNMEASURED.
2. **All 5 prose-only asks occur inside that unstable population** —
   `{1,9,11,18,24}`.
3. **The 17 stable cases produced 0 prose-only asks.**
4. **Case 18 — an 8/8 stable-ASK anchor hours earlier — now also exhibits the
   durability defect.** The defect is not confined to cases that fail their
   label.
5. **Fixed identity vs configurable identity strongly separates the observed
   population** — but it was discovered on this same corpus.

Points 1–4 are enough to authorize a root-cause tranche. Point 5 is **not**
enough to encode a policy.

## The defect populations

**D — REPRESENTATION INSTABILITY.** The same utterance becomes a materially
different decomposition:

| case | rows across reps | expected | meal |
|---|---|---|---|
| 1 | `5, 1` | `[1,1]` | Subway Footlong Turkey |
| 14 | `1, 2, 2` | `[2,2]` | Shake Shack SmokeShack and fries |
| 25 | `1, 5, 5` | `[1,1]` | large poke bowl |

⭐ **Case 11 is why structure is scored and not just the terminal.** In the
targeted n=8 check it logged 1050 / 1170 / 1100 / 1050 kcal — *every value
inside its frozen range* — while alternating between **1, 5 and 6 rows** for
the same utterance. Terminal-and-calories-only would have called that healthy.
Its true `LOG_COMPLETE` rate was 2/8, not the 4/8 the terminal suggested.

**E — TERMINAL INSTABILITY.** `9,11,17,18,24` flip between ASK and LOG on
unchanged code.

**F — NON-DURABLE CLARIFICATION.** 5 turns. Arnie asks a question **in prose**,
calls no tool, and creates no answerable state — no row, no pending question.
Example (case 11): *"Regular size or the double-protein? And is that a normal
scoop of rice/beans or extra?"* — nothing recorded.

⭐ **F is a correctness bug regardless of frequency**: the user is asked a
question they cannot answer. The interaction is structurally broken, not noisy.
But its perfect containment inside the unstable population (2,3 above) makes it
most likely a *symptom* of E rather than an independent defect — probably the
same repair.

## Sequencing (authorized)

1. ✅ freeze the sweep — `STABILITY_SWEEP_FROZEN_2026-08-27.md`
2. ✅ register case 20 — `CF28_REGISTERED_PACKAGED_SERVING_BASIS.md`
3. ✅ open this tranche
4. ⏭ **reproduce ONE unstable case with a full turn / lane / decomposition
   trace**
5. ⏭ **identify the FIRST divergence** — not the point where damage surfaces
6. ⏭ repair that mechanism
7. ⏭ rerun the frozen 100-turn sweep against `data/corpus/stability_sweep_v1_2026-08-27.jsonl`

**Explicitly deferred: recalibrating family-B ranges.** Validate those against
source data later. D/E/F is already an unambiguous product-defect population
and is the higher-value target — no label calibration is required to know that
one utterance must not produce three different decompositions.

## The held-out experiment (before ANY criterion is written)

Add new cases in two arms and score out-of-sample:

- **configurable but highly specified** — a build-your-own item with every
  component and portion stated
- **fixed but composition-heavy** — a named fixed menu item with many
  components

If configurability predicts instability out-of-sample, the criterion is earned.
If not, decomposition goes one layer lower.

⛔⛔ **THE CORPUS HAS SAVED THIS TRANCHE FROM A FITTED CRITERION TWICE.** The
magnitude/span-threshold rule was disproved and retired. "Dish vs vessel" was
fitted to three fixtures, then declared falsified on **n=1** — and the
falsification itself did not survive n=8 (burrito bowl: 1/1 LOG in the probe,
**0/8** on repetition). Both failures share one shape: **a rule inferred from
the cases it was tested on.** Do not write a third.

## Standing constraints

- **The magnitude result stays retired.** `impact_cal` overlapped almost
  completely across cases 11/23/18 and the burrito-bowl control. Resurrecting
  span thresholds is regression-by-forgetting.
- **Frozen terminal labels are unchanged** by this tranche.
- **Case 23** remains a registered case-specific gap, not a tranche.
