# Food Ledger v2 — architecture, contract, and roadmap to general food intelligence

**Date:** 2026-07-24
**Owner:** Danny
**Status:** Phase 1 shipped (this document's companion change). Phases 2–5 planned below.

## North star

> Treat food logging as a financial-ledger-style transaction system with an LLM
> interface, not as a chatbot that happens to call food tools. The backend
> operates like a strict transactional operating system; the frontend feels like
> a single intelligent person who remembers everything relevant, understands
> vague language, responds immediately, makes reasonable assumptions, and fixes
> mistakes without drama.

Target pipeline (the full build):

```
User message + UI context
→ universal conversational interpreter
→ memory and entity retrieval
→ world-state resolver
→ ordered action plan
→ domain-specific policy validation
→ transactional execution (idempotent, versioned, event-sourced)
→ immutable transaction snapshot
→ card renderer
→ coach response renderer
→ analytics and evaluation trace
```

Food is the first domain inside this shape. Workouts, weight, sleep, wearables,
goals and habits follow the same contract.

## Honest framing (correcting the prior prose)

The earlier "logger and coach" description overstated its guarantees. The
accurate statements, now reflected in code comments and this doc:

- One model produces structured logging decisions and constrained narration
  material; **the system validates and resolves the numeric parts**. The
  numeric channel cannot conflict with the DB; the semantic channel is policed
  by a claim filter (below), not by magic.
- "A question can never become a food entry" is earned **structurally** now:
  the `consumption_evidence` invariant drops log operations for interrogative /
  negated / planned messages regardless of the model's chosen action — it is no
  longer just an action-union property.
- "The system owns the numbers" means the **final persisted values and every
  number the user reads**. The model still materially influences interpretation
  (decomposition, identity, amounts) — which is why provenance, CAS, policy
  arbitration, and the eval harness exist.

## Phase 1 — shipped in this change

Maps to the "what I would change immediately" list (both versions) and the
20-point critique.

| # | Fix | Where |
|---|-----|-------|
| 1 | **Ordered transaction plan** — `operations: [{op: log|update|delete}, …]`, executed in the user's order; mixed turns ("bump the tacos and add a Coke") are one plan. Homogeneous plans keep their kind as the action label; mixed plans are `commit`. | `core/food_turn.py` (`_normalize_ops`, `run`) |
| 2 | **Explicit `delete`** — single-entry removals ("remove the fries", "undo that") are structured ledger ops resolving to real board ids; whole-day wipes stay with the big brain. `move_date` rides the update primitive (`date` field). | `_delete_call`, `applies_destructive`, conversation routing |
| 3 | **Consumption-evidence invariant** — a log write requires a message that can honestly be read as a consumption assertion. Interrogatives, negations, and plans can never execute a `log`, whatever the model chose. | `consumption_evidence` in `core/food_turn.py`, enforced in `run()` |
| 4 | **Narrowed mid-thread routing** — intent taxonomy (`classify_thread_intent`: report / correction / deletion / question / estimate_challenge / coaching / prospective / commentary / retraction / ack) + graded relevance (`thread_relevance`) replaces the flat 15-minute takeover. Challenges, explanation requests, coaching asks and commentary stay with the conversational brain even seconds after a write; hours-old writes bind only explicit corrections/removals. | `core/food_turn.py`, wired in `core/conversation.py` |
| 5 | **One committed snapshot** — `TransactionSnapshot` built from post-enrichment DB state; narration renders only from it. (Card unification onto the same object is Phase 2.) | `core/food_ledger.py` (`build_snapshot`, `render_committed`) |
| 6 | **Semantic-claim policing** — the digit contract stays, plus a claim filter: interpreter prose making database-dependent claims ("protein-heavy", "balanced", "under target", "plenty of fiber") is replaced by the deterministic render from committed numbers. Notes with digits/claims/questions don't ship. | `_CLAIM_RE`, `say_semantically_safe`, `sanitize_note` |
| 7 | **Non-blocking post-commit questions** — the correct rule is now encoded: a committed write cannot ask a question *whose answer is required for that write's validity*; whitelisted optional follow-ups (`save_as_regular`) ride as a second bubble. Blocking clarification stays pre-write. | `_FOLLOW_UPS`, `render_committed` |
| 8 | **Bounded follow-up ask** — the absolute one-question ceiling became an information-gain policy: a second ask is allowed when the user invited it or their answer introduced a *new* material unknown (`new_ambiguity`), never a third, never a re-ask. | `run()` answer-turn branch, `ask_count` in the pending payload |
| 9 | **Policy engine (first inversion step)** — the model *reports* ambiguities it estimated through (`ambiguities: [{item, field, impact_cal}]`); deterministic code (`material_ambiguities`) decides whether any of them holds the write, using the mode thresholds. Thresholds now live in code. | `core/food_ledger.py`, applied in `run()` |
| 10 | **Idempotency** — every structured commit computes a stable key over (user, message, plan); duplicate delivery inside the window is absorbed with an honest reply and zero writes. | `turn_idempotency_key` / `already_processed` / `mark_processed`, wired pre-execution |
| 11 | **Update CAS** — update ops carry `expected_calories` from the board snapshot; the executor refuses the write if the row changed materially since (cross-device edit, enrichment drift) and forces a re-read. | `_update_call` + `update_food_entry` branch in `handlers/tool_executor.py` |
| 12 | **Pending-state expiry** — confirm pendings expire in minutes (a bare "yes" 45 minutes later binds nothing), clarify pendings in hours; expired pendings are resolved and the turn treated as cold. | `pending_expired`, wired at prior-load |
| 13 | **First-class source + provenance** — structured tool calls are no longer anonymous pass-1 impersonations: every call carries `source: structured_food:<interpreter_version>` and log items carry `basis: stated|regular|estimate`, persisted verbatim in each entry's `raw_input`. "Why did you log 6 oz?" has a recorded answer. | `_SOURCE`/`basis` in `core/food_turn.py`; `raw_input=str(inp)` already persisted every input |
| 14 | **Versioning** — `INTERPRETER_VERSION` / `POLICY_VERSION` / `RENDERER_VERSION` constants, stamped into the per-turn telemetry line (`event=structured_food … kinds=… iv=… pv=…`). | `core/food_ledger.py`, `core/conversation.py` |
| 15 | **Correction-operator discipline** — prompt now distinguishes replace / addition / reattribute / relocate explicitly ("two MORE tacos" ≠ "actually only one" ≠ "chicken not beef" ≠ "that was yesterday"). | `_SYSTEM` in `core/food_turn.py` |

Everything is covered by `tests/test_food_ledger.py` (24 cases) plus the
existing 33-case `tests/test_food_turn.py`, all green; the change introduces
zero new failures elsewhere in the suite.

## Kept deliberately (already strong)

- Provisional macros → enrichment (user history → USDA → brand DBs).
- Updates require real board entry ids (now with CAS on top).
- Pending clarification state; deterministic strict-mode confirmation replay.
- Structured path bypassing the 46k-token general model on food turns.
- Final totals filled from committed DB state; deterministic confirmation floor.
- Original user statement + full tool input persisted per entry (`raw_input`).
- Scribe completeness reconcile, dedup guards, meal-slot inheritance.

## Open product decision (needs Danny's call)

**Strict-mode confirmations.** The 2026-07-24 incident fix ("nothing commits
silently on strict") conflicts with the later direction ("do not overuse strict
confirmations — reserve them for high-impact/destructive/ambiguous/bulk").
Phase 1 keeps the incident behavior (every strict pure-log confirms). The
proposed narrowing: confirm only when the plan contains system-estimated
amounts (`basis != stated`), bulk (≥4 items), or destructive/ambiguous ops;
show assumptions inside the committed card otherwise. Flip when approved.

## Phase 2 — ledger durability (first slice SHIPPED 2026-07-24)

**Domain decision (Danny 2026-07-24): the ledger is domain-general.** Food,
fitness, water and weight ride the SAME event history and the same
exactly-once machinery — food is the reference implementation, not a silo.

Shipped:

- **Event-sourced history** — `ledger_events` (alembic `foodledger002`):
  append-only created/updated/deleted events with payloads, scoped by
  `domain` (food | exercise | weight | water), recorded at every executor
  mutation site. Delete events capture the full entry payload BEFORE the row
  dies, so restore ("bring it back") is possible; events survive entry
  deletion by design (entry_id is not a FK). Current state stays materialized
  on the domain tables. Best-effort recording — history can never break the
  write it describes.
- **Durable exactly-once** — `processed_turns` (same migration): structured
  commits claim (user, idem_key) with a unique constraint before writing;
  resends, double-taps, cross-device races and post-restart redeliveries find
  the claim and answer from it. Time-scoped (same message a day later is a new
  turn); concurrency settled by the constraint inside a SAVEPOINT; fails OPEN
  so a claim-infra hiccup never blocks a real meal. The Phase 1 in-process TTL
  registry remains as the fast path.
- **Conversational undo/restore** (`core/ledger_undo.py`) — "undo" / "bring
  back the fries" is a DETERMINISTIC inverse on the event ledger, zero model
  calls: created→delete, updated→rollback (update events now capture the
  row's `before` state), deleted→restore through dedicated
  `restore_food_entry` / `restore_exercise_entry` executor branches (row
  recreated from the event payload, totals recomputed, restore appends its
  own created event). Bounded to recent events (12h; name-restores 24h); an
  uninvertible last event (water/weight for now) REFUSES rather than
  skipping past it. Food + exercise; the plan feeds the same structured
  pipeline (execution → snapshot → renderer).

Remaining in Phase 2:

- **Undo tokens in cards** — backend contract SHIPPED 2026-07-24: every
  food macro_card (including restores, which now get cards) carries the
  `event_id` of the ledger event behind the write, optional on the wire.
  iOS renders "· Undo" from it; the conversational undo flow is the
  execution backend. Remaining: the native client UI + an API endpoint
  accepting an event_id inversion.
- **Card + narration from the same snapshot**: extend `TransactionSnapshot`
  into the card render path (`transaction_id`, `day_revision`,
  `affected_entries`, `batch_totals`, `day_totals`, `remaining_targets`).
- **Timezone / date ownership**: formal meal-event timestamp + log-date policy
  (after-midnight eating, travel, backfill, "breakfast this morning" at 1 a.m.).
- **Meal trees**: hierarchical composite representation (meal event → dish →
  components) with parent ids and atomic/composite/component flags, so
  decomposition helps editability without card noise or double-enrichment.
- **Structured lane for fitness**: the exercise/water/weight domains now have
  event history; giving them the full interpreter → policy → renderer contract
  (like food) is the complementary system Danny flagged — same ledger,
  domain-specific interpreters.

## Phase 3 — policy inversion complete + clarification UX

- Interpreter always emits operations + ambiguity taxonomy (identity, brand,
  quantity, unit, prep, consumed-vs-planned, partial consumption, target
  reference, meal date, duplicate-vs-additional); policy engine owns commit /
  ask / commit-with-estimate-label / require-confirmation for every path.
- Decision score beyond calorie swing: protein impact, relative uncertainty,
  identity confidence, dietary constraints/alcohol, interruption cost, reuse
  value (`expected accuracy improvement ÷ user effort`).
- Progressive correction: log the estimate with an "estimated" label +
  one-tap Smaller / About right / Larger, instead of blocking, for moderate
  ambiguity. Blocking reserved for planned-vs-consumed, serving-count,
  date, and correction-target ambiguity.
- Friction-ranked questions ("light, moderate, or heavy?" over "how many
  tablespoons of aioli?").
- Estimation-state field on entries: exact / user-estimated / system-estimated
  / database-derived / unresolved (subtle UI label).
- Confidence calibration harness: measure acceptance-without-correction per
  confidence bucket from real logs; tune thresholds empirically.

## Phase 4 — memory and entities

- Five memory layers (identity / preference / routine / episodic / ledger),
  ledger never reconstructed from conversation.
- Memory validity: confidence, scope, source, first/last observed,
  reinforcement count, revalidate-after; preference memory separated from
  factual meal memory ("usually dressing on the side" ≠ "yesterday dressing
  on the side"); conversational forgetting ("that isn't my usual anymore").
- Canonical entity graph: meal templates, regulars, restaurants, exercises,
  injuries — aliases + components + confidence.
- **Same-as-before as a first-class op**: `clone_and_modify` from a prior
  entity ("same shake without banana", "repeat Monday's lunch") — no re-parse.
- User-specific estimation priors from corrections ("handful" → 1 oz for this
  user), with confirmed-regular / likely-regular / recent-pattern / one-time
  tiers.
- Retrieval by relevance (small context packet per turn), not profile dumps.

## Phase 5 — universal conversation layer

- Universal turn interpreter (domains + intents + references) ahead of every
  specialized path; multi-intent turns ("half, and remind me to train legs")
  resolve fully.
- Universal interaction stack replacing loose per-domain pendings
  (interaction_id, expected_response_types, priority, expiry).
- Fast-path / deep-path split with explicit latency budgets per turn type;
  regular-meal repeats and undo near-instant, deterministic.
- Staged rendering: "Adding your lunch…" → committed card → coach line after
  enrichment; never a fake acknowledgment before the write.
- UI actions as conversation events (entry_opened, quantity_edited …) feeding
  reference resolution; "make that 4 oz" resolves to the expanded card.
- One assistant voice policy across all subsystems; response proportionality
  (routine log → one tight line; coaching only at meaningful moments).
- Async-enrichment display rules: silent finalize / silent small update /
  transparent material change ("refined 690 → 810 after matching the menu").
- Aggressive versioned caching (regulars, resolutions, conversions, menu
  items); service-level fallback hierarchy — a coaching-generation failure
  never invalidates a successful write.

## Cross-cutting (start now, grow every phase)

- **Replayable evaluation**: the sim suites (`simulate_*.py`,
  `scripts/eval_food_matrix.py`, `tests/test_food_logging_simulation_suite.py`)
  grow into a versioned dataset of real turns with expected route / intent /
  operations / clarification / targets / ranges, replayed on every prompt or
  schema change. Hard cases first: corrections after multiple meals, mixed
  turns, questions containing food names, sarcasm, typos, voice errors,
  multi-language, yesterday-vs-today, repeated retries.
- **Observability trace** per turn: message → intents → references → memories →
  operations → policy decision → DB ops → enrichment source → snapshot →
  response (the telemetry line is the seed; grow it into a stored trace).
- **Product metrics over model accuracy**: % logged without correction,
  correction-within-10-min rate, clarification abandonment, clarifications per
  meal, duplicate rate, undo rate, message→card latency, retention.
- **Coaching-safety policy**: no moralizing foods, no praise for restriction,
  no precision-compulsion escalation, no compensatory-exercise framing, no
  failure framing on missed targets — sustainable-behavior coaching encoded in
  the renderer/voice policy, not left to model mood.
- **Nutrition arithmetic is deterministic**: the LLM interprets language; once
  identity + quantity are resolved, conversions, serving math, DB candidate
  scoring, rounding and totals are code.

## Kill switches

`STRUCTURED_FOOD=false` (whole structured lane), `FAST_LOG_VOICE=false`
(legacy voice), `FOOD_LOGGER_MODEL`, `FOOD_CONFIRM_TTL_MIN`, `FOOD_ASK_TTL_MIN`,
`FOOD_IDEM_TTL_SEC`.
