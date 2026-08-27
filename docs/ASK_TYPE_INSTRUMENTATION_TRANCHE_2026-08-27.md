# TRANCHE — ASK-TYPE INSTRUMENTATION (next production-code tranche)

**Authorized 2026-08-27. Precedes any T1 defaulting policy.** The system cannot
currently measure its own clarification behaviour: **103 of 105 recorded asks
carry no type at all.**

## ⛔⛔⛔ THIS IS NOT "ADD A FIELD" — TWO VOCABULARIES ALREADY EXIST AND DISAGREE

```
structured lane   core/food_turn.py:4069 _KIND_PHRASING
                  portion · identity · preparation · extras · detail

tool path         core/tools.py  note_food_clarification.kind enum
                  portion · brand · cook_method · ingredient · other
```

They agree on `portion` and diverge everywhere else — `preparation`/`cook_method`,
`identity`/`brand`, `extras`/`ingredient`, `detail`/`other`. **This is the
four-tables condition `skills/nutrition/materiality.py` was written to end,
recreated one layer up.** Two vocabularies for one concept, in the two producers,
that agree today and will disagree later.

## Two defects in the existing vocabularies, not just duplication

**1 — `portion` conflates three types with DIFFERENT defaults.**

| taxonomy type | today | default strength |
|---|---|---|
| T1 menu size option — *"small, medium, or large?"* | `portion` | ⭐ STRONG (enumerable, modal) |
| T2 continuous portion — *"how much rice?"* | `portion` | MEDIUM (standard serving) |
| T6 portion multiplier — *"single or double scoop?"* | `portion` | STRONG (assume single) |

A single `portion` bucket cannot support a T1-only policy, which is exactly the
first policy experiment queued.

**2 — T3 consumption completeness is INEXPRESSIBLE in both vocabularies.**
*"Did you finish both, or leave some?"* is not portion, identity, preparation,
extras, brand, ingredient or cook_method. It falls to `detail`/`other`. **The one
ask type with NO defensible food-knowledge default is the one the system cannot
name.** It would be invisible in any production denominator built on today's
fields.

## The work

1. **ONE vocabulary**, in one module, with a structural test forbidding a second
   — same shape as `test_there_is_exactly_ONE_materiality_POLICY`:
   `menu_size | continuous_portion | consumption_complete | preparation_fat |
    unstated_extras | portion_multiplier | identity_variant`
2. **Emit at the DECISION POINT, durably.** `core/food_turn.py` has **8
   ask-shaped return sites** (1377, 6032, 6120, 6343, 6428, 6497, 6533, plus the
   `_sft` ask path) and **only 2 set a `kind` at all** — and those two set
   `"clarify"` / `"confirm"`, which are turn SHAPES, not question subjects.
   Every site must emit a type.
3. **No text inference. No post-hoc classifier.** `scripts/classify_ask_types.py`
   exists only because the field does not; it reads `questions[0]`, leaves 23 %
   unclassified, and must not become the production mechanism.
4. Map the legacy values forward so historical rows remain readable.

## What it buys

A real production denominator: how often each type occurs, which correlate with
abandonment, which get answered, which could have been defaulted — and
**whether T1 is common enough outside this 158-turn corpus to be worth a
policy at all.** That last question currently has no evidence either way.

## Sequence after this lands

```
ask-type telemetry  ->  T1 menu-size policy  ->  T5 / T6  ->  T2
                        (OILS owns T4, canonical identity owns T7, in their own lanes)
```

- **T1 first**: 23 observed turns, 6 cases, enumerable choices, a modal default,
  and a held-out matched-pair demonstration already exists (101/102 ask `AAAA`;
  105/106 — same utterance, size specified — log `LLLL`).
- **T3 is EXPLICITLY EXCLUDED from DEFAULTABILITY.** *"Did you finish it?"* is
  user state, not food knowledge.
- **T2 is the largest eventual prize and the most dangerous** — "standard
  serving" is inherently softer than "default menu size".

## Gate

Any criterion arising from this tranche is bound by
`tests/test_no_criterion_promoted_from_its_own_corpus.py`.
