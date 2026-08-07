# Clarification migration — Phase B approach and sequencing


> **Current as of 2026-08-07.** B-1 and B-1.9 are production-proven on iOS
> (structured `option_id` taps, entries 2887/2890, ~215–257 ms). B-1.5's
> multi-field lifecycle is BUILT and DEPLOYED — `Outcome.PARTIAL`,
> `hold_answer` / `ready_to_settle`, `ResolvedFields`, per-field settlement,
> and an iOS client that renders every open field (`singleField` deleted).
>
> **B-1.5 does not close yet.** Preparation opens nowhere in production because
> no evidence source can establish whether a retrieved row is about the food
> the user meant — measured, not inferred. `docs/CANONICAL_MIGRATION_DIRECTIVE.md`
> §B-1.5E is the bounded prerequisite; the corpus is in
> `tests/evidence_corpus/`. Design decisions here remain valid; the producer's
> TRIGGER is what changed.
> Sequencing authority: [CANONICAL_MIGRATION_DIRECTIVE.md](CANONICAL_MIGRATION_DIRECTIVE.md) (Phase B–F master directive). This document is the detail layer.

Source: architecture review received 2026-08-05, folded into sequencing per the
author's framing ("notes to consider … incorporate into approach and
sequencing"). This is the plan-of-record for migrating conversational food —
the two remaining `tool_executor` writers — onto the canonical spine.

**Standing constraint (in force NOW, enforced by C8):** do not expand the old
clarification architecture further. Four producers + one relay are frozen;
a fifth fails CI (`test_c8_every_clarification_producer_is_a_known_one`).

## The verdict being acted on

The intelligence is repeatedly flattened, reconstructed, parsed, and handed
across competing owners before reaching the user or the ledger. The runtime is
a chain of translated representations:

    clarify_policy (typed ClarificationQuestion)
      → flattened into loose payload keys           (food_turn)
      → buttons attached separately                 (conversation)
      → client re-derives chips from prose          (39/40 asks shipped options:[])
      → answer turn reconstructs the question
      → parse_prior_answer returns None sans response_schema
      → broad interpreter fallback                  (answers become new meals)

## Risk ranking (P0 first — these order the phases)

| rank | risk | anchor |
|---|---|---|
| P0 | four producers, three shapes | `skills/nutrition/clarification_adapter.py` docstring |
| P0 | typed clarification is shadow-only | adapter runs beside, owns nothing |
| P0 | client reconstructs chips from prose | `QuickReplyEngine.swift`; options:[] measurement |
| P1 | unstable field IDs (position + display text) | adapter's own warning |
| P1 | attribute inferred from rendered prose | `_attribute_of` / `_facet_kind` — "DELETION MILESTONE" comment in-file |
| P1 | multiple pending representations | `payload_json` · `deferred_calls` · `staged_items` · `pending_questions` · `pending_operations` |
| P1 | broad-interpreter fallback on unparsed answers | answers become duplicate meals |
| P1 | moderate-mode partial commit topology | one reported meal → multiple commits |
| P2 | `Any`-typed option values; string attribute/status | `core/semantics.ClarificationField` |
| P2 | English-only command regexes | Tier-2 constrained classifier later |
| P2 | question-centric bundling | interaction-with-fields, not sentence-with-fields |

## Design decisions locked for Phase B

1. **Moderate mode stops meaning partial commit.** Per-item ambiguity decisions
   stay; write timing separates: clear item → `ready`, ambiguous → awaiting,
   whole meal → ONE pending operation, ONE write after the clarification turn.
   Partial commit becomes an explicit **recovery** mode (abandonment, expiry,
   "log the rest", separable consumption events) — not the default topology.
   All three accuracy modes decide *ask / assume / defer / disclose* only;
   none invents its own storage architecture. One pending operation, revisions
   across modes.
2. **`ClarificationInteraction` replaces question-as-container.** Voice
   introduction + grouped `ClarificationField`s per event. Mixed-field chip
   rows become unconstructable rather than a client obligation.
3. **Typed patches everywhere.** `ClarificationAttribute` / `ResponseType` /
   `ClarificationStatus` enums; every option carries a `SemanticPatch`
   (e.g. `SetQuantity(event_id, CanonicalQuantity)`), so chip taps and typed
   answers converge at one application boundary:
   `apply_answer(operation, patches) → RevisedDomainPayload`, with patch
   application delegated to the domain — never a dict merge. (This is also the
   workout-sharing seam: see docs/WORKOUT_CONTRACTS.md.)
