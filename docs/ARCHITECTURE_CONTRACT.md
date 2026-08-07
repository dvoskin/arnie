# Arnie architecture contract


> **Current as of 2026-08-07.** Sequencing authority is
> `docs/CANONICAL_MIGRATION_DIRECTIVE.md`; this document holds the executable
> invariants. **Two new enforced contracts joined C1–C9 and live in their own
> suites rather than `test_the_canonical_invariants.py`:**
>
> * **The Semantic Extension Contract** — a new food behaviour enters as a
>   REGISTERED FIELD or not at all. `core/semantic_fields.py` is the registry;
>   `tests/test_the_semantic_extension_contract.py` enforces it. A field cannot
>   be PRESENTED unless registered (checked on `ClarificationInteraction`, not
>   on `UnresolvedField` — construction stays free so the Phase-O workout seam
>   holds). `ResolvedFields` is the only settlement boundary; `Pricing` has no
>   MULTIPLIER member; exactly one field may decide the amount. Generality is
>   claimed only by `tests/test_the_rule_of_three_fields.py`, and its known
>   limit is pinned: one answer per field, so multi-valued fields are not yet
>   expressible.
> * **One gate decides lane ownership** — `core/canonical_lane.py`.
>   `tests/test_one_gate_decides_the_lane.py` forbids any other module naming
>   `may_take_ownership` or `client_renders_interactions`. This replaced a
>   two-owner predicate that had already drifted in production.
> * **No row is deleted without a ledger event** —
>   `tests/test_no_row_is_deleted_without_a_ledger_event.py`, added after
>   `clear_day_log` removed 14 rows (4 canonical) with zero events.
>
> C4 still reads 3 legacy writers and C8/C9 stay frozen: promotion and
> predecessor deletion are DEFERRED until B-2 by deliberate rollout decision,
> not by drift. See the directive's "One promotion event".
>
> **B-1.5E added two more enforced boundaries:** semantic evidence
> qualification runs BEFORE `best_candidate` (eligibility, not truth —
> `tests/test_qualification_changes_resolver_behavior.py`), under the
> invariant `SEMANTIC_RESOLVER_DOWN != RAW_EVIDENCE_AUTHORIZED`: the user's
> action fails open through the ladder's qualification-free rungs, ambiguous
> evidence fails closed. And SPACE vs VALUE — external evidence may open a
> semantic field and populate its options but may never construct a resolved
> patch (`tests/test_evidence_opens_preparation_but_cannot_answer_it.py`).

**Status:** authoritative. A change that violates a rule here is wrong even if every test passes.
**Created:** 2026-07-30, from the master audit (`audits/MASTER_AUDIT_2026-07-30.md`).
Each invariant lists its current production status and its enforcement point — the directive's rule
is that an invariant enforced only in documentation or prompts does not count as enforced.

## 1 · Invariants

