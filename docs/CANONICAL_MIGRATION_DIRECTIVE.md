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

Its first application is the **B-1 production-evidence ladder (B-1b)**:
B-1's option pipeline does not widen until the evidence says which candidate
source actually produces answers people accept and do not correct. Note what
the rule does NOT say — it does not require that evidence to be organic. Class
matters, not provenance: deterministic behaviour is proven deterministically,
and only natural preference requires natural traffic. It is deliberately labelled inside B-1 — it
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

*(Superseded by events — kept for the construction/storage distinction below.
As of 2026-08-07: B-1 and B-1.9 are production-proven on iOS, B-1.5's
machinery is deployed and blocked on B-1.5E, and the authoritative "where are
we" is the Status board. This section is history, not position.)*

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

*(2026-08-07: the lifecycle below is BUILT and deployed — PARTIAL outcome,
`hold_answer`/`ready_to_settle`, `ResolvedFields`, per-field settlement, the
two-field producer, evidence-driven `unresolved_when`, and the iOS multi-field
client. Preparation opens nowhere in production because no evidence source can
establish comparability — see B-1.5E, which now gates closure. The spec below
remains the contract.)*

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
| **iOS B-1d: ID-addressed payload + real chip-path proof** | DONE 2026-08-07 — entries 2887/2890 answered by `option_id` |
| **the card the client can actually decode** | DONE 2026-08-07 — `card_for` was dropping `quantity`/`carbs_g`/`fats_g`, which iOS declares non-optional; the meal logged and the card vanished silently |
| **reply-metadata binding for `LABEL_TEXT` channels** | TODO — owed with B-1d |
| **rollout** | ~~allowlist → 1% → 5% → 25% → 100%~~ **SUPERSEDED 2026-08-07.** No ramp. Allowlist only through B-2, then ONE promotion event |
| **deletion: legacy quantity producer, option builder, answer reconstruction, prose-chip path; lower C8/C9** | DEFERRED to the one promotion event — not per slice |

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

*(Inherits from B-1.5: the preparation ontology (`preparation_ontology.py`,
ids constrained to resolver-actionable tokens — `breaded`/`plain` rejected as
inert, `baked` folded into `roasted` for the validator, though USDA itself
says "baked" for potatoes), identity-composition pricing, and the B-1.5E
evidence layer. MULTI_SELECT remains unproduced and the one-answer-per-field
limit is pinned by `test_one_field_holds_exactly_one_answer_and_that_is_a_known_limit`
— multi-valued additions land HERE, and that gate is where the work starts.)*

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
 1. B-1 one-item quantity                   DONE, production-proven
 2. B-1.5 quantity + preparation           }  machinery DONE; closure
    2a. B-1.5E semantic evidence layer     }  blocked on 2a
 3. B-1.6 conditional activation           }  all built on the canonical
 4. B-1.7 mode policy                      }  path, allowlist only
 5. B-1.8 answer repair/fallback           }
 6. B-2 multi-item and partial answers     }
 7. THE PROMOTION EVENT — all users to canonical, allowlist removed,
    legacy food pipeline deleted, ratchets lowered. Once, not per slice.
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
previous capability is authoritative end to end and production-measured. That
gets Arnie to the desired backend without recreating the same fragmentation
under better type names.

### One promotion event, not a rollout ramp *(Danny, 2026-08-07 — SUPERSEDES per-slice promotion)*

**Canonical stays allowlist-only — user 26 and internal testers — through
B-1.5, B-1.6, B-1.7, B-1.8 and B-2.** Every one of those is built on the
canonical path. Then a SINGLE promotion:

```text
  move all users to canonical
  remove the allowlist
  delete the legacy food pipeline
  lower the migration ratchets
```

**Why: one migration event instead of repeatedly switching production users
between implementations.** The prior order promoted and deleted after each
slice, which meant every user crossed the boundary five separate times, each
crossing carrying its own regression surface and its own rollback question.

**What this changes about the earlier rule.** "Prove → promote → delete →
reuse" required a slice's legacy owner to be *deleted* before the next slice
began. That clause is now deferred to the promotion event for the whole B-1
family. The reuse discipline is unchanged: each slice must still be
authoritative and production-measured before the next starts.

**The cost, stated plainly, because deferring deletion is the thing that rule
existed to prevent.** The legacy path stays alive through five more slices, so
"two owners of one behaviour" is carried longer, and C4/C8/C9 stay high until
the end. Two facts make it affordable and both must keep holding:

* legacy is **unchanged** for everyone outside the allowlist, so drift cannot
  reach a production user before promotion;
* the canonical path is **additive** — `try_take_ownership` returning None
  leaves the turn exactly as it is today.

If either stops being true, this sequencing has to be revisited rather than
worked around.

**The promotion event is therefore large, and must be gated hard rather than
declared.** Its gate is the union of every slice's promotion criteria — not a
fresh judgement made on the day. Each slice writes its promotion conditions as
executable gates when it lands, so promotion is running them, not re-deriving
them.

## Status board

Kept current. This is the single answer to "where are we"; the phase sections
above are the detail. **Everything open lives here** — a finding recorded only
in a session, a commit message or a side document is a finding that gets lost,
which is how this board came to read "B-1 NEXT" while B-1 was production-proven.

Last reconciled 2026-08-07 (evening) against production traces, the evidence
corpus, and the commit history through `c5d3614`. The findings ledger below the
board holds everything instrumental from the B-1.5 build-out.

```text
Phase A    COMPLETE          production-verified on a66e9ba8
B-0        COMPLETE          ratchets enforced continuously (C8, C9)
B-0b       COMPLETE          contract surface
B-0c       COMPLETE          serialization, validation, immutability, persistence
B-1.75     COMPLETE          answered quantity is the only quantity authority
B-1.9      COMPLETE          production proven on iOS 2026-08-07
B-1b.1     COMPLETE          absorbed by B-1.9 step 7
B-1b.2     COMPLETE          absorbed by B-1.9 step 7
B-1b.3     CONTINUOUS        usability evidence, NON-BLOCKING
B-1b.4     CONTINUOUS        low-volume organic evidence, NON-BLOCKING
B-1c       COMPLETE          detector coverage and precision
B-1d       COMPLETE          native ID-addressed iOS live

B-1 canonical capability   COMPLETE for allowlisted users
B-1 global promotion       DEFERRED until B-2
B-1 predecessor deletion   DEFERRED until B-2
B-1 legacy                 FROZEN for non-allowlisted users

B-1.5      BLOCKED ON B-1.5E readiness, producer, pricing and the generic
                             `unresolved_when` derivation are DONE and
                             deployed (c5d3614). Preparation cannot open:
                             no evidence source can say whether a retrieved
                             row is about the food the user meant. MEASURED,
                             not inferred — a bare `chicken` query returns
                             zero comparable rows.
CONTRACT   FROZEN 08-07      semantic field registry + rule of three
B-1.5E     NEXT              semantic evidence resolution. Bounded
                             prerequisite; two consumers, then stop.
B-1.6      after B-1.5
B-1.7      after B-1.6
B-1.8      after B-1.7
B-2        after those prerequisites
PROMOTION  after B-2 — a DELETION event, not a flag flip
B-3/B-4    ownership consolidation and deletion
C/D/E/F    canonical food, shared contracts, workouts
```

**Promotion and deletion are deliberately batched after B-2. This is a
ROLLOUT decision, not an architectural dependency.** Canonical development
continues for allowlisted users only. Nothing in B-1.5 through B-2 waits on
promotion, and promotion waits on all of them.

## Findings ledger — 2026-08-07, the B-1.5 build-out

Everything here was paid for once. Recorded so it is not paid for again.

### Defects found and fixed, by class

**A — architecture**

* **Lane ownership had two owners and had already drifted.** `conversation.py`
  computed client capability, `try_take_ownership` asked the rollout gate;
  `client_capable` ("can read the payload at all" — TRUE for Telegram)
  collapsed into `ID_ADDRESSED if client_capable else LABEL_TEXT`, so a real
  Telegram turn persisted `surface=id_addressed` (`telegram:9241`). One gate
  now (`canonical_food_enabled` → `LaneDecision`), capability carried on the
  ask, ratchet keeps derivations from coming back. Deploy-safe because
  `surface` is inside the `decision_id` hash — a corrected turn writes a NEW
  decision rather than raising DeterminismViolation.
* **The expiry door bypassed readiness.** An expired-but-awaiting operation
  receiving its FIRST late answer settled immediately — a late tap on Amount
  would have committed a two-field meal with Preparation never asked. Found by
  an existing sweep gate failing with "reached settlement with no quantity
  answer". Settled-vs-expired share one claiming rule but NOT one settlement
  path.
* **`ResolvedFields._one` returned `found[0]`** — right for one food, silently
  wrong for two: would price the chicken and drop the rice. Cannot fire in
  B-1.5 (one event by construction); defused before B-2 with a loud raise plus
  `for_event()` / `event_ids` as the per-event seam. B-2 settles per event; it
  does not relax the check.
