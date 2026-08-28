# D1 — AMBIGUITY RECORD OMISSION

**Opened 2026-08-27. SEPARATE from D2 by explicit instruction — and the
separation is the point.**

> **Exit: every ask-producing path emits at least one structured ambiguity when
> an unresolved semantic subject exists.**

## The defect

**5 of 18 asks carried ZERO ambiguity records** (`producer_characterisation_
2026-08-27.jsonl`). Every one was case 2 or case 3:

```
c2  "The little cheeseburger and fries, did you finish both, or leave some?"   n_amb=0
c3  "For the Orange Chicken, was that one scoop or two?"                       n_amb=0
c3  "regular entree scoop or did you double it?"                              n_amb=0
```

The question is asked with **nothing structured behind it**. The prompt's own
rule — *"ONE UNKNOWN, ONE ENTRY... nothing may appear in one and not the
other"* — is being violated: a question exists in `points` with no
`ambiguities` entry.

## ⛔⛔⛔ WHY THIS MUST NOT BE FOLDED INTO D2

**A path that emits nothing still bypasses the entire contract, however rich
the vocabulary becomes.** Extending the field vocabulary (D2) cannot repair an
absent record, and — the real hazard — **fixing D2 must not be allowed to make
D1 look solved.** If the vocabulary work lifts overall coverage, a residual
zero-record path is easy to mistake for noise.

Confirmed empirically: after the D2 prompt exception, c2 rep1 still emits
`n_amb=0`. The vocabulary changed; the omission did not.

## Not started

No repair proposed. The first question is whether the omission is a distinct
ask-return path (several of the 7 sites build a question without an
interpreter ambiguity) or an interpreter behaviour on these utterances.

---

# ATTRIBUTION — from data already on disk, zero model turns

53 asks pooled across the three characterisation runs; **19 zero-record.**
Discriminator: was `_ask_types_from` **called with an empty list** (an
interpreter-backed site ran and got nothing) or **never called** (a hardcoded
site, or a producer outside `food_turn`'s seven ask sites)?

| population | n | cases | signature |
|---|---:|---|---|
| **A — CALLED, `n_amb=0`** | **14** | **2, 3 only** | interpreter returned an ask with ZERO ambiguities |
| B — NEVER called | 5 | 1, 9 only | `ask_types=[]` |

## ⛔ POPULATION B IS AN INSTRUMENT ARTIFACT, NOT A DEFECT

Pending-question `kind` settles it:

```
food_structured_ask   ask_types present  24/24   <- the structured lane is 100% TYPED
conversation_hook     ask_types present   0/2    <- NOT a food clarification at all
food_clarification    ask_types present   0/1    <- the TOOL path
```

`c1 rep2` is a **`conversation_hook`** — a general conversational follow-up the
harness counted as a food ask. The one `food_clarification` is the
`note_food_clarification` tool path, which records no `ask_types` **by my own
choice**: that payload write was reverted to avoid raising the
pending-mutation ratchet. A known, documented coverage hole — not an omission
defect.

⭐ **D1's real size is 14 of 19, cases 2 and 3 only.** The instrument inflated
it by counting non-food asks.

## The answer to the diagnostic question

> *If cases 2 and 3 concentrate on the acquisition/split-refusal sites, D1 is
> probably a plain code-path omission and the model may not need to change.*

**They do not.** Neither hardcoded site fired — `6533` writes
`['consumption_complete']` and `6497` writes `['unclassified']`; we observed
`[]`. Every case-2/3 zero-record ask **called the helper and received an empty
list**, so an interpreter-backed site ran and the interpreter produced
`action:ask` with `points` and no `ambiguities`.

> ⛔ **D1 DOES NOT COLLAPSE INTO A DETERMINISTIC CODE FIX. It is
> interpreter-output.**

## ⭐ AN ATTRACTIVE HYPOTHESIS, ALREADY FALSIFIED

*"The interpreter omitted the record because it had no valid field name for
consumption or multiplier."* Tempting — cases 2 and 3 are exactly the two
subjects the vocabulary lacked, which would have made D1 and D2 one defect.

**The post-exception runs refute it.** Both field values were added and **c2
still emitted zero records on 5/5 of its asks.** The omission is independent of
vocabulary availability. D1 and D2 remain genuinely separate.

## What D1 actually is

A **compliance failure against a rule the prompt already states**:

> *"ONE UNKNOWN, ONE ENTRY. Every question you put in `points` must have its own
> entry in `ambiguities` naming the same field, and nothing may appear in one
> and not the other."*

The instruction exists and is explicit. The model ignores it on two specific
utterance shapes — Five Guys (consumption) and Panda Bigger Plate (multiplier) —
**c2 7/8 and c3 7/9 of their asks.** So *adding a rule* is unlikely to be the
repair: the rule is there and is being violated deterministically by case.

⚠ **Not yet investigated:** whether these two utterances share a structural
property that routes them past the rule, or whether the model treats a
consumption/multiplier question as not-an-ambiguity by nature. That is D1's
first real question, and it is NOT answerable from data on disk.
