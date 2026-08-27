# ASK-TYPE TAXONOMY — 158 turns, 105 asks

Derived by READING all 105 asks recorded across the v2 baseline, the 60-turn
confirmation and the held-out set. Production config throughout.

⚠ **The counts are a lower bound.** The regex coding aid in
`scripts/classify_ask_types.py` reads only `questions[0]` and leaves **24 of
105 (23 %) unclassified**; the compound figure it reports (13 %) is therefore
an undercount — reading shows compounding is common. **The taxonomy came from
the text; the regexes only count it.**

## ⛔⛔ 103 OF 105 ASKS CARRY NO TYPE AT ALL

Only **2** asks recorded a `kind` field (`ingredient` ×2, `cook_method` ×1).
The other 103 came through the structured lane, **which records no ask type**.

**So none of this is measurable in production today.** Every number below comes
from re-reading question text in a local harness. This is the cheapest and
highest-leverage engineering item on the board: the structured lane should
record an ask type at the point it decides to ask.

## The seven types

| type | turns | cases | default available? |
|---|---:|---:|---|
| **T1 menu size option** — *"small, medium, or large?"* | 23 | 6 | ⭐ **STRONG** — enumerable set, known values, modal size |
| **T2 continuous portion** — *"how much rice?"* | 21 | 9 | MEDIUM — standard serving, wider variance |
| **T3 consumption completeness** — *"did you finish it?"* | 8 | 2 | ⛔ **NONE from food knowledge** |
| **T4 preparation / added fat** — *"grilled or pan-seared?"* | 15 | 5 | **OILS owns this** |
| **T5 unstated extras** — *"any toppings?"* | 12 | 6 | STRONG — assume as stated |
| **T6 portion multiplier** — *"single or double scoop?"* | 9 | 2 | STRONG — assume single |
| **T7 identity / variant** — *"little or regular?"*, *"whole or half?"* | 8 | 3 | ⚠ **not a portion question — identity** |

## ⭐⭐⭐ THE 8 "DEFAULTABILITY CASES" ARE NOT ONE POPULATION

| case | types asked |
|---:|---|
| 14 | **T1** only |
| 25 | **T2** only |
| 3 | **T6** only |
| 12 | T1 + T7 |
| 17 | T2 + T7 |
| 23 | T2 + T5 |
| 24 | T2 + **T4** |
| 2 | T2 + **T3** + T5 + T7 |

**At least five different questions were wearing one label.** A single
defaultability policy over "these 8 meals" would have been a policy over five
unrelated decisions — the four-tables condition `skills/nutrition/materiality.py`
was written to end, re-created one layer up.

Two consequences fall out immediately:

- **c24 asks T4** — preparation/added fat. **OILS's reach is wider than cases
  16 and 22**; T4 appears in 16, 18, 22, 24 and 110.
- **c2's distinguishing type is T3.** It is the case that refuted H2, and it is
  the ONE type where no amount of food knowledge yields a default. Only the
  user knows whether they finished their fries.

## Re-scoping DEFAULTABILITY

The tranche should target **ask TYPES, not meals**:

- **T1 is the clean first target.** Enumerable options, known per-chain values,
  a strong modal default, and a held-out demonstration already exists: 101 and
  102 ask `AAAA` while their matched pairs 105/106 — same utterance, size
  specified — log `LLLL`.
- **T5 and T6 are strong defaults** and small.
- **T2 is the hard middle** and the largest by case count.
- **T3 is EXCLUDED.** No food-knowledge default exists.
- **T4 goes to OILS**, with its scope widened.
- **T7 is an identity question** and belongs to the canonical identity lane,
  not to a defaulting policy.

⛔ **STILL NO CRITERION.** This taxonomy is descriptive, derived from 105 asks
in one config, and 23 % of them are unclassified. It reorganises the question;
it does not answer it. H1 is refuted and H2 remains unpromoted.
