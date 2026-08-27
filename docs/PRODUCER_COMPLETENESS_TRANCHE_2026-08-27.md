# TRANCHE — UPSTREAM AMBIGUITY REPRESENTATION / PRODUCER COMPLETENESS

**Opened 2026-08-27 on `T1_LOCAL_SCREENING_INSTRUMENT_INVALID_2026-08-27.md`.**

⛔ **NOT "defaultability". NOT "menu size". NOT "clarification policy."** Those
framings all presuppose a type field that can carry the distinction they act
on. It cannot yet.

## The lesson that named this tranche

> **A typed field is only authoritative if its PRODUCER can actually express
> the distinctions the policy depends on.**

The storage and vocabulary layer is solved: one canonical vocabulary, canonical
writes, legacy-forward reads, explicit missingness, semantic judgment separated
from rendering. Then the producer was measured and it **collapses multiple
semantic subjects into `quantity`**. The canonical type is **structurally sound
but semantically underfed.**

## Acceptance question

> Can the interpreter/code path produce **distinct structured subjects** for
> consumption, menu size, continuous portion, extras and multiplier cases
> **without reading rendered prose?**

## What counts as proof — and what does not

⛔ **NOT "the mapper returns the right enum."** That is exactly what passed
while a consumption question wore the `menu_size` label. The proof is **real
producer reachability**:

1. **One live/real-path fixture per semantic subject** — observed emission, not
   a constructed call to `classify()`.
2. **Compound asks produce MULTIPLE structured ambiguities** when multiple
   subjects are present. Case 2 asks a size question and a consumption question
   in one turn and records ONE ambiguity; that under-typing is the defect.
3. **Negative cases proving subjects do NOT collapse into one another** — a
   consumption question must not be representable as a quantity one.
4. **A reachability test that FAILS if a protected type has zero producers.**
   The direct answer to the day's recurring failure class.

## Current producer evidence (`data/ask_type_producers.json`)

| type | status | turns |
|---|---|---:|
| `menu_size` | proven ⚠ **contaminated** | 7 |
| `continuous_portion` | proven ⚠ **contaminated** | 11 |
| `preparation_fat` | proven | 10 |
| `identity_variant` | proven | 2 |
| `consumption_complete` | ⛔ **unproven** | 0 |
| `unstated_extras` | ⛔ **unproven** | 0 |
| `portion_multiplier` | ⛔ **unproven** | 0 |

**Proven ≠ clean.** `menu_size` has a real producer AND a documented case of a
consumption question wearing its label.

## Board

```
ask-type storage architecture   DONE
T1 sizing                       INVALIDATED
deployment pressure             REDUCED — shipping collects the same
                                contaminated field at higher volume
DEFAULTABILITY                  open conceptually, NOT measurable
next real blocker               PRODUCER SEMANTICS  <- this tranche
```

## ⛔⛔⛔ STANDING ENGINEERING RULE (enforced)

> **Never treat "guard passes" as evidence unless the protected state is proven
> reachable.**

Every failure this session had that shape:

```
CF23            trust was TRUE OF ROWS NOBODY COULD CREATE — correct and inert
memory rung     float('exact') in a bare except: 0 of 836 rows, gates green
_backfill_city  dead since P17f.5 behind `except: pass`
ask_type        classify("consumed") maps correctly and NOTHING EMITS
                field="consumed" — so a consumption question arrived labelled
                menu_size, a DEFAULTABLE type, while the negative-invariant
                test passed AND WAS CORRECT
```

Enforced by `tests/test_protected_types_have_proven_producers.py` against
`data/ask_type_producers.json`. It does **not** demand every type be reachable —
three are not, and that is the measured truth, recorded rather than hidden.
It forbids **treating an unproven type as authority**: no policy may consume a
type whose producer has never been observed.

⭐ **Mutation-verified 4 RED / 0 GREEN, and the fourth needed a fix.** M4
(silently adding `consumption_complete` to `DEFAULTABLE_CANDIDATES`) first came
back **GREEN**: the guard refused it because it was UNPROVEN, so the
unprovenness *shielded* the mutation — **two guards in series with the outer
answering for both**, the P3 shape again. The membership is now asserted
directly so the test stands on its own.
