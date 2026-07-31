# Handoff — 2026-07-31

Read this, then `docs/MARKET_READINESS_SCORECARD.md`. Everything below is
verified, not remembered.

## Start here

```bash
curl -s https://arnie.onrender.com/health | python3 -m json.tool   # deployed truth
python scripts/release_check.py $(git rev-parse HEAD)              # CI + live SHA
python scripts/mutation_inventory.py                               # contract coverage
python scripts/branch_triage.py                                    # branch hygiene
python scripts/latency_report.py --hours 24                        # needs DATABASE_URL
```

`/health` is the authority on what is running. **Merged is not deployed** —
Render deploys are a manual dashboard action.

## The one thing that matters most

**13+ CI-green commits are undeployed.** Two of them fix things wrong in
production right now:

* every native HealthKit workout is dropped (`TypeError`, 4 args vs 3)
* proactive history records messages that never arrived, and the cadence
  budget counts them — so a user with failing pushes gets rate-limited into
  silence

Both fixed on main. Neither running. This is B1 and it is Danny's action.

## What was closed today

| id | thing | how it was proven |
|---|---|---|
| — | quick-log had no turn id, and double-taps wrote two rows | probe on deployed code: `2 rows, turn_id [None, None]` |
| G5 | food row and ledger event committed separately | crash test leaves no orphan |
| B3 | proactive could not tell sent from failed | `core/delivery`, history gated on acceptance |
| B4 | web + proactive turns had no id | 10/77 in an 18h window, now 0 |
| B8 | multi-connection race unproven | `postgres:16` in CI; errors rather than skips |
| B11 | HealthKit workouts never landed | the TypeError, pinned end to end |
| P0 | crash between domain commit and claim completion | reconcile against the ledger, never a timer |

## Live gotchas

* **`scripts/extract_replay_corpus.py` writes beta-user transcripts into the
  repo on the assumption it is private. The repo is PUBLIC. Do not run it.**
* Secrets were one `git add -A` from publication (`.env.bak.*`,
  `scripts/_danny_live_day_http.py` holds the prod `SESSION_SECRET`). Ignored
  now on `feat/coach-card-microviz` @ `73a261b`. Sweep untracked files for
  `API_KEY|SECRET|TOKEN=|postgres://` before committing.
* The full alembic chain **cannot** replay on SQLite. Verify a new migration
  with `alembic stamp <parent>` then upgrade one step, and check the CI
  offline-Postgres compile — `sa.inspect` must be guarded by
  `context.is_offline_mode()`.
* The suite is shuffled and **flakes**. Two confirmed today; one root-caused
  (module-level prompt build ran at collection). A red run that will not
  reproduce is a known shape — CI now emits the failing tests AND the seed as
  annotations, readable via the public check-runs API without a token.
* Run the **full** suite before pushing. Targeted runs keyed to the area you
  touched cannot catch a test failing where you did not think to look; that
  missed three times today.

## Next, in order

1. **B7 security** — admin/debug endpoint inventory, credentials out of query
   strings, rate limits, webhook signatures. Largest remaining closable item.
2. **B6 voice** — `CoachMessagePlan` + one renderer + a 150-turn corpus. Big
   enough to deserve its own session.
3. **B2** — 57 of 60 user-visible mutations are off the contract. Scope, not a
   bug; `mutation_inventory.py` ranks them.
4. **B9/B10** — backup restore and rollback rehearsal. Ops, needs Danny.

## Open questions nobody has answered

* `_within_proactive_budget` counts `conversation_logs`. Correct today only
  because those rows are now written on acceptance — it reads the wrong table
  for the right answer and should query `delivery_attempts`.
* The +54% p50 regression flagged 2026-07-30 is still unexplained.
  `turn_metrics` now makes it measurable; there is no data yet.
* Composite food: `composites.py` does not exist on main, yet
  `authority.py:439` ships "Estimated from its components". Extract from
  `claude/open-issues-composites-stall-usda-1ipqnu` (it carries the USDA
  ground-truth fixtures) onto a fresh branch.
