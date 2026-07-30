# Master architecture audit — full 18-hour window

**Window:** 2026-07-29 20:40 → 2026-07-30 14:40 UTC · **Pulled:** 2026-07-30 ~15:10 UTC ·
**Directive:** the structural-hardening master prompt (this document is its §20 output)

**Evidence statuses** per the directive: `OBSERVED` `REPRODUCED` `ROOT CONFIRMED` `FIXED LOCALLY`
`DEPLOYED` `CLOSED`. Nothing below is marked closed on the strength of a commit, a merge, a flag,
or a green suite.

---

## 1–4 · Population, deployment coverage, mixed periods, flags

**Population** `OBSERVED`: **79 turns**, 3 users, all iOS-platform. Source types: ios 65,
dashboard_edit 6, photo 3, voice 3, proactive 2. 71 turns carry `reasoning_json`; the **8 that do
not are exactly the dashboard_edit and proactive turns — writes that never create a canonical turn**
(violates invariant "one inbound message creates one canonical turn"; see §26).

**Deployment coverage** `OBSERVED`, established from markers, not commits:

| Evidence | Conclusion |
|---|---|
| `log_date` first appears on pending id=1989 at **07-30 12:12 UTC** | a deploy landed shortly before 12:12 |
| `Good morning 🌞` admitted `owner=gate_regex` at **13:09** | the deployed `_non_latin` is the OLD one — `15f961a` is NOT live |
| `staged_items` present throughout | `cca96be` is live |

**Deployed SHA ≈ `47e290d`** (then-main). Everything merged 06:11–06:55 UTC today — the four-branch
combine, `KEEP_AS_READ`, the gate fix, `[TURN OBLIGATIONS]`, the five state blocks, the provenance
fix — is **merged, NOT deployed** (`FIXED LOCALLY`).

**Mixed-deployment period** `OBSERVED`: the window spans two builds. Turns before ~12:12 ran the
07-29 build; after, the 47e290d build. All per-lane numbers below are labeled where the split
matters.

**Effective flags**: not queryable from here — Render dashboard-managed; `render.yaml` is
reference-only. The audit cannot verify `FOOD_GATE_MODEL`/`FOOD_GATE_OPEN` state, and §8's routing
analysis is bounded by that. **Unknown #1.** (The structural fix — SHA + flags stamped per turn —
is Phase 1 work, implemented below in this branch.)

## 5–7 · Route, owner, escapes

| lane | n | | owner | n |
|---|---|---|---|---|
| legacy | 45 (57%) | | gate_regex | 41 |
| structured_log | 16 | | (none — route recorded, owner not) | 16 |
| structured_ask | 5 | | thread | 7 |
| structured_update | 3 | | prior | 5 |
| structured_delete | 2 | | photo | 2 |

`legacy_reason`: **interpreter_none 30**, mixed_domain 8, question 4, future_plan 3 `OBSERVED`.
Ledger events by source: structured 25, `legacy:ios` 11, ios 8, ios_edit 6, legacy 2 — **13 of 52
(25%) from a legacy source**; plus 14 from iOS direct paths that bypass the turn pipeline entirely.

## 8 · `interpreter_none` breakdown (30 turns) `OBSERVED`, classified by causal path

| Cluster | n | Examples | Status of fix |
|---|---|---|---|
| Non-food admitted on punctuation/emoji or shape | ~9 | "Mark my Flat DB complete 💪", "7 couldn't do more", "Good morning 🌞" | `ROOT CONFIRMED` + `FIXED LOCALLY` (`15f961a`) — **13:09 proves not deployed** |
| Workout/weight reports with real shapes | ~5 | "86.7kg this morning", "50 pull ups", "No it was 4 different sets" | `OBSERVED` only — these carry units/numbers, likely admitted by portion-shape regexes; separate mechanism from punctuation. **Not yet root-caused.** |
| Food corrections / clarification answers | ~8 | "Update the sun chips to just 9 chips", "Okay make that 3/4 of that cube", "Can I have this" | Premise confirmations `FIXED LOCALLY` (`b0437a7`); quantity corrections **REPRODUCED as working locally with a correct board** — the production failures likely involve board/prior state absent at the time. Not fully root-caused. |
| **Russian turns, incl. a premise confirmation** | 3 | "Это было вчера…", "Да, сегодня только это" | `OBSERVED`, **new**: `KEEP_AS_READ` is EN-keyed — the fix for cluster 3 reproduces the RU blindspot (see §24). |
| Media/meta noise | ~5 | `[REGENERATE]`, voice "you", "Accidentally sen that" | expected degradation |