4. **Field identity derives from semantics, not rendering:**
   `operation_id / event_id / attribute / revision`. The adapter's
   position+text IDs stay measurement-only and die with it.
5. **Answer fallback order hardens** (the current "unparsed → fresh meal" path
   is how answers duplicate):
   exact option-ID binding → narrow schema parser → pending-aware constrained
   classifier (CANCEL/SKIP/USE_ESTIMATE/COMMIT_READY/RESTART/KEEP_AS_READ/NONE,
   given the open operation and fields — never the full interpreter) →
   targeted repair question → explicit cancel → only then fresh-turn
   interpretation, under a hard constraint: an open clarification means no new
   meal unless the user clearly introduced new consumption.
6. **One ambiguity engine.** Resolver produces uncertainty *evidence*
   (candidate ranges); one engine converts evidence into fields; one policy
   decides ask-vs-assume. Resolver-side and staged-pipeline ambiguity
   detection do not both survive.
7. **Voice boundary:** policy emits `QuestionIntent` (type, subjects, resolved
   context, assumption context); the renderer words it under constraints with
   deterministic fallback templates. `_bundle_prompt` / `_default_prompt`
   stop owning wording.
8. **Provenance survives answer application.** USER_STATED / USER_SELECTED /
   USER_CONFIRMED / MODE_DEFAULT are never collapsed at apply or commit time —
   a tapped chip is not the user's own precise figure.
9. **One `ClarificationOptionGenerator`** (entity, field, candidates, history,
   locale, mode, channel capabilities → canonical options), separating
   semantic selection / label rendering / client layout.
10. **The wire payload is grouped and ID-addressed** (§13 shape: operation_id,
    revision, groups → fields → options with option_ids). The client submits
    IDs; labels are never the semantic value. When present,
    `QuickReplyEngine` prose parsing is disabled entirely, then deleted.

## Sequencing (coordinated with the migration directive's phases)

    B-0  freeze producers                     DONE — C8 ratchet (a66e9ba)
    B-0b strengthen semantic types            DONE — ClarificationAttribute,
                                              ResponseType, ClarificationStatus,
                                              CandidateSource, SemanticPatch
                                              family, UnresolvedField,
                                              CandidateValue,
                                              ClarificationInteraction/Group;
                                              option carries `patch`
                                              (tests/test_clarification_
                                              contracts_b0b.py). Option
                                              producers frozen separately: C9.
                                              Chip pipeline plan:
                                              docs/CHIP_GENERATION_MIGRATION.md
    B-0c CONTRACTS SURVIVE STORAGE            DONE — `patch_type` discriminator
                                              + schema version, typed round
                                              trip (Decimal exact), symmetric
                                              enum coercion, group/interaction
                                              validation, deep-copied payloads,
                                              and the persistence proof: a
                                              stored option_id becomes a typed
                                              SetQuantity in a NEW session
                                              (tests/test_contract_persistence_
                                              b0c.py). B-0b proved the types
                                              hold in memory; B-1 crosses a
                                              JSON column and a process
                                              boundary, which is a different
                                              claim.
    B-1  ONE-ITEM QUANTITY SLICE ONLY         the whole of the next milestone:
                                              "I had chicken" → quantity ask →
                                              chip OR text answer → revised
                                              ResolvedMeal → canonical commit →
                                              narration/card/totals agree.
                                              Staged policy emits canonical
                                              fields for THIS case only; the
                                              canonical client payload and
                                              typed answer application ship
                                              inside this slice, not after it.
    B-2  multi-item, bundles, partial answers  ONLY after B-1 is green in prod
    B-3  DELETE adapters + legacy producers    C8 baselines → 0; the adapter
                                              has a deletion milestone, not
                                              tenure

Scope discipline for B-1: it is a VERTICAL slice, not a horizontal layer. One
attribute (quantity), one item, both answer modalities, all the way to the
ledger and back to the card. Widening before it is proven in production is how
the four producers happened the first time.

Steps 3–6 ride the same PendingOperation persistence already built
(`core/pending_repository.py`, flags off) — Phase B is where it stops being
shadow. What is *kept* from today's system, deliberately: `clarify_policy`'s
materiality-per-effort ranking, bundling affinities, neighbor-protection, and
the narrow answer parser's coverage (fractions, ordinals, ranges, commands) —
re-homed onto typed fields, not rewritten.
