# HANDOVER — the duplicate turn, 2026-08-16

**Deployed state: `main` = `e2d732d`.** Five gates open, cohort = user 26, iOS
only. Board is clean: `#3013` cucumber 20 kcal, `#3014` white rice 365 kcal.

## ✅ CLOSED — THE DUPLICATE'S REPLY WAS THE COORDINATOR'S FAILURE FLOOR

**A repeated food message answered "Something went sideways on my end. Resend
that…" — an instruction to retry the one thing that cannot succeed.**

```text
02:39:46  7864ms  8f5501d  '100g of white rice'  -> logged 365 cal (#3014)
02:40:12  8035ms  8f5501d  'How am I doing'      -> ok
02:40:23     6ms  8f5501d  '100g of white rice'  -> "Something went sideways…"
02:40:34     7ms  8f5501d  '100g of white rice'  -> "Something went sideways…"
```

⭐⭐⭐ **THE REPLY WAS ALREADY WRITTEN BEFORE THE ABSORPTION RAN.**
`TurnCoordinator.run` catches EVERY exception and sets
`state.response = await finalizer.recover(state)` — the coordinator's failure
floor, `recovery_message("llm_error", seed=request.text)`. Only *then* does
`entrypoint.run_turn` absorb `ExactlyOnceRefusal`, and its replacement was
guarded by `if not state.response.bubbles`. **The floor had already filled them,
so `"Already logged that one."` was unreachable on the live path.** `8f5501d`
was reached, ran, and had no effect the user could see.

The stored line names its own producer. `seed` is the user's text:

```text
len("100g of white rice") + len("llm_error") = 27,  27 % 3 = 0
RECOVERY_BUBBLES["llm_error"][0]
  == "Something went sideways on my end.|||Resend that and I'll catch it."
  == conversation_logs #9223 / #9224
```

⚠ **AND AN EMPTY RESPONSE IS A DIFFERENT POOL.** `Response.from_text("")` falls
back to `stall` ("Lost the thread there"), never to `llm_error` — so on the
native path that line could only have come from `Finalizer.recover`.

⭐⭐⭐ **THE FIRST TEST WAS GREEN BECAUSE ITS FIXTURE SUPPLIED THE DECIDING FIELD.**
`test_a_duplicate_turn_is_absorbed_not_raised` stubs the whole coordinator and
hands in `response=None` by hand, so `Finalizer.recover` never runs. The one
value that decides the outcome in production was the one the test invented.
`tests/test_the_duplicate_reply_is_not_the_failure_floor.py` drives the **real**
`TurnCoordinator` and the **real** `Finalizer`, stubbing only the stage that
genuinely raises — and it reproduces the production row exactly, down to
`outcome=ok`, `total_ms=6`, `stages_json={}`.

**The fix** (`core/turns/entrypoint.py`): the absorption discards a response
that `is_recovery_text`, not merely an empty one. A recovery bubble is the
product's word for "this failed, send it again"; a duplicate did not fail.
Mutation-checked three ways — reverting the clause, deleting the reply, and
deleting reply + return — each goes RED with the right failure name.

**Proven through the real turn**, `scripts/reproduce_the_duplicate_turn_reply.py`
against a scratch Postgres and a live model:

```text
send 1  OK        "White rice logged, 251 cal and 10g protein."
send 2  OK        "Already logged that one."
```

## ⛔ WHAT THE 6ms IS NOT, AND WHAT IS STILL OPEN

The earlier handover read the 6ms as proof that the duplicate is caught
**before interpretation, by a different layer**. That inference was wrong: the
refusal branch IS the layer, and it produces a 6ms / `stages_json={}` row
because the coordinator dies at `execute` and no timed leaf ever closes.

⚠ **BUT THE MISSING `llm` LEAF IS STILL UNEXPLAINED AND IS NOT CLAIMED HERE.**
Driven offline, the duplicate records `llm: 1814` and 1820ms — the interpreter
runs, as `FoodPlanStage` says it must. Production reached
`NativeExecutionStage` with approved operations in 6ms and recorded no model
call at all. Something short-circuits the plan there and it has not been found.
It does not change this repair — the repair sits where the refusal's reply is
chosen, which every route to the refusal shares — but **do not build on the
assumption that the production duplicate ran the interpreter.**

⛔ **`turn_metrics.outcome` IS `ok` ON A NATIVE TURN THAT 500s.** `_rt.done()`
runs in the `finally` around `coordinator.run`, which never raises because the
coordinator catches everything; `raise state.error` happens afterwards, outside
the closed trace. So the outcome field cannot distinguish a served turn from a
failed one on the native lane — the likely reason `outcome=ok` on 1188/1188
all-time. **Deliberately not fixed here:** it changes what the P12 canary
readings mean mid-canary, which is a call to make on purpose.