| # | Invariant | Prod status (07-30) | Enforcement point (current → target) |
|---|---|---|---|
| I1 | One inbound message creates one canonical turn | **violated** (dashboard_edit, proactive, quick-log create no turn) | none → executor boundary creates the turn record |
| I2 | One unresolved question has one authoritative pending owner | holds behaviourally since 07-29 deploy | code (`32dcb36`) → DB partial unique index on open pendings per (user, purpose) |
| I3 | One user action produces at most one committed operation | **violated** (quick-log double-write ×7/18h) | none → single writer + unique (user, entry, event_type, turn_id) |
| I4 | Every state-changing request is idempotent | partial (chat turns keyed; iOS direct paths not) | idempotency_key on conversation_logs → required at executor for all writers |
| I5 | Corrections target existing entities by stable ID | holds in structured lane; escapes precede it | `_update_call` board-anchoring → routing on state, not phrases (8.3) |
| I6 | A correction must not create new consumption | held this window (0 observed) | `_revalidate_after_answer` + veto → keep; add DB-side status |
| I7 | User-visible numbers come from committed state | partial (say-contract covers digits; join gap blocks verification) | `enforce_say_contract` → extend to entities (cause H) + turn↔op join |
| I8 | Models propose; they do not own persistence | holds in structured lane; legacy writes via tools directly | executor tool layer → legacy containment (§12 of directive) |
| I9 | Presentation renders committed state; never reinterprets | **violated** (dashboard `_reconcile_macros` second reconciler) | none → PresentationSnapshot phase |
| I10 | Local filesystem is not authoritative | holds for domain data (`ARNIE_USERS_DIR` memory files are the exception, known) | migrate memory files → DB in memory-interface phase |
| I11 | Legacy may not write around the structured layer | **violated** (13/52 events legacy-sourced) | source labels only → typed adapter (§12) |
| I12 | Undo is an inverse operation, not history deletion | holds (`ledger_undo` builds inverse plans); delete-as-move seen 07-29, fixed `c20885e` | code → keep; DB immutability constraint deferred |
| I13 | Committed records retain provenance | holds for food entries (raw_input, source, basis) | keep |
| I14 | User-local dates are computed once and passed through | improved (`log_date` deployed 07-30); RU answer-turn escape bypasses | pending payload → TurnContext phase |
| I15 | Storage units are explicit and normalized at the boundary | holds by convention (kg/g); no constraint | convention → `[UNITS]` block (merged) + boundary validation |
| I16 | A narrated success has a matching successful operation | **unverifiable** (no turn↔operation join) | none → join (audit item 28.2), then reject at render |
| I17 | No subsystem reconstructs state already held by a canonical ID | **violated** (ask/write disconnect; `user_food_matches` third identity) | none → FoodResolution join (8.1) |

### 1b · Canonical mutation boundary (C1–C6)

I1–I17 describe the system as a whole. These six are the canonical lane's own,
and unlike the table above they are **executable** —
`tests/test_the_canonical_invariants.py` fails when one breaks. An invariant
that lives only in a table is a hope; this rearchitecture exists because of a
list of properties everyone believed and nothing checked.

| # | Invariant | Status | Enforced by |
|---|---|---|---|
| C1 | Every committed row belongs to exactly one `MealCommitResult` | holds in the canonical lane | `test_c1_*` — rows written across two operations are disjoint and fully owned |
| C2 | Every `MealCommitResult` corresponds to exactly one operation revision | holds | `UNIQUE (operation_id, operation_revision)`, proved under real concurrency in `test_two_connections_one_commit.py` |
| C3 | Every macro-aggregation site is a known one | ratchet, 7 known | `test_c3_*`. Named for what it proves: it sees `sum()` over a macro attribute. The day's REMAINING calories — three owners disagreeing by one — is I9 and is **not** detected. The *goal* it serves (renderers consume `MealCommitResult`) is broader than the check |
| C4 | Every direct food writer is a known one | ratchet, **3 legacy remain** | `test_c4_*`: `api/app.py`, `handlers/tool_executor.py` ×2. quick_log deleted at its promotion (first migrated owner). The goal is zero |
| C5 | No `PendingOperation` transitions directly to COMMITTED | holds | `_ALLOWED_TRANSITIONS`; COMMITTING is the only state that says a write was in flight, so a retry can tell "never started" from "may have written" |
| C6 | Every duplicate returns the identical **persisted** result | holds | `test_c6_*` — identical to the stored row, not merely equivalent |
| C7 | Deleted ownership stays deleted | holds | `test_c7_*` — promoted owners' legacy imports are forbidden by name; a returning `add_food_entry` in `api/quick_log.py` fails CI |
| C8 | Every clarification producer is a known one | ratchet, **4 producers + 1 relay frozen** | `test_c8_*`. The Phase-2 freeze from the clarification review: no fifth producer, no new `ClarificationQuestion` constructor, until Phase B collapses the four into canonical `ClarificationField`s |
| C9 | Every clarification **option** producer is a known one | ratchet, **repo-wide by AST: 13 payload sites across 6 files (classified debt / bystander / canonical) + 5 constructors frozen** | `test_c9_*`. Separate from C8 per the chip directive — question and options had different owners, which is how options:[] shipped while the client parsed prose. The first version froze five files and one spelling, so two live relays (`context_builder`, `clarify_ui`) shipped uncounted; it now walks the repo like C3/C4 and matches every spelling a producer can use. The chip invariants beyond this (typed patches, ID-only taps, no label parsing) enter this table as their phases make them enforceable — see docs/CHIP_GENERATION_MIGRATION.md |

