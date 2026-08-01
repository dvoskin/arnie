# Market-readiness scorecard

**Verified: 2026-07-31.** Three states only: **PASS**, **FAIL**, **UNKNOWN**.
Unknown is not pass. A row is PASS only where this document can name the check
that produced it — an assertion in a commit message is not a check.

---

## Release state

| | value | state |
|---|---|---|
| `origin/main` | see `git rev-parse --short origin/main` | — |
| Deployed SHA | `b4ff66debef9` (2026-07-31 deploy of the merged B3/B5/B6/B7 work) | **PASS** — `/health` |
| Deployed == main | **yes** (code); docs-only commits may sit ahead | **PASS** — `/health.commit` == `origin/main` |
| Schema applied / expected | `metrics001` / `metrics001` | **PASS** — `/health.schema.in_sync` |
| Enum config valid | `TURN_COORDINATOR_MODE`, `NUTRITION_RESOLVER_MODE` both `env_valid: true` | **PASS** |
| Resolver mode | `live`, intentional | **PASS** |
| One alembic head | `alembic heads` → single | **PASS** |
| Rollback rehearsed | never performed | **UNKNOWN** |

> Deployment is a **manual** action in the Render dashboard. `main` moving is
> not a deploy. Verify with `python scripts/release_check.py <sha>` and then
> `/health`.

---

## 1-3. Food, exercise, weight logging

| check | state | evidence |
|---|---|---|
| Row + ledger event commit atomically | **PASS** | `test_a_row_and_its_history_commit_together.py` |
| Idempotency claim completes in the same transaction | **PASS** | `test_a_crash_cannot_replay_the_meal.py` (4/7 fail on parent) |
| Stale claim reconciles before takeover | **PASS** | same suite |
| Corrupt state fails loudly | **PASS** | `IdempotencyCorrupt` |
| Weight has ledger-backed history | **PASS** | `domain="weight"`, `previous_weight_kg` preserved |
| All three carry a request trace | **PASS** | `mutation_inventory.py` → 3 complete |
| Multi-connection race proven | **PASS** | ran in CI on `a4f0b18`: `postgres:16` service initialized (step 2) and tests green (step 9). CI now **errors** rather than skips if `TEST_POSTGRES_URL` is absent, so this cannot silently stop being checked |
| Food decision quality | **PASS** | `eval_food_matrix` 22/22 × 3 reps, 0 flaky |
| Counted-portion accuracy | **FAIL → mitigated** | label serving now persisted (`serving001`); **fixes second-and-later logs only**, unverified in production |

## 4. Corrections and deletion

**UNKNOWN.** `PATCH/DELETE /{entry_id}` show turn id and ledger event but no
idempotency and no trace. Not evaluated for replay safety.

## 5. Turn traceability

| check | state | evidence |
|---|---|---|
| Quick-log surfaces traceable | **PASS** | 3/3 complete |
| All user-visible mutations traceable | **FAIL** | **3 of 60** on the full contract |
| Production turns carry a build stamp | **PASS** | 18h trace: 1/77 missing reasoning |
| Production turns carry a turn id | **FAIL** | **10/77 missing** — web (5), proactive (4), ios/text (1) |

## 6. Idempotency and replay

**PASS for food, exercise, weight.** **UNKNOWN elsewhere** — 48 of 60
user-visible mutations have no idempotency policy at all.

## 7. Latency

**MEASURABLE (was UNKNOWN).** B5, branch `dvoskin/b5-latency-budgets` @
`472e8e6` (committed, not deployed). The instrumentation now exists; the numbers
still need a week of production rows. Full suite green at the SHA.

| check | state | evidence |
|---|---|---|
| Main turns emit a durable metric | **PASS** | `run_turn` now opens a `RequestTrace` at the turn boundary and writes one `turn_metrics` row per turn (was quick-log only, so main-turn latency was invisible in the table that outlives the logs — the exact reason the 2026-07-30 p50 regression went unexplained). `test_run_turn_writes_a_metric_row_for_the_turn` |
| Stage breakdown, not just total | **PASS** | `core/llm.chat` + `chat_follow_up` record `llm`, `execute_tool_calls` records `tools`, ambiently via a contextvar — so the breakdown needs no argument threaded through the 3,000-line pipeline. Duplicate stages sum (three model calls → one `llm` figure) |
| Telemetry can't corrupt the turn | **PASS** | the row is written on an ISOLATED session (`persist_isolated`), never the turn's, so it can neither commit half a turn nor roll back with it. Never raises |
| A failed / slow turn is still recorded | **PASS** | the trace closes in a `finally`, `outcome=error:<Class>` on a raise; a turn that hits the 6s deadline is the one whose row has to survive. `test_run_turn_records_an_error_outcome_and_still_persists` |
| Budgets scored | **PASS (provisional)** | `scripts/latency_report.py` scores p95 against `BUDGET_P95_MS` — quick-log 2.5s, `turn` 6s, `turn:log` 5s. The turn budgets are PROVISIONAL (set at the deadline; calibrate down once real rows exist). `test_latency_report.py` |
| The numbers themselves | **UNKNOWN — needs prod** | the report reads `DATABASE_URL`; a clean checkout has no rows. The +54% p50 regression is now MEASURABLE but not yet explained — there is no production data through the new writer yet. Danny runs `python scripts/latency_report.py --hours 168` a week after deploy |

