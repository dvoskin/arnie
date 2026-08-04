# Food semantics: architecture map and migration plan

**Phase 1 deliverable.** Measured against the working tree on 2026-08-04, not
recalled. Every count below is reproducible with the scan in
`scripts/food_identity_inventory.py`.

The directive's success condition is *"a new variation of food language can be
absorbed without editing several regexes, matching functions, portion tables
and renderers."* This document establishes how far that is from true today, in
numbers, and what has to move to close it.

---

## 1. The finding

**There is no owner of food identity.** There are five string-keyed
vocabularies with disjoint coverage of the same concept, and every consumer
picks whichever one it happens to import.

| Vocabulary | Rows | Module | Answers |
|---|---:|---|---|
| `FOOD_CATEGORIES` | 111 | `skills/nutrition/portions.py` | which portion/density row |
| `PIECE_WEIGHTS_G` | 59 | `skills/nutrition/normalize.py` | what one of them weighs |
| `FORM_ALIASES` | 40 | `skills/nutrition/portions.py` | cooked / shredded / cubed |
| `VAGUE_MEASURES` | 23 | `core/food_pipeline.py` | which hedge word this is |
| `PORTION_ONTOLOGY` | 14 measures | `skills/nutrition/portions.py` | what a measure spans |
| `_DISH_CATEGORIES` | 10 | `skills/nutrition/portions.py` | dish beats ingredient |

They do not share an ID space, a normalisation, or a plural rule. The
consequences are directly observable:

```
potato                 category=default    piece_key=potato
burger                 category=default    piece_key=burger
chicken noodle soup    category=soup       piece_key=None
orange chicken         category=meat       piece_key=None
peanut butter          category=nut_butter piece_key=None
```

`burger` and `potato` are **unknown to `FOOD_CATEGORIES` and known to
`PIECE_WEIGHTS_G`**. That single disagreement is the whole 2026-08-04 defect:
a burger fell to `some.default` (30–200 g) while another table in the same
process knew it weighed 226 g. `orange chicken` resolving to `category=meat`
is the compound-collapse family the directive names, live today.

### Duplicate table, now nearly dead

| | Rows | Status |
|---|---:|---|
| `normalize.PIECE_WEIGHTS_G` | 59 | LIVE — prices |
| `core.portions._PIECE_GRAMS` | 34 | advisory only |

Measured: **0 rows exist only in the advisory table**, and the two disagree on
exactly **one** value — `bagel` 98 g vs 105 g. So `_PIECE_GRAMS` is fully
subsumed and its only distinct contribution is a conflicting number. It has a
deletion milestone below.

---

## 2. Competing sources of truth, by concern

Reference counts across `core/ handlers/ skills/ api/ db/` (192 modules).

| Concern | Refs | Modules | Where it concentrates |
|---|---:|---:|---|
| Pending state | 89 | 12 | `conversation.py` **55**, `pending_store.py` 6 |
| Portion / density | 71 | 8 | `normalize.py` 27, `portions.py` 18 |
| Commit result | 61 | 9 | `execution_result.py` 20, `conversation.py` 19 |
| Preparation wording | 51 | 15 | `food_turn.py` 13, `staged_codec.py` 10 |
| Deferred calls | 45 | 2 | `food_turn.py` 26, `conversation.py` 19 |
| Cards | 38 | 5 | `conversation.py` 29 |
| Alias tables | 36 | 7 | `portions.py` 14, `normalize.py` 11 |
| Identity matching | 34 | 3 | `food_turn.py` 22, `normalize.py` 10 |
| Pluralisation | 26 | **6** | `normalize.py` 9, `food_response.py` 8 |
| Question options | 18 | 4 | `food_turn.py` 13 |

### The three that matter most

**Identity has three implementations.** `food_turn._same_food` /
`_is_renaming_of` / `_name_tokens` (token subset + head-noun rule, owns
deferred reconciliation), `normalize._head_matches` / `_stems` (owns piece
lookup), `logging_intent` (2 refs). None can see the others' answers. This is
what the directive means by *"`_same_food` token-subset logic no longer owns
item reconciliation"*.

**Pluralisation has six.** Six modules independently decide what the singular
of a word is. Two `rstrip("s")` bugs were fixed *today*, in two different
modules, with the same root — `potatoes` → `potatoe`. Four more sites remain
(`food_response.py` ×8, `answer_parsers.py`, `food_pipeline.py`,
`tool_executor.py`), each currently masked by a downstream fallback rather
than correct. This is the clearest possible case for the directive's
*"adding a new plural must not require modifying matching algorithms."*

**Pending has three owners.** `conversation.payload_json` (the live one, 55
refs), `pending_store.py`, and `deferred_calls` — which is a *fourth* notion of
"food we are holding", threaded between `food_turn` (26) and `conversation`
(19) with no shared type.

---

## 3. What the recent fixes actually were

Named honestly, because the directive is a correction to how they were made.
Every one is a code patch where the target architecture wants registry data:

