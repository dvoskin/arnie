# Market-readiness scorecard

**Verified: 2026-07-31.** Three states only: **PASS**, **FAIL**, **UNKNOWN**.
Unknown is not pass. A row is PASS only where this document can name the check
that produced it — an assertion in a commit message is not a check.

---

## Release state

| | value | state |
|---|---|---|
| `origin/main` | see `git rev-parse --short origin/main` | — |
| Deployed SHA | `26e36539c86e` at last read | **PASS** — `/health` |
| Deployed == main | **no**, main has moved since | **FAIL** — redeploy required |
| Schema applied / expected | `serving001` / `serving001` | **PASS** — `/health.schema.in_sync` |
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

**UNKNOWN.** No voice corpus, no evaluation, no single renderer. Voice
ownership is spread across prompts, composers and deterministic fallbacks.

## 9. Proactive delivery

**FAIL.** `_send` swallows channel errors and returns no result, so a
conversation row means "we tried", not "it arrived". Generated / attempted /
accepted / delivered / failed are indistinguishable, and cadence is computed
from generated messages.

## 10. Administration and security

**UNKNOWN**, with one **FAIL** already found and fixed locally:

- `.env.bak.20260727` (bot token, two API keys, prod `DATABASE_URL`) and
  `scripts/_danny_live_day_http.py` (prod `SESSION_SECRET`) were untracked but
  **not ignored**, in a **public** repository. Now ignored on
  `feat/coach-card-microviz` @ `73a261b`. Never committed — verified.
- ⚠ `scripts/extract_replay_corpus.py` writes real beta-user transcripts into
  `tests/corpus/` on the stated assumption the repo is private. **It is not.**
  Do not run it.
- Admin/debug endpoint inventory, rate limits, webhook signatures: not started.

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
| B1 | Deployed != main | FAIL | Danny (manual deploy) |
| B2 | 57 of 60 user-visible mutations off the contract | FAIL | backend |
| B3 | Proactive delivery cannot distinguish sent from failed | FAIL | backend |
| B4 | `turn_id` missing on web + proactive | FAIL | backend |
| B5 | Latency | **MEASURABLE** — main turns write turn_metrics with a stage breakdown, isolated from the turn; report scores p95 vs budgets. Numbers need a week of prod rows (`dvoskin/b5-latency-budgets`) | backend + Danny (deploy + read) |
| B6 | Voice unevaluated, no single renderer | UNKNOWN | backend |
| B7 | Admin/security pass not started | UNKNOWN | backend |
| ~~B8~~ | ~~Multi-connection race unproven~~ | **CLOSED** — ran green on `a4f0b18` | — |
| B9 | Backup restore untested | UNKNOWN | ops |
| B10 | Rollback unrehearsed | UNKNOWN | ops |
| B11 | HealthKit workout contract mismatch (PR #7) | FAIL | backend |

**Controlled TestFlight beta:** defensible — mutation integrity on the three
logging surfaces is the part that corrupts user data, and it is now PASS.

**Broad launch: NO.** B2, B3 and B11 are user-visible correctness. B5, B6 and
B7 are no longer unmeasured — each has a harness and a gate on its own unmerged
branch (`dvoskin/b5-latency-budgets`, `b6-voice-renderer`, `b7-admin-security`)
— but none is in `main` or deployed, and B5's numbers still need a week of
production rows to read.

---

## How to refresh this

```bash
python scripts/release_check.py $(git rev-parse HEAD)   # CI + live SHA
curl -s https://arnie.onrender.com/health               # deployed truth
python scripts/mutation_inventory.py                    # contract coverage
python scripts/branch_triage.py                         # branch hygiene
```

Production data checks (18h trace, card rate, turn-id holes) need a prod
`DATABASE_URL`; they are not runnable from a clean checkout today, which is
itself an **UNKNOWN** worth closing.
