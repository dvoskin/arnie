# Phase B–F directive: complete clarification migration, finish conversational food, then extend the canonical backend to workouts

> **Augmented directive — plan-of-record.** Received 2026-08-05, augmented
> 2026-08-06 from team review (slice loop and deletion, presentation
> boundary, B-1a–e closing sequence, release gates). Supersedes no prior
> directive, composes with all of them. Detail documents:
> [CLARIFICATION_MIGRATION.md](CLARIFICATION_MIGRATION.md) (Phase B design
> decisions), [CHIP_GENERATION_MIGRATION.md](CHIP_GENERATION_MIGRATION.md)
> (option pipeline + status ledger),
> [QUICK_LOG_PROMOTION_RECORD.md](QUICK_LOG_PROMOTION_RECORD.md) (Phase A
> evidence), [WORKOUT_CONTRACTS.md](WORKOUT_CONTRACTS.md) (Phase E/F shapes),
> [DELETION_INVENTORY.md](DELETION_INVENTORY.md) (cleanup scoreboard),
> [ARCHITECTURE_CONTRACT.md](ARCHITECTURE_CONTRACT.md) §1b (executable
> invariants C1–C9). Enforcement lives in
> `tests/test_the_canonical_invariants.py`; this document is the sequencing
> authority.

## End goal

Arnie's backend should converge on one production architecture:

```text
human input
→ domain interpretation
→ canonical unresolved/resolved domain state
→ semantic clarification fields
→ typed answer patches
→ one PendingOperation
→ one canonical commit
→ one persisted result
→ presentation from committed truth
→ durable downstream work
```

The target is not merely "better clarification." The target is:

* no direct food writes outside the canonical writer,
* no client-derived chip meaning,
* no question-text parsing to recover semantics,
* no broad interpreter treating clarification answers as new meals,
* no competing pending stores,
* no partial meal topology created by accuracy mode,
* no narration before authoritative commit,
* no duplicated card/totals logic,
* and no clarification adapter with permanent tenure.

Food is the reference implementation. Workouts adopt the shared operation
spine only after food proves it.

## The slice loop — and what "done" means

**Augmented 2026-08-06 from team review.** A slice is not finished when its
lifecycle works. It is finished when its predecessor is gone.

```text
measure → freeze → build canonical path → gate → validate
→ promote → DELETE PREDECESSOR → LOWER RATCHET
```

The last two steps are the ones that get skipped, and skipping them is how the
four legacy clarification producers happened the first time: each was a
canonical path that shipped without removing what it replaced.

**Promote and delete per family, continuously.** Do not build every remaining
slice and postpone promotion to the end — that recreates a second large
migration branch whose assumptions go untested for months. Each field family
promotes and deletes its own predecessor independently.

**The goal is a repeatable loop, not heroics.** The first slice was expensive
because it had to invent the operation model, ownership rules, revision
semantics, answer routing, replay protection, commit coordination, failure
handling, provenance, presentation facts, lifecycle tests, production probes,
telemetry and ratchets. Later slices reuse nearly all of it. The measure of
success is when a slice takes **days to implement rather than weeks to
invent**.

## Presentation rides behind each slice — it is never the next phase

Voice, formatting and diction are a **controlled presentation layer**, not a
milestone. They sit strictly after the persisted-result boundary:

```text
interpretation → canonical state → typed clarification → PendingOperation
→ canonical commit → persisted result → PRESENTATION FROM COMMITTED TRUTH
```

**There are two distinct wording passes and they must not be confused.**

| | when | what it is | constraints |
|---|---|---|---|
| **Instrumentation wording** | inside every slice | make the question unambiguous and the routes visible so the slice is MEASURABLE | fixed · minimal · versioned · same QuestionIntent, options and patches · no dynamic LLM diction |
| **Product voice** | **B-2.8** | make it genuinely Arnie | adaptive · contextual · channel-aware · still facts-constrained |

Instrumentation wording is measurement hygiene: the phrasing directly affects
the metric being evaluated, so it must be settled *before* evidence
collection, and version-stamped so a later change stays comparable. It is not
permission to start the voice project.

**Why product voice waits for B-2.8.** The renderer needs stable semantic
intents to express — a question, an assumption, an uncertainty, a disclosure,
a repair, a confirmation. Those intents are not stable until B-1.6 fixes
dependency ordering and B-1.7 fixes accuracy policy. Diction written before
then gets rewritten. At B-2.8 the renderer owns sentence structure, tone,
contractions, channel length, splitting, emphasis and the deterministic
fallback — and never owns which field is unresolved, which options are valid,
what an option means, whether an assumption occurred, or whether the meal
committed.

**Output consolidation belongs to C-4, not to any slice.** `MealCommitResult →
CanonicalResponseFacts → copy` is the first safe boundary and is deliberately
narrow. One `PresentationSnapshot` feeding chat, card, day totals, timeline,
coach feed, notifications, widgets and API payloads is C-4's authority.
Polishing chat prose while cards and totals still have separate factual owners
is how screens come to disagree.

**The rule for the team:** every slice ships a presentation adapter; no slice
runs a broad voice redesign.

## Measure before generalize

**No clarification generator, candidate source, interaction pattern or UX
refinement expands until production telemetry demonstrates where users actually
succeed or fail.**

Adopted 2026-08-06, at the point B-1 stopped being an architecture question and
became a product one.

**Multiple defects in this slice shipped green because fixtures encoded
expected states without exercising naturally occurring production sequences**
— the ask origin, the ambiguity field name, the settled and expiry windows.
**Others exposed different gaps**: contradictory ownership of the quantity
(the stale macros), a renderer substituting its own question, observability
that could not report what it appeared to measure, and database parity between
models and migrations that nothing compared. **Both classes require
sequence-level production evidence before expansion**, which is what this rule
buys. Generalising an option generator without it would repeat the failure at
a layer where the cost is a user's trust rather than a test run.

Its first application is the **B-1 internal evidence window (B-1b)**: B-1's
option pipeline does not widen, and the structured client (B-1d) does not
begin, until the window says which candidate source actually produces answers
people accept and do not correct. It is deliberately labelled inside B-1 — it
is not Phase D work, and naming it `D4.1` implied Phase D was starting before
B-1 closed.

The rule binds the instruments too. An observation window read from
`core/trace_buffer` would be a window over "since the last deploy" — it is a
`deque(maxlen=2000)` in process memory, shared across every watched event, and
production measured **zero lines** minutes after a deploy with its dropped
counter reset alongside. Telemetry that decides a roadmap lives in a table.

## Standing constraints

These remain in force throughout the migration.

### Ownership

One owner per responsibility:

```text
resolver               → produces evidence
ambiguity engine       → identifies unresolved semantic fields
policy                 → decides ask / assume / defer / disclose
option generator       → produces valid semantic answer candidates
renderer               → produces human-facing wording and labels
answer application     → applies typed patches
domain writer          → mutates storage
presentation builder   → renders committed truth
```