| Fix | What it patched | What it should have been |
|---|---|---|
| `_stems` set-intersection | a matching function | an alias row per plural |
| piece tier in `distribution_for` | a resolution ladder | `count_unit` on the entity |
| `_SERIAL_LIST_RE` | a regex over prose | `ClarificationField.options` |
| `_PREPARATION_OPTIONS` | a table keyed on category | `preparation_compatible` on the entity |
| `_is_renaming_of` head-noun | a matching function | stable item IDs |

They are correct and they hold; they are also five separate edits for what is
one missing abstraction. That is the pattern to stop.

---

## 4. Migration order

Sequenced so each phase is independently shippable and reversible, and so
nothing depends on a later phase to be safe.

### Phase 2 — registries (no behaviour change)
Introduce `FoodEntityDefinition`, `UnitDefinition`, `CountUnitDefinition`,
preparation IDs, dish hierarchy. **Populate by adapting the six existing
tables**, not by re-authoring them. Ship with the registry unused: it must
reproduce today's answers before anything reads it.

*Exit:* a parity test asserting registry lookups equal current table lookups
for every row in all six tables.

### Phase 3 — `CanonicalMeal` in shadow
Adapt interpreter output into `CanonicalMeal` beside the live path. Write
nothing. Log disagreements.

*Exit:* disagreement rate measured on replay; no writes changed.

### Phase 4 — stable IDs where identity is mutation-critical
In dependency order, because these are the paths where a false match currently
costs a row: deferred reconciliation (`_undeferred`/`_same_food`) → correction
binding → duplicate prevention → card identity.

*Exit:* `_same_food` no longer reachable from any write path.

### Phase 5 — clarification from typed fields
`ClarificationField` owns question **and** options. Delete
`QuickReplyEngine.swift` once every client consumes the structured contract.

*Exit:* zero chips derived from rendered prose.

### Phase 6 — one pending lifecycle
`PendingMeal` absorbs `payload_json`, `pending_store`, `staged_items`,
`deferred_calls`.

*Exit:* replay parity, then delete the other three.

### Phase 7 — deletions (milestones, not aspirations)

| Delete | Blocked on | Evidence it is safe |
|---|---|---|
| `core.portions._PIECE_GRAMS` | resolve `bagel` 98 vs 105 | 0 unique rows, 1 conflict |
| 4 remaining `rstrip("s")` sites | Phase 2 registry | each already masked by a fallback |
| `_same_food` / `_is_renaming_of` | Phase 4 | — |
| `_SERIAL_LIST_RE`, `_PREPARATION_OPTIONS` | Phase 5 | — |
| `_stems` | Phase 2 | becomes a registry-backed adapter |

---

## 5. What this plan does not accept

**The directive's corpus target is 1,000+ labelled messages.** There is no such
corpus. `tests/test_a_full_day_of_food.py` replays one day through the real
app, which is the right *shape* and roughly 1% of the required *size*. Every
metric the directive asks for (`false_entity_match_rate`,
`compound_collapse_rate`, `lost_food_rate`) is unmeasurable until it exists,
and Phase 3's shadow mode is worthless without it — a disagreement rate
against no ground truth is a number, not a result.

**So the corpus is Phase 2a, ahead of the registries**, and it should be built
from production turns rather than written by hand. Anything else measures
synthetic English.

**One risk to state plainly:** phases 2–4 add a second representation of every
food while the first is still live. That is the *"do not leave old and new
ownership active indefinitely"* failure mode the directive warns about, and
the mitigation is the exit criteria above being gates rather than notes.

---

## 6. Cross-domain expansion

The expansion directive asks whether the same anti-patterns exist outside
nutrition. Measured across the same 192 modules, split into domain modules and
the shared routing layer they all pass through.

### The anti-patterns are NOT evenly spread

| Domain | regex | substring gate | plural heuristic | prose parsing |
|---|---:|---:|---:|---:|
| food | 72 | 82 | 25 | 26 |
| workout | 0 | 4 | 1 | 14 |
| sleep | 0 | 0 | 0 | 1 |
| water / habits / memory / search / reminders | 0 | 0 | 0 | 0 |

This is a real result and it changes the plan. **Food is the only domain that
built its own language layer.** Everything else routes through LLM tool-calling
and never grew a regex gate, because it never had a deterministic
interpreter to gate. So the expansion is not "port the food fix to eight
domains" — seven of them have nothing to port.

The corollary is less comfortable: those domains have no deterministic
interpretation *at all*, so they cannot preserve uncertainty, cannot bind a
correction to a stable prior item, and cannot ask a typed clarification. They
are not clean; they are absent. Food is ahead of them and its problems are the
problems of having tried.

### What IS genuinely cross-domain

**Unit conversion, and it is worse than in food.** `2.20462` appears at **74
sites across 16 modules** with no shared units module anywhere:

```
api/app.py 15   tool_executor 10   api/native_data 7   api/exercise_edit 6
core/targets 5  context_builder  strength_prs  session_state  memory_moments …
```

