# CF28 — REGISTERED: inconsistent package-semantics handling on a multi-serving packaged product

**Rewritten 2026-08-27 under production config. Rule-0 only: registered, not
implemented. Deliberately NOT folded into DEFAULTABILITY — see below.**

⛔⛔ **THIS SUPERSEDES THE ORIGINAL REGISTRATION, WHICH WAS WRONG.** The first
version claimed *"a mechanically identified packaged product is priced at ONE
serving of a MULTI-serving package"* — a silent mis-pricing, 4/4, worst miss
−138 kcal (−19.8 %), with a clean arithmetic proof. **Every one of those
numbers came from a run in which `NUTRITION_RESOLVER_MODE`, `FOOD_GATE_MODEL`
and `DEFAULT_MODEL` were all unset.** None of them survives.

## What is actually observed

Utterance: *"Trader Joe's Butter Chicken and a Garlic Naan"*. Production config
(`STABILITY_BASELINE_V2_PRODCONFIG_2026-08-27.md`), 2 reps.

| rep | outcome | what happened |
|---|---|---|
| 1 | **ASK** | *"One package of the butter chicken, or did you split it? And the naan, one piece or two?"* |
| 2 | **LOG** | Butter Chicken 420 kcal / 21.0 g · Garlic Naan 230 kcal / 6.0 g — **650 kcal / 27.0 g**, 2 rows |

Frozen expectation: cal `[698,1162]`, protein `[26,44]`, rows `[2,2]`.

**Rep 1 asks EXACTLY the right question.** The system demonstrably possesses
the concept of package-vs-serving on this product and raises it unprompted.
Rep 2 does not ask, and logs a number 48 kcal (−6.9 %) below the floor with
protein and row count both INSIDE their ranges.

## The defect is inconsistency, not mis-pricing

The claim this file now makes is narrow and supported: **the same utterance
sometimes surfaces package semantics as a question and sometimes silently
resolves them.** A user cannot know which behaviour they received.

⛔ **THE ARITHMETIC PROOF IS WITHDRAWN.** It stated that doubling the entrée put
BOTH dimensions inside the frozen range at once, and that two independent
dimensions resolving on one correction could not be coincidence. Under
production config it no longer holds:

```
calories   420 × 2  +  230  =  1070   ∈ [698, 1162]   ✅
protein     21 × 2  +    6  =    48   ∉ [ 26,   44]   ⛔ overshoots
```

One dimension resolves, the other breaks. The servings-factor hypothesis is
**not supported** by the current evidence and must not be carried forward.

⚠ **The −19.8 % magnitude is also withdrawn.** Under production config the miss
is −6.9 %, which is close enough to the hand-drawn family-B bounds that it
cannot be cleanly separated from range-calibration error. **The size of this
defect was itself a configuration artifact.**

## ⚠ The zero-retrieval observation, correctly scoped

`search_food_database` was called **0 times in all 50 turns** of the
production-config run, with `NUTRITION_RESOLVER_MODE='live'`. That is a real
observation and it survived the config correction — but it is a fact about the
**TOOL**. The nutrition resolver is a separate internal path, so *"the product
was never looked up"* remains **unproven**. Establishing it requires reading the
resolver path, not counting tool calls.

## Why this stays separate from DEFAULTABILITY

DEFAULTABILITY asks *when may a well-identified meal be logged under a stated
assumption instead of asked about* — a POLICY question over a population of 8
cases that ask **consistently**. Case 20 does not belong to it: the problem is
not that it asks, nor that it logs, but that it does **both** for one input.
Folding an inconsistency finding into a policy tranche would let the policy
question absorb a determinism question and quietly answer it by fiat.

## Rule-0 status

Registered only. No code change, no test, no label change. Related: `CF20`,
`CF25`, `CF26`, `CF27`, and the residual determinism defects in
`DETERMINISM_DECOMPOSITION_TRANCHE_2026-08-27.md`.