No layer may silently re-own another layer's responsibility.

### Migration discipline

Every migration slice follows:

```text
measure → freeze → build canonical path → shadow or gate → validate
→ promote → delete predecessor → lower ratchet
```

Do not leave old production ownership available "just in case."

### Transaction rules

* One reported meal normally produces one operation and one commit.
* No user-facing success before commit.
* Duplicate delivery returns the persisted original result.
* Pending revisions are durable.
* Durable downstream work uses the transactional outbox.
* Best-effort cache or UI work remains post-commit.
* Accuracy mode changes policy, never storage topology.

## Current position

Already complete:

```text
Phase A
✓ quick-log canonical writer
✓ direct quick-log writer deleted
✓ production verification complete
✓ typed nutrition provenance
✓ canonical commit/replay path
✓ durable outbox split
✓ clarification producers frozen by C8 (and option producers by C9)
✓ B-0b semantic contract surface implemented and test-locked
✓ B-0c persistence, round-trip, validation and immutability hardened
```

The next work begins at B-1.

Status wording is deliberately split. "Implemented and test-locked" is a claim
about construction; "storage-proven" is a claim about the boundary B-1
actually crosses, and the two were conflated once already — the contracts
passed 105 in-memory tests while no patch could be serialized at all.

## Phase B — Canonical clarification for conversational food

### B-0 — Freeze legacy growth

Status: complete, but maintain continuously.

Enforce:

* four legacy clarification producers plus one relay cannot increase,
* option-producer locations cannot increase,
* no new loose `questions` payload shape,
* no new `ClarificationQuestion` constructor outside the frozen inventory,
* no new client prose-to-chip parser,
* no new pending representation,
* no new direct conversational food writer.

Add or retain ratchets for:

```text
question producers          (C8)
option producers            (C9)
legacy food writers         (C4)
pending-state writers
client prose chip derivation
```

Any new feature must use the canonical contracts or remain out of scope.

### B-0b — Lock semantic contracts

Status: implemented as prerequisites; production proof still pending.

Canonical contracts: `ClarificationAttribute`, `ResponseType`,
`ClarificationStatus`, `CandidateSource`, `UnresolvedField`, `CandidateValue`,
`SemanticPatch`, `ClarificationOption`, `ClarificationGroup`,
`ClarificationInteraction`, `QuestionIntent`, `EntityCapabilities`.

Required properties:

**Stable field identity** — `field_id = operation_id + event_id + attribute +
semantic revision`. Never derive identity from list index, option label,
question wording, screen position, or display name.

**Typed option meaning** — every selectable option carries a typed patch.
`label` = presentation, `option_id` = wire identity, `patch` = semantic
meaning.

**Versioned serialization** — every persisted canonical clarification payload
carries schema version, domain, operation ID, revision, event IDs, field IDs,
patch type IDs. No unversioned arbitrary dict becomes the permanent pending
payload.

**`patch=None` is permitted exclusively on inventoried legacy measurement
paths** — today the two construction sites in
`skills/nutrition/clarification_adapter.py`, which set `adapter_built=True`.
Every canonical option created for B-1 must carry a non-null patch. `source`
alone could not express this: it is independently optional, so no predicate
could distinguish an adapter-built option from a canonical producer that
forgot its patch, and C10 was a comment with nothing to key on.

### B-0c — Contract hardening and persistence proof

Status: complete (`core/semantics.py`, `tests/test_contract_persistence_b0c.py`).

Purpose: prove the B-0b types cross process and storage boundaries without
losing type identity, provenance, immutability, or domain meaning. B-1 stores
options and later receives only an `option_id`, so the backend must reload the
exact typed patch from persisted state. Without typed serialization the
canonical flow degrades to

```text
SetQuantity → JSON dict → loaded as dict → reconstructed heuristically
```

which is the architecture being removed, relocated server-side.

**Patch serialization.** Every patch serializes with an explicit
discriminator and schema version:

```json
{
  "patch_type": "set_quantity",
  "schema_version": 1,
  "event_id": "food_1",
  "field_id": "op_1:food_1:quantity:0",
  "provenance": "user_selected",
  "quantity": {"amount": "5", "unit_id": "oz", "dimension": "mass",
               "grams": "141.7"}
}
```

Loading returns the concrete type (`SetQuantity → JSON → SetQuantity`, never
`→ dict`) through a closed registry that fails shut on an unknown
`patch_type` or a newer `schema_version`. Round-trip equality is asserted for
every patch family. **Decimals cross as strings, not JSON numbers** — through
a float, `Decimal("0.1")` does not come back equal to itself, and exact
portion arithmetic is the reason quantities are `Decimal` at all.

**Enum coercion is symmetric.** Strings are coerced and invalid ones refused
at every construction boundary; after construction every internal value is an
enum instance. The asymmetry that existed — field attribute required an enum
while patch provenance and option source kept raw strings — silently
reclassified a user's own figure as an estimate, because
`Provenance.is_users_own` is an identity check and a `str` fails it without
raising.

**Group validation.** `ClarificationGroup` enforces a non-empty event id, at
least one field, every field targeting the same event, and no duplicate field
ids — which, since `field_id` embeds attribute and revision, is also the
no-duplicate-attribute check.

**Interaction validation.** `ClarificationInteraction` enforces operation and
revision alignment across every group and field, unique field ids across
groups, one group per event, and no option referencing a foreign field. A
selectable field with no options is refused at construction: it must declare
`FREE_TEXT_FALLBACK` rather than ship blank for a client to "repair" (C15).

**Immutability.** Mutable payloads are deep-copied at contract construction. A
frozen dataclass holding the caller's dict is not immutable — the producer
could keep editing it, injecting values past validation. The outbox's
`version` key is reserved so a payload cannot shadow the schema version.

**Workout seam completeness.** `SelectEntity` (renamed from
`SelectFoodEntity`) is the domain-neutral entity-selection patch that answers
`EXERCISE_IDENTITY`; `CandidateSource.DEVICE` exists for HealthKit/Whoop
candidates; `UncertaintyEvidence.impact_spread` is a `CanonicalQuantity`
rather than a calorie number. Renaming was free while zero producers existed;
after B-1 stores patches, `patch_type` is wire data and a rename is a
migration. Load-basis semantics (per-dumbbell vs total) remain owed and are
tracked in `docs/WORKOUT_CONTRACTS.md`.

**Persistence proof.** The test that matters is not an in-memory contract
test. It performs the real sequence, against a file database with real
per-session connections:

```text
create interaction with a SetQuantity option
  → serialize into the PendingOperation payload
  → commit → close the session → open a NEW session
  → load the operation → bind option_id
  → obtain a typed SetQuantity → apply
```

