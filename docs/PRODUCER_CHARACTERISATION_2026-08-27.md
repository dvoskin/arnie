# PRODUCER CHARACTERISATION — **the structured vocabulary is 2 values for 7 subjects**

**Measurement, 2026-08-27, tree `0a0040e`.** 8 cases × 3 reps = 24 turns,
production config, 0 errors, 18 asks.
Raw: `data/corpus/producer_characterisation_2026-08-27.jsonl`.
Instrument: `scripts/characterise_ask_producer.py`.

⛔ **NO REPAIR PROPOSED.** This answers the tranche-shaping question and puts a
scoping decision to Danny.

## What the interpreter actually emits

```
ambiguities[].field  over 24 turns:   {'quantity': 18, 'prep': 12}
```

**TWO values. That is the entire structured vocabulary**, against **seven**
semantic subjects. With `items[].branded` as the only other structured signal,
the producer can express at most **4 states** (`quantity|prep` ×
`branded|unbranded`).

`consumption_complete`, `unstated_extras`, `portion_multiplier` and
`identity_variant` have **no structured representation available at all.**

## TWO DISTINCT DEFECTS, not one

### D1 — asks produced with ZERO ambiguity records: **5 of 18**

Every one is case 2 or case 3 — **the consumption and multiplier cases**:

```
c2: "The little cheeseburger and fries, did you finish both, or leave some?"   n_amb=0
c3: "For the Orange Chicken, was that one scoop or two?"                       n_amb=0
c3: "regular entree scoop or did you double it?"                               n_amb=0
```

The question is asked with **nothing structured behind it**. This is not a
vocabulary gap — it is a producer that skipped recording. **Plausibly a code
path question, and plausibly fixable under the prompt freeze.**

### D2 — the structured vocabulary cannot express the subjects

Where records DO exist, they are `quantity` or `prep` and nothing else. c9
emits **three `quantity` records** for a bowl whose question bundles size,
extras and base portion. **Not fixable in code**: the information was never
produced.

## Compound asks: the mechanism EXISTS but is rarely exercised

```
asks with >1 ambiguity record : 10
...of which >1 DISTINCT field :  3   (all case 24, 'prep' + 'quantity')
```

Exit criterion 3 is therefore **not architecturally blocked** — the interpreter
does emit multiple records with distinct fields. It simply has only two fields
to distinguish with.

## ⚠⚠ THE DISTINGUISHING INFORMATION EXISTS — AS PROSE

`points[].qs` is populated on 10 asks and **contains exactly the missing
subjects**:

```
c16  "what toppings - cheese, bacon, sour cream, butter?"      <- unstated_extras
c23  "about how big - a small snack cup or a full meal-size?"  <- menu-size-shaped
c24  "pan-fried, baked, or grilled, and how lean was it?"      <- preparation_fat
```

⛔⛔⛔ **AND IT MUST NOT BE USED.** `points[].qs` is natural language. Deriving
the canonical subject from it is **precisely the prose inference this tranche
was created to remove** — the `_FACET_KINDS` mechanism, rebuilt one layer down.
c16's ambiguities say `prep, prep, prep` while its `qs` asks about toppings;
trusting the prose would "fix" the type by reintroducing the defect.

**The information is present but not in a form that may be used.**

## ⭐⭐⭐ THE SCOPING ANSWER

The tension flagged before the run resolves against the freeze:

> **Producer completeness for all seven subjects is NOT achievable under the
> frozen food prompt.** The interpreter's structured ambiguity vocabulary is
> two values, and the missing subjects exist only as prose.

`D1` may be fixable in code. **`D2` cannot be.**

## Decision required — three shapes, none taken

1. **Prompt exception** — extend `ambiguities[].field`'s vocabulary. Directly
   contradicts the standing FROZEN-prompt rule; needs an explicit exception.
2. **Re-scope to what the producer CAN express** — accept a 2-subject reality
   (`prep` vs `quantity`, i.e. roughly OILS vs everything-else) and size policy
   only there. Honest, much smaller, and needs no exception.
3. **A second STRUCTURED pass in code** — a separate typed call that returns a
   subject enum. Not prose inference and not a prompt change, but it adds a
   model call per ask and a new failure mode.

⚠ Whichever is chosen, **`D1` should be scoped separately**: 5 of 18 asks carry
no structured ambiguity at all, and no vocabulary change fixes an absent record.
