# Clarification migration — Phase B approach and sequencing

Source: architecture review received 2026-08-06, folded into sequencing per the
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

    2. freeze producers                       DONE — C8 ratchet, this commit
    3. strengthen semantic types              enums + SemanticPatch + Interaction
    4. staged policy emits canonical fields   start: one-item quantity ask
    5. canonical client payload               iOS renders groups; parser off
    6. canonical answer application           patches from chips AND text
    7. one vertical flow proven               chicken → ask → answer → revised
                                              ResolvedMeal → canonical commit →
                                              matching narration/card/totals
    8. multi-item, bundles, partial answers
    9. DELETE adapters + legacy producers     C8 baselines → 0; adapter has a
                                              deletion milestone, not tenure

Steps 3–6 ride the same PendingOperation persistence already built
(`core/pending_repository.py`, flags off) — Phase B is where it stops being
shadow. What is *kept* from today's system, deliberately: `clarify_policy`'s
materiality-per-effort ranking, bundling affinities, neighbor-protection, and
the narrow answer parser's coverage (fractions, ordinals, ranges, commands) —
re-homed onto typed fields, not rewritten.
