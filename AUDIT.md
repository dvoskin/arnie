# Arnie — Comprehensive System Audit (2026-05-30)

A full sweep of the codebase to find the highest-leverage places to strengthen the
foundation before adding more features. Findings are ordered by severity. Each has
**impact**, **evidence**, and a **concrete fix**. Nothing here was changed except
where noted under "Applied this pass" at the bottom.

Codebase: ~7,300 lines Python across 28 modules. Biggest: `api/app.py` (2,842),
`scheduler/proactive_scheduler.py` (940), `core/prompts/arnie.py` (743),
`bot/telegram_handler.py` (699), `bot/imessage_handler.py` (697).

---

## 🔴 P0 — Foundational risks (fix before scaling users/features)

### 1. SQLite has zero concurrency hardening → "database is locked" glitches
**Impact:** Telegram + iMessage webhooks both write concurrently (async). With
default SQLite settings, concurrent writers raise `OperationalError: database is
locked`. This is almost certainly behind a chunk of the intermittent "glitches"
users report — a log that doesn't save, a reply that errors out.
**Evidence:** `db/database.py` — `create_async_engine(DATABASE_URL, echo=False)`
with **no** `connect_args`, **no** `busy_timeout`, **no** WAL journal mode (verified:
0 occurrences of each). No global write lock anywhere.
**Fix (low risk, standard):** enable WAL + a busy timeout on every connection:
```python
from sqlalchemy import event
engine = create_async_engine(
    DATABASE_URL, echo=False,
    connect_args={"timeout": 30},   # wait up to 30s for the lock instead of erroring
)
@event.listens_for(engine.sync_engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")     # readers don't block the writer
    cur.execute("PRAGMA busy_timeout=30000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()
```
This alone will remove most lock errors.