## 9 · Narrated actions without tool calls

**Not computable this window** — and that is itself the finding. 29 replies claim a log; ledger
`turn_id` uses three incompatible formats (`ios:h:<hash>`, `ios:ios:<uuid>`, `ios_edit:update:<id>`)
none of which equals `conversation_logs.id` or `idempotency_key` (`ios:<uuid>` — the uuid matches
quick-log events only). **There is no reliable join between a turn and its operations.** Violates
"foreign keys between turns…and operations". **Unknown #2**, structural fix in §28.

## 10–11 · Duplicate tool calls / ledger operations `OBSERVED`

**10 duplicate ledger pairs** in 18h (same user+entry+event_type, ≤60s):

- **7 × quick-log double-write**: every iOS quick-log `created` event is written **twice, 0s apart,
  same turn_id, two source labels (`ios`, `legacy:ios`)**. Deterministic, not a race — two writers
  on one path. `ROOT CONFIRMED` at the pattern level; the two call sites are identified in §26.
- 1 × `ios_edit` double-update 18s apart (the dashboard `_reconcile` double-edit, still live).
- 1 × structured update written under two different turn_id formats 7s apart.

## 12 · Duplicate pending questions — **status changes to CLOSED, and yesterday's claim corrected**

Exact-text cross-kind duplicate pairs by day `OBSERVED`:

```
07-23: 4 · 07-24: 4 · 07-25: 8 · 07-26: 19 · 07-27: 12 · 07-28: 14 · 07-29: 1 · window: 0
```

The 07-29 deploy **closed G**. Yesterday's audit said "G is deployed and does not work — 62
duplicates in 7 days"; that figure pooled six pre-deploy days with one post-deploy day and was
**wrong as a verdict on the fix**. Within this window: 0 exact-text duplicates, 1 cross-kind pair
within 60s (different texts). G is `DEPLOYED` + post-deploy window confirms → **`CLOSED`** — with
the caveat that structural prevention (a uniqueness constraint, one writer) still does not exist;
the invariant currently holds behaviourally, not structurally. Hooks are still written (12 vs 5
food asks) but no longer duplicate the question.

## 13–16 · Clarifications, corrections, undo

- 17 pendings asked, 16 answered in-window; 4 of 5 food asks carry `staged_items`, 4 carry
  `response_schema` `OBSERVED` — the empty-payload ask return points have narrowed but still exist.
- Clarification answers that failed to settle state: the two RU turns above (`OBSERVED`); "Да,
  сегодня только это" is an unsettled premise confirmation.
- Corrections creating new entries instead of updating: **0 observed this window** (the update lane
  handled its 3). Corrections targeting the wrong entry: none observed. Undo: no undo events in
  window — **no evidence either way.**

## 17–19 · Integrity

- **Zero/null-calorie entries: 0** this window `OBSERVED` (4 in the prior 7d — those predate it).
- **Wrong-day writes:** 8 entries have UTC-date ≠ log-date; all are consistent with correct
  user-local rollover behaviour (NY evening = next UTC day). **0 confirmed wrong-day writes**, but
  the check requires per-user tz joins the schema makes awkward — same join gap as §9.
- **Unit inconsistencies:** none observed; not systematically checkable without per-field audit.

## 20–23 · Rendering, model calls, latency, retries

- Rendering mismatches: correction cards missing receipts is `FIXED LOCALLY` (`7b89e4c`, merged
  today, not deployed); not re-observable until deployed.
- Model calls by lane: not directly recorded — inferable only from steps/duration. **Unknown #3**
  (fix: per-call records in the trace, §28).
- Latency `OBSERVED`: p50 **7.1s** · p90 11.5s · p99/max 17.7s (n=71). Flat vs both prior windows.
  Structural waste identified and unfixed-in-prod: ~14 of 45 legacy turns paid a full interpreter
  pass to produce nothing (5–14s each).
- Retries/fallbacks: not distinguishable in current telemetry. **Unknown #4.**

## 24 · Violated invariants (§3 of the directive), ranked