### B-1 — One item, one mass-quantity field

This is the first authoritative production slice.

**Eligibility predicate** — B-1 applies only when ALL are true: exactly one
food event; food identity sufficiently resolved; only material unresolved
attribute is consumed quantity; quantity expressible in one supported
dimension; first implementation uses mass; no product identity ambiguity; no
preparation dependency; no multi-item meal; no mixed food/workout turn; no
correction or destructive action; no requirement for multiple clarification
rounds.

Example — eligible: *"I had some chicken breast."* → entity = chicken breast,
quantity = unresolved, dimension = mass.

Not eligible (remain on legacy paths until their own slice is promoted):
"chicken and rice" · "a Core Power" · "two pieces of chicken" · "fried chicken
with sauce" · "half a rotisserie chicken" · "change yesterday's chicken".

**B-1 flow**

```text
message → resolved food identity → one UnresolvedField(quantity)
→ candidate generation → deterministic option selection
→ canonical ClarificationInteraction → persist PendingOperation
→ send grouped ID-addressed payload → receive chip or typed answer
→ produce SetQuantity patch → validate and apply patch
→ revise ResolvedMeal → canonical commit → PresentationSnapshot
→ narration/card/totals
```

**Candidate evidence for B-1** — use ONLY: (1) high-confidence user history
for the same canonical entity, (2) validated entity portion evidence,
(3) deterministic domain fallback candidates, (4) free text. Exclude
initially: web search, LLM-proposed candidates, complex cross-unit ranking,
product catalog variants, conditional preparation logic.

**Quantity option selection** — maximize useful coverage, not generic portion
tiers: `probability × information gain × nutritional materiality × evidence
confidence × user familiarity ÷ interaction cost`. Rules: one field only; at
most three primary numeric options plus "Other"; avoid near-duplicates;
respect preferred display units; preserve semantic quantities internally;
never parse rendered labels later.

**Wire contract** — server sends:

```json
{
  "operation_id": "op_123",
  "revision": 0,
  "interaction_id": "int_123",
  "groups": [
    {
      "event_id": "food_1",
      "label": "Chicken breast",
      "fields": [
        {
          "field_id": "op_123:food_1:quantity:0",
          "attribute": "quantity",
          "response_type": "single_select_or_text",
          "options": [
            {"option_id": "opt_3oz", "label": "3 oz"},
            {"option_id": "opt_5oz", "label": "5 oz"},
            {"option_id": "opt_8oz", "label": "8 oz"}
          ]
        }
      ]
    }
  ]
}
```

The stored server-side option contains the patch. The client submits
`operation_id · revision · interaction_id · field_id · option_id · delivery
key`. It never submits the label as meaning.

**Answer paths** — chip: `option_id → load stored SetQuantity patch →
validate field/revision/event → apply`. Typed ("Around six ounces"): `narrow
quantity parser → SetQuantity(6 oz, USER_STATED) → validate → apply`. Both
converge before pending-state mutation.

**Revision rule** — revision changes only when persisted semantic state
changes: r0 pending meal with open field → r1 patch applied, meal ready → r1
canonical commit. Sending, retrying, or re-rendering the same interaction does
not increment revision.

**B-1 answer idempotency** — chip-answer identity: operation_id, revision,
field_id, option_id, client delivery key. Typed-answer identity: operation_id,
revision, source turn ID, client delivery key. A replay after commit returns
the stored result. A duplicate before commit does not create another revision.

**B-1 presentation** — the final response is produced from committed result
data (committed item, meal totals, day totals, assumptions, provenance,
correction actions). The model may phrase this data. It may not recalculate or
invent it.

**B-1 production definition of done**

Server: canonical quantity producer is sole authority for eligible turns; one
PendingOperation persists the interaction; options carry typed patches; chip
and typed answers converge; stale and foreign answers fail closed; duplicate
answers are idempotent; commit uses the canonical coordinator; result is
persisted; no legacy writer is reached.

Client: canonical payload disables prose-derived chips; chips render directly
from fields/options; taps submit IDs; free text remains available; stale
interactions are handled; final card uses committed result.

Production corpus: chip answer · typed offered quantity · typed non-offered
quantity · duplicate tap · stale revision · invalid option · wrong field ·
answer after commit · repair flow · card/totals agreement · zero duplicate
meals.

Promotion: observe canonical B-1 writes → compare behavior → promote
eligibility path → delete legacy B-1 option/question path → lower
producer/option ratchets.

**B-1 option pipeline scope.** B-1 builds a *minimal, quantity-specific*
candidate generation → selection → patch → render path. It does NOT build the
generalized cross-field `ClarificationOptionGenerator` (milestone 9). The
distinction is load-bearing in both directions: overbuilding the general
framework during B-1 is how a vertical slice becomes a horizontal layer, and
deferring *semantic option integrity* to milestone 9 would ship B-1 chips that
are still labels. B-1's options are canonical — typed patches, recorded
source, no prose derivation — over exactly one attribute.

**B-1 deletion boundary.** Deletion happens at B-1 promotion, not at B-4.
Scoped to the exact B-1 eligibility predicate, delete or disable:

* the legacy quantity question producer,
* the legacy quantity option builder,
* answer-turn quantity reconstruction,
* client prose chip derivation for canonical quantity interactions.

Leaving these alive "until the cleanup phase" is how B-4 becomes an
unreviewable mass, and it is also how two owners of the same question coexist
in production — the condition that produced the four producers.

**B-1 product measurement.** Correctness is not success. Instrument, per
interaction: clarification shown · chip selected · free text used · repair
required · clarification abandoned · time to answer · rounds before commit ·
estimate requested · meal committed · correction within 10 minutes.

Key indicators: clarification completion rate · median clarification latency ·
repair rate · duplicate-meal rate · immediate-correction rate · share of
options sourced from history versus fallback · share of users choosing
"Other". **A technically correct option system that frequently forces "Other"
has failed**, and only the last two indicators can detect it.

### B-1.5 — One item, multiple independent material fields

After B-1 is green in production, add preparation classification. Do not use a
generic `cook_type`; model nutrition-relevant fields (breading, fried status,
skin presence, cut, added sauce, added fat). First expansion uses one compact
preparation category: `plain / breaded / fried / unknown`.

```text
Chicken breast
Amount        [3 oz] [5 oz] [8 oz]
Preparation   [Plain] [Breaded] [Fried] [Not sure]
```

Proves: multiple fields on one event; one grouped interaction; partial answer
state; independent typed patches (`SetQuantity`, `SetPreparationCategory`);
operation remains pending until policy says ready. Rules: both fields already
eligible; each option belongs to exactly one field; mixed chip rows forbidden;
a partial answer updates only answered fields; unanswered fields remain open;
one meal still commits once.

**B-1 language scope — English-only, ENFORCED, not assumed.**