## ✅ A12 — CANONICAL NOW OWNS WHAT A DUPLICATE IS

Both findings from the offline drive are closed in one slice, because they were
one contract:

⛔ **THE TWO OWNERS DISAGREED, AND THE MIGRATION WAS THE ONE THAT MOVED.**
Canonical's operation id was the TURN id, which absorbs a redelivery and nothing
else; legacy additionally refuses a *retyped* identical message inside an hour.
Three sends gave **one row and two refusals on legacy, three rows canonically** —
so promoting a user changed a user invariant.

⛔ **THE LEGACY KEY WAS CASE-SENSITIVE IN THE PLAN.** `turn_idempotency_key`
lowercased the message and fingerprinted `input["food_name"]` **verbatim**, so
send 3's `"White Rice"` missed send 1's `"White rice"` and wrote a second row.
A key that depends on model output is only as stable as the model.

**The definition, decided once and owned by canonical:**

```text
identity   the USER'S MESSAGE, normalised for case and whitespace
           — never the turn id, never the model's plan
revision   which occurrence of that meal this is
window     60 minutes, legacy's, unchanged — this slice moves WHO decides,
           not WHAT is decided
```

`meal_commits` is already unique on (operation_id, revision), so this needs **no
second claim, no new table, and nothing imported from legacy**. Keying on the
message rather than the plan closes the case-sensitivity hole in the same move;
`_fingerprint_token` closes it at the legacy boundary too.

⭐ **A8'S AST GATE REFUSED THE FIRST VERSION AND WAS RIGHT.** The duplicate
signal was first renamed inside `NativeExecutionStage.run` — an except handler
around settlement, which is exactly how a canonical refusal reaches the legacy
executor. `DuplicateMeal` now propagates like `PricingRefused` and the entrypoint
absorbs both signals as one, so the user cannot tell which owner settled.

**Driven three times through the real turn, on both branches:**

```text
canonical    send 1 logs · send 2 "Already logged that one." · send 3 (re-cased) same · 1 row
legacy       send 1 logs · send 2 "Already logged that one." · send 3 (re-cased) same · 1 row
```

⚠ **CHANGING `turn_idempotency_key` CHANGES EVERY LIVE DIGEST.** Claims already
in `processed_turns` were hashed with the old shape, so on the first deploy a
duplicate inside its window misses once and logs. One extra row per in-flight
claim, once.

## ✅ RESOLVED — THE TWO "UNEXPLAINED" `processed_turns` ROWS

They are `NativeExecutionStage._claim`, which calls `claim_processed_turn`
**without** a `result_summary`. Both map onto a turn exactly, once the metric
row's `created_at` is read as the turn's END:

```text
01:52:20.38  claim   <->  01:52:26.73  6291ms  'I had 150g of cucumber'
02:39:38.13  claim   <->  02:39:46.32  7864ms  '100g of white rice'
```

The ~300ms offset is app-clock vs DB-clock, the hazard `ONE_CLOCK_MIGRATION`
already names. Nothing is unaccounted for.

## ✅ WHAT `8f5501d` ACTUALLY SHIPPED, AND WHAT IT DID NOT

`core/turns/entrypoint.py` absorbs `ExactlyOnceRefusal` instead of letting it
propagate as an unhandled 500, and **returns rather than falling through** —
`state.execution is None` on a refusal, which is exactly the `native_no_plan`
delegation's condition, so falling through would hand an already-logged meal to
the legacy executor and cause the double-log the claim exists to prevent.

⚠ **IT WAS REACHED AND IT DID NOTHING VISIBLE.** The earlier reading — "a real
defect closed on a path production does not take" — was itself wrong. Production
*did* take this path; the branch ran, absorbed the refusal, and returned. What
it could not do was replace the reply, because the coordinator's floor had
already supplied one and the guard only replaced an EMPTY response. A fix can
be live, correct, and inert; `build_sha` proves it shipped, never that it bit.

## ⭐⭐⭐ THE MUTATION THAT CORRECTED THE FIX'S OWN DOCSTRING

Four tests went green. Mutating the line I had called load-bearing left them
**green**:

```text
return removed only        GREEN  <- the twin does NOT bite
return AND reply removed   RED    <- delegation reached, double write
```

The delegation is guarded by `not _bubbles`, so **giving the duplicate a REPLY is
what closes that path**; the return is defence-in-depth behind it. The two lines
are **order-dependent and silent** — make the reply conditional, or move it below
the return, and the double write reopens with nothing to catch it. Recorded in
both the code comment and the test, replacing the claim I first wrote.

## WHAT IS PROVEN, AND WHAT IS ONLY INFERRED