C3 and C4 **cannot** hold yet: the legacy lane is still the production writer,
and it is meant to be. They are ratchets against a measured baseline — they
permit exactly what exists today and fail the moment it grows. That is the
difference between "not done" and "getting worse".

### 1c · The migration converges or it is not a migration

**Every production mutation migrated must permanently reduce legacy code.** The
new architecture must never become an additional layer that coexists
indefinitely with the old one. Migrations stall at 80–90% precisely because the
last legacy paths are never deleted, and two systems that both survive will
diverge — one special-case bug fix at a time, applied to whichever lane the
reporter happened to hit.

So each mutation owner moves through all five steps, and the last one is not
optional:

    move one mutation owner -> shadow -> validate -> promote -> DELETE legacy

`C4`'s count is what makes this checkable rather than aspirational: promoting a
path without deleting its predecessor leaves the number unchanged, and the
ratchet says so. Lowering `_LEGACY_FOOD_WRITERS` is the last step of each
migration, not bookkeeping afterwards.

## 2 · Ownership map

"Owner" = the one component allowed to make the decision or write the state. Everything else is an
adapter, consumer, or contained legacy. Responsibilities currently owned by two components are the
audit's root-cause clusters.

| Responsibility | Authoritative owner (current) | Other implementations, classified | Target owner |
|---|---|---|---|
| Inbound turn creation | `core/conversation.run_turn` | iOS quick-log/dashboard/proactive — **rogue writers, no turn** | executor boundary (all paths) |
| User-local time / logging day | `db/queries._user_today` + `log_date` on pending | context_builder computed separately — redundant | `TurnContext`, computed once |
| Routing | `conversation` free signals → `food_turn.applies` → Haiku gate | shadow coordinator re-judges (observe-only) — acceptable shadow | unchanged; predicates letters-only (`15f961a`, undeployed) |
| Interpretation | `food_turn` interpreter (structured); legacy big-brain (contained by lane) | fast-path parser — shadow | unchanged |
| Active thread state | `thread_relevance` / `_route_mid` | — | TurnContext |
| Pending questions | `conversation.py` ASK_KIND stash (structured) | conversation_hook writer — **was duplicate writer, now references; CLOSED behaviourally** | one writer + DB uniqueness |
| Food identity | **none** — split across staging / resolver / `user_food_matches` | three representations `ROOT CONFIRMED` | `FoodResolution` |
| Candidate generation | `shadow.candidates_from_live` → `resolver` (write time only) | none at ask time — **the missing join** | `FoodResolution` at stage time |
| Nutrient resolution | `resolver.resolve` (live mode) | `food_intelligence.analyze` ladder — overlapping authority | resolver, with analyze as adapter |
| Ambiguity detection | `food_pipeline.attach_ambiguities` | resolver `_ambiguities` — second implementation | one, fed by candidates |
| Clarification policy | `clarify_policy.decide` | legacy ask paths (empty payloads) | clarify_policy only |
| Clarification application | `answer_parsers` + `parse_prior_answer` + `answer_application` (shadowed) | interpreter re-run — fallback, should shrink | typed application |
| Tool selection | model within lane | — | ExecutionIntent phase |
| Execution / ledger writes | `handlers/tool_executor.execute_tool_calls` | `api/quick_log`, `api/food_edit`, `api/app:3604` — **bypasses**; quick-log **double-writes** | one executor, typed adapters |
| Corrections | `_update_call` (structured) | dashboard `_reconcile_macros` — second reconciler | executor path |
| Undo | `core/ledger_undo` | — | keep |
| Health imports | wearables handlers | reachability audit flags 9 dead methods — suspect | audit then contain |
| Quick-log | `api/quick_log.py` — **bypass + double-write** | | adapter over executor |
| Memory updates | `upsert_user_food_match` (+ ceiling guard) | promotion path writes too | one memory interface (Phase 4) |
| Cards | `conversation._logged_entry_card` | iOS renders from payload — consumer | PresentationSnapshot |
| Coach narration | composer + deterministic floors (`validate()` twice) | interpreter `say` — bounded by say-contract | one presentation policy |
| API responses | api/app | — | snapshot consumer |
| Push/scheduling | `scheduler/proactive_scheduler` | writes no turn — I1 violation | executor-visible operations |

