# Materiality / over-clarification — CLOSED

**Reachability fix SHIPPED (`c7d3ca8`). Policy hypothesis REJECTED.**
*(Danny, 2026-08-27)*

## ⭐⭐⭐ THE FINDING

> **Clarification cannot be decided from impact magnitude alone. The missing
> variable is whether the system has a defensible default for the unresolved
> attribute.**

Three fixture pairs were tested and **none separated on the quantity the policy
reads.** That is not a threshold nobody found — it is arithmetically
unavailable.

## The proof, in three attempts

### 1 — meal-level AND (implemented, measured, reverted)

```
case 16 (anchor)   0/2 -> 0/2   still asks
case 22 (counter)  1/2 -> 0/2   LOST the ability to ask at all
```

⛔ The AND inverted the intent. `is_material` already takes an item denominator
so the fraction rule catches a span that DOMINATES a small item — an 80-cal
swing on a 210-cal egg is most of the egg. Requiring the meal view as well
suppressed exactly that: 80 against a ~760 meal fails the meal fraction. It
made asking about SMALL components harder and big ones no harder.

### 2 — case 16 DOMINATES case 22 on every magnitude axis

```
              span   of item   of meal   frozen label
case 16 potato  200     .417      .167    LOG
case 22 eggs     80     .381      .105    ASK
```

⛔⛔ **No monotone function of (span, item, meal) yields LOG for 16 and ASK for
22**, because 22 is smaller on every axis. AND vs OR does not solve it.
Different constants do not solve it. Another threshold does not solve it.

That produced the first ontology correction: **materiality was combining two
different semantic questions.** *Does the amount of a declared thing matter?*
is not *does an undeclared component exist?* Cases 16 and 22 moved to
OILS/component-completeness; both frozen terminal labels unchanged.

### 3 — case 11 vs case 18, and this one is decisive

```
case 11  expect LOG   kind='portion'  impact_cal=300   item_cal=None
case 23  expect LOG   kind='portion'  impact_cal=250   item_cal=None
case 18  expect ASK   kind='portion'  impact_cal=300   item_cal=None
```

⛔⛔⛔ **11 AND 18 REPORT AN IDENTICAL CONSEQUENCE AND DEMAND OPPOSITE
OUTCOMES.** Same kind, same 300-cal span, same shape. And `item_cal` came back
`None` on every one, so the fraction branch is not merely insufficient on this
path — **it is unavailable.**

## What the questions say that the numbers do not

- **11** *"Regular-size burrito with standard scoops, or loaded up?"* — a
  Chipotle burrito has a **conventional default**.
- **23** *"How big's the parfait, drizzle or a real spoonful?"* — a parfait has
  a conventional serving.
- **18** *"How much rice (roughly a cup?) and whole pita or half?"* — a
  *Mediterranean chicken platter* has **no defensible default** across the
  category; it is a restaurant-dependent construct.

The decision was never *how much could the answer move*. It is **whether there
is something defensible to log under.**

## What SHIPPED, and it is real

Reachability. **2 of 25 clarifications ever reached the materiality rule**; the
other 23 came through the `note_food_clarification` TOOL, whose handler
recorded any ask and replied *"just ask the question naturally"* — no span, no
mode, no decision. Both paths now cross the same `_proposed_ask_is_material`,
before the write, with `impact_cal` required so there is something to weigh,
and a demotion that instructs a LOG rather than silence. Four structural tests
pin it, including that a gate firing after the record is not a gate.

⚠ Reachability alone moved no fixture: 11 and 23 now REACH the decision and it
KEEPS their asks. **Routing was necessary and insufficient** — which is itself
the evidence that the policy, not the plumbing, was wrong.

## Registered as a NEGATIVE RESULT

The magnitude-policy experiment is not a failure to be retried with better
constants. It is a **disproof**, and it is recorded as one: *a monotone
threshold on reported consequence cannot decide clarification.* Three
independent fixture pairs, two ontology corrections, zero thresholds tuned.

⛔ **DO NOT ADD THRESHOLDS. DO NOT CHANGE LABELS.**

## The next tranche — DEFAULTABILITY / DEFENSIBLE DEFAULT

Its question is **not** *how large could the error be?* It is:

> **Is there a sufficiently conventional interpretation that Arnie can log
> without interrupting the user, while stating the assumption?**

Fixtures, all frozen labels unchanged:

```
11 burrito   -> LOG   a regular/default burrito interpretation exists
23 parfait   -> LOG   a conventional serving interpretation exists
18 platter   -> ASK   "platter" composition and portions are
                      restaurant-dependent; no defensible default
16, 22       -> OILS  prep / unstated added fat, not this tranche
```

### ⛔⛔⛔ DEFINE THE CONCEPT BEFORE CHOOSING A SIGNAL

The tempting move is to add `has_conventional_default` to the interpreter and
let the model decide. **Refused** *(Danny, 2026-08-27)*: that prematurely makes
the model the authority for a policy concept nobody has defined, and risks
**replacing one opaque signal (`impact_cal`) with another opaque boolean that
conveniently makes the fixtures pass.** This project has caught that class
repeatedly — a plausible-looking signal that is really the answer smuggled in
as an input.

So "defensible default" is defined FIRST, independently. It likely needs some
combination of:

```
recognized food archetype
  + conventional serving / composition
  + bounded default interpretation
  + an explicit assumption that can be STATED to the user
```

⭐ Only after that is defined does the question of WHERE the signal comes from
get decided — deterministic food knowledge, evidence metadata, the interpreter,
or some combination. And if a signal is added it must be **evidence-bearing**,
never a bare boolean:

```
default_basis = conventional_serving | explicit_context | product_serving | none
                + provenance / reason
```

so policy consumes a **typed fact**, not *"the model thinks this is
defaultable."*

⛔ **LABELS 11 AND 23 ARE NOT REVISITED.** Three failed separation attempts are
evidence that the abstraction is wrong, not that the labels should be rewritten
until the abstraction works.

## Roadmap position

```
materiality / reachability   CLOSED at c7d3ca8
defaultability               NEXT
OILS                         separate; owns 16 and 22
CF24                         passive — instrumentation live, does not block
CF27                         registered; Rule-0 only
```

⭐ **THE CORPUS SHRANK THE POLICY BOUNDARY INSTEAD OF LETTING IMPLEMENTATION
PRESSURE BROADEN IT.** Two ontology corrections, zero thresholds tuned. More
threshold work here would be fitting arithmetic to labels it mathematically
cannot represent.
