# Defensible default — evidence contract

**DRAFT FOR REVIEW. Nothing implemented. No schema field added. No model
judgment introduced.** *(2026-08-27)*

The prior tranche closed on a negative result: **clarification cannot be
decided from impact magnitude alone.** This document defines the variable that
replaced it, *before* anyone decides where the signal comes from — because the
obvious next move, a `has_conventional_default` boolean from the interpreter,
would make the fixtures pass while explaining nothing. That is the answer
smuggled in as an input.

## The question

> **Can Arnie log under a conventional, defensible assumption, or is the
> ambiguity too unconstrained to resolve without asking?**

Not *how large could the error be* — that was disproved. This asks whether
there is **something to log under**.

## What "defensible" has to mean

A default is defensible when all four hold. Each must be **something you can
point at**, not a judgement about the food.

### 1. A recognized archetype

The named thing denotes a **dish or product**, not a serving format.

```
burrito     a countable item with a conventional build      ✅
parfait     a composed dish with a conventional serving     ✅
platter     a VESSEL — says nothing about quantity          ⛔
```

⭐ **THIS IS THE CANDIDATE DISCRIMINATOR.** *"Platter"* is a container word:
it describes how food arrives, not what or how much. A rule that can tell a
dish from a vessel separates 18 from 11/23 without knowing anything about
Mediterranean food.

⚠ **HYPOTHESIS, NOT YET TESTED.** Needs the separability check below.

### 2. A conventional serving or composition

There is a **retrievable record** whose serving basis covers the named thing
*as a whole* — not its components separately.

```
11  a Chipotle burrito exists as a branded product with a serving
23  a yogurt parfait has a conventional composed serving
18  no record covers "Mediterranean chicken platter" as a unit
```

⛔ **COMPONENT COVERAGE IS NOT WHOLE COVERAGE.** All three enumerate their
components — rice, pita, hummus are each individually resolvable. What 18 lacks
is a basis for *how much of each arrives on a platter*, and that is the thing a
default must supply.

### 3. A bounded interpretation

The plausible range under the default is **closed**, not open. A burrito is
regular-or-large; a platter runs from a lunch portion to a shareable tray.

⚠ This is where magnitude re-enters — legitimately, as a **property of the
default**, never as the decision itself. Boundedness is about whether a range
exists; materiality asked how wide it was. That distinction is the whole
lesson of the previous tranche and must not be allowed to blur.

### 4. A statable assumption

The default can be **said back to the user in one clause** they could correct.

```
"logged as a regular burrito with standard scoops"     ✅
"logged as a typical Mediterranean platter"            ⛔ typical of what?
```

⭐ **THIS IS THE USER-FACING TEST AND THE CHEAPEST ONE.** If the assumption
cannot be stated without embarrassment, it was not defensible. It also
guarantees the user can repair it, which is what makes logging-under-assumption
honest rather than a silent guess.

## The typed fact policy would consume

Never a boolean. If a signal is added it carries its basis and provenance:

```text
default_basis = conventional_serving   a generic archetype's standard serving
              | explicit_context       the user stated it ("8 oz sirloin")
              | product_serving        a branded product record
              | none                   nothing covers the whole named thing
              + provenance   which record, which field
              + assumption   the clause that would be said to the user
```

⛔ **`none` MUST BE REACHABLE AND MUST MEAN ASK.** A vocabulary where every
input maps to some basis is a boolean wearing an enum's clothes.

## What is NOT evidence of a default

- **The model asserting one.** `has_conventional_default: true` is unreviewable
  and would be fitted to the fixtures.
- **A small reported span.** Disproved: 11 and 18 both reported 300 kcal and
  require opposite outcomes.
- **The components being enumerable.** All three fixtures enumerate them.
- **A plausible number existing.** Case 16's own reply bracketed the meal at
  ~1200 and still asked; plausibility is not authority.

## ⛔⛔⛔ THE SEPARABILITY TEST COMES BEFORE IMPLEMENTATION

Two tranches were spent implementing policies whose fixtures could not be
separated by the quantity the policy read. The check costs three model turns.

```
required:  11 burrito  -> a basis that is NOT `none`
           23 parfait  -> a basis that is NOT `none`
           18 platter  -> `none`
```

If a proposed definition cannot produce that split **on the evidence the system
already holds**, it is refused before a line is written — no thresholds, no
constants, no third attempt at fitting arithmetic to labels.

## Open questions for review

1. **Is "dish vs vessel" the real discriminator**, or does it merely happen to
   fit three fixtures? *Burrito bowl*, *combo plate*, *bento*, *sampler* are
   the cases that would test it.
2. **Where should the basis come from** — the artifact/evidence store the
   canonical lane already queries, deterministic food knowledge, the
   interpreter, or a combination? **Deliberately unanswered here.**
3. **Does `explicit_context` subsume part of materiality?** *"8 oz sirloin"*
   states its own basis; that may be why case 16 felt loggable.
4. **What happens when the basis exists but the user's phrasing contradicts
   it** — *"a huge burrito"*? Probably `explicit_context` overriding
   `product_serving`, but the precedence is undefined.

## Status

Definition drafted. **Not agreed, not tested, not implemented.** The next step
is review of the four criteria — particularly criterion 1, which carries the
discriminating weight and is the one most likely to be wrong.
