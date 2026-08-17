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

## ⭐ TWO EXACTLY-ONCE FINDINGS FROM THE OFFLINE DRIVE

⛔ **THE CLAIM KEY IS CASE-SENSITIVE IN THE PLAN, NOT ONLY IN THE MESSAGE.**
`turn_idempotency_key` lowercases the message and then fingerprints
`input["food_name"]` **verbatim** (`core/food_ledger.py:159`). Send 3 of the
triple produced `"White Rice"` where send 1 produced `"White rice"`, so the key
missed and a second row was written. One duplicate absorbed, one not, from the
same text — the guard holds only while the model is stable.

⛔ **THE TWO SETTLEMENT OWNERS DO NOT AGREE ON WHAT A DUPLICATE IS.**
With `GENERAL_SETTLEMENT_ALLOWLIST` on, `_canonical_route` returns an owner and
`NativeExecutionStage` takes **no legacy claim** — `commit_or_load_existing` is
keyed on `source_turn_id`, so a *retyped* identical message is a different turn
and logs again. Driven three times under canonical settlement: **three rows.**
Under the legacy branch the same three sends give one row and two refusals.
Production's rice turn took the legacy branch (a hashed `processed_turns` row
with an empty `result_summary`, 02:39:38 UTC), which is why it was refused at
all. **An undeclared divergence in exactly-once semantics between two owners is
the dual authority this migration exists to delete** — worth settling before
general-settlement hardening is frozen.

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

- ⚠ **NO CI HAS EVER RUN ON THIS BRANCH.** Every green is local dual-engine.
  Full suite at this commit: **9265 passed, 107 skipped, 4 xfail, 4 failed.**
- ⚠ **4 pre-existing failures** in `test_no_row_is_deleted_without_a_ledger_event`,
  proven failing at `d598610`, before any of this work. ⭐ **NOT order-dependent
  as previously recorded** — they fail standalone too. Correct the claim before
  anyone spends a session chasing test ordering.
- ⛔ **The card is still absent on native turns**, which remains the blocker on
  widening beyond user 26 (§3a.3).

## THE SEQUENCE FROM HERE

```text
1  ✅ the duplicate's reply — it was the coordinator's failure floor, not a
      pre-interpretation layer
2  ✅ rice triple re-run OFFLINE through the real turn: send 2 answers
      "Already logged that one." — production re-run is Danny's, after deploy
3  freeze general-settlement hardening  <- settle the two owners' duplicate
      semantics first; they currently disagree (above)
4  OILS
```

Related: `docs/P12_CANARY_PREREGISTRATION.md` ·
`docs/CANONICAL_MIGRATION_DIRECTIVE.md` ·
`scripts/reproduce_the_bare_phrasing_failure.py` (the controlled pair) ·
`scripts/reproduce_the_duplicate_turn_reply.py` (the rice triple) ·
`tests/test_the_duplicate_reply_is_not_the_failure_floor.py` (the real
coordinator) · `tests/test_a_duplicate_turn_is_absorbed_not_raised.py`
