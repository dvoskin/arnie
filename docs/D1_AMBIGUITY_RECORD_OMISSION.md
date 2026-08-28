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
