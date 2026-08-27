# HELD-OUT RESULT — **H1 REFUTED. NO CRITERION WRITTEN.**

12 cases × 4 reps = 48 turns, production config, zero UNMEASURED, SELFTEST OK.
Predictions preregistered at `1d4bddd` **before** the run.
Raw: `data/corpus/heldout_defaultability_result_2026-08-27.jsonl`.

**H1**: *the system asks when a confidently-priced PRIMARY is accompanied by an
UNSPECIFIED SECONDARY component.*

## H1 is refuted by its own registered falsification conditions

| case | H1 | observed | |
|---:|---|---|---|
| 110 `A bowl of oatmeal` | LOG — no secondary exists | **`AAAA`** | ⛔ asks anyway |
| 111 `Some grilled chicken and a medium McDonald's fries` | ASK | `AAAA` | ⛔ asks about the **PRIMARY** |

c111's question, all four reps: *"McDonald's fries at 340, and the chicken is
the open one."* It prices the fixed SECONDARY confidently and asks about the
vague PRIMARY — the exact inverse of H1.

**Matched pairs separated 2 of 4.** 101/105 ✅ · 102/106 ✅ · 103/107 near
(3/4 vs 0/4) · **104/108 not at all** — both `LLLL`.

## What the controls DID establish (positive results)

- **c109 `LLLL`** — five components, all specified. **Component count is not
  the driver.**
- **c112 `LLLL`** — three named fixed items. **Brandedness is not the driver.**

Both proxies are eliminated. That is real information and it survives H1.

## H2 emerged, fits better, and is NOT adopted

*The ask fires when a component's quantity is UNBOUNDED by the utterance* —
"fries", "a side of rice", "a bowl of oatmeal", "some chicken" — and not when
bounded, **including countable items**: "a croissant" is one croissant, which
is why 104 logged.

- **12/12 in-sample** on the held-out set.
- **6/8 out-of-sample** against the 8 DEFAULTABILITY cases (a genuinely
  different set, so this is a real test).

⛔⛔⛔ **H2 IS NOT PROMOTED.** It was derived post-hoc from the 12 cases that
refuted H1. Adopting it now is precisely the error that killed the previous
three criteria — a rule inferred from the cases it was tested on. **The rule
was: if the set does not separate cleanly, decompose one layer lower rather
than tune the rule to fit.** It did not separate cleanly.

## ⭐⭐⭐ THE DECOMPOSITION: the ask is not ONE thing

c2 is the finding. It is fully specified — *"Five Guys Little Cheeseburger and
a small fries"* — and asks **8/8** anyway:

> *"did you finish both, or leave some?"*
> *"did you eat the whole burger and the full order?"*

That is **consumption completeness**, not quantity boundedness. c3 is a third
shape: a portion MULTIPLIER inside a fixed container (*"was each one a regular
single scoop or did you double it up?"* — a Panda Bigger Plate does not bound
per-entrée scoops).

**At least three distinct ask types are now visible:**

1. **unbounded quantity** — "fries", "a bowl of oatmeal"
2. **consumption completeness** — "did you finish it"
3. **portion multiplier inside a fixed container** — "single or double scoop"

DEFAULTABILITY has been asking *"which MEALS may be defaulted"*. The evidence
says that is the wrong unit. **The right unit is the ASK TYPE**: each of the
three has a different defensible default, and one of them (consumption
completeness) may have none at all — no amount of food knowledge tells you
whether someone finished their fries.

## Next work

**Classify the ask TYPE across every run already collected** — the `kind` field
on `note_food_clarification` plus the question text across the v2 baseline, the
60-turn confirmation, and this held-out set. That is ~160 recorded turns and
costs nothing new to analyse.

Only once the ask types are enumerated and counted does the defaultability
question become answerable, because it is really three questions.

⚠ Do not write a criterion for H2, or for any ask type, before that
classification exists.