## 3 · Flag registry (ownership + deletion criteria)

| Flag | State | Owner | Deletion condition |
|---|---|---|---|
| `STRUCTURED_FOOD` | on (default) | food lane | legacy containment complete |
| `FOOD_GATE_MODEL` | on (dashboard) | routing | gate precision measured ≥ target post-`15f961a` |
| `FOOD_FAST_PATH_SHADOW` | on | routing | decision by agreement rate — **set a review date; currently unowned** |
| `NUTRITION_RESOLVER_MODE` | live | resolution | delete after FoodResolution phase |
| `FOOD_COMPOSER` | on | presentation | PresentationSnapshot phase |
| `TURN_COORDINATOR_MODE` | new_observe | orchestration | promote or delete after disposition-agreement number exists |
| `FOOD_ANSWER_APPLY` | off (cannot fire) | clarification | enable after join (8.1); delete after FoodResolution owns commits |
| `TURN_OBLIGATIONS` | on (merged, undeployed) | turn context | delete when 8.5's typed ExecutionIntent ships |
| `FOOD_IDENTITY_ASK` | **off** (shipped `27d6f7b`) | food identity | **Enable when:** the firing rule handles a thin shelf without trading a silent assumption for a needless question. **Review by 2026-08-06.** Reported on `/health` so the pending decision is visible without anyone remembering it. **Owner: Danny.** |

### Flag hygiene

Every flag in this table carries an owner and a condition. That is the audit's
own finding applied to itself: §26 listed flags parked in shadow indefinitely
(`FOOD_FAST_PATH_SHADOW`, "shadow since 07-29, no decision date") as stale
code, because a flag with no review date is not a rollout, it is a fork of the
product nobody is measuring.

The mechanism is deliberately not a reminder. Anything whose state matters is
reported by `GET /health`, which needs no token and no traffic — so "did we
ever turn that on?" is a request, not a memory.

## 4 · Canonical contracts (target shapes)

The directive's contracts (`TurnContext`, `FoodResolution`, `ExecutionIntent`, `OperationResult`,
`PendingQuestion`, `CorrectionPatch`, `UndoOperation`, `MemoryFact`, `PresentationSnapshot`) are the
Phase 3–4 deliverables. Current partial implementations to grow from — not to duplicate:

- `TurnContext` ← the five `[…]` state blocks (`core/turn_obligations.py`) + `food_trace` fields.
- `FoodResolution` ← `StagedFoodItem` + `staged_codec` + `ProductCandidate` (the join, 8.1).
- `ExecutionIntent`/`OperationResult` ← `execute_tool_calls`'s call dicts + `ExecutionResult`.
- `PendingQuestion` ← the ASK_KIND payload (now carrying schema/options/staged_items/log_date).
- `PresentationSnapshot` ← the committed-snapshot dict the reply layer already builds.

Rule: **no new context model may be created for one lane** — extend these.