The 6s hard cap (`core/deadline`) still enforces at runtime and is unchanged —
B5 adds the durable MEASUREMENT the cap never produced, not a second cap.

## 8. Voice consistency

**MEASURED (was UNKNOWN).** B6, branch `dvoskin/b6-voice-renderer` @ `e97945d`
(committed, not deployed). There is now a corpus, an evaluation, and a single
renderer. Full suite green at the SHA.

| check | state | evidence |
|---|---|---|
| One renderer, not three that drift | **PASS** | `core/voice` owns the character rules AND sentence case; `platform._sanitize_bubble` and `log_voice._clean` both delegate to it. They had drifted — `_clean` collapsed an en dash so "12–13%" survived on one path and not the other; that is now one implementation |
| Sentence case enforced at the root | **PASS** | the seam (`Response.from_text`, streaming and not) capitalizes every bubble's lead. The 2026-06-15 decision was enforced only in the prompt; `handlers/onboarding.py` still shipped "good to meet you" and proactive shipped "morning {name}." The audit shows the seam fixes **7/7** lowercase leads in the corpus, 0 shipped. Kill switch `VOICE_SENTENCE_CASE` |
| Voice is measurable | **PASS** | `core.voice.check_voice` is a linter (em dash, tilde, lowercase lead, joke emoji, helpdesk filler, exclamation pile, robotic ack, leaked marker). `scripts/voice_audit.py` runs it over the corpus pre/post seam; `tests/test_voice.py` freezes the result |
| A voice corpus exists | **PASS (deterministic)** | `tests/corpus/voice_corpus.py` — the bubbles the product ships verbatim (recovery, onboarding, proactive) mirrored from source, plus curated representative turns and 4 negative controls. NOT sampled from prod: the only tool that did that writes beta transcripts into this PUBLIC repo and is banned |
| Structured message path | **PASS** | `CoachMessagePlan` + `render` — a composer names intent (read / receipt / nudge / ask) and the renderer voices it, in voice by construction. Available; adoption by the composers is incremental |
| Every shipped string in voice | **FAIL → 1 known** | one shipped violation the seam cannot fix (it does not rewrite emoji): the proactive city ask ships 😅. **Danny's call** — the main prompt is self-contradictory on joke emoji (an approved example at `arnie.py:2378` uses 😂; a rule at 2533 bans it). Frozen by `test_only_known_shipped_finding_is_the_city_nudge_joke_emoji` |

Not done: the LLM path still generates its own prose under the prompt anchor
(the renderer normalizes it at the seam but does not compose it), and the 20+
composer files have not adopted `CoachMessagePlan` — the linter measures that
gap, it does not close it.

## 9. Proactive delivery

**PASS** (was FAIL — the FAIL text below described the pre-B3 state and was
never refreshed).

| check | state | evidence |
|---|---|---|
| Sent is distinguishable from failed | **PASS** | `_send` returns a `DeliveryResult` — suppressed / accepted / failed / invalid-destination — not a swallowed error (core/delivery, B3) |
| Every attempt is recorded | **PASS** | `_record_delivery` writes one `delivery_attempts` row per send, statuses per `core/delivery`; `test_a_proactive_row_means_it_arrived` |
| History means it arrived | **PASS** | the `conversation_logs` proactive row is gated on acceptance (B3) |
| Cadence counts DELIVERIES, not generated messages | **PASS (this branch)** | `_within_proactive_budget` read `conversation_logs`; it now counts `delivery_attempts` with a TERMINAL_SUCCESS status, so a user whose pushes ALL fail is no longer rate-limited into silence — the exact incident `DeliveryAttempt` was built to end but the budget had never been migrated to. Branch `dvoskin/proactive-budget-delivery-attempts`, `test_proactive_budget_counts_deliveries.py` |

The budget was the last open question the 2026-07-31 handoff left on this
surface ("it reads the wrong table for the right answer"). Also hardened the
SQLite datetime-string case the query shared with `_user_spoke_recently`.

