# HANDOVER — the duplicate turn, 2026-08-16

**Deployed state: `main` = `8f5501d`, live and confirmed via `build_sha` on real
turn rows.** Five gates open, cohort = user 26, iOS only. Board is clean:
`#3013` cucumber 20 kcal, `#3014` white rice 365 kcal. Nothing is broken.

## ⛔⛔ THE OPEN ITEM, AND IT IS THE FIRST THING TO PICK UP

**A repeated food message answers "Something went sideways on my end. Resend
that…" — an instruction to retry the one thing that cannot succeed.**

```text
02:39:46  7864ms  8f5501d  '100g of white rice'  -> logged 365 cal (#3014)
02:40:12  8035ms  8f5501d  'How am I doing'      -> ok
02:40:23     6ms  8f5501d  '100g of white rice'  -> "Something went sideways…"
02:40:34     7ms  8f5501d  '100g of white rice'  -> "Something went sideways…"
```

⭐⭐⭐ **THE 6ms IS THE WHOLE DIAGNOSIS, AND IT IS THE LESSON.** `ExactlyOnceRefusal`
fires *after* the interpreter produces a plan, so any turn reaching it costs
seconds — the successful send cost 7864ms. Six milliseconds cannot have called a
model. **The duplicate is caught BEFORE interpretation, by a different layer
than the one that was repaired.** Latency is a layer fingerprint; read it before
attributing a symptom to a mechanism.

**Where to look:** `core/food_ledger.py` carries an in-memory `_SEEN` /
`already_processed` TTL cache, entirely separate from the DB claim
(`claim_processed_turn`). An `idempotency_key` path through `chat_service` / the
API layer is the other candidate. Whichever it is, it returns a **recovery
bubble** with `outcome=ok` and a `conversation_logs` row.

**What it needs:** the same treatment `8f5501d` gave the other layer — say
"already logged that", never "something went sideways, resend that".

## ✅ WHAT `8f5501d` ACTUALLY SHIPPED, AND WHAT IT DID NOT

`core/turns/entrypoint.py` absorbs `ExactlyOnceRefusal` instead of letting it
propagate as an unhandled 500, and **returns rather than falling through** —
`state.execution is None` on a refusal, which is exactly the `native_no_plan`
delegation's condition, so falling through would hand an already-logged meal to
the legacy executor and cause the double-log the claim exists to prevent.

⚠ **IT IS A REAL DEFECT CLOSED ON A PATH PRODUCTION DOES NOT TAKE.** An
unhandled exception reaching the user was worth fixing and the twin proves it
bites — but it is **not** the code producing the observed symptom. Do not read
`8f5501d` as a fix for the open item above.

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

OPEN    two `processed_turns` rows (01:52:20, 02:39:38) both carry an EMPTY
        result_summary and neither maps cleanly onto a turn. Unexplained.
OPEN    TWO DIFFERENT FAILURE PRESENTATIONS, previously treated as one:
          "Arnie's temporarily unavailable"  no row of any kind
          "Something went sideways on my end" outcome=ok + conversation row
        They are different paths and may have different causes.
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
- ⚠ **4 pre-existing failures** in `test_no_row_is_deleted_without_a_ledger_event`
  — order-dependent, proven failing at `d598610`, before any of this work.
- ⛔ **The card is still absent on native turns**, which remains the blocker on
  widening beyond user 26 (§3a.3).

## THE SEQUENCE FROM HERE

```text
1  fix the pre-interpretation dedup message   <- the open item
2  re-run the rice triple, confirm "already logged" + still ONE row
3  freeze general-settlement hardening
4  OILS
```

Related: `docs/P12_CANARY_PREREGISTRATION.md` ·
`docs/CANONICAL_MIGRATION_DIRECTIVE.md` ·
`scripts/reproduce_the_bare_phrasing_failure.py` (the controlled pair) ·
`tests/test_a_duplicate_turn_is_absorbed_not_raised.py`