### 2. User Profile Matrix + memory stored on EPHEMERAL disk → wiped every deploy
**Impact:** The adaptive per-user profiles AND legacy memory (the "Arnie learns you
over time" core value prop) are markdown files written to a **relative** `users/`
dir, not the persistent `/data` disk. Every Render deploy/restart wipes them. Users
effectively lose Arnie's accumulated understanding on each ship — feels like memory
loss, and is a likely contributor to "glitches."
**Evidence:** both `memory/profile_manager.py` and `memory/memory_manager.py` —
`USERS_DIR = Path("users")` (relative). `render.yaml` didn't point it at `/data`.
Local `users/<id>/arnie_memory.md` files exist in the working tree, confirming it
writes repo-relative.
**Fix:** `resolve_users_dir()` now derives the dir from the DB's persistent disk
(`/data/users` when DB is at `/data/arnie.db`), honors `ARNIE_USERS_DIR`, falls back
to `/tmp`. `render.yaml` sets `ARNIE_USERS_DIR=/data/users`; `users/` added to
`.gitignore`. **Applied this pass — see bottom.**

### 3. No retry/timeout on LLM calls → transient API blip = user-facing failure
**Impact:** A single momentary Anthropic hiccup (rate limit, 529, network) makes
Arnie reply "something went wrong, try again." With logging happening mid-turn,
it can also leave a tool executed but no confirmation sent.
**Evidence:** `core/llm.py` — 0 occurrences of retry/backoff/timeout. `_anthropic_chat`
calls `client.messages.create(**kwargs)` once, no `max_retries`, no request timeout.
**Fix:** construct the SDK client with `AsyncAnthropic(max_retries=2, timeout=30)`
and wrap `chat`/`chat_follow_up` in a small retry (2 attempts, short backoff) on
`APIStatusError`/`APIConnectionError`. Cheap, removes a whole class of glitches.

### 4. Thin test coverage for a system this stateful
**Impact:** ~2 test files for ~7,300 lines. This session alone surfaced a missing
migration (bot went fully down), a missing `return True`, drifted totals, and
several edits that silently failed — exactly the regressions a test suite catches.
A strong foundation needs a safety net before piling on features.
**Evidence:** only `tests/test_onboarding_targets.py` + `scripts/test_arnie.py`.
**Fix:** add `pytest` + an in-memory-SQLite fixture and cover the highest-risk pure
logic first (it's already very testable): `recompute_log_totals`, `is_generic_food_name`,
`resolve_send_target`, `resolve_timezone`, `_migrate` idempotency, the tool dispatch
happy-paths. Wire a GitHub Action to run them on push.

---

## 🟠 P1 — Scaling & reliability ceilings

### 5. SQLite caps you at a single instance
**Impact:** SQLite-on-a-disk means you can never run >1 web instance (Render
horizontal scaling, zero-downtime deploys). The migration scares this session
(channel_preference outage) are also a symptom of hand-rolled schema management on
SQLite.
**Fix (plan, not urgent):** migrate to **Postgres** (Render managed) + **Alembic**
for migrations. The code already uses SQLAlchemy async, so the data layer barely
changes. This unlocks scaling, real migrations, concurrent writers, and backups.
This is the single biggest "future-proofing" move.

### 6. Hand-rolled migrations instead of a framework
**Impact:** `db/database.py._migrate` is a manual `ALTER TABLE` list + the auto-heal
net I added. It worked, but a forgotten entry already took the whole bot offline
once. No down-migrations, no version history, no safety on type changes.
**Fix:** adopt **Alembic** (pairs with #5). Until then, the auto-heal pass is a
reasonable guard — keep it.

### 7. Telegram pipeline lacks the per-user lock iMessage has
**Impact:** `bot/imessage_handler.py` uses a per-user `asyncio.Lock` + debounce to
stop double-processing (the fix for duplicate onboarding questions). The Telegram
handler has **none** (verified: 0). If PTB delivers two updates for one chat
concurrently, you can get duplicate logs / races — the same bug class, unfixed on
one platform.
**Fix:** mirror the iMessage per-user lock + debounce in `telegram_handler`, or
confirm PTB's `concurrent_updates` is off so updates serialize per chat. Verify
before trusting.

### 8. No model fallback — Anthropic down = Arnie down
**Impact:** `_openai_chat` exists but nothing falls back to it. If Anthropic has an
outage, the whole bot is dead.
**Fix:** on repeated Anthropic failure, fall back to the OpenAI path (already built)
for that turn. Pairs with #3.

---

## 🟡 P2 — Maintainability & cost

### 9. `api/app.py` is a 2,842-line god-module
**Impact:** Routing, the entire inline HTML/CSS/JS dashboard, admin pages, Stripe,
Whoop, Apple Health, the iMessage webhook, and the audit/broadcast endpoints all
live in one file. Hard to navigate, easy to break (we hit anchor-mismatch edits
here repeatedly).
**Fix:** split into an `api/` package — `routes_dashboard.py`, `routes_admin.py`,
`routes_webhooks.py`, `routes_health.py` — and move the dashboard HTML/JS to a
real template/static file. Pure refactor, do it incrementally with FastAPI routers.

### 10. ~159 `except` blocks, many swallow errors silently
**Impact:** Heavy defensive `try/except … logger.warning/pass` makes real failures
invisible — "it just didn't log" with no trace. Directly lengthens every
glitch investigation.
**Fix:** audit the broad handlers; let truly-unexpected errors propagate to Sentry,
reserve `except: pass` for genuinely optional paths, and add user_id/context to the
logs that remain.

### 11. Two LLM calls per logging turn + a ~9.7k-token system prompt
**Impact:** Every food/exercise log does an initial call **plus** a follow-up call
(for the post-tool confirmation). At ~9.7k cached system tokens each, that's real
latency + cost as you grow. (The redundant *third* call was removed this session.)
**Fix:** consider a single-pass pattern (let the model write the confirmation in the
first turn using predicted totals, or compute the confirmation deterministically —
`deterministic_confirmation` already exists). Measure first; the follow-up does
improve quality, so A/B it rather than cutting blindly.

### 12. Observability is optional/uneven
**Impact:** Sentry only initializes if `SENTRY_DSN` is set; logging is plain INFO
with no per-request correlation id. Hard to trace one user's bad turn.
**Fix:** ensure `SENTRY_DSN` is set in prod; add a request/turn id to logs; emit a
metric on tool failures, LLM failures, and DB lock retries so glitches are visible.

---

## ✅ Confirmed healthy (no action)
- **No hardcoded secrets** in source — all via env vars. Good.
- Totals are now **derived** from entries (this session) — can't drift.
- Migration **auto-heal** net prevents a missing column from bricking the bot.
- Proactive messaging is correctly **gated** (kill switch + timezone gate + 9–9 window).
- Linking dedup + channel preference correctly route one message per user.

---

## Recommended order of execution
1. **#1 SQLite WAL/busy_timeout** (1 hr, removes lock glitches) ← do first
2. **#2 profile dir → /data** (done this pass) + set env var
3. **#3 LLM retry/timeout/fallback** (#8) (half day, removes API-blip glitches)
4. **#7 Telegram per-user lock** (half day)
5. **#4 test suite + CI** (1–2 days, the real foundation)
6. **#5/#6 Postgres + Alembic** (2–3 days, unlocks scale) — the big one
7. **#9 split app.py / #10 error audit / #11 cost** (ongoing cleanup)

---

## Applied this pass (the 3 safest, highest-impact, fully-tested P0 fixes)
- **P0 #1 — SQLite concurrency:** WAL + `busy_timeout=30000` + `synchronous=NORMAL`
  on every connection (+ `connect_args timeout=30`); removes the "database is
  locked" glitch class under concurrent Telegram/iMessage webhooks. Guarded behind
  an is-sqlite check so a future Postgres URL is unaffected. (`db/database.py`)
- **P0 #2 — durable user memory:** `resolve_users_dir()` puts per-user profile +
  memory files on the persistent disk (`/data/users`) instead of ephemeral
  `./users`; survives deploys. `render.yaml` sets `ARNIE_USERS_DIR`; `users/`
  gitignored. (`memory/memory_manager.py`, `memory/profile_manager.py`)
- **P0 #3 — LLM resilience:** Anthropic client now `max_retries=3, timeout=45`
  (SDK-native backoff on 429/500/529/connection) so a transient blip retries
  instead of surfacing as a user error mid-turn. (`core/llm.py`)

All three unit-tested locally (pragmas active, dir derivation + override, full
init_db under WAL, client config) and committed together for easy review/rollback.

## Left for your review (higher-risk or larger — not done unsupervised)
#4 test suite + CI · #5 Postgres · #6 Alembic · #7 Telegram per-user lock parity
(note: a debounce exists but no per-user asyncio.Lock like iMessage has — verify) ·
#8 model fallback to the existing OpenAI path · #9 split the 3,046-line `api/app.py`
· #10 audit the 22 `except…: pass` swallow sites · #11 LLM cost (2 calls/log turn,
~9.7k-token cached prompt) · #12 observability (ensure SENTRY_DSN set, add turn ids).
Recommended order is in the section above. Also: pin `requirements.txt` (0 of 15
deps are version-pinned — a transitive bump could break a deploy unpredictably).

---

## Foundation batch — final status (2026-05-31)

Done, pushed, and verified (96 tests pass; all modules boot-import clean):
- **#4 Test suite + CI** — tests/ (12 files, 96 tests) on in-memory SQLite built
  from the real models + _migrate; .github/workflows/ci.yml (byte-compile +
  pytest on Py3.14); pytest.ini (--import-mode=importlib, required because the
  repo path contains a space).
- **#7 Telegram per-user lock** — _tg_pipeline_locks serializes handle_text's
  pipeline per user (parity with iMessage); message_debounce hardened to never
  interrupt an in-flight runner (test_debounce.py).
- **#8 Model fallback** — core/llm.chat() falls back to OpenAI when Anthropic
  fails and OPENAI_API_KEY is set; chat_follow_up() returns "" on failure so the
  caller uses deterministic_confirmation (test_llm_fallback.py).
- **#10 Silent-except audit** — benign sites (import guards, asyncio task-cancel,
  ValueError parse fallbacks) left; hot-path ones (reactions, follow-up, insights
  send, profile-clear) now log.
- **requirements.txt** — all 15 runtime deps pinned to installed/prod versions
  (+ pytest/pytest-asyncio dev pins).

Deferred (safe plan in #9 above):
- **#9 split api/app.py** — high regression risk, no user-facing benefit; do it in
  a clean tooling session with the per-step gates (route count stays 25, tests
  green after each extraction).

Next session (user agreed):
- **#5 Postgres + #6 Alembic** — real migrations, concurrent writers, horizontal
  scaling. Data layer is already SQLAlchemy-async, so it's mostly config + an
  Alembic baseline.