```text
PROVEN  repetition is the trigger, NOT phrasing — the repro drives each
        phrasing 3x and sends 2 and 3 refuse for BOTH. Rewording only ever
        worked because a reworded message is by definition a first send.
PROVEN  dedup itself is correct: NO double write in production
PROVEN  P15 legacy containment holds — cucumber 268 -> 20 kcal, ambiguous
        address still declined, no re-cache
PROVEN  the fix was deployed when the duplicate failed (build_sha 8f5501d)
PROVEN  the duplicate's reply came from `Finalizer.recover`, and the new reply
        reaches the user — offline, through the real turn: send 2 answers
        "Already logged that one." and the board keeps ONE row

CLOSED  the two EMPTY-`result_summary` `processed_turns` rows: they are
        `NativeExecutionStage._claim`, and both map onto a turn once the
        metric's `created_at` is read as the turn's END
CLOSED  the two failure presentations ARE different paths, as suspected —
          "Arnie's temporarily unavailable"  the pre-8f5501d raise (500)
          "Something went sideways on my end" the refusal absorbed, wearing
                                              the coordinator's failure floor

OPEN    the production duplicate reached `execute` with approved operations in
        6ms and recorded NO `llm` leaf. Offline the same duplicate costs
        1820ms with `llm: 1814`. Unexplained; do not assume the interpreter ran.
OPEN    `turn_metrics.outcome` cannot report a native failure (see above)
OPEN    the two settlement owners disagree on what a duplicate IS (see above)
OPEN    `turn_idempotency_key` fingerprints `food_name` case-sensitively, so a
        duplicate slips through whenever the model re-cases the plan
```

## A DECISION THAT IS DANNY'S, NOT A BUG

The claim window is **60 minutes** and the key is `(user, lowercased text,
plan)` with **no time component** (`core/food_ledger.py:171`,
`db/queries.py:3720`). `8f5501d` changed how a duplicate is *presented*, not the
policy. **"Clear my day" does not invalidate that day's claims**, so re-logging
identical text after a deliberate clear is refused rather than logged. Arguably
a day-clear should drop its claims — that is a design decision and was
deliberately not made.

## STANDING RISKS, UNCHANGED

- ⚠ **NO CI HAS EVER RUN ON THIS BRANCH.** Every green is local. Dual-engine at
  this commit, 9398 tests each: **Postgres 9369 passed / 29 skipped / 0 failed ·
  SQLite 9287 passed / 111 skipped / 0 failed.** Postgres runs 82 more tests
  than SQLite, which is how you know the Postgres run was not a silent fallback.
- ✅ **THE 4 DELETION-LEDGER FAILURES WERE A CLOCK, AND BOTH EARLIER READINGS
  WERE WRONG.** Called "order-dependent, pre-existing" in one handover and "not
  order-dependent, they fail standalone" in the next. Neither varied anything.
  Holding the commit fixed and varying only `TZ`:

  ```text
  Pacific/Honolulu  local 08-16 18:57   4 failed
  America/Chicago   local 08-16 23:57   4 failed
  America/New_York  local 08-17 00:57   0 failed
  Europe/London     local 08-17 05:57   0 failed
  ```

  The fixture built its `DailyLog` with `date.today()` — the HOST'S calendar
  date — while `reset_today_log(s, user_id, "UTC")` targets `_user_today("UTC")`.
  They agree only when the host's local date equals the user's. Fixed by using
  the resolver production uses; green across 15 timezone × rollover-hour
  combinations. ⭐ **A failure nobody can reproduce on demand gets explained
  away, and this was the ratchet protecting "no delete without a ledger event".**
- ⛔ **The card is still absent on native turns**, which remains the blocker on
  widening beyond user 26 (§3a.3).

## THE SEQUENCE FROM HERE

```text
1  ✅ the duplicate's reply — it was the coordinator's failure floor, not a
      pre-interpretation layer                                       (eedacfd)
2  ✅ rice triple, offline through the real turn, BOTH branches
3  ✅ A12 — canonical owns what a duplicate is, and the legacy key is
      normalised at the same contract
4  Danny: deploy, then the production three-send test including the
   capitalisation variation
5  freeze general-settlement backend hardening
6  OILS
```

Related: `docs/P12_CANARY_PREREGISTRATION.md` ·
`docs/CANONICAL_MIGRATION_DIRECTIVE.md` ·
`scripts/reproduce_the_bare_phrasing_failure.py` (the controlled pair) ·
`scripts/reproduce_the_duplicate_turn_reply.py` (the rice triple) ·
`tests/test_the_duplicate_reply_is_not_the_failure_floor.py` (the real
coordinator) · `tests/test_a_duplicate_turn_is_absorbed_not_raised.py`