| Invariant | Status | Evidence |
|---|---|---|
| One user action → at most one committed operation | **VIOLATED** | 7 quick-log double-writes/18h `OBSERVED` |
| One inbound message → one canonical turn | **VIOLATED** | dashboard_edit/proactive writes create no turn `OBSERVED` |
| FKs between turns/pendings/operations | **VIOLATED structurally** | three turn_id formats, no join `OBSERVED` |
| Legacy may not write around the structured layer | **VIOLATED** | 13/52 legacy-source events `OBSERVED` |
| One pending owner per question | **HOLDS post-deploy** | §12 — but behaviourally, not structurally |
| Every user-visible number from committed state | Partially violated | narrated-claim join impossible (§9) |
| Corrections target stable IDs | HOLDS in structured lane; legacy corrections escape first | §8 cluster 3 |
| User-local dates computed once | Improved (`log_date` deployed); answer-turn RU escape bypasses it | §8 cluster 4 |

## 25 · Root-cause clusters (shared causal path, not wording)

1. **No canonical join turn↔operation↔pending** — makes §9, §18 unauditable and idempotency
   unenforceable. Earliest-violated invariant of the entire audit.
2. **Two writers on the quick-log path** (`ios` + `legacy:ios`) — duplicate operations.
3. **Ask-time/write-time disconnect** (8.1) — unchanged; `FIXED LOCALLY` half-measures live only.
4. **Gate admits on non-semantic evidence** (8.4) — fix exists, not deployed; the number-shape arm
   (86.7kg / 50 pull-ups) is a second, un-root-caused mechanism.
5. **EN-keyed deterministic layers** — `KEEP_AS_READ` continues the pattern the RU memory warns
   about; two RU escapes this window.
6. **Out-of-pipeline writers** (dashboard_edit, proactive, quick-log) — no turn, no reasoning, no
  idempotency.

## 26–27 · Redundant implementations, stale code and flags

- Quick-log's **two ledger writers** (§10) — the concrete §6 target: `api/quick_log.py` +
  `handlers/tool_executor.py` default-stamping (`legacy:{source_type}`) both record the same write.
- The carried backlog's known bypasses: `api/quick_log.py:61`, `api/food_edit.py:62,128`,
  `api/app.py:3604`, `_reconcile_macros` as a second reconciler — all still live `OBSERVED`
  (ios_edit double-update).
- `user_food_matches` as a third identity store — unchanged.
- Stale branches: cleaned this morning (4 branches merged). Flags without deletion criteria:
  `FOOD_FAST_PATH_SHADOW` (shadow since 07-29, no decision date), `TURN_COORDINATOR_MODE=new_observe`
  (observe since #23), `FOOD_ANSWER_APPLY` (cannot fire until the join exists — has a defined
  enable condition), `TURN_OBLIGATIONS` (new, deletion condition = 8.5's typed solution).

## 28 · Minimal ordered change set (Phase 1–2 of the directive)

1. **Stamp `deployed_sha` + effective flags on every turn's `reasoning_json`** — turns Unknown #1
   into a query; prerequisite for every future closure claim. *(Implemented in this branch — see
   companion commit.)*
2. **One turn_id, threaded turn→operation** — normalize the three formats; write
   `conversation_logs.id` (or the idempotency uuid) onto `ledger_events.turn_id` from every writer.
   Unlocks §9, §18, §24-FK, and idempotency enforcement.
3. **Kill the quick-log double-write** — one writer, one event; DB unique partial index on
   (user_id, entry_id, event_type, turn_id) as the structural guard.
4. **Deploy the merged head** — five audited fixes are sitting undeployed; every later closure
   claim needs them live.
5. **De-EN-key the deterministic layers** — `KEEP_AS_READ` (and audit `_YES_RE`, `_VAGUE_SELECTIONS`)
   for RU equivalents, driven by the two observed RU escapes, as typed/bounded patterns per the
   directive's parser rule.
6. **The ask-time/write-time join** (8.1) — unchanged priority; after 1–3 because closure needs
   their telemetry.
7. **Route the out-of-pipeline writers through the executor** (dashboard_edit, quick_log,
   proactive) behind typed adapters (§12 containment).

## 29 · Risks and rollback

Items 1–3 are additive telemetry/constraints: rollback = revert commit; the unique index ships
`NOT VALID`-style (create, verify, then enforce) so a false constraint cannot block writes. Item 4
is Danny's manual action. Items 5–7 each carry their own test + revert path per the directive's
per-fix format.

## 30 · Unknowns

1. Effective runtime flags (dashboard-only) — until item 1 ships.
2. Narrated-without-operation rate — until item 2 ships.
3. Per-lane model-call counts — needs trace enrichment.
4. Retry/fallback distribution — same.
5. Whether the number-shape gate arm (86.7kg) is `_PORTION_SHAPE_RE` — needs the same repro pass
   that settled the punctuation arm.
6. iOS default branch state — repo present locally but out of this audit's window scope; not
   audited this pass.