* **`clear_day_log` deletes with no ledger events** (14 rows, 4 canonical,
  zero `deleted` events — the ledger CAN record food deletes; this path
  doesn't). OPEN, and ahead of B-1.6 in urgency: unrecoverable data loss on
  the canonical lane.
* **Cross-lane pending-state leak** (16:08 salmon): canonical settled and
  released; legacy re-asked a question canonical answered 21s earlier, then
  read "Ignore" as a log instruction. NOT hybrid ownership — the measured
  standing cost of deferring promotion until B-2. Accepted, not fixed.

**C — implementation**

* **The client silently dropped every canonical card.** `card_for` omitted
  `quantity`/`carbs_g`/`fats_g`; iOS `MacroCardPayload` declares them
  non-optional; synthesized Decodable fails the whole struct; `try? decode` →
  `.unknown` → dropped. The backend gate asserted only "cards non-empty" — the
  server WAS sending a card the client could not read. Now pinned field-for-
  field against legacy's card.
* **B-1.5 was askable and unreachable.** Preparation opened only when the
  interpreter volunteered the ambiguity, which it does not do for a food it
  identifies confidently. The producer's trigger is now the field's own
  evidence-driven `unresolved_when` — but see B-1.5E: the evidence itself is
  the remaining blocker.

**D — nutrition (tracked, not B-1.5's to fix)**

* Papaya 2896: 200 cal for 80g — the heavy-syrup row (206/100g) over raw (43).
* Banana 2891: 736 cal for 236g (312/100g vs real ~89) via canonical free-text.
* Both are the same class: retrieval treated as identity. B-1.5E's boundary is
  the structural fix; no food-specific patches.

**F — instruments that lied by silence, continued**

* `turn_metrics.outcome` = ok on 1188/1188 rows ALL-TIME. A non-ok value has
  never been written; "no errors in 7d" from this table is worth nothing.
* Proactive turns: 50 conversation_logs rows in 7d, 0 turn_metrics — every
  route-mix and latency table silently excludes them.
* `meal_commits.result_payload` carries no enrichment receipt — the papaya
  miss could not be diagnosed from durable state. Forensic reproducibility is
  a B-1.5E deliverable (§9 persistence).
* My own deploy watcher grepped `"ae95043|ok"` — matched `"status": "ok"` on
  the OLD build and reported success. The instrument-verification rule applies
  to instruments built mid-conversation too.

### ⭐ The synthetic-fixture failure — the one to internalize

The first B-1.5 producer shipped FOURTEEN green gates against `CHICKEN_ROWS`,
a fixture written to look like USDA and never checked against it. Mutation
testing caught a vacuous gate INSIDE the fixture (FLAT_ROWS used raw/boiled/
grilled — only one registered, so the materiality branch was never reached, and
mutating the threshold changed nothing) and still could not catch that the
fixture was fiction: **mutation testing verifies the test against the code,
never the code against the world.** Only a live probe found it.

Standing rule: a slice that consumes provider data is not proven until
something has touched the provider. Recorded fixtures are captured, never
authored (`tests/evidence_corpus/`), and stay ugly.

### Working patterns that held (reuse them)

* **Write the gate, then the headline** — held through ~20 commits.
* **Mutation-verify every new gate** — caught the vacuous FLAT_ROWS gate, the
  copy_for fall-through to "Logged.", and each ratchet's ability to fire.
* **AST ratchets over substring** — substring flagged its own explanatory
  docstrings twice; punishing WHY-comments teaches people to delete them.
* **Behavior, not mechanism, when porting** — badges-v2 reconciliation took
  five commits whole, rejected 650e414 for resurrecting QuickReplyEngine, and
  hand-ported its ReceiptStore fix by file.
* **Function calls, not import side effects, for registration** —
  `import_module` on an already-imported module is a no-op; `_reset_for_tests`
  never repopulated and 35 tests went red at a distance.
* **Construction free, presentation gated** — the contract bites on the
  interaction (persisted, rendered, answered), not on `UnresolvedField`, or
  the Phase-O workout seam breaks.
* **Live-probe the operand before writing the policy** — the corpus capture
  found in one hour what the fixture hid for a full commit cycle.

## B-1.5E — SEMANTIC EVIDENCE RESOLUTION *(Danny, 2026-08-07 — prerequisite, bounded)*

**B-1.5's topology is sound and its producer is blocked on evidence quality.**
Measured in production, not inferred: the multi-field spine holds, preparation
prices correctly through canonical naming, and the field cannot open because
nothing can tell whether retrieved evidence is about the food the user meant.

### What the measurement actually showed

Real USDA, corpus of seven, captured 2026-08-07 — **preserved raw in
`tests/evidence_corpus/usda_2026_08_07.json` with human-reviewed ground truth
in `tests/evidence_corpus/GROUND_TRUTH.md`**. Fixtures for the semantic layer
start from those files, never from memory of them. A bare `chicken` query returns
**zero** comparable rows in its top eight:

```text
Chicken spread · Chicken, meatless · Fat, chicken (900 cal) · Frankfurter,
chicken · Fast foods, chicken tenders · Bologna · Bratwurst · Chicken, canned
```

`Papaya, canned, heavy syrup` at **206 cal/100g** sits three rows above
`Papayas, raw` at 43 — and production entry 2896 committed 200 cal for 80 g.
The papaya miss is this defect, already shipped.

Shaped queries are worse, not better: they fall through USDA's curated pass into
Branded and return all-caps commercial rows.

⭐ **AND THE LESSON THAT MATTERS MOST.** The first B-1.5 producer shipped with
fourteen green gates against a `CHICKEN_ROWS` fixture I wrote to LOOK like USDA
and never checked against it. Mutation testing caught a vacuous gate INSIDE that
fixture and still could not catch that the fixture was fiction — mutation
testing verifies the test against the code, never the code against the world.
Only a live probe found it. **Synthetic provider fixtures must be grounded in
captured real responses, and a slice that consumes provider data is not proven
until something has touched the provider.**

### The prohibition, and it is absolute

There must be no production identity logic based on regex matching,
comma-position parsing, token counts, substring exclusions, food-name
allowlists, curated lists of foods needing clarification, enumerated bad
provider results, `if food == "chicken"`, `if "fat" in candidate`,
provider-specific textual special cases, or calorie-density multipliers standing
in for identity.

**A provider adapter may decode STRUCTURED provider fields. It may not infer
food semantics from naming tricks.** If USDA exposes a field, use it. If USDA
exposes only a human-readable description, that description is natural-language
evidence and goes through semantic resolution.

This kills the tempting fix. USDA writes `<base>, <qualifiers>`, so "the leading
term is the base identity" would reject five of six failure classes for
`chicken` in one line — and it is a naming trick, provider-specific, and the
first description that breaks the convention breaks the system silently.

### The layer

```text
typed FoodIntent  +  bounded EvidenceRecord[]
        -> SEMANTIC RESOLVER (model, typed, versioned, schema-closed)
        -> EvidenceAssessment[]   relationship + extracted semantics
        -> DETERMINISTIC POLICY   authority, thresholds, abstention
        -> qualified evidence graph
        -> semantic-field derivation
```

`relationship` is closed and driven by measured failure classes:

```text
SAME_IDENTITY · COMPATIBLE_SPECIALIZATION · COMPOSITE_CONTAINING_IDENTITY
DERIVED_OR_EXTRACTED_FORM · SUBSTITUTE_OR_ANALOGUE · DIFFERENT_IDENTITY
INSUFFICIENT_EVIDENCE
```

**THE MODEL INTERPRETS MEANING; CODE DECIDES AUTHORITY.** The resolver may say
`COMPATIBLE_SPECIALIZATION, confidence 0.94, preparation=roasted`. It may never
say "use this row" or "log 226 calories". `confidence=0.91` does not authorize a
mutation — a deterministic threshold owns that, and nutrition values still come
from the existing resolver ladder.

**UNDER-SPECIFICATION IS EXPLICIT.** "I had chicken" means *base identity
chicken, everything else unspecified*. It does not mean "any description
containing chicken", and it does not mean "assume chicken breast".

**SEMANTIC CONFIDENCE AND SOURCE QUALITY ARE DIFFERENT DIMENSIONS.** A model can
be highly confident a low-quality blog is about fried chicken while policy
refuses it for nutrition. Store both, plus `claim_support`.

**AUTHORITY IS PER CLAIM, NOT PER SOURCE.** Web search answers the materiality
question USDA cannot — measured: grilled ~165 vs fried ~297 cal/100g — but its
synthesized answer is admissible for *"is preparation worth asking about"* and
inadmissible for *"what are this food's calories"*. `TAVILY_API_KEY` is
configured in production.

**PRECISION OVER RECALL, AND ABSTENTION IS A RESULT.** Rejecting a useful
candidate costs another lookup; accepting chicken fat as chicken costs a wrong
meal. `INSUFFICIENT_EVIDENCE` is a first-class answer.

Persist typed conclusions — never chain-of-thought — under
`food_evidence_semantics_v1`, so changing the prompt or model cannot silently
redefine historical assessments.

### The core/domain boundary — protected aggressively

**There is no single giant resolver that knows every domain's ontology.** The
shared layer provides mechanism and contract; domains provide schemas and
meaning:

```text
shared core                          nutrition (first domain)
  EvidenceRecord                       FoodIntent schema
  SemanticAssessment                   food relationship vocabulary
  resolver invocation/versioning       preparation projection
  confidence/abstention contract       product projection
  persistence
  policy boundary                    workouts (Phase E/F, later)
                                       ExerciseIntent schema
                                       exercise relationship vocabulary
                                       equipment / load / reps projections
```

**THE HONESTY TEST, and it is a gate, not a sentiment: if workouts adopt this
later, core must not change.** Workouts add a domain schema, field
registrations and evidence projections — never another semantic-resolution
architecture. This is the same inversion already enforced for the field
registry (`_DOMAIN_REGISTRARS`, `supported_vocabulary`), extended to evidence:
the seam generalizes or it is nutrition-specific debt wearing a generic name.

Why this detour is not really a food detour: it is the missing seam between
probabilistic interpretation and deterministic execution —

```text
LLM / search / external systems -> uncertain evidence
    -> typed semantic boundary -> deterministic canonical system
```

— which is what later lets Arnie become more agentic without probabilistic
reasoning ever mutating user state directly.

### Scope, and where it stops

NOT a food ontology, knowledge graph, universal nutrition engine, search engine,
fine-tune, cuisine model, restaurant intelligence, ingredient decomposition or
recipe reconstruction. The objective is narrow: **stop retrieval results being
treated as interchangeable because strings overlap, and make enough trustworthy
evidence available to production-prove preparation.**

Two consumers prove generality — preparation AND product_variant, sharing one
assessment with different projections, neither owning an identity matcher.
Product_variant may not be substituted for preparation: B-1.5 closes on a
NATURALLY occurring real iOS turn, with no constructed ambiguity, no synthetic
rows, and no manually inserted field.

**When B-1.5 passes, stop and resume B-1.6.**

## THE SEMANTIC EXTENSION CONTRACT *(Danny, 2026-08-07 — enforced, not documented)*

**A new food behaviour enters as a REGISTERED FIELD or it does not enter.**
`core/semantic_fields.py` is the registry and the only door. The question asked
of "fried", "with sauce", "half the package", "skin on" and "brand variant" is
the same one every time — *what semantic field is this?* — and an
implementation beginning `if "fried" in food_name` has already answered it
wrong.

A spec declares all of: typed `attribute` · `value_space` · `patch_type` ·
`pricing` · `evidence` · `settlement` · `activation` (+ predicate) ·
`vocabulary` · presentation metadata. `register()` refuses anything else, at
IMPORT time, so a malformed field breaks the process rather than the first user
who triggers it.

**The invariants, and where each is enforced:**

| invariant | enforced by |
|---|---|
| a field cannot be **presented** unless registered | `ClarificationInteraction.__post_init__` |
| unsupported semantics cannot be emitted | `register()` → `validators._PREPARATIONS` |
| `ResolvedFields` is the ONLY settlement boundary | `Settlement` has one member |
| no field may price by a multiplier | `Pricing` has no such member |
| exactly one field decides the amount | `register()` |
| a conditional field declares its predicate as DATA | `register()` |
| no field-specific settlement extractor | AST ratchet |
| the coordinator names no attribute | AST ratchet |

**Two boundaries that are NOT the same, and conflating them broke a test.**
`ClarificationAttribute` is the vocabulary of what COULD be asked — including
the Phase-O workout attributes that exist so onboarding workouts need no food
edit. The registry is what CAN be asked today. Construction is free;
**presentation** is gated. That is why the check sits on the interaction rather
than on `UnresolvedField`.

### The rule of three — PASSED, and what it does not prove

`tests/test_the_rule_of_three_fields.py` registers a third family
(`serving_basis`, `Pricing.NONE`, its own patch type), drives it through
production, presentation, answering, holding and settlement, and asserts three
fields settle **once** with no coordinator change. It passes, and the coordinator
names no attribute.

**It is a probe, deliberately not shipped** — a field with no producer and no
user is the defect `UNUSABLE_AMOUNT` was deleted for.

**A KNOWN LIMIT, pinned by its own gate.** All three families answer with ONE
option producing ONE patch, and `hold_answer` keys the held map by field id, so
a second answer REPLACES the first. A genuinely multi-valued field ("no bun,
extra cheese") cannot be expressed: the held value would have to become a set
and `ResolvedFields._one` would have to stop assuming singularity.
`ResponseType.MULTI_SELECT` exists and nothing produces it.
`test_one_field_holds_exactly_one_answer_and_that_is_a_known_limit` is there so
whoever tries finds out from a test rather than from a user whose second
selection vanished. **"The mechanism is generic" must not be read more broadly
than this.**

### Owed to B-1.5 UI — ported behavior, NOT the legacy mechanism

`feat/badges-v2` reached these on the legacy `QuickReply` bar. Those four
commits were deliberately NOT picked (37f946d, 34f2b2c, 0a10677, 8652439) —
label-valued answers, a `group` index for identity, label deduplication and
legacy chip routing are the architecture B-1b replaced and D7 deletes. Four of
the product decisions were hand-ported in `55bf93b`; **two remain owed**, and
both need canonical equivalents expressed through `option_id`:

* **selected answers render back into the transcript** — from `34f2b2c`. The
  chosen chip should appear as the user's turn, by option id, never by echoing
  the label back as if they had typed it.
* **a card does not visually erase an unresolved question** — from `0a10677`. A
  committed card arriving while another field is open must not read as "done".
  Directly relevant now: B-1.5 settles on the LAST field, so every partial turn
  is exactly this state.

These are presentation and belong with the B-1.5 UI work, not with the
contract. Also owed and unrelated: `ArnieShare` (from `6376a76`) needs its
provisioning profile before a signed device build.

### Product-quality backlog — recorded, NOT blocking

These are B-1's first-production findings. They are product quality, not
semantic-spine defects, and none of them justifies reopening canonical
architecture. Do not let them interrupt B-1.5 through B-2 unless severity
changes.

| finding | note |
|---|---|
| labels render `118g`, not `4 oz` | `_everyday_labels` does not know the food; the number is correct, the phrasing is not |
| iOS replies are richer and slower | 223 chars vs Telegram's 95 — `IOS_STYLE` + `NATIVE_CARDS` + `IOS_FORMAT_ANCHOR`. A product decision about output length |
| copy refinement | Arnie voice over committed facts, still the deterministic fallback |
| chip visual polish | client-side |
| candidate-quality generalisation | belongs to the generalised generator milestone, not here |

**Latency is a separate thread from this migration.** Measured on the same
user: the structured tap itself is 257 ms, and iOS framework overhead
(15–154 ms) is LOWER than Telegram's. Perceived latency is dominated by model
output length, not by the clarification architecture. Optimise it separately;
do not treat it as evidence about the canonical path.

### Legacy is a frozen compatibility lane, not a second development lane

Allowed in legacy:

* P0/P1 production fixes
* security fixes
* migration compatibility needed to keep existing users working

Forbidden in legacy: new food features · new clarification semantics · new
pending mechanisms · new candidate logic · new mutation writers. **All new
food capability belongs to canonical.**

### Lane ownership is decided ONCE, at the top of the food turn

`core.canonical_lane.canonical_food_enabled(user_id=…, channel=…)` is the one
gate, and `tests/test_one_gate_decides_the_lane.py` is the ratchet that keeps
it the only one — no other module may name `may_take_ownership` or
`client_renders_interactions` to decide a lane.

**There is never hybrid ownership inside one user turn.** A canonical user may
not ask through canonical and answer through legacy, create canonical pending
state and fall back to legacy pending state, commit through a legacy writer
because canonical clarification failed, reconstruct canonical options from
prose, or switch implementations between turns of the same live operation.

**PROMOTION BLOCKER — no per-request client build.** The gate takes
`(user_id, channel)` and not `(user_id, channel, build)`, because NOTHING
carries a client build to the backend: no header, no field. `_CHANNEL_CAPABILITY`
therefore claims `ios` is `ID_ADDRESSED` for the whole platform rather than for
the app in the user's hand. An older build that cannot decode `interaction`
receives `ask_copy(capability=ID_ADDRESSED)` — the introduction ALONE, options
carried only in a payload it cannot read — so the user sees "How much chicken
breast?" and nothing to pick from. Free text still works; the options are
invisible and their usage rate reads zero. Harmless at one user on a known
build; NOT harmless at promotion, which is when every old build arrives at
once. Closing it needs an iOS version header plumbed through to the gate.

### B-1 state — the authoritative lines

```text
B-1 lifecycle implementation       COMPLETE
B-1 production lifecycle proof     COMPLETE
B-1a wording                       COMPLETE      versioned b1_quantity_q2
B-1c safety observability          COMPLETE      coverage and precision proven
B-1b.1 system validation           COMPLETE      absorbed by B-1.9 step 7
B-1b.2 sequence simulation         COMPLETE      absorbed by B-1.9 step 7
B-1b.3 human simulation            CONTINUOUS    usability, NON-BLOCKING
B-1b.4 organic confirmation        CONTINUOUS    low volume, NON-BLOCKING
B-1d structured iOS client         COMPLETE      live, answering by option_id
B-1 canonical capability           COMPLETE      for allowlisted users
B-1 global promotion               DEFERRED      until B-2
B-1 predecessor deletion           DEFERRED      until B-2
B-1 legacy                         FROZEN        for non-allowlisted users
```

These last four lines are a SCHEDULE, not a defect. B-1 is not blocked on
anything; promotion and deletion were batched to the end of B-2 so production
users cross the boundary once instead of five times.

Quote these lines rather than a single adjective. "B-1 is done" is true of the
first four and false of the rest, and the slice loop is won or lost in the rest.

**The last three lines changed meaning on 2026-08-07 and the distinction
matters.** They no longer read BLOCKED because something is wrong; they read
DEFERRED because promotion and deletion were consolidated into a single event
at the end of B-2. B-1 is not waiting on a defect. It is waiting on a schedule.
Do not let that reading drift back into "B-1 is finished" — the legacy producer
is still alive and still serving everyone outside the allowlist, which is
exactly the condition the slice loop was written to make visible.

**B-1 owes the promotion event its executable gate.** Write it when B-1.5
starts, not on promotion day: the answered quantity produces the committed
numbers across every basis, and the legacy quantity path has no remaining
caller. That is the B-1.75 condition already recorded above.

### B-1.9 — candidate-system correction. Runs BEFORE B-1 closure.

**Received 2026-08-06.** Two production failures showed the candidate layer,
not the lifecycle, is what is wrong. B-1.5 does not start until this and B-1
closure are done.

```text
1  contain unsafe "not sure"        <- IMMEDIATE, safety
2  add the missing quantity semantics
3  instrument the whole candidate universe
4  evidence-backed quantity generator
5  versioned candidate selector
6  replay the two failures as SYSTEM CLASSES
7  complete B-1b.2 integration evidence
8  freeze the candidate contract
9  structured iOS interaction
10 promote and close B-1  (deletion included, or it is not closed)
```

**1 — contain unsafe "not sure".** `USE_ESTIMATE` must not commit from weak or
unsupported evidence.

```text
not sure -> retrieve typed estimate evidence
         -> policy evaluates SUFFICIENCY
         -> commit only when the evidence supports it
         -> otherwise remain unresolved and REPAIR
```

Forbidden as the fix: a smaller hardcoded estimate · a midpoint · a
food-specific cap · a manually chosen "safe" portion · regex food
classification. Exit gate: **insufficient evidence → zero meal writes →
operation stays open → explicit repair.**

**1 — status: PASS with two carry-forwards** *(disposition 2026-08-06)*.
Landed `c859758`. **B-1 may not be promoted on this commit alone.**

* **CF-1 — replace source-name sufficiency with typed evidence semantics,
  before B-1.9 closes.** The containment currently keys on a frozenset of
  source NAMES (`{"user_history", "catalog"}`). That is a stand-in: it works
  because those sources happen to be entity-specific today, and it will drift
  the moment a source is added whose name says nothing about what its evidence
  is ABOUT. The property is semantic — *does this candidate describe this
  entity for this user* — and belongs on `QuantityCandidateEvidence` in item 2,
  read rather than inferred from a name.
* **CF-2 — persist the policy version.** ✅ done. `estimate_evidence_v1` was
  emitted to a log and nowhere else; the ring is a bounded in-memory deque
  that empties on deploy, so an analysis weeks later could not say which
  sufficiency rule produced a refusal. `b1_answer_observations.policy_version`
  (migration `b1obs003`), empty when no versioned policy governed the route —
  a stated quantity decides itself, and stamping every row would make the
  field mean "some policy ran" rather than "this policy decided".

Also fixed in passing: `modality_of` matched the reason by exact equality, so
improving an error message reclassified a refusal from `command` to `text`
and counted it as free-text usage — corrupting the "Other" rate with a better
sentence.

**⚠ CI HAS NOT PRODUCED A GREEN CHECK ON ANY RECENT COMMIT.** Raised in review
as "no combined status checks", investigated 2026-08-06, and it is worse than
a reporting quirk:

```text
6b66681  queued
c859758  failure   job=cancelled   15 min   no failed step
9c9d4ea  failure   job=cancelled   15 min   no failed step
cda108e  failure   job=cancelled   15 min   no failed step
bd30854  failure   job=cancelled   15 min   no failed step
a16bc03  failure   job=failure      7 min   failed at "Set up job"
```

**CAUSE: a GitHub Actions outage, not this repository.** The job page reports
*"The job was not acquired by Runner of type hosted even after multiple
attempts"* alongside an internal server error, and GitHub Status shows Actions
in **major outage** from 2026-08-06T15:22Z: *"Workflow runs are failing or
delayed in starting, and some queued jobs may time out."* Every red run above
falls inside that window, and one cause explains all five — jobs queue, no
runner takes them, they are cancelled around fifteen minutes.

Ruled out on the way: not the push cadence (`cancel-in-progress` is `false` on
`main`), not a job timeout (none set, default 360 minutes), and **not billing**
— which was my first hypothesis from the "Set up job" failure and was wrong.
Nothing needs enabling or configuring.

The cause being external and temporary does not change the standing: until a
check goes green, **every test result in this programme is author-reported
execution evidence, not an attached check.** The numbers are real and the runs
happened; nothing independent confirms them. That distinction belongs in the
evidence-class table alongside the others, and it should be closed before
promotion — a migration whose safety rests on a suite nobody else has seen run
is resting on the same kind of unverified instrument this slice keeps finding.

**2 — the missing contracts.** `ServingBasis` (MASS · VOLUME · COUNT · PIECE ·
PACKAGE · FRACTION_OF_PACKAGE · FRACTION_OF_ENTITY · STANDARD_SERVING),
`QuantityCandidateEvidence`, `EstimateEvidence`, `CandidateSet`,
`CandidateSelectionDecision`. Every candidate carries canonical entity id,
canonical quantity, serving basis, source type and record, conversion
evidence, confidence, uncertainty, policy version, provenance. **No candidate
without typed evidence enters an interaction.**

**2 — status: DONE** *(commits `f93e77c` + `cd17234`, 2026-08-06)*. CF-1 is
closed: sufficiency now reads declared scope and subject, not a source name.

* **Commit 2 shipped a P0 and review caught it.** `authorizes_assumption`
  proved the evidence *named* a user or product and never that it described
  the one being asked about — all three subject ids were stored and none was
  compared to anything, so evidence about user 123 would have authorised an
  assumption for user 456. Fixed in **2.1** with `EvidenceContext` and
  identity comparison, assembled **from the operation** rather than
  re-derived from the incoming message.
* `THIS_PRODUCT` → **`THIS_PRODUCT_QUANTITY`**, requiring a quantity-bearing
  basis. Identity is not consumption: knowing a jar is Brand X honey does not
  establish that three tablespoons were eaten.
* Evidence-bearing options **fail shut** without a context.

**3 — instrument the whole universe, not the selected three.** Persist all
generated candidates, their evidence sources, serving bases, conversions,
which were selected, which excluded, the selection reasons, policy version,
the answer, its modality, and any later correction — so that *retrieval*
failure, *conversion* failure, *selection* failure, *presentation-basis*
failure and *ranking* failure stop being one undifferentiated "bad options"
problem.

**3 is SPLIT — 3a contracts, 3b persistence** *(2026-08-06)*. The schema is
not cut until the shape is settled, because a migration is the one artefact
this programme may not amend after pushing
(`feedback_arnie_never_amend_a_pushed_migration`).

**3a — the architectural correction. `candidate_id` belongs to the CANDIDATE,
never to the evidence.** The first implementation put identity on
`QuantityCandidateEvidence`, which encodes *one candidate = one evidence
record* into the persisted shape. That assumption does not survive real
candidate generation, where one offered amount may be supported at once by
exact user history, package metadata and a canonical serving record. Caught in
review before any schema existed. Three levels now:

```text
CandidateSet
└── QuantityCandidate          candidate_id · normalized offered quantity
    │                          · presentation serving basis
    └── evidence[]             QuantityCandidateEvidence
                               observed quantity · observed basis
                               · provenance · applicability · conversion
```

The split also fixes an ownership ambiguity: with a quantity on both objects
and no stated authority, `candidate.quantity = 21 g` beside
`evidence.observed = 30 g` was representable and meaningless. The candidate
owns the **offered** value; evidence owns what its source **observed**;
crossing them requires a sourced conversion, and agreeing on one basis
requires agreeing on the number.

Further corrections taken in 3a:

* **Selection is reproducible only with its context.** A policy version alone
  does not determine the outcome — the same universe yields three text options
  on Telegram and five structured ones on iOS.
  `CandidateSelectionContext(surface, locale, maximum_options,
  renderer_contract_version)` is persisted, so the claim becomes *set + policy
  + context = same decision*.
* **A source id is not durable evidence.** A `food_entries` id points at
  whatever that row says now, not what it said at generation. Evidence
  snapshots `observed_quantity`, `observed_basis`, `observed_at` and a
  `SourceReference(dataset_id, dataset_version, record_key, record_version)` —
  so `portion:chicken_breast:large` cannot silently mean 174 g before an
  ontology refresh and 190 g after while presenting as one claim.
* **`RENDER_COLLISION`, not `DUPLICATE_LABEL`.** A label is presentation. Two
  candidates can be semantically distinct, collide in English and not collide
  in another locale; recording that as a duplicate would assert they meant the
  same thing when they did not. Reproducible only against
  `renderer_contract_version`, which is why that field is required.
* **No generic exclusion reason.** "Not selected" restates the fact already
  recorded. The enum is exactly `semantic_duplicate · render_collision ·
  selection_cap` — one per real policy branch.
* **Generation failures are not selection decisions.**
  `CandidateGenerationRejection` holds inputs that could not form a candidate.
  Forcing them into the universe would mean constructing invalid candidates
  just to mark them excluded, defeating the construction-time gates and
  corrupting the denominator of every selection metric. It also separates
  "found nothing" from "found a row that could not be used".
* **Keyword-only construction** on every new contract. These records grow
  fields as the slice does, and a positional call silently reinterprets an old
  argument as a new field.
* **Selected order is data**, not database insertion order — it decides which
  option is first, and therefore prominence and selection rate.
* **Opaque candidate ids.** Never built from user id, food name, label,
  confidence or evidence ordering; `semantic_hash` carries merge identity
  separately, where it can be compared without being an address.

The load-bearing gate: `selected ∪ excluded == every generated candidate` and
`selected ∩ excluded == ∅`. With it, three failures that look identical in
production separate — **retrieval** (absent from the set), **selection**
(present and excluded with a typed reason), **user rejection** (present in
`selected`, so it *was* shown). Without it the first two are one observation
and the third is guesswork over displayed options.

**3a — status: DONE, contracts only.** 7987 pass on SQLite, 0 failed.

**3a.1 — the contract proved evidence EXISTED, not that it produced the
offered quantity.** Review 2026-08-06 on `2d67bc3`. Every conversion check was
structural — a source exists, the factor is positive, the bases join up — and
none of them applied the factor. Reproduced before fixing:

```text
CONSTRUCTIBLE  evidence 240 ml x 0.758 g/ml -> candidate 435 g   (false by 2.4x)
CONSTRUCTIBLE  evidence 240 ml            -> candidate 500 ml    (both .grams None)
CONSTRUCTIBLE  confidence=7.5 · uncertainty=-40 · naive datetime
CONSTRUCTIBLE  a conversion claiming a result its own factor does not produce
```

The same-basis check read `.grams` only, so two volume quantities compared
`None == None` and agreed; count, piece, package and fraction had the
identical hole. Closed by `measure_on(quantity, basis)` plus one basis-aware
support operation — *evidence → typed conversion → supported quantity →
compare with the candidate's own quantity* — exact, with **no tolerance**. A
producer that must round declares `quantize_exponent` under a
`policy_version`, so rounding is a versioned decision rather than an epsilon
that absorbs real errors alongside representation noise.

Also in 3a.1:

* **`ServingExpression`** — a basis enum cannot render an option. `21 g +
  VOLUME` does not say `1 tbsp` / `15 ml` / `3 tsp`; `182 g + PIECE` does not
  say `1 breast` / `½ large breast`. That gap *is* the honey failure, and it
  was still there. The candidate now owns both what would be committed
  canonically and what the user is offered; a candidate that cannot be said
  cannot be constructed.
* **`ConversionEvidence.source` is a `SourceReference`**, not a free string —
  a density record can be corrected while keeping its key. It also carries
  input, output and policy version, so the conversion is executable.
* **`PresentedCandidateOption`** — "candidate c1 was selected" does not prove
  "c1 became `opt_c1`, labelled `6 oz`, first, in revision 0". The rendered
  label is **persisted, not recomputed**: locale and renderer version do not
  capture every renderer input, and re-rendering later answers a question
  about today rather than about that turn. This is what makes
  `RENDER_COLLISION` auditable.
* **Fail-shut properties became contracts**: timezone-aware `observed_at`,
  `0 ≤ confidence ≤ 1`, `uncertainty ≥ 0`, typed collection elements, and a
  `SourceReference` that must carry a `record_version` **or** declare
  `immutable_within_version` — a `food_entries` id points at whatever the row
  says now, and correction rewrites it.

**3a.2 — the shown serving and the committed quantity were still independent
fields.** Review 2026-08-06 on `e4b6139`. `ServingExpression` checked that
`amount` was positive, `unit_id` non-empty and `normalized` non-empty on its
basis — and never that the amount and the unit PRODUCE the normalized value.
Reproduced before fixing:

```text
CONSTRUCTIBLE  displayed 99 tbsp · normalized 15 ml · committed 21 g
               attached conversion 100 ml -> 140 g (valid, unrelated)
CONSTRUCTIBLE  unit_id "wibbles"
CONSTRUCTIBLE  set.user_id=26 holding a salmon candidate on a chicken field,
               carrying THIS_USER evidence about user 99
CONSTRUCTIBLE  presented positions [7, 12] and [0, 0]
   NON-DETERMINISTIC  a stored conversion returning 182, then 181, after any
               library anywhere set getcontext().rounding
```

Closed by:

* **`core/unit_registry.py`** — a closed Decimal table, so `amount + unit_id`
  formally normalizes to the stored quantity, and an unregistered unit is
  REFUSED rather than defaulted. Mass constants are **derived from
  `core.units`**, not respelled: the "one place knows what a pound is" ratchet
  caught this module on its first run, which is the gate working on a module
  added to improve exactness.
* **The attached conversion must be about THIS expression's values** — input
  equal to the expression's own basis amount, output equal to its committed
  mass. An internally valid conversion for an unrelated quantity licensed
  nothing while looking fully sourced.
* **`CandidateSet.context`** — the set is bound to an `EvidenceContext` and
  every candidate and scoped record is checked against it. Foreign evidence is
  **rejected, not out-voted**: applicability is an `any()`, so a population
  record beside a foreign THIS_USER record made the candidate look applicable
  while the foreign record stayed persisted and readable. A stored claim about
  another user is a durable disclosure whether or not a selector reads it.
* **`RoundingMode`**, persisted and passed explicitly to every `quantize()`.
* **Presented positions must be exactly `0..n-1`** — otherwise "position"
  means only "earlier than" and the exact row cannot be reconstructed.

**3a.2 — status: DONE.** 8035 pass on SQLite and 8035 on Postgres (21 skips),
97 contract gates.

**3a.1 — status: DONE.** 8017 pass on SQLite and 8017 on Postgres (21 skips),
79 contract gates. Mutation-verified: disabling the support comparison turns 5
gates red, disabling the conversion arithmetic turns 2 red. No schema, no
producer, no ranking, no visible-option change.

**A RULE ADOPTED BEFORE CUTTING THE SCHEMA** *(2026-08-06)*:

> Any field that participates in **identity, replay, authorization,
> arithmetic, or provenance** must be final before persistence. Organization
> and module placement may change later without changing the wire or the
> stored meaning.

That is what made 3a/3a.1/3a.2 worth their review cycles, and it is why
`core/semantics.py` being large is not a reason to delay 3b — splitting it is
pure module movement, gated on *no payload change, no schema change, no
renamed enum value, identical suite*.

**3b — status: DONE** *(2026-08-06)*. Five tables, `b1uni001`, all six
domain-neutral: `domain`, `subject_entity_id`, `candidate_kind` and typed
payloads. Nothing names a food, so exercise identity, set/rep, distance,
duration and dose ambiguity reuse them without a redesign.

**NOT SCORED ON THE TABLES EXISTING.** Scored on whether a persisted record
survives hostile lifecycle conditions without changing meaning —
`tests/test_the_candidate_universe_survives_storage.py`, 15 gates:

```text
atomic write                  partial write rolls back to zero rows
idempotent create             a retried ask finds its universe, not a second
same key / same fingerprint   returns the stored set
same key / diff fingerprint   DeterminismViolation, loudly
concurrent duplicate          one universe, DB-deduped, no half-written loser
process restart reload        full record from storage, generator never run
append-only revisions         revision 1 adds; revision 0 is untouched
user-scoped retrieval         an id alone does not open someone's history
schema/model parity           alembic head vs create_all, on Postgres
end to end                    the row persisted IS the row shown
```

Plus the analytics gate: `why_not()` returns exactly one of `shown` ·
`excluded:<typed reason>` · `not_generated`, and **never "unknown"** — with
the set's `rejections` separating "found nothing" from "found a row we could
not use". Exclusion reasons and evidence sources aggregate by `GROUP BY`
rather than by opening payloads, because "why wasn't my usual portion there"
has to be answerable at population scale.

**Fail-closed is wired at the ask.** The universe is written BEFORE
`open_operation`, so a persistence failure means no operation, no option ids
and no question — the turn proceeds as it does today and nothing was taken.
The alternative, ask-then-persist, produces exactly the state this record
exists to prevent: a user answering options nothing can explain.

**One instrument fixed while writing the gates.** The end-to-end test began as
`pytest.skip("rollout gate declined")` — which is an instrument lying by
silence: the day the gate started declining, it would have gone green having
exercised nothing. It asserts now. It caught two real setup defects
immediately (`client_incapable`, then `no_quantity_question`).

**3b.2 — durable identity and integrity completed** *(review of `6c5e87b`)*.
Four defects, all confirmed by reading the code before fixing:

* **P0 — a decision could never be written over an existing set.** `save()`
  returned the moment the set existed, so a second decision over the same
  immutable universe was impossible — and that is the NORMAL case: the same
  universe rendered for Telegram and for iOS, or reduced again after the
  selector versions up. Split into `ensure_candidate_set` /
  `ensure_selection_decision` / `ensure_presented_options`, three independent
  idempotencies. The set is write-once; the decision is not.
* **P0 — `maximum_options` was missing from the decision's identity**, in both
  the id hash and the unique constraint, while the selection context claimed
  the outcome was determined by it. A three-option text row and a five-option
  structured row collided under one identity: the second could never be
  written and the first was replayed in its place.
* **P1 — membership was enforced only by the aggregate.** Exclusions and
  presented options had a foreign key to the DECISION and none to the
  candidate, so either could name a candidate from another set, or from no
  set, at the database level. Composite foreign keys added; `candidate_set_id`
  added to `candidate_exclusions` and backfilled from the decision it already
  pointed at.
* **P1 — evidence had two durable authorities.** The candidate payload
  embedded its evidence AND every record was written to
  `candidate_evidence_records`; replay read the first, the funnel grouped the
  second. They could disagree, and the system would behave correctly while
  reporting the wrong provenance — a metric that is confidently wrong, which
  is worse than a missing one. The evidence rows are now the sole authority
  and the payload carries no copy to drift from.

`b1uni002`, **forward only** — `b1uni001` is pushed and `main` auto-deploys.

**A gate that was proving nothing.** Enabling the composite foreign keys
revealed that **SQLite ignores foreign keys unless the pragma is set per
connection**, so every database-integrity assertion in the storage suite would
have passed against an engine enforcing none of them. The fixture now sets
`PRAGMA foreign_keys=ON` and asserts it took. Same class as the three
instruments this slice has already caught lying by silence.

**3b — status: DONE.** 8061 pass on SQLite and 8061 on Postgres (21 skips),
26 storage gates.

**3b.3 — replay bound to the exact decision** *(review of `edae1d8`)*. Making
several decisions per universe legal — the 3b.2 fix — broke the read path,
which still behaved as though there were one. Three P0s, all reproduced first:

* **`load()` returned an arbitrary decision.** `.first()` over an unordered
  query, so once a universe held a Telegram decision and an iOS one, replay
  returned whichever row the database produced. That is the same failure as
  regenerating: a true statement about the system and a false one about this
  turn. `load_by_decision_id()` is the authoritative read now, `load()` orders
  deterministically and is administrative, and **the operation stores the
  `decision_id`** so the answer turn names the question it is answering
  instead of inferring it.
* **Decision equality compared only the winners.** Same options, different
  reason for dropping the rest — `SEMANTIC_DUPLICATE` becoming
  `SELECTION_CAP` — was accepted and silently discarded, so the caller
  believed one explanation and the record held another. A decision whose
  explanation can drift is not evidence. The whole canonical decision is
  compared now: selection AND order, exclusions AND reasons, full context,
  policy, set.
* **Presented equality compared only option ids.** `6 oz` becoming `8 oz`
  under the same id was accepted and dropped. The whole ordered row is
  compared now — id, candidate, set, revision, position, label, renderer.

Plus the P1: **the repository recovers from a lost race** instead of
surfacing an `IntegrityError` to a turn that did nothing wrong. Losing the
insert is a replay — the winner wrote the same universe — so it rolls back to
a savepoint, re-reads, and validates the fingerprint. Concurrency is proven at
all three boundaries, including two legitimately different decisions over one
set both persisting.

No migration: `decision_id` and `candidate_set_id` live in the operation's
existing JSON payload.

**3b — status: DONE.** 8073 pass on SQLite and 8073 on Postgres (21 skips),
38 storage gates.

**Superseded plan for 3b:** Atomic write of the immutable set and its typed decision
*before options are rendered*, fail-closed; append-only; candidate set bound to
its operation's user at write **and** read; database constraints as well as
domain validation, because migrations and future write paths bypass a
dataclass; `generation_input_fingerprint` so that the same key regenerated from
different inputs **fails loudly** instead of silently returning the old
universe; the interaction referencing its `candidate_set_id` directly, so
settlement proves `option_id → candidate_id → candidate_set_id → the exact
revision shown`.

**Commit 3 gates.** Ticked only against executed proof.

```text
[x] QuantityCandidate owns the normalized offered quantity
[x] evidence owns observed source facts, not candidate identity
[x] new contracts are keyword-only
[x] a candidate may carry multiple evidence records
[x] selection context is persisted and versioned
[x] selected ordering is durable
[x] label collisions cannot erase distinct semantics silently
[x] every exclusion maps to a real policy branch
[x] invalid generation attempts are separate from valid exclusions
[x] arbitrary converted quantities are unconstructable          3a.1
[x] same-basis mismatches fail for mass, volume, count,
    piece and package                                           3a.1
[x] every candidate can render its own basis                    3a.1
[x] every conversion authority is versioned and auditable       3a.1
[x] every shown option binds to one persisted candidate         3a.1
[x] rendered labels and positions are durable                   3a.1
[x] invalid timestamps or evidence types fail at construction   3a.1
[x] expression amount/unit formally produces its quantity        3a.2
[x] expression conversion starts and ends on that quantity       3a.2
[x] unrelated conversion evidence cannot be attached             3a.2
[x] candidate set rejects wrong-user / wrong-entity /
    wrong-product evidence                                       3a.2
[x] population evidence cannot mask foreign scoped evidence      3a.2
[x] rounding is deterministic independent of Decimal context     3a.2
[x] presented positions are exactly 0..n-1                       3a.2
[x] generator inputs carry a reproducibility fingerprint      3b
[x] same key + different fingerprint fails loudly             3b
[x] source evidence is snapshotted, not merely referenced     3b.1
[x] ontology source identity includes dataset version         3b.1
[x] the interaction directly references the candidate set shown  3b.1
[x] candidate set and decision are append-only                3b
[x] database constraints enforce cross-record integrity       3b
[x] user ownership is checked at persistence AND retrieval    3b
```

**Stop condition, unchanged:** the system can distinguish retrieval failure
from selection failure from user rejection **using durable records alone** —
not by re-running the generator, and not by inferring from displayed options.

**4 — status: DONE** *(2026-08-06)*. Every production quantity source emits
`QuantityCandidate` with typed evidence, a versioned source snapshot, a
`ServingExpression` and a stable semantic identity. The bridges are deleted:

```text
[x] every production candidate is natively typed
[x] every evidence record has explicit scope and subject
[x] every mutable source is revisioned or content-pinned
[x] every conversion is typed and versioned
[x] no producer emits ClarificationOption      selection does; producers do not
[x] generate() is the only production generation entry
[x] reduce_universe() is the only production reduction entry
[x] compatibility callers inventoried and RATCHETED
[x] _LEGACY_SOURCE_SCOPE deleted
[x] visible labels, order and patches unchanged
```

`tests/test_every_quantity_candidate_is_natively_typed.py` keeps them closed —
three of its gates are SOURCE SCANS, because a reappearing bridge behaves
identically to the canonical path until the day it diverges, so nothing
observable can catch it.

**The deletion forced a real wiring gap into the open.** With source names no
longer authorising anything, the estimate path refused every live turn: the
stored wire form carries only ids, by design, so options reconstructed from a
pending row have no candidate. The answer turn now resolves them from the
persisted universe via the operation's `decision_id` — which is exactly what
3b.3 stored it for, and the first thing to actually consume it.

**Both 3b follow-ups taken here rather than deferred**, since an
administrative default on a read path is what gets misused later:

* `load_for_replay(decision_id=...)` is separated from
  `load_oldest_for_admin()` **by signature**, so a future production caller
  cannot take the administrative behaviour by omission.
* `why_not()` is **decision-scoped**. "Shown" and "excluded" are properties of
  a decision, not of a universe — the same candidate can be shown on iOS and
  dropped on Telegram by the slot cap.

8080 pass on SQLite and 8080 on Postgres (21 skips).

**4 — the generator.** Approved sources only: exact canonical-entity user
history · validated entity portion evidence · validated product/package
metadata · canonical serving distributions. **Never**: food-name
conditionals, curated per-food option lists, arbitrary tiers, LLM-generated
numeric portions, unverified mass/volume/piece conversion, broad regex
classification. A narrow parser may recognise formal quantities (`1 tbsp`,
`50 g`, `½ package`); it does not decide what to offer.

**5 — status: DONE** *(2026-08-06)*. `skills/nutrition/candidate_selection.py`.

```text
[x] same set + same context + same policy -> identical decision
[x] every generated candidate is selected or excluded exactly once
[x] every exclusion has the actual typed policy reason
[x] the selector reads only persisted candidate features
[x] the selector performs no generation or enrichment
[x] option capacity respected without losing auditability
[x] semantically equivalent candidates merge, better-evidenced survives
[x] distinct serving bases are NOT collapsed when labels collide
[x] exact user history outranks population evidence when applicable
[x] population evidence still cannot authorise "not sure"
[x] a new policy version writes a new append-only decision over one set
[x] the visible row is unchanged — v1 IS the baseline
```

**THE RESTRUCTURE THE DIRECTIVE FORCED.** The selector rendered labels inside
itself, so a wording judgement was indistinguishable from a semantic one:
`RENDER_COLLISION` was attributed to the policy, and a locale that worded two
candidates differently would silently have changed what got SELECTED. Three
stages with three owners now:

```text
select    what each candidate MEANS      pure · versioned · never sees a label
present   what each candidate SAYS       renders, reports its collisions
record    what was offered and why not   the durable decision
```

Policies are **registered, not replaced** — re-registering a version raises,
because a version names one rule forever and redefining it would change what
past decisions claimed to be. The partition is checked inside `select()` as
well as in the aggregate: a new policy is exactly where losing a candidate
gets done, and catching it there names the RULE rather than the record.

`_says_the_same_thing` requires a shared serving basis. `1 piece` and `1 g`
can be numerically adjacent and mean nothing like each other; collapsing them
would delete a distinct option and file it as a duplicate.

The authority ladder falls out of persisted features rather than a special
case: history carries prior 0.55 at confidence 0.9, the ontology median 0.5 at
0.6. **No rule names a source.** The policy signature has nowhere to put a
food name, so a per-food branch cannot be written without changing the
contract — and a source scan holds the purity line, because a selector that
reached for a label would decide identically today and differently the first
time a locale worded two candidates apart.

**5.1 — exactness and a purity proof that cannot be fooled** *(review of
`2a47f40`)*. Two findings, both taken before the contract freeze rather than
carried to it:

* **P1 — the policy still computed in `float`.** Ranking, the near-duplicate
  ratio and the final ordering all crossed `float()`, which contradicts the
  determinism this module claims: two `Decimal` scores differing in the 18th
  place collapse to one binary float, and **generation order silently becomes
  the tie-breaker** — an accidental rule nobody wrote, reachable only by
  inputs nobody would think to test. All three are `Decimal` now, and `_near`
  compares by **multiplication rather than division** (`hi < lo * ratio`),
  because `hi / lo` is exact only to the ambient decimal context's precision —
  process-wide state any library can change, the same trap already found in
  conversion rounding. Ties are now broken by a **stated** rule: the
  earlier-generated candidate, which is the authority ladder's own order.
* **P2 — the purity ratchet was a string scan.** A scan catches an obvious
  call and misses an indirect one. The selector now runs against candidate and
  context **proxies that raise on any attribute outside the approved set**, so
  a future policy reaching for something new fails at the gate rather than
  quietly making decisions the persisted record cannot explain. The scan is
  kept as the cheap first line.

**5.2 — the exactness claim was still false.** *(review of `f40e472`)*
Avoiding division was not enough: `hi < lo * ratio` is still **Decimal
multiplication**, and every Decimal operation is governed by the ambient
context's precision and rounding. `prior * best` in `rank_of` had the
identical defect. Measured:

```text
lo=100.1  hi=125.1  ratio=1.25    exact product 125.125, so hi < it -> True
  prec=3 ROUND_DOWN -> 125  ->  False
  prec=3 ROUND_UP   -> 126  ->  True
```

The same comparison, two answers, decided by process-wide state no caller set.
Both now use **`Fraction`**, which has neither precision nor rounding: the
arithmetic is exact or it does not happen.

**The gate I wrote could not have caught it.** It used `100 x 1.25 = 125` — a
product no precision can round — so it would have passed however wrong the
arithmetic was. The replacement parameterises over operands that *do* round
(100.1/125.1, 80.7/100.8) across four precisions and five rounding modes, and
mutation-verified: restoring Decimal multiplication turns five gates red.

8110 pass on SQLite and 8110 on Postgres (21 skips), 30 selector gates.

**Standing lesson, third instance in this slice:** an instrument that cannot
express the failure it is aimed at reports success indistinguishably from
absence — see also `matched: 0`, the phantom-log detector, and SQLite's
foreign keys.

**Carried forward from the commit-4 review** *(non-blocking, for the
observability pass)*: a candidate-universe read failure currently degrades to
the same refusal as genuine insufficient evidence. The safety behaviour is
right; the two need separating in telemetry —
`estimate_refused:insufficient_evidence` vs
`estimate_refused:universe_unavailable`. And `candidates()` / `select()`
survive for offline tooling with production reachability structurally
prohibited; their deletion belongs with the D7 legacy sweep.

**5 — the selector.** Entity-agnostic, versioned, reproducible, observable,
mutation-tested, and replaceable by a learned ranker later. Every inclusion
and exclusion explainable from persisted features.

**6 — status: DONE** *(2026-08-06)*.
`tests/test_the_known_failures_replay_as_classes.py`, 32 gates. Chicken and
honey are one row each, not the subject.

```text
CLASS A  unsupported estimate    swept over ALL SEVEN serving bases x
                                 {population, this-user, this-product} x
                                 {history-rich, history-empty}
CLASS B  serving-basis mismatch  every cross-basis pair refused without a
                                 sourced conversion; with one, the arithmetic
                                 must land on the offered quantity; a
                                 volume-native food stays volume-native
```

**THE SWEEP FOUND A LIVE DEFECT, which is what a class sweep is for.** The
renderer pushed every candidate through `float(grams)`, so the first volume,
count, piece, package or fraction candidate to reach a real ask would have
raised `TypeError` on `float(None)` and **taken the whole turn down**. The
platform claimed to carry those bases since 3a.2 and could not render one. A
narrow chicken-and-honey regression pair would never have touched it.

Fixed by rendering non-mass candidates from their own `ServingExpression` —
which is what that field exists for — while mass still goes through
`_everyday_labels`, unchanged. Label collision is now compared **only within a
basis**, so `1 piece` and `150 g` can never merge on a coincidence of wording.

**Coverage ledger, asserted rather than assumed:** the generator still emits
mass only, because the portion ontology it reads is in grams. Everything above
proves the PLATFORM carries the other bases; production does not yet PRODUCE
them. A gate fails the day that changes, so someone decides deliberately
whether the ledger still describes reality — *"not produced" is not
"not supported", and neither is "not tested"*.

**6.1 — the matrix I claimed was broader than the matrix I wrote.** Eight
corrections from the review of `4cbffed`:

* **The cross-product was described, not implemented.** Population and
  this-user were swept across seven bases; product evidence was ONE case,
  history-empty ONE case, and the test named "population prior beside the
  user's record" built only the user record — so the thing its name promised
  was never tested. `MATRIX` is now generated: scope × basis × history, with
  `THIS_PRODUCT_QUANTITY` present on the three quantity-bearing bases and
  **excluded by rule** on the others rather than silently absent.
* **"Every cross-basis pair" was five of forty-two.** Generated now from all
  unequal pairs, twice: once proving no basis changes without an authority,
  once proving a conversion must START where the evidence looked.
* **Product evidence ran through `authorizes_assumption` directly.** It goes
  through the full ask → "not sure" → answer route now, against the matching
  variant, a foreign variant and no variant.
* **Labels were never asserted** — only stored expressions. So `3 tbsps`,
  `240 mls` and `2 ozs` sat in the row unremarked: `_expression_label`
  appended "s" whenever the amount was not one. **No rule can fix that**,
  because nothing in a canonical unit id says whether it is an abbreviation,
  and it does not survive a second language. Written forms are now a
  versioned table in `core/unit_registry` (`UNIT_DISPLAY_VERSION`), and the
  rendered labels are asserted across every basis. Mass still goes through
  `_everyday_labels`, unchanged.
* **One assertion was vacuous** — `... and result.patch` inside an `any()`
  after `result.patch` was established as `None`. It could never be true.

8279 pass on SQLite and 8279 on Postgres (25 skips), 159 class gates.

**Carried to the step-8 freeze** *(P2 from the 5.2 review)*: the purity proxy
returns real evidence objects, so a future policy could branch on
`evidence[0].source_type` without tripping it. Tighten to per-evidence proxies
permitting only `confidence`, and narrow the approved candidate and context
fields to those actually read.

**6 — replay the two failures as CLASSES, not as chicken and honey.**
*Unsupported estimate*: weak evidence + "not sure" → no automatic commit.
*Serving-basis mismatch*: volume evidence or volume-based history → volume
candidates preserved, canonical mass conversion stays server-side. Also:
piece-native · count-native · package-native · fraction-native · history-rich
· history-empty · conversion available · conversion unavailable.

**6.2 — word units inflect; symbol units do not.** The registry marked every
volume alias invariant, so an offered expression stating `cup` or
`tablespoon` would have rendered `2 cup` and `3 tablespoon`. Symbols
(`ml · g · tbsp · oz · lb`) and words (`cup/cups · tablespoon/tablespoons ·
ounce/ounces`) are registered separately now, both spellings of a word unit
pointing at one pair so the id a producer happens to use cannot change how the
row reads.

**7 — status: DONE** *(2026-08-06)*.
`tests/test_the_whole_slice_holds_together.py`.

The three corpora that came before each prove one half of the slice, and all
three **predate the durable universe** — not one joins a committed meal back
to the candidate row that justified it. That join is what step 7 closes:

```text
raw message -> operation -> candidate set -> decision -> presented option
            -> tap (by id) -> patch -> nutrition -> card + totals -> telemetry
```

Covered: real Postgres · real enrichment · raw-message routing · restart
between turns · stale and foreign answers · duplicate transport and duplicate
taps · unrelated meals while awaiting · exact candidate, decision, option,
nutrition and telemetry records · and `why_not()` answering for **every**
candidate on a real production turn, never "unknown".

**TWO INSTRUMENT DEFECTS, BOTH SELF-CAUGHT.** The engine reporter read
`db.database.engine` — the module-level engine the harness does not bind to —
and printed `sqlite` with `TEST_POSTGRES_URL` set, so *"this ran on Postgres"*
would have been false while the reporter agreed. It reads the bound engine
now, asserts the binding, and **fails if the variable is set and Postgres was
not used**. The restart test disposed that same wrong engine, simulating
nothing; it drops the real pool on Postgres and re-materialises from rows on
SQLite, where disposing would destroy the database.

**7.1 — the proof was narrower than its headline.** Six corrections:

* **The chain said "tap by id" and the test answered with prose.** `say(label)`
  is LABEL SELECTION — a different route, a different modality — so the one
  path the iOS client will actually use was untested by the test that claimed
  it. It goes through `option_id` now, and asserts the recorded modality is
  `option_id` rather than something else.
* **Real enrichment was never in the same sequence.** The candidate chain was
  proven against a fixed density; live USDA was proven by a separate suite
  that knows nothing about candidates. Neither showed a candidate's own grams,
  priced by the real ladder, producing the row and the card. Now joined —
  **verified running on Postgres with a live key**, and the gate PRINTS
  whether it ran, because a skip reported as a pass is the same instrument
  problem as everything else here.
* **Card and daily totals were in the headline and not in the test.** Both
  asserted now, against the row: `entry_id`, calories, protein, the
  `estimated` flag, and the sentence beside the card.
* **Stale and foreign were conflated** — one case sent a nonsense option id, a
  field id in the wrong parameter, and the CURRENT revision. Three separate
  gates now: a valid option at a stale revision (and the same option at the
  right one, so the refusal is the revision talking), an option never offered,
  and an answer to a foreign field.
* **Duplicate transport and duplicate taps were one test using labels.** Three
  now: the same transport id redelivered, the same option under two transport
  ids, and the label route separately.
* **Provenance attribution** — `USER_SELECTED` on the patch, the telemetry
  source matched against persisted evidence rows, and a plain tap proven to
  name NO policy version, because stamping every row would make that field
  mean "some policy ran".

The unrelated-meal gate also had its claim corrected: an unrelated message is
**held, not logged** — it repairs rather than answering — so "the meal is not
lost" means the board stays empty, the question survives, and the lane frees
afterwards. Asserting the meal had been logged was asserting a design the
system does not have.

**7.2 — two of these were product defects, not test gaps.**

* **THE UNRELATED MEAL WAS WORSE THAN LOST.** Probed live: *"I had some salmon
  too"* while chicken was awaiting drew **"How much was it? A rough amount is
  fine."** — no food named. A user reasonably reads that as a question about
  the salmon, answers it, and the amount prices the **chicken**. The pronoun
  was doing work no pronoun can do. The re-ask now names the food and states
  that anything else mentioned is not logged yet. **The deferred report is
  still not persisted** — that is a real open decision, recorded below, not
  something to call "held".
* **The live-enrichment gate could pass on stale nutrition.** `0.8 ≤ cal/g ≤
  3.0` admits the ask-time 280 cal for any quantity between ~94 g and 350 g,
  so it could not tell repricing from a number that never moved. Now the
  ask-time figure is **seeded at 9999** — impossible for any real food — so a
  stale value is falsifiable without knowing a live density. *(Proportionality
  across two answers was the first attempt and does not work: a second ask for
  the same food replays the settled operation rather than opening a new one.)*
* Source attribution is scoped to the **tapped candidate's own evidence**, not
  matched against the whole universe.
* Transport redelivery goes through **`run_chat_turn` with a repeated
  `msg_id`**, not two direct calls to the answer layer — the dedup that sits
  in front is the layer a real retry hits first.
* The "stale revision" case was a FUTURE revision. In B-1 the revision moves
  in exactly one place — `settle()` — so a stale-but-valid revision on an OPEN
  operation is **not reachable today**. That reachability is now asserted, so
  B-1.5's dependent re-asks will fail this gate rather than inherit a comment;
  and the genuinely stale post-settlement tap is proven to replay.

**OPEN DECISION, BEFORE USER TESTING** — a food reported while a question is
open is refused, not stored. The user is now told, but the report itself is
gone and must be re-sent. Persisting and replaying deferred reports is the
alternative. **Do not describe the current behaviour as "held".**

Mutation-verified: making `save()` persist nothing turns six of seven red.

8319 pass on SQLite and 8319 on Postgres, live-enrichment join included.

**8 — status: PARTIAL. NOT CLOSED.** *(2026-08-06)* — stated plainly because
the standing failure in this slice has been headlines running ahead of gates,
and a contract freeze institutionalises whatever it gets wrong.

**Landed:**

```text
[x] typed RepairReason      no_amount_in_answer · unusable_amount ·
                            estimate_unsupported · universe_unavailable
[x] typed RefusalReason     unknown_option · foreign_field ·
                            revision_mismatch · option_without_patch
[x] repair_reason persisted           b1obs004, indexed for GROUP BY
[x] outage split from evidence        universe_unavailable is its own reason
[x] wire envelope frozen              24 gates, every persisted enum
[x] golden JSON fixtures              13 gates: old bytes decode, round-trip
                                      exact, additive changes compatible,
                                      unknown versions and enums fail shut
[x] selector purity per EVIDENCE      only `confidence`; context only
                                      `maximum_options`
[x] unrelated-report copy contract    names the food, states it is not
                                      logged, PROVES it claims nothing about
                                      saving or queueing
```

**NOT landed, and step 8 does not close until they are:**

```text
[ ] client_message_id in the answer envelope      needs the API surface
[ ] `replay` and `expired` as first-class outcomes  today `replay` is a
                                                  reason on an APPLIED turn
                                                  and expiry is a property of
                                                  the row, not an outcome —
                                                  changing that touches every
                                                  consumer and is the kind of
                                                  edit a freeze exists to
                                                  make deliberate
[ ] telemetry for the RESEND after a refusal      round_index counts attempts
                                                  on one operation; a resend
                                                  opens a NEW one, so nothing
                                                  currently joins them
[ ] CI attached and mandatory                     Actions outage; every number
                                                  in this document remains
                                                  author-reported
```

**ONE REQUESTED ITEM IS REFUSED, WITH REASONING.**
`unrelated_report_while_awaiting` is asked for in the reason taxonomy and is
**not implemented, deliberately**. The answer turn runs BEFORE the interpreter
and receives only the raw message — that ordering is how `"6 oz"` stopped
becoming a second meal. It therefore cannot distinguish *"I had some salmon
too"* from *"it was pretty good"*; doing so needs the interpreter, and
reaching for it there reintroduces exactly the coupling C10 removes. Stamping
the reason anyway would record knowledge the turn does not have.

The user-facing requirement is met without the claim: the re-ask names the
active food and states that anything else mentioned is not logged. A gate
asserts the reason is absent, so this stays a decision rather than an
oversight.

**8.1 — the reason contract, completed.** *(review of `a01950c`)*

* **The overclaim, again, and in the freeze commit itself.** That message said
  *"typed RepairReason and RefusalReason, persisted and indexed"*. Only
  `repair_reason` was. `RefusalReason` existed on the in-memory result and
  stopped at the answer function — so the reason a CLIENT has to branch on
  never reached storage or the wire. Now carried through `AnswerTurn` →
  `CanonicalResponseFacts` → `B1AnswerObservation`, with `b1obs005`
  **forward-only** and an index. A gate asserts it reaches the facts, named
  after the overclaim so it cannot recur silently.
* **`universe_unavailable` was inferred from container shape.** `not
  candidates` conflates a legitimate empty, an operation older than the
  universe, and a read that failed — so a future legitimate empty would be
  filed as an outage. The loader now DECLARES a typed
  `UniverseDisposition(loaded · unavailable · not_applicable)` and `_estimate`
  copies it.
* **`UNUSABLE_AMOUNT` was frozen with no producer.** A planned behaviour in a
  vocabulary meant to describe actual ones — and a value analysis would look
  for and never find, indistinguishable from one that simply never occurs.
  **Removed.** A gate now scans production source and fails on any frozen
  reason nothing can produce; mutation-verified by adding a dead member.
* Reasons are asserted **empty on the outcomes they do not describe**, so a
  field means "this is why" rather than "something happened".

**8364 pass on SQLite and 8364 on Postgres**, live-enrichment join running.

**8.2 — status: DONE.** *(2026-08-06)*

**`REPLAY` is a first-class outcome.** `APPLIED` with `reason="replay"` was an
unstable contract: an authoritative result handed back with nothing written
was indistinguishable from a fresh mutation, so a client could not tell
whether to animate a row and "successful applications" silently counted
repeats. Split into `turn.applied` (authoritative result, new OR replayed —
what every existing caller means) and `turn.mutated` (a new meal was written —
what the count means). Three gates caught the addition, including one written
earlier for exactly this: *"the outcome set changed — re-check which of them
actually ask a question."*

**`POST /api/v1/chat/answer`, Class A, through `mutation_turn`.** Built,
reverted once for non-compliance, and rebuilt properly rather than made to
pass by mentioning the right symbols:

```text
canonical turn id   make_turn_id(channel, client_key, user_id, dedup)
request trace       RequestTrace around the whole turn
durable claim       claim=True; a retry returns the ORIGINAL result and never
                    reaches settlement again
concurrency proof   two deliveries via asyncio.gather through the real ASGI
                    app: one 200, the other 200-replay or 409-conflict,
                    and EXACTLY ONE meal
ledger event        settle() -> write_canonical_meal, in the row's own
                    transaction
```

**ONE IDENTITY, NOT TWO.** `client_message_id` becomes the turn id the claim
is taken under **and** the `source_turn_id` settlement dedupes on. Two dedup
mechanisms would be two answers to "has this already happened", and they would
eventually disagree.

`b1_answer_turn.handle` was added to the `ledger_event` markers under the
reasoning already documented for `execute_tool_calls`: *a route that delegates
owns the turn's identity rather than the write*, so reading only the handler
reports it as leaving no history when it leaves the strongest kind.

**Expiry is modelled explicitly, and is NOT an answer outcome.**
`OwnershipDisposition(holding · expired · settled)`, with
`claims_unaddressed_messages` naming the one thing expiry changes. An expired
operation still accepts an answer ADDRESSED to it — someone replying late is
still replying — so the user never receives "expired" as the result of
answering. A gate asserts `Outcome.EXPIRED` does not exist.

**Golden request/response fixtures frozen.** The five-field envelope, all
required; the response envelope proven to leak no semantics; the committed
request fixture still validating against the current model.

**8.3 — a replay returned the SHAPE of the original, not its CONTENT.**

The commit said *"a retry returns the ORIGINAL result"*. It returned
`{outcome, entry_id}` with **empty bubbles and no card** — so a phone that
lost the HTTP response after the meal committed got back an id and nothing to
show, and would have to reconstruct the confirmation itself or re-fetch. That
is the client-side inference the frozen boundary exists to prevent.

`IdempotencyRecord` stores a durable IDENTIFIER, not a response body, so the
fix is the second option: `facts_from_committed_row()` recovers the result
from the thing that IS authoritative — the row — and re-renders it through
**the same `copy_for`/`card_for`** the first reply used. `_render_answer()` is
now the one renderer for both, so a fresh result and a replayed one cannot say
different things about one row.

**Nothing there recomputes semantics**: no quantity is parsed, no candidate
selected, no pricing run. It reads what was written and says it again.

The claim replay reports the **original outcome** (`applied`) with
`idempotent_replay: true` — that flag is how a client knows it is a
redelivery. `Outcome.REPLAY` still means something different: a NEW request
finding the operation already settled.

**The crash window is tested, not reasoned about.** The meal commits first and
the claim completes in a second transaction; the shared contract documents
that a process dying between them leaves durable work behind an incomplete
claim, and nothing proved what a retry then does. It now kills `complete()`
after the commit, verifies the meal IS durable, retries, and proves **no
second meal** — safety that comes not from the claim, which never completed,
but from settlement finding the operation already settled under the same turn
id.

Mutation-verified: restoring the empty-shell replay turns two gates red.

**8389 pass on SQLite and 8389 on Postgres**, live-enrichment join running.

**CI — CONFIGURED, NOT YET OBSERVED BY ME.** `.github/workflows/ci.yml` runs
on every push to `main` and every PR, against a real Postgres service. This
push triggers it. I cannot read the result: `gh` is not installed in this
environment and I cannot authenticate to the API, so **whether a check
attaches to this SHA is something you can see and I cannot.** Until you
confirm a green attached run, every number in this document remains
author-reported execution evidence.

Resend-to-refusal attribution stays **deferred to B-1b.3** as advised.
`unrelated_report_while_awaiting` stays **unimplemented**, with a gate
asserting its absence.

**7–8** — run the sequence corpus through the real candidate pipeline *and*
real enrichment together, then freeze the wire contract, the semantic
candidate contract and the decision telemetry. **Client work begins only
after that freeze.**

**B-1b.0 — THE INTERACTION HAD NO WIRE CHANNEL.** *(2026-08-06, found by the
iOS integration on its first hour — which is what integrations are for.)*

`POST /chat/answer` requires `operation_id`, `revision`, `field_id` and
`option_id`. **Nothing on the wire could tell a client what any of them
were.** Probed live rather than reasoned about:

```text
serialize_response keys:  v bubbles reaction effect buttons link cards
                          achievement program_updated reasoning
buttons:                  [{label: "1 chicken breast",
                            value: "1 chicken breast"}]   <- a LABEL as a value
pending_clarifications:   the LEGACY question shape, no ids
interaction:              did not exist
```

The interaction was built, persisted and rendered into the SENTENCE — correct
for Telegram, where the sentence is the whole interface — and a native client
had only `buttons`, whose `value` is a label travelling back as semantics: the
round-trip C11 exists to forbid. The endpoint was unanswerable by the client it
was built for.

`Response.interaction` is now on the wire, **additive and optional**: absent
unless a canonical operation owns the turn, so its presence IS the signal that
a structured answer is possible, and older clients are unaffected.

**TWO THINGS THAT ARE NOT DEFECTS, checked before assuming they were:**

* **iOS is deliberately absent from `_CHANNEL_CAPABILITY`.** B-1 declines every
  iOS turn with `client_incapable` BY DESIGN — *"naming it here before then
  would be a capability claim about software that does not exist."* Adding
  `"ios": ID_ADDRESSED` is the LAST step of B-1b, after a build renders
  fields and submits ids. Gates driven through `/api/v1/chat` therefore skip
  on a designed exclusion and prove nothing, so they drive the capable channel
  instead — the wire contract is channel-agnostic.
* **`field_id` rides the FIELD on the wire and the OPTION in storage.** Both
  deliberate: the field computes it as a property, so only options survive
  serialization. A client reads it from the field.

**9 — status: BUILT AND ON DEVICE** *(2026-08-06, `arnie-ios@48cb626`)*.

```text
ClarificationInteraction   ids and labels; no patch, candidate or evidence
ChatResponse.interaction   always present, null on most turns; NON-NULL is
                           the signal a structured answer is possible
answerClarification()      POST /chat/answer, four ids + a stable key
```

**One key per tap, reused on retry** — the server makes it the turn identity
its claim AND its settlement key on, so a resend resolves to the original
commit. Taps are once-only while one is in flight; an unknown outcome fails
safe to "still open" so a newer server cannot make an older build claim a meal
it never wrote; a network failure keeps the question open and the key intact.

**`"ios": ID_ADDRESSED` is now in `_CHANNEL_CAPABILITY`** — added when the
build that honours it existed and not before. Three gates pinned the old state
and had to be updated deliberately, which is what they were for. Exactly one
channel is ID-addressed, and a gate says so.

### B-1b — PROVEN END TO END IN PRODUCTION ON iOS *(2026-08-07)*

The first structured clarifications ever answered by tapping. Read from the
production database, not from a reply:

```text
candidate_sets        3 written, user 26, domain=food, gen b1_quantity_gen_v1
decisions             3, ALL surface=id_addressed   <- the structured path
answers               2 applied via modality=option_id  (entries 2887, 2890)
                      1 applied via text/free_text on telegram (entry 2875)
clarification_answer  257 ms   {claim 34, write 223}
```

**Every exclusion reason fired on a real turn, on day one:**

```text
cand_9ad7f3e4041   semantic_duplicate
cand_0107453db45   selection_cap
cand_0784b20d111   render_collision
```

That is the whole point of the durable universe, working in production: for a
candidate the user did not see, the record says which of the three happened —
never "unknown". Evidence sources so far: **9 ontology, 1 user_history**.

**TWO FINDINGS FROM THE FIRST SESSION, neither an architecture defect.**

**1 — The labels read `118g` and `276g`, not `4 oz` and `10 oz`.**
`_everyday_labels` did not recognise the food and fell back to grams. The
mass path is unchanged and correct; the ontology simply has no everyday
rendering for this item. A product-quality item for the candidate-quality
pass, not a contract problem.

**2 — iOS feels slower than Telegram, and it is not this architecture.**
Measured on the same user (26), same account:

```text
              turns   avg total    LLM    tools   framework
  ios           367     8672 ms   7303     1190         190
  telegram       59     6390 ms   5649      185         556
```

Framework overhead on iOS is **15–154 ms** on 9 of the last 10 turns — LOWER
than Telegram's. The tap is 257 ms. **The latency is the model writing more**:
iOS replies average 223 characters against Telegram's 95, because
`IOS_STYLE` + `NATIVE_CARDS` + `IOS_FORMAT_ANCHOR` (~3,200 tokens Telegram
never sees) teach rich markdown, paragraph structure and card driving. Input
caching is already on with a 1h TTL, so those tokens are cheap to send; the
cost is that Arnie then WRITES 2.3x more.

Trimming that is a PRODUCT decision — shorter replies, less markdown, and the
card layer loses its instructions — so it is recorded here rather than done
silently. **Open: does iOS keep the rich voice or trade some of it for speed?**

**9 — the client** receives and returns identifiers and labels only, and never
generates options, chooses units, converts quantities, infers meaning from
labels, ranks candidates, or recreates missing semantics.

**10 — promotion and closure**, deletion included. B-1 is complete only after
the legacy question producer, answer reconstruction, overlapping pending
ownership and prose-derived options are deleted and C8/C9 lowered.

### Permanent engineering constraints

Standing rules, added 2026-08-06. They bind every slice, not just this one.

> **No semantic decision may depend on a food-name branch, a broad regex
> classifier, an arbitrary threshold, a manually curated option tier, or an
> unsupported conversion.**
>
> **Deterministic parsers are restricted to formal syntax**: quantities,
> registered units, identifiers, transport metadata, narrowly defined
> commands.
>
> **Every candidate, estimate, conversion, assumption and selection decision
> carries typed evidence, provenance, confidence and policy version.**
>
> **When evidence is insufficient the canonical state remains unresolved.**
> The system does not manufacture certainty to complete a turn.
>
> **No new domain introduces an alternate pending owner, answer interpreter,
> mutation path or presentation authority.**

### The remaining programme, in dependency order

Recorded so nothing is lost and the order is not re-litigated per slice.

```text
B-1.9  candidate-system correction      <- current, at 3b (persistence)
B-1    promote + DELETE predecessor + lower ratchets
B-1.5  quantity + preparation_category  (largest exclusion class in production)
B-1.6  conditional dependencies         generic field-activation engine,
                                        never `if fried then ask oil`
B-1.7  accuracy policy over ONE topology — may change ask/assume/defer/
                                        disclose, never storage or writers
B-1.8  answer classification and repair — option id -> narrow field parser ->
                                        pending-aware constrained classifier
                                        -> targeted repair
B-2    multi-item: many events, grouped fields, partial answers, neighbour
       protection, ONE revision, ONE meal commit
B-2.5  SelectEntity · SelectProductVariant · SetPackageSize ·
       SetConsumedFraction
B-2.6  sauces and additions — only nutritionally material fields
B-2.7  generalized option generator — ONLY after several real field families
       exist. Not pulled forward because quantity needs better evidence.
B-2.8  product voice — QuestionIntent + CanonicalResponseFacts only
B-3    PendingOperation as SOLE durable pending owner; delete writes to
       pending_questions, deferred_calls, staged blobs, loose payloads
C-1    every remaining conversational food writer through the coordinator
C-2    canonical corrections (quantity, identity, preparation, additions,
       meal type, date, removal) as operation revisions
C-3    canonical undo by stable committed event id — no "last meal" heuristic
C-4    ONE PresentationSnapshot for chat, cards, totals, timeline, coach feed,
       notifications, widgets, API
C-5/6  one resolver coordinator, one ambiguity engine, policy separate
C-7    food production-readiness gate — food is NOT half-migrated when
       workouts begin
D      generalize under the RULE OF TWO only: shared OperationRequest /
       OperationResult / outbox, domain payloads stay typed
E/F    workouts — structured first, then conversational, on the SAME spine.
       No separate workout pending or chip architecture.
G      weight · hydration · supplements · medication · vitals, same spine
```

**Directive 1 restated, because it is the whole method:** every capability runs
`measure → define semantic field → add typed evidence → build canonical
producer → persist PendingOperation → apply typed patch → commit canonically →
produce committed facts → validate in production → promote → delete
predecessor → lower ratchet`. **No slice skips deletion.**

### B-1 is now a PROMOTION project, not an implementation project

**Augmented 2026-08-06 from team review.** Every commit until now answered
*"can this architecture work?"*. From here they answer *"can we trust it
enough to delete the old one?"* — a different question, and the roadmap says
so rather than leaving the shift implicit.

```text
lifecycle implementation      COMPLETE
persistence                   COMPLETE
settlement                    COMPLETE
presentation boundary         COMPLETE
evidence harness              COMPLETE
Postgres engine validation    COMPLETE
logic matrix                  COMPLETE
product evidence              IN PROGRESS
structured client             NOT STARTED
promotion                     NOT STARTED
legacy deletion               NOT STARTED
```

**"Implementation complete" is not "slice complete."** The last three lines are
the slice.

#### Track A — production evidence. Finishes first.

> **A1 — THE ARCHITECTURE IS FROZEN.** No new abstractions, no new ownership
> concepts, no shared framework work. Bug fixes only. Every generalisation is
> cheaper after the evidence and irreversible before it.

| | | |
|---|---|---|
| **A1** | freeze | in force from 2026-08-06 |
| **A2** | finish instrumentation — every clarification measurable | ✅ closed below |
| **A3** | internal observation window — observe, do **not** optimise | running |
| **A4** | real-enrichment validation **in production**, not another synthetic test | pending traffic |

**A2's eleven signals, and where each lives.** Nothing else is built until
every clarification can be analysed end to end.

```text
shown              pending_operations                      (durable)
accepted           b1_answer_observations.modality         chip | label
free-text override b1_answer_observations.selected_source  free_text
repair             b1_answer_observations.outcome
estimate           modality=command + MODE_DEFAULT
cancellation       outcome=cancelled
abandonment        pending_operations.status = expired     <- was UNANALYSABLE
latency            b1_answer_observations.latency_ms
correction window  b1_correction_observations
candidate source   selected_source + offered mix
copy version       question_version
```

**Abandonment was the hole, and it was structural.** The funnel table holds
ANSWERS, and a question the user walked away from never produced one — so
every rate computed from it silently conditions on *"they replied"*, and
completion % was not derivable at all. It is the loudest possible statement
that a question was not worth asking, and an answers-only dashboard is blind
to it by construction. `scripts/b1_option_scorecard.py` now reads the
operation table for a `shown → committed / cancelled / abandoned` lifecycle
and reports completion against questions **asked**, never against questions
answered — the second number is the flattering one.

#### Track B — product refinement. Only after the evidence exists.

```text
B1  clarification wording    version every change; copy is an experiment;
                             never overwrite a baseline
B2  candidate ranking        history weighting, ontology ranking, portion
                             generation — telemetry decides, not taste
B3  voice harmonization      eliminate the two-Arnie-voices seam only.
                             NOT adaptive coaching. Renders
                             CanonicalResponseFacts, never the commit result.
```

#### Then, in order

```text
B-1d structured client   -> after candidate quality is understood, so the UX
                            is not hard-coded around weak suggestions
promotion                -> internal -> 1% -> 5% -> 25% -> 100%, evidence-driven
deletion                 -> legacy quantity clarification, legacy pending
                            ownership, legacy answer routing, legacy
                            presentation for this slice; then lower ratchets
```

> **DO NOT START B-2 — or preparation, added fat, multi-item, or workout
> clarification — until B-1 is promoted AND its predecessor is deleted.**
>
> The temptation will be to reuse the new architecture immediately *because it
> is working*. That is exactly how a second generation of legacy paths gets
> created, and this migration exists because it happened once already. The
> order is **prove → promote → delete → reuse**, and only the last step is
> allowed to be fun.

### Closing B-1 — the production-evidence ladder

**Augmented 2026-08-06 from team review.** The earlier plan made organic
traffic the sole sequencing gate: observe, wait, then build. That was an
overcorrection. Synthetic *acceptance* data would measure our model of the user
rather than the user — true, and still true — but low traffic must change the
**label and confidence** of evidence, not suspend the migration.

| | step | exit condition |
|---|---|---|
| **B-1a** | measurement wording | ✅ versioned `b1_quantity_q2` |
| **B-1b.1** | deterministic system-validation matrix | ✅ **GREEN** — Postgres-backed, real enrichment exercised |
| **B-1b.2** | production-sequence corpus | green under Postgres and real pricing |
| **B-1b.3** | instrumented human simulation | internal panel shows the interaction is understandable |
| **B-1b.4** | natural-traffic confirmation | continuous; confirms rather than gates |
| **B-1c** | safety observability | ✅ coverage and precision proven |
| **B-1d** | structured iOS client | **may start after B-1b.1 + B-1b.2** — does not wait for organic volume |
| **B-1e** | promote → delete predecessor → lower ratchets | after B-1d proof |

**B-1d is deliberately not gated on B-1b.3 being statistically significant.**
Start it once the system matrix and sequence corpus are green and no structural
redesign of the candidate contract is known — then run B-1b.3 *through the iOS
client*, because the structured `option_id` path is the actual intended
interaction and testing it in prose is testing something else.

### Evidence classes — what a given source may legitimately prove

| class | what it can prove | valid source |
|---|---|---|
| **System correctness** | ownership, persistence, settlement, idempotency, replay, pricing, card/totals agreement, telemetry | automated production-like scenarios |
| **Candidate quality** | source availability, option spread, degenerate forks, history recall, ontology coverage, ranking | real account history + deterministic dry runs |
| **Interaction usability** | whether the wording and choices are understandable; whether people know they can type an amount or say "not sure" | structured internal human testing |
| **Natural preference** | true acceptance, free-text preference, abandonment, correction over time | **real production usage only** |

**No simulated result may be reported as natural preference.** Absence of
organic traffic changes the label, never the sequence.

### B-1b.1 — the deterministic system-validation matrix

Canonical path, production-like Postgres, **real enrichment enabled**. Every
axis crossed:

```text
candidate source   history · calibrated ontology · fallback · none
answer route       exact label · typed offered · typed NOT offered ·
                   "not sure"/MODE_DEFAULT · malformed -> REPAIR · cancel ·
                   stale · foreign · duplicate delivery
quantity basis     grams · ounces · mass answer replacing non-mass ask-time
                   data · conflicting ask-time macros removed before pricing
outcome            commit · repair · cancel · refuse · internal failure · replay
```

Each scenario verifies **database state, never reply text**: exactly one
operation · expected revision · expected terminal state · 0 or 1 meal commit ·
0 or 1 food row · resolved quantity and provenance · real `analyze()` result ·
card and totals agreement · expected telemetry · duplicate execution
impossible · health detector executed · no legacy fallback after ownership.

**Status 2026-08-06.** `tests/test_b1b1_system_matrix.py`, 17 scenarios.

* **Postgres backing — CLOSED.** The harness fixture binds the real engine in
  a private per-test schema when `TEST_POSTGRES_URL` is set, via
  `make_engine` (the codebase refuses an unpinned Postgres engine by
  construction). The file **asserts its own dialect**: without the variable it
  passes on SQLite and skips with a message saying that is not B-1b.1
  evidence; with it, the dialect must genuinely be `postgresql` in an isolated
  schema. Verified directly — engine `postgresql`, `search_path`
  `harness_…`, real rows written.
* **Real enrichment — CLOSED.** `tests/test_b1b1_real_enrichment.py` runs the
  canonical path against the live USDA/Open Food Facts ladder, gated on
  `USDA_API_KEY` so its absence SKIPS loudly rather than weakening the matrix
  quietly. Verified by counting calls: 8 real results for "Chicken breast",
  committing **165.0 cal at 100 g** — the correct density, matching production
  entry 2860 exactly.

  **And the ladder's refusal machinery is what earns that.** USDA's top hit
  for "chicken breast" is *"Chicken breast tenders, breaded, uncooked"* at 263
  cal/100 g; for "white rice" it is rice FLOUR at 359; for "salmon" it is fish
  OIL at 902. All three carry no confident match, the ladder declines to seat
  them, and the committed number is right anyway. Raw lookup quality is poor;
  the authority ladder is the reason that does not reach a user.

  Assertions there are **relational, never absolute** — pinning a calorie
  number would encode today's USDA index and fail on a data refresh for
  reasons unrelated to B-1. What must hold whichever row wins is that the
  answered quantity drives the result.

> **Reporting rule, because these were conflated once.** State the backing
> store, not the run flag. *"Suite run under Postgres; matrix scenarios
> Postgres-backed"* is a different sentence from *"7,914 pass on Postgres"* —
> the second says only that the run had the variable set, and was true for
> months while every one of these scenarios executed on SQLite.

Found while closing it: `DROP SCHEMA … CASCADE` at teardown deadlocks against
the same engine's pooled connections (`asyncpg.DeadlockDetectedError`). The
pool is disposed first and the drop runs on a throwaway connection.

### B-1b.2 — the production-sequence corpus

Naturally occurring *sequences*, not isolated states:

```text
clarification -> answer -> unrelated new meal
clarification -> answer -> duplicate answer
clarification -> delayed answer after another operation opens
clarification -> cancel -> new meal
clarification -> repair -> valid answer
clarification -> internal failure -> retry
clarification -> deploy/restart -> answer
clarification -> duplicate webhook delivery
clarification -> prior meal referenced in the reply -> new question
clarification -> correction within ten minutes
```

Through real routing, real persistence, **fresh database sessions between
turns**, real pricing, production-equivalent platform capabilities, the
expected deployment configuration, and durable telemetry queries.

> **Simulate sequences, not desired outcomes.** A scenario must begin from raw
> user messages and production-shaped account history and pass through real
> routing, candidate generation, persistence, answer application, enrichment
> and commit. It may control the user's next reply; it may **not** directly
> construct the internal state it exists to validate, unless the test
> explicitly targets that isolated contract.
>
> Every defect this slice produced that shipped green came from violating this:
> a fixture built the state it then asserted, so the assertion could not fail.

### B-1b.3 — instrumented human simulation

Preference cannot be inferred from synthetic answers, so recruit rather than
wait. 5–10 people · 10–15 sessions each · 50–150 interactions, mixing familiar
foods, foods with history, foods with no ontology row, vague portions, branded
foods that B-1 excludes, and deliberately awkward quantities. Real product
surface; participants answer naturally and are **not told which option is
expected**.

Capture: selected option · typed amount · "Other" · "not sure" · repair ·
abandonment · time to answer · immediate correction · qualitative reason after
selected sessions.

This is **usability** evidence, not retention evidence. It is sufficient to
validate the interaction contract and to begin B-1d.

### B-1b.4 — natural-traffic confirmation

A confirmation stream, not the gate. Confirms: no behaviour absent from the
corpus · real users understand the wording · correction and abandonment are not
materially worse · no channel-specific issue · candidate-source distribution
resembles the tested corpus. **Low sample size is reported explicitly** and
blocks nothing unless it reveals a severe contradiction.

### B-1 promotion gates

Promotion means deleting the legacy quantity path. Blocked until all hold.
**No arbitrary organic sample count is required** unless traffic later becomes
sufficient to justify one.

```text
[ ] production-like system matrix green            (B-1b.1)
[ ] production-sequence corpus green               (B-1b.2)
[ ] real analyze() pricing verified through the canonical path
[ ] internal human simulation shows the interaction is understandable (B-1b.3)
[ ] no known severe candidate-generation defect remains
[ ] structured iOS option_id path production-proven (B-1d)
[ ] natural traffic, where available, shows no contradictory severe signal
[ ] B-1c detector coverage and precision remain live
[ ] 100% of eligible turns canonical under the rollout cohort
[ ] rollback tested
```

### Coverage ledger — "not seen organically" is not "not tested"

Kept current. Four columns per required behaviour, so a gap in one column
cannot masquerade as a gap in the system.

| behaviour | automated sequence | internal human | organic | status |
|---|---|---|---|---|
| history option offered | ✅ matrix (PG) + control | pending | none yet | **sufficient** |
| typed non-offered amount | ✅ matrix (PG) | pending | 2 observations | **sufficient** |
| real `analyze()` pricing | estimate lane only | pending | ✅ density lane (2860) | partial — needs USDA key |
| duplicate delivery | ✅ harness | unnecessary | ✅ proven | **sufficient** |
| settled op declines new meal | ✅ harness | pending | ✅ proven | **sufficient** |
| expired op declines new meal | ✅ harness | pending | none yet | **sufficient** |
| stale revision / foreign field | ✅ harness | pending | none yet | **sufficient** |
| estimate / "not sure" route | ✅ matrix (PG) | pending | 1 observation | **sufficient** |
| abandonment preference | not simulable | pending B-1b.3 | none yet | **provisional** |
| long-term correction rate | not simulable | limited | none yet | **unresolved** |

### B-1b finding 1 — the `piece` fallback produces unusable option sets

**Recorded 2026-08-06. Evidence, not opinion. Deferred, not fixed.**

Measured with `scripts/b1_option_dryrun.py` over the 60 most-logged real foods
of a real account — real foods, real history, the deterministic producer, and
**no synthetic answers**. The correlation is total:

```text
ontology specificity   foods   degenerate   share
category                 33         0         0%
fallback                 18         0         0%
piece                     9         6        67%   <- no ontology row
```

A "degenerate" set is two options 2× or more apart with nothing between —
not a choice, a fork. Every one of them is `specificity='piece'`, meaning the
portion ontology has **no row for that food** and falls back to a generic
piece bracket:

```text
39x  Barebells Salty Peanut Protein Bar   ['2 oz', '5 oz']    2.6x
14x  Banana                               ['98g', '276g']     2.8x
 3x  Grilled chicken breast               ['5 oz', '16 oz']   3.3x
```

**It reproduces the production observation exactly.** Live, a chicken-breast
question offered `6 oz` / `16 oz`; the dry run gives `5 oz` / `16 oz` for the
same food. And under the standing bias-high rule a "not sure" answer then takes
the upper of two, which committed **435 g of chicken breast, 718 cal** on
2026-08-06. The estimate logic is correct; it was handed a fork.

Two further signals inside the same data:

* **Countable foods are bracketed by mass.** A protein bar offered as "2 oz or
  5 oz" is not a question anyone answers. Whether B-1 would ask at all is a
  separate matter — see the caveat below.
* **The three-anchor set collapses to two** in `_collapse_by_label` when the
  lower and median render alike, so the middle value disappears precisely
  where the bracket is widest.

**Scope, and why it is deferred.** Wording ("say it more like a person") is
B-2.8. This is not wording — it is *candidate generation*, which B-1b exists
to evaluate and B-1.5+ inherits. Fixing it now would be optimizing a generator
before the window has finished saying what is wrong with it. It is recorded so
promotion cannot happen while it is unexamined.

**The instrument's honest limit.** The dry run **cannot apply `is_eligible`** —
that needs a decision with staged items, which cannot be built from a food
name. So the corpus is foods *logged*, not foods B-1 would *ask* about; a
branded bar may be declined as `identity_ambiguous` and never reach a
question. **Read the per-specificity rates, not the headline total.** The
unambiguous in-scope case is grilled chicken breast, and it matched production.

*(An earlier version of this tool reported "0 degenerate sets" — it measured
the raw ontology anchors and skipped `_collapse_by_label`, which is where the
degeneracy is created. A clean number from an instrument pointed at the wrong
stage; the same failure as the trace ring, one layer up.)*

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

