# DESIGN PASS — INDEPENDENT ASK SEMANTICS

**Design only. No implementation. 2026-08-30.**

## The question, in one line

> **How does Arnie say "I know the missing thing is toppings" without that
> statement ALSO meaning "I'm allowed to guess the toppings"?**

## ⭐⭐⭐ THE ENTANGLEMENT, PRECISELY LOCATED

`ambiguities[]` serves **TWO ROLES WITH ONE STRUCTURE**:

```
on a LOG turn   "here is what I ASSUMED"        <- resolved by judgement (PERMISSION)
on an ASK turn  "here is what is OPEN"          <- unresolved subject (OBSERVATION)
```

Same array. Same field vocabulary. And the prompt sentence that introduces the
vocabulary is phrased in the RESOLUTION voice:

> *"Every unknown you resolved by judgement is reported as `ambiguities`…
> (fields: quantity, identity, brand, prep, consumed)"*

**That is why adding one word changed asking behaviour.** Vocabulary membership
IS resolution permission, because the sentence granting the vocabulary is a
sentence about resolving.

## The contract the next design must create

```
observed unresolved subject        ≠        permission to resolve/default it
```

## Candidate shapes — NONE VALIDATED

### Shape A — a second array

`ambiguities[]` unchanged; add `open_subjects[]`, purely descriptive.

- **For:** the two roles get two structures; unambiguous.
- **Against:** a new array is still a prompt addition, and every prompt addition
  this session moved behaviour. Two arrays also invite the model to populate
  one and not the other — a correlation it has failed to maintain three times.

### Shape B — a permission flag per entry

`ambiguities[{item, field, resolved: true|false}]`.

- **For:** SMALLEST change. The vocabulary describes the SUBJECT; a boolean
  carries the PERMISSION. Adding a subject value would no longer grant
  permission, because permission stops living in vocabulary membership.
- **Against:** still one array doing two jobs, now distinguished by a field the
  model must set correctly. If it defaults `resolved:true`, the coupling
  returns silently.

### Shape C — ⭐ the model REPORTS, the code DECIDES

The prompt stops saying *"unknowns you resolved by judgement"* and says
*"unresolved subjects, with your best estimate"*. **Permission to default
becomes purely code-side.**

- **For:** **this is where the policy ALREADY LIVES.**
  `skills/nutrition/materiality.py` and `_proposed_ask_is_material` are already
  the deciders of whether an unknown is worth interrupting for. The prompt is
  currently granting a permission the code also grants — two authorities for one
  decision, which is the four-tables condition in another costume.
- **For:** representation could then be extended freely, because naming a
  subject would carry no permission at all.
- **Against:** the largest prompt reframe of the three, and the food prompt has
  a standing freeze. It changes what the model is asked to DO, not just its
  vocabulary — so the behavioural risk is the highest of the three even though
  the architecture is the cleanest.

## ⭐ THE NORTH-STAR TEST (frozen)

> **Adding the ability to represent a subject must NOT change whether Arnie
> asks the user about it.**

Concretely, for any candidate:

```
1. add a NEW subject to the representation
2. rerun the census
3. require: the new subject is emitted
4. require: clarification rate AND material asks stay inside that variant's
   OWN same-SHA null
```

Both required. `c17` (primary-item size) and `c1` are the named canaries — the
two asks the rejected changes suppressed most cleanly.

## What this design pass does NOT settle

- **Which shape is right.** A, B and C are candidates; the evidence so far only
  rules out editing the existing list in place.
- **Whether ANY prompt-side shape can pass the north-star test.** Every prompt
  change measured so far moved asking behaviour. That is not proof it must, but
  it is four for four.
- **`portion_multiplier`**, which has no producer under any shape and is not
  addressed by this seam at all.

## Explicitly NOT to be done

```
✗ further tweaks to the existing interpreter field list
✗ reopening Option 3 (the authorities are sequential; staged never runs)
✗ inferring portion_multiplier from enum existence
✗ deploying 27983be
✗ starting DEFAULTABILITY anyway
✗ a second model call to route around the architecture, unless the simpler
  shapes are exhausted
```
