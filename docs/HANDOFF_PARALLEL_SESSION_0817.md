# HANDOFF — for a PARALLEL session · 2026-08-17

> **Current as of 2026-08-17.** Sequencing authority is
> `docs/CANONICAL_MIGRATION_DIRECTIVE.md` §NEXT. **This document does not
> sequence anything** — it tells a second session how to work in this repo
> without colliding with the first. Read §NEXT for what to do; read this for how.

## WHERE THINGS STAND

⛔⛔ **NO MUTABLE STATE IS WRITTEN DOWN HERE, AND THAT IS THE SECOND LESSON THIS
FILE HAS LEARNED.** The first version of this block hard-coded
`origin/main 8443cb0` — and it was **already wrong in the commit that shipped
it**, because the same commit moved main. A handoff whose whole purpose is
"verify, never assume" cannot itself publish a SHA. Ask the system:

```text
origin/main    git fetch origin && git rev-parse --short origin/main
local vs main  git log --oneline origin/main..HEAD
live           curl -s https://arnie.onrender.com/health   -> .commit
CI             ../arnie/.venv/bin/python scripts/release_check.py
               (needs GITHUB_TOKEN; without it the checks read UNREADABLE,
                which is NOT the same as green)
ownership      data/corpus/settlement_coverage.json -> C_ownership_rate_pct,
               and read `predicate_commit` in the same file. A figure without
               its predicate is not a figure
```

What is STATIC, and therefore safe to write down:

```text
cohort         user 26, iOS only. general_settlement_reachable
backend        A1–A12 FROZEN (§FREEZE)
rollout        expansion needs BOTH ownership >= 40% AND B-1.8 closed (§NEXT)
sequencing     §NEXT in docs/CANONICAL_MIGRATION_DIRECTIVE.md — never here
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

## THE SEQUENCE IS NOT HERE

⛔ **Read `§NEXT` in the directive.** This document deliberately does not carry
the order, and it used to: on 2026-08-17 Danny re-sequenced the program — oils
moved back behind materiality, B-1.8 became a *gate* on cohort expansion rather
than a parallel lane, and B-2 moved behind the whole coverage track. Anything
restated here would have gone stale within the hour. **Two boards is the failure
the one-board rule exists to prevent, and a handoff is the easiest place to grow
a second one.**

What follows is METHOD for the two tranches at the head of that board — how to
run them, not whether to.

### P16b — the meal-level rollup ✅ RAN *(2026-08-17, method kept for re-runs)*

Ownership is a **MEAL** rate and item counts are not points. The counterfactual:

> for each declining structured meal, flip the fact mechanism *M* names on the
> items it stopped and re-run the REAL `decide()` over every item — count the
> meals that become `Supported`.

Implemented in `scripts/measure_settlement_coverage.py`
(`--freeze NAME` / `--population NAME`), which holds the meals, the verdicts and
the session. **Two traps it hit, both worth knowing before re-running it:**

⛔ **Satisfying a mechanism is not recovering an item.** Flipping `has_mass` on a
count-only item moves it PAST the mass branch and straight into the evidence
branches, where it can decline again. 142 count-only items sit in 89 meals, and
only 28 of those recover on mass alone.

⛔⛔ **Rank LOWER against LOWER.** The first version of the table banded PRODUCT
(mass only .. mass + evidence) while silently handing every IDENTITY mechanism
the optimistic end for free — which read as an inversion of P16 that was not
there. Each mechanism now carries both ends: LOWER is what the tranche literally
puts into `ItemFacts`, UPPER adds the evidence delivery might also bring.

⭐ It self-checks: under the UPPER flip every meal blocked by exactly one
mechanism must recover and every multi-mechanism meal must not, so the UPPER
recoveries must sum to the single-mechanism meal count exactly.

### Candidate P17 method — use ONLY if the measurement selects serving-basis evidence

⛔ **The measurement names the tranche; this document does not.** Read §NEXT for
what P16b actually selected, and re-read `settlement_coverage.json` if it has
been re-run since. What follows applies *if and only if*
`TYPED:count_only_quantity` is still the ranked mechanism.

`assemble()` hard-codes PRODUCT to `None`, so every canonical rung is per-100g and
a count-only portion ("1 medium", "2 eggs", "a bar") cannot be scaled at all. The
predicate correctly refuses them — `decide()`'s mass branch exists because
canonical committed a corn-on-the-cob at a refusal. **The fix is to land a
per-serving basis, not to loosen the predicate.**

⭐⭐ **AND THE BAND IS A DESIGN INSTRUCTION, NOT A FOOTNOTE.** A serving basis
that only supplies a scale factor recovers the LOWER end; one that arrives as an
evidence rung of its own recovers the UPPER. The gap between those two is larger
than every other mechanism combined, so *how* P17 is built matters more than
whether it ships.

⚠ **`decide()`'s mass branch is the place PRODUCT earns its way back in**, and its
own comment says so: *"When PRODUCT gains a producer, this branch is where it
earns its place."* Editing that branch means editing the freeze manifest in the
same commit.

⭐⭐ **AND THE NON-LATIN ROWS WERE TWO MECHANISMS, NOT ONE — CORRECTED 08-17.**
This section previously said the 67 non-Latin items were "a correlation, not the
cause", and that was half right in a way that mattered. Re-attributing by driving
the REAL normalizer over the frozen rows splits the old 142 into 84 genuine
counts and **51 rows stating a mass in Cyrillic** — `150 г`, `200 мл` — that the
unit parser does not read. Those 51 are 51-of-51 non-Latin and are NOT a serving
problem; no serving evidence would price them.

⛔ So the standing instruction holds for a better reason: do not turn P17 into a
non-English tranche, **because "non-English" spans two different defects at two
different layers**. Sequence by the mechanism the parser can be shown to hit.

⚠ **AND DO NOT READ THE UNIT-ALIAS FIX AS FREE COVERAGE.** It is 51 items and a
LOWER bound of **0.0 ownership points** — given a mass, those foods hit the
evidence wall immediately.

### What comes after P17 — go and read §NEXT

Re-measure, name the predicate commit, and let the *new* measurement pick the
next mechanism. ⛔ **Crossing 40% does not by itself permit a wider cohort:
B-1.8 gates the first band.** The bands and that gate live in the directive,
not here.

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
