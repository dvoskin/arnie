# The release gate

**Status:** authoritative. A deploy that skips this is a deploy nobody can
reason about afterwards.

> ## ⛔ THE GATE IS CLOSED, AND HAS BEEN SINCE `17da24f` (recorded 2026-08-09)
>
> `release_check.py` exits 0 only on a deployable commit. **No commit on `main`
> is currently deployable**, because the full-suite gate below has failed on
> every one of them since 2026-08-06 — 50 commits, including `2a885603`.
>
> The cause is not a regression in any feature. `17da24f` dropped asyncpg from
> `requirements.txt` in favour of psycopg3, while `tests/test_a_full_day_of_food.py`
> (lines 288 and 318) still rewrites the engine URL *to* `+asyncpg`. The shared
> Postgres fixture therefore raises `ModuleNotFoundError` at setup, and every
> Postgres-backed test errors with it. Fixing it needs more than the URL: the
> same call passes `connect_args={"server_settings": …}`, which is asyncpg's
> shape — psycopg3 wants `options="-csearch_path=…"`.
>
> The `battery` gate is also red, for a different and benign reason:
> `ANTHROPIC_API_KEY` is unset and the job refuses rather than score a false
> failure. That refusal is correct behaviour and needs a secret, not a fix.
>
> **Why this is worse than a red build.** This document's own argument is that
> CI passing is "a fact sitting somewhere nobody reads at deploy time". A CI
> that has been red long enough to become background noise is the same failure
> one step further along — the signal still exists and has stopped meaning
> anything. Fifty commits merged during this window, including the whole
> canonical-pricer workstream, and the engine those changes most needed to be
> checked against is precisely the one that has not run.
>
> Nothing below this box is wrong. It simply cannot be exercised until the
> fixture is repaired, and that repair is the highest-priority item in the
> project right now.

Deploys are a human action in the Render dashboard. That is fine, but it means
CI passing is not a gate on its own — it is a fact sitting somewhere nobody
reads at deploy time. Two incidents in one week came from exactly that: five
audited fixes sat merged and undeployed for a day, and establishing which SHA
was actually running cost an hour of inference from behavioural markers.

## Before every deploy, one command

```bash
python scripts/release_check.py
```

It prints the commit, what `/health` says is live, and the state of that
commit's checks, then exits 0 only if it is deployable. `unknown` counts as not
deployable — a check nobody can read is not a check.

## What runs, and what each gate is for

| Gate | Runs on | Catches |
|---|---|---|
| Byte-compile | every push/PR | syntax and indentation errors before runtime |
| **Alembic one head** | every push/PR | two heads from parallel sessions — a deploy that dies in Render's release phase *after* a green build |
| **Head migration compiles offline vs Postgres** | every push/PR | the offline-mode class: `op.execute()` returns None there, so an unguarded `.rowcount` crashes the Postgres compile while every SQLite test passes |
| Full suite (shuffled order) | every push/PR | regressions; the shuffle is what surfaces cross-test cache leaks |
| **Food eval battery** | food-path PRs, nightly, on demand | the lane's DECISIONS — ask vs log, which item, whose numbers |

The battery is the one the unit suite cannot replace. Every behavioural
regression this project has shipped to users was green in pytest. It is not on
every push because it costs paid API calls and around ten minutes; it runs
where the decision matters and nightly, so drift in the model itself is caught
without anyone remembering to look.

If the battery ever runs without `ANTHROPIC_API_KEY`, every case fails auth and
the run reads as a catastrophic regression. That false score has cost a
debugging session here before, so the job now fails with a clear message
instead of reporting one.

## What Danny has to enable once (I cannot)

These are repository settings, not code:

1. **`ANTHROPIC_API_KEY` as an Actions secret** — Settings → Secrets and
   variables → Actions. Until it exists the battery workflow stops with the
   message above rather than scoring a false failure.
2. **Branch protection on `main`** — Settings → Branches → require the `test`
   check to pass before merging. Note this ends direct pushes to `main`, which
   is how the current workflow lands work; adopt it when the team is bigger
   than one, and rely on `release_check.py` until then.

## The rule

A commit is deployable when its checks are green. Not when the suite passed
locally, not when it looked fine — the record has to exist outside the head of
whoever wrote it. `release_check.py` exists so that record takes one command to
read, and `/health` exists so what is running takes one request to confirm.
