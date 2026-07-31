# Deployed state — 2026-07-31

Read at 2026-07-31 from `https://arnie.onrender.com/health` (HTTP 200) and from
`origin` after `git fetch --prune`. Every line is labelled **confirmed**,
**inferred**, or **unknown**. Nothing here is asserted because it exists on
`main`.

---

## 1. The headline

**Production is at `433cdf39f2d0`, which IS the tip of `origin/main`.**

The starting hypothesis for this pass — "deployed `27d6f7b`, main ~8 commits
ahead" — was true when it was written and is **false now**. A deploy has
happened since; `27d6f7b` is 8 commits behind the current tip. There is no
undeployed backend drift to close.

| Fact | Value | Status |
|---|---|---|
| Deployed commit | `433cdf39f2d0` | **confirmed** — `/health` |
| Deployed branch | `main` | **confirmed** — `/health` |
| `origin/main` HEAD | `433cdf39f2d0f3909b247d69369ac4e64a761f` | **confirmed** |
| Deployed == main tip | yes | **confirmed** |
| Local worktrees | 37 commits BEHIND `origin/main` | **confirmed** |
| Alembic heads on main | one: `pendinguniq001` | **confirmed** — `alembic heads` |
| Alembic revision APPLIED in prod | — | **unknown** (§4) |

> The local checkouts being 37 behind is a working-copy hazard, not a
> production one. `Code Learn/arnie` is on `feat/coach-card-microviz` with 101
> dirty files; this work was done in a fresh worktree off `origin/main`.

## 2. Effective production configuration

Straight from `/health`. `env_set` distinguishes an explicit dashboard value
from a code default — the distinction that makes the drift in §3 visible.

| Flag | Effective | env_set | Status |
|---|---|---|---|
| `TURN_COORDINATOR_MODE` | `new_observe` | true | **confirmed** |
| `NUTRITION_RESOLVER_MODE` | `shadow` | true | **confirmed** |
| `resolver_owns_committed_values` | `false` | — | **confirmed** |
| `FOOD_IDENTITY_ASK` | `false` | false | **confirmed** |
| `FOOD_COMPOSER` | `true` | true | **confirmed** |
| `FOOD_COMPOSER_MODEL` | `claude-sonnet-5` | — | **confirmed** |
| `fast_log_voice` | `true` | — | **confirmed** |
| `log_voice_model` | `claude-sonnet-5` | — | **confirmed** |
| `TURN_COORDINATOR_OBSERVE_DEEP` | — | — | **unknown** — documented in `render.yaml`, reported by nothing |

## 3. Configuration drift — the resolver is not doing what the repo says

`render.yaml` (lines ~57-62) says, in a comment dated by name and date:

> *"Nutrition resolver LIVE for ALL users (Danny 2026-07-25): empty allowlist =
> everyone."*  → `NUTRITION_RESOLVER_MODE: live`

**Production reports `shadow`, with `env_set: true`.**

Traced through `skills/nutrition/canary.py:242`, the gate is ordered
`halted → not live → allowlist → canary → …`, and it returns `False` at the
second line for any mode that is not `live`. So:

- the nutrition resolver **does not own committed nutrition values in
  production**;
- the legacy path owns them;
- every behaviour gated behind resolver ownership is **inert**, including the
  source/confidence tracking that Phase 5 of this pass is meant to build on.

This is the exact failure mode the pass exists to catch: the capability is
merged, documented as live, and switched off in the only place that counts.
`render.yaml` is reference-only (the service is configured manually in the
Render dashboard and Render never reads the file), so the file could not have
corrected itself — but nothing else reported the disagreement either.

**Not yet determined:** whether `shadow` is a deliberate rollback that the
comment outlived, or a value that was never promoted. That is a question for
Danny, not something to infer from the repo. **Do not flip it** without
knowing which.

## 4. What is NOT knowable from here, and why

| Unknown | Why | What would close it |
|---|---|---|
| Applied alembic revision in prod | No endpoint reports it; no DB access from this host | PR 1 (below) |
| Whether `preDeployCommand` is configured | `render.yaml` is documentation, not blueprint-managed; the dashboard is the real config | Render dashboard, or PR 1 |
| `turn_id IS NULL` counts in prod `ledger_events` | No `DATABASE_URL` for prod in this environment | `DATABASE_URL`, or a reconciliation job |
| PR #67 contents | No `gh` CLI; repo is private | `gh` install + token, or a fetched ref |
| Per-service revision parity | See below | — |

**Service topology (inferred, high confidence):** `render.yaml` declares one
Python web service, `arnie-bot`, with `startCommand: python main.py`, plus a
static `arnie-landing`. `main.py` starts uvicorn **and** the Telegram
application in the same process (webhook mode in production, polling locally).
No separate worker, scheduler, or webhook service is defined anywhere in the
repo. So "do all production services run the same revision" is trivially
**yes — there is one process**. This is worth stating plainly because it also
means there is no rolling-deploy window in which two revisions coexist, which
simplifies the migration-safety rules in Phase 12 considerably.

## 5. Deployed-vs-main surface matrix

`main == deployed`, so the "deployed commit" column is `433cdf3` for every
row and is omitted. What varies is whether the path has a turn, an idempotency
mechanism, and a trace.

| Surface | Entry point | Turn envelope | Idempotency | Ledger event | turn_id on event |
|---|---|---|---|---|---|
| iOS chat | `api/chat.py` | yes — `make_turn_id` from client msg id | `ConversationLog.idempotency_key` (per send) | yes | yes |
| Telegram | `bot/telegram_handler.py` | yes | text-window collapse | yes | yes |
| **iOS quick-log food** | `api/quick_log.py` | **none** → **fixed here** | **none** → **added here** | yes | **NULL** → **fixed** |
| **iOS quick-log exercise** | `api/quick_log.py` | **none** → **fixed here** | **none** → **added here** | yes (in `add_exercise_entry`) | **NULL** → **fixed** |
| **iOS quick-log weight** | `api/quick_log.py` | **none** → **fixed here** | upsert by (user, day, source) | **none** | n/a |
| Dashboard edit | `api/food_edit.py` | joined at `c1bd5c9` (D4) | — | yes | yes |
| Proactive | scheduler | partial (audit: 79 turns unreasoned) | — | n/a | — |

Rows marked **fixed here** are the subject of §6.

## 6. What this pass changed

See `docs/HARDENING_JOURNAL.md` for the append-only record.

---

*Method note: production was treated as the primary source throughout.
Where production could not be read, the row says `unknown` rather than
carrying a value inferred from `main`.*