`parse_command` decides whether to cancel a meal, skip an item or assume a
portion, and its patterns are English. Run against another language it is not
neutral: it is a matcher that does not know the ground moved. This repo has
shipped that defect — EN-only rescue detectors let Russian meals go unlogged
(2026-08-03); the routing gate was fixed and the DETECTORS were not.

The command layer is therefore a three-tier design, and B-1 builds only Tier 1:

```text
user text
  → Tier 1  locale-specific deterministic lexicon   (B-1: English only)
  → Tier 2  pending-aware constrained classifier    (B-1.8)
  → Tier 3  repair, never a guess
```

The OUTPUT is language-neutral (`ClarificationCommand`); the PATTERNS are not.
So, in force from B-1:

* `parse_command(text, locale=...)` returns `NONE` unless the locale is
  English. No phrase gets a "language-neutral" exemption — none can be proven
  one, and the cost of being wrong is a destroyed meal.
* `UNKNOWN_LOCALE` is not English. "We could not tell" must never authorise a
  destructive command.
* The locale is **persisted on the operation** (`operation_id · revision ·
  locale`), so an answer is interpreted under the same language context as the
  question rather than re-detected from a two-word reply.
* Resolution order: stored preference → the operation's established locale →
  script detection, last.
* Numeric/unit answers (`150 g`, `6 oz`) still work in any locale — excluding
  a locale from the COMMAND lexicon must not exclude it from answering.
  Language-specific number words (`seis onzas`, `шесть унций`) belong to the
  narrow quantity parser, not here.
* Destructive and non-destructive commands do not share a threshold:
  `CANCEL` very high · `SKIP_ITEM` high · `USE_ESTIMATE` moderate · `NONE`
  safe default. A mistaken estimate is repairable and disclosed; a mistaken
  cancellation discards the meal.

**Owed, per language, before that language may run Tier 1:** a locale lexicon,
field-parser fixtures, a classifier corpus, adversarial destructive-command
tests, and production measurement. Tracked in `DELETION_INVENTORY.md`.

**B-1 progress ledger** — kept current, because "the tests are green" and "the
slice is done" are different claims and were conflated once already.

| area | state |
|---|---|
| eligibility predicate, one owner, evaluated once | DONE |
| pre-ownership rollout gate (halt / allowlist / cohort) | DONE |
| candidates: user history + calibrated ontology only | DONE |
| deterministic selection, ≤3 + Other, no near-duplicates by grams OR label | DONE |
| typed `ClarificationInteraction`, persisted with patches | DONE |
| `PendingOperation` created before the question is sent | DONE |
| answer ownership: chip · exact label · typed · command | DONE |
| terminal ownership (C10): no mid-flight fallback, gate unreachable by AST | DONE |
| settlement: one canonical commit, replay on re-delivery | DONE |
| locale pinned at the ask, English-only Tier 1 | DONE |
| repair / cancel / internal-failure copy from committed truth | DONE (facts + deterministic fallbacks) |
| card + totals from the SAME facts — disagreement unconstructable | DONE |
| instrumentation: all 11 signals, one owner; abandonment + correction on a timer | DONE |
| live operation probe, correlated to a self-minted operation id | WRITTEN — evidence owed on deploy |
| **Arnie voice over the committed facts** | TODO — after lifecycle/committed-truth verification, BEFORE broad rollout |
| **Telegram/iMessage label-text path proven in production** | TODO |
| **iOS B-1d: ID-addressed payload + real chip-path proof** | TODO |
| **reply-metadata binding for `LABEL_TEXT` channels** | TODO — owed with B-1d |
| **rollout: allowlist → 1% → 5% → 25% → 100% of eligible turns** | TODO |
| **deletion: legacy quantity producer, option builder, answer reconstruction, prose-chip path; lower C8/C9** | TODO |

**B-1 presentation boundary.** B-1 completes the canonical response FACTS and
their deterministic fallbacks. Production-quality Arnie voice may be refined
after end-to-end lifecycle and committed-truth verification, and must land
before broad rollout — not after it.

The ordering is the whole point:

```text
commit  →  committed facts  →  deterministic copy  →  (later) voice
```

**Voice is post-commit, and may never reinterpret, recompute, or override a
committed fact.** It phrases what the row says; it does not decide what the
row says. The failure this forbids is measured and specific: a reply reading
"logged, 970/98g" while nothing had been written (2026-08-03), and a card whose
totals disagreed with the prose beside it because three owners each computed
their own. A renderer that can recompute is a second owner of the number.

**The renderer is never passed `MealCommitResult`.** Nor persistence models,
resolver evidence, or any mutable domain state. It receives the immutable
`CanonicalResponseFacts` that `facts_for()` produced, and nothing else — an
earlier draft of this section said voice would render "the same
`MealCommitResult` fields", which reopens the exact ownership problem the
seam exists to close. A renderer holding the commit result can recompute, and
a renderer that can recompute is a second owner of the number.

```text
MealCommitResult
  → facts_for()
    → CanonicalResponseFacts   (immutable)
       ├── deterministic fallback
       └── constrained voice renderer
```

This is structural and absolute. A voice pass that fails degrades to the
deterministic sentence — never to silence, and never to an invented one.

**THREE VOICE PASSES, EXPLICITLY, because "when does voice happen" currently
has three defensible answers and a team will pick different ones.**

| pass | when | scope |
|---|---|---|
| **B-1 presentation harmonization** | before **public** rollout of B-1 | remove the obvious lane-to-lane discontinuity — B-1 turns render from a template while legacy turns are composed, so the assistant sounds different depending on routing the user cannot see. Fixed/versioned templates or tightly constrained rendering. **Not** the adaptive voice project. |
| **B-2.8 product voice system** | after semantic intents and dependencies stabilize (B-1.6, B-1.7) | adaptive, contextual, channel-aware rendering. Inputs are `CanonicalResponseFacts` and `QuestionIntent` **only**. This is the first implementation of the real voice boundary. |
| **Gate 3 voice polish** | release candidate | final diction, consistency, evaluation and release tuning. **Not** the first implementation of the boundary — that already exists by then. |

Separate again from all three: **instrumentation wording inside each slice**
(B-1a and its successors), which exists to make a slice measurable and is
fixed, minimal and version-stamped.

**The `LABEL_TEXT` correlation limit, stated rather than discovered later.**
`"6 oz"` carries no identity. Once operation A has settled, a delayed reply
naming an option that also exists on operation B is indistinguishable from a
reply to B — `owning()` returns the most recent operation and binds there.

