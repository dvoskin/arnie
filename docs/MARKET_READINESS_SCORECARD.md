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
| B5 | Latency unmeasured and unbudgeted | UNKNOWN | backend |
| B6 | Voice | **MEASURED** — one renderer (`core/voice`), sentence case enforced at the seam, linter + corpus gate. 1 known shipped finding (proactive 😅) pending Danny's voice call | backend + Danny |
| B7 | Admin/security pass not started | UNKNOWN | backend |
| ~~B8~~ | ~~Multi-connection race unproven~~ | **CLOSED** — ran green on `a4f0b18` | — |
| B9 | Backup restore untested | UNKNOWN | ops |
| B10 | Rollback unrehearsed | UNKNOWN | ops |
| B11 | HealthKit workout contract mismatch (PR #7) | FAIL | backend |

**Controlled TestFlight beta:** defensible — mutation integrity on the three
logging surfaces is the part that corrupts user data, and it is now PASS.

**Broad launch: NO.** B2, B3 and B11 are user-visible correctness. B5 is still
unmeasured. B6 is now measured (voice has a renderer, a linter, and a corpus)
and B7 is a partial pass on its own branch — both are on unmerged branches
(`dvoskin/b6-voice-renderer`, `dvoskin/b7-admin-security`), so neither is in
`main` or deployed yet.

---

## How to refresh this

```bash
python scripts/release_check.py $(git rev-parse HEAD)   # CI + live SHA
curl -s https://arnie.onrender.com/health               # deployed truth
python scripts/mutation_inventory.py                    # contract coverage
python scripts/voice_audit.py                           # voice: pre/post-seam violations
python scripts/branch_triage.py                         # branch hygiene
```

Production data checks (18h trace, card rate, turn-id holes) need a prod
`DATABASE_URL`; they are not runnable from a clean checkout today, which is
itself an **UNKNOWN** worth closing.
