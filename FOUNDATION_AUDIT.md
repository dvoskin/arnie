# Arnie Foundation Audit & Stabilization Plan

> Status: **AUDIT + PLAN ONLY. No refactors performed.** Awaiting approval per Task 14.
> Date: 2026-05-31. HEAD at audit: `7c20376`.

---

## 0. How to read this

This is the read-only deliverable for the "re-evaluate / simplify / stabilize" pass.
Nothing in the codebase has been changed by this audit except the addition of this
file. Every recommendation is a proposal; the phased plan at the end is sequenced so
each step is independently shippable and reversible. Items are flagged
**[KEEP] / [ISOLATE] / [SIMPLIFY] / [REMOVE-CANDIDATE]** so we can decide per item.

---

## 1. Current architecture summary

**Entry points**
- `main.py` (90 LOC) — boots the Telegram bot (polling/webhook) + FastAPI app.
- `api/app.py` (**3,065 LOC**) — FastAPI: BlueBubbles `/imessage` webhook, Telegram
  `/webhook/{token}`, Stripe, Whoop OAuth, **admin HTML dashboard**, user dashboard
  HTML, REST CRUD for food/exercise/profile, Apple Health inbound. *Mixed concerns.*

**Two parallel conversation pipelines (the core duplication problem)**
- `bot/telegram_handler.py` (**1,876 LOC**) — `_run_pipeline` + 26 slash commands.
- `bot/imessage_handler.py` (963 LOC) — `run_imessage_pipeline`.
- Both independently do: build system prompt → `chat(tools=True)` → `execute_tool_calls`
  → follow-up (`chat_follow_up` or `deterministic_confirmation`) → `detect_moment`
  for reactions/effects → send. **The coaching logic lives twice.**

**Shared core (good — this is the salvageable foundation)**
- `core/prompts/arnie.py` (619) — single behavior prompt, assembled by `build_arnie_system(platform)`.
- `core/context_builder.py` (543) — formats DB state into `[TODAY]`, `[FOOD HISTORY]`,
  `[WEEKLY BREAKDOWN]`, `[MOMENTUM]`, `[COACHING STATE]`, etc.
- `core/llm.py` (563) — `chat()` / `chat_follow_up()`, Anthropic→OpenAI fallback.
- `core/platform.py` (348) — `Response`, `React`, `FX`, adapters, `detect_moment`,
  `onboarding_reaction`. **This is already the right "messaging layer" seed.**
- `core/tools.py` (302) — 14 tool schemas.
- `handlers/tool_executor.py` (535) — `execute_tool_calls` + `deterministic_confirmation`.
- `core/food_intelligence.py` (244), `core/targets.py`, `core/coaching_state.py`,
  `core/timezones.py` — domain engines.
- `db/` — `models.py` (340, SQLAlchemy), `queries.py` (721), `database.py` (289, migrations).
- `memory/` — `memory_manager`, `profile_manager`, `profile_updater`, `reflection`.
- `scheduler/proactive_scheduler.py` (913) — APScheduler nudges/briefings/recaps.
- `skills/` — 18 skill modules (8 fitness, 10 nutrition) + 18 `docs/*.md` (docs unused at runtime).
- `wearables/` — whoop (live) + apple_health, fitbit, garmin, oura (stubs).

**Engagement extras layered on top**
- `core/missions.py`, `core/momentum.py`, `core/memory_moments.py`,
  `core/insights_engine.py` — momentum score, daily "mission", weekly memory moments.

---

## 2. Feature map: Essential / Useful / Future / Non-essential