## 10. Administration and security

**PARTIAL PASS.** The pass ran (B7, branch `dvoskin/b7-admin-security` @
`5d75ce6`, committed not deployed); `scripts/endpoint_inventory.py` walks the
131-route live table and classifies auth, URL-borne credentials, and rate
limits — repeatable, and gated by `tests/test_endpoint_inventory.py` so a
regression fails CI instead of shipping. Full suite green at this SHA.

| check | state | evidence |
|---|---|---|
| Admin endpoints off the query string | **PASS** | all 12 `/admin*` were `?token=`; now `X-Admin-Token` header or a SESSION_SECRET-signed HttpOnly cookie. `?token=` survives only as a one-shot bootstrap that 303-redirects to a clean URL. `test_admin_auth.py` (11), inventory gate |
| Admin gate rate limited | **PASS** | `require_admin` fronts the token check with `core.ratelimit` (60/min/IP); a brute-force flood trips 429. `test_brute_force_is_throttled` |
| Session mint + pairing-code rate limited | **PASS** | were unbounded; now 30/min and 20/min per IP |
| Client IP correct behind the proxy | **PASS (needs env)** | limiter keyed on the proxy peer before — one shared bucket. `client_ip` reads `X-Forwarded-For` **iff** `TRUST_PROXY_HEADERS=true`. Danny must set it in the Render dashboard |
| Stripe webhook verified | **PASS** | `construct_event`; fails closed without the secret (pre-existing) |
| Telegram webhook | **PASS** | was a non-constant-time `!=` on the bot token; now `hmac.compare_digest` + an enforced `X-Telegram-Bot-Api-Secret-Token` when `TELEGRAM_WEBHOOK_SECRET` is set (registered in `main.py`). `test_webhook_signatures.py` |
| iMessage/BlueBubbles webhook | **FAIL → fixed, gated on deploy** | `verify_bb_signature` **failed open** when the secret was unset — a live probe on 2026-07-31 confirmed prod was accepting unsigned POSTs. Now **fails closed** (mirrors Stripe), dev escape hatch `IMESSAGE_WEBHOOK_ALLOW_UNSIGNED`. **Danny must set `BLUEBUBBLES_WEBHOOK_SECRET` on Render AND in BlueBubbles before deploying, or iMessage inbound 403s.** |
| Secure-by-default sign-in | **UNKNOWN — Danny** | `DEV_AUTH_ENABLED` defaults **true**; when true, `provider=device` mints a session for any identity with no credential. Pinned `false` in `render.yaml`, but the dashboard value is authoritative — verify it |
| `SESSION_SECRET` set in prod | **UNKNOWN — Danny** | unset → auth.py falls back to a **public** hardcoded dev secret and every session token + admin cookie is forgeable. Now declared in `render.yaml`; confirm the dashboard value |

Still open (scope, not this pass):

- **36 capability tokens still ride in the URL** — the iOS logging API
  (`/api/food/log?token=…`) and the dashboard/health capability URLs
  (`/dashboard/{token}`). Path/query tokens land in proxy access logs and
  `Referer`. Moving them to a header is a coordinated iOS+server change; the
  `/api/v1/*` surface already shows the target shape (Bearer session). Counted
  and frozen by `test_endpoint_inventory.py`.
- ⚠ `scripts/extract_replay_corpus.py` writes real beta-user transcripts into
  `tests/corpus/` on the stated assumption the repo is private. **It is not.**
  Do not run it.
- The secret-leak items (`.env.bak.*`, `_danny_live_day_http.py`) from the prior
  pass remain ignored on `feat/coach-card-microviz` @ `73a261b`; never committed.

## 11. Database and migrations

| check | state |
|---|---|
| One head | **PASS** |
| Head compiles offline against Postgres | **PASS** — CI step 7 |
| Full chain replays on SQLite | **FAIL, by design** — verify a new migration with `alembic stamp <parent>` then upgrade one step |
| Backup restore tested | **UNKNOWN** — never attempted |

## 12. Rollback readiness

**UNKNOWN.** Deletion of 47 branches is reversible via `archive/*` tags
(proven by restoring one). Application rollback has never been rehearsed.

---

## Open blockers