Also `2.54` (3 sites), `28.3495` (11 sites / 4 modules), `29.5735` (3). Every
one is a literal at a call site. This is the directive's *"duplicated unit
conversion"* exactly, it spans weight, height, strength and nutrition, and it
is the single highest-leverage cross-domain fix because a `UnitDefinition`
registry is required by the food plan anyway — Phase 2 should own **all**
dimensions, not just food's.

**The shared routing layer** (107 modules the domain buckets do not claim)
carries 62 compiled regexes and 119 substring gates, concentrated in
`tool_executor` (30), `db/queries` (16), `conversation` (12), `coach_live` (11).
This is where channel divergence and English-only routing actually live, and it
is shared by every domain — so fixing it once fixes all of them.

*One correction to my own scan:* the "reference phrase" count (293) is
inflated. 56 of those are in `core/prompts/arnie.py`, which is prompt TEXT
rather than code, and prompt text handling "another one" is the correct place
for it. The real code-side figure is much smaller and I have not isolated it;
it should not be quoted as evidence until it is.

### Revised sequencing

1. **Phase 2 owns units for every dimension**, not food's alone. It is already
   required, it is the largest measured duplication in the codebase, and it is
   the one change that pays off in eight domains at once.
2. **The shared routing layer is audited before the domain layers**, because
   its regexes and substring gates are what every domain inherits.
3. **Do not build full domain ontologies for the seven quiet domains yet** —
   every exercise, every habit, every sleep concept, every search entity.
   Those are feature projects and should be sequenced on product need.

### Correction (Danny, review of the audit commit)

The line above originally read *"do not build canonical semantics for the seven
quiet domains yet"*, and that was too strong. It conflated two different
things:

- building **rich domain ontologies** for eight domains — correctly deferred;
- building the **shared semantic contracts** — which must happen now.

The audit's own findings are the argument against the version I wrote. It
established that those domains cannot preserve uncertainty, bind a correction
to a stable prior event, produce a typed clarification, distinguish
interpretation evidence, or behave consistently across languages. Those are
precisely the gaps the universal contracts close. Deferring them does not
protect the quiet domains; it guarantees food re-implements each concept in a
food-specific way and someone generalises it later — which is how food got
here.

**So: land the shared contracts now, with food as their first deep
implementation.**

```
SemanticTurn        CanonicalIntent     CanonicalQuantity   UnitRegistry
EventReference      ClarificationField  PendingOperation    CanonicalEvent
ExecutionResult     provenance / confidence / language / locale metadata
```

The quiet domains keep their LLM tool interpretation for now, but their outputs
adapt **into these same contracts** rather than growing parallel ones. The
binding rule: *food may not define a food-specific version of quantities,
references, clarifications, pending lifecycle or execution results, because
none of those concepts is food-specific.*

### The audit's other weakness: a count is not a risk

Every hit currently weighs the same. A regex that formats a display string and
a regex that decides whether to delete a row both count as one, and prioritising
by raw count therefore prioritises by verbosity rather than by consequence.

Before implementation, every regex, substring gate, prose parser and conversion
is classified by what it can actually break:

```
presentation-only   routing            interpretation      identity-resolution
reference-binding   quantity-conversion  mutation-targeting  commit-gating
search-promotion
```

A substring inside a prompt is not comparable to one deciding "same prior
workout" or "delete last weight". `scripts/food_identity_inventory.py
--consequence` produces this classification; priority follows mutation risk,
not volume.

**Measured result:**

| class | hits |
|---|---:|
| mutation-targeting | 8 |
| commit-gating | 6 |
| identity-resolution | 13 |
| reference-binding | 3 |
| quantity-conversion | 5 |
| search-promotion | 1 |
| unclassified residual | 158 |
| presentation-only | 3 |

**27 hits can break data; 158 cannot.** Prioritising by raw count would have
started almost anywhere; prioritising by consequence puts one function at the
top:

```
core/food_turn.py:2819 (_undeferred)  _fuzzy = [s for s in unclaimed
                                       if _is_renaming_of(key, s)]
```

Its own neighbouring comment reads *"DELETING a row the user reported"*. That
is the single highest-risk heuristic in the codebase, it is what acceptance
criterion 4 names, and it is where migration to stable IDs starts.

Second is `_item_is_stated` (commit-gating), whose `rstrip("s")` unit
comparison was probed on 2026-08-04 and found **not** to misfire today —
protected only by a downstream digit fallback. Behaving is not the same as
being correct, and a commit gate is not a place to rely on the difference.

*Two false-positive classes were removed from this count and are worth naming,
because both inflated it the way the `\b` bug deflated the conversion count:*
every boolean feature flag (`os.getenv("X").lower() in ("true","1")`) matched
the substring-gate pattern and was scoring as language handling; and the
catch-all bucket is labelled **unclassified-residual** rather than
"interpretation", because calling a `lambda: True` fallback a classification is
how 158 unexamined lines would have acquired a meaning they have not earned.

### Priority (revised)

1. duplicated units — **done**, `core/units.py`
2. mutation-critical shared routing
3. reference and correction binding
4. food identity and clarification
5. adapters so the quiet domains emit the same contracts
6. domain ontology expansion, on product need