### A. Essential foundational — PRESERVE & STABILIZE
| Component | Notes |
|---|---|
| `core/prompts/arnie.py` (behavior layer) | **The single source of truth for voice.** Keep, harden. |
| `core/context_builder.py` | Context assembly. Keep; trim what's injected (see §3). |
| `core/llm.py` | LLM + fallback. Keep. |
| `core/platform.py` | Multi-bubble, reactions, effects, adapters. **Keep — this is the messaging layer.** |
| `core/tools.py` (log_food, update/delete_food, log_exercise, update/delete_exercise, log_body_weight, log_water, close_day, reopen_day, update_profile) | Core logging tools. Keep. |
| `handlers/tool_executor.py` | Keep; it already has the anti-fabrication `deterministic_confirmation`. |
| `core/food_intelligence.py`, `core/targets.py`, `core/timezones.py` | Nutrition + targets + tz. Keep. |
| `db/` (models, queries, database) | Keep. |
| `handlers/onboarding.py` + `core/prompts/onboarding.py` | Keep, but redesign flow (§5). |
| `memory/profile_manager.py`, `memory/profile_updater.py` | Keep; centralize writes (§8). |
| `bot/message_debounce.py` | Keep. |
| iMessage + Telegram inbound/outbound | Keep, but **deduplicate the pipeline** (§11). |

### B. Useful but non-essential — KEEP ONLY IF NOT INTERFERING
| Component | Notes |
|---|---|
| `core/coaching_state.py` (wearable readiness) | Keep if Whoop connected; gracefully no-op otherwise (already does). |
| `core/momentum.py` / `fmt_momentum` | Useful for briefings; injected into context. Low risk. |
| `scheduler/proactive_scheduler.py` | Keep but it's **OFF** (`PROACTIVE_MESSAGING_ENABLED=false`). Needs the §9 rework before re-enabling. |
| `update_memory` tool + `memory/memory_manager.py` | Useful, but overlaps `update_profile`; see §3 conflict. |

### C. Future-use — ISOLATE / DEACTIVATE until foundation is stable
| Component | Recommendation |
|---|---|
| **14 of 18 skill files** (cardio_endurance, flexibility_tracking, hiit_circuits, recovery_deload, sport_conditioning, strength_programming, yoga_mobility, grocery_list, progress_timeline, restaurant_mode, travel_mode, weekly_summary, aggressive_cut, weigh_in_analysis) | **[ISOLATE]** Move out of always-on injection. Not deleted — gated behind a future trigger layer. |
| `core/missions.py` (daily mission) | **[ISOLATE]** Adds a second "what to focus on" voice competing with coaching. Disable until core is stable. |
| `core/memory_moments.py` | **[ISOLATE]** Nostalgia callbacks ("X weeks ago you were…") — a retention nicety, not foundational. |
| `core/insights_engine.py` (pattern discovery) | **[ISOLATE]** Feeds briefings; fine to pause with proactive off. |
| `wearables/` fitbit, garmin, oura, apple_health | **[ISOLATE]** Stubs. Keep whoap only; others behind a flag. |
| `generate_image` tool | **[ISOLATE]** Not foundational to a texting coach; rarely correct to fire. |
| `multimodal/` | Verify usage; likely image/voice — keep only the path actually wired to photo food logging. |

### D. Non-essential / conflicting / overbuilt — FLAG
| Component | Issue |
|---|---|
| **Always-on skill injection** (`load_all_skills()` inside `build_arnie_system`) | **Root cause of prompt bloat + conversational degradation.** All 18 skill blocks (~14k chars) enter every prompt. See §3. |
| **Dual pipeline** (telegram_handler vs imessage_handler) | Duplicated coaching logic; behavior drifts between platforms; 2× maintenance. |
| `api/app.py` 3,065 LOC | Admin HTML + dashboard HTML + webhooks + REST in one file. Split (§11). |
| 26 Telegram slash commands | Many (`/me`, `/memory`, `/ai`, `/history`, `/profile`, `/targets`) overlap natural-language coaching. Audit for removal. |
| Hardcoded `"still here. what's up?"` fallback (×3, lowercase) | Lowercase leak + robotic. |
| `update_memory` vs `update_profile` | Two ways to persist user facts → inconsistent writes. |

---

## 2.5 ⭐ THE #1 ROOT CAUSE (found mid-audit) — logging turns mute the coach

**Evidence:** `bot/imessage_handler.py:881-889` and `bot/telegram_handler.py:805-812`.
On **every turn that logs anything** (food/exercise/weight/water), both pipelines do:

