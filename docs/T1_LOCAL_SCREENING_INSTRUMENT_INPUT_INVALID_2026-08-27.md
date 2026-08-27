# T1 LOCAL SCREENING: **INSTRUMENT INPUT INVALID FOR POLICY SIZING**

**Frozen negative result, 2026-08-27, tree `8f418c3`.** 25-meal corpus × 2 reps
= 50 turns, production config, zero UNMEASURED, SELFTEST OK, 27 ASK turns.
Raw: `data/corpus/t1_local_screening_2026-08-27.jsonl`.
Analysis: `scripts/t1_local_distribution.py`.

⛔ **NO REPAIR IS PROPOSED HERE. This finding is the NEXT tranche's input, not
its repair** (Danny, 2026-08-27).

## The ask-type instrumentation is NOT disproven

It did exactly its job. **It is what made this visible at all.** The classifier
reads the interpreter's structured `field`, at the decision point, never from
prose — and that is precisely why the mislabelling could be seen rather than
guessed at. **The failure is UPSTREAM of the classifier:** the structured
ambiguity input is under-typed.

## What was measured

```
ask type                turns   lower bound M/N   ceiling (M+U)/N
menu_size               7         25.9%            37.0%
continuous_portion      11        40.7%            51.9%
preparation_fat         10        37.0%            48.1%
identity_variant        2          7.4%            18.5%
consumption_complete    0          0.0%            11.1%
unstated_extras         0          0.0%            11.1%
portion_multiplier      0          0.0%            11.1%
(unclassified)          3         11.1%
N = 27 asks · C = 24 classified · U = 3 unclassified · compound 6/27
```

## The four findings

**1 — `menu_size` 25.9 %–37.0 % IS RETIRED AS A SIZING RESULT.** The bucket is
contaminated by at least one `consumption_complete` ask:

```
case 2 rep2   "...Did you finish the whole little..."     typed menu_size
case 3 rep1   "regular entree scoop or a bigger/double?"  typed continuous_portion
```

**2 — THREE TYPES HAVE ZERO PROVEN PRODUCERS**: `consumption_complete`,
`unstated_extras`, `portion_multiplier`.

**3 — ⭐⭐⭐ AT LEAST TWO SUBJECTS ARE NOT MERELY ABSENT — THEY ARE REPRESENTED
AS OTHER SUBJECTS.** This is the finding. Before it, the uncertainty model was

```
known type  +  unclassified
```

and `unclassified` bounded the missing semantics. There is now a SECOND
uncertainty class:

```
known type that is SEMANTICALLY WRONG
```

**That destroys the lower-bound / ceiling envelope**, because `unclassified` is
no longer the only place missing semantics can hide. A contaminated bucket
looks exactly like a clean one.

**4 — T1 CANNOT ESTABLISH PREVALENCE OR POLICY SCOPE from the canonical type
field — locally OR in production.** Deploying the instrumentation would not fix
this; it would collect the same contaminated field at larger volume.

## ⛔⛔⛔ RETIRED IMPLICATION — READ THIS BEFORE TRUSTING A DURABLE ROW

> **`ask_type in DEFAULTABLE_CANDIDATES` does NOT currently imply the actual
> question subject is defaultable.**

A `menu_size` row may be a *"did you finish it?"* question. Anyone seeing
`menu_size` in a durable row and treating it as authorization to default would
be acting on a label the upstream representation got wrong.

## ⭐⭐⭐ WHY THE NEGATIVE INVARIANT DID NOT CATCH THIS

`test_consumption_complete_is_distinguishable_from_every_defaultable_class`
**passes**, and is correct:

```python
assert AT.classify("consumed") == AT.CONSUMPTION_COMPLETE
assert AT.classify("quantity", branded=...) != AT.CONSUMPTION_COMPLETE
```

Both true. **It never checked that a consumption question IN THE WORLD arrives
as `field="consumed"`.** It does not — the interpreter emits `quantity`. So the
mapping is right and the input never takes the value the guard protects.

Same shape as: the CF23 guard that was correct and INERT (true of rows nobody
could create) · `float('exact')` in a bare except, 0 of 836 memory rows ·
`_backfill_city` dead since P17f.5. **A guard whose protected input never
occurs is a guard nobody has.** See [[feedback-arnie-mutation-validity]] and
[[verify-the-instrument-before-its-silence]].

The mechanism is **compound under-typing**: case 2's ask contains a fries-size
question AND a consumption question, and only one ambiguity was recorded — so
the reported `compound 6/27` is itself an undercount.

## Status

| | |
|---|---|
| ask-type instrumentation | ✅ shipped, sound, NOT reopened |
| T1 | **UNSIZED** — no authoritative prevalence, local or production |
| `menu_size` 25.9–37.0 % | ⛔ **NON-AUTHORITATIVE**, retired as a sizing result |
| DEFAULTABLE_CANDIDATES | unchanged |
| interpreter prompt | unchanged (frozen) |
| `27983be` | still held; option 4 stands |

## Explicitly NOT done in this pass

No interpreter prompt change · no compound-question splitter · no special-case
`consumed` detector · no change to `DEFAULTABLE_CANDIDATES` · no reopening of
the ask-type tranche · **no repair of any kind.**
