# HANDOFF — for a PARALLEL session · 2026-08-17

> **Current as of 2026-08-17.** Sequencing authority is
> `docs/CANONICAL_MIGRATION_DIRECTIVE.md` §NEXT. **This document does not
> sequence anything** — it tells a second session how to work in this repo
> without colliding with the first. Read §NEXT for what to do; read this for how.

## WHERE THINGS STAND

```text
live (verify, never assume)   /health -> commit  == cd2b74a at time of writing
origin/main                   8443cb0            (one ahead of live)
CI                            GREEN. ci.yml runs the suite on every push to
                              main against a REAL Postgres service
cohort                        user 26, iOS only. general_settlement_reachable
backend                       A1–A12 FROZEN (§FREEZE)
OWNERSHIP                     20.2%   band `<40%` -> user 26 only
open engineering              P16 ✅ measured · P16b and P17 below
```

## ⛔⛔ FIVE THINGS THAT WILL BITE A PARALLEL SESSION

**1. The directive is 8,000 lines and it is the authority. Do not both edit it.**
Only the session that owns the tranche may edit `§NEXT`. Everything else records
findings in its own `docs/` file and links from there. A merge conflict inside the
execution authority is the worst possible place to have one.

**2. Any commit under `core/ skills/ api/ handlers/ db/` makes the directive
STALE WITHIN TWO DAYS, and CI goes red for it.**
`tests/test_the_directive_does_not_run_stale.py` compares the newest code-commit
date against the `Last reconciled YYYY-MM-DD` stamp; `MAX_LAG_DAYS = 2`. This has
already turned `main` red once, on a build that was live. **The fix is not to edit
the date** — re-read the board against what changed, correct it, then stamp what
you actually reconciled.

**3. Adding to the settlement backend requires editing the freeze manifest in the
same commit.** `tests/test_the_general_settlement_backend_is_frozen.py` pins the
constants by value, the coverage ladder's ORDER, and a manifest that IMPORTS each
enforcing gate. That is deliberate: changing a frozen value is allowed, drifting
into it is not.

**4. `NEXT` may not appear as an instruction anywhere but §NEXT.**
`tests/test_only_one_board_sequences_the_work.py` fails on `<- NEXT`,
`IMMEDIATE NEXT`, `NEXT SESSION` below §NEXT unless the line marks itself history.

**5. Git and deploy.** `git fetch` and verify the SHA before every push — cloud
sessions run in parallel. Pushing to `main` has deployed on its own and has also
sat undeployed for an hour; **read `/health`, do not infer.** Run
`scripts/release_check.py` before believing anything about CI — it reads the
check-runs API.

## HOW TO PROVE ANYTHING HERE

```text
suite        ../arnie/.venv/bin/python -m pytest tests/ -q -p no:randomly
             (no venv in this worktree — use ../arnie/.venv)
dual-engine  TEST_POSTGRES_URL=postgresql+psycopg://$USER@localhost:5432/<db>
             Postgres runs ~82 MORE tests than SQLite. An identical skip count
             on both means the switch did not take.
one tree     a suite run that straddles an edit measures NEITHER version. Diff
             the collected test ids between engines to prove one tree.
mutation     GREEN proves nothing. Break the line under test and require RED
             with the right failure NAME. Check the fixture can fail at all.
```

## THE SEQUENCE

### P16b — the meal-level rollup *(small, precise, do this first)*

P16 attributed **declining ITEMS**; ownership is a **MEAL** rate. The ranking is
by *recoverable ownership points*, and item counts are not points. Compute the
counterfactual per mechanism:

> for each declining structured meal, re-run `decide()` over its items with
> mechanism *M* treated as satisfied — count the meals that become `Supported`.

That number, divided by ordinary food-chat meals, is the ownership points
mechanism *M* recovers. Extend `scripts/measure_settlement_coverage.py` in place;
it already holds the meals, the verdicts and the session.

**Acceptance:** a table of `mechanism -> meals recovered -> ownership points`,
summing to no more than `100% - 20.2%`, recorded to
`data/corpus/settlement_coverage.json`. Expect PRODUCT to lead — 142 of 207
items — but **do not skip this to save an hour**: a mechanism spread thinly across
many multi-item meals recovers fewer points than its item count suggests.

### P17 — the PRODUCT rung / per-serving basis *(the tranche P16 chose)*

```text
142 of 207 declining items (69%)   TYPED:count_only_quantity
```

`assemble()` hard-codes PRODUCT to `None`, so every canonical rung is per-100g and
a count-only portion ("1 medium", "2 eggs", "a bar") cannot be scaled at all. The
predicate correctly refuses them — `decide()`'s mass branch exists because
canonical committed a corn-on-the-cob at a refusal. **The fix is to land a
per-serving basis, not to loosen the predicate.**

⚠ **`decide()`'s mass branch is the place PRODUCT earns its way back in**, and its
own comment says so: *"When PRODUCT gains a producer, this branch is where it
earns its place."* Editing that branch means editing the freeze manifest in the
same commit.

⭐ **67 of those 142 items are non-Latin — and that is a correlation, not the
cause.** Do not turn P17 into a non-English tranche. The defect is a missing
serving basis and it is language-neutral.

### Then

```text
re-measure ownership · check the rollout band · only then widen the cohort
```

### Runs in parallel safely — touches nothing frozen

```text
B-1.7b  materiality      changes WHEN the product asks, not what it can price;
                         needs no coverage argument
B-1.7c  composition
B-1.8   canonical repair PARKED and still a real defect. Do NOT weaken the
                         ownership firewall to make it look finished
B-2     messy / multi-food
```

## DO NOT

```text
loosen canonical eligibility to raise adoption
reintroduce heuristics
reopen legacy authority
widen the cohort merely because the canary passed
do the five oils because they are ready — the artifact decides 1.9% of real food
sequence by feature name; sequence by measured mechanism
```

## ⛔ AND QUOTE NO COVERAGE NUMBER WITHOUT ITS PREDICATE COMMIT

`36.9%` was published at `beac35a` (08-15), the count-only branch landed at
`951b90e` (08-16), and re-running the same instrument on the same window gave
**20.2%**. For a day, the program was being sequenced on a number the system could
no longer produce. Every coverage figure names the commit it was taken at, or it
is not a figure.

## OPEN, AND NOT MINE TO CLOSE

- **`turn_metrics.outcome` cannot report a native failure.** `_rt.done()` runs in
  the `finally` around `coordinator.run`, which never raises; `raise state.error`
  happens after the trace closed. Deferred on purpose — it moves the canary's
  measurement contract.
- **6 of 88 `meal_commits` rows for user 26 carry `created_at IS NULL`** despite
  `server_default=func.now()`. A12 fails closed on an unstamped row, so behaviour
  is safe; the NULLs have the shape of the `_migrate` Postgres gap.
- **Whether a day-clear should drop that day's claims** — a product decision.
- **`eval.yml`'s `battery` job failed at `eedacfd`** and is unexamined.
