# TRANCHE — INDEPENDENT ASK SEMANTICS

**Opened 2026-08-30. DESIGN, not another prompt experiment.**

## The architectural requirement

> **Representation and permission-to-default must be INDEPENDENT STATE.**
>
> Representing an unresolved semantic subject must not alter whether that
> subject is defaultable.

## Why the old path is CLOSED, not "needs tuning"

```
census_v4  4049778  baseline               asks 30  extras 0
census_v5  ede35b9  exception (2 edits)    asks 25  extras 6
census_v6  ede35b9  NULL TWIN of v5        asks 24  extras 7    null Δ = 1
census_v7  cfe4d51  variant (ONE WORD)     asks 24  extras 7    Δ -6
```

The interpreter's field list sits on the **log-time resolution rule** — it
enumerates what the model may resolve by judgement and log. So adding a subject
to it **creates the semantic signal and reduces asking with the same sentence.**
One word cost 6 asks and drove c17's primary-item size question to zero.

**No smaller edit to that list can succeed.** The coupling is the mechanism.

## ⭐ THE DESIGN SPACE — and what evidence already bears on each

### Option 1 — a second field on the interpreter's ambiguity record

`ambiguities[].field` keeps its resolution meaning; a new `subject` carries the
ask semantics.

- **For:** minimal shape change; both stores end up with a subject.
- **Against:** still prompt-driven, and the model must now populate two
  correlated fields correctly. **Three separate times this session, naming a
  value in a schema did not make the model emit it** (`consumed`, the staged
  enum types, `multiplier`). A second field is a second chance to not be used.

### Option 2 — derive the ask subject in CODE

From the ambiguity plus item context, structurally, with no new model output.

- **For:** no prompt change, no new model behaviour to measure, cannot suppress
  asking.
- **Against:** **the signal may not exist.** `quantity` + `branded` already
  separates `menu_size` from `continuous_portion`, but nothing structural
  distinguishes an extras question from a prep question — that distinction lives
  only in `points[].qs`, which is PROSE and forbidden as an input.

### Option 3 — ⭐ make the STAGED pipeline the ask authority

**It already has exactly the separation this tranche wants.**
`ClarificationQuestion.requested_fields` is ask-specific and carries **no
resolution permission**. It already produced `consumed_fraction`, and it
already raises roughly half of all asks.

- **For:** the required architecture EXISTS and is measured. No new vocabulary,
  no prompt edit, no new way for the model to decline to ask.
- **Against:** a routing change is a large behavioural change and would need its
  own null pair. Round 1 already showed asks migrating between the two
  authorities changes what the user sees.
- ⚠ **Unmeasured:** whether the staged pipeline CAN raise the asks the
  interpreter currently raises. Its 9 `AmbiguityType`s are richer than the
  interpreter's 5 fields, but richness of vocabulary has repeatedly failed to
  predict emission.

### Option 4 — an ask-only enum in the prompt's ASK example

Separate list, attached to the ask contract only.

- **Against:** this is closest to the change already rejected. The full
  exception did attach a vocabulary to the ask branch and suppressed asking
  anyway. **Weakest option; do not start here.**

## Recommended first step — CHEAP, no prompt change

**Establish whether Option 3 is even viable before designing anything.**

For each ask the INTERPRETER currently raises, ask: *could the staged pipeline
have raised it?* That is answerable from data already on disk — the censuses
record both authorities per turn — and it decides whether the existing
separation can carry the load or whether a new representation is unavoidable.

**Zero model turns.** If the staged pipeline never raises the shapes the
interpreter does, Option 3 dies and the choice narrows to 1 vs 2.

## EXIT TEST (frozen, unchanged)

```
1. real `unstated_extras` emissions
2. clarification rate AND material asks INSIDE that variant's OWN same-SHA null
```

Both required. If they do not both pass, **the problem is deeper than
vocabulary and work stops again.**

## Standing constraints

- No DEFAULTABILITY or D2 work until this passes.
- `portion_multiplier` still has **no proven producer** on either path.
- `27983be` remains held. Nothing is deployed.

---

# ⛔⛔⛔ OPTION 3 COVERAGE RESULT — **0 of 28**

`code=407ed03`, 50 turns, 0 errors, 30 asks, 20 interpreter-raised.
Raw: `data/corpus/census_v8_coverage_2026-08-30.jsonl`.

```
interpreter subject     asks   staged-equiv   no staged equiv
continuous_portion        11        0              11
preparation_fat            9        0               9
menu_size                  5        0               5
identity_variant           3        0               3
TOTAL                     28        0              28

WHY:  28/28  "no staged decision at all"
```

## The reason is NEITHER candidate

Not *"ambiguity present, declined to ask"* (routing) and not *"ambiguity never
existed"* (representation gap). **The staged pipeline never executed.**

```
5960  if action == "ask" and not prior:     <- interpreter ask branch
6113  return {"action": "ask", ...}         <- RETURNS HERE
6203  return {"action": "ask", ...}
6329  _decision = plan_turn(...)            <- staged pipeline, AFTER
```

> **The two authorities are SEQUENTIAL, not parallel.** The interpreter's ask
> branch returns before `plan_turn` is ever called. The staged pipeline only
> runs on turns where the interpreter did NOT propose an ask.

`staged_state` was captured on **31 of 50 turns** — and on **none** of the
interpreter-raised asks.

## What this does to Option 3

**It is not a routing change.** There is no staged alternative sitting alongside
an interpreter ask to route to, because staged never computed one. Option 3
would require **REORDERING the pipeline** — running `plan_turn` before or
independently of the interpreter's ask branch — which is a far larger change
than "own the ask", and round 1 already showed that migrating asks between
authorities changes what the user sees.

## ⭐ AND IT STILL WOULD NOT SOLVE THE BLOCKING PROBLEM

Staged field names observed **anywhere** in this census:

```
quantity 17 · variant 8 · product_line 6 · prep 4 · consumed_fraction 3
```

Richer than the interpreter's — `variant` and `product_line` are staged-only.
**But `component_breakdown` never fires**, so **`unstated_extras` has NO
observed staged producer either.**

By the frozen interpretation, third branch:

> *If the DEFAULTABILITY-critical subjects — especially `unstated_extras` —
> have no staged representation, Option 3 does not solve the blocking problem,
> however much else it covers.*

**It covers nothing here, and it would not cover the critical subject even if
reordered.**

## Option 3: CLOSED

The design space narrows to **Option 1** (a second interpreter field, weakened
by three failures of schema-naming to produce emission) and **Option 2** (derive
in code, weakened by the signal possibly not existing outside prose).

⚠ **Neither is attractive, and that is the honest state.** No option is
currently known to work.