```python
if has_logging and not in_onboarding:
    response_text = deterministic_confirmation(tool_calls, today_log, prefs)  # <-- LLM text DISCARDED
```

`deterministic_confirmation` is a fixed set of ~8 templates ("Royo bagel logged.|||
You're at 160/1800 cal today.|||..."). So when the user logs a meal — *the single most
common interaction in the product* — **Arnie never coaches; it emits a canned line.**
The model's real response (and any coaching nuance) is thrown away on the most
important path.

**Why it exists:** introduced in `4dd9fea` ("stop the LLM inventing running totals")
to fix the fabricated-totals screenshot. Correct problem, wrong cure: it muted the
model instead of *giving it the authoritative numbers to coach with*.

**This one choice explains most reported symptoms:** robotic, generic, repetitive,
"weaker conversational logic," "over-instructed" — on every food/workout log.

**The fix (no return of the fabrication bug):** `_dispatch` already returns the
authoritative totals + an `ANALYSIS:`/`coach_note` string (`tool_executor.py:240-246`),
and the prompt already has a "NUMBERS ARE SACRED" rule (`arnie.py:188`). So:
- Let `chat_follow_up` (or the first-turn text) **coach**, with the authoritative
  totals injected as ground truth + a hard "use ONLY these numbers" instruction.
- Keep `deterministic_confirmation` **only** as the empty/error fallback.
- Optionally append the authoritative total line *after* the model's coaching, so the
  number is always exact AND the coaching is alive.
This is Phase 3 priority #1 — highest impact, moderate risk, covered by existing
confirmation tests (which we update to assert "authoritative number present" rather
than "exact template string").

---

## 3. Behavioral-conflict findings (Task 3)

1. **Always-on skills = the biggest *prompt-bloat* conflict.** `build_arnie_system()` →
   `load_all_skills()` concatenates all 18 skill prompts into a `SKILL KNOWLEDGE`
   block on **every** request. Even after the recent DRY pass (voice stripped from
   skills), this still injects ~14k chars of domain instructions the user didn't ask
   for, diluting the model's attention and nudging it toward "report" answers.
   → **Recommendation:** make skills *retrieval-gated* — inject a skill's block only
   when its trigger matches the user message (cheap keyword/embedding match), or
   disable the non-foundational 14 entirely for now.

2. **Lowercase leak (Task 17.1).** No "lowercase" *directives* remain in prompts
   (confirmed), BUT three hardcoded fallbacks are lowercase:
   `bot/telegram_handler.py:851`, `:857`, `bot/imessage_handler.py:918`
   → `"still here. what's up?"`. **This is the only remaining in-code lowercase
   source.** (The bigger lowercase symptom you saw in prod was *stale deploy*, now
   resolved by build-stamp `7c20376`.)

3. **Repetition (Task 17.2).** Causes:
   - `deterministic_confirmation` is a small fixed set of templates; on logging-heavy
     days the same 2-3 lines recur. (Acceptable, but vary them.)
   - Both pipelines can run a follow-up *and* a deterministic confirmation in edge
     paths → occasional double "logged" energy.
   - `detect_moment` + momentum + mission can stack three "next step" nudges in one
     turn. Removing missions (§2C) reduces this.

4. **Conversational degradation (Task 17.3).**
   - Too much always-on context: skills (14k) + FOOD HISTORY + WEEKLY BREAKDOWN +
     MOMENTUM + COACHING STATE + PRs every turn. The model drowns.
   - Tool-first bias: prompt pushes a tool call for many turns where a plain reply is
     better. → Add "respond conversationally when no log/correction is needed."

5. **Two system prompts can disagree across platforms.** Telegram builds
   `_ARNIE_SYSTEM` once at import (`telegram_handler.py:100`) while iMessage builds
   per-request (`imessage_handler.py:777`). Same source, but lifecycle differs.

6. **No pending-question store** → follow-ups can't be context-aware (Task 9B). The
   feature you want literally has no backing state yet.

---

## 4. Root-cause hypotheses (consolidated)

- **Lowercase in prod:** primarily **stale Render deploy** (screenshot predated the
  sentence-case commits). Secondary: 3 hardcoded lowercase fallbacks. *Build-stamp
  `/health` now added so "is prod current?" is one curl.*
- **Repetition:** fixed-template confirmations + stacked nudges (mission + momentum +
  moment + hook) + occasional double follow-up.
- **Robotic / generic / over-instructed:** ~14k of always-on skill instructions +
  heavy context + tool-first bias.
- **Onboarding friction:** rigid 5-step flow (name→goal→weight→training→city) gates
  value; no "immediate-use mode." (See §5.)
- **Weak/absent follow-ups:** no pending-question state; reminders are slot-based
  (`nudges_sent`) not context-aware; proactive is fully OFF.

---

## 5. Onboarding re-evaluation (Task 5)

**Current:** `core/prompts/onboarding.py` defines a required 5-step sequence and a
separate `build_onboarding_system`. The pipeline branches into onboarding mode until
`is_onboarding_complete`. This blocks immediate use.

**Recommendation — two modes:**
- **Immediate-use (default):** any first message that is a log/question is handled by
  the *normal* coaching brain. Profile is `NULL`-tolerant; targets estimated with
  sensible defaults; Arnie answers, then *opportunistically* asks for ONE missing
  essential (height/weight/goal) at the end — never blocking.
- **Guided-profile (opt-in):** only when user says "set up my profile" / "I'm new and
  want to set up." Then walk the fields conversationally, extracting multiple from a
  single paragraph (the prompt already supports multi-field `update_profile`).

This is mostly a **prompt + routing** change, not new infrastructure.

---

## 6. Food logging (Task 6) — assessment

Strong already: `log_food` → `_analyze_food` (USDA + recurring-memory + LLM estimate),
`deterministic_confirmation` reads authoritative DB totals (anti-fabrication),
generic-name guard ("protein bar" won't silently reuse a brand). Supports past-day
logging, corrections (`update_food_entry`), deletes, "how much left" via context
pacing. **Keep as-is**; only ensure the future-tense guard (just shipped) and trim
over-questioning. No structural change needed.

---

## 7. Workout logging (Task 7) — assessment

`log_exercise` parses sets/reps/weight/cardio; history in context; `detect_moment`
celebrates PRs. Foundationally fine. The **strength_programming / hiit / cardio /
sport / recovery / yoga / flexibility skills are premature** — they add programming
depth before the core loop is stable. → Isolate (kept for later).

---

## 8. Memory & profile (Task 8)

**Current stores:** `User` (stable profile), `UserPreferences` (coaching prefs),
`DailyLog`+`FoodEntry`+`ExerciseEntry`+`BodyMetric` (dynamic), plus a file-based
`users/<id>/` memory dir via `memory_manager`. **Two write paths**: `update_profile`
tool (→ DB) and `update_memory` tool (→ file). Recommendation:
- Categorize per your A–E and make **one centralized write path** per category.
- **Add the missing "E. Pending conversation state"** table (see §9/§13) — this is
  net-new but foundational for follow-ups.
- Behavioral patterns (C) and coaching prefs (D) partially exist (`UserPreferences`);
  keep, don't over-engineer pattern learning yet.

---

## 9. Daily interaction, reminders, follow-ups (Tasks 9 / 9B)

**Current:** `scheduler/proactive_scheduler.py` does slot-based nudges (morning,
midday, preworkout, evening, night), briefings, weekly recaps, city nudge. Gated by
`PROACTIVE_MESSAGING_ENABLED` (**currently OFF**) + 9am-9pm window + timezone hard-gate.
**Missing:** context-aware follow-ups to unanswered questions; suppression based on
ignored-reminder streak; per-type frequency limits.

**Recommendation (do NOT re-enable until built):**
- Add `PendingQuestion` state (question, asked_at, kind, answered).
- A single reminder/check-in module owns: eligibility → type → preference check → tz →
  generation → delivery → follow-up timing → suppression → frequency. Most of this
  scaffolding exists in `proactive_scheduler.py`; refactor, don't rewrite.
- Follow-up tone tiers (casual vs goal-critical) per your spec.

---

## 10. iMessage / Telegram experience (Task 10)

**Already supported:** multi-bubble via `|||` (`Response.from_text`), tapbacks
(`React`), iMessage effects (`FX`), typing indicator, reply-to. `detect_moment`
chooses reaction/effect. **Gap:** sequencing/feature selection is split across both
handlers and partly in the prompt. **Recommendation:** the coaching brain should
return a structured plan (messages + per-message tone/feature), and a single
**delivery layer** (`core/platform.py` extended) renders per platform with graceful
fallback when effects/tapbacks aren't supported. Your suggested response schema is a
good target; adopt incrementally.

---

## 11. Maintainability & target architecture (Task 11/13)

**Proposed module boundaries (refactor toward, not a rewrite):**
```
messaging/         # adapters: iMessage, Telegram; bubble-splitting, reactions, effects, fallback
orchestrator/      # one entry: receive → load context → call brain → execute plan → deliver
                   #   (replaces the duplicated logic in both bot/*_handler.py)
core/brain         # arnie.py behavior layer + llm + tool decision (single source of truth)
nutrition/         # food_intelligence, targets  (already mostly here)
workout/           # exercise parsing + (later) programming
memory/            # profile (stable) | daily logs | patterns | prefs | pending-state  (centralized writes)
reminders/         # proactive_scheduler refactored: eligibility/type/suppression/follow-up
skills/            # OPT-IN, retrieval-gated; never globally injected
api/               # thin webhooks + REST; admin/dashboard HTML split into api/admin/, api/dashboard/
tests/             # + realistic conversation suite
```
Biggest wins, in order: (1) **collapse the two pipelines into one orchestrator**,
(2) **gate skills**, (3) **split `api/app.py`**.

---

## 12. Recommended immediate fixes (low-risk, do first)

1. **Gate or disable the 14 non-foundational skills** so only essential knowledge is
   ever injected. (Biggest conversational-quality win, lowest risk — it's prompt content.)
2. **Fix the 3 lowercase fallbacks** → sentence case + vary them.
3. **Disable `missions` + `memory_moments` stacking** in the live turn (keep code).
4. Confirm prod is on `7c20376` via `/health` (deploy verification already shipped).

---

## 13. Phased implementation plan (sequenced, each shippable)

- **Phase 1 — Audit (this doc).** ✅
- **Phase 2 — Behavior/prompt single-source.** Trim always-on context; gate skills;
  add "reply conversationally when no tool is needed."
- **Phase 3 — Lowercase/repetition fixes.** 3 fallbacks; de-stack nudges; vary confirmations.
- **Phase 4 — Onboarding: immediate-use + guided modes.**
- **Phase 5 — Food logging polish** (mostly done; reduce over-questioning).
- **Phase 6 — Workout logging stabilize** (isolate programming skills).
- **Phase 7 — Memory: centralize writes + add PendingQuestion.**
- **Phase 8 — Reminders/follow-ups module + context-aware follow-ups.**
- **Phase 9 — Skill/tool isolation layer (retrieval-gated plug-in pattern).**
- **Phase 10 — Collapse dual pipeline into one orchestrator; split platform delivery.**
- **Phase 11 — Structured message plan (1–4 bubbles, tone, features) end-to-end.**
- **Phase 12 — Split `api/app.py`; folder reshape.**
- **Phase 13 — Realistic conversation test suite (Task 15).**
- **Phase 14 — Final QA over realistic conversations.**

**Sequencing rationale:** 2–3 are pure-content, near-zero risk, and directly fix the
reported symptoms. 4–8 stabilize each core domain behind tests. 9–12 are the
structural refactor (highest risk) and come only after behavior is locked + tested.

---

## 14. Risks

- **Do nothing:** continued prompt conflicts, drift between platforms, follow-ups
  never possible, every new skill makes it worse.
- **Over-refactor now:** collapsing both pipelines (Phase 10) before the conversation
  test suite (Phase 13) risks regressions with no safety net. → Tests **before** the
  big structural moves.

---

## 15. Specific files

**Modify (Phases 2–3, low risk):** `core/prompts/arnie.py`, `skills/__init__.py`
(gating), `bot/telegram_handler.py` + `bot/imessage_handler.py` (3 fallbacks),
`core/context_builder.py` (trim), live-turn callers of `missions`/`memory_moments`.

**Isolate / deactivate (kept on disk):** 14 skill modules; `core/missions.py`;
`core/memory_moments.py`; `core/insights_engine.py` (with proactive off);
`generate_image` tool; `wearables/{fitbit,garmin,oura,apple_health}`.

**Later structural:** new `orchestrator/`, `messaging/`, `reminders/`; split `api/app.py`.

**Net-new (foundational):** `PendingQuestion` model + a reminders module owning follow-ups.

---

## 16. PROGRESS LOG — structural phases (updated as work lands)

**Done & shipped:**
- ✅ Behavior/prompt pass: skills 18→4 active; coach-unmute on logging turns;
  anti-repetition + "not every message needs a tool"; global multi-bubble cadence;
  hard no-AI rule; coaching belief system (`COACHING_PHILOSOPHY` in arnie.py).
- ✅ Postgres + Alembic cutover (AUDIT.md #5/#6), verified live (user onboarded on PG).
- ✅ **#9 phase 1 — split api/app.py 3,065→1,485 LOC** (HTML builders → `api/templates.py`,
  commit e2b6c6d). 25 routes intact.
- ✅ **Pipeline test harness** (`tests/test_pipeline.py`, commit 0e6186a) — drives the
  real `run_imessage_pipeline` with mocked LLM + stubbed BlueBubbles + in-memory DB.
  The net for the collapse. Full suite 127 passing.

- ✅ **Pipeline collapse** (`core/conversation.py::run_turn`, commits a68eac0 + 696292e).
  `run_turn(user, db, messages, system, platform, *, on_image, on_completion, ...)` → `TurnResult`
  owns: LLM call → tool execution → coach-unmute / follow-up / deterministic fallback →
  Response assembly (detect_moment, dashboard-link-once). Both handlers are now thin:
  pre-work → run_turn → adapter.send. 130 tests passing (7 pipeline tests: 4 iMessage,
  3 Telegram twins).

- ✅ **Reminders module + PendingQuestion** (commits 29d3fcc, f839c3d, 5d10830, +this).
  - `PendingQuestion` table (kind, question, tier, asked_at, last_asked_at,
    follow_up_count, answered_at) — Alembic `5ed44c60f075`, additive, verified on
    SQLite + Postgres. Queries: record / get_open / mark_followed_up / resolve
    (one-open-row-per-kind).
  - `reminders/` package owns the cross-cutting decisions as pure functions:
    `eligibility` (window / timezone / pacing / live-conversation / linked de-dup),
    `suppression` (one-shot slot de-dup), `pending` (context-aware follow-up timing —
    tier-scaled cadence casual 24h/cap2 vs goal_critical 8h/cap3, spacing, cold-user
    cutoff, one-per-tick selection, tone hints), `lifecycle` (record/resolve bridge).
  - `scheduler/proactive_scheduler.py` is now the cron driver delegating eligibility
    to `reminders/`; added `_maybe_followup_pending` (re-asks the one due question via
    the adapter path). Bespoke profile-collection slots replaced by the unified
    `profile_stats` PendingQuestion loop.
  - Lifecycle wired into `run_turn`: every inbound turn records the profile_stats loop
    when age/sex/height are missing and resolves it the moment they land — runs
    regardless of the proactive flag (recording/resolution are state, not sends).
  - 166 tests passing (+36: pending-questions, reminders, follow-up dispatch,
    lifecycle, end-to-end pipeline). **Proactive messaging stays OFF** — `_run_reminders`
    isn't even scheduled in prod; only the loop's *state* is exercised live.

**NEXT (per audit) — re-enable + validate proactive:** with the follow-up machinery
built and dark, the remaining work is a staged turn-on: per-type frequency caps in
prefs (`reminder_frequency` is defined but unused), a shadow/dry-run mode to log what
*would* send, then flip `PROACTIVE_MESSAGING_ENABLED=true` behind a small allowlist.