| # | blocker | state | owner |
|---|---|---|---|
| ~~B1~~ | ~~Deployed != main~~ | **CLOSED** — `b4ff66d` deployed 2026-07-31; `/health.commit` == `origin/main`. B7 posture confirmed LIVE by probe: unsigned `/imessage`→403, `/admin` no-creds→401. ⚠ verify real inbound iMessage still works (BLUEBUBBLES_WEBHOOK_SECRET on both sides) | — |
| B2 | Mutation contract coverage | **RESCOPED — 0 UNKNOWN, 20 Class A gaps left.** The old row ("57 of 60 off the contract") measured conformance to ONE contract and could only be improved by bolting claims and ledger events onto routes that should have neither. All 75 mutating routes now declare their class and policy in `core/mutation_policy.py`; `scripts/mutation_inventory.py --check` is a CI gate. Exit criterion is `--check --strict`. See `docs/SESSION_HANDOFF_0801_B2.md` | backend |
| ~~B3~~ | ~~Proactive delivery cannot distinguish sent from failed~~ | **CLOSED** — DeliveryResult + delivery_attempts (B3); cadence now counts delivered sends (`dvoskin/proactive-budget-delivery-attempts`) | — |
| ~~B4~~ | ~~`turn_id` missing on web + proactive~~ | **CLOSED** — closed on main before this session (parent handoff: "10/77 → 0"); pinned by `test_every_surface_names_its_turn.py`, green in the merged suite. Row was stale | — |
| B5 | Latency | **MEASURABLE** — main turns write turn_metrics with a stage breakdown, isolated from the turn; report scores p95 vs budgets. Numbers need a week of prod rows | backend + Danny (deploy + read) |
| B6 | Voice | **MEASURED** — one renderer (`core/voice`), sentence case enforced at the seam, linter + corpus gate. 1 known shipped finding (proactive 😅) pending Danny's voice call | backend + Danny |
| B7 | Admin/security | **PARTIAL PASS** — admin off query strings, gate + mints rate limited, Telegram/iMessage webhooks fail closed. Remaining: 36 capability tokens in URL (scope); 3 Danny env actions | backend + Danny |
| ~~B8~~ | ~~Multi-connection race unproven~~ | **CLOSED** — ran green on `a4f0b18` | — |
| B9 | Backup restore untested | UNKNOWN | ops |
| B10 | Rollback unrehearsed | UNKNOWN | ops |
| ~~B11~~ | ~~HealthKit workout contract mismatch (PR #7)~~ | **CLOSED** — the TypeError fix landed on main before this session (parent handoff "closed today"); pinned by `test_a_native_workout_actually_lands.py` + `test_apple_workout_ingest.py`, green in the merged suite. Row was stale | — |

**Controlled TestFlight beta:** defensible — mutation integrity on the three
logging surfaces is the part that corrupts user data, and it is now PASS.

**Broad launch: closer.** B3/B4/B5/B6/B7/B11 are all closed or measured and, as
of 2026-07-31, **deployed** (`b4ff66d`). **B2 is the remaining user-visible
correctness gap**, now measured properly: every mutating route declares the
contract it owes, zero are UNKNOWN, and 20 Class A routes are still short of
theirs.

⚠ **Correction to the previous entry, which called B2 "completeness, not a
data-loss bug".** That was wrong for at least one surface. A water entry
logged from the iOS Today tile wrote no ledger event, and `ledger_undo` takes
the last event unconditionally — so "undo that" after tapping the water tile
**deleted the user's previous meal**, a row they never mentioned. Silent, and
reachable from the primary iOS surface. Fixed in `b587fd8` and pinned by
`test_undo_after_a_pour_takes_back_the_pour_not_the_meal`, which fails on the
parent commit by planning `delete_food_entry`. Treat the remaining Class A
gaps as potential data-loss until each is checked, not as bookkeeping.

Remaining beyond B2: B5's
numbers need a week of prod rows to read; B9/B10 (backup restore, rollback) are
untested ops; and B7 left 36 capability tokens in URLs (scope) plus Danny env
confirmations (`BLUEBUBBLES_WEBHOOK_SECRET` — **verify real iMessage still
delivers** — `TRUST_PROXY_HEADERS`, `SESSION_SECRET`, `DEV_AUTH_ENABLED=false`).

---

## How to refresh this

```bash
python scripts/release_check.py $(git rev-parse HEAD)   # CI + live SHA
curl -s https://arnie.onrender.com/health               # deployed truth
python scripts/mutation_inventory.py                    # contract coverage
python scripts/endpoint_inventory.py                    # auth / URL-creds / rate limits
python scripts/voice_audit.py                           # voice: pre/post-seam violations
python scripts/latency_report.py --hours 168            # turn p95 vs budgets (needs prod DB)
python scripts/branch_triage.py                         # branch hygiene
```

Production data checks (18h trace, card rate, turn-id holes) need a prod
`DATABASE_URL`; they are not runnable from a clean checkout today, which is
itself an **UNKNOWN** worth closing.
