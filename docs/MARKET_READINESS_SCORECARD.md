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

**UNKNOWN.** No stage timings exist outside quick-log, no budgets are enforced,
and the +54% p50 regression flagged 2026-07-30 was never explained. One
observed symptom: `food composer model call failed: exceeded 6.0s of turn
budget` during the eval run.

## 8. Voice consistency

**UNKNOWN.** No voice corpus, no evaluation, no single renderer. Voice
ownership is spread across prompts, composers and deterministic fallbacks.

## 9. Proactive delivery

**FAIL.** `_send` swallows channel errors and returns no result, so a
conversation row means "we tried", not "it arrived". Generated / attempted /
accepted / delivered / failed are indistinguishable, and cadence is computed
from generated messages.

## 10. Administration and security

**PARTIAL PASS.** The pass ran (B7); `scripts/endpoint_inventory.py` walks the
131-route live table and classifies auth, URL-borne credentials, and rate
limits — repeatable, and gated by `tests/test_endpoint_inventory.py` so a
regression fails CI instead of shipping.

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
| B1 | Deployed != main | FAIL | Danny (manual deploy) |
| B2 | 57 of 60 user-visible mutations off the contract | FAIL | backend |
| B3 | Proactive delivery cannot distinguish sent from failed | FAIL | backend |
| B4 | `turn_id` missing on web + proactive | FAIL | backend |
| B5 | Latency unmeasured and unbudgeted | UNKNOWN | backend |
| B6 | Voice unevaluated, no single renderer | UNKNOWN | backend |
| B7 | Admin/security pass | **PARTIAL PASS** — admin off query strings, gate + mints rate limited, Telegram/iMessage webhooks fail closed. Remaining: 36 capability tokens in URL (scope); 3 Danny env actions | backend + Danny |
| ~~B8~~ | ~~Multi-connection race unproven~~ | **CLOSED** — ran green on `a4f0b18` | — |
| B9 | Backup restore untested | UNKNOWN | ops |
| B10 | Rollback unrehearsed | UNKNOWN | ops |
| B11 | HealthKit workout contract mismatch (PR #7) | FAIL | backend |

**Controlled TestFlight beta:** defensible — mutation integrity on the three
logging surfaces is the part that corrupts user data, and it is now PASS.

**Broad launch: NO.** B2, B3 and B11 are user-visible correctness, and B5–B6
are unmeasured rather than passing. B7 is now a partial pass — the admin surface
and both spoofable webhooks are closed — but it is **gated on three Danny env
actions** (`BLUEBUBBLES_WEBHOOK_SECRET`, `TRUST_PROXY_HEADERS`, and confirming
`SESSION_SECRET` + `DEV_AUTH_ENABLED=false`), and the iMessage fail-closed flip
will 403 inbound if the BlueBubbles secret is not set before the deploy.

---

## How to refresh this

```bash
python scripts/release_check.py $(git rev-parse HEAD)   # CI + live SHA
curl -s https://arnie.onrender.com/health               # deployed truth
python scripts/mutation_inventory.py                    # contract coverage
python scripts/endpoint_inventory.py                    # auth / URL-creds / rate limits
python scripts/branch_triage.py                         # branch hygiene
```

Production data checks (18h trace, card rate, turn-id holes) need a prod
`DATABASE_URL`; they are not runnable from a clean checkout today, which is
itself an **UNKNOWN** worth closing.