This is a TRANSPORT limitation, not an architecture flaw: with no metadata on
the reply there is nothing to correlate against. It is bounded, not solved, by
`SETTLED_OWNERSHIP_MINUTES` and by iOS being excluded until taps are
ID-addressed. **Owed with B-1d:** where a platform does expose reply metadata
(Telegram's `reply_to_message`), bind it to `operation_id` and prefer it over
inference. Until then `LABEL_TEXT` is a restricted capability and is named as
one in code — its production evidence does not substitute for the chip path's.

Two scope facts to state rather than let green tests imply otherwise:

* **The chip path has no production channel yet.** `answer_from_chip` is
  implemented and tested, but nothing in production submits an `option_id` —
  Telegram and iMessage return the label text, which binds to the stored patch
  through the label-selection path. The structured tap's PRODUCTION proof is
  owed at B-1d and must be recorded as owed, not as landed.
* **Pricing is stubbed in the lifecycle suites.** They monkeypatch
  `_analyze_food` deliberately, to measure the lifecycle rather than the
  enrichment ladder. "One commit, one row, correct provenance" is proven;
  "the number is right for 6 oz of chicken" is `analyze()`'s contract, tested
  where that lives. The live probe is what first exercises real pricing
  through this path.

**B-1.5 deletion boundary:** delete the matching legacy preparation ownership
at promotion — the preparation question producer, its option builder
(`_PREPARATION_OPTIONS`), and answer-turn preparation reconstruction.

### B-1.6 — Conditional clarification dependencies

Add semantic dependencies, beginning with added fat:

```text
quantity
preparation category
added_fat_present
    └── added_fat_amount, active only when present = true
```

Not hardcoded conversation code — field activation predicates
(`added_fat_amount active when added_fat_present == true`). After every patch
the dependency engine: (1) recomputes active unresolved fields, (2) closes
fields made irrelevant, (3) activates newly eligible dependent fields,
(4) reruns materiality policy, (5) asks, assumes, or commits.

Revision sequence: r0 quantity+preparation open → r1 quantity=5oz,
preparation=plain, added_fat_present activates → r2 present=yes, amount
activates → r3 amount=1 tbsp, ready → r3 canonical commit.

**B-1.6 deletion boundary:** delete hardcoded added-fat follow-up branching
for eligible turns, if present. The dependency engine replaces it; leaving the
branch as a fallback means two owners decide when to ask.

### B-1.7 — Accuracy-mode policy over one topology

Quick: ask quantity; assume plain; assume no added fat; disclose assumptions.
Moderate: ask quantity; ask preparation; ask added fat only when material.
Strict: ask quantity; ask preparation; ask skin/breading when relevant; ask
added-fat presence; ask amount when present.

All modes use one PendingOperation, one revision model, one answer system, one
commit path. Mode assumptions produce typed patches or typed assumptions with
`MODE_DEFAULT` provenance — never masquerading as user statements.

### B-1.75 — Repricing after a quantity patch *(observed in production, deferred)*

**Not a nutrition-accuracy item, and not fixable by improving the resolver.**
`core/b1_quantity_operation.py` builds the pricing input as
`inp = {**item, "quantity": quantity_text}` — the answered quantity layered on
top of the ask-time `amount`, `unit`, and macros. `_analyze_food`
(`handlers/tool_executor.py:2896`) reads `calories/protein/carbs/fats` straight
out of that dict as the authoritative figures, so it receives two contradictory
statements of the same fact and picks one.

**⚠ The production evidence first cited here was wrong, and is corrected below.**
The defect is asserted from the CODE, not from these three operations. Read the
correction before designing tests against them.

| entry | item at ask | answer actually sent | committed | verdict |
|---|---|---|---|---|
| 2849 rice | 100 **g** → 161/4/34/1 | *(typed grams)* | 39.6 g → 64/1.4/13.4/0.5 | scaled correctly (×0.396) |
| 2851 chicken | 6 **oz** → 280/52/0/7 | "Half a breast grilled with a little spray oil" | 87 g → 96/20/**4**/0 | **confounded** — the answer changed the food's description (spray oil legitimately re-prices fat 7→0). 4 g carbs on a chicken breast still looks wrong, but cannot be attributed to this mechanism. |
| 2852 oatmeal | 1 **cup cooked** → 150/5/27/3 | "Half a cup Made with milk nothing else in it" | 45 g → 150/5/27/3 | **not a defect.** ½ cup dry ≈ 45 g, and 1 cup cooked oatmeal *is made from* ½ cup dry — same quantity of food, so identical macros are correct. |

The original reading ("gram-based items survive, every other basis does not")
came from inferring the answers from what was *suggested* rather than reading
`conversation_logs.raw_message`. It does not survive contact with the actual
messages.

**What the defect rests on instead — a fact about the code.** `_analyze_food`
reads the macros out of `inp`, and `analyze()` documents its own conflict
policy: *"The LLM's calories/protein anchor the portion unless the quantity is
an explicit mass and the winner is trustworthy."* B-1 hands it macros belonging
to the ask-time quantity together with the answered quantity, so which of the
two governs is decided by that policy rather than by the user's answer. The
answered quantity must be the only quantity authority; today it is one of two
inputs competing for the role.

**Therefore the acceptance criteria are BEHAVIOURAL, not reproductions.**
Writing "the oatmeal regression" as a test would encode a misreading. Prove
instead that committed nutrition responds to the answered quantity across
gram, ounce, cup, piece and free-text bases — and let whichever of those is
already correct stay green.

**The fix is a deletion, not a guard:** the item handed to pricing must have its
quantity fields *replaced*, not shadowed, so pricing derives from `food_name` +
answered grams exactly once. Adding scaling arithmetic here would violate the
standing no-heuristics rule and would leave the contradictory input in place.

**Sequencing (Danny, 2026-08-06):** downstream nutrition refinement owns this;
it does not gate B-1. Recorded here so it is not rediscovered. It *does* gate
B-1 **promotion**, because promotion asserts the answered quantity produces the
committed numbers — so this must close before the legacy quantity path is
deleted, whichever phase closes it.

Regression test owed with the fix: ask-time basis in a non-gram unit, answer in
grams, assert the committed macros scale from the stated basis.

### B-1.8 — Harden answer classification and repair

Includes **Tier 2 of the command layer**: a pending-aware constrained
multilingual classifier that receives the user text, the known locale, the
active clarification field and the allowed command enum — and may return only
a `ClarificationCommand` or `NONE`. It has no authority to interpret a new
meal. "No tengo idea" resolves to `USE_ESTIMATE`; it can never resolve to a
food entry. Below the confidence threshold the answer falls to the field
parser and then to repair, phrased in the user's own language.

Fallback order:

```text
1. exact option-ID binding
2. narrow field parser
3. pending-aware constrained classifier
4. targeted repair
5. explicit cancel or skip
6. fresh-turn interpretation only with clear new consumption
```

Constrained commands: CANCEL · SKIP_ITEM · USE_ESTIMATE · COMMIT_READY ·
RESTART · KEEP_AS_READ · NONE. The classifier receives the open operation,
active fields, recent interaction, and user text — not an unconstrained
fresh-meal task.

**Hard routing rule** — while a clarification is open: an ambiguous reply is
presumed to address the open operation unless it clearly introduces a distinct
new consumption event. ("5 ounces" → answer; "probably grilled" → answer;
"skip it" → command; "I also had a protein shake" → potential new food event,
handled explicitly; "yeah" → field-specific interpretation or repair, never a
fresh meal.)

## B-2 — Multi-item meals and grouped interactions

Only after single-item dependent flows are production-proven.

*"I had chicken and rice."* →

```text
Meal
├── chicken: quantity open · preparation open · added fat conditional
└── rice:    quantity open
```

Capabilities: multiple events; grouped fields per event; partial answers;
multi-turn completion; independent field activation; neighbor protection; one
operation revision; one eventual meal commit.

**Neighbor protection** — a clear item must not be re-questioned because an
adjacent item is ambiguous. "5 oz chicken and some rice" → chicken quantity
stays resolved; only rice is open.

**Partial answers** — "5 oz for the chicken" applies only the matching field
patch; rice stays open. Do NOT create one committed chicken meal and a second
rice meal.

**Bundling** — bundle fields only when all are currently active, independently
answerable, the interaction remains compact, and field ownership stays clear.
Never flatten all options into one row.

**Explicit recovery partial commit** — allowed only through explicit recovery
("log the chicken and skip the rice", expiry policy, abandonment, clearly
separable consumption events, explicit "log the rest"), recorded as a
deliberate operation outcome — not normal moderate-mode behavior.

### B-2.5 — Product identity, package size, consumed fraction

*"I had a Fairlife shake."* Fields: product identity, package size, consumed
fraction. Candidate sources in order: user product history, exact catalog
candidates, package metadata, validated resolver candidates, constrained model
proposal last. Options carry stable identifiers (`SelectEntity`,
`SelectProductVariant`, `SetPackageSize`, `SetConsumedFraction`); the label is
never parsed.

### B-2.6 — Material preparation, sauces, composite additions

Typed fields as needed: breading, skin, added fat, sauce type, sauce amount,
sweetener, milk type, toppings. Ask by materiality (`expected nutrient
variance × uncertainty × confidence improvement ÷ user effort`): grilled vs
baked may not deserve a question; plain vs fried often does; oil presence may
matter; herb seasoning does not; garnish color does not.

### B-2.7 — Semantic chip candidate pipeline

One `ClarificationOptionGenerator` (entity, field, resolver candidates, user
history, locale, accuracy mode, channel capabilities) → canonical candidates.
Evidence hierarchies per field family as in
[CHIP_GENERATION_MIGRATION.md](CHIP_GENERATION_MIGRATION.md). Selection by
probability, information gain, materiality, source confidence, semantic
diversity, user familiarity, interaction cost. A separate renderer owns
locale, unit preference, shortening, accessibility, channel constraints — no
semantic choice during rendering. The client decides layout only; it does not
derive semantics or generate missing options.

### B-2.8 — QuestionIntent and voice boundary

Policy emits `QuestionIntent` (interaction type, subjects, resolved context,
unresolved fields, assumptions, urgency/materiality, desired compactness); the
renderer produces wording under constraints, with deterministic fallback
templates mandatory. Wording failure must never block the semantic
interaction.

## B-3 — Consolidate pending state

`PendingOperation` becomes the sole durable owner: operation ID, revision,
domain, payload schema version, domain payload, active fields, inactive
dependent fields, resolved patches, assumptions, answer history, interaction
history, expiry, attempt count, terminal status, commit claim, answer claim.

Delete ownership from `deferred_calls`, `staged_items`, `pending_questions`,
loose conversation payloads, reconstructed wire questions, parallel pending
blobs. Compatibility readers may exist temporarily; no new writes target them.

### B-3.5 — Promote canonical clarification across all food cases

Field families one at a time (quantity → preparation → added fat → product
identity → package size → fraction → serving basis → multi-item → partial
answer → commands → repair), each through: eligibility predicate → canonical
producer authoritative → shadow/measure → production corpus → promote →
delete legacy family path → lower ratchet. Do not wait for all families before
deleting migrated legacy ownership.

## B-4 — Delete the old clarification architecture

Delete: the clarification adapter; loose dict question producers; duplicate
`ClarificationQuestion` constructors; question-text attribute inference;
position/text-based field IDs; response-schema reconstruction; client
`QuickReplyEngine` prose parsing; server option reconstruction; legacy
pending-question ownership; broad interpreter fallback for open clarification;
default moderate partial commits.

Ratchets: C8 producers → 0 · legacy relays → 0 · prose chip parsers → 0 ·
unstable field-ID builders → 0 · legacy pending writers → 0.

**Phase B is not complete until deletion is merged and production-stable.**

## Phase C — Finish conversational food on the canonical spine

* **C-1** Migrate the two remaining `tool_executor` writers to
  `ResolvedMeal → commit_or_load_existing → canonical writer`; C4 → 0.
* **C-2** Canonical corrections (edit quantity, replace identity, change
  preparation, remove item, add missed item, change meal type, correct
  logging day) — each a new operation revision → immutable ledger event →
  canonical write → persisted result. No row patches without ledger history.
* **C-3** Canonical undo — targets stable committed event IDs, never
  "last row" heuristics.
* **C-4** `PresentationSnapshot` authority — one post-commit snapshot feeds
  chat narration, meal card, day timeline, coach feed refresh, notifications,
  API response. Delete duplicated calculation/formatting paths.
* **C-5** Search/resolver consolidation — one coordinator over user history,
  catalog, USDA, OFF, web evidence, model estimate; every winning value
  records source, candidate ID, confidence, serving basis, identity
  provenance, nutrition provenance, evidence IDs. The resolver reports
  uncertainty; it does not decide whether to ask.
* **C-6** One ambiguity engine — resolver evidence → one food ambiguity
  engine → canonical unresolved fields → policy.
* **C-7** Food production-readiness gate before workouts: all food writers
  canonical; clarification canonical; corrections canonical; undo canonical;
  no prose-derived chips; one pending owner; presentation from committed
  truth; duplicate replay stable; PG concurrency tested; observability
  complete; fallback rates within target; no unbounded clarification loops;
  no legacy writer escape.

## Phase D — Generalize the proven operation envelope

Only after food has two real operation types or workouts begin using the
spine. **D-1** shared `OperationRequest` (domain payload stays strongly
typed — `ResolvedMeal | ResolvedWorkout | ResolvedWeight`, never generic JSON
blobs). **D-2** shared `OperationResult` (moves render actions, outbox
events, assumptions, warnings, committed event IDs out of `MealCommitResult`;
domain results stay inside the envelope). **D-3** shared typed outbox
contracts (event ID, kind enum, version, payload, dedup key, operation ID,
user ID) for memory update, coaching analysis, trend recomputation,
notification planning, timeline refresh, PR detection.

### The destination this is walking toward (recorded 2026-08-05)

B-1 turned out to be less "food clarification" than "a transaction system that
happens to be clarifying food": explicit ownership, canonical operations,
optimistic revisions, replay instead of duplicate execution, deterministic
presentation, boundaries that are structural rather than conventional, and
observability designed in rather than bolted on.

So the long-term target is **one conversational execution framework that
health domains plug into**, not parallel systems per domain. The concepts that
should end up domain-agnostic:

```text
PendingOperation           an operation with unresolved fields
ClarificationInteraction   what we are asking, ID-addressed
SemanticPatch              a typed answer
AnswerOutcome              applied / repair / cancelled / refused
CanonicalResponseFacts     committed truth, extracted once
Renderer                   phrases facts; never recomputes them
```

The backend should eventually think *"I have a pending operation with
unresolved fields"* and not *"I have a pending food quantity."* Food becomes
one implementation; workouts a second; medication, hydration, weight and
supplements are then additions rather than rewrites.

**This does NOT belong in B-1 or B-2, and pulling it forward would be the
mistake this whole migration exists to avoid.** The rule of two still governs:
extract only what two real domains have demonstrated needing. B-0b already
followed it (`ClarificationAttribute` carries workout members; the spine is
proven domain-neutral by a fake-domain test) and B-1 deliberately did not
(`quantity_clarification` is food-specific, because a generalized option
generator built before one vertical slice works is how the four legacy
producers happened).

What makes this a destination rather than a wish is that each phase already
lowers the distance: every ratchet that falls, every legacy owner deleted, and
every food-named-but-generic shape in `WORKOUT_CONTRACTS.md`'s owed-renames
register is one fewer thing standing between here and it.

## Phase E — Structured workout logging

**E-1** contracts (`ResolvedWorkout`/`ResolvedExercise`/`ResolvedSet`/
`WorkoutCommitResult`/`WorkoutPresentationSnapshot`). **E-2** storage
(`workout_sessions`, `workout_exercises`, `workout_sets`,
`exercise_resolution_evidence`; shared ledger for create/correct/undo/
replace). **E-3** structured quick workout path through the shared
coordinator, proving atomicity, duplicate replay, crash safety, PG
concurrency, correction/undo, outbox behavior. **E-4** one workout entity
registry (canonical exercise IDs, aliases, equipment variants, movement
pattern, laterality, load semantics, measurement capabilities) — no ad hoc
exercise-name strings as identity.

## Phase F — Conversational workout logging and cross-domain turns

**F-1** interpretation ("Bench 3x8 at 135, then incline dumbbells 3x10 with
50s" → `ResolvedWorkoutDraft`). **F-2** clarification reuses the EXACT shared
architecture — workout patches (`SetSetCount`,
`SetRepCount`, `SetExternalLoad`, `SetLoadBasis`, `SetDuration`,
`SetDistance`, `SetEquipment`; exercise identity is answered by the shared
`SelectEntity`, not a byte-identical `SelectExerciseEntity`), dependencies
(load amount → load basis:
per-dumbbell / total / machine stack / assisted), options from program
prescription, same-session history, recent history, equipment increments,
device data. No separate workout chip system. **F-3** presentation post-
commit; coaching downstream, never owning logging semantics. **F-4** mixed-
domain turns ("chicken and rice, then bench 3x8") → one Turn, independent
food and workout operations, each with its own resolution/pending/revision/
commit/result; no giant cross-domain transaction by default; the response may
aggregate both after each reaches a valid state.

## Final deletion and completion criteria

**Mutation** — zero direct food writers outside the canonical domain writer;
zero direct workout writers; duplicate replay always loads the persisted
result; all committed mutations have ledger events; corrections and undo use
canonical operations.

**Clarification** — zero legacy producers; zero adapter-owned production
semantics; zero prose-derived chips; zero label-to-meaning parsing; one
`PendingOperation` owner; typed patches for chip and text answers;
dependency-driven follow-ups; accuracy modes share one topology.

**Presentation** — narration, cards, totals from committed results; the model
cannot mutate facts; no duplicated total calculation paths; assumptions and
provenance preserved.

**Operations** — durable work uses the outbox; best-effort work is explicitly
noncritical; release tooling compiles operational scripts; promotion records
are measured; health reports active owners; ratchets prevent legacy ownership
from returning.

**Domain expansion** — food fully canonical and production-proven; structured
workout logging on the shared spine; conversational workout clarification
reuses typed fields and patches; domain payloads stay specific.

## Recommended milestone order

```text
 1. B-1 one-item quantity
 2. promote and delete legacy B-1 path
 3. B-1.5 quantity + preparation
 4. B-1.6 added-fat dependency
 5. B-1.7 mode policy
 6. B-1.8 answer repair/fallback
 7. B-2 multi-item and partial answers
 8. product/fraction/package fields
 9. generalized ClarificationOptionGenerator across all migrated field
    families — NOT "semantic options arrive here". B-1 already ships a
    minimal, quantity-specific option pipeline; this milestone generalizes it
10. one PendingOperation owner
11. delete adapters and legacy clarification producers
12. migrate remaining conversational food writers
13. canonical corrections and undo
14. PresentationSnapshot authority
15. C4 reaches zero
16. food production-readiness gate
17. shared OperationResult envelope
18. structured workout logging
19. workout corrections/undo
20. conversational workout interpretation
21. workout clarification using the same patch system
22. mixed-domain turn coordination
```

**The key sequencing rule:** expand one semantic capability only after the
previous capability is authoritative end to end, production-measured, and its
legacy owner has been deleted. That gets Arnie to the desired backend without
recreating the same fragmentation under better type names.

## Status board

Kept current. This is the single answer to "where are we"; the phase sections
above are the detail. **Everything open lives here** — a finding recorded only
in a session, a commit message or a side document is a finding that gets lost,
which is how this board came to read "B-1 NEXT" while B-1 was production-proven.

Last reconciled 2026-08-06 against the task list, `docs/B1_PRODUCTION_LOG_0805.md`
and the commit history.

```text
Phase A    COMPLETE          production-verified on a66e9ba8
B-0        COMPLETE          ratchets enforced continuously (C8, C9)
B-0b       COMPLETE          contract surface
B-0c       COMPLETE          serialization, validation, immutability, persistence
B-1        SLICE NOT CLOSED  see the seven-line state below — "backend
                             complete" alone is the sentence that lets a
                             slice look finished while its predecessor
                             still runs
B-1.75     COMPLETE          answered quantity is the only quantity authority
B-1b       IN PROGRESS       internal evidence window — the current phase
B-1d       BLOCKED ON EVIDENCE  structured iOS client
B-1.5/.6/.7/.8              resume after promotion
B-2+       expansion
B-3/B-4    ownership consolidation and deletion
C/D/E/F    canonical food, shared contracts, workouts
```

### B-1 state — the authoritative seven lines

```text
B-1 lifecycle implementation       COMPLETE
B-1 production lifecycle proof     COMPLETE
B-1 product evidence               IN PROGRESS
B-1 structured client              BLOCKED ON EVIDENCE
B-1 promotion                      BLOCKED
B-1 predecessor deletion           NOT STARTED
B-1 slice closure                  NOT COMPLETE
```

Quote these lines rather than a single adjective. "B-1 is done" is true of the
first two and false of the last five, and the whole point of the slice loop is
that the last five are where migrations are actually won or lost.

### Closing B-1 — the first promotion and deletion cycle

B-1's lifecycle is production-proven. The **slice** is not closed until its
predecessor is deleted and its ratchets are lowered.

| | step | state |
|---|---|---|
| **B-1a** | Measurement calibration — instrumentation wording, versioned | ✅ `b1_quantity_q2` |
| **B-1b** | Internal evidence window | **current** |
| **B-1c** | Close the safety-observability gap (detector silence) | runs in parallel; blocks *public rollout*, not internal collection |
| **B-1d** | Structured iOS client against the validated contract | after the B-1b window |
| **B-1e** | Promote → delete the legacy quantity path → lower ratchets | after B-1d |

**B-1a — allowed scope, now closed.** Make the question unambiguous · make the
free-text and "not sure" routes visible · version-stamp the wording · preserve
the QuestionIntent, options and patches · no dynamic LLM diction. Found and
fixed: `ClarificationCommand.ESTIMATE` was fully implemented and advertised
nowhere, so "not sure" usage would have measured zero.

**B-1b — what the window must answer.** Candidate source availability · option
selected · free-text amount · "Other" usage · "not sure" usage · repair rate ·
latency · abandonment · correction within ten minutes · card/totals agreement ·
real enrichment through `analyze()`. This decides whether the candidate
*product* is viable, not whether the code works.

**B-1e — delete only what overlaps B-1:** the legacy single-item mass-quantity
question producer, its answer reconstruction, its quantity-specific pending
ownership, and any prose option derivation used for that slice. Then lower C8
and C9 in the same commit.

### B-1 promotion gates

Promotion means deleting the legacy quantity path. Blocked until all hold:

```text
[ ] the B-1b evidence window says the option pipeline is good enough to keep
[ ] B-1d shipped and the canonical structured client is sufficiently deployed
[ ] 100% of eligible turns canonical, production-proven
[ ] no canonical operation ever fell back mid-flight (C10)
[ ] rollback tested
```

### Open findings — deferred, not dropped

Each is real, none blocks the current phase, and none may be closed silently.

| finding | evidence | owner |
|---|---|---|
| `/admin/food-traces?q=` is ignored — substring queries return EVERYTHING, not nothing | measured 08-05 | instrument fix, unscheduled |
| `phantom_log_claim` fires in the harness but showed `flags=None` on both production incident turns; `skills_fired` is NULL even on turns that wrote rows, so the column cannot say why | measured 08-06 | **unrecorded until now** — needs a cause before it is trusted as a safety net |
| the legacy lane re-logged a meal already on the board (entry 2862 duplicated 2861, `legacy_reason=interpreter_none`) | measured 08-06, row deleted | D7 — the path B-1 replaces |
| `reask_refused` firing for user `ios:5` on the legacy lane | observed 08-05 | uninvestigated |
| `scripts/b1_operation_probe.py` cannot exercise B-1 — it drives `/api/v1/chat`, which is `PLATFORM="ios"`, excluded until B-1d | by design | B-1d |
| zero history-sourced options across all asks so far | 7 asks, all `sources=ontology` | B-1b decides whether this is recall or ranking |
| two voices: B-1 turns render from a template, legacy turns from the composer, so the assistant sounds different depending on which lane owns the turn | measured 08-06 | item 2 above |

### Release gates — where the whole product stands

**Team assessment, 2026-08-06.** B-1 proves the migration *method* and the
hardest ownership mechanics. It does not mean every food behaviour has moved.

```text
Core backend architecture        80–85%
Food logging migration           60–70%
Production-ready food product    55–65%
Entire Arnie V1                  45–55%
Tightly controlled beta          close
Broad consumer release           not yet
```

| gate | goal | position after |
|---|---|---|
| **1 — Internal canonical product** | daily internal use with no manual DB intervention: B-1 promoted, detector silence explained, pricing and card/totals verified, corrections and undo safe for the supported scope, telemetry readable, failures visible | 55–60% of V1 |
| **2 — Closed beta** | the common food workflow end to end: B-1 → ~B-2.7, single and multi-item, branded foods and package fractions, preparation and additions, Quick/Moderate/Strict, corrections/deletion/undo, structured iOS, one presentation authority, no critical legacy duplication on eligible turns | 70–80% |
| **3 — Release candidate** | chargeable: every intended slice promoted, overlapping legacy writers deleted, clarification ownership consolidated, voice boundary stable, output consistent, onboarding, billing, analytics, error budgets, rollback playbooks. **This is where the serious voice and diction pass belongs** — the renderer finally sits on stable intents and committed facts | 90–95% |
| **4 — Public release** | staged rollout completed, acceptable duplicate/false-confirmation/correction/abandonment rates, stable latency, no unresolved severe data-loss path, release-blocking legacy deleted, privacy and account-deletion reviewed, support process live | shipped |

The last 5–10% after Gate 3 is not features. It is reliability proof, rollout
evidence and cleanup.

**Rough ranges** (two focused engineers, architecture reusing cleanly, no
foundational surprise — planning aid, not a commitment):

```text
close and promote B-1                          1–3 weeks
common single-item clarification surface       3–6 more
multi-item, products, additions                4–8 more
corrections, undo, presentation consolidation  3–6 more
production hardening and closed beta           3–5 more
staged broad release                           2–4 more

credible closed beta        8–14 weeks
release candidate          14–22 weeks
broad rollout              16–26 weeks
```

**What is NOT yet canonical, and gates production readiness.** Logging commits
canonically; these still do not: corrections and edits · additions to an
existing meal · deletion · undo · replacements · merge/split · delayed and
out-of-order answers · proactive follow-up actions. A system is not
production-ready while logging is canonical and correction takes a separate
mutation path. Those are Phase C-1 through C-3.

### Earlier items — superseded or still live

Reconciled rather than carried forward silently:

```text
P3  chips on every question        SUPERSEDED for quantity by B-1; still open
                                   for every other attribute (B-1.5+)
P4  undercount as a commit gate    STILL LIVE, unscheduled
P5  resolving state, latency copy  STILL LIVE, unscheduled
Phase 1b invariants I2/I7/I8       STILL LIVE, unscheduled
adversarial gap hunt before push   STILL LIVE, unscheduled
```

