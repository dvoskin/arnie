# Arnie architecture contract

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
