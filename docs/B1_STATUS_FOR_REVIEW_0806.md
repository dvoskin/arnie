# Arnie canonical migration — status for team review

**2026-08-06.** Production `4535d1e`, schema `b1obs002`, in sync.
Test suite 7884 passing on SQLite and 7884 on Postgres.

---

## The one-paragraph version

The backend migration for conversational food logging is **complete and proven
in production**. Arnie can now ask a clarifying question, take durable
ownership of that question, apply the user's answer, and commit the meal
through a single authoritative path — with no duplicate writes, no false
confirmations, and no fallback to the old system once it has taken ownership.
Four production defects were found and fixed today, three of them by tooling
rather than by a user losing data. **We are no longer building; we are
collecting evidence.** The next decision — how good our suggested portions
actually are — is a product question, and the instrumentation to answer it went
live today.

---

## Where we stand

### Done and production-proven

| milestone | what it means |
|---|---|
| **B-1** | One clarification question, owned end to end: asked, persisted, answered, committed. Verified against real database rows, not reply text. |
| **B-1.75** | The user's answer is the only authority on quantity. Previously the system could quietly price a meal from its own earlier guess. |
| **D2** | A test harness that replays real multi-turn conversations locally. It found a live data-loss bug on its first run. |
| **D3** | Every safety case — stale answers, cancelled operations, corrupt state, database failure — proven as an automated gate rather than by hand. |
| **Presentation** | The question the user is shown is now provably the question the system stored. |

### Current phase: evidence collection

Rollout is deliberately **one internal user**, 0% of traffic. That is not
caution about stability — the backend is stable. It is because the remaining
question is whether the *suggestions* are good, and that can only be answered
by watching real usage.

---

## What today cost, and what it bought

Four production defects, in the order found:

1. **Two meals silently lost.** A completed question kept "owning" the
   conversation for 30 minutes, so the next unrelated meal was read as an
   answer to it. The user was told both were logged. Neither was.
2. **An unanswered question owned the conversation indefinitely.** Same failure
   through a different door — found by the new harness on its first run, before
   any user hit it.
3. **The user's stated amount did not drive the calories.** Worse than not
   scaling: which number won *flipped* depending on what the user answered.
4. **The system asked a question it had not stored.** It computed "how much?"
   with three portion options, and the user was shown "how was it cooked?"

**The pattern behind all four is the same and worth naming for the team:** each
shipped with a green test suite, because the test constructed the situation we
expected rather than sampling the situation that occurs. 204 tests covered this
feature. Not one of them sent an unrelated message after a question was
answered — which is the exact sequence that lost the meals.

**Three measuring instruments were also found to be lying by silence** — each
reported "nothing happened" when it meant "I could not read that." One cost a
full day of misdiagnosis. All three are fixed, and one now has a test that
scans the codebase and proves the instrument can report every signal we emit.

---

## Standing concerns

Ordered by how much they could cost us.

### 1. We cannot yet tell a good suggestion from a bad sentence

The measurement about to run asks: when we suggest portions, do people accept
them or type their own? Typing their own is supposed to mean our suggestions
were wrong. But it could equally mean the *question was phrased awkwardly* —
and the current phrasing is a placeholder written today.

**Risk:** we spend the observation window producing a number we cannot
interpret. **Mitigation:** a wording pass before the window fills, with a
version stamp so old and new phrasing are comparable. *Decision needed —
see below.*

### 2. Our suggestions have never once come from the user's own history

Across every question asked so far, the portion options came from a generic
food ontology and never from what this user has actually logged before.
The sample is far too small to conclude anything — but it is the single most
important thing to watch, because "we suggest what you usually eat" is a
materially better product than "we suggest a typical portion."

The instrumentation deliberately separates **never offered** (a matching
problem) from **offered and ignored** (a ranking problem). Those are different
engineering projects and one number would have hidden which.

### 3. Arnie currently speaks in two voices

Turns handled by the new path use a fixed template; turns still on the old path
are composed by the language model. The assistant sounds different depending on
internal routing the user cannot see. Cosmetic today, but it will not survive
wider rollout.

### 4. The old path still logs duplicates

Observed today: the legacy lane re-logged a meal that was already recorded. The
new path declined that turn correctly. This is in the code B-1 is designed to
replace, and it is an argument for finishing the migration rather than a reason
to slow it.

### 5. A safety net whose silence we cannot explain

We have a detector for exactly the "claimed to log, logged nothing" failure. It
fires correctly in tests. It did **not** fire on the two production turns where
that failure actually occurred, and the diagnostic column that would explain
why is empty even on turns that succeeded. Until we know why, it cannot be
counted as protection.

### 6. Our tests could not see database drift *(fixed today, worth knowing)*

Every test built its database from the application's code; production builds it
from migration files. The two were never compared. A default value promised by
the code and missing from the migration was therefore correct in every test and
absent in production — which silently disabled response-time measurement. A new
test now compares both, and found a second instance of the same defect on its
first run.

---

## Next steps

| # | step | status |
|---|---|---|
| 1 | Deploy the instrumentation fixes | ✅ **done today** — verified live |
| 2 | Wording pass on the clarification question | **decision needed** |
| 3 | Run the observation window | ready; collecting |
| 4 | Analyse suggestion quality, history, free-text reasons, repairs | after 3 |
| 5 | Build the iOS structured interface (B-1b) | after 4 |
| 6 | Widen rollout 1% → 5% → 25% → 100% | after 5 |
| 7 | Delete the old clarification path | after 6 |
| 8 | Extend to more question types, then multi-item meals | after 7 |

**Deliberately not doing yet:** building the iOS chip interface. It would mean
investing client work in suggestions we have not validated. If the window shows
the suggestions are weak, that interface gets redesigned — better to learn first.

### The decision needed

**Improve the question's wording before collecting data, or collect first and
treat current wording as the baseline?**

- *Improve first:* roughly an hour; removes a known ambiguity from the primary
  measurement. Only one observation exists so far, so nothing is lost.
- *Collect first:* no delay, but the headline number may be uninterpretable.

Recommendation: **improve first.** The same reasoning as fixing a scale before
weighing something, rather than after.

---

## A rule adopted today

> **Measure before generalize.** No suggestion generator, candidate source,
> interaction pattern or interface refinement expands until production
> telemetry demonstrates where users actually succeed or fail.

This is written into the migration directive as a standing constraint. It is
the rule the whole migration was already following implicitly, and every defect
found today came from breaking it somewhere — building on an assumption that
looked like evidence.

---

*Detail: `docs/CANONICAL_MIGRATION_DIRECTIVE.md` (sequencing authority, with the
full status board and every open finding) · `docs/B1_PRODUCTION_LOG_0805.md`
(incident-level engineering detail).*
