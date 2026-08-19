# Phase B–F directive: complete clarification migration, finish conversational food, then extend the canonical backend to workouts

> **Augmented directive — plan-of-record.** Received 2026-08-05, augmented
> 2026-08-06 from team review (slice loop and deletion, presentation
> boundary, B-1a–e closing sequence, release gates). Supersedes no prior
> directive, composes with all of them. Detail documents:
> [CLARIFICATION_MIGRATION.md](CLARIFICATION_MIGRATION.md) (Phase B design
> decisions), [CHIP_GENERATION_MIGRATION.md](CHIP_GENERATION_MIGRATION.md)
> (option pipeline + status ledger),
> [QUICK_LOG_PROMOTION_RECORD.md](QUICK_LOG_PROMOTION_RECORD.md) (Phase A
> evidence), [WORKOUT_CONTRACTS.md](WORKOUT_CONTRACTS.md) (Phase E/F shapes),
> [DELETION_INVENTORY.md](DELETION_INVENTORY.md) (cleanup scoreboard),
> [ARCHITECTURE_CONTRACT.md](ARCHITECTURE_CONTRACT.md) §1b (executable
> invariants C1–C9). Enforcement lives in
> `tests/test_the_canonical_invariants.py`; this document is the sequencing
> authority.

>
> **CURRENT RECONCILIATION — 2026-08-17 @ `0dcc1f8`.** §NEXT is the **only
> executable sequencing authority** in this file. P16/P16b measurement is closed;
> P17 is the active coverage tranche. `P17c.2` has landed: one scaling resolver,
> authoritative quantity precedence, canonical-eligibility separated from
> estimate scalability, real-normalizer twins, plural/canonical unit matching,
> and sourced panel provenance. The local suite reported by that commit is
> **9350 passed / 107 skipped / 0 failed**. The pricing artifact is still
> intentionally unchanged. **The immediate P17 blocker is source-snapshot
> identity before USDA hydration** — no authoritative measure may be committed
> with `dataset_version="committed_artifact"` or with an immutability claim the
> source contract cannot actually prove.

## ⚠ HISTORICAL CORRECTED SEQUENCING *(Danny, 2026-08-16. SUPERSEDED FOR EXECUTION BY §NEXT.)*

> **Historical state at the time.** Interpretation adoption was closed for
> ADDRESSING while coverage/cacheability had not yet been re-measured. That
> uncertainty is now resolved enough to sequence: P16/P16b measured the current
> predicate and selected P17. This block is retained as history only; **§NEXT
> below is the sole live board.**

```text
P0   correct the closure language and FREEZE the rollout   ✅ 11511f1
P1   repair corpus correlation                             ✅ 79ba9ad  v2
P3   re-close interpretation adoption — SCOPED             ✅ fc2db9d  §0z
P4   amend §3a.2 with decisions A-D                        ✅ IN FORCE. A6 and
                                                              A7 amended, A2's
                                                              boundary drawn,
                                                              A11 added
P5   approve the A1-A10 plan                               ✅ GO (Danny)
P6   build ResolvedMeal + GeneralSettlementOwner           ✅ A1-A9 + A11 built,
                                                              gated, mutation-
                                                              proven. A7 PASSED
                                                              live: rung=artifact
                                                              evidence=usda:168389
                                                              poison calls = 0
P7   negative twins for every positive invariant           ✅ 11 twins; two
                                                              mutations RED
P8   dual-engine on the EXACT tree                         ✅ 77c842e, clean:
                                                              SQLite 9195/0/107s
                                                              PG     9277/0/25s
                                                              9306 collected both

⛔⛔ P6 CLOSES IMPLEMENTATION. THE COORDINATOR MIGRATION CLOSES ADOPTION.
   P2 QUANTIFIES THE CEILING BETWEEN THEM.  *(Danny, 2026-08-16)*

P9   one REAL turn through the routing seam (scratch DB)   ✅ PASS — rung=
                                                              artifact through
                                                              run_chat_turn.
                                                              ⛔ AND IT TOOK
                                                              FIVE GATES, NOT
                                                              FOUR
P10  presentation from the canonical branch                ⚠ the card gap is
                                                              the NATIVE
                                                              RENDERER's, not
                                                              this slice's —
                                                              §3a.3. Hardened
                                                              by three review
                                                              rounds, below
```

⛔ **COMMIT-MESSAGE NUMBERING DOES NOT MATCH THIS BOARD, AND THE BOARD WINS.**
Three commits are titled `P9` / `P11` / `P12` in git while directive-P11 is the
COVERAGE measurement and directive-P12 is the CANARY. Read them as **P10
hardening rounds**:

```text
9b06bd4  "P9"   -> P10a  the routing seam, driven through a real turn
135ef78  "P10"  -> P10b  the card gap diagnosed to the native renderer
6240058  "P11"  -> P10c  committed totals cross the seam · mismatch · anti-stale
0922882  "P12"  -> P10d  unknown is not zero · the dataflow gate
(this)          -> P10e  transaction semantics corrected · rollback gate
```

**P10 IS CLOSED** *(Danny, 2026-08-16, at `ecacd76`)* — the canonical branch no
longer takes the durable legacy `ProcessedTurn` claim, the failure gate counts
it in the zero-delta set, and the retry must succeed exactly once.

**P11 — COVERAGE — MEASURED, from production, no credits spent:**

⛔⛔ **THE 2026-08-15 FIGURES BELOW ARE SUPERSEDED, AND NOT BECAUSE THE WINDOW
SLID — BECAUSE THE PREDICATE CHANGED UNDER THEM** *(re-measured 2026-08-17)*.
P11 ran at `beac35a` on 08-15. The count-only/mass branch entered `decide()` at
`951b90e` on 08-16, AFTER it. So the `108 / 3` decline split describes a
predicate that had no mass branch, and re-running the SAME instrument on the SAME
window reclassifies most of it:

```text
                      P11 @ beac35a (08-15)     RE-MEASURED (08-17)
population            406 rows · 252 meals      362 rows · 233 meals
A  routing rate                 81.0%                  83.0%
B  support rate                 45.6%                  24.3%   <- flattering
C  OWNERSHIP RATE               36.9%                  20.2%   =  A x B
expected rung         memory 81 · artifact 12   memory 30 · artifact 14 · both 1
declines              108 no local evidence      86 count-only quantity
                        3 no stated quantity     54 no local evidence
```

⭐ **THE DROP IS HONEST, NOT A REGRESSION.** The mass branch declines meals
canonical genuinely cannot price — every rung is per-100g and a count carries no
mass — so 20.2% is what ownership always was once the predicate stopped calling
count-only meals supportable. **36.9% was never a number the current system
could produce.**

⚠ **AND THIS IS THE FAILURE MODE THIS PROJECT KEEPS PAYING FOR: a number
published under one instrument used to sequence work under another.** The 108 was
made the authoritative backlog on 2026-08-17 review, hours before the re-measure
showed it does not exist. Any coverage figure quoted here must name the predicate
commit it was taken at.

⛔ **THE FIRST PUBLICATION OF THESE NUMBERS WAS WRONG AND IS SUPERSEDED**
(66.7 / 42.3 / 28.2). It read `ledger_events.source` as the ROUTE when it names
the WRITER, so all 36 `canonical:create` meals — the B-1 answer path — were
filed as routing failures. Adoption would have driven the measured routing rate
DOWN. See §3a.4.

⚠ **AND THE "~25% ROUTING" FIGURE QUOTED EARLIER IN THIS SESSION WAS NEVER A
ROUTING RATE** — it came from the 08-15 identity-SEAM measurement
(`entity_identity_skipped reason=no_interpretation`), a different population.

**P12 — THE CANARY — HAS RUN AND PASSED, ON BOTH BRANCHES** *(2026-08-17,
`29ba0e1`)*. Its precondition was "only once the coordinator actually routes that
user through the branch"; it does, and canonical settlement owned real
production meals under `general:26:meal:…`. **P13/P14 and the backend freeze are
in §FREEZE at the end of this section.**
⛔ **THIS BLOCK WAS CORRUPTED AND IS REPLACED** *(Danny, 2026-08-17, on review)*.
It had accumulated two different lists into one run-on paragraph — the live
P11–P14 status notes and a superseded P2/P6–P11 plan — in a document used as an
execution authority. What follows is the immutable status table. Nothing here is
a sequence; the sequence is §NEXT below.

```text
PHASE  WHAT IT WAS                                 STATE
P0     correct the closure language, freeze rollout ✅ 11511f1
P1     repair corpus correlation                    ✅ 79ba9ad  (attribution v2)
P2     rerun the corpus from a clean database       ⏸ OFF THE CRITICAL PATH.
                                                      Costs credits. Its purpose
                                                      was the coverage number and
                                                      P11 produced one from
                                                      history. What it still
                                                      uniquely offers is the
                                                      shadow-vs-off COMPARISON
P3     re-close interpretation adoption — SCOPED    ✅ fc2db9d  (§0z)
P4     amend §3a.2 with decisions A–D               ✅ IN FORCE
P5     approve the A1–A10 plan                      ✅ GO (Danny)
P6     ResolvedMeal + GeneralSettlementOwner        ✅ built, gated, mutation-
                                                      proven; A7 passed live
P7     negative twin for every positive invariant   ✅ 11 twins
P8     dual-engine on the EXACT tree                ✅ 77c842e
P9     one REAL turn through the routing seam       ✅ PASS (five gates, not four)
P10    presentation from the canonical branch       ✅ CLOSED at ecacd76
P11    coverage AND ownership, at MEAL level        ✅ MEASURED (beac35a, corrected
                                                      in §3a.4) — 20.2% ownership
P12    one-user production canary                   ✅ PASSED 2026-08-17 on BOTH
                                                      settlement branches
P13    B-1.8 canonical correction defect            ⏸ PARKED, and stays a real
                                                      defect. Do NOT weaken the
                                                      ownership firewall to make
                                                      a slice look finished
P14    call general settlement PRODUCTION-OWNED     ✅ FOR THE COHORT ONLY —
                                                      adoption is proven for
                                                      user 26, not for the fleet
P15    ambiguous memory is never authoritative      ✅ 3b03943  (both owners)
A12    canonical owns what a duplicate is           ✅ 29ba0e1  (§FREEZE)
P16    MISS ATTRIBUTION / COVERAGE MAP              ✅ MEASURED 2026-08-17
P16b   meal-level recovery + re-attribution          ✅ FROZEN population
                                                      p16b_0817 · 361 rows /
                                                      232 meals
P17    authoritative serving-basis consumption       🟡 ACTIVE — current head
                                                      0dcc1f8; §NEXT + §P17
```

⚠ **P16, NOT P15 — THE NAME IN THE REVIEW COLLIDES.** The review called miss
attribution "P15", but P15 is already spent: `3b03943`, *"ambiguous memory is
never authoritative — for EITHER settlement owner"*. Two phases sharing a number
in the execution authority is exactly how an agent resurrects the wrong work, so
the new tranche is **P16**.

⭐ **WHY P2 MOVED RATHER THAN VANISHED.** It was sequenced as a closure gate
when the corpus was believed to carry the adoption evidence. It does not — step
5's five measurements are store-side. What the corpus uniquely owns is the
COVERAGE number, and coverage is what the settlement slice's own risk turns on:
`assemble()` retrieves nothing, so the coverage predicate's miss rate is the
whole of that slice's exposure. **P2 is now a design input to P6, not a
permission slip for P3.**

⛔ **SUPERSEDED — THE CANARY HAS RUN.** This paragraph read "the immediate next
move is P12" on 2026-08-16. P4 ✅, P5 ✅, P6–P10 ✅ (`ecacd76`), P11 ✅ measured
(`beac35a`, corrected in §3a.4), **P12 ✅ passed live 2026-08-17 (`29ba0e1`)**.
The immediate next move is COVERAGE — see §FREEZE.
⛔ **Cohort expansion is still prohibited**, and the reason has changed: it is no
longer waiting on the canary but on COVERAGE. Widening is a coverage decision
whose blast radius is mispricing, and the ownership rate is 20.2% (re-measured
2026-08-17; the 36.9% this line carried came from a superseded predicate).

⭐ **AND P2 IS NO LONGER ON THE CRITICAL PATH.** Its purpose was the coverage
number; P11 produced one from HISTORICAL production data with no credits and
no model, exactly as the frozen "no phase waits for traffic" rule predicted.
What P2 still uniquely offers is the shadow-vs-off COMPARISON.

⛔ **ROLLOUT IS FROZEN.**

```text
ENTITY_RESOLUTION_CONSUME_ALLOWLIST = 26        keep it — do not widen
GENERAL_SETTLEMENT_ALLOWLIST        = 26        keep it — do not widen
cohort expansion                     PROHIBITED — a COVERAGE decision now,
                                     not a canary one
```

## ⛔⛔ §FREEZE — GENERAL-SETTLEMENT BACKEND HARDENING IS CLOSED *(Danny, 2026-08-17)*

**Live: `29ba0e1`. Cohort: user 26, iOS. Verified in production on BOTH
settlement branches.** Dual-engine at the freeze commit, 9398 tests each:
Postgres 9369 passed / 0 failed · SQLite 9287 passed / 0 failed.

```text
P12  one-user canary                                    ✅ PASSED, both branches
P13  B-1.8 keeps the canonical correction defect        ⏸ PARKED, unchanged. Do
                                                          NOT weaken the
                                                          ownership firewall to
                                                          make a slice look done
P14  general settlement may be called PRODUCTION-OWNED  ✅ adoption proven for
                                                          the cohort — and for
                                                          the COHORT ONLY
A12  canonical owns what a duplicate is                 ✅ 29ba0e1
```

### What the freeze means

**Backend hardening for the general canonical settlement owner is finished.**
A1–A12 are built, gated, mutation-proven, dual-engine, and production-verified.
From here the work is COVERAGE, and **coverage widens by landing EVIDENCE, never
by loosening this backend.** If a later reader is tempted to return `Supported`
for a food with no local evidence, the thing to change is the artifact.

The frozen surface is enforced executably, not by prose:
`tests/test_the_general_settlement_backend_is_frozen.py`.

```text
LOCALLY_EVIDENCED     = ("memory", "artifact")   ESTIMATE stays out
DUPLICATE_WINDOW_SEC  = 3600.0                   legacy's hour, deliberately
meal identity         = the user's MESSAGE       never the turn id, never the
                                                 model's plan
POLICY_VERSION        = food_policy_native_v1    distinguishable from the ledger's
coverage ladder       identity -> quantity -> mass -> memory -> artifact -> decline
```

⭐ **THE FREEZE IS NOT A VETO.** Changing a frozen value is allowed — it has to
be a decision made on purpose, recorded here, with the freeze test edited in the
same commit. That is the whole difference between a freeze and a drift.

⚠ **AND IT WATCHES FOR GATE DELETION.** The cheapest way to defeat an invariant
is to delete the test that names it, and until now nothing was looking. The
freeze file carries a manifest of every frozen invariant and imports each
enforcing gate; a rename is fine, a silent disappearance is not.

### A12 — what canonical means by "the same meal"

The two owners disagreed and **the migration was the one that had moved**: the
legacy branch refused a retyped identical message inside the hour, while
canonical keyed its operation id on the TURN id — which absorbs a redelivery and
nothing else — so three sends wrote three rows. Promoting a user changed a user
invariant. Canonical now decides it, using primitives it already had:

```text
identity   the user's MESSAGE, normalised for case and whitespace
revision   which occurrence of that meal this is
window     60 minutes — legacy's, unchanged
```

`meal_commits` is already unique on `(operation_id, revision)`, so this needed no
second claim, no new table, and nothing imported from legacy. Keying on the
message also closed a second hole: the legacy key fingerprinted
`input["food_name"]` verbatim, so `"White Rice"` and `"White rice"` hashed
differently and a re-cased plan slipped the guard.

⭐ **A8'S AST GATE REFUSED THE FIRST VERSION AND WAS RIGHT.** The duplicate signal
was first renamed inside `NativeExecutionStage.run` — an except handler around
settlement, which is exactly how a canonical refusal reaches the legacy executor.
`DuplicateMeal` now propagates like `PricingRefused`, and the entrypoint absorbs
both signals as one so the user cannot tell which owner settled the turn.

Production evidence, both branches, three sends each including a re-cased one:

```text
legacy    one claim (was TWO), 1 row, 2x "Already logged that one."
canonical general:26:meal:9303ac8deca72cd7 rev=0, 1 row, 2x same reply,
          and ZERO processed_turns claims — canonical borrowed nothing
```

### ⛔ WHAT COMES NEXT IS A COVERAGE DECISION, AND THE MEASUREMENT DISAGREES WITH THE ROADMAP

The frozen roadmap's step 4 is "the next largest measured gap *(expected:
PRODUCT)*" and step 5 is the oils. **The measurement does not put the oils
anywhere near the front.** From §3a.2, 691 real production entries:

```text
NON-ENGLISH   30.4%   <- the largest measured gap, by 3x
BRANDED        9.8%
QUALIFIED      7.7%
bare           5.6%   <- where the oils live
```

⚠ **AND THE DIRECTIVE ALREADY SAYS SO**: "landing all five oils moves real
coverage under one point." The artifact is the deciding rung on 1.9% of real
food. So `oils -> materiality -> branded` is an ordering by *readiness*, not by
measured gap; **non-English is the biggest number and it is not on that list.**
This is flagged, not resolved — the sequencing call is Danny's, and it should be
made with these four numbers in view rather than around them.

⭐ Materiality (B-1.7b) is the exception that does not need a coverage argument:
it changes WHEN the product asks rather than what it can price, so its value does
not depend on which bucket is largest.

## ⏭ §NEXT — THE ONLY EXECUTABLE SEQUENCING IN THIS DOCUMENT *(Danny, 2026-08-17; reconciled at `c406e87`)*

> ⛔⛔ **ONE BOARD RULE.** **This section is the only place in this document that
> may tell anyone what to do next.** Everything below it is EVIDENCE, METHOD,
> CAPABILITY PLACEMENT or HISTORY. A later section may say where a capability
> belongs; it may not silently promote that capability ahead of the measured
> sequence. Enforced by `tests/test_only_one_board_sequences_the_work.py`.
>
> ⭐ **PRODUCT GOAL AND PROGRAM RULE ARE BOTH TRUE.** We are building toward a
> coach that can understand normal food language, resolve exact branded products,
> ask only material questions, handle several foods in one turn, accept
> corrections, use memory to reduce friction, and coach from settled truth.
> **That product destination does not authorize feature-order engineering.**
> Coverage work is selected by measured recoverable ownership; correctness work
> runs in parallel where explicitly allowed; later product capabilities compose
> the canonical primitives rather than bypassing them.

### ⚠ §CARRY-FORWARD REGISTER — findings that MUST be picked up downstream *(2026-08-18)*

> Not sequencing (§NEXT owns that). A REGISTER: each item names its owner
> tranche so the next person does not rediscover it. Remove an item only by
> naming the commit that closed it. When a tranche named as OWNER goes GO,
> its brief must cite the CF ids it takes.

```text
ID   FINDING                                          OWNER TRANCHE       STATUS
CF1  POISONED MEMORY ROW ufm 1941501: "Grilled        M1 (memory quality) OPEN
     Chicken Breast" prices 230 kcal / 16.5 g
     protein / 22.5 g carbs / 10 g sugar per 6 oz —
     not chicken; settled user 26 row 3027 from
     MEMORY on 08-18 and the canonical correction
     faithfully scaled the poison to 8 oz. Same
     class as ufm#400 (13.2 C/100 g). Quarantine at
     read time via the disagreement test, or fix the
     row; NEVER by a calorie range.
CF2  CANONICAL REFUSALS REACH THE USER AS GENERIC     rendering (after      PARTLY
     RECOVERY COPY: CorrectionRefused / StaleUndo /  B-1.8; not semantic)  CLOSED*
     PricingRefused propagate (A8, correct) and the
     coordinator's failure floor answers with
     recovery_message("llm_error"). "Undo the newer
     correction first" / "I can't price that from
     what I know" never reach the user. Refusal
     stays canonical (closure criterion held); the
     COPY is the gap.
     * 2026-08-18 (P17 live canary #2): it bit — a
       CorrectionRefused surfaced on iOS as "Arnie's
       temporarily unavailable · Retry" x6. The
       entrypoint now ANSWERS a CorrectionRefused
       (incl. StaleUndo, ProductSelectionRefused) in
       user-grade words by refusal KIND, beside the
       duplicate absorption: no write, no legacy, no
       raise. PricingRefused at settle still takes
       the generic floor — remaining half of CF2.
CF3  ENTRY 2674 UNLEDGERED MUTATION: "Ground beef,   ledger invariant      OPEN
     seasoned" -> "Ground bison, seasoned" with NO   (I3-family)
     ledger event — one production write path does
     not record. Found by M1.1. Owner is the ledger
     invariant; do not derail a tranche for it, do
     not lose it either.
CF4  HEURISTIC MASS x EXACT PRODUCT: "2 cups" of a   P17-SB (scan/binding) CLOSED*
     peanut bar -> vessel heuristic 260 g -> the     tranche
     PRODUCT rung scales an exact label from an
     estimated mass. INVARIANT (Danny): exact
     product evidence x heuristic quantity
     conversion != authoritative settlement.
CF5  SCAN IS BINDING like a tap (Danny): settle-time P17-SB (scan/binding) CLOSED*
     _bind_scanned_product still runs the UNBOUND   tranche (NEXT)
     ladder — a memory row can outrank the scanned
     snapshot. Use the c2.2 primitive
     (assemble/price bound=True): SCAN-BOUND -> that
     snapshot only -> price or refuse.
CF5b SCAN BINDING MUST DOMINATE CORRECTION CLAIMS   P17 (before P17g)     BUILT;
     *(Danny, 2026-08-18 — verbatim; P1 AUTHORITY                          live
     VIOLATION, not a routing inconvenience)*.                              canary
     A scan-bound turn cannot be claimed by                                 OWED
     implicit correction, ratio correction or legacy
     mutation before the bound predicate runs.
       PRODUCTION (turn ios:D3B7757E, 21:01, the
       DIRECT canary): scan acquired exact snapshot
       (product_acquired code=70004199 snapshot=1 at
       21:01:04) -> correction route discarded binding
       (interpreter emitted update_food_entry(3030,
       "4 bar") against the legacy Barebells row on the
       board) -> heuristic ratio mutation committed
       (correction_apply route=ratio ratio=2.000
       cal=800.0) -> bound predicate NEVER RAN (no
       settlement_route line). Every scan-binding check
       keyed on log_food; the update op fell through
       the native stage to the legacy executor. CF4
       and CF5 broken in one turn. The two-turn canary
       56 s later on the SAME product REFUSED the same
       heuristic (BoundUnpriceable) — the invariant
       works; a shape in front of it did not carry it.
       REQUIRED ARCHITECTURE, at the correction-claim
       boundary:
         if turn carries SCANNED_PRODUCT_EVIDENCE:
             implicit correction eligibility = false
             ratio correction eligibility = false
             preserve snapshot
             continue through fresh bound-item planning
       A scan attachment means a NEW exact-product
       report. It must not mutate an old row merely
       because that product already appears on the
       board. Defence in depth inside correction
       execution: scan-bound turn reaches
       correction_application -> typed invariant
       failure -> zero mutation -> never silently
       discard snapshot. The executor guard is not the
       primary router; it prevents another 800-calorie
       commit if upstream classification regresses.
       PREREGISTERED PROOF: EXISTING row 3030 =
       Barebells 400 cal; TURN scan 70004199 -> "2
       servings of Barebells"; REQUIRE row 3030
       byte-identical · zero correction event · zero
       ratio route · settlement_route = Supported ·
       new row committed · product_evidence_id =
       acquired snapshot · resolved 110 g · ~220 cal ·
       pricing_rung = product · zero MEMORY · zero
       legacy. TWINS: remove scan exclusion from
       correction claim -> RED · remove executor
       invariant -> adversarial misroute commits
       nothing · same food already on board must not
       change the result · scan + unsupported "2 bars"
       -> BoundUnpriceable + CF9 ASK, not correction.
       Do not weaken ratio correction globally: the
       defect is narrower and stronger — IMPLICIT
       CORRECTION CANNOT OUTRANK EXPLICIT SCAN BINDING.
       Scope (Danny): exact scan binding exists · plan
       contains exactly one food update · no explicit,
       separately addressed correction · unbound
       updates byte-identical. Scanning-to-correct, if
       ever supported, is a distinct explicit
       interaction with a named target — never
       inferred from ordinary scanner attachment.
       BUILT (this commit): planner lift
       `_lift_bound_correction_to_log` (identity from
       the exact snapshot via `_name_from_snapshot`,
       quantity from the user's LITERAL message — "2
       servings", never the planner's "4 bar" total) ·
       native backstop `ScanBoundNotLegacy` before the
       legacy claim, keyed on the BINDING not the
       attachment (a multi-food scan turn binds nothing
       by design) · `ScanBoundCorrectionRefused` in all
       three correction_application arms · answered in
       words at the entrypoint's refusal seam. Proof:
       tests/test_scan_binding_dominates_correction_
       claims.py — every mutation seen RED (A: 3 twins ·
       B: 1 · C: 1 · D multi-item: 1). P17g remains
       blocked; the two-turn canary stays valid; the
       DIRECT canary must be RERUN after deploy and
       must create a NEW bound row while the prior rows
       remain untouched.
       REVIEW (Danny, same evening) — three findings,
       two fixed before deploy, one narrowed:
         P1 ✅ FIXED — snapshot identity was "enrichment"
            for a lifted item (fail OPEN: keep the board
            row's placeholder, continue) -> could commit
            one product's NAME over another snapshot's
            NUTRITION. Now AUTHORITATIVE: `_scan_lifted`
            -> snapshot must load + usable name -> replace
            -> else `ScanBoundIdentityUnavailable`, raised
            before the predicate, zero write, no legacy,
            answered in words. Proofs: Quest row + Barebells
            snapshot -> committed name is EXACTLY the
            snapshot's · missing/nameless/unreadable ->
            zero write · replacement removed -> RED ·
            fail-open return -> RED (AST + behavioural).
         P2 ✅ FIXED — binding disposition counted only
            log_food, so update(bar)+log(soup) under a
            scan read as ONE food and the backstop refused
            the whole turn (safe, but not "unchanged").
            Now every food-affecting op counts
            (`_FOOD_OPS`); twin: existing bar + scan +
            "a bar and some soup" -> update+log -> binds
            nothing -> general path unchanged (both ops
            reach legacy, no product_evidence_id).
            Reverting to log_food-only -> RED (3).
         P2b ✅ FIXED — ATTACHMENT IS NOT BINDING. The
            mixed-plan twin had STUBBED the legacy
            executor and its own docstring admitted "the
            correction guard is not consulted" — it
            asserted the claim it was meant to test.
            Driven through the REAL executor the claim was
            FALSE: log "1 bag" (210 kcal), then a scan
            attached + [update(bag -> "9 chips"),
            log(soup)] — the scan binds NOTHING, but the
            guard read the ATTACHMENT, raised, and
            `_apply_portion_correction`'s bare except left
            `changes` untouched, so the row was written
            "9 chips" beside the WHOLE BAG's 210 kcal
            (unbound: 90.1). A portion and a value allowed
            to disagree — the class that function exists to
            end, reintroduced by a guard. NOT a safe
            failure: it is an incorrect write.
            Now binding is an EXPLICIT STATE, decided once
            and read by every guard:
              None · ATTACHED · BOUND(snapshot_id) ·
              SKIPPED_MULTI_ITEM · CONSUMED
            `product_acquisition.begin_turn()` clears BOTH
            the attachment and the decision at ingress
            (one door; ingress no longer sets the id
            directly); `attach()` records ATTACHED;
            `decide_binding()` is the ONE decision, made in
            `NativeExecutionStage.run` where the turn's ops
            are first known; `scan_is_bound()` is the ONE
            reader. Operation counting (`_FOOD_OPS`) is the
            decision's INPUT and is consulted exactly once
            — asserted by AST, so no guard grows a second
            definition. The planner still reads the
            ATTACHMENT (the decision needs ops that do not
            exist yet) and scopes itself; that is
            documented at the reader.
            And the typed invariant PROPAGATES: re-raised
            in `_apply_portion_correction` AND in the
            executor's per-tool dispatch loop, which would
            otherwise turn an authority violation into
            `results[name] = "Error: ..."` and carry on.
            Proofs (real executor, nothing stubbed but the
            enrichment network): mixed turn byte-identical
            to its unbound twin, on the corrected row AND
            the soup, neither carrying product_evidence_id,
            no refusal, no "portion correction not applied"
            warning · a genuinely bound correction raises
            and the row does not move · binding state does
            not leak into the next turn across settle /
            refuse / crash · the four-state matrix · AST
            gates for the re-raise order and the single
            decision point. Mutations seen RED: guard reads
            attachment (1) · swallow in the applier (3) ·
            swallow in the loop (2) · begin_turn forgets
            the decision (5) · binder trusts its own count
            (2).
         ⚠ ALSO FOUND: `tests/test_a_scan_is_binding.py`'s
            `_log` fixture PINNED `dt.date(2026, 8, 18)`
            while the canonical writer resolves the logging
            day itself — at 00:02 UTC on the 19th the two
            disagreed and FIVE tests in that file went red
            on a tree that had been green hours earlier.
            The 9639 run was time-dependent. Fixture now
            uses `get_or_create_today_log`; a fixture that
            pins a date is a test that expires.
         P2 ⚠ NARROWED — liquid chips are helper-proven
            (display says ml when the record says ml) but
            the PATH (per-ml ProductEvidence -> coverage ->
            BoundUnpriceable -> ask -> ml chips -> settle)
            is not: `_open` still gates on
            coverage.serving_grams. The bound-ask path is
            claimed for GRAM-BASED labels only; the liquid
            path proof is registered under P17-UE / CF10
            (below). No liquid claim ships in this commit.
CF5c ONE SCAN AUTHORITY — the guard-placement fix   P17 (before P17g)     BUILT;
     *(Danny, 2026-08-19)*. SUPERSEDES CF5b's                              live
     local-guard framing; CF5b's guards are RETAINED                       canary
     as backstops, stripped of decision-making.                            OWED
       THE FINDING IS THE PATTERN, not a fifth hole.
       Four production-shaped routes were found around
       CF5, and every fix added a guard where the
       damage SURFACED, each re-deriving "is this
       bound?" from whatever it had to hand:
         ios:D3B7757E  implicit ratio correction    CF5b
         mixed turn    attachment read as binding   review 2
         undecidable   the decision failed open     review 3
         zero-op       early return before any      review 4
                       decision ran
       Danny: "binding is decided from approved_
       operations, after information about the full
       turn may already be lost." Correct — and the
       remaining escapes followed from it:
         · ConfirmReplayPlanStage runs BEFORE the scan
           rule, so scan + "yes" could replay an older
           confirmed food and attach THIS snapshot to
           it — one product's nutrition under another's
           name, upstream of every identity guard.
         · a two-food clarification exposes ONE approved
           operation (the validation stage approves only
           the READY items), so ops-counting binds a
           turn that names two foods.
         · a bound canonical update could execute
           through _correction_route if the lift missed.
         · the zero-op escape also left LAST_EXECUTION
           uncleared.
       THE BUILD: one SEMANTIC decision, three physical
       touch points (`core/scan_authority.py`):
         PRE-PLAN   an attached scan suppresses confirm
                    replay AND pending-prior consumption
                    (keyed on ATTACHMENT — the
                    disposition does not exist yet, and
                    the earlier question must not shape
                    this turn's plan).
         POST-PLAN  decide BOUND / SKIPPED_MULTI_ITEM /
                    UNDECIDABLE from the COMPLETE plan —
                    operations AND the clarification's
                    items, counted as the MAX of the two
                    views. In `FoodValidationStage`, the
                    first place the complete plan exists.
         EXECUTION  `require_shape` consumed before every
                    early return, correction route and
                    legacy route. BOUND means EXACTLY ONE
                    log_food; every other shape refuses
                    (`ScanAuthorityRefusal`, non-mutating,
                    answered in words by REASON).
       NO STATED AMOUNT is not a blanket refusal: exactly
       one consumed product with quantity the ONLY unknown
       opens the durable CF9 ask HOLDING the snapshot, so
       the answer settles bound; anything else (no
       trustworthy intent, failed plan, another ambiguity)
       is the typed refusal.
       IDENTITY: the snapshot is authoritative for EVERY
       BOUND log, not only `_scan_lifted` ones — the
       interpreter's prose can name the wrong product
       beside a correct snapshot, and the barcode is the
       stronger statement either way.
       BACKSTOPS RETAINED, DECISIONS REMOVED: the legacy
       backstop, `correction_application`, the binder and
       the identity repair all READ the disposition and
       fail closed on an impossible shape. Gates assert
       that food counting (`FOOD_OPS` / `foods_in_plan`)
       appears in NO other module and that
       `decide_from_plan` has exactly ONE caller.
       PROOFS `tests/test_cf5c_one_scan_authority.py`:
       scan+"yes" suppressed (+ unscanned "yes" still
       replays, no re-parse) · two-food ask with one ready
       item -> SKIPPED_MULTI_ITEM · zero-op -> CF9 ask
       holding the snapshot / typed refusal / unscanned
       zero-op still reaches legacy / LAST_EXECUTION
       cleared · bound update refused BEFORE
       _correction_route (spied) · mismatched name loses
       to the snapshot · ORDINARY correctly-named scan
       settles IDENTICALLY (the twin that makes the
       widening safe) · unbound log keeps the
       interpreter's name. Six mutations seen RED.
       Suite 9667 passed, PYTEST_EXIT=0, frozen tree.
       REVIEW of da32929 (Danny) — the "complete plan"
       proof was against a SYNTHETIC clarification
       shape the live ask producer does not emit
       (`{"items":..,"ambiguities":..}`); the primary
       ask origin returns {tool_calls, deferred_calls,
       questions, b1_material, points}. With partial
       commit OFF a one-food quantity ask has ZERO
       approved writes and read as "no food"
       (UNDECIDABLE -> refused instead of CF9); ON, a
       two-food ask exposing one ready write read as
       BOUND. FIXED: `FoodSubject` + `TurnPlan.food_
       subjects`/`open_fields`, normalised ONCE in
       `plan_from_interpretation` from the producer's
       real keys; `ValidationResult.plan` carries it;
       CF5c reads ONLY the typed subjects and refuses a
       plan without them. Real-producer proofs (`FT.run`,
       model mocked) under BOTH FOOD_PARTIAL_COMMIT
       settings: one-ready-plus-one-held ->
       SKIPPED_MULTI_ITEM; the live quantity-only ask
       -> BOUND -> CF9 opens holding the snapshot; the
       re-ask origin normalises too; each carrier proven
       as the SOLE carrier of a food (the sweep found
       deferred_calls and b1_material each redundant with
       the labels on the fixtures — green under
       mutation until then). An unnamed `update_food_
       entry` (entry_id only — `_update_call`'s live
       shape) is one subject keyed entry:<id>.
       CLEANUP: `decide_binding` removed, `scan_is_bound`
       a mechanical delegate, AST gate against
       production callers · CONSUMED applied after
       normal bound settlement and after the ordinary
       BoundUnpriceable ask · the correction backstop
       RAISES on an unreadable authority (was `return`
       — fail-open).
       PRE-SHIP (Danny) — OCCURRENCE IS THE UNIT, NAME
       IS ONLY THE CROSS-CARRIER LINK: name-keyed dedupe
       collapsed two SEPARATE same-name operations
       (one ready, one held) to one subject -> BOUND ->
       the ready write through on a turn with two food
       intents. Now: within a carrier, occurrences are
       distinct by a stable id (op:carrier:index ·
       entry:<id> · staged:<staged_item_id> ·
       interp:<i>); across carriers a LABEL (question,
       point) attaches to every same-name occurrence or
       creates one only when nothing else names the
       food. Twins: one subject mirrored through seven
       carriers -> 1 · two independently represented
       same-name subjects -> 2 -> SKIPPED_MULTI_ITEM ·
       two same-name ready writes -> 2, refused under
       BOUND. Eight mutations seen RED (each confirmed
       APPLIED — a mutation whose anchor no longer
       matches reports the unmutated tree's green as
       evidence). Suite 9684 passed, PYTEST_EXIT=0,
       frozen tree fdb5a8226fc8.
       REVIEW of fc38825 (Danny) — FOUR BLOCKERS, all
       upstream of or beside the authority:
         B1 ✅ `b1_answer_turn.handle` runs from
            conversation.py BEFORE the coordinator; an
            open chicken ask could claim a NEW scan +
            "2 servings" as its answer. Now a scanned
            FREE-TEXT message is "not ours" (None); a
            chip tap still answers (the CF9 tap).
         B2 ✅ CF9 did not prove consumption: scanning
            or naming a product with no "I ate it"
            opened a quantity ask whose answer LOGS.
            `FoodSubject.consumed` — a write asserts
            it, a label inherits the message's
            `consumption_state`; CF9 requires it, else
            `no_consumption` refusal.
         B3 ✅ ask creation not idempotent / single-
            owner: supersede failure in a bare except
            CONTINUED; same-turn retry cancelled its
            own ask and collided; no DB constraint.
            Now: same op id -> return THAT ask;
            supersede-or-refuse (`BoundAskNotSingular`,
            answered at the seam); insert race -> return
            the winner; PARTIAL UNIQUE INDEX
            `uq_pending_operations_one_awaiting`
            (model both dialects + migration oneask001).
            ⭐ The index exposed that the WHOLE B-1 lane
            never superseded — an expired-but-unswept
            prior (last night's chicken) blocked this
            morning's oatmeal ask. Production checked
            first: 0 users >1 awaiting, 0 unswept-
            expired, so the constraint encodes what is
            already true. Supersede moved to
            `open_operation` (the ONE insert site,
            bound or ordinary): `_release_prior_
            awaiting` marks an expired prior expired,
            cancels a live one as superseded, under the
            repository's new shared lock
            `locked_awaiting_for_user` (the house gate
            forbids a bare with_for_update outside
            pending_repository — it caught mine, then
            caught my COMMENT naming it: it greps text).
            PG proofs on the real engine: two turns at
            once -> ≤1 active (supersede) · the SAME
            turn twice -> exactly one row, both workers
            return its id.
         B4 ✅ attachment transformed the plan BEFORE
            the decision (identity-answer lift,
            correction lift, unit restore all keyed on
            attachment) so a plan could be scan-
            transformed then classified SKIPPED. The
            planner is now ATTACHMENT-BLIND (its only
            attachment reads are the pre-plan hooks);
            the three transforms live in `bind_plan`,
            run in the validation stage only after
            `decide_from_plan` says BOUND; `TurnPlan.
            source` carries the raw interpretation for
            it. Hidden-second-subject proof: none of the
            three fires; remove the second subject: all
            three fire, post-decision. AST: no planner
            function reads the attachment or is_bound.
       LEAKS (a) typed field ids — the model schema
       REQUIRES `ambiguities:[{item,field}]`; the
       producer dropped them and CF5c inferred fields
       from question PROSE. Now carried verbatim,
       canonicalised (`prep`->preparation, `flavor`->
       food_identity …); prose inference is the marked
       fallback ("quantity?") which CF9 REJECTS — an
       untyped question refuses rather than asks; an
       item-less record does not type a field. (b) after
       the decision `snapshot_id()` follows
       `ScanBinding.snapshot_id`, not the attachment; a
       decided/attached MISMATCH is refused before any
       write; a decision whose attachment was cleared
       reads as no scan; no module outside the authority
       reads SCANNED_PRODUCT_EVIDENCE (AST). (c) a
       repeated same-name label WITHIN one carrier with
       nothing to anchor to is a second subject; the
       same label across questions+points is one. (d)
       `SUBJECT_SOURCES` is a gate input.
       Danny's five proofs + twins; TEN mutations RED,
       each printed `applied` (B3's supersede mutation
       was first MASKED by the DB constraint — defence
       in depth catching what the swallowed handler let
       through — so the proof asserts WHICH layer
       refused). Suite 9703 passed, PYTEST_EXIT=0,
       frozen tree 51e1b5646fc2.
       REVIEW of 22b9e7a (Danny) — B3's two identity-
       impacting defects; oneask001 itself sound,
       unchanged:
         · `_release_prior_awaiting` IGNORED SaveOutcome.
           save_revision/mark_expired REPORT conflicts
           (ok=False, conflict=True), they do not raise;
           the code logged "released" and inserted beside
           a row it had not released. My test mocked an
           EXCEPTION, so it missed the real contract. Now
           ok=False -> PriorAskNotReleased; proven with a
           real SaveOutcome(ok=False, conflict=True).
         · a lost insert race returned WHICHEVER ask
           owned the user — another turn's, i.e. another
           product's question rendered in this product's
           reply. Now reuse ONLY when the winner IS this
           operation id (`OpenedElsewhere` otherwise ->
           BoundAskNotSingular); the wrapper's same-id
           reuse also verifies the persisted snapshot.
         · contract gap closed: open / reuse / race all
           live in `open_operation`, the shared insert
           seam — ordinary B-1 now gets "same op id ->
           same ask" (proven: no self-release on retry).
         · proof gaps: the B4 test now supplies an
           update_food_entry + hidden soup (the
           correction lift does NOT fire; drop the soup
           and it does, post-decision); SUBJECT_SOURCES
           has its AST gate (every listed key read by the
           normaliser; every read key declared).
       Four mutations RED (`applied`). PG race on the
       real engine green. Suite 9709 passed,
       PYTEST_EXIT=0, frozen tree b71b92258e09.
CF6  LANE PROMOTION RULE (learned from 3 canaries):  every future lane     RULE
     a proven CONSUMER (stage) is unreachable if the
     PRODUCER (planner) or RENDERER in front of it
     is unproven on the LIVE request shape, or the
     lane is not in TURN_COORDINATOR_LANES. Before
     claiming a path is live: read /health lanes +
     allowlist, prove planner inputs on the real
     request, prove the reply renders. "Lost the
     thread there" = EMPTY reply (kind "stall"),
     not an exception; turn_metrics.outcome now
     records error:<Type> for a caught stage error.
     * CLOSED in the P17-SB commit for the BOUND path (price(bound) refuses
       heuristic scaling; settle binds a scanned item). The UNBOUND general
       ladder still scales ARTIFACT/MEMORY by heuristic mass — that is the
       predicate question P17g owns, not a reopening of CF4.
CF8  LEGACY NARRATOR CLAIMS ACTIONS IT DID NOT TAKE:  legacy (not this      OPEN
     2026-08-18 user 26 — "Clear my day" x2 replied   program's; recorded
     "Day's cleared" with NO tool call and NO deleted  because canaries hit
     ledger event (row 3028 survived both); "Two       it repeatedly)
     servings … logged" x2 with NO row written. The
     phantom class the migration exists to delete,
     alive in the legacy narrator. Also: a legacy
     pending ask with a log_date stays open until
     the NEXT day and hijacks every same-food message
     as an "answer".
CF9  A BOUND REFUSAL IS A DEAD-END WITHOUT THE ASK    P17 (before P17g)     OPEN
     ARM: the scan chip is consumed by the message it
     rides; the user's answer to "how many servings?"
     arrives unbound -> legacy -> a guess row. Fix =
     BoundUnpriceable opens a pending quantity
     operation that HOLDS the snapshot (B-1 machinery
     with a product-bound item), so the answer settles
     bound. Preregistered by Danny as "ASK / REFUSE";
     REFUSE shipped first, ASK is owed.
CF10a LIQUID BOUND-ASK PATH UNPROVEN (from the CF5b   P17-UE (with CF10)    OPEN
     review): a per-ml label reaches `_open` only via
     coverage.serving_grams; ml chip DISPLAY exists
     (`_label_base_unit`), the PATH does not. Prove
     per-ml ProductEvidence -> coverage ->
     BoundUnpriceable -> ask -> [240 ml — 1 serving]
     -> settle before claiming liquids; until then the
     bound ask is claimed for gram-based labels only.
CF10 INCOMPLETE PRODUCT RECORDS may provide serving   P17-UE — UNIT         OPEN
     mass without the physical consumer-unit          EVIDENCE COMPLETION
     relationship required for natural inputs such   (after P17g/h + the
     as "1 Twizzler" or "2 bars". The missing fact is frozen remeasure;
     not nutrition — it is the relationship between   before cohort
     a physical consumer unit and the label's         expansion)
     serving mass. Acquire it EXPLICITLY (structured
     serving text · package count + net quantity ·
     explicit single-serve equivalence · label image
     with provenance · user package fact · user
     measurement); never manufacture it from shape,
     category, name, common sense or averages. Full
     directive: §P17-UE below the P17 method.
CF7  TEST_POSTGRES_URL FORM: the shared PG harness   tooling               RULE
     needs postgresql+psycopg://...; +asyncpg
     yields 174 connect() errors. Full-suite recipe:
     TZ=UTC TEST_POSTGRES_URL="postgresql+psycopg://
     $(whoami)@localhost:5432/arnie_test" and no
     extra -q (addopts already has -q; -qq hides the
     N-passed line — read it or claim nothing).
```

```text
HEAD                                   the commit carrying this line
                                       (git log -1 -- this file)
GENERAL SETTLEMENT BACKEND             ✅ FROZEN          (§FREEZE)
ONE-USER PRODUCTION CANARY             ✅ PASSED          (P12, both branches)
PREREGISTERED BASELINE                 ~20.3%            (predicate a747b56,
                                                         232 meals / 361 rows,
                                                         sha 6247a33c55ed64f5)
CURRENT SURVIVOR AUDIT                 ~20.0%            (predicate 00cdcfd,
                                                         230 meals / 359 rows)
  ⛔⛔ THE "FROZEN" POPULATION IS NOT FROZEN — CORRECTED 08-18 *(Danny, P1)*.
  The M1 commit called 20.3 -> 20.0 "memory drift". It was not: rows 3016 and
  3017 (fried chicken 150 g, ground turkey 150 g) were DELETED by user 26 via
  ios_edit at 22:35 on 08-17, and the arithmetic is fully explained by the
  denominator — 45/222 = 20.27%, 44/220 = 20.00%. p16b_0817 froze POINTERS to
  mutable production rows, not INPUT FACTS, so it can only shrink. The
  instrument recorded population_drift={missing:[3016,3017]} and the commit
  message wrote a different cause over the top of it. The preregistered
  20.3% STAYS the baseline; 20.0% is the survivor audit; neither replaces the
  other until M1.1 makes the fixture self-contained.
  ✅ M1.1 DONE (2026-08-18): p16b_0817 now carries INPUT FACTS — ledger
     `created` events replayed through `updated` events (both payload shapes)
     to the freeze instant — and REPRODUCES 232 MEALS / 45 SUPPORTED / 20.3%
     from a database that has since deleted two of its rows. Drift is now
     impossible by construction. The preregistered anchor stands.
     Two production findings surfaced by the reconstruction:
       · 55 of 361 rows had been CORRECTED before the freeze — a naive
         created-only rebuild mismatched 42 of them; replay was required
       · entry 2674 (Ground beef -> Ground bison) mutated with NO LEDGER
         EVENT — an unledgered production write, in violation of the ledger's
         own invariant. Recorded in the fixture; not M1.1's to fix
MEMORY QUALITY (M1, beside — never    2.7 pts of that   supported-but-
subtracted from — ownership)          ownership are     implausible; 22 of
                                      WRONG (lower      31 memory-priced
                                      bound)            meals UNJUDGEABLE
BASELINE POPULATION                    ✅ FROZEN          361 rows / 232 meals,
                                                         sha 6247a33c55ed64f5
P17 STATUS                             🟡 ACTIVE          a–f, f.5, SB, iOS
                                                         producer, UA A/B/C
                                                         SHIPPED (7187742);
                                                         P17g BLOCKED on a
                                                         bound settle in prod
B-1.8 CORRECTION LANE                  ✅ CLOSED 08-18    3 canaries; stale-
                                                         undo guard on path
ROLLOUT                                FROZEN — user 26 only

⭐ CURRENT STATE — 2026-08-18, reconciled at 7187742 (deployed: see /health)
    Transport / binding invariants        ✅  (scan -> snapshot -> bound turn)
    Bound refusal                         ✅  (label-terms; non-mutating)
    Unit-evidence hierarchy (P17-UA A/B)  ✅  (70004199 negative preserved)
    CF9 bound ASK continuity (slice C)    ✅  built + 29 proofs; live ⏳
    Bound production settlement           🟡  FIRST BOUND ROW IN PROD: 3031
                                              (two-turn canary, 21:02:29,
                                              rung=product, snapshot 1,
                                              off:70004199) — but 1 serving
                                              tapped for 2 eaten (ask copy
                                              defect, fixed this commit)
    Clarification preserves binding LIVE  ✅  two-turn canary PASSED (op 87
                                              held snapshot 1; chip settled
                                              bound; no legacy, no MEMORY)
    DIRECT canary                         ❌  FAILED — MISROUTED (CF5b): the
                                              bound turn became a ratio
                                              correction of legacy row 3030
                                              (400 -> 800). Fix built; RERUN
                                              after deploy
    P17g                                  ⛔  BLOCKED on the direct canary
    CF10 / P17-UE                         ◻  registered; begins after remeasure

⭐ SEQUENCE FROM HERE *(Danny, 2026-08-18 — verbatim)*:
    P17-UA A/B  ✅
    -> CF9 slice C  ✅ (pushed 7187742)
    -> two-turn canary (scan -> "2 bars" -> ASK -> "2 servings" -> bound
       row on the SAME held snapshot)                                  ✅ 3031
    -> CF5b (scan binding dominates correction claims) built + proven  ✅ (this
       — the direct canary's failure class; ask copy names the unknown,      commit)
       chips lead with the label's unit ([110 g — 2 servings])
    -> CF5c one scan authority (pre-plan hook · post-plan gate ·
       execution enforcement; CF5b guards retained as backstops)        ✅ (this
                                                                            commit)
    -> DEPLOY, then RERUN the direct canary (scan -> "2 servings of
       Barebells" -> a NEW bound row; 3030/3031 untouched)              ⏳
    -> P17g / P17h                                                     ⛔
    -> frozen 232-meal remeasure (both predicate commits published)    ⏳
    -> P17-UE unit-evidence completion (CF10)                          ◻
    -> cohort expansion                                                ⛔
  BOTH canaries required before P17g is declared closed. P17-UE must
  complete before barcode rollout expands beyond the canary cohort, and it
  must not alter the frozen population, predicate, 40% gate or attribution.

NEXT

⭐⭐ TWO INDEPENDENT CLOCKS RUN BEFORE ROLLOUT, AND EXPANSION WAITS FOR BOTH
    COVERAGE     can Arnie correctly OWN enough meals?
    CORRECTNESS  can a user safely INTERACT with the meals it owns —
                 including CORRECTING identity, quantity and product variant?
    Neither clock alone authorizes a wider cohort.

COVERAGE TRACK
1. P16b  ✅ DONE — population FROZEN as p16b_0817, misses rolled up to MEALS,
         then re-attributed through the REAL normalizer. Recoverable ownership
         points, ranked LOWER against LOWER:

           MECHANISM                          ITEMS   LOWER    UPPER  non-latin
           TYPED:count_only_quantity             84   12.2%    24.8%     14
           IDENTITY:no_resolution_row            48    0.0%    16.7%      4
           TYPED:mass_stated_but_unit_unparsed   51    0.0%     7.2%     51
           CACHEABILITY:memory_quarantined        7    3.2%     3.2%      0  (tight)
           BRANDED:product_non_binding            7    0.0%     1.8%      0
           TYPED:mass_present_but_not_read        6    0.0%     1.8%      2
           IDENTITY:distinct_refused              3    0.0%     1.4%      3
           TYPED:energy_stated_not_a_quantity     1    0.0%     0.5%      0
                                                      15.4 .. 57.4 total

         ⛔⛔ "COUNT-ONLY QUANTITY" WAS ONE PREDICATE BRANCH DESCRIBING FOUR
         DEFECTS. Driving the real normalizer split 142 into 84 + 51 + 6 + 1.
         `150 г` / `200 мл` are stated quantities the parser does not read; they
         are NOT serving-basis misses. A unit-alias fix therefore has a 0.0-point
         lower bound because those rows can immediately hit the evidence wall.

         13 meals carry more than one blocker.

         ⭐⭐ CONTINGENCY RANKING — Δ(M | P17), NOT STANDALONE CEILINGS. P17
         alone recovers 27 meals at its floor, 55 at its ceiling. What each
         OTHER mechanism then adds, with both flipped together through real
         `decide()`:

           MECHANISM                            Δ MEALS   Δ PTS      standalone
                                                  L / U    L / U        upper
           IDENTITY:no_resolution_row            0 / 41   0.0 / 18.5     16.7
           TYPED:mass_stated_but_unit_unparsed   0 / 20   0.0 /  9.0      7.2
           CACHEABILITY:memory_quarantined       7 /  7   3.2 /  3.2      3.2
           BRANDED:product_non_binding           0 /  6   0.0 /  2.7      1.8
           TYPED:mass_present_but_not_read       1 /  5   0.5 /  2.3      1.8
           IDENTITY:distinct_refused             0 /  3   0.0 /  1.4      1.4

         Several marginals exceed their standalone ceilings because two-blocker
         meals are recovered by the pair, not by either isolated flip. Identity
         remains the strongest likely second tranche, but **it is a contingency,
         not a precommitment**. Only cacheability is tight at both bounds (+3.2).

2. P17   🟡 ACTIVE — AUTHORITATIVE SERVING-BASIS CONSUMPTION.

         THE ARCHITECTURE DECISION IS CLOSED:
           · authority and serving basis remain independent axes
           · coverage and pricing share one scaling resolver
           · heuristic normalized mass may produce an ESTIMATE but never
             evidence-backed canonical ownership
           · an unsourced conversion may scale for ESTIMATE but never makes
             `can_scale(authoritative_only=True)` true
           · user-stated exact quantity outranks sourced conversion
           · direct compatible authoritative basis outranks conversion
           · sourced ConversionEvidence outranks heuristic mass
           · provider identity never grants authority
           · synthesized web evidence never prices

         LANDED:
           ✅ P17a/b       basis-aware evidence-backed pricing contract
           ✅ P17b.1      count must count the source's unit
           ✅ P17b.2      one unit authority / one conversion engine
           ✅ P17-SA      provider / authority contract
           ✅ P17c.1      one `resolve_scaling`; `can_scale` is the same call
                          asked as yes/no                         89e606d
           ✅ P17c.2      quantity-authority precedence; real-normalizer twins;
                          plural/canonical unit identity; panel provenance;
                          authoritative eligibility separated from estimate
                          scalability                             0dcc1f8

           ✅ P17c.3a     durable source-snapshot identity BEFORE hydration.
                          No placeholder version reached a durable record.
                                                                  c406e87

         ⭐ WHAT THE PROVIDER ACTUALLY EXPOSES, PROBED NOT ASSUMED. Before the
         contract was written, `/food/{id}?format=full` was inspected:

             dataType           'SR Legacy'
             publicationDate    '4/1/2019'      <- a real record version
             foodPortions[].id  83012           <- stable per-portion identity
             release version    ABSENT from the record entirely

         So the FDC release CANNOT be read from the record. `--fdc-release` is
         required with no default, an absent version yields NO authoritative
         conversion, and `immutable_within_version` is claimed only once the
         version it refers to is named. `record_key` is `fdc_id#portion:<id>`,
         because an fdc_id names a FOOD and a food states several portions —
         "1 large" is not "1 cup".

         ⚠ AND THE IMMUTABILITY CLAIM IS NOT UNIFORM ACROSS DATA TYPES. SR
         Legacy is FINAL, so `immutable_within_version=True` is genuinely
         defensible there; Foundation updates periodically and Branded monthly,
         so the same assertion is weaker for them. The committed artifact is
         121 SR Legacy + 3 Foundation + ZERO Branded, which is why the claim
         holds for almost all of it today — and why P17d cannot source exact
         products from this artifact at all.

         ⬅ IMMEDIATE NEXT INSIDE P17:
           THEN P17c.3b USDA HYDRATION + ARTIFACT REBUILD.
             - fetch authoritative serving measures at BUILD time only
             - expected population from the dry run: 124 candidates / about
               259 portion records; re-measure rather than assuming this count
             - write source identity on every committed measure
             - artifact must remain load-only at settlement

           THEN P17d EXACT PRODUCT PRODUCER.
             - barcode / GTIN / already-bound stable product_variant_id only
             - no fuzzy OFF/name/model confidence may construct PRODUCT
             - direct per-unit label basis stays direct; do not route through
               grams merely because grams are available

           THEN P17e PACKAGE + FRACTION through conversion DATA.
           THEN P17f persist dual nutrition + basis/conversion provenance.
           THEN P17f.5 EXACT PRODUCT ACQUISITION WIRE *(Danny, 2026-08-17 —
           deliberately BETWEEN persistence and activation, so P17 cannot be
           declared production-proven while its exact PRODUCT path is
           physically unreachable, and so the iOS change cannot accidentally
           create scan -> backend fetches OFF DURING SETTLEMENT)*:
             □ iOS scan preserves raw barcode          <- THE OPEN HALF
             ✅ backend receives barcode separately from prose
                (ChatRequest.barcode; invalid shapes sanitize to None)
             ✅ barcode is never reconstructed from product name — the
                validator ignores codes inside the MESSAGE, and a structural
                test forbids the acquisition module from ever knowing about
                prose
             ✅ acquisition performs exact-ID fetch, at INGRESS, with a
                local-newest-snapshot fallback when the provider is down —
                yesterday's evidence is evidence
             ✅ ProductEvidence persisted (and COMMITTED) before the turn runs
             ✅ canonical event stores the reference: snapshot id rides the
                item -> pricing receipt's product_evidence_id column
             ✅ settlement performs zero provider calls — AST ban: no settle-
                path module imports acquisition or the OFF client; E2E twin
                prices 2 bars with the provider dead
             ✅ prose remains presentation/context only
             ⭐ binding is ONE VIEW (`_bind_scanned_product` wraps
                `_food_inputs` for BOTH coverage and settlement), single-item
                only — a scan names one product, and P17g's predicate will
                read the same items the pricer does
             ⚠ scan-bound snapshots carry NO unit noun (OFF names none), so
                they land per-100g + serving mass as a conversion input: gram
                portions price now; "2 bars" waits for unit binding
             ⛔ OPERATIONAL PRECONDITION *(Danny, 2026-08-17 close)*: before
             exercising this wire against anything LIVE, confirm the deploy
             has advanced through `prodev001` — read /health for the commit
             AND verify alembic_version reports prodev001 applied cleanly.
             Production was last observed at 8e2ed45, several commits behind.
             □ P17g starts only when BOTH the wire and that production-schema
               verification are true
           THEN P17g change the eligibility predicate LAST.
           THEN P17h positive twins + mandatory mutation twins.

         ⛔ +24.8 IS A COUNTERFACTUAL CEILING, NOT A FORECAST:
             floor    20.3 + 12.2 = 32.5%
             ceiling  20.3 + 24.8 = 45.1%
         P17 therefore may cross 40% but does not guarantee it.

3.       RE-MEASURE `p16b_0817`, THE IDENTICAL 232 MEALS, after P17g/P17h.
         The delta is attributable to P17 only:
             baseline -> P17 on same population -> delta

4.       RUN THE P17 DEPLOYMENT CANARY WITHOUT WAITING FOR ORGANIC VOLUME.
         First SHADOW the new authoritative path, then consume for user 26 only.
         Prove:
             path actually executed — a quiet canary is not evidence
             current decision vs P17 decision recorded
             rung + nutrition evidence + basis/conversion evidence recorded
             resolved amount / scaling factor explain every numerical delta
             no provider/model call occurs at settlement
             canonical write happens exactly once
             ledger/day totals/presentation agree
             latency acceptable
             refusal twins remain refusals
             rollback stops P17 consumption without corrupting shadow evidence

         PREREGISTERED live/synthetic examples should include:
             2 eggs · 3 large eggs · 100 g eggs
             direct per-bar product basis
             count with mismatching unit
             unsourced conversion
             1 bottle / half bottle after P17e
             100 g chicken · 6 oz salmon regression twins
         Exact branded/flavor clarification is NOT smuggled into this canary;
         P17d proves exact PRODUCT consumption, not product-family ambiguity.

5.       RE-MEASURE current rolling production SEPARATELY. Frozen-population
         movement proves the mechanism; rolling production proves relevance to
         what users are eating now.

6.       IF ownership remains under 40%, attack the next largest CONDITIONAL
         marginal measured after P17. Identity is the current likely winner
         (+18.5 ceiling after P17), but steps 3–5 decide. Do not add standalone
         ceilings.

7.       repeat measure -> tranche -> canary until the ownership threshold is
         crossed.

ORDERED PRODUCT-CORRECTNESS TRACK — parallel to coverage; touches nothing frozen
A. B-1.7b  MATERIALITY   should Arnie ask about preparation/added fat AT ALL?
                         May proceed in parallel because it changes when the
                         product asks, not which coverage tranche is selected.
B. B-1.7a  OILS          if added fat matters, identify a real fat entity;
                         never add a calorie multiplier.
C. B-1.7c  COMPOSITION   chicken + olive oil = two canonical contributions.
                         Depends on B.

INDEPENDENT REPAIR TRACK — parallel to both
D. B-1.8   CANONICAL CORRECTION / REPAIR — 🟡 ACTIVE *(GO Danny,
           2026-08-17: highest-value use of the P17g wait — a hard rollout
           gate under EVERY measurement outcome)*.

           THE CORE CONTRACT *(Danny, verbatim)*:
             correction -> bind existing canonical event -> load persisted
             evidence snapshot / pricing receipt -> change ONLY the corrected
             semantic fact -> deterministic reprice -> mutate ledger/day
             totals -> preserve provenance -> never fall back to legacy.
           THE CRUCIAL PROOF: correction REUSES what Arnie already knew.
           "2 eggs -> 3 eggs" changes the scaling factor against the stored
           evidence — it never rediscovers USDA, never invokes a provider.
           Scope is canonical MUTATION, not conversation UX.

           ⭐ THE ARCHITECTURE ALREADY PAID FOR MOST OF THIS:
             MutationAuthority.CANONICAL_OWNER   reserved by the firewall,
                                                 never yet exercised
             MealIntent.CORRECTION               exists, never constructed —
                                                 ledger_source canonical:correction
             owning()                            binds a settled meal to its
                                                 operation (recent window)
             P17f receipt + snapshots            the reprice arithmetic:
                                                 scaling_factor, resolved_grams,
                                                 source basis, evidence ids
           B-1.8 is the path that EXERCISES the authority the firewall
           reserves — the firewall itself is untouched, as frozen.

           SLICES, dark-first like P17:
             B-1.8a  the repair PRIMITIVE — pure, receipt-driven quantity
                     reprice; committed macros × a deterministic ratio; both
                     the receipted path and the ratio path for pre-P17f rows
                     (which is ALL current production rows); refusals typed
             B-1.8a  ✅ primitive (f349c7b, corrected d0d8d1b: resolved
                     mass carries forward on gram repair; a conflicting or
                     newly-stated SIZE refuses as semantic repair; composition
                     claimed as bounded storage rounding, not exact)
             B-1.8b  ✅ routing + the write: correction turn on a
                     canonically owned meal -> bind via owning()/ledger ->
                     authority CANONICAL_OWNER -> canonical:correction event
                     -> idempotent claim, revision++ -> day totals.
                     ⛔⛔ THE FIELD-MERGE CONTRACT *(Danny, verbatim)*:
                         new field STATED    -> replace that field
                         new field OMITTED   -> PRESERVE the existing field
                         conflicting field   -> semantic repair path / refuse
                     "2 large eggs" corrected by "actually 3 eggs" is 3 LARGE
                     eggs. The write must never collapse canonical semantics
                     to the correction's bare words and lose `large` — this
                     rule governs size, preparation, product variant, and
                     every future correction chain.
                     LANDED: correct_quantity() is the FIRST caller of
                     MutationAuthority.CANONICAL_OWNER; the native stage's
                     `_correction_route` (one update_food_entry, quantity-
                     only, canonical row) sends it there before the legacy
                     claim; CorrectionRefused PROPAGATES (A8 re-asserted).
                     Firewall untouched — proven: the row the owner just
                     corrected still refuses INFERRED_INTERPRETATION.
                     ⚠ FOUND BY THE FIRST TEST: `resolved_grams` was never a
                     COLUMN — in the receipt payload since P17f, never
                     forwarded by the writer, never migrated; the models-vs-
                     migrations gate could not see it because NEITHER side had
                     it. Paired add: model + writer + _migrate + corrrec001.
                     Only the owner authority may write panel + receipt
                     columns through update_food_entry.
             B-1.8c  identity + product-variant repair — REBIND evidence,
                     then price. Recon fixed the shape: no live path builds
                     SelectProductVariant/SetPreparation yet, and an identity
                     correction arrives as update_food_entry(food_name=...,
                     calories=...) — the interpreter's RE-ESTIMATE. So the
                     repair takes ONLY the new identity, keeps the row's
                     quantity (omitted -> preserved), and reprices through
                     the same assemble()->price() seam settlement uses with
                     THE ESTIMATE RUNG WITHHELD: evidence-backed rung or a
                     typed refusal. Receipt rewritten WHOLESALE (new rung,
                     evidence, basis, factor, snapshot). Route dispatches by
                     kind; the interpreter's numbers are IGNORED, never routed
                     to legacy where they would land. Never reinterprets
                     identity via quantity math.
                     ⛔ THREE P1s CAUGHT ON REVIEW OF 40fcee5, ALL CLOSED:
                       1. identity+quantity chained TWO committing calls — a
                          crash between them left identity NEW, quantity OLD,
                          claim COMPLETED, retry refused. Now ONE call: the
                          quantity rides into the rebind, priced once. Crash
                          twin on Postgres: both old, no event, no claim,
                          retry applies BOTH.
                       2. "wholesale" was an OVERLAY — None values were
                          filtered, so old fiber/sodium/micros/resolved_grams/
                          basis_evidence/conversion ids/snapshot survived a
                          rebind. Now every OWNER_WRITABLE field is present in
                          the write, None = CLEAR; a row never describes two
                          foods.
                       3. THE LEDGER DROPPED EXPLICIT CLEARS (`v is not None`)
                          — a product->generic rebind cleared the snapshot on
                          the row and recorded nothing, so the M1.1 replay
                          could not reproduce it. The `updated` payload now
                          carries the merge distinction: absent = preserved,
                          None = cleared. Pinned by replaying the events.
                     ⭐ #5 DESIGN CHOICE, AGREED: NO revision/CAS column. FOR
                     UPDATE at the repair's READ (not only the write), held
                     through the single commit, is the ONE serialization
                     mechanism; a revision column would be a second one
                     guarding the same property. Proof: two concurrent
                     "actually 3 eggs" against "2 eggs" land at 270 not 405,
                     and the before-states read ["2 eggs","3 eggs"] — a chain.
                     ⛔⛔ SECOND ADVERSARIAL PASS *(Danny)* — SEVEN GAPS, and
                     the fix is ONE STRUCTURAL CHANGE, not seven patches:
                       #2b the generic calorie-ratio rescale in update_food_entry
                           runs BEFORE the owner write, so a rebind RESCALES THE
                           OLD FOOD'S MICROS INTO THE NEW FOOD; the owner write
                           only overrides fields the new evidence supplies
                       #3  ledger undo restores quantity + 4 macros ONLY — not
                           food_name, not the receipt, not the panel. Breast ->
                           thigh -> undo = a HYBRID row. Also true of every
                           B-1.8b quantity correction: macros undone, the new
                           scaling_factor/resolved_grams left behind
                       #5  NO revision on FoodEntry, NO row lock in the repair.
                           Two correction turns both read "2 eggs" and last-
                           writer-wins; their `before` states describe the same
                           ancestor, not a chain. The board says revision++
                           and nothing implements it
                       #6  a product snapshot is a CANDIDATE RUNG, not a binding
                           fact — supplied alongside an unrelated identity, no
                           relationship check; the ladder still runs MEMORY
                           first
                       #7  the merge contract stops at quantity — identity is
                           replaced as a composed string; omitted PREPARATION is
                           not preserved; no SelectProductVariant/SetPreparation
                           producer
                       +   stale metadata: estimated_flag, micros_estimated,
                           alcohol_units, processing_level survive a rebind
                           (wine -> chicken keeps the wine's alcohol)
                     THE FIX: one semantic correction patch; lock/version the
                     row -> reserve ONE claim -> compute the COMPLETE final row
                     + COMPLETE final receipt from the pre-state -> write ONCE
                     -> record full BEFORE + explicit AFTER/clears -> totals ->
                     complete claim -> ONE COMMIT. B-1.8d then proves apply ->
                     replay -> undo -> redo/crash -> concurrent correction, not
                     happy paths.
                     ⭐⭐ STATE AFTER THE SECOND PASS *(Danny, verbatim)*:
                       B-1.8a    ✅ repair primitive
                       B-1.8b    ✅ quantity write
                       B-1.8b.1  ✅ transactional exactly-once
                       B-1.8c1   ✅ generic identity repair
                                 ✅ identity + quantity atomic
                                 ✅ wholesale receipt/panel replacement
                                 ✅ explicit NULL history
                                 ✅ serialized concurrent correction*
                                 ✅ exact undo/replay*
                                 ✅ stale metadata cleared*
                       B-1.8c2.1 ✅ the persisted exact candidate universe:
                                 ExactProductCandidate (NOT the fuzzy search-
                                 result ProductCandidate — different epistemic
                                 states, never to be merged) · discriminated
                                 CandidateSet(candidate_kind) · rode the
                                 candidate_kind column that already existed ·
                                 SelectProductVariant carries the three ids ·
                                 PRODUCT_VARIANT registered · reopening
                                 producer that REFUSES without a persisted set
                                 · verify-not-trust binding check
                                 REGISTRY CONTRACT SHARPENED: Evidence = WHEN
                                 answers may be offered; Vocabulary = WHERE
                                 valid answers come from. Static vocabulary
                                 -> known before the turn; none -> the
                                 persisted universe + a declared membership
                                 reader. Added-fat stays GENERATED+static.
                                 SCHEMA: PATCH_SCHEMA_VERSION NOT bumped — it
                                 rides the WIRE on every patch and the B-1.9
                                 golden pins it for Swift; the changed type
                                 carries its own SCHEMA_VERSION=2 instead.
                                 Zero persisted select_product_variant patches
                                 in production, proven. A v1-shaped payload
                                 (evidence id 0) is UNBOUND, never weakly bound.
                       B-1.8c2.2 ✅ THE CHAIN IS ENFORCED, NOT INVENTED
                                 *(2026-08-18, local, unpushed through review)*:
                                 tap -> answer_from_chip -> STORED patch ->
                                 reopen(op/user/set) -> verify_selection ->
                                 correct_identity(BOUND) -> ONE txn.
                                 · verify_selection proves the WHOLE triangle:
                                   patch is SelectProductVariant with
                                   product_evidence_id > 0 (else
                                   UnboundSelection) · a candidate in THIS
                                   universe has patch.entity_id · that
                                   candidate's product_evidence_id AND
                                   serving_id == the patch's · then
                                   verify_candidate_binding (snapshot exists,
                                   provider:canonical_code == entity)
                                 · BOUND = evidence constraint, mechanically:
                                   assemble(bound=True) does NOT READ memory /
                                   artifact / estimate; price(bound=True)
                                   prices that snapshot or PricingRefused.
                                   correct_identity(product_evidence_id=X) is
                                   bound BY ITSELF — before c2.2 the ladder ran
                                   MEMORY first over an explicit snapshot
                                   binding (proven: with bound mutated off, the
                                   memory-disagrees proofs go RED)
                                 · select_product_variant() =
                                   ProductSelectionRefused (non-mutating: row
                                   byte-identical, zero correction events) or
                                   the repair; exactly-once via the same claim
                                 PROOFS (tests/test_a_tap_binds_to_the_
                                 snapshot_it_offered.py, 9): 123 offered / 124
                                 later / tap -> 123 priced, receipt says 123 ·
                                 candidate from another set REFUSE · another op
                                 / another user REFUSE · patch says 123
                                 candidate says 124 REFUSE · v1 patch (evidence
                                 0) UNBOUND, refused from bound pricing (both
                                 the verifier and price(bound, product=None)) ·
                                 MEMORY disagrees -> NEVER CONSULTED (spy on
                                 _memory: zero calls) · bound PRODUCT cannot
                                 scale ("2 pieces") -> REFUSE, no fallback,
                                 while the same identity UNBOUND prices from
                                 memory.
                                 ⚠ INSTRUMENT NOTES: (a) the memory rung
                                 quarantines a surface key bound to disagreeing
                                 records FLEET-WIDE, so a shared-session test
                                 must use per-user labels or memory abstains
                                 and the proof is vacuous; (b) "2 bars" is a
                                 quantity memory CANNOT price, so the
                                 memory-disagrees proof had to run at "110 g"
                                 to mean anything. Both found by MUTATION, not
                                 by green.
                                 ⚠ FLAGGED, DECIDED *(Danny 2026-08-18)*, NOT
                                 IN c2: (1) "2 cups" of a peanut bar -> vessel
                                 heuristic 260 g -> exact PRODUCT nutrition.
                                 INVARIANT for the P17 authority tranche:
                                   exact product evidence x heuristic quantity
                                   conversion != authoritative settlement
                                 exact nutrition authority does not make an
                                 estimated consumption mass authoritative.
                                 (2) SCAN IS BINDING, like a tap — stronger,
                                 even: the user supplied the exact identifier.
                                 Once acquisition has verified scanned code <->
                                 canonical_code <-> persisted ProductEvidence,
                                 MEMORY may not outrank it:
                                   SCAN-BOUND -> that snapshot only -> PRODUCT
                                   -> price or refuse   (not MEMORY -> PRODUCT)
                                 Same evidence-constraint primitive c2.2 built
                                 (assemble/price bound=True) — a reusable
                                 authority concept, not a new special case.
                                 FIX IN THE P17 SCAN/BINDING TRANCHE, after
                                 c2.3. Settle today still runs the unbound
                                 ladder for a scan.
                                 NOT WIRED LIVE: no producer opens a
                                 PRODUCT_VARIANT operation yet (form B, the
                                 acquisition wire), so no live turn reaches
                                 select_product_variant. The chain is enforced
                                 for the day it does.
                       B-1.8c2.3 ✅ SetPreparation *(2026-08-18, local)*:
                                 correct_preparation(entry, prep) -> lock ->
                                 split OLD identity UNDER THE LOCK (entity
                                 preserved structurally, old prep dropped) ->
                                 name_with(entity, prep) -> _rebind: local
                                 evidence for entity|prep, ESTIMATE withheld,
                                 wholesale receipt, one claim / one event /
                                 one commit. Unregistered prep -> refuse
                                 BEFORE the lock (name_with would silently
                                 drop it and still write a row+event).
                                 REFACTOR: correct_identity and
                                 correct_preparation share _locked_owned_row
                                 + _rebind — one transaction path, and what a
                                 repair derives from the row is derived under
                                 FOR UPDATE (B-1.6a: a lock over a stale read
                                 still loses the write).
                                 TWINS (tests/test_a_preparation_repair_
                                 keeps_the_entity.py, 6): grilled chicken +
                                 SetPreparation(fried) -> "chicken, fried" ·
                                 grilled chicken + "chicken thigh" -> chicken
                                 thigh, NOT grilled chicken thigh (a grilled-
                                 thigh memory row at 999 kcal present and NOT
                                 chosen) · no evidence -> refuse, row byte-
                                 identical, zero events · unregistered prep
                                 refused · duplicate -> exactly once · undo ->
                                 exact old snapshot. MUTATION: name_with(old_
                                 name, prep) ("Grilled chicken, fried") turns
                                 3 twins RED.
                                 NOT WIRED LIVE, deliberately: the interpreter's
                                 update_food_entry has no preparation field
                                 (a text "actually fried" arrives as food_name
                                 and takes the identity path, which lands on
                                 the same chicken|fried); the typed producer
                                 is the B-1 PREPARATION field on a correction
                                 operation, which does not exist yet. The
                                 primitive is ready for it; the route is not
                                 invented ahead of it.
                       B-1.8c    ✅ EFFECTIVELY DONE (c1 · c2.1 · c2.2 · c2.3):
                                 the reusable authority primitive (bound
                                 evidence constraint) + the persisted-universe
                                 producer + preserve/replace semantics. What
                                 remains for B-1.8 is PROOF (d), not
                                 architecture: twins + E2E + rollback/canary +
                                 the stale-event undo twin.
                       B-1.8c2   ✅ (was ⏳) PRODUCER-BOUND SEMANTIC REPAIR —
                                 closed by c2.1–c2.3 above; original statement
                                 kept for the record:
                                   -> a producer emits typed
                                      SelectProductVariant / SetPreparation
                                   -> binds the exact snapshot / semantic field
                                   -> snapshot <-> identity compatibility
                                      ENFORCED
                                   -> omitted semantic fields PRESERVED
                                   -> canonical repair CONSUMES that binding,
                                      and once it says "this exact snapshot",
                                      PRODUCT is BINDING, not merely another
                                      rung in MEMORY -> PRODUCT -> ARTIFACT
                                 The correction machinery must not invent this
                                 contract before its producer exists. The
                                 snapshot-rebind PRIMITIVE is already valid;
                                 what is missing is authoritative ACQUISITION
                                 of the semantic correction, not pricing.
                       B-1.8d    ⏳ PROOF, NOT ARCHITECTURE *(2026-08-18,
                                 semantics frozen at c2.3)*. Local, unpushed:
                                 ⭐⭐⭐ #4 STALE-EVENT UNDO — THE PREREGISTERED
                                 TWIN FOUND A REAL HOLE, reachable through a
                                 SHIPPED path: plan_for_event (tap-to-undo
                                 backend) targets the event the user pointed
                                 at; restore_recorded_state wrote A's whole
                                 before-state verbatim -> undo A after B
                                 restored pre-A AND erased B. Written RED
                                 first (3 tests DID NOT RAISE), then the guard:
                                 _invert stamps `undoes_event_id`; the restore
                                 locks the row (FOR UPDATE, it had none) and
                                 applies ONLY while that event is the row's
                                 newest ledger event, else StaleUndo (a
                                 CorrectionRefused; non-mutating). Claim
                                 replay is checked BEFORE the tip (same-turn
                                 redelivery = replay None; new-turn
                                 redelivery = stale). An undo naming no event
                                 is refused. Not a semantic tranche: the
                                 guard the directive preregistered.
                                 tests/test_a_stale_undo_cannot_erase_newer_
                                 work.py (4) · tests/test_b18d_the_correction_
                                 lane_is_proven.py (13, incl. 5 Postgres crash
                                 twins RUN for real against local PG
                                 arnie_test_pg — not skipped):
                                   1 APPLY   q · id+q (one write, interpreter
                                             numbers ignored) · product
                                             variant · preparation        ✅
                                   2 REPLAY  every kind: 1 event, 1 completed
                                             claim, from the DB           ✅
                                   3 UNDO    product-variant exact (snapshot
                                             binding CLEARED)              ✅
                                   4 STALE   above                          ✅
                                   5 CRASH   id+q at reservation / staged /
                                             before-commit; restore at staged
                                             / before-commit -> nothing
                                             durable, retry exactly once    ✅
                                   6 CONCUR  existing PG chain twin         ✅
                                   7 E2E     refusal PROPAGATES (A8) and the
                                             legacy executor is instrumented
                                             to FAIL if invoked: never
                                             called (CorrectionRefused and
                                             StaleUndo, through the stage)  ✅
                                   8 ROLLBK  no flag: ownership decides;
                                             legacy row same shape ->
                                             _correction_route None         ✅
                                             CANARY #1 (b8edc11 live, in_sync,
                                             corrrec001) — FAILED, and the
                                             failure was the point:      ⛔→🔧
                                  ⭐⭐⭐ THE NATIVE PLANNER WAS BLIND. user 26,
                                  "actually the grilled chicken breast was
                                  8 oz" (ios:4DB2A7D6): native FoodPlanStage
                                  called the interpreter with board=None —
                                  build_request never carried board /
                                  day_line / last_assistant / regulars /
                                  thread_active; legacy computes all five
                                  inline and the native stage read keys
                                  nobody wrote. Blind -> ZERO ops ->
                                  native_no_plan -> delegated to legacy ->
                                  legacy re-interpreted WITH its board ->
                                  update_food_entry(3026, 8 oz) under
                                  INFERRED_INTERPRETATION -> firewall
                                  REFUSED (ledger 2105 mutation_rejected).
                                  "Undo" re-routed as the pending update
                                  (structured_update / thread) -> refused
                                  again (2107). Row 3026 untouched; 0
                                  canonical:correction events fleet-wide.
                                  ⚠ AND the reply + macro_card_patch said
                                  "corrected: true, 8 oz, 343" for a write
                                  the DB refused — the phantom-correction
                                  class, in the legacy narrator.
                                  THE PROOF GAP: B-1.8d fed ops straight to
                                  NativeExecutionStage; nothing proved the
                                  PLANNER in front of it could produce a
                                  correction op on the live request shape.
                                  FIX (root, one definition, both lanes'
                                  shapes): core/turns/planner_inputs.py —
                                  board_for / day_line_for / last_assistant_
                                  of / thread_is_active / regulars_for;
                                  FoodPlanStage derives them from db / user
                                  / today_log / messages when the request
                                  lacks them; build_request + chat_service
                                  carry `messages`. tests/test_the_native_
                                  planner_sees_the_board.py (4): the stub
                                  interpreter RECORDS what it is handed
                                  (board with the real row id, thread_active
                                  True, last_assistant); explicit board not
                                  overridden; build_request carries the
                                  thread; E2E plan -> validate -> native
                                  stage -> canonical correction with the
                                  legacy executor instrumented to fail.
                                  MUTATION: wiring off -> 2 RED, the E2E one
                                  failing exactly the production way.
                                  CANARY #2 (231fcf9 live): THE LANE FIRED —
                                  first canonical:correction in production
                                  (event 2110, claim 80, row 3026 6->8 oz,
                                  ratio-priced) — and two more findings:
                                  (a) the reply was the "stall" recovery
                                  bubble: NativeRenderStage returned None
                                  for a committed correction (op<->call
                                  identity re-match) -> empty reply ->
                                  delivery substituted "Lost the thread".
                                  FIX: the render stage narrates the
                                  correction's own receipt (CallResult.
                                  correction / result_text, user-grade copy
                                  "Updated the grilled chicken to 8 oz, 343
                                  cal."); turn_metrics.outcome now records
                                  error:<Type> when a stage failed after
                                  commit (it said ok — the instrument lied).
                                  (b) "Undo" ran through LEGACY (source
                                  ledger_undo:v1): LEDGER_UNDO was not an
                                  enabled native lane, so restore_recorded_
                                  state and the B-1.8d stale-tip guard were
                                  NOT on the production path; legacy also
                                  wrote undoes_event_id into a ledger payload
                                  as a "change" (now stripped). FIX = config:
                                  TURN_COORDINATOR_LANES=structured_food,
                                  ledger_undo (Danny, Render). E2E proof
                                  through the real entrypoint with that lane
                                  string: correction native -> undo native
                                  (ledger_undo:canonical, restore claim), no
                                  legacy executor.
                                  CANARY #3 (c74ae98, lanes structured_food+
                                  ledger_undo, allowlist 26) — ✅ CLEAN:
                                  "Actually that was 8 oz grilled chicken" ->
                                  "Updated the Grilled Chicken Breast to 8 oz,
                                  307 cal." · event 2129 canonical:correction
                                  · claim 83 completed · native (llm 1672 ms,
                                  no tools stage). "Undo" -> "Rolled it back
                                  to how it was." · event 2130 ledger_undo:
                                  canonical · claim 84 restore completed · 30
                                  ms, no llm, no legacy · row 3027 byte-
                                  identical to the correction's before-state.
                                  The stale-tip guard is on the production
                                  path.
                       ⛔⛔⛔ B-1.8 CLOSED 2026-08-18. Every closure criterion
                       ✅ including the production canary. THREE canaries were
                       needed and each found something the stage-level proofs
                       could not: (1) the native planner had no board, (2) a
                       committed correction rendered no reply, (3) undo was
                       not a native lane. **Production CONFIRMS a decision; it
                       also finds the wiring in front of the thing you proved.**
                       ⚠ NOTED FOR M1, not B-1.8: ufm 1941501 prices "Grilled
                       Chicken Breast" at 230 kcal / 16.5 g protein / 22.5 g
                       carbs / 10 g sugar per 6 oz — a poisoned memory match
                       settled it and the correction faithfully scaled the
                       poison. Same class as ufm#400.
                       NEXT: P17 scan/binding tranche (scan-bound pricing =
                       the c2.2 evidence-constraint primitive) · P17g/h ·
                       preregistered remeasure.
                                 ⚠ OBSERVED, NOT CHANGED: a propagated
                                 canonical refusal (CorrectionRefused /
                                 StaleUndo / PricingRefused) reaches the user
                                 as the coordinator's generic recovery line
                                 (finalizer.recover -> recovery_message
                                 "llm_error"), not "undo the newer correction
                                 first". Refusal stays canonical (never
                                 legacy) — the CLOSURE criterion — but the
                                 copy is a rendering gap; noted for after
                                 closure, not a semantic tranche.

                       ⭐⭐ c2.0 RECON, DONE — reshapes c2 *(2026-08-18)*:
                         PRODUCT_VARIANT IS NOT MISSING A PARSER. IT IS
                         MISSING A PERSISTED EXACT CANDIDATE UNIVERSE.
                         · CandidateSet.candidates is TYPE-LOCKED to
                           QuantityCandidate — there is no product candidate
                           in the persisted universe at all. ProductCandidate
                           exists as a semantic type OUTSIDE it.
                         · SelectProductVariant.entity_id names a PRODUCT
                           IDENTITY (off:...), not a snapshot
                         · PREPARATION is real infrastructure: registered
                           FieldSpec, pricing=IDENTITY, evidence=ONTOLOGY,
                           its own unresolved_when. SetPreparation = "change
                           THIS event's preparation" — entity preserved
                           STRUCTURALLY, no string comparison
                         · the ladder is a fixed 4-tuple loop, MEMORY first;
                           a bound snapshot is today only a candidate rung
                       ⛔⛔ TWO GUARDRAILS *(Danny)*, BOTH STRUCTURAL:
                         1. do NOT weaken CandidateSet's type check into
                            list[Any]. Replace it with a DISCRIMINATED model:
                            candidate_kind = quantity | product; the set is
                            structurally incapable of mixing kinds
                         2. the producer must answer "WHERE DID THIS EXACT SET
                            OF ALTERNATIVES COME FROM" in stable IDs and
                            persisted evidence ONLY. c2.1's producer REOPENS an
                            already-persisted exact universe (form A); it
                            never assembles one from "similar / same brand /
                            looks related / search again". A correction with
                            no persisted universe and no exact mechanical
                            relation REFUSES. Form B (build the universe at the
                            moment exact evidence exists — the acquisition
                            wire) is a LATER producer, not smuggled into c2.1
                       SCHEMA INVARIANT for SelectProductVariant:
                         entity_id            WHAT product was selected
                         product_evidence_id  WHICH immutable observation
                                              justified it
                         serving_id           WHICH serving, if applicable
                         Written TOGETHER at option generation; the answer
                         path never resolves entity_id then looks up "latest".
                         TEST: option from snapshot 123, snapshot 124 inserted
                         later, tap old option -> settles 123.
                       BOUND PRICING = an EVIDENCE CONSTRAINT, not a priority:
                         bound=False  MEMORY -> PRODUCT -> ARTIFACT -> ESTIMATE
                         bound=True   the specified snapshot ONLY -> scalable:
                                      price · not scalable: REFUSE. No fallback.
                       c2 ORDER: c2.1 ✅ discriminated universe + snapshot-
                       bound ExactProductCandidate + PRODUCT_VARIANT FieldSpec
                       + reopening producer · c2.2 ✅ tap -> stored patch ->
                       exact candidate in exact revision -> exact snapshot ->
                       BOUND pricing · c2.3 ✅ SetPreparation: preserve
                       entity, replace prep, evidence rebind ("grilled chicken
                       -> chicken thigh" does NOT keep grilled). NEXT: B-1.8d.
                       ⛔ B-1.8 IS NOT CLOSED UNTIL c2. The frozen directive
                       names "actually it was the Elite one" and "actually it
                       was Cookies & Cream" as B-1.8's own examples; moving
                       them out now — after discovering the producer does not
                       exist — would move the rollout goalposts. It stays.
                       * = local, pending independent verification
                     ⚠ LIVE PRODUCT-VARIANT CORRECTION IS NOT PRODUCTION-
                       COMPLETE: the primitive accepts product_evidence_id;
                       the live route does not thread one, because no
                       producer yields it for a text correction
                       (SelectProductVariant still has no producer). Generic
                       identity repair is live; snapshot rebind is a proven
                       primitive awaiting its producer.
             B-1.8d  twins + E2E + rollback proof
           ⚠ pre-P17f rows carry NO receipt: their quantity repair is the
           macro-ratio path (committed macros ARE the persisted facts) —
           evidence-preserving by construction, and typed refusal where no
           deterministic ratio exists (cross-dimension without evidence).
           Must handle more than amount corrections:
             "actually that was 8 oz"
             "actually it was 3 eggs"
             "actually it was the Elite one"
             "actually it was Cookies & Cream"
           Corrections bind to the canonical event, reuse persisted nutrition
           and conversion evidence where still applicable, reprice
           deterministically, and write a ledger mutation.
           ⛔ MUST CLOSE BEFORE ANY COHORT EXPANSION.

ROLLOUT GATE — expansion beyond user 26 requires BOTH
           ownership >= 40%                       (bands: §ROLLOUT below)
           AND
           B-1.8 canonical repair CLOSED
⛔ Crossing an ownership threshold does not itself authorize expansion.

PRODUCT-COMPLETENESS GATE BEFORE B-2
           SINGLE-ITEM PRODUCT_VARIANT binding must be canonical and
           production-proven before B-2 composes several product ambiguities.
           This is a destination gate, NOT a command to interrupt P17 or the
           measured post-P17 tranche.
           Current canonical primitives already include
           `ClarificationAttribute.PRODUCT_VARIANT` and
           `SelectProductVariant`; the nutrition field registry still needs a
           real PRODUCT_VARIANT registration/producer before this capability
           may be called canonical.

AFTER SINGLE-ITEM / DEPENDENT SEMANTICS ARE PRODUCTION-PROVEN
           B-2       messy / multi-food — compose independent event-bound
                     quantity / preparation / product-variant fields
           PROMOTE   canonical broadly, only through rollout gates
           DELETE    legacy food system after canonical promotion is proven
           C         conversation / one voice — render structured unresolved
                     state naturally; never derive semantics from prose
           D         personalization / memory — rank/shorten clarification;
                     never supply unstated product identity as fact
           E         coaching intelligence — consume settled canonical truth
           F         proactive agency — decide when to speak / stay silent

PARALLEL SESSIONS -> docs/HANDOFF_PARALLEL_SESSION_0817.md (how, not what)

DO NOT
           loosen canonical eligibility
           reintroduce heuristic authority
           let a guessed serving size/piece weight/package relation grant
                MEMORY / PRODUCT / ARTIFACT ownership
           let an unsourced conversion make `can_scale` authoritative
           stamp placeholder dataset versions into durable evidence
           assert source immutability without a source/version contract that
                actually guarantees it
           turn OFF/USDA/WEB into authority rungs
           let synthesized web evidence price
           reopen legacy authority
           weaken the correction firewall
           change rollout thresholds because a measurement disappointed
           widen solely because ownership crossed a band
           widen because the original P12 canary passed
           sequence by feature name; sequence coverage by measured mechanism
           quote a coverage number without its predicate commit/population
```

### ⏭ §P17 — METHOD AND CURRENT SUBPHASE STATUS *(reconciled 2026-08-17 @ `c406e87`)*

> **PLACEMENT RULE.** This section is METHOD for the tranche selected by §NEXT.
> It may describe how P17 closes; it does not select the program's next tranche
> after P17. §NEXT remains the only executable sequencing board.

### P17 invariants now frozen

```text
AUTHORITY AXIS
    MEMORY · PRODUCT · ARTIFACT · ESTIMATE
    answers WHY nutrition may be used

BASIS / CONVERSION AXIS
    COUNT · PIECE · STANDARD_SERVING · PACKAGE · FRACTION
    + ConversionEvidence
    answers WHAT amount the nutrition describes and HOW it reconciles with intake

QUANTITY PRECEDENCE
    1  USER-STATED EXACT QUANTITY
    2  DIRECT COMPATIBLE AUTHORITATIVE BASIS
    3  SOURCED ConversionEvidence
    4  HEURISTIC NORMALIZED MASS
       -> may support ESTIMATE; NEVER evidence-backed canonical ownership
```

`mass_is_exact` is the existing discriminator for the first class:
`mass_conversion | volume_conversion` are exact; `piece_weight | ontology |
vessel` are not. Do not invent a second authority classifier.

`resolve_scaling(...)` is the one place a consumed quantity meets a source
basis. `price()` consumes the resolution; `can_scale()` asks the same resolver
whether an **authoritative** resolution exists. There is no second eligibility
implementation.

The real-normalizer twins are load-bearing:
- `"2 eggs"` may arrive with heuristic `grams=100`; a sourced `56 g / egg`
  conversion must produce **112 g**, not preserve the heuristic 100
- `"100 g eggs"` remains **100 g**; a sourced per-egg conversion may not
  reinterpret a user-stated exact mass
- an unsourced measure may produce a numeric ESTIMATE path but may not make
  canonical eligibility true
- unit matching uses canonical/user unit semantics before raw `unit_label`, and
  singularizes real production forms (`eggs` vs `large egg`)

### P17 status

```text
P17a     ✅ basis-aware rung contract active
P17b     ✅ direct evidence-backed serving pricing proven
P17b.1   ✅ source unit identity carried and enforced            d540467
P17b.2   ✅ one unit authority / one conversion engine           672efc4
P17-SA   ✅ provider / canonical-authority axes frozen           7a74bf1
P17c.1   ✅ one scaling resolver; `can_scale` shares it          89e606d
P17c.2   ✅ authoritative precedence + real-normalizer twins     0dcc1f8
P17c.3a  ✅ durable source-snapshot identity, no placeholder    c406e87
P17c.3b  ✅ hydrated at FDC 15.3 — 120/124 candidates, 259
         portions, additive-verified, every measure stamped
P17d.0   ✅ OFF raw barcode probe — raw responses committed   ee07427
P17d.1-4 ✅ exact producer, corrected BY the probe before it
         landed (identity guard, serving unit, 100ml trap)     c54077e
         ⚠ dark: no channel yet delivers a barcode to the
         backend — iOS resolves scans client-side and sends
         prose. Acquisition wiring is Danny's sequencing call
P17e     ✅ package + fraction as basis DATA — spp active,
         parity refused when unstated
P17f     ✅ persisted immutable evidence. product_evidence is
         append-only and snapshot-addressed; the pricing receipt
         is COLUMNS on food_entries; assemble() loads-only, proven
         with the OFF client poisoned. Migration prodev001.
         ⛔⛔ INVARIANT: evidence rows are immutable snapshots;
         canonical meal rows reference them; acquisition may ADD
         evidence; settlement may only READ evidence.
         Hardened on review, all three structural not conventional:
           · identity = provider + code + provider_revision +
             fingerprint, each EXPLICIT (revision was hidden in
             the hash; a rev bump with identical facts is now
             visibly two snapshots with one fingerprint)
           · FK RESTRICT — the ENGINE refuses to delete evidence a
             committed meal cites. Caught model/migration drift:
             the model declared the FK, the migration added a bare
             Integer, and only production would have allowed the
             delete
           · provider_revision NOT NULL, '' for revision-less
             providers — a NULL component exempts a row from
             UNIQUE in both Postgres and SQLite
         Dark: nothing writes product_evidence_id until P17f.5
P17f.5   ✅ backend barcode wire (api/chat.py barcode -> acquisition at
         ingress -> SCANNED_PRODUCT_EVIDENCE -> _bind_scanned_product).
         ⚠ FOUND 08-18: ba8e62a also pasted the acquisition block into
         _backfill_city, where `barcode` is unbound -> NameError inside
         `except: pass` -> the CITY BACKFILL silently never ran since.
         Removed in the scan/binding commit.
P17-SB   ✅ SCAN/BINDING *(2026-08-18, GO Danny; takes CF4 + CF5, obeys
         CF6)* — A SCAN IS BINDING, LIKE A TAP:
           verified barcode -> persisted snapshot -> SCAN-BOUND item
           -> predicate judged BY THE SNAPSHOT (look(): _from_product +
              can_scale(authoritative_only=True), the ONE resolver)
                scales authoritatively -> Supported("product")
                heuristic / no quantity -> BoundUnpriceable (a NEW
                verdict; NEVER plain Unsupported, which routes to legacy
                and loses the scan)
           -> settle: assemble(bound=True) never READS memory / artifact
              / estimate; price(bound=True) prices THAT snapshot only and
              REFUSES a heuristic scaling path (CF4)
           -> the bound snapshot id lands on the ROW (product_evidence_id
              was NEVER written by settlement before — the correction
              path wrote it, settle did not; "the meal reads its own
              referenced snapshot" is now true of the row)
           -> BoundUnpriceable: NativeExecutionStage publishes a
              canonical REFUSAL view (blocked call, owner canonical,
              user-grade copy in the label's units: "Got the scanned
              Barebells bar, but I can't price 2 cups of it from the
              label — how many bars was it?"); nothing written, nothing
              claimed, legacy executor never invoked; NativeRenderStage
              narrates it (the same receipt path as corrections)
         NEVER scan -> MEMORY -> PRODUCT (spy: zero _memory reads on a
         bound settle) · NEVER exact product x heuristic mass ->
         authoritative (2 cups / 2 handfuls refused; 2 bars / 110 g
         price) · NEVER scan-bound -> legacy.
         nutrition authority != quantity authority, kept explicit:
         Supported("product") is the ONLY branch of decide() that does
         not require has_mass — because the label counts its own units.
         PROOFS tests/test_a_scan_is_binding.py (11): predicate matrix ·
         bound item not judged by memory/artifact · pricer bound vs
         unbound on the same "2 cups" · settle spy · LIVE SHAPE (CF6):
         plan -> validate -> native stage -> render for "2 bars"
         (settles bound, row carries snapshot id, reply) and "2 cups"
         (refused, no row/claim/event, reply names "bar", legacy
         forbidden) · multi-item scan binds nothing.
         MUTATION: pricer authority check off -> RED; settlement bound
         off -> RED (2); route BoundUnpriceable -> legacy -> RED.
         A11 purity gate widened by NAME to the third verdict type.
         STATE *(Danny, 2026-08-18)*:
           P17 SCAN/BINDING IMPLEMENTATION     ✅
           CF4                                ✅
           CF5                                ✅
           CF6 backend/live-shape proofs      ✅
           LIVE iOS PRODUCER                  ⏳  (barcode on ChatRequest)
           LIVE CANARY                        ⏳  (deferred — option (b))
           P17g                               BLOCKED only on the iOS field
         ⛔ WHY DEFERRED, NOT RUN VIA THE API *(Danny)*: option (a) — curl
         with a token — would prove the backend endpoint can ingest a
         barcode; it would NOT prove the production producer that
         matters. CF6 exists because stage-level / live-shape substitutes
         miss wiring defects — learned three times in B-1.8. The canary
         waits for the real producer.
         ⭐ PREREGISTERED LIVE CANARY (run when iOS ships the field):
           1. scan Barebells 70004199
           2. "2 barebells bars"
              -> PRODUCT-bound · exact snapshot · label-unit scaling
              -> product_evidence_id PERSISTED ON THE ROW and EQUAL TO
                 THE ACQUISITION SNAPSHOT ID from that scan (inspect the
                 row: not merely pricing_rung=product) · no MEMORY read
                 (turn_metrics/log: no memory rung consulted)
           3. scan the same product again
           4. "2 cups of barebells"
              -> BoundUnpriceable · ZERO food write · ZERO claim · ZERO
                 legacy execution · the user gets the deterministic
                 quantity clarification in the label's units
           Every "zero" is asserted from food_entries / ledger_events /
           idempotency_records, never from reply text.
         The frozen 232-meal population carries no product_evidence_id,
         so decide()'s new branch is inert on the remeasure. 40% gate
         unchanged.
         ⭐ _backfill_city REGRESSION (its own, per Danny — `except: pass`
         hid a dead path): tests/test_the_city_backfill_actually_runs.py
         — behaviour (an empty city gets filled) + STRUCTURE (an AST
         free-name check: every name the body reads is bound; the pasted
         `barcode` fails BY NAME — mutation-checked).
P17-iOS  ✅ BARCODE PRODUCER *(2026-08-18, GO Danny; transport only)*
         iOS: arnie-ios branch p17/barcode-transport @ 23f5b2c (off
         b1b/structured-clarification). The scan is an ATTACHMENT: the raw
         code is staged on the composer (chip; the on-device lookup only
         decorates it, never the wire) and rides the NEXT send as
         `barcode` — REST body AND the WebSocket frame — consumed by that
         send, carried by the REST fallback and a same-id retry, and by a
         queued batch. The user's words carry the quantity. NO product
         prose is composed on-device any more (the retired
         sendScannedProduct put OFF macros into the message — iOS-side
         product authority; gone). ArnieTests/BarcodeTransportTests (4;
         mutation: dropping the code from send() -> 2 RED).
         ⛔⛔ BACKEND FINDING WHILE WIRING IT: EVERY WEBSOCKET TURN HAS
         RAISED NameError SINCE ba8e62a. The acquisition block was pasted
         into THREE functions; only _coached_reply got the parameter.
         `_stream_turn` (the WS turn = every iOS turn) read `barcode` as
         a global that does not exist -> the handler answered
         {"type":"error"} -> iOS silently fell back to REST /chat. That is
         why production kept working and why nobody saw it: every iOS
         turn since P17f.5 paid a failed WS round-trip first, and
         coalescing never ran. AND the WS handler never read `barcode`
         from the frame at all — the P17f.5 field existed on REST only,
         a dead transport for the producer that matters (CF6, exactly).
         FIXED: the frame carries `barcode` (sanitised like ChatRequest),
         the coalesced turn carries it, `_stream_turn` takes it.
         tests/test_the_chat_ingress_binds_every_name.py: an AST free-
         name gate over EVERY function in api/chat.py (mutation: the
         original paste is named: {'_stream_turn': {'barcode'}}) + a WS-
         frame transport proof (barcode -> _stream_turn -> acquisition ->
         SCANNED_PRODUCT_EVIDENCE bound for the turn) + the _backfill_city
         behaviour test.
         ⚠ DEPLOY IMPLICATION: the live canary needs THIS backend commit,
         not 90a5304 — 90a5304's WS handler would drop the iOS field.
P17-LC1  ⛔→🔧 LIVE CANARY #1 *(2026-08-18, backend 7ef684d, iOS build
         386 on Danny's phone)* — THE TRANSPORT WORKED END TO END: scan ->
         product_acquired code=70004199 snapshot=1 -> native lane ->
         BoundUnpriceable. Two PRODUCER findings, both honest, both fixed:
           1. THE LABEL HAS NO UNIT NOUN. OFF 70004199 as acquired: per-
              100 g, serving 55 g, no "bar", no product_quantity — the
              P17d probe's exact shape. "2 bars" is NOT authoritative from
              this record and the refusal was CORRECT — but the copy asked
              "what was the weight" while the label DOES state a 55 g
              serving, and the pricer offered no way to count it
              (`_product_measures` needed a noun). FIX: the label's own
              serving is a SOURCED conversion under the noun "serving"
              (P17 precedence class 3), provenance = OUR SNAPSHOT — the
              OFF revision is mutable at OFF, but rev@modified_t is pinned
              by the append-only, fingerprinted, FK-RESTRICT store (the
              P17f invariant), which is the source/version contract the DO
              NOT list demands before asserting immutability. "2 servings"
              / "half a serving" / "110 g" now price bound (110 g resolved,
              conversion id off:70004199 on the row); "2 bars" / "2 cups"
              still refuse. The refusal is in the label's terms: "the label
              lists a 55 g serving — how many servings, or how many grams?"
              P17d REFINED, not loosened: a count of a FOREIGN noun still
              cannot multiply the label; a count of the label's OWN unit
              can. (Directive P17d text and off.py docstring amended.)
           2. THE INTERPRETER ASKED FLAVOR FOR A SCAN-BOUND ITEM ("Salty
              Peanut or Caramel Cashew?") -> no op -> native_no_plan ->
              LEGACY. A barcode proves WHAT: the plan stage now approves a
              scan-bound SINGLE item whose only ambiguities are identity-
              class (identity/brand/variant/flavor — food_turn's own
              vocabulary) and lets the bound predicate decide the QUANTITY.
              Unbound, the same ask stays an ask; a quantity ambiguity is
              NOT answered by a scan (proven). Aligned with P17d: the
              "sibling ambiguity is not exact PRODUCT" clause is about NO
              barcode. The op is built by `core.food_turn._log_call` — the
              SAME item->op builder the native ConfirmReplayPlanStage already
              imports ("one item->call codepath"); food_turn is the
              interpretation boundary both lanes consume, not legacy
              run_turn. Follow-up, not semantic: give that builder a public
              name (two native stages now import an underscore name).
         PREREGISTRATION CORRECTED (recorded, not rewritten): step 2 said
         "2 barebells bars -> label-unit scaling"; that assumed the label
         names its unit. It does not. The honest step 2 for THIS record is
         "2 servings of the barebells" (or grams); "2 bars" yields the
         deterministic ask in the label's terms. Step 4's "2 cups": the
         interpreter coerced "cups" -> "bar" (msg='2 cups of barbells',
         unit=bar), so that arm is not reproducible through the model; the
         heuristic-mass refusal is proven at the live shape ("2 handfuls",
         "2 cups" straight into the stage) instead.
         PROOFS: tests/test_a_scan_is_binding.py +9 (20 total): OFF prod
         shape matrix · 2 servings settle bound with snapshot id AND
         conversion on the row · 2 bars refused in the label's terms ·
         the interpreter's flavor-ask payload VERBATIM -> execute (unbound
         -> ask; quantity ambiguity -> ask).
         Also proven live: no MEMORY read on the bound turn (turn_metrics
         stages: pricing.usda_search + llm only), zero food writes, zero
         claims, no legacy execution on the refused turn.
         CANARY #2 (after deploy): scan -> "2 servings of the barebells"
         -> row product_evidence_id == snapshot id, resolved_grams 110,
         conversion off:70004199 · scan -> "2 barebell bars" -> ask names
         the 55 g serving, zero write/claim/legacy.
P17-LC2  ⛔→🔧 LIVE CANARY #2 *(2026-08-18, e7da0da live, build 386)* —
         the chip works, the scan rides the frame (product_acquired
         70004199 at 19:04:16 and 19:05:08, turn_native) — and EVERY turn
         still went legacy. reason=pending_clarification: legacy's flavor
         question from 18:10 ("Salty Peanut or Caramel Cashew?",
         pending_questions 2198) carries a log_date, so pending_expired
         keeps it LIVE UNTIL TOMORROW, and every later Barebells message
         was routed as its ANSWER: the interpreter ran with the prior and
         either "pass"ed (19:04, 19:08) or re-asked and run() refused the
         re-ask (reask_refused, 19:05) -> None -> no op -> native_no_plan
         -> legacy narrated ("already logged" / "logged" with NO row —
         phantom). The bound predicate never got a turn. A LEGACY PENDING
         QUESTION IN FRONT OF THE PRODUCER — the third producer-side layer
         the canaries have found (planner inputs, interpreter identity
         ask, now the pending prior).
         FIX (root, small): a scan-bound turn is a fresh, exact statement,
         not an answer — FoodPlanStage interprets it COLD (no prior). The
         pending row is left as it is (legacy's row, legacy's expiry); it
         just cannot hijack a bound turn. Unbound turns still carry the
         prior. Proof: the 19:05 shape (stale prior + bound scan) -> the
         interpreter receives prior=None -> op; unbound -> prior travels.
         ALSO SEEN, legacy CF: "Clear my day" x2 said "Day's cleared" with
         NO tool call and no deleted event; "logged" x2 with no row. The
         narrator claims actions it did not take (see CF8).
         CANARY #3 (after deploy): scan -> "2 servings of the barebells"
         -> bound settle; scan -> "2 barebell bars" -> label-terms ask.
P17-LC3  ⛔→🔧 LIVE CANARY #3 *(2026-08-18, 897b7da live)* — THE BOUND
         PATH FIRED ON BOTH SCAN TURNS (single metric row each, no legacy,
         the label-terms ask rendered) — and the ask was about "2 bar" for
         a message that SAID "2 servings of the Barebells": the interpreter
         rewrote the user's unit (item unit=bar; it treats bar and serving
         as synonyms for this product), so the honest quantity never
         reached the predicate. FIX (narrow, deterministic): for a scan-
         bound single item, the user's STATED label unit (serving(s) /
         grams / oz, literally in their text) outranks the interpreter's
         rewrite — P17 precedence class 1 over a normalisation. "2 barebells
         bars" is untouched and still asks. Proof: the 19:33 op shape
         (unit=bar) + the user's sentence -> settles bound at 110 g.
         ⚠ THE REMAINING DEAD-END, REGISTERED (CF9): the chip is spent by
         the message it rides, so the ANSWER to a bound refusal ("2
         servings") arrives UNBOUND and goes to legacy (turns 9291, 9293:
         legacy asked flavor, then logged a 400-cal guess row 3030). The
         REFUSE arm proved the invariants; the ASK arm Danny specified is
         what makes it usable: BoundUnpriceable should open a pending
         quantity operation that HOLDS the snapshot so the answer settles
         bound. B-1's machinery with a product-bound item — its own
         tranche, before P17g widens anything.
         CANARY #4 (after deploy): scan -> "2 servings of the barebells" ->
         bound settle, row product_evidence_id == snapshot 1, resolved_grams
         110, conversion off:70004199, calories 220 (not 400).
         ⛔ GATE STATUS, STATED PLAINLY *(Danny asked)*: NOT CLEARED. Proven
         live are INVARIANTS (transport, bound decision, no memory read, no
         legacy on a bound turn, non-mutating refusal, refusal rendered).
         The preregistered OUTCOME — a bound settle with product_evidence_id
         on the row — has NOT happened: zero bound rows exist; every attempt
         reached the predicate as "2 bar", and this label names no bar. The
         refusal is CORRECT under the frozen rules (CF4 / P17-SA: "a bar is
         one serving" is not a fact this record states) — which means the
         canonical lane cannot settle the most natural post-scan phrase from
         OFF's data shape; it can only ask. Danny's decision, on the record:
           1. accept the ask for foreign nouns (honest) -> needs the unit
              fix (this commit) + CF9 (the ASK arm holding the snapshot)
           2. additive mechanical single-serve rule when the provider
              states product_quantity == serving_quantity (not on this
              record; helps records that state it)
           3. nothing else is honest — mapping "bar" -> serving without a
              stated fact is the frozen invariant.
         P17g stays blocked until a bound settle exists in production.
         ⛔⛔ DECIDED *(Danny, 2026-08-18)*: OPTION 1. "The refusal proves the
         authority boundary is working; it does not prove P17 can own and
         settle a scanned product in production." DO NOT translate bar ->
         serving: the user-facing inconvenience is real and preferable to
         silently violating CF4. The mechanical single-serve rule is
         acceptable LATER only when evidence explicitly establishes
         product_quantity == serving_quantity — never to rescue 70004199,
         where that fact is absent. ORDER:
           1. push unit-precedence fix (7d1926b) — servings/grams survive
              interpretation unchanged                              ✅
           2. deploy backend + compatible iOS build (386 is)         ⏳
           3. CANARY #4 — direct authoritative quantity: scan 70004199
              -> "2 servings of Barebells" -> snapshot stays bound ->
              PRODUCT pricing -> 110 g deterministic scaling -> canonical
              row committed -> row.product_evidence_id == acquired
              snapshot id -> zero MEMORY reads -> zero legacy -> correct
              rendered confirmation                                  ⏳
           4. BUILD CF9 — bound clarification continuity: scan 70004199
              -> "2 bars" -> BoundUnpriceable ASK -> snapshot SURVIVES
              without reacquisition -> "2 servings" or "110 g" -> the
              SAME bound snapshot settles canonically -> no legacy during
              either turn                                            ⏳
           5. run the complete two-turn production canary            ⏳
           6. close CF9, then P17g                                   ⏳
         Canary #4 proves the settlement MACHINERY; CF9 proves the actual
         natural user JOURNEY. BOTH required before P17g is declared closed.
         STATUS: transport/binding invariants ✅ · bound refusal ✅ · bound
         production settlement ❌ · clarification preserves binding ❌ (CF9)
         · P17g ⛔ BLOCKED.
P17-UA   ◻ UNIT-ALIAS EVIDENCE *(Danny, 2026-08-18 — the fix for "2 bars",
         verbatim)*: acquire the missing fact EXPLICITLY. The system knows
         1 serving = 55 g; it must not invent 1 bar = 1 serving. Solution:
         an evidence-backed unit-alias layer attached to the IMMUTABLE
         product snapshot.
         EVIDENCE HIERARCHY — accept bar -> serving ONLY from:
           1. manufacturer/label evidence: "Serving size: 1 bar (55 g)"
              (strongest)
           2. package facts: net weight 55 g + package count 1 bar ->
              deterministic 55 g / 1 bar
           3. barcode catalog with EXPLICIT unit description: structured
              serving text says "bar", not merely "55 g"
           4. user confirmation FOR THIS CONSUMPTION: "The label lists a
              55 g serving. Was each bar one full serving?" — "yes"
              authorizes 2 bars = 110 g for THAT ENTRY; never silently
              promoted to a global product fact.
         ARCHITECTURE (snapshot-scoped): unit evidence rows keyed to the
         exact snapshot id — consumer_unit "bar", consumer_units_per_
         serving 1, provenance (manufacturer_label | package_facts |
         catalog_serving_text | user_confirmed:<entry>), evidence capture
         id. Pricing is then MECHANICAL: 2 bars x 1 serving/bar x 55 g/
         serving = 110 g — every edge evidence-backed, no heuristic.
         WHEN OFF LACKS THE NOUN: attempt deterministic enrichment at
         acquisition (structured serving text -> package facts -> optional
         label scan/OCR later) -> persist the exact relationship; if none
         supplies "bar": ASK "The label gives nutrition per 55 g serving.
         Is each bar one 55 g serving?" -> yes: settle THIS entry at 110 g
         · no/unsure: request grams or servings · no response: remain
         refused · NEVER memory or legacy.
         PRODUCT-QUALITY (later): label capture after an incomplete scan —
         "Scan the serving-size line" — turns missing provider data into
         durable, auditable product evidence; future scans of that exact
         snapshot then understand "2 bars" without guessing or re-asking.
         => authoritative unit enrichment -> snapshot-scoped unit
            equivalence -> deterministic scaling -> clarification only
            when evidence remains incomplete.
         SLICES: A) ✅ product_unit_evidence table (append-only, snapshot FK
         RESTRICT, migration produnit001 — /health must show it applied)
         + model + store (provenance-typed; a user_confirmed row is
         consumption-scoped, user+entry named, never global) · B) ✅
         acquisition producer for sources 2/3 (strict deterministic parse
         of OFF serving_size / quantity+product_quantity; "1 bar (55 g)"
         -> bar x1; "55.0g" -> nothing; 70004199 yields NO alias) +
         pricer consumes an alias as a SOURCED conversion (grams_per_unit =
         serving_g / units_per_serving; provenance = the alias evidence
         row); "2 bars" -> 110 g ONLY with an alias, refuses without;
         receipt on the row names unit_evidence:<id>. tests/test_a_
         consumer_unit_is_evidence_not_a_guess.py (7) + PG migration gate.
         · C) ✅ CF9 proper *(local, unpushed until green)*: a
         BoundUnpriceable opens a durable canonical quantity operation
         (core/product_bound_ask.py, on B-1's own open_operation /
         quantity_field / build_interaction / answer path / settle) whose
         stored item CARRIES product_evidence_id; the ask is in the
         label's terms ("The label gives nutrition per 55 g serving — is
         each bar one 55 g serving?") with options whose SEMANTIC object
         is the patch — quantity 2 x unit "serving" (COUNT), display "2
         servings" — never a pre-multiplied mass and never the label
         string. B-1's settle prices BOUND when the stored item carries a
         snapshot and now writes the pricing receipt (B-1 rows never had
         one). Closure proofs (Danny's list; tests/test_a_scan_is_
         binding.py, 29): TURN 1 ask + snapshot persisted + zero write +
         zero claim + zero legacy · TURN 2 typed "2 servings" -> same held
         snapshot, 110 g via the label's serving conversion, bound row,
         product_evidence_id == snapshot, no reacquisition (spy 0), zero
         MEMORY reads (spy 0 — the PREDICATE was reading memory for bound
         items; fixed), zero legacy · TURN 2 tap -> identical · duplicate
         answer -> ONE row (REPLAY) · expired ask ignores prose, tap still
         lands · another user cannot answer · a new scan supersedes the
         open ask · failed settle ("2 cups") does NOT consume the ask ·
         success consumes exactly once.
         ⭐⭐ FOUND BY THE SAFETY PROOFS: `answer_from_text` collapsed EVERY
         answer to a MASS in grams stamped USER_STATED — "2 cups" -> 260 g
         (vessel heuristic) was indistinguishable from typed "260 g", so a
         BOUND settle priced a heuristic mass as class-1 authority through
         the answer door (CF4). Fixed at the source: a non-exact mass keeps
         the user's unit/dimension; grams ride as DERIVED; unbound B-1
         prices as before, bound refuses.
         ⚠ NOT YET: the "yes" is not persisted as user_confirmed unit
         evidence (needs the confirmation keyed to the operation before
         the entry exists — produnit002 — and its own answer semantics);
         the receipt still names the snapshot + the panel conversion.
         ⚠ The native lane does not check for an owning canonical
         operation before interpreting: a typed answer reaches the
         interpreter first, yields no op, delegates, and legacy's block
         calls b1_answer_turn — works, indirect; watch it live.
         · D) label capture (later).
P17-CAN  ⏳ THE TWO PRODUCTION CANARIES *(both required, Danny)*, run on
         7187742 (P17-UA A/B/C + CF9 live; /health must show produnit001):
           DIRECT — scan 70004199 -> "2 servings of Barebells" -> exact
             snapshot stays bound -> PRODUCT pricing -> 110 g deterministic
             (label serving conversion) -> canonical row ->
             row.product_evidence_id == acquired snapshot id -> zero MEMORY
             reads -> zero legacy -> correct rendered confirmation
           TWO-TURN — scan 70004199 -> "2 barebells bars" -> ASK in the
             label's terms (snapshot persisted on the operation, zero write,
             zero claim, zero legacy) -> tap "2 servings" (or type it) ->
             the SAME held snapshot settles canonically -> row.product_
             evidence_id == that snapshot -> no reacquisition -> zero MEMORY
             -> zero legacy
         The BOUND ROW — not the ask — clears the P17g gate.
P17g     ◻ eligibility predicate LAST — BLOCKED until BOTH canaries commit a
         bound row in production
P17h     ◻ mutation + positive twins — after P17g
P17-RM   ◻ frozen 232-meal remeasure — historical anchor 20.3% @ a747b56 +
         paired contemporaneous predicate delta on the SAME run; publish
         BOTH predicate commits; the 40% gate is unchanged
P17-UE   ◻ unit-evidence completion (CF10; §P17-UE) — after the remeasure,
         before cohort expansion
P17h     ◻ mutation + positive twins
```

### ⭐ MEASURED FACTS AND TRAPS THIS TRANCHE ALREADY HIT *(added 2026-08-17 @ `c406e87`)*

Four things the sections below anticipate in the abstract, now measured, plus
two traps that are cheap to walk into and expensive to detect.

```text
HYDRATION SIZE, MEASURED RATHER THAN ESTIMATED   (dry run, no write)
    120 of 124 committed candidates yield a measure     259 portions
    4 candidates yield NONE — a record may simply state no usable portion,
      which is an absence to report, never a gap to fill with a default
    artifact composition: 121 SR Legacy · 3 Foundation · ZERO Branded
```

⛔⛔ **P17d CANNOT SOURCE EXACT PRODUCTS FROM THIS ARTIFACT.** There is not one
Branded row in it. That is not an argument for relaxing PRODUCT admission — it
is the measured reason OFF (or another exact-identity provider) is *required*
for P17d rather than merely preferred, and it should be known before anyone
tries to satisfy P17d from what is already committed.

⛔⛔ **THE STEP-3 RE-MEASURE COMPARES TWO PREDICATES, AND THAT IS BY DESIGN —
SAY SO OR IT BECOMES THE 36.9% FAILURE AGAIN.** The baseline 20.3% was taken at
predicate `a747b56`; the post-P17 number will be taken after P17g has CHANGED
`decide()`. The instrument executes the predicate, so the two figures are not
the same instrument — which is exactly the discipline this document already
requires, and exactly the shape of the failure that cost a day on 36.9%. The
difference is that here the predicate change IS the tranche being measured. So
the delta is legitimate, and publishing it **must name both predicate commits
and the frozen population**, or a later reader will quote one number against the
other as though the instrument had held still.

⚠ **P17g'S REAL INTEGRATION RISK IS GATE B, NOT THE PREDICATE LOGIC.**
`can_scale` needs the SOURCED MEASURES to answer authoritatively, and `look()`
today performs LOCAL READS ONLY and returns booleans. Wiring the predicate to
the resolver therefore means `look()` must obtain measures from already-loaded
local evidence — never by reaching for the artifact loader mid-turn, and never
by a provider call. The predicate is where a retrieval could quietly re-enter
the settle path after `price()` was made synchronous specifically to forbid it.

⭐ **AND THE CANARY NEED NOT RE-PROVE "no provider/model call at settlement".**
`price()` is synchronous: there is no `await` in it, so no provider or model
call can hide there. That is a structural guarantee, stronger than any observed
run, and the canary's effort is better spent on the claims only production can
settle — that the path EXECUTED, that refusal twins stayed refusals, and that
rollback stops consumption without corrupting shadow evidence.

⚠ **A UNIT MATCHER THAT CANNOT FOLD A PLURAL DISABLES THE WHOLE TRANCHE
SILENTLY.** `unit_matches` appended an optional `s` to the search term only, so
it matched `egg` inside `eggs` but not `eggs` against USDA's `large egg` — and
production normalization yields `unit="eggs"`. Every real count would have
failed to match while every synthetic test passed. This is the standing shape of
the hazard: the capability looks landed, the gates are green, and it never fires
once in production.

### P17c.3a — durable source-snapshot identity BEFORE hydration

⛔ `dataset_version="committed_artifact"` is a placeholder, not a source
version. It may not be baked into authoritative `SourceReference`s.

A durable source reference must make a later correction able to answer **which
source facts were actually committed**, not merely which provider/key would be
queried today.

Required shape/consequences:

```text
dataset_id          provider dataset identity, e.g. usda_fdc
dataset_version     meaningful provider release/snapshot identity when known
record_key          provider record id, e.g. FDC id
record_version      provider record version OR exact captured snapshot identity
data_type           preserved as provider-structured metadata
content fingerprint fingerprint of the exact normalized source facts committed
```

`SourceReference` already requires a `record_version` OR an
`immutable_within_version` declaration. Therefore:

- set `immutable_within_version=True` **only** when the underlying source/version
  contract actually guarantees the record cannot change inside that version
- if the live provider does not expose a trustworthy release/record version,
  do **not invent one** and do not claim immutability; capture the exact build-time
  record/snapshot and give that snapshot a durable version/fingerprint
- same `record_key` observed under two distinct source snapshots must produce
  distinguishable references
- missing durable source identity means a conversion may not grant canonical
  authority
- nutrition evidence and serving/conversion evidence are separate claims even
  when they came from the same provider record

This is the last cheap point to settle the contract: the artifact is still
unchanged. Hydrating first and correcting provenance second turns a dark-path
contract edit into a data migration over every committed measure.

### P17c.3b — USDA structured measure hydration

Only after P17c.3a is green:

- fetch `/food/{fdc_id}` detail at BUILD time, never settlement
- preserve serving panel measures and `foodPortions`
- carry provenance through both paths symmetrically
- normalize every measure into the existing `ConversionEvidence` contract
- rebuild the artifact only after the conversion representation is final
- re-measure actual candidate/portion counts; the previous dry run observed
  roughly 124 candidates / 259 portions, which is evidence about that run, not
  a permanent constant

`core/portions.py` piece weights remain sanity/estimate machinery. They do not
become authority because USDA happened to agree with one of them.

### P17-SA — source / authority contract *(FROZEN before P17d)*

PROVIDER AND CANONICAL AUTHORITY ARE INDEPENDENT AXES.

```text
USDA · OFF · manufacturer web · restaurant web    WHERE a record was retrieved
MEMORY · PRODUCT · ARTIFACT · ESTIMATE             WHY nutrition is authorized
```

1. **No provider receives authority because of its name.** Deterministic policy
   assigns authority to a claim.
2. **OFF is a PRODUCT producer, never a PRODUCT rung.** PRODUCT requires
   mechanically exact identity: GTIN/barcode or an already-bound stable
   `product_variant_id`. Provider `_match`, string similarity and model
   confidence establish no such identity.
3. **USDA is a provider, not a synonym for ARTIFACT.** Qualified structured
   generic-food records ordinarily feed ARTIFACT; other structured providers
   must be able to do the same without inventing new rungs.
4. **`evidence_type=synthesized_text` never prices.** It may support semantic
   classification, materiality, clarification or discovery.
5. Web/search may discover an attributable first-party structured source. The
   source may price if it independently satisfies canonical policy; the
   synthesis that found it may not.
6. The semantic resolver may classify what a record means. **Code decides
   authority.**

### P17d — exact PRODUCT producer

Replace `"product": None` with a real producer, but keep the admission narrow:

```text
ALLOWED
barcode / GTIN
already-bound stable product_variant_id
equivalent mechanically exact stable identifier

NOT ALLOWED
provider "_match"
brand/name overlap
fuzzy search rank
model confidence
user-history prior by itself
```

If a label says `1 bar = 200 kcal` and the user consumed one of that exact bar,
the authoritative path is direct per-bar scaling. Do not route through grams
merely because grams also exist.

*(Refined 2026-08-18, live canary #1.)* When the label states a serving MASS
and no unit noun (OFF's usual shape: `serving_size 55.0g`), the label's own
serving is still a unit the label names — "serving" — and a count of it is a
SOURCED conversion (precedence class 3, provenance = the immutable snapshot).
A count of a FOREIGN noun ("2 bars", "2 bottles") is not, and refuses; the ask
is in the label's terms.

**P17d does NOT own product-family ambiguity.** `"Barebells bar"` with an
unstated flavor is not exact PRODUCT merely because OFF returns plausible
siblings. That belongs to canonical PRODUCT_VARIANT binding described in the
placement section below.

### P17e — PACKAGE + FRACTION

Represent relationships as conversion data, never a new branch in
`scale_profile()`:

```text
1 bottle = 2 servings
half bottle = 1 serving
half bar = 0.5 bar
```

FRACTION never prices independently; it modifies an evidenced parent.

### P17f — persisted dual provenance

Persist enough to deterministically replay a later repair:

```text
rung
nutrition_evidence_id
source_basis
basis_evidence_id
conversion_evidence_ids
source_amount
source_unit
scaling_factor
source snapshot/version/fingerprint
```

USDA nutrition and USDA `1 large egg = 56 g` are two claims. B-1.8 must be able
to change 2 eggs -> 3 eggs by reusing those claims, not by rediscovering USDA.

### ⭐⭐ P17 REMEASURE — PREREGISTERED *(Danny, 2026-08-17, BEFORE the measurement exists)*

⛔ WRITTEN DOWN NOW so the result cannot be argued into a different question
later — the same discipline as the P12 canary preregistration.

```text
POPULATION      p16b_0817 — the identical 232 meals, sha 6247a33c55ed64f5
BASELINE        ~20.3%   predicate a747b56   THE PREREGISTERED ANCHOR — kept
                ~20.0%   predicate 00cdcfd   a SURVIVOR AUDIT after two rows
                         were deleted live (not memory drift — corrected). The
                         P17 delta is published against the ANCHOR on the
                         self-contained 232-meal fixture M1.1 produces. If
                         reconstruction is impossible, old and new predicate
                         run SIDE-BY-SIDE over the same survivor snapshot and
                         the result is labelled a CONTEMPORANEOUS PAIRED DELTA,
                         not the original preregistered experiment.
✅ M1.1 UNBLOCKED THE REMEASURE: the fixture cannot shrink; the delta is
   published against the preregistered 20.3% on the identical 232 meals.
⭐ BUT M1.1 FROZE THE INPUT POPULATION, NOT THE EVIDENCE STATE *(Danny)*. The
   instrument still executes coverage_for() against the LIVE database, so
   between now and the remeasure memory/evidence rows can change and a meal's
   answer can move for reasons other than P17g. TWO NUMBERS AT REMEASURE:
     1. HISTORICAL ANCHOR      20.3% @ pre-P17 predicate -> X% @ P17,
                              same frozen 232 inputs (the preregistered headline)
     2. PAIRED CONTEMPORANEOUS pre-P17 predicate NOW vs P17 predicate NOW,
                              same 232 inputs, same evidence state, same run —
                              only the eligibility predicate differs. THE
                              STRONGEST CAUSAL ANSWER to "what did P17 change".
   If they agree, excellent. If 20.3->42.0 historical but 20.8->42.0 paired,
   0.5 pts is evidence drift and 21.2 is P17. Evidence is NOT frozen wholesale
   unless it falls out cheaply — paired evaluation is cleaner.
⚠ LEDGER-INVARIANT DEFECT, TRACKED SEPARATELY (not M1.1's, not B-1.8's):
   entry 2674 mutated "Ground beef, seasoned" -> "Ground bison, seasoned" with
   NO ledger event — an unledgered production write. Every food mutation is
   supposed to record an event; one path does not. Owner: the ledger
   invariant (I3-family). Do not derail the correction track for it.
EXPECTED GAIN   +12.2 .. +24.8 pts  ->  ~32.5% .. ~45.1%
PUBLISH         BOTH predicate commits, or it is not a figure

THE QUESTION    how much HISTORICAL food traffic becomes canonically ownable
                because sourced serving conversions are now authoritative and
                P17g admits them?

NOT THE QUESTION  the barcode wire. Those 232 meals contain no barcode event,
                and any scan-infrastructure contribution to this number would
                make the measurement LESS trustworthy, not more. Scan coverage
                arrives through FUTURE traffic and is measured there.

INTERPRETATION, FIXED IN ADVANCE
    ~37%   NOT a failed P17 — a clean measurement saying the next tranche
           comes from the largest remaining CONDITIONAL marginal (Δ(M|P17):
           identity +18.5 ceiling; only cacheability certain at +3.2)
    ~43%   coverage gate crossed — and rollout still does NOT widen until
           B-1.8 correction/repair closes. Two clocks, as frozen.
```

GO CONDITION FOR P17g *(Danny)*: the iOS barcode field is shipped AND the
deploy has advanced with /health showing schema.applied = expected = prodev001,
in_sync = true. Then P17g immediately.

### P17g — predicate LAST

Only after producers, provenance and scaling are settled may `ItemFacts` /
`decide()` admit a count-only item when the **same scaling resolver used by
pricing** says an authoritative local path exists.

The predicate must not ask:
- whether mass happens to be present
- whether a basis field exists
- whether a provider returned something
- whether a heuristic can produce a number

It asks: **can this authoritative evidence be scaled to this consumed quantity
without retrieval, guessing or unsourced conversion?**

The freeze manifest changes in the same commit as the intentional predicate
change.

### P17h — mandatory positive and mutation twins

Positive:

```text
2 eggs
2 large eggs
source disagreement with piece-weight prior -> source wins
100 g eggs -> user mass wins
1 medium banana
exact 1 Barebells bar
half exact Barebells bar
1 Fairlife bottle
half Fairlife bottle
100 g chicken
6 oz salmon
```

Mandatory RED mutations:

```text
delete basis evidence
remove conversion provenance
replace sourced conversion with model/ontology guess
restore placeholder dataset_version
claim immutable source with no version contract
change egg unit to slice
use whole-roll basis for one sushi piece
ignore package -> servings
allow FRACTION with no evidenced parent
default a missing new-evidence basis to Per100g
let fuzzy product search construct PRODUCT
make `can_scale` disagree with the pricer
```

### ⏭ §P17-UE — AUTHORITATIVE CONSUMER-UNIT EVIDENCE *(Danny, 2026-08-18; DIRECTIVE, verbatim)*

> **PLACEMENT.** Registered as **CF10**. Owner: **P17-UE — UNIT EVIDENCE
> COMPLETION**. Do not interrupt or expand CF9 slice C. P17-UE begins ONLY
> after: (1) P17-UA A/B pushed · (2) CF9 holds the exact snapshot across
> clarification · (3) the direct bound-settlement canary is clean · (4) the
> two-turn ASK → answer → settlement canary is clean · (5) P17g/h closes ·
> (6) the frozen 232-meal remeasure is published. P17-UE must complete
> before barcode rollout expands beyond the existing canary cohort. It must
> not alter the frozen P17 population, predicate, 40% gate, or P17
> attribution.

**Problem.** A scanned product may provide `serving_quantity = 30 g` without
providing `3 pieces = 30 g`. In that state the system cannot authoritatively
settle "1 Twizzler", "1 strand", "2 bars". The missing fact is not nutrition.
It is the relationship between a physical consumer unit and the label's
serving mass. The system must acquire that relationship explicitly. It must
never manufacture it from product shape, category, product name, common
sense or average weights.

**Governing invariant.**

```text
Exact nutrition authority does not create consumer-unit quantity authority.

NEVER:  bar ≈ serving · piece ≈ serving · Twizzler ≈ 10 g ·
        single package ≈ one serving
Allowed only when an admissible source explicitly supports the relationship.
```

**Target architecture.**

```text
exact barcode -> immutable ProductEvidence snapshot
  -> consumer-unit evidence acquisition -> typed UnitRelationship
  -> deterministic validation -> snapshot-scoped persistence
  -> deterministic scaling

LABEL: 3 pieces (30 g)
PERSIST: consumer_unit=piece · consumer_units_per_serving=3 ·
         serving_mass_g=30 · grams_per_consumer_unit=10 ·
         provenance=structured_label
THEN:  1 piece × 30 g / 3 pieces = 10 g
```

The model may extract or verbalize the relationship. It may not authorize
the arithmetic or persistence.

**Evidence hierarchy — use the first complete admissible source.**

1. **Structured serving text** — "3 pieces (30 g)", "2 cookies (28 g)",
   "1 bottle (355 ml)", "about 12 chips (28 g)". Persist the exact count,
   printed noun, mass and original source text. If the label says `about`,
   preserve the qualifier — never silently convert approximate label evidence
   into exact evidence.
2. **Explicit package count plus net quantity** — only when the SAME product
   evidence explicitly states both: `package_count = 6 bars`,
   `net_quantity = 330 g` → 330 g / 6 bars = 55 g/bar (mechanical
   derivation). Do not use package appearance, category or a product title
   containing a number as package-count evidence.
3. **Explicit single-serve equivalence** — `product_quantity ==
   serving_quantity` AND `package_count == 1` → one package may equal one
   serving. `product_quantity == serving_quantity` ALONE is insufficient if
   the package count or physical unit remains unknown.
4. **Manufacturer-label image** — if structured fields are incomplete, use
   the exact product's serving-size label image. The model/vision layer
   returns a CANDIDATE only: `{raw_text, consumer_unit, consumer_unit_count,
   serving_mass, serving_mass_unit, image_reference, image_region,
   confidence}`. The image, crop/reference and extracted raw text remain
   attached as provenance. A model assertion without the source image is not
   evidence. If extraction is incomplete, conflicting or visually ambiguous:
   do not persist automatically; ask the user to confirm the printed
   relationship.
5. **User-confirmed package fact** — "The nutrition is listed per 30 g. How
   many pieces does the package say are in one serving?" A reply such as
   "3 pieces" may authorize the current entry. Persist as
   `provenance=user_supplied_package_fact`, `scope=current entry or held
   clarification`. Never automatically promoted to globally verified product
   evidence.
6. **User measurement** — if the package genuinely gives grams only: "If you
   can weigh one piece, send me its weight." A measured answer may authorize
   that entry: `1 piece = 9 g`, `provenance=user_measurement`,
   `scope=current consumption`. Never promoted to a universal product fact.

**Language resolution is not mass authority.** Morphology may be normalised
(piece/pieces, strand/strands, serving/servings), but different nouns are
not automatically equivalent. For an exact Twizzlers product: user noun
"Twizzler", label noun "strand" — do not silently assert Twizzler = strand.
If no explicit product-scoped alias exists, ask: "By one Twizzler, do you
mean one individual strand?" A confirmation may bind the current request's
noun to the label unit. It does not create new mass evidence; the label
relationship still supplies the mass.

**Required state behaviour.**

```text
complete structured evidence:  scan -> "1 piece" -> resolve product-scoped
    UnitRelationship -> deterministic scaling -> canonical bound settlement
incomplete, label image available:  scan -> "1 piece" -> structured evidence
    incomplete -> inspect exact label image -> extract candidate -> validate
    or confirm -> settle against the same snapshot
no complete evidence:  scan -> "1 piece" -> ASK for piece count, serving
    count or grams -> hold exact product snapshot -> answer supplies quantity
    authority -> settle bound
NEVER: incomplete unit evidence -> MEMORY -> generic artifact -> estimated
       average piece weight -> legacy
```

**Persistence.** Store unit relationships separately from nutrition values
and serving rows. Minimum fields: `product_evidence_id, consumer_unit,
consumer_unit_normalized, consumer_unit_count, serving_quantity,
serving_unit, relationship_kind, source_kind, source_text, source_reference,
source_revision_or_hash, is_approximate, verification_state, created_at`.
Use rational count-to-serving arithmetic (`requested_units /
consumer_units_per_serving`); do not prematurely round grams or nutrients —
round only at the presentation boundary. A ProductEvidence snapshot remains
immutable: new or corrected unit evidence creates a new relationship/version;
it never rewrites historical provenance. *(P17-UA's `product_unit_evidence`
is the seed of this table; P17-UE completes the fields and sources.)*

**Conflict policy.** If admissible sources disagree (structured label 3
pieces = 30 g vs image label 4 pieces = 30 g): do not select whichever is
more convenient. Return a typed `ConflictingUnitEvidence`, then ask the user
to scan the current package label or enter grams. A newer image must not
silently rewrite rows settled under an older snapshot.

**Required proofs.** Positive fixtures: 3 pieces (30 g) → 1 piece = 10 g,
3 pieces = 1 serving, 6 pieces = 2 servings · 2 cookies (28 g) → 1 cookie =
14 g · 1 bottle (355 ml) → 1 bottle = 355 ml. Real negative fixture: OFF
70004199 (55 g serving, no bar noun, no package-count relationship) must
produce NO bar → serving relationship; "2 bars" must remain BoundUnpriceable
and must ASK. Natural-language: evidence "3 strands = 30 g" → "1 strand" →
10 g; "1 Twizzler" requires an explicit product-scoped noun alias or
clarification — the product name must not manufacture the alias. Label-image:
structured record incomplete + label image explicitly states 3 pieces (30 g)
→ candidate extracted with source reference → deterministic validator accepts
→ one piece settles as 10 g. MUTATIONS: remove the printed piece count → RED;
change 3 to an unreadable value → refusal/ASK, never settlement; remove the
image reference → candidate cannot become durable evidence; replace the exact
barcode image with another product's image → RED. Safety: zero MEMORY reads
on a bound unit-evidence settlement; zero legacy; no nutrition write before
quantity authority exists; held snapshot survives the clarification; another
user cannot consume the relationship or held ASK; an old ASK cannot bind a
newer scan; duplicate confirmation creates one row; failed settlement does
not consume the held ASK; successful settlement consumes it exactly once;
committed row retains the exact `product_evidence_id` and unit-evidence
provenance.

**User experience.** Keep it short. Preferred: "The label gives nutrition per
30 g. How many pieces does it list per serving?" · image needing
confirmation: "The label appears to say 3 pieces equal 30 g. Is that
correct?" · noun differs: "By one Twizzler, do you mean one individual
strand?" · evidence unavailable: "I can log it accurately in grams or
servings, but the product record doesn't say how much one piece weighs." Do
not expose internal terms (BoundUnpriceable, rung, snapshot, authority).

**Closure criteria — P17-UE closes only when:** (1) explicit count-plus-mass
serving text settles deterministically · (2) real incomplete records remain
negative · (3) label-image extraction is provenance-backed and cannot
authorize unsupported values · (4) user clarification retains the exact
product snapshot · (5) natural product nouns cannot manufacture physical-unit
equivalence · (6) replay, isolation and conflict proofs are green · (7)
SQLite and live Postgres suites are green · (8) a production canary commits
a bound packaged-food row using an explicit physical-unit relationship ·
(9) the committed row points to the exact product snapshot and unit-evidence
source · (10) no heuristic unit conversion, MEMORY read or legacy execution
occurs. **Do not change the 40% ownership gate or reinterpret the frozen P17
remeasure after seeing P17-UE results.**

### PRODUCT CAPABILITY PLACEMENT — NOT EXECUTABLE SEQUENCING

This subsection says **where the final product behavior belongs**. It does not
override §NEXT's measured order.

#### Single-item PRODUCT_VARIANT binding — required before B-2

The canonical vocabulary already contains `ClarificationAttribute.PRODUCT_VARIANT`
and the typed patch `SelectProductVariant(entity_id, serving_id)`. The capability
is **not complete merely because those types exist**: the nutrition semantic-field
registry must actually register/produce PRODUCT_VARIANT and generated options
must come from attributable structured product candidates.

Target flow:

```text
"Barebells bar"
      ↓
canonical product family / unresolved variant
      ↓
structured candidate set for THIS event
      ↓
is the nutritional/semantic difference material enough to ask?
      ↓
YES -> PRODUCT_VARIANT clarification
      ↓
user selects/confirms
      ↓
SelectProductVariant(stable id)
      ↓
exact PRODUCT evidence may price
```

Flavor is only one variant dimension. The same field may distinguish:
`flavor · formulation · product line · format · fat level · package/size`
when those are genuinely different catalog products.

Memory may rank or shorten the question:

```text
"Salty Peanut like usual, or a different one?"
```

but history may never silently turn `"Barebells bar"` into Salty Peanut.
A prior reduces friction; it does not manufacture a user statement or exact
PRODUCT authority.

#### B-1.8 — corrections across the same typed fields

Repair must support changing quantity, serving, identity and product variant.
A correction targets the canonical event and replaces/recomputes the affected
typed field using persisted evidence. It does not route the canonical row back
through legacy mutation.

#### B-2 — multi-food composition

Only after the single-item fields are production-proven:

```text
"Barebells bar and a Fairlife shake"
      ↓
event A: PRODUCT_VARIANT unresolved
event B: PRODUCT_VARIANT unresolved
      ↓
two independent candidate sets
      ↓
one operation / event-bound ClarificationGroups
```

Candidate sets, options and patches may never cross event boundaries. B-2
**composes** single-item semantics; it must not invent a multi-food resolver.

#### C — conversation / one voice

C owns how the structured unresolved state is spoken/rendered:

```text
"Which ones — Salty Peanut or Caramel Cashew for the Barebells,
and regular Core Power or Elite for the Fairlife?"
```

C does not decide what is unresolved, which candidate is authoritative, or what
nutrition to use. Conversation is presentation over typed state.

#### D — personalization / memory

D uses history to rank likely answers, shorten questions and reduce
clarifications-per-meal. It never turns an unstated variant/preparation/amount
into settled fact merely because it is common for the user.

#### E / F — intelligence and agency

E coaches from settled canonical events and provenance. F decides when to act or
stay silent. Neither may participate in canonical nutrition authority.

### P17 CANARY / USER-SIDE EXPECTATION

Before P17g, the user should see essentially no behavior change: the artifact
is intentionally dark and unchanged.

After P17 is complete, the expected user-side improvement is **less friction,
not more UI**:
- ordinary count foods resolve more often on the first message
- fewer unnecessary quantity questions
- fewer estimate/fallback paths
- exact branded products use their label basis deterministically
- incorrect/mismatched unit evidence still refuses

Live proof stays on user 26 until the rollout gate moves. A canary must include
successful cases **and refusals**, and it must prove the new mechanism executed;
"no behavior changed" with zero P17 resolutions is a failed instrument, not a
safe result.

### ⛔ THE ROLLOUT THRESHOLD — PREDETERMINED, SO "COVERAGE DECISION" STOPS BEING SUBJECTIVE

The directive said cohort expansion was prohibited pending a coverage decision
and never said what number permits it, which makes the decision re-arguable every
time the number moves.

```text
OWNERSHIP        COHORT PERMITTED
< 40%            user 26 only        <- WE ARE HERE, baseline ~20.3%
40 – 55%         controlled 1–5%
55 – 70%         controlled 10–25%
70% +            consider broad canonical promotion
```

⛔⛔ **THE NUMBER IS NECESSARY, NOT SUFFICIENT. B-1.8 GATES EVERY BAND IN THIS
TABLE.** *(Danny, 2026-08-17)* Correction — "actually that was 8 oz" — still
fails on a canonical meal, because the ownership firewall correctly refuses to
let the old correction system write canonical rows. Crossing 40% with that open
would ship a broken everyday action to 1–5% of the fleet, **and the firewall
breaks correction on precisely the meals the coverage track just won** — so the
defect's blast radius is proportional to the coverage work succeeding.

```text
ownership >= band   ->  Arnie is coverage-ELIGIBLE for that cohort
B-1.8 CLOSED        ->  Arnie is READY for it
expansion            =  BOTH, never either
```

Eligible is not ready. This is a gate, not a preference, and it is the reason
the board carries two clocks instead of one.

⚠ **THESE PERCENTAGES ARE A PRODUCT AND RISK DECISION, NOT A MEASUREMENT.** They
were set by Danny on 2026-08-17 review and nothing in this repository derives
them. They are binding until he changes them, and the point is that they were
fixed BEFORE the number moved. Changing them is allowed; changing them in the
same breath as reporting a new ownership number is not.

⭐ **REVIEWED AND RETAINED ON 2026-08-17, AND THE REASONING IS RECORDED SO IT IS
NOT RE-LITIGATED EACH TIME THE NUMBER DISAPPOINTS.** The bands entered at
`cd2b74a`, one commit before `8443cb0` published 20.2% — so they were indeed
calibrated while 36.9% was operative, and the gap to the first band widened from
3.1 points to 19.8 overnight. Two different arguments follow from that, and only
one of them is legitimate:

```text
DISTANCE  "40% is far away now, so lower it"        <- this is goalpost-moving,
                                                       and the rule above bars it
ANCHOR    "the bands were calibrated against a      <- legitimate: a units
           figure the predicate cannot produce"        problem, not an ambition
                                                       one
```

The anchor argument is real and is NOT resolved here. It is deferred to a
separate, dated decision requiring **at least two measurements on the current
predicate — the P16b frozen-population baseline and a post-P17 reading** — so
that any recalibration is made against two points on one scale rather than under
a single disappointing number. **40% stands until then.**

⭐ **THE NUMBER TO RUN THE PROGRAM ON IS 20.2% OWNERSHIP** — not the superseded
36.9%, not the older 44–46% coverage figures, and not the flattering 24.3%
support rate. Ownership is
routing × support, and it is the only one of the three that describes the
product.

### ✅ P16 — MISS ATTRIBUTION, MEASURED *(2026-08-17, `scripts.measure_settlement_coverage --days 21`)*

**RUN, not planned.** 207 declining items across the declining structured meals,
each classified into exactly one mechanism, first match wins:

```text
MECHANISM                                            COUNT   non-latin   example
TYPED:count_only_quantity                              142      67       Seaweed Salad
IDENTITY:no_resolution_row                              48       4       Salmon, pan-cooked with oil
CACHEABILITY:memory_quarantined_ambiguous_address        7       0       ground turkey
BRANDED:product_recognised_but_non_binding               7       0       Barebells Salty Peanut Protein Bar
IDENTITY:distinct_refused_a_false_collapse               3       3       Сметана 5%
```

⛔⛔ **THE DOMINANT MECHANISM IS COUNT-ONLY QUANTITY — 142 of 207, 69%.** Not
non-English, not branded, not the oils. This is the **PRODUCT rung**:
`assemble()` hard-codes it to `None`, so there is no per-serving basis at all and
any count-only portion is unpriceable by construction. The frozen roadmap's step
4 guessed *"expected: PRODUCT"*; the measurement now says it outright, by a
factor of three over anything else.

⭐⭐⭐ **AND THE LANGUAGE CROSS-TAB IS WHY THIS AXIS WAS THE RIGHT ONE.** 67 of the
142 count-only items are non-Latin. A tranche named "non-English support" would
have *appeared* to fix a large share while the actual defect is a missing serving
basis, which is language-neutral — the wrong layer, chosen by a correlation.
Meanwhile:

```text
Сметана 5%   -> IDENTITY:distinct_refused_a_false_collapse   a DELIBERATE refusal
ground turkey-> CACHEABILITY:memory_quarantined_ambiguous_address   only 7 items
```

The sour-cream row is not a coverage miss at all; `DISTINCT` is the system
declining to collapse two foods, working as designed. And cacheability — the
mechanism the review expected to lead — is **7 items**, not the tranche.

⚠ **TWO LIMITS, BOTH LOAD-BEARING BEFORE ANYTHING IS SEQUENCED ON THIS.**
`IDENTITY:no_resolution_row` (48) partly reflects the instrument's own stated
limit: `food_entries` carries no `canonical_entity_id`, so the predicate is asked
with an EMPTY identity — this is coverage without identity stamping, which is what
the fleet has today but not what a stamped turn would see. And these are declining
**items** while ownership is a **meal** rate, so recoverable ownership POINTS per
mechanism still needs the meal-level rollup before the ranking is final.

**The ranking to act on, subject to that rollup:** PRODUCT / per-serving basis
first by a wide margin, then identity-resolution coverage. Rank by
`recoverable ownership points × confidence × implementation risk`, never by
feature name — feature names are user-input categories, and sequencing by them is
how the oils came to look next.

The instrument was EXTENDED, not duplicated: attribution runs inside
`measure()`'s own session, over the meals it already grouped and the verdicts it
already computed, so P11 and P16 cannot disagree about the population. Recorded
to `data/corpus/settlement_coverage.json`.

⛔ **THE OLDER 30.4 / 9.8 / 7.7 / 5.6 TAXONOMY DOES NOT DICTATE ENGINEERING.** It
is a 691-entry, ENTRY-LEVEL identity analysis from 2026-08-14, and this
measurement supersedes it for sequencing.

## ⏭⏭⏭ THE FROZEN ROADMAP — MEASURED-ADOPTION ORDER *(Danny, 2026-08-14. SUPERSEDED FOR SEQUENCING BY THE CORRECTION ABOVE; the content below remains the plan of record for steps 2 onward.)*

> **We are no longer building B in SPECIFICATION order. We are building it in
> MEASURED-ADOPTION order.** The spine is good. Now we make sure real user
> behaviour actually reaches it before we keep widening what the spine can
> theoretically do.

**THE IMMEDIATE GOAL IS NO LONGER "FINISH THE FIVE OILS."** It is: get ordinary
real food turns onto the canonical spine reliably, then expand what that spine
can do.

```text
 1  INTERPRETATION BOUNDARY          (was P0-next; CLOSED — see §NEXT)
 2  general canonical settlement owner
 3  RE-MEASURE real coverage         <- decides step 4; do not skip to features
 4  next largest measured gap        (expected: PRODUCT/branded rung)
 5  B-1.7a  added-fat identity       (the oils — now that turns can consume them)
 6  B-1.7b  materiality / ask policy
 7  B-1.7c  composition
 8  B-1.8   correction / repair
 9  B-2     messy real food
10  PROMOTE canonical · DELETE legacy    -> one food system
11  C  conversation / one voice      (users cannot tell which lane ran)
12  D  personalization / memory      (metric: clarifications per meal FALLS)
13  E  coaching intelligence         (what happened -> means -> matters next)
14  F  proactive agency              (knowing when to SPEAK and when to STAY SILENT)
```

**WHY THE OILS MOVED.** Measured 2026-08-14 on 691 real production entries: the
artifact is the DECIDING rung on **13 of them — 1.9%**. Only the 5.6%
"bare + uncovered" bucket is what adding artifact identities fixes, and the
oils live in it. Landing all five moves real coverage under one point. See
§3a.2 for the full breakdown and the instrument's honest limits.

### 0 — ⛔ FROZEN RULE: NO PHASE BLOCKS ON ORGANIC TRAFFIC *(Danny, 2026-08-15)*

> **No phase may block on organic traffic VOLUME if the required evidence can be
> reproduced from HISTORICAL traffic or a PREREGISTERED corpus. Live traffic is
> required only for canary proof of ROUTING, PERSISTENCE, LATENCY, PROVENANCE
> and ROLLBACK behaviour.**

⭐ **THE SPLIT THIS FREEZES.** Use historical production data + synthetic replay
for COVERAGE and CORRECTNESS. Use live production only to prove DEPLOYMENT
behaviour and catch environment-only defects. Production traffic is for CANARY
VALIDATION, not for discovering the next architecture step.

⚠ **AND IT RETIRES A REAL BLOCKER I RAISED.** The interpretation boundary was
sitting behind "the store is empty, so no rerun can show what it is worth" —
which is exactly the shape this rule forbids. The corpus is built from the
measured distributions, not waited for.

**THE CONTROLLED EVIDENCE PROGRAM:**

```text
 1  exact-head CI on main                                    ← owner: Danny
 2  deploy the interpretation boundary DARK (mode=off)        ← owner: Danny
 3  synthetic production-like corpus through the REAL turn path:
      multilingual · branded · modifier-heavy · bare uncovered
      known collisions · egg/mackerel materiality · quantity+preparation variants
 4  WEIGHT that corpus by the ALREADY-MEASURED production distributions
      (NON-ENGLISH 30.4% · BRANDED 9.8% · QUALIFIED 7.7% · BARE 5.6%)
      so it approximates traffic rather than being a toy fixture set
 5  ENTITY_RESOLUTION_MODE=shadow for CANARY USERS ONLY — prove:
      resolution writes · NO turn behaviour change · no false collapse
      no PRODUCT binding · latency acceptable
 6  promote consumption for the CANARY COHORT, without waiting for volume
 7  re-run the 30-day historical corpus through the now-real consumer path:
      MEMORY · ARTIFACT · PRODUCT · REFUSE/ESTIMATE
      false-collapse rate · unresolved rate · p50/p95 latency
 8  -> GENERAL CANONICAL SETTLEMENT OWNER          ← the next substantive build
 9  canary that slice
10  next largest measured gap (expected PRODUCT)
11  oils / B-1.7a
12  B-1.7b -> 1.7c -> B-1.8 -> B-2 -> promote/delete legacy -> C/D/E/F
```

**NOT MORE PHASE-0-STYLE ARCHAEOLOGY** unless a gate exposes a real defect.

#### 0a — STEP 3 STATUS: BUILT AND VERIFIED OFFLINE · THE RUN IS BLOCKED *(2026-08-15)*

```text
data/corpus/production_like_v1.json          preregistered, committed
scripts/corpus_through_the_real_turn.py      drives run_chat_turn, committed
--validate                                   PASSES: no model, no DB, no network
the actual run                               ⛔ BLOCKED — API credit balance
```

**`--validate` passes at 100/100**: every label agrees with PRODUCTION'S OWN
classifier (`_looks_branded`, the non-ASCII test), no duplicate utterances, and
every bucket within **1.3 points** of the measured mix. ⛔ **No coverage number
is claimed yet** — the last run made 543 calls and every one was rejected.

⭐ **THREE FIDELITY DEFECTS THE RUNS FOUND, AND THEY GENERALISE TO ANY
SYNTHETIC CORPUS THIS PROJECT BUILDS:**

1. ⛔⛔ **A ONE-DAY CORPUS CANNOT REPRODUCE A THIRTY-DAY MEMORY RATE, BY
   CONSTRUCTION.** 100 turns wrote 45 rows; 39 of 44 memory-declared entries
   produced none; every miss was a REPEAT and nothing was mis-parsed. The 43.7%
   is earned ACROSS DAYS, and the dedup guard is scoped to TODAY's log — it
   exists to stop exactly the shape compression creates. The corpus now runs as
   simulated days, re-dating each finished log: dedup resets, memory persists.
   ⚠ Via the DAY, never `core.clock` — the one-clock migration exists to stop
   code inventing its own time.
2. ⛔⛔ **A BARE MENTION DOES NOT LOG, IT ASKS** — conversationally, NOT through
   the structured pending path, so the log carries no clarification signal at
   all. And asks ACCUMULATE: one unanswered question silently truncates every
   later turn for that user. Portions moved into the body; the ask/answer loop
   moved to probe P8, where it is the subject rather than a confound.
3. ⛔ **ROWS ARE NOT ATTRIBUTED TO THE TURN THAT WAS RUNNING.** Held food rides
   `deferred_calls` and commits on the FOLLOWING turn. Reconciliation is by food
   and user, in order — never by turn index.

⭐⭐ **AND ONE CORRECTION TO AN EXISTING INSTRUMENT — `measure_identity_coverage`
HAS NO TEMPORAL GUARD.** It asks `_memory()` about 30-day-old entries, long
after each turn cached its own candidate, so **43.7% means "addressable today",
not "priced from memory at settle time"**. The corpus reports BOTH, and its
drift check uses the comparable one. Comparing a settle-time number to 43.7%
would be the §1e two-populations error a second time.

⚠ **UNVERIFIED, AND THE SHADOW RUN IS WHAT SETTLES IT.** Read from the call
graph, not yet from a run: `stamp_canonical_identity` — the boundary's ONLY
producer — is called from one site, `FoodPlanStage.run`, reachable only under
`TURN_COORDINATOR_MODE=new_execute`, or `new_observe` **with**
`TURN_COORDINATOR_OBSERVE_DEEP=1`. Production's default is `MODE_LEGACY_ONLY`,
where `observing()` is False. **If that holds, a shadow canary writes ZERO
resolutions and reports as "no behaviour change" — the most reassuring possible
result, produced by the feature never running.** The corpus's
`shadow_actually_resolved_something` check exists for precisely this, and
`--compare` refuses to interpret a zero-resolution shadow run in either
direction. ⛔ **Do not start step 5 on the strength of a quiet canary.**

✅ **CLOSED — see §0b above.** The seam landed in `54d91bd`; a real turn now
writes resolutions, and `shadow_actually_resolved_something` is a live check
rather than a hypothetical one.

#### 0z — ✅ INTERPRETATION ADOPTION IS CLOSED — ADDRESSING, NOT COVERAGE *(re-closed 2026-08-16, SCOPED)*

> **THIS SECTION HAS BEEN WRONG IN BOTH DIRECTIONS, AND THE HISTORY IS THE
> POINT.** It read *"ADOPTION IS CLOSED"* on 08-15 while publishing a corpus mix
> computed over mis-attributed rows. P0 retracted the whole section on 08-16.
> P1 then showed the retraction was **too wide**: the evidence step 5 actually
> owed is structurally independent of the broken instrument.
>
> ⭐ **THE CHECK THAT SETTLED IT.** `_resolution_quality` — the function whose
> docstring names *"THE FIVE THINGS STEP 5 MUST MEASURE"* — takes
> `(resolutions, observations, body)` and **never references `observations`**.
> Every step-5 number comes from the RESOLUTION STORE and the DRIVEN CORPUS.
> Neither passes through `_reconcile`. The attribution defect destroyed the
> MIX — which rung real food reaches, per-population cacheability, drift — and
> **the mix was never the adoption gate.** It is the coverage question, and
> coverage is open below.
>
> **So what is closed is ADDRESSING, and it is closed on production evidence.**

**The frozen §0 sequence, with each claim's instrument named:**

```text
1  record ask/pending foods at stage time    ✅ 82efb5a · proven telegram:9345
2  gates + dual-engine                       ✅ SQLite 9152/0 · PG 9218/0
3  resolver truncation reliability           ✅ bf4b8ba · Russian single resolves
4  real-model proof, non-English singles     ✅ 4/4 claims
5  weighted corpus in shadow                 ✅ STORE-SIDE ONLY — 46 identities,
                                                0 false collapses, 5 PRODUCT
                                                rows binding nothing, 19/19
                                                non-English resolved. Read from
                                                FoodEntityResolution and
                                                entity_id_for_surface, never
                                                from the reconciler.
                                             ⛔ the MIX from that same run is
                                                WITHDRAWN — see §0c.
6  consume canary, cohort of one             ✅ c8482c1 · proven telegram:9362/9365
7  B-1 prices + provenance watched           ✅ correct, incl. one rung=memory
8  close interpretation adoption             ✅ THIS SECTION, SCOPED
```

⛔⛔ **WHAT IS *NOT* CLOSED, AND MUST NOT BE READ INTO THE ABOVE.**

```text
ADDRESSABILITY   closed   the key names the food; the rung is consulted
CACHEABILITY     OPEN     nothing seats a candidate, so the correct key
                          addresses nothing — and its PREVALENCE IS UNKNOWN
COVERAGE / MIX   OPEN     unmeasured since 08-16; P2 owes the number
```

⛔ **AND THE COHORT STAYS FROZEN.** `ENTITY_RESOLUTION_CONSUME_ALLOWLIST=26`
does not move. **Widening is a COVERAGE decision, not an adoption one** — the
blast radius of consumption is mispricing, and the instrument that would size
that risk is exactly the one whose numbers were withdrawn. Adoption being
closed is not a reason to widen; a measured miss rate is. **Expansion stays
prohibited until P2 publishes one.**

⭐ **THE BEFORE/AFTER, ON THE FOOD THAT FAILED ALL DAY.** `Сметана 5%`:

```text
before   memory_key_refused key='5'          the rung was never even consulted
         canonical_priced rung=estimate
after    entity_identity_consumed stamped=1  key = 'smetana 5percent'
         pricing.memory: 4ms                 the rung RAN and returned nothing
         canonical_priced rung=estimate      price unchanged: 80 kcal/100g
```

⭐⭐ **AND THE CAVEAT IS THE MOST USEFUL PART. CONSUMPTION MADE THE KEY
ADDRESSABLE; IT DID NOT MAKE THE ROW EXIST.** `evidence_qualified raw=8 kept=0
dispositions={'DIFFERENT_IDENTITY': 8}` — nothing seats a candidate for Russian
sour cream, so nothing caches, so the correct key still addresses nothing. The
identity boundary fixes ADDRESSING. **Cacheability is a different defect with a
different owner**, and it now stands between the non-English population and a
memory hit.

⛔ **ITS PREVALENCE IS UNKNOWN AND MUST NOT BE STATED.** This paragraph carried
*"2 of 22 QUALIFIED foods ever cached, 2 of 27 non-English"* until 2026-08-16.
Both ratios were reconciliation-derived and are **withdrawn**. The phenomenon
above stands on the live `Сметана 5%` turn alone, which is enough to name it and
not enough to size it. Do not write it as a rate, a fraction, or a population
share until P2 republishes one.

**WHAT IS PROVEN** — none of it reconciliation-derived

```text
producer reachable from ordinary turns   seam 1 (log) · 2 (tool batch) · 3 (ask)
shadow is annotation-only                0 identity-keyed rows across 836 (prod DB)
consume is scoped by its own cohort      coordinator rollout cannot widen it
resolver does not truncate               Russian singles resolve
no false collapse                        46 identities, 0 merges (resolution store)
PRODUCT binds nothing                    5 rows, 0 binding (consumer-side read)
61eec60 memory rung                      live, decided a correct B-1 price
```

⚠ **THE LAST THREE ARE STORE-SIDE READS, WHICH IS WHY THEY SURVIVED.** They come
from `FoodEntityResolution` and `entity_id_for_surface`, never from `_reconcile`.
Anything in the same run that joined a written ROW to a corpus ITEM did not
survive — see the invalidation list in the defect record.

**WHAT REMAINS, NAMED RATHER THAN LEFT**

1. ⛔ **The B-1 ASK path does not consume.** A food staged into a pending
   operation settles via `assemble()` from the staged item, not from a tool
   call, so the tool-input stamp never reaches it. A bare `Сметана 5%` still
   refuses the key. Scoped, not surprising, not started.
2. ⚠ **Seam 2 is unproven on fleet traffic.** `structured_food_executes_
   natively` is `{allowlisted_user: true, fleet: false}` and user 26 is the
   allowlist, so the fleet's door has unit and mutation proof only. One
   non-allowlisted shadow canary closes it.
3. ⚠ **Entity-id form is unstable across calls** — `kefir 1percent`,
   `ground turkey 96 percent lean`, `ground turkey 94 lean`. Stable per
   surface, so harmless today. One measured cross-language duplicate:
   `Листья салата` → `lettuce leaves` vs `Lettuce leaves` → `lettuce`.
4. ⛔ **Canonical rows cannot be corrected** through the ordinary
   interpretation path — carried to B-1.8 (§6), firewall not to be reopened.

**NEXT: P1 — repair corpus correlation.** *(This line read "NEXT: general
canonical settlement owner, A1–A10" until 2026-08-16.)* A1–A10 may be PLANNED;
**implementation is blocked until P2–P4 complete**, and §3a.2 carries two
blocking contract ambiguities that are not yet resolved.

#### 0b — ✅ CLOSED BY THE ADOPTION SEAM `54d91bd` *(2026-08-15)*

**FIXED. The producer is now on the path ordinary food traffic takes**, and the
sequence Danny froze from this state is:

```text
wire identity producer into ordinary turn path   ✅ 54d91bd
local / dual-engine gates                        ✅ SQLite 9098/0 · PG 9181/0
shadow real-turn corpus                          (was next; P2, off the critical path)
canary shadow -> canary consumption -> replay/re-measure
general canonical settlement owner -> settlement canary -> oils
```

⭐ **THE SEAM HAS TWO DOORS, AND THE SECOND CARRIES MOST OF THE TRAFFIC.** Wired
to the structured interpreter's output alone it covered **one food turn in
four**: three of four ordinary food turns emit `entity_identity_skipped
reason=no_interpretation`, because the structured lane declines and the food is
logged from the legacy tool batch where no interpreter `items` dict exists. The
store went **0 rows → 1 (seam 1) → 4 (both)**.

⭐⭐ **`record_identities` PERSISTS AND ANNOTATES NOTHING.** The stamp travels
through `_log_call` into `_analyze_food`, where `memory_key(food, entity)`
addresses a different memory row and so changes the PRICE. Recording is shadow;
stamping is consumption, and consumption keeps its own canary.

⚠ **AND THE MUTATION GATE'S FIRST VERSION WAS HOLLOW** — it substring-scanned
for `observing(` and the mutation defeated it with an aliased import. The gate
now states the property structurally and names no flag: *the recorder may not
sit inside any conditional the interpreter is not*. **Below is the original
finding, kept because the shape recurs.**

#### 0b(i) — ⛔⛔⛔ THE PRODUCER WAS NOT REACHABLE FROM AN ORDINARY FOOD TURN *(2026-08-15, MEASURED)*

**THIS BLOCKED STEP 5, AND IT WAS THE SESSION'S HEADLINE.** Two runs, same scratch
database, same `ENTITY_RESOLUTION_MODE=shadow`, minutes apart:

```text
stamp_canonical_identity CALLED DIRECTLY      4 resolutions written
  (scripts.prove_memory_addressing)           Помидор -> tomato · творог != corn
                                              Barebells -> PRODUCT, entity EMPTY

the SAME foods through run_chat_turn          4 food rows written
  (scripts.corpus_through_the_real_turn)      0 resolutions written
```

⭐ **THE PRODUCER WORKS. THE ORDINARY TURN PATH NEVER REACHES IT.**
`stamp_canonical_identity` has ONE call site — `FoodPlanStage.run` — reachable
only under `TURN_COORDINATOR_MODE=new_execute`, or `new_observe` **with**
`TURN_COORDINATOR_OBSERVE_DEEP=1`. Production's default is `MODE_LEGACY_ONLY`,
where `observing()` is False and no stage runs at all.

⛔⛔ **SO A SHADOW CANARY WOULD HAVE REPORTED "NO BEHAVIOUR CHANGE" — THE
STRONGEST POSSIBLE RESULT — PRODUCED BY THE FEATURE NEVER RUNNING.** §0 step 5
asks the canary to prove "resolution writes · NO turn behaviour change"; the
second half would have passed for the worst reason, and the first half is what
catches it. ⚠ **Do not start step 5 until the producer is on the path an
ordinary turn takes.** The next substantive engineering step is wiring it there
— a CODE change, no traffic and no API spend required to decide it.

⭐⭐ **AND NOTE THE SHAPE: THIS IS "A PROVEN CAPABILITY IS NOT AN ADOPTED ONE"
FOR THE THIRD TIME.** `prove_distinct_reuse` and `prove_memory_addressing` are
both TRUE and both call one level below the turn. Every gate over the producer
passes. Nothing asked whether a turn reaches it.

#### 0c — ⛔ WITHDRAWN: WHAT THE OFF RUN "MEASURED" *(invalidated 2026-08-16)*

> **EVERY NUMBER THIS SECTION PUBLISHED WAS RECONCILIATION-DERIVED AND IS
> WITHDRAWN.** `run_off.json` shares the broken attribution instrument: **26 of
> its 27 attributed `ru` rows name a different food than the one that produced
> them.** The drift table, the per-population cacheability ratios, and the
> branded-prediction verdict all depended on joining a written row to its corpus
> item. See [CORPUS_ATTRIBUTION_DEFECT_0816.md](CORPUS_ATTRIBUTION_DEFECT_0816.md).
>
> **What survives from this run:** 100 turns · 81 entries · 0 turn failures ·
> 0 recovery bubbles · p50 6.0 s · p95 9.6 s. Those are per-turn measurements
> and never pass through the reconciler.
>
> **The original text is kept below, struck**, because the shape of the error —
> a run that reported a confident, well-formed, internally consistent mix over
> mis-attributed rows — is the thing worth remembering.

~~Drift on the comparable basis:~~

```text
WITHDRAWN — reconciliation-derived
NON-ENGLISH   29.6%  vs 31.3%   -1.7
BARE          8.6%   vs  5.7%   +2.9
ARTIFACT      0.0%   vs  1.9%   -1.9
MEMORY        34.6%  vs 43.7%   -9.1
QUALIFIED     27.2%  vs  7.6%  +19.6
BRANDED       0.0%   vs  9.9%   -9.9
```

~~⭐ **THE LAST THREE HAVE ONE CAUSE, AND IT IS A REAL FINDING ABOUT THE SYSTEM,
NOT A CORPUS DEFECT.** Which populations ever reach a cached row:~~

```text
WITHDRAWN — reconciliation-derived
en-staples  16 of 24
branded      8 of  8
qualified    2 of 22
ru           2 of 27
```

⚠ **THE HYPOTHESIS SURVIVES THE NUMBERS; DO NOT LET IT SMUGGLE THEM BACK IN.**
That modifier-heavy and non-English names may be **uncacheable rather than
merely uncovered** — retrieval cannot seat "Spicy White Tuna Poke Bowl, heavy
sauce", so nothing is written to memory and the food misses on every log — is
consistent with the live `Сметана 5%` turn (`evidence_qualified raw=8 kept=0`,
`DIFFERENT_IDENTITY: 8`), which is independent of the corpus. **It is a named
mechanism with no measured prevalence.** P2 owes the size of it.

⚠ **THE BRANDED PREDICTION IS NEITHER CONFIRMED NOR FALSIFIED.** The claim that
all 8 branded entries cached — and therefore that production's BRANDED miss
might be ENVIRONMENTAL — rests on the same attribution. **Do not build the
PRODUCT rung on it, and do not discard the environmental hypothesis either.**
Re-ask it in P2.

**OWED BY DANNY:** API credits for the shadow corpus run — ⛔ **but NOT until P1
lands** *(2026-08-16)*. The seam is reachable and a run will measure something;
with the reconciler as it stands, what it measures is mis-attributed. Spending
the budget before the repair buys 120 real turns of the same defect.
⚠ **Also owed:** exact-head CI, deploy dark, then `ENTITY_RESOLUTION_MODE=shadow`
for a canary cohort — watching **B-1 settlement PRICES**, not only resolution
writes, because `61eec60` is a live behaviour change on deploy.

⭐ **AND ONE STANDING RULE FROM THIS SESSION** *(Danny, 2026-08-15)*: **do not
spend 120-turn runs on architectural reachability questions.** Use 4-12
preregistered turns to prove the seam, then spend larger corpus budget only
after the seam is proven reachable. The 120-turn shadow body queued before this
finding would have measured a feature that never ran.

### 1 — INTERPRETATION-DERIVED IDENTITY — ⚠ BUILT END TO END, SHIPS DARK *(status 2026-08-15)*

```text
02ab6eb   HEAD · SQLite 9090/0 · Postgres 9172/0
fac8f97   containment — a memory key must name a food      DEPLOYED, LIVE
44f137f   substrate: 3 states + migration entres001        pushed
05a5166   producer: interpreted meaning, once              pushed
d24868a   DISTINCT reuse + PRODUCT separation              pushed
ee7457f   live reuse proof 4/4                             pushed
d3a4fc2   credential boundary gate                         pushed
02d87b3   wired at interpretation — ENTITY_RESOLUTION_MODE=off
1f13347   identity keys durable memory                     pushed
61eec60   P0 memory-rung repair + remeasure                pushed
02ab6eb   measurement loop closed apples-to-apples         pushed
```

**ONLY `fac8f97` IS CURRENTLY DEPLOYED.** The interpretation-resolution FEATURE
is dark: `ENTITY_RESOLUTION_MODE` defaults `off`, so nothing is stamped and
nothing is consumed.

⚠⚠ **AN EARLIER DRAFT SAID "ONLY `fac8f97` CHANGES PRODUCTION BEHAVIOUR" AND
THAT IS TOO BROAD** *(Danny, 2026-08-15)*. It is true of what is DEPLOYED. It is
false of the TRANCHE. `61eec60` repairs `_memory()` in
`core/canonical_pricing_inputs.py`; `assemble()` is its only route to
production and has exactly one caller — `core/b1_quantity_operation.py:1486`,
the LIVE B-1 quantity clarification path. The rung returned None for 836 of 836
rows and now returns evidence, so a B-1 settlement can price from a user memory
row where it previously fell through to artifact-or-estimate — **with the mode
flag off and nothing resolved.**

⭐ **THE DISTINCTION IS DEPLOYED-vs-BEHAVIOURAL, AND IT GENERALISES.** A feature
flag gates the feature it was written for. It does not gate a defect repair that
happened to travel in the same tranche, and "ten of eleven commits are inert" is
the kind of summary that hides exactly one live change in a rounding. The dark
deploy makes ten commits free; it does not make `61eec60` free. **Canary
B-1 settlement PRICES, not only resolution writes.**

**OWED, BOTH OUTSIDE THIS SESSION'S REACH:**
1. **exact-head CI** on `05a5166` → the tranche tip (`gh` unavailable here)
2. **the dark deploy**, then `ENTITY_RESOLUTION_MODE=shadow` for a canary cohort

⛔ **WHAT IS *NOT* OWED ANY MORE: WAITING.** An earlier draft of this section
listed a third debt — *"the resolution store is EMPTY, so until real traffic
fills it no rerun can show what the boundary is worth."* **§0 retires exactly
that.** Today's 43.7% is still the honest caption (the REPAIRED RUNG ON TODAY'S
KEYS, no identity ever passed in production), but the remeasure does not wait on
organic volume: the corpus is BUILT from the measured distributions and driven
through the real turn path. Live traffic owes routing, persistence, latency,
provenance and rollback — never coverage.

**THEN, IN §0's ORDER — 3 through 7 BEFORE 8:** weighted corpus through the real
turn path → canary shadow → canary consumption → historical replay through the
now-real consumer path → general canonical settlement owner → PRODUCT rung →
oils last.

### 1 — THE ORIGINAL BRIEF

> **THE INVARIANT: surface language is for DISPLAY and AUDIT. Canonical
> identity comes from INTERPRETED FOOD MEANING.**

Target cases: non-English foods · modifiers like `white rice` · cooked/steamed
wording · synonymous forms · **foods where a literal translation would be
wrong**.

```text
EXIT  rerun the 691-entry coverage instrument
      materially reduce the 30.4% non-English / modifier miss bucket
      NO evidence that normalization collapses distinct foods incorrectly
```

⚠ That third line is the one that can fail silently, and it is the reason this
cannot be a translation table: `творог` is not "cottage cheese", and the
interpreter prompt ALREADY warns that renaming a food can change which grade is
the default. The prompt is right. The defect is that identity is built from the
surface string at all.

### 1b — ⭐ THE PRODUCER, MEASURED LIVE — AND WHAT IT CHANGED *(2026-08-14)*

36 real production non-English foods through the real resolver:

```text
31 resolved · 5 distinct · 0 unresolved
```

⭐ **GATE 3 HOLDS WITHOUT BEING ASKED TO.** `Творог -> tvorog` and
`Сметана -> smetana`, both DISTINCT, both with reasons naming why the English
approximation would change the food. творог did not become cottage cheese and
сметана did not become sour cream — with no list, no catalogue, and no
food-specific instruction.

⛔ **BUT ONLY 1 OF 31 RESOLVED ENTITIES REACHES THE ARTIFACT.**

```text
HIT   Банан   -> banana
miss  Помидор -> tomato      Огурец -> cucumber      Авокадо -> avocado
miss  Кефир   -> kefir       Индейка -> turkey       Клубника -> strawberry
```

The translations are right; the artifact holds 27 entries and none of these are
in it. **SO THE BOUNDARY DOES NOT MOVE THE ARTIFACT RUNG.** Its payoff is making
these foods ADDRESSABLE AT ALL — which principally means the MEMORY rung, where
44.6% of production already lives and where §1a's containment currently makes
every one of them non-addressable. A unit-gates-only reading would have reported
this backwards.

✅ **CLOSED 1 — DISTINCT ID STABILITY** *(2026-08-14, split into two halves
because they are different kinds of problem)*. **Typography** is settled
deterministically by `normalize_entity_id`, run inside `record()` rather than by
the producer, so every writer — model, human, backfill — lands on one spelling
and two rows cannot disagree purely typographically (`%` survives as the word it
means; dropping it would merge 2% and 5% curd). **Semantics** is settled by
asking whether a new DISTINCT food IS one of the already-stored distinct
identities — ⭐ a GROWING STORE, NOT A CATALOGUE: every candidate got there by
being resolved once, so the question is "is this one of the identities we have
met" rather than "pick from these blessed foods". The prompt is biased AGAINST
merging, because a wrong merge is permanent and prices one food from another
while a redundant identity is merely untidy. Reuse may only name an id that
already exists. Cost: one extra call per genuinely-new distinct food, none
thereafter, none for the first ever.

✅ **CLOSED 2 — PRODUCT SEPARATED FROM DISTINCT.** `ResolutionState.PRODUCT` is
in `MAY_NAME_AN_ENTITY` but **not** in `BINDING`, so a branded product is
RECORDED — step 4 can find the population — and BINDS NOTHING. Products also
never enter the DISTINCT reuse step, which would pollute the growing store with
things that are not food identities. **VERIFIED LIVE, 12/12:**

```text
PRODUCT   Simple Wolf Wrap · Barebells · Royo Everything Bagel
          Quest Protein Chips · Coca-Cola · McDonald's Big Mac
DISTINCT  Творог -> tvorog          Сметана -> smetana
RESOLVED  Помидор -> tomato   White rice   Chicken breast   Eggplant
```

✅ **AND THE LIVE REUSE PROOF IS NOW DONE** — `scripts/prove_distinct_reuse.py`,
real model, real store, table cleared first (reuse against leftovers would prove
the store remembers, not that the judgement works):

```text
1  'Творог 5%'            -> 'tvorog 5 percent'       establishes one identity
2  'Творог 5% жирности'   -> 'tvorog 5 percent'       REUSED
3  'Творог 2%'            -> 'tvorog 2 percent fat'   did NOT collapse
4  Barebells Salty Peanut -> PRODUCT, bound {}        binds nothing, offered to nobody
```

⭐ **STEP 3 IS THE ONE THAT MATTERS.** A reuse step that merged everything would
satisfy step 2 perfectly and then price 2% curd from 5% forever after. The model
was shown an established `tvorog 5 percent` and DECLINED it. Duplicate
identities are cheap; a false collapse is permanent.

⚠ The ids are not formally uniform — `tvorog 5 percent` vs
`tvorog 2 percent fat` — and that is not a defect: they are different foods, so
their ids SHOULD differ. Consistency for any ONE food comes from the store,
which keys on `surface_key`. The defect would be two ids for one food, which is
what step 2 rules out.

⚠ Deliberately NOT in the suite: a proof that costs money and depends on a
provider is EVIDENCE, not a gate.

**SUPERSEDED — what the earlier probe did not show:**

⚠ AND WHAT THE LIVE PROBE DID NOT SHOW. The smoke harness calls `interpret()`
directly, so the reuse step — which lives in `ensure_resolved` — never ran in
it. The `tvorog 5% fat` / `tvorog 5%` variance visible there is RAW PRODUCER
OUTPUT BEFORE REUSE, not evidence that reuse failed, and equally not evidence
that it works. Reuse is proven by gate and mutation only; a live proof of it is
owed at wiring time.

---

**THE ORIGINAL FINDINGS, KEPT:**

⚠ **OPEN 1 — DISTINCT IDS ARE NOT STABLE.** Three ids for one food family, and
they differ in punctuation AND in semantics:

```text
Творог                  -> tvorog
Творог 5%               -> tvorog_5%
Творог (5% или средний) -> tvorog 5% fat
```

The requirement is "a stable lowercase identifier"; per-surface variation breaks
it, so one food logged with different wording becomes several identities.
Deterministic normalization fixes the punctuation half and not the `5%` vs
`5% fat` half. The principled fix is a second step asking whether a new DISTINCT
food matches an ALREADY-STORED distinct id — a growing store rather than a
curated catalogue, the same shape as the semantic annotation store. **DECISION
OWED.**

⚠ **OPEN 2 — BRANDED PRODUCTS LEAK INTO DISTINCT.**
`Simple Wolf Wrap (Original Dough) -> wolfnights_simple_wolf_wrap`. That is the
PRODUCT rung's population (roadmap step 4), not a distinct-food identity. Needs
a gate before the producer is wired into a turn.

⚠⚠ **AND A GATE ONLY A LIVE RUN COULD HAVE CAUGHT.** `_get_client` imported
`_get_anthropic` from `core.micro_estimator`, which imports it from `core.llm`
and does not re-export it. **All 14 unit gates passed** — every one of them
stubs `_get_client`, so the single line they could not exercise was the single
line that was broken. **A stub is a statement about the CONTRACT; it is never
evidence that the thing being stubbed exists.**

### 1c — ⛔⛔ P0: THE CANONICAL MEMORY RUNG WAS DEAD FOR EVERY ROW *(2026-08-14)*

> **CORRECTED CLAIM, PERMANENT** *(Danny)*
>
> ~~memory carries 44.6% of production~~
>
> **44.6% of production had an ADDRESSABLE memory row under a SIMULATED key
> lookup. Actual canonical MEMORY contribution was 0% until this boundary
> repair.** Do not carry the old interpretation forward, and do not trust the
> number again until it is recomputed from REAL RUNG EXECUTION.

`_memory()` did `float(m.confidence)` on a column holding the WORDS
`'likely'` · `'exact'` · `'estimated'` · `'user-confirmed'` — each of which
raises — inside a bare `except Exception` that logged at DEBUG and returned
None. Measured against production:

```text
494 'likely' · 298 'exact' · 41 'estimated' · 3 'user-confirmed'
────────────────────────────────────────────────────────────────
  0 of 836 rows the canonical _memory() rung could return
```

`Rung.MEMORY` is the **TOP** of the canonical ladder, so the canonical lane has
priced from artifact and estimate alone since it was written.

⭐ **FOUND BY A CONSUMER-SIDE PROOF, NOT BY A GATE.** Eleven source gates on
`1f13347` passed; every one asserted `memory_key` was CALLED and none asserted
evidence came BACK. The first proof that read a row off its MACROS found a
permanent failure sitting under all of them. **Third time this session: a
function that is called is not a function whose result is used.**

⭐⭐ **THE REPAIR IS A NAMED BOUNDARY, NOT A GUESSED MAPPING.**
`food_intelligence._CONF_NUM` ALREADY declared the four grades and their
numbers, with its own comment refusing to invent precision. What was missing was
a named crossing between the persisted vocabulary and the numeric contract:
`confidence_score()`. An undeclared grade returns **None, not a default**.

⭐⭐⭐ **AND SILENT FAILURE IS GONE — ONE OUTCOME BECAME FOUR:**

```text
row absent           -> None, silent            EXPECTED
lookup raised        -> None, WARNING           a defect, not an absence
row has no per-100g  -> None, INFO + reason
grade unmapped       -> EVIDENCE RETURNED, WARNING naming the word
```

The row is never discarded over its METADATA — the macros are still evidence.
What is refused is silently substituting a number, which is exactly what broke
it.

**GATES:** one per production grade, verbatim with their real counts, each
asserting a returned `MemoryEvidence` and its macros. **MUTATION: restoring
`float(m.confidence)` turns SIX red**, including all four grades.

⚠ A FIXTURE DEFECT THE GATE ALSO CAUGHT: keying a row on `user-confirmed`
verbatim fails because `normalize_name` strips the hyphen, so the seeded and
looked-up keys differed. A fixture that cannot address its own row proves
nothing — visible only because the failure named a GRADE rather than a
mechanism.

### 1d — ✅ REMEASURED THROUGH THE ACTUAL RUNG *(2026-08-14)*

The instrument now **EXECUTES** `_memory()` instead of approximating it from the
table, because an instrument that approximates its subject cannot discover that
its subject is broken:

```text
    446   44.6%   MEMORY               <- 0% before the repair
     13    1.3%   ARTIFACT
    541   54.1%   estimate / refuse
   ─────────────────────────────────
    459   45.9%   EVIDENCE-BACKED

  uncovered   NON-ENGLISH 307 · BRANDED 96 · QUALIFIED 87 · BARE 51
```

⭐ **THE REPAIR TAKES CANONICAL MEMORY FROM 0% TO 44.6% OF REAL PRODUCTION.**

⚠ **THE NUMBER LANDING ON 44.6% AGAIN IS A COINCIDENCE WORTH NAMING.** The old
addressability estimate was accurate AS AN ESTIMATE; what was false was the
claim that the rung delivered it. Same number, different meaning — exactly the
banana-210 shape, and the reason the corrected claim in §1c stays permanent.

⚠ Population differs slightly from the 691 run (last 1000 entries, no 30-day
window), so ARTIFACT reads 1.3% here against 1.9% there. Not a change — a
different sample.

### 1e — ✅ THE MEASUREMENT LOOP, CLOSED APPLES-TO-APPLES *(Danny, 2026-08-15)*

The first rung-executing run dropped the date filter and reported against the
last 1000 entries while the baseline was 691 over 30 days. **Two populations
read as one longitudinal result** — which is how a coverage number quietly
becomes a trend it never was. Rerun on the SAME window and query shape:

```text
rung                  SIMULATED        EXECUTED
MEMORY              308   44.6%      300   43.7%
ARTIFACT             13    1.9%       13    1.9%
ESTIMATE_OR_REFUSE  370   53.5%      374   54.4%
EVIDENCE-BACKED           46.5%            45.6%

uncovered (executed)  NON-ENGLISH 215 · BRANDED 68 · QUALIFIED 52 · BARE 39
```

⚠ **691 vs 687 ENTRIES: THE WINDOW MOVED.** A rolling 30 days is not the same
30 days a day later, so this is *comparable*, not identical, and about 4 of the
8-entry memory gap is population rather than estimate.

⭐ **WHAT THE COMPARISON ACTUALLY SHOWS.** The simulated estimate was a GOOD
estimate of what the rung COULD deliver — 44.6% against an executed 43.7%, and
the ARTIFACT half matched EXACTLY at 13 / 1.9%. It was a completely FALSE
statement of what the rung DID deliver, which was **0%**. The estimate was never
wrong about the data; it was wrong about the code, and it could not have been
otherwise, because it never ran the code.

**Both records are kept side by side** —
`coverage_last_30_days.json` (simulated) and
`coverage_last_30_days_through_the_rung.json` (executed) — so nobody later reads
one as a continuation of the other.

### 1a — ⛔ P0 CONTAINMENT: A MEMORY KEY MUST NAME A FOOD *(landed 2026-08-14)*

**FOUND WHILE DESIGNING STEP 1, AND IT WAS NOT COVERAGE DEBT — IT WAS A LIVE
MISPRICE.** `normalize_name` keeps `[a-z0-9 ]`, so a food named in a non-Latin
script normalizes to whatever DIGITS it happened to contain, and those digits
were the key into durable per-user food memory.

```text
'Творог 5%'                    -> '5'
'Молоко (2.5%)'                -> '25'
'Кукуруза варёная (2 початка)' -> '2'
'Омлет из 2 яиц'               -> '2'
```

MEASURED, 180 days: **361 distinct non-English foods · 300 normalizing to
EMPTY · 6 KEYS each shared by several DIFFERENT foods of one user**, one key
carrying nine (глазунья · омлет · шакшука · …).

⭐ **AND ONE PRICED A REAL MEAL FROM THE WRONG FOOD:**

```text
cached  u=76 key '2'  'Кукуруза варёная (2 початка)'    boiled corn
        per100g  54.0 kcal · 3.33 p · 5.0 c · 2.08 f    last_used 2026-08-04
entry   2026-08-04  'Творог 2%'  150 g                  2% cottage cheese
        committed 81.0 kcal · 5.0 p · 7.5 c · 3.1 f
        per100g   54.0 · 3.33 · 5.00 · 2.07   <- IDENTICAL, ALL FOUR MACROS
```

Real 2% творог carries ~18 g protein per 100 g. It committed at **3.33** — from
the MEMORY rung, at high confidence. A wrong number wearing evidence, which is
the failure class this whole migration exists to delete.

⭐⭐ **THE KEY FAILS IN BOTH DIRECTIONS AT ONCE.** It MERGES corn, cottage
cheese and fried eggs onto `'2'`, and it SPLITS one food across
`Творог 4% жирности` → `'4'` and `Творог 5% жирности` → `'5'`. Neither is
identity.

**THE CONTAINMENT** — `core.food_intelligence.memory_key_is_addressable`,
enforced inside `get_user_food_match` AND `upsert_user_food_match`:

> A memory identity key must contain meaningful alphabetic content. Empty or
> numeric-only keys are non-addressable.

⭐⭐⭐ **KEY QUALITY, NOT LANGUAGE** *(Danny)*. There is no Cyrillic test and
there must never be one — a key that lost all its letters is non-addressable
whoever wrote it, which is what makes this generalize to every script
normalization has not been taught. ⚠ `str.isalpha()` would have been the wrong
predicate: `'п'` IS alpha to Python, so it would answer about a string
normalization is about to delete entirely.

⚠ **BOTH DOORS, ONE RULE.** Guarding only the READ would be worse than
guarding neither: `upsert` looks up through the guarded reader, so a refused
read takes the CREATE branch and every non-Latin food would mint a fresh `'2'`
row per log — one collision becoming an unbounded pile, and
`scalar_one_or_none` raises on several.

**COST, MEASURED: 11 of 836 memory rows (1.3%) become unreachable** — every one
of them a digit-residue row. Those foods now re-resolve fresh instead of
returning a neighbour's macros. **In this layer no evidence is strictly better
than wrong evidence.** ⚠ The rows are left in place, not deleted: unreachable is
already safe, and deleting production data is a separate decision with an owner.

**THIS IS CONTAINMENT, NOT THE FIX.** These foods are now SAFE rather than
ADDRESSABLE. Step 1 is what makes them addressable.

### 2 — GENERAL CANONICAL SETTLEMENT OWNER

```text
ordinary food turn  ->  ResolvedMeal -> canonical pricing inputs -> assemble()
                        -> price() -> commit_or_load_existing()
                        -> write_canonical_meal()

NOT                 ->  ordinary turn -> legacy _analyze_food -> legacy settlement
```

Acceptance stays **A1–A10** (§3a.2). **EXIT: a normal food turn is canonically
owned end to end** — ⭐ *the true promotion boundary B-1 never claimed to have
completed.*

### 3 — RE-MEASURE, AND DO NOT JUMP BACK INTO FEATURE WORK

Rerun the same historical analysis after 1–2, broken down by MEMORY · ARTIFACT ·
PRODUCT · uncovered · refusal/estimate · language/modifier miss. **That
measurement decides what comes next** — not this document.

### 4 — THE NEXT LARGEST MEASURED GAP *(expected: PRODUCT)*

`Rung.PRODUCT` exists and ranks second; `assemble()` hard-codes
`"product": None`. Expected sequence: product evidence producer → branded-food
fixtures → consumer-side proof → coverage rerun. **Only after this is raw
artifact expansion likely to become the highest-value move again.**

### 5–7 — B-1.7a / b / c

**a** oils: regenerate → prior-identity diff → deterministic pricing →
added-fat identity clarification. **b** materiality: outputs `ASK` ·
`SAFE_TO_ESTIMATE` · `ACCEPT` · `REFUSE`; permanent fixtures bare egg · bare
mackerel · added oil · cooking method · unknown preparation. ⭐ **THE EXISTENCE
OF A RANKER WINNER NEVER PROVES CLARIFICATION IS UNNECESSARY.** **c**
composition: `chicken + olive oil → one meal from two canonical foods`.

### 8–10 — repair, messy food, promotion

**8** every canonical write must be repairable: "actually 8 oz" · "fried, not
grilled" · "no oil" · delete · undo · stale correction · correction after
settlement. **9** stop testing neat examples — mixed meals, restaurant food,
multiple foods per message, sauces, leftovers, partial portions, vague amounts,
photo-then-text. **10** canary → rollback proof → promote → delete the legacy
writer, pricer and duplicate semantic owners. **Then there is ONE food system,
and that is the real completion of B.**

---

## ⏭ THE PRIOR ROADMAP *(Danny, 2026-08-11; revised 2026-08-14 — SUPERSEDED ABOVE for sequencing; the Phase 0 detail below remains accurate)*

**HISTORY — NOT EXECUTABLE.** This read "the next session starts at the
authoritative rebuild — Phase 0 step 1". Phase 0 closed 2026-08-14; the only
executable sequencing is §NEXT.
Not at B-1.7a, and not at any B slice. Phase 0.9 is applied, G1/G2/G3 are
closed, and the build-path proof now RUNS — which is how we learned the store
does not yet cover the retrieval population (see THE STORE IS NOT POPULATED
OVER THE SEAM below). The open defect is confined to BUILD-TIME PRICING
EVIDENCE AUTHORITY and does NOT reopen downstream canonical mutation
correctness.

⚠ **THIS HEADER RAN 2,100 LINES BEHIND ITS OWN BOARD.** It said "start at
0.9" and listed three gates as owed while the status board — reconciled the
same day — recorded all three CLOSED. The staleness gate only checks a date
stamp, so it passed throughout. Reconciling the board is not reconciling the
document; the head is what a parallel session actually reads.

```text
B-1 · B-1.5 · B-1.6   REMAIN CLOSED
concurrency locking, canonical settlement, replay/idempotency, ownership seam
                      REMAIN CLOSED
```

## ⚠ PHASE 0 — ARCHITECTURE CLOSED, CLOSURE EVIDENCE BEING REFRESHED *(2026-08-14)*

**THE ARCHITECTURE STAYS CLOSED. THE EVIDENCE DOES NOT YET MATCH IT.** A
review of `a4b6d23` found that the proof it rested on replays a FROZEN
ARTIFACT and never calls `build_one` — so it establishes replay determinism,
not `captured source -> production builder -> pre-retention equality`. Driving
the real build path then exposed defects the replay proof structurally could
not see.

```text
Phase 0 ARCHITECTURE          CLOSED — do not reopen
Phase 0 CLOSURE EVIDENCE      ~80-85%, refresh owed
Phase 0.5                     implemented and causally wired
B-1.7a                        DO NOT START until the three gates below close
```

### ⛔ WHAT DRIVING THE REAL BUILD PATH FOUND

**1. THE ELIGIBILITY LAYER HAD ZERO PRODUCTION CALLERS.** Phases 0.1/0.2/0.3
and 0.5 built `skills/nutrition/eligibility.py` and nothing imported it —
`cooking_state.py` went with it, its only importer being the module nothing
imported. Its 23 gates passed against dead code and always would have: they
call `el.vetoes(...)` directly, which proves the function WORKS and says
nothing about whether anything INVOKES it. Fixed `d28fc02`, wired into
`build_one` BEFORE the resolver.

**2. AND THE FIRST WIRING CONSUMED ONE REASON OF SIX.** `vetoes()` emits
base-food mismatch, cooking-state conflict, heat-medium conflict,
branded-for-generic, duplicate and no-energy; the build filtered to the first
and discarded the rest. THE CALL WAS THERE AND THE RESULT WAS THROWN AWAY,
which is indistinguishable from being wired at any distance except that line.
Now consumed in full: 34 rows refused (17 mismatch, 12 cooking-state, 5
heat-medium). ⚠ **THAT 34 WAS MEASURED AGAINST THE 249-ROW RECONSTRUCTED
CAPTURE, WHICH G1 THEN REPLACED WITH A 397-ROW SEAM RECORDING** — so the
denominator in the original note ("of 249") described a corpus that no longer
exists. The refusals now visible on the real build path are per-identity and
larger; they are reported by `prove_build_reproducibility.py` and must be
classified by the authoritative rebuild rather than quoted as a single total.

**3. THE SOURCE-QUALIFICATION FIX WAS APPLIED TO THE DATA, NOT THE PRODUCER.**
`candidate_evidence_id` was added, 115 candidates backfilled, gates written —
and `build_one` kept emitting `{fdc_id, description, per100g}`. **The next
real build would have written an artifact with no namespaces**, silently
reverting the portability invariant while every gate stayed green against the
backfilled file. `data_type` was missing the same way, which disabled
`BRANDED_FOR_GENERIC` in any capture built from the artifact.

**4. A REBUILD ON A THIN CAPTURE IS UNINTERPRETABLE.** A first rebuild took
27 identities to 24 and 115 candidates to 73, losing `mushrooms|`, `oats|` and
`rice|` entirely. Cause was MINE: the capture issued only `entity` and
`entity + prep` while the build issues `art.QUERY_SHAPES`. **A rebuild that
shrinks the artifact by a third is only interpretable if its inputs are known
to be at least as good as the ones it replaces.** Reverted, nothing committed.

### THE THREE GATES BEFORE B-1.7a — ALL CLOSED *(2026-08-14)*

```text
G1 capture fidelity   ✅ 2db4029 — recorded AT the seam, 397 rows, fingerprint
                         sha256:5508eb9e, every committed candidate present
G2 human authority    ✅ 2db4029 — 6 admissions in the ANNOTATION STORE
                         + backfilled: all six now BOUND to their source rows
G3 lexical scope      ✅ 5a4c7f4 — the veto reads SILENCE unless the CALLER
                         asserts its namespace; the layer names no provider
```

⛔ **AND THE GATES THEMSELVES SHIPPED WITH THREE HOLES, ALL THE SAME SHAPE:
THE CHECK EXISTED AND DID NOT FIRE.** Found by review of `2db4029`, fixed in
the commit that carries this text. None was a wrong answer; each was a
correct-looking check that could not observe what it claimed to.

```text
1  source_fingerprint is "" on all 6 human admissions.  `apply()` takes
   `source_fingerprints` as an optional kwarg and `__main__` calls
   `apply(store)` without it, so it falls through to "". The gate's
   required-non-empty tuple lists every attributable field EXCEPT this one.
   -> the commit claimed the six carry "was / now / reviewer / cause /
      source fingerprint / round". Five of six were true.
   -> OPEN: needs a decision, see below.

2  the capture gate computed the expected query set and never compared it.
   `expected` was assigned and referenced nowhere; the loop counted records
   and read their metadata. A capture holding the RIGHT NUMBER of the WRONG
   QUERIES passed — the exact capture the gate exists to reject.
   -> FIXED. Asserted, and against `prep_onto.name_with` rather than a
      re-spelled string transform, which would have been a second
      implementation of the notion the gate is checking.

3  prove_build_reproducibility.py could not run at all. It declared its OWN
   CAPTURE_PATH at the file G1 rewrote, so it read the seam capture's
   `{meta, queries}` envelope as a flat identity map, handed `build_one` the
   literal string "meta" as a food, and died on 'str' has no attribute 'get'.
   NOTHING IMPORTED IT, so the suite stayed green over a dead proof.
   -> FIXED. One constant, imported from `capture_retrieval`. Replays BY
      QUERY, because the build dedupes keeping first occurrence. A missing
      capture is refused, never synthesised onto the authoritative path.
      And `tests/test_the_build_path_reproduces_itself.py` now INVOKES it.
```

⭐ **THE PATTERN IS WORTH NAMING ONCE MORE.** A kwarg nobody passes, a
variable nobody asserts, a script nobody imports — the same family as the
eligibility layer with no caller, the veto result thrown away, and the
`matched: 0` read off an unarmed instrument. Each was written correctly. None
could fire.

### ⛔ THE STORE IS NOT POPULATED OVER THE SEAM *(measured 2026-08-14)*

**Driving the now-runnable build proof against the G1 capture is what finally
showed this**, and no replay proof could have: the store was populated over
the committed artifact's CANDIDATES, while the real build sees the retrieval
POPULATION.

```text
poisoned build x3 through build_one()      regime rank_v2
  poison bites                             True
  resolved_this_build per run              [0, 0, 0]
  identities built                         27
  fingerprint da009b002460b393  IDENTICAL across runs   <- determinism HOLDS

  ⭐ UNSEEN PAIRS per run                  86    <- SIZES THE POPULATE STEP
     resolver batches per run              37    (batch size 3)
     resolver ATTEMPTS per run             111   (up to 3 tries each)
     attempts total, all 3 runs            333   <- NOT a pair count
  ⛔ candidate deltas, build vs artifact
       cauliflower| 9/6 · chicken|roasted 5/4 · egg| 6/5 · mackerel| 8/7
       salmon| 14/13 · shrimp| 4/3 · tofu| 2/4
```

**WHAT THIS DOES AND DOES NOT MEAN.** The build IS deterministic over fixed
real inputs — the fingerprint is byte-identical across three runs, which is
the claim the script exists to make and it holds. What does NOT hold is
`resolved_this_build == 0` meaning "it could not have asked": it asked and was
refused every time. **`tofu| 2/4` is the two HOUSE FOODS rows, already typed
as a RETRIEVAL absence.** The other six deltas are the store admitting rows
the 08-08 candidate lists never held — the eight-row delta's larger cousin,
and exactly the population the authoritative rebuild must classify by
retrieval | mechanical | semantic | source.

⚠ **AND THE FIRST VERSION OF THIS SECTION QUOTED THE WRONG NUMBER.** It said
the store needs population over "333 pairs". It does not. 333 was raw resolver
invocations: `build_one` batches unseen rows by `_QUALIFY_BATCH = 3` and
retries each batch up to `_QUALIFY_ATTEMPTS = 3` times, and the counter
accumulated across all three proof runs. One missing pair can bill as nine
attempts. **The measured figure is 86 unique pairs** — the populate step is
roughly a quarter the size the headline implied. The proof now emits
`unseen_pairs`, `unseen_pairs_by_identity`, `resolver_batches` and
`resolver_attempts` per run, separately named, and a gate reconciles them
against the batching constants so they cannot drift apart again.

```text
86 pairs   ->  37 batches (ceil per identity)  ->  111 attempts/run  ->  333
heaviest: oats| 8 · rice| 8 · chicken|grilled 7 · egg| 6 · potato|fried 6
```

⚠ **AND IT WAS BRIEFLY 87, WHICH IS THE MORE INTERESTING CORRECTION.** The
first fix counted from `build_one`'s RETURN PAYLOAD, which reads
`result["unresolved"]`. Two things were wrong with that:

```text
1  the FAILED branch omits `unresolved` entirely — it computes the list,
   quotes its LENGTH in the reason string, and drops the list. So an
   identity with nothing priceable contributes ZERO outstanding pairs no
   matter how many the resolver was asked about, and the undercount lands
   precisely on the identities in the worst shape.   (fixed in build_one)

2  the payload counted `beef|/usda:173086`, which is a REVIEWED UNRESOLVED
   — a human read the record, judged the evidence insufficient, and DECLINED
   TO RULE. `needs_resolution` refuses to re-ask it on purpose: replacing a
   considered refusal with a sampled opinion would erase the review on every
   rebuild. It is SETTLED, not outstanding.
```

**Counting what the resolver is ASKED, rather than what the build reports,
fixes both at once** — no return shape can suppress it, and a human's
non-decision is never billed as work. A gate asserts no counted pair is one a
reviewer has already settled. The proof now also emits `unseen_pair_ids`, so
the populate step reads the worklist rather than re-deriving it with a second
implementation.

⛔ **THE CLOSURE CONDITION REQUIRES BOTH HALVES, AND IT IS NOW EXECUTABLE.**
`resolved_this_build == 0` is TRUE today while the resolver is called and
refused every time — reading that zero alone as "it could not have asked" is
the unarmed-instrument error this migration keeps finding. The proof computes
`closure_condition_met` as:

```text
poison_bites  AND  resolved_this_build == 0 for every run
              AND  resolver_calls == 0
              AND  no failures
```

**WHEN THE STORE IS POPULATED ACROSS THE SEAM, TIGHTEN THE GATE IMMEDIATELY**
— `test_resolved_zero_alone_does_not_mean_the_resolver_was_unreachable` says
so in its own body. Until then an all-red-but-deterministic build must not be
able to satisfy the "deterministic over fixed inputs" test and read as
closure.

**This is a measurement, not a regression.** Nothing shipped worse; an
instrument that could not run now runs and reports the real state.

### THE ORIGINAL GATE TEXT *(kept — it is the specification)*

**G1 — CAPTURE FIDELITY.** The capture must be produced by the SAME retrieval
invocation `build_one` uses, never by a second script reconstructing
`QUERY_SHAPES`. Record query string -> ORDERED rows (the build dedupes
preserving first occurrence, and order can reach ranking), provider namespace,
data type, and `retrieval_fingerprint`. Gate that the capture fingerprint
equals the build's current one. This removes another "two implementations of
one notion" seam — the defect family this migration keeps finding.

**G2 — HUMAN AUTHORITY.** An adjudication that changes candidate ELIGIBILITY
cannot live in `winner_review.py`: `build_one` decides candidates from
`sa.eligible(annotation)`. Decisions must enter the ANNOTATION STORE as a new
attributable review round carrying identity, source-qualified evidence, old
disposition, new disposition, reviewer/cause, source fingerprint and round —
with a gate proving an ordinary resolver rebuild cannot overwrite them. Do NOT
amend the frozen 77. `winner_review.py` stays about REPRESENTATIVENESS; the
store stays the authority for ADMISSION.

**G3 — LEXICAL-VETO SCOPE.** `base_food_mismatch` proves mismatch through
ABSENCE OF SHARED TOKENS. Sound inside one lexical namespace, false the moment
a second exists: `eggplant`/`aubergine`, `chickpea`/`garbanzo`,
`chicken`/`poulet` each have zero overlap and are one concept. Scoped to
`VALIDATED_LEXICAL_NAMESPACE = "usda_en"`; every other namespace reads as
SILENCE. The architecture this must not block:
`provider text -> provider normalisation -> canonical concept identity ->
mechanical comparison`, never `arbitrary provider text -> English token
overlap -> destructive decision`.

### THE EIGHT-ROW DELTA — 6 SEMANTIC ADMITS + 2 RETRIEVAL ABSENCES

Populating the store gave the artifact annotations its 08-08 candidate lists
never had, so the live build derives a smaller universe. Eight rows disagree.

```text
ADMIT   mackerel|roasted  usda:174236 / 173674 / 171994   king · spanish ·
                          Pacific-and-jack, cooked dry heat
ADMIT   chicken|fried     usda:171448   battered
ADMIT   chicken|grilled   usda:171536   with added solution
ADMIT   shrimp|           usda:171972   canned
retrieval  tofu|          usda:173788 / 173787   HOUSE FOODS
```

⭐ **THE RESOLVER CONTRADICTED ITSELF ON THE MACKEREL THREE.** It marked them
DIFFERENT_IDENTITY while marking chinook/chum/pink/sockeye/Atlantic salmon
admissible for `salmon|roasted` — the identical class, hand-signed as
"same_base_food + species_specialization + preparation_compatible".

⭐⭐ **AND TWO CALLS WERE CORRECTED BEFORE THEY BECAME DURABLE.** Canned
shrimp was nearly a semantic REJECT; canned shrimp IS shrimp, and calling it
otherwise would use ADMISSION to solve REPRESENTATIVENESS. The HOUSE FOODS
rows were nearly human rejects too — their absence has a PROVENANCE and it is
RETRIEVAL (Foundation + SR Legacy returns no branded rows), neither a
reviewer's verdict nor a veto. Recording them as rejects would have written
down that a tofu product is not tofu.

### ⛔ AN ABSTENTION WAS BECOMING A CONFIDENT NEGATIVE *(found 2026-08-14, before the populate)*

**THIS WOULD HAVE CORRUPTED THE POPULATE RUN, DURABLY AND INVISIBLY.** Found
while building the batch-completeness instrumentation, which exists precisely
because "a batch can look like a completed model operation while silently
shrinking the evidence universe". It does worse than shrink it: it writes down
a falsehood.

```text
qualify_usda_rows   treats ONLY an all-abstain batch as an outage
a PARTIAL abstention returns disposition="qualified", and the unjudged
  rows simply fall out of `kept`
build_one           judged = {ids in q.rows};  everything else ->
                    DIFFERENT_IDENTITY at confidence 0.95
needs_resolution    sees a RESOLVED annotation -> never reopens it
```

Measured on a stubbed partial batch, before the fix:

```text
usda:1  KEPT              SAME_IDENTITY       0.95
usda:2  ABSTAINED         DIFFERENT_IDENTITY  0.95   <- nobody assessed it
usda:3  judged-rejected   DIFFERENT_IDENTITY  0.95
        every one of them  needs_resolution = False
```

**A durable, confident verdict about a row no model ever assessed** — and
afterwards indistinguishable from a real rejection, so nothing downstream can
count how often it happened. Over 86 pairs in 37 batches, every partial
abstention would have become a permanent false negative that no rebuild
reopens.

⭐ **THIS IS `541ed12` ONE LAYER DOWN.** "An absent answer is not a negative
answer — stop the qualifier deleting evidence" fixed the QUALIFIER. The store
write underneath it kept doing the same thing, on the stated reasoning that
"anything it saw and did not keep is a judged negative" — true for a
rejection, false for an abstention.

```text
Qualification.abstained   the rows the model DECLINED to judge, carried out
                          of the qualifier instead of dropped on the floor
build_one                 abstained -> UNRESOLVED, confidence 0.0, and NOT
                          counted in resolved_this_build
                          judged-and-rejected -> DIFFERENT_IDENTITY, unchanged
```

**THE PRODUCTION TURN PATH WAS NEVER AFFECTED.** `tool_executor` reads
`q.rows` for ranking and writes no durable annotation, so an abstention there
only means the row does not compete that turn — correct fail-closed behaviour.
The defect was confined to `build_one`, the durable-annotation writer, which
is the right scope and is where the fix lives.

Gated causally, including a test that reintroduces the defect: a
`Qualification` reporting no abstentions must produce the confident false
negative again, or the suite is not testing what was wrong.

### SEQUENCE FROM A CLEAN BASE

```text
✅ commit the sound hardening -> clean tree
✅ capture at the REAL retrieval seam (G1)
✅ apply attributable human annotation overrides (G2)
✅ make the build-path proof RUNNABLE and gate it   <- was dead; see above
✅ bind all 6 human admissions to their source rows (Danny's call: BACKFILL)
✅ correct the pair/attempt accounting: 86 unique pairs, not 333
✅ STOP AN ABSTENTION BECOMING A CONFIDENT NEGATIVE   <- BLOCKED the populate
◻  batch-completeness instrumentation on the seam-population path
◻  populate the store over the SEAM population, not the 08-08 candidates
      -> 86 unique (identity, evidence) pairs have no annotation
      -> the worklist itself is emitted as `unseen_pair_ids`; the seam
         population CONSUMES it and must never rediscover it
◻  authoritative rebuild
◻  classify EVERY old->new delta: retrieval | mechanical | semantic | source
◻  re-freeze ONLY moved winner universes
◻  poisoned real-build proof: resolved=0 AND resolver_calls=0, retention=0
      -> then TIGHTEN the gate to require closure_condition_met
◻  exact-tree SQLite + Postgres
◻  controlled production canary   (prod is 30 commits behind)
◻  B-1.7a starts
```

### ✅ THE SIX HUMAN ADMISSIONS ARE BOUND TO THEIR ROWS *(Danny, 2026-08-14)*

All six shipped with `source_fingerprint: ""`. That is not a weaker binding —
it is the ABSENCE of one: `stale_source()` compares only when BOTH sides carry
a value, so the six rows a human took the trouble to adjudicate were the only
ones that could never be invalidated by their evidence moving underneath them.

**DECIDED: BACKFILL FROM THE SEAM CAPTURE, NOW, NOT DEFERRED INTO THE
REBUILD.** The review decision already exists; adding the fingerprint
completes its provenance rather than re-adjudicating it.

```text
mackerel|roasted usda:174236  sha256:070bf87271b0bea6
mackerel|roasted usda:173674  sha256:a17264eb5c02bb25
mackerel|roasted usda:171994  sha256:73dff2cde9b2022a
chicken|fried    usda:171448  sha256:93293faac84a0ea2
chicken|grilled  usda:171536  sha256:d36e8677a4749b63
shrimp|          usda:171972  sha256:7c19af9c82ac8458
```

The artifact diff is exactly twelve lines — six `""` out, six fingerprints in.
`was = DIFFERENT_IDENTITY` is preserved because the committed LEDGER, not the
already-moved store, is the authority for what each pair was before the round.

**⭐ AND EVERY OCCURRENCE IS CHECKED, NOT THE FIRST ONE FOUND.** A row can be
returned by more than one query shape, so one evidence id legitimately appears
several times in the capture. `fingerprints_from_capture()` requires EXACTLY
ONE unique `_row_fingerprint` per pair and REFUSES otherwise: two different
fingerprints under one source-qualified id means the id is describing two
rows, and taking whichever came first would bind a human decision to an
arbitrary one of them. Absence is refused the same way. Both are gated
causally.

`apply()` no longer defaults the fingerprint to `""` — an optional kwarg
nobody passes is not a default, it is a hole — and both `verify()` and the
gate's required-field tuple now include `source_fingerprint`.

## ✅ PHASE 0 IS TECHNICALLY CLOSED *(2026-08-13 — SUPERSEDED ABOVE)*

> Given retrieved source-qualified evidence, the frozen semantic baseline, and
> the explicit `rank_v2` policy regime, Arnie deterministically reproduces the
> same pre-retention candidate universe, eligibility, winner, winner-review
> state, price and provenance **without an LLM call**. Every destructive change
> is attributable. Retention is not required to manufacture semantic coverage
> or reproducibility.
>
> **`HELD` REMAINS `HELD` AND IS NOT UPGRADED BY THIS CLOSURE.** `SIGNED` means
> a winner was approved; `HELD` means deterministic and NOT approved for broad
> promotion. Phase 0 closes REPRODUCIBILITY AND ATTRIBUTABILITY, not winner
> acceptability — which is what keeps a missing fish taxonomy or `beef|`'s
> retrieval breadth from turning it into an unbounded food-quality project.

```text
POISONED REBUILD x3 · regime rank_v2
  poison bites (verified BEFORE trusting its silence)   True
  resolved_this_build per run                           [0, 0, 0]
  identities compared                                   27
  raw fingerprint            f6f4bc2dba07d8d8823b6830b84c33e5
  frozen winners reproduced                             27/27
  retention additions                                   0

WINNER ACCOUNTING   27/27 · 13 SIGNED · 14 HELD · accounting 0 failures
SEMANTIC STORE      186 annotations = 77 human + 109 resolved
SUITES              SQLite 8908/0 · Postgres 8990/0 · shuffled, both engines
```

**WHAT IS STILL OWED, AND IS DELIBERATELY NOT PHASE 0'S:** 14 HELD winners
remain real release blockers for those identities — 5 on `cooking_yield`
having no entry for the food, 4 on retrieval breadth, 4 on a specialty variant
outranking the generic, 1 on the as-eaten canary. They are honest, typed and
owned; none of them is a determinism defect.

**FIRST FOLLOW-UP AFTER CLOSURE:** `ci.yml` passes `-q` on top of
`pytest.ini`'s, making it `-qq`, which suppresses the summary line the
workflow then greps for. The build still passes or fails correctly on exit
code, but the reported summary is empty.

**PHASE 0 PROGRESS, 2026-08-13.** Roughly 95–97%. What was a
"just run the poisoned rebuild" problem on 08-12 is not: the baseline freeze
exposed a separate RANKER REACHABILITY defect that had to be fixed first, and
then that fix exposed that the remaining ambiguity was a temporary TWO-POLICY
problem. Both are now closed.

```text
0.1  adapter keeps what code can decide          ✅ d3066ac
0.2  raw cannot serve a cooked request           ✅ 4b17097
0.3  preparation compatibility by heat medium    ✅ be33974
0.4  the model annotates once; code decides      ✅ bc58abf
0.5  base-food mismatch as a mechanical veto     ◻ AFTER Phase 0 closes
0.6  baseline admission and freeze               ✅ 0c255cd   77 signed
0.7  ranker reachability                         ✅ 724935b   27/27 under V2
0.8  split V2 from its preference                ✅ uncommitted
0.9  review the 24 canonical winners             ⬅ IN FLIGHT, 0 signed
1    populate store unpoisoned, then poison      ◻ ORDER CORRECTED
2    permanent drift gates                       ◻
     -> PHASE 0 CLOSED
```

**⚠ WHAT PHASE 0 DOES AND DOES NOT BUY.** Meeting the exit criterion makes
prices **REPRODUCIBLE, NOT CORRECT.** Before 0.7, five committed identities
priced from nothing and 21 of 27 production winners had never been reviewed.
The baseline machinery worked exactly as intended: *it exposed that the
population being reviewed and the population actually pricing users were not
the same thing.*

**⚠ AND V2 PROMOTION IS ITS OWN RELEASE DECISION.** "Adopt V2-structural as
the canonical regime Phase 0 proves against" is SEPARATE from "expose it to
100% of production traffic". The refusal behaviour is safe and supported; the
`as_eaten` tie-break needs its own canary with explicit cut/coating controls.
See 0.8 and step 11 below.

### 0  PRICING AUTHORITY MIGRATION  *(HISTORY — was "immediate next session"; done, see §NEXT)*

Move these qualification dimensions into DETERMINISTIC CODE:

```text
raw vs cooked · preparation compatibility · branded vs generic
unit compatibility · duplicate equivalence
```

The model is reduced to ADVISORY SEMANTIC METADATA ONLY — classification,
confidence, reason, ambiguity — with **no authority to delete durable
evidence**. The four-layer spine becomes:

```text
evidence -> deterministic eligibility -> advisory semantics -> deterministic ranking
```

**EXIT — STRENGTHENED *(Danny, review of `9279860`)*.** "No authority to
delete durable evidence" is NECESSARY AND NOT SUFFICIENT. With the same
candidate universe and no deleted rows, differing model confidence could still
move eligibility, the winner and the price — eliminating DESTRUCTIVE
stochasticity while keeping RANKING stochasticity, which would fail Phase 1's
own exit. The invariant, in its sharpest form:

```text
PRODUCTION PRICING MUST BE COMPUTABLE WITHOUT AN LLM CALL ONCE SOURCE
EVIDENCE IS RETRIEVED.
```

Model advisory metadata may neither delete durable evidence NOR alter
production eligibility, winner or price — unless converted through an
explicitly deterministic, versioned policy that is itself reproducible from
frozen inputs.

**MEASURED STATE AGAINST THAT BAR, 2026-08-11:**

```text
TURN TIME   ALREADY COMPLIANT AND GATED. `price()` is synchronous
            (`test_pricing_cannot_await_anything`, AST-checked), and stored
            candidates carry only fdc_id / description / per100g — no
            confidence and no relationship reaches the ranker.
BUILD TIME  NOT COMPLIANT. The model does not rank, but it GATES SET
            MEMBERSHIP: `qualified(accept=IDENTITY_BEARING,
            minimum_confidence=0.80)` decides who competes, so a confidence
            of 0.75 vs 0.80 on one row changes the set and can change the
            winner. Same consequence, one step earlier.
```

So Phase 0's real target is precise: **the artifact's candidate set must be
derivable deterministically from retrieved evidence. The model may ANNOTATE;
it may not GATE.** The model can still explain, flag ambiguity and feed
diagnostics, human review and future policy research — none of which touch
the price-producing path.

**FIRST INCREMENT LANDED.** `EvidenceRecord.structured` now preserves the
provider's own facts (`data_type`, `basis`, serving mass), which the USDA
adapter previously DISCARDED — handing the model prose and nothing else, which
is why qualification became its job at all. A dimension decidable from a
structured field must not be decided by a language model, and it cannot be
decided in code that never receives it.

`skills/nutrition/eligibility.py` adds deterministic mechanical vetoes:
branded-record-for-generic-intent, non-scalable basis, record-states-no-energy,
duplicate. It **VETOES AND NEVER ADMITS** — a rule that could admit would be a
second authority on identity — and a veto is NOT an abstention: there is
deliberately no reason meaning "unknown", because a rule that cannot evaluate
its dimension stays silent rather than manufacturing a negative.

Measured: 50/50 identical on frozen rows; 0 vetoes on curated mackerel rows;
**8/8 vetoed on branded queries for generic intent**.

**INCREMENT 0.2 — RAW VERSUS COOKED, the dimension that actually caused the
instability.** `skills/nutrition/cooking_state.py`. For `mackerel|roasted`
USDA returns eight rows and the discriminating fact is plain in every one:

```text
VETOED    Fish, mackerel, Atlantic / king / spanish, raw        RAW
eligible  Fish, mackerel, Atlantic / king / spanish, cooked, dry heat
eligible  Fish, mackerel, salted · jack, canned, drained solids UNCLASSIFIED
```

A request for a ROASTED food cannot be served by a row stating RAW, and
establishing that needs no language model. **The three rows left eligible are
exactly the three the stable qualifier kept — and two of them, 174236 and
173674, are rows the drift destroyed.** They can no longer be removed by any
mechanical rule. 50/50 identical.

**THE VOCABULARY IS DECLARED, NOT INVENTED.** Tokens come from
`validators._PREPARATIONS`, the set the resolver already acts on, so this adds
no new words — only a STATE GROUPING over an existing closed set, versioned as
`food_cooking_state_v1`. A gate asserts no food name appears in the module's
code.

**CONSERVATIVE BY CONSTRUCTION.** `UNCLASSIFIED` is a first-class state, not a
failure. Preservation terms (salted, canned, smoked, dried, frozen) decline to
speak — canned fish is usually cooked and "usually" is not mechanical. A
description asserting BOTH states declines to choose, because "raw, then
cooked" is real USDA phrasing and picking one is identity work. A veto needs
BOTH sides classified AND in conflict; everything else is silence.

Mutations, signal verified before each verdict:

```text
unclassified treated as conflict   conflict(salted)->True      4 red
substring instead of word bounds   "Strawberry preserve"->RAW  1 red
both-states description picks one  "raw, then cooked"->COOKED  1 red
```

The substring signal is the sharpest: it classifies **"Strawberry preserve" as
RAW**, because "raw" sits inside "strawberry" — the silent food-changing
failure `pricing_artifact._without` was written for, arriving in a new module.

**INCREMENT 0.3 — PREPARATION COMPATIBILITY, BY HEAT MEDIUM.** Raw-vs-cooked
was safe because the states are mutually exclusive. Preparation is not, and a
naive token conflict would be WORSE than the defect it replaces:

```text
"roasted" vs "cooked, dry heat"   NOT a conflict — dry heat is USDA's SUPERSET
"grilled" vs "roasted"            NOT vetoable — different, not exclusive
"roasted" vs "stewed" / "fried"   a real conflict
```

Vetoing the first would destroy correct evidence DETERMINISTICALLY, which
never varies and therefore never surfaces — strictly worse than destroying it
nondeterministically.

So the rule groups by HEAT MEDIUM (dry / moist / fat), **which is USDA's own
vocabulary** — their rows say "cooked, dry heat" and "cooked, moist heat"
beside method terms already in `validators._PREPARATIONS`. A specific method
therefore never conflicts with the generic term containing it, and preparation
discrimination WITHIN a medium stays with ranking. `"dry"` without `"heat"` is
preservation, not a medium — reading it as dry-heat cooking would veto
moist-cooked rows against a dried request.

```text
unclassified treated as conflict   conflict(salted) -> True         4 red
substring instead of word bounds   "Strawberry preserve" -> RAW     1 red
both-states description picks one  "raw, then cooked" -> COOKED     1 red
token conflict instead of medium   grilled vs roasted -> conflict   2 red
"dry" alone counts as dry heat     "Milk, dry, whole" -> DRY        1 red
multi-medium picks the first       "fried, then baked" -> DRY       1 red
```

### 0.4 — THE MODEL ANNOTATES ONCE; CODE DECIDES WHAT IT MEANS

Two options were MEASURED before this design was chosen, and both are closed.

**Removing the model is not viable.** With mechanical eligibility alone,
deterministic fuzzy ranking selects `Babyfood, guava and papaya with tapioca`
for "papaya", `Chicken spread` for "chicken" and `Fish oil, salmon` at
902 kcal for "salmon" — zero vetoes on all three. The semantic boundary is
load bearing.

**Re-sampling the model is not viable either.** `temperature` returns
`400 deprecated for this model`, and 0.75-vs-0.80 on one row moves the priced
universe with no source change.

So the model becomes a ONE-TIME ANNOTATOR whose output is durable, versioned,
reviewable DATA — `skills/nutrition/semantic_annotations.py`.

```text
annotation.relationship == SAME_IDENTITY  ->  deterministic policy  ->  eligible
NOT:   model -> eligible=true
```

That distinction is the slice. Persisting the model's own eligibility
conclusion would SERIALIZE the gate rather than remove it — the same authority
with a longer cache. The vocabulary therefore contains no operational member,
and `Annotation` carries no `eligible` field.

**PROVEN AT BUILD LEVEL, NOT ONLY IN UNIT TESTS:**

```text
build 1                     44 annotations persisted, 44 resolved
build 2, API KEY POISONED   "ALL ANNOTATED — resolver not called"
                            0 resolved this build (REUSE ONLY)
                            mackerel|roasted -> [175120, 174236, 173674, 171994]
                            IDENTICAL, including all three rows the original
                            drift destroyed, with the model unreachable
```

**THE BEHAVIOURAL FIX.** A resolver outage no longer FAILS the identity. It
marks unseen rows `UNRESOLVED` and prices everything already annotated. That
is exactly why `mackerel|roasted` lost three rows before: one bad reply
refused the whole identity.

**`UNRESOLVED` IS NOT `DIFFERENT_IDENTITY`.** Four dispositions stay distinct —
`unresolved_never_annotated`, `ambiguous`, `different_identity`,
`below_confidence`. Two are revisitable and two are settled, and only a
distinct reason says which. A corrupt stored row loads as ABSENT. The model
cannot assert `UNRESOLVED` at all, or it could launder a failure into a
stored fact.

**A NEWER MODEL IS NOT AN INVALIDATION EVENT.** `rebuild`, `retry`,
`new_model_available`, `confidence_changed` and `unexplained` cannot be
spelled as causes. `needs_resolution` is AST-gated against reading confidence,
model or version.

**`source_fingerprint` IS ENFORCED, NOT MERELY RECORDED.** A changed USDA row
makes the stored verdict answer a question nobody asked, so it re-annotates
with `cause=source_changed`. A MISSING fingerprint does NOT force
re-annotation — silence about the source is not evidence the source changed,
the same invariant one layer down.

Eight mutations, each with its signal verified before the verdict:

```text
missing annotation -> DIFFERENT_IDENTITY   3 red
rebuild as a valid cause                   2 red
replacement with no cause                  7 red
reuse re-rolls on marginal confidence      1 red
model may assert UNRESOLVED                1 red
fingerprint ignored                        1 red
missing fingerprint forces re-annotation   1 red
DIFFERENT_IDENTITY becomes priceable       3 red
```

**PHASE 0 EXIT IS NOW MET AT BUILD TIME**: production pricing is computable
without an LLM call once source evidence is retrieved — demonstrated with the
resolver not merely unnecessary but BROKEN.

**NEXT IS PHASE 1**, and it is not yet done: 10-50 clean PRE-RETENTION builds,
100% identical, no statistical tolerance, with retention forbidden from being
what creates agreement.

**WHAT 0.2 AND 0.3 DO NOT DO.** The model still GATES: removing raw rows and
incompatible media mechanically does not stop
`qualified(minimum_confidence=0.80)` abstaining on the rows that survive.
Authority is REDUCED, not removed, and Phase 0's exit is unchanged. **0.4 —
removing the model's gating power — is what actually unblocks the raw
reproducibility proof.**

### 0.5  BASE-FOOD IDENTITY MISMATCH AS A MECHANICAL VETO  *(NEW — Danny, 2026-08-13)*

**FOUND BY THE PHASE 1.5 WORKSHEET, and it reframes what the semantic
boundary is for.** The Tier 2 rows — "would win after one candidate removal"
— read:

```text
chicken|grilled  <-  Mushrooms, portabella, grilled     29 kcal
egg|fried        <-  Plantains, green, fried           309 kcal
egg|fried        <-  Tofu, fried                       270 kcal
potato|fried     <-  Egg, whole, cooked, fried         196 kcal
beef|roasted     <-  Salami, cooked, beef              261 kcal
```

**`best_candidate` MATCHES ON THE PREPARATION TOKEN, NOT THE FOOD.** "grilled"
matches "grilled", so portabella mushrooms would price grilled CHICKEN if one
candidate disappeared. "fried" matches "fried", so plantains would price a
fried EGG.

So the semantic boundary is not merely cleaning up noisy USDA matches. It is
the only thing standing between a preparation word and a completely different
food — and the reviewed baseline is correspondingly more load-bearing than
"papaya / chicken / salmon" suggested.

**THE FRONTIER CANNOT CERTIFY SAFETY, ONLY CONSEQUENCE.** It calls
`best_candidate`, which is correct for "what would production do?" and
insufficient for "what risk exists?" — it can expose only errors the ranker is
capable of producing under its own scoring. It inherits the ranker's blind
spots by construction.

**THE FIX IS A RANKER-INDEPENDENT MECHANICAL VETO**, not a replacement
frontier: an obvious cross-food identity mismatch should be rejected BEFORE
ranking, so "fried" never gets the chance to outweigh "egg" versus "plantain".
The semantic baseline remains the ADMISSION authority; the mechanical layer
gains the power to refuse a mismatch it can establish confidently.

**THE DESIGN RISK, NAMED IN ADVANCE.** The conservative form — "the requested
base entity appears nowhere in the candidate description" — is much weaker
than identity parsing and is NOT comma-position parsing: it asks whether the
requested food is mentioned AT ALL, not which food the description is. But it
would false-veto on synonymy ("beef" requested, description says "steak"), and
a false mechanical veto is DETERMINISTIC evidence destruction — the failure
class 0.3 was written to avoid. So this needs the same discipline 0.2/0.3 got:
silence whenever the check cannot be made confidently, and a measured
synonym-collision survey before it is allowed to veto anything.

**SEQUENCED AFTER Phase 0 closes**, not folded into the 77-row adjudication.
The Tier 2 rows are telling us the ranker relies on semantic admission to
protect it from a class of failure that could be made mechanically impossible
— that is a hardening increment, not a review decision.

**⭐ AND 2026-08-13 SHARPENED WHY IT MUST STAY OUT OF THE EVIDENCE BOUNDARY.**
`papaya` used to seat "Babyfood, fruit, guava and papaya with tapioca,
strained" — the entry-2896 defect, and the RED half of the qualification
red/green pair. Morphological folding closed it: the composite never won
because it was attractive, it won because **"papaya" could not reach "Papayas,
raw" AT ALL.** One apparent qualification failure was a RANKER REACHABILITY
defect, and fixing it inside qualification would have papered over the wrong
layer.

The pair's red is RESTORED with a case that still reproduces — with no plain
row on the shelf, ranking alone still seats the babyfood purée, because
**composite-seating is a property of WHAT IS ON THE SHELF, not of how the
query is spelled.** Qualification remains independently justified; one
demonstration of the need was removed and the need survives in a form the
fold cannot reach. *A red that has quietly gone green makes its green half
prove less than it claims.*

### 0.6  BASELINE ADMISSION AND FREEZE  ✅ **DONE** *(2026-08-13, `0c255cd`)*

77 hand-adjudicated `(identity_key, evidence_id)` pairs are durable semantic
fact: **29 admit · 45 reject · 3 signed UNRESOLVED**. Signatures live as DATA
in `scripts/baseline_signatures.py`; `accounting()` enforces the six
pre-freeze conditions and `freeze()` writes them under an open
`baseline_migration`, which then closes behind itself.

**⭐ A GATE PROVES ITS POPULATION RECONCILES WITH ITSELF, NOT THAT IT IS THE
RIGHT POPULATION.** The accounting gate immediately caught 8 rows the triage
narrative had called "quick REJECT" and never signed — prose cannot audit
itself. It then passed at 77/77 while 77 was still the wrong set: the
artifact commits **116 candidate pairs and the review covered 6 of them**.
71 of the 77 were cold-start discoveries. The frontier had selected rows
consequential relative to the REBUILD candidate sets, not to production.

Two traps caught before writing, both now gated:

* `needs_resolution` would have handed the 3 human UNRESOLVED calls back to
  the model on every build. A reviewer's refusal to rule spells the same
  relationship as "nobody looked". A signed row is now SETTLED — still
  ineligible, never re-rolled; only a changed `source_fingerprint` reopens it.
* `invalidation_reason=baseline_migration` would have EMPTIED the artifact.
  `eligible()` refuses any annotation carrying one, so writing it on all 77
  makes all 29 ADMITS ineligible. **`baseline_migration` is the CAUSE
  authorising replacement — an argument to `record()`. A signature is not an
  invalidation.**

### 0.7  RANKER REACHABILITY  ✅ **DONE** *(2026-08-13, `724935b`)*

The freeze exposed a defect that had survived the entire migration: **five
committed identities priced from NOTHING.** `_from_artifact` returns None
when `best_candidate` matches nothing and `price()` falls through — no error,
no log, no metric. `mackerel|roasted` is the identity this migration started
from.

**MEASURED CAUSE, and it was TWO defects, not one.** Reading the description
said "category prefix"; reading the SCORE said otherwise:

```text
banana| potato|    overlap 0.00, token ABSENT           MORPHOLOGY
oats|              overlap 1.00, 3.0-0.15*13 = 1.05     V1 LENGTH LEVER
mackerel|roasted   overlap 0.50, id 1.00, 0.90 < 1.2    V1 LENGTH LEVER
tilapia|roasted    same
```

`_singular` folds both sides of the comparison. **SYMMETRY IS THE CONTRACT,
CORRECTNESS IS NOT** — "molasses" folds to "molass" and still matches
"molasses", which is what lets this be six suffix rules instead of a
dictionary. Applied to the two coverage ratios ONLY; `_FORM_PENALTY`,
`_SPECIES_TOKENS`, `_CUT_NARROWERS`, `_COOKED_MARKERS` still match RAW
literals, with a gate that fails if anyone folds those too.

Collateral over all 27 identities, both live modes: **recovered 2 · lost 0 ·
winner_changed 0.** The other three need no ranker change — they are a v1
scoring artifact V2 already fixes.

**THE CLASS, NOT THE FIVE CASES.** `artifact_candidates_present_but_ranker_`
`returned_none` is now emitted where the rung used to vanish. Invariant:
every committed identity, in every live mode, either prices or names a reason.

**A 600-NAME REAL-QUERY CORPUS IS NOW THE COLLATERAL CHECK.** A diff scoped
to the 27 committed identities cannot see the query space users actually
type. It found the seam this change opened: `best_candidate` chose on FOLDED
tokens while `score_match` labelled on UNFOLDED ones, so the ranker seated
the right row and called it `estimated` — and `tool_executor` passes that
label to the pricing path. **The identity-boundary defect a third time: two
consumers of one notion, one of them updated.**

### 0.8  SPLIT V2 FROM ITS PREFERENCE  ✅ **DONE** *(Danny, 2026-08-13)*

**DO NOT PROMOTE "V2" AS ONE INDIVISIBLE THING.** It holds two behaviours of
different maturity, and freezing a baseline against the pair would sign a
transitional mistake into the record.

```text
STRUCTURAL SAFETY   folded morphology · identity/coverage gate · cross-food
                    refusal · cooked-by-default · typed artifact refusal
                    -> only ever declines a wrong row or reaches a right one
                    -> 27/27 reachable vs v1's 24/27
                    -> refuses 15 rows v1 seats; >= 8 are the WRONG FOOD
                       (asparagus for "boiled egg", shrimp for "squash",
                        tofu for "fried lamb", portabella for "grilled shrimp")

PREFERENCE POLICY   as_eaten_over_trimmed, a +/-0.4 tie-break
                    -> NOT freezable: a tie-break decides NEAR-TIES, so the
                       row it seats differs in dimensions it never evaluates
```

Margin decomposed term by term: five of the six winners V2 moves are decided
by `as_eaten` alone with every other term within 0.16.

```text
beef|fried       knuckle      -> striploin lean+fat   +123 kcal   (CUT)
beef|grilled     ribeye filet -> shoulder steak        -22 kcal   (CUT)
beef|roasted     NZ ribs      -> chuck eye roast       +44 kcal   (CUT)
chicken|fried    meat only    -> meat+skin, BATTER     +70 kcal   (COATING)
chicken|roasted  meat only    -> meat and skin         +56 kcal   (trim only)
salmon|          raw          -> cooked dry heat       +52 kcal   (STRUCTURAL)
```

**THESE ARE CUT CHOICES WEARING A TRIM RULE'S CLOTHES.** A rule named
`as_eaten_over_trimmed` must not decide knuckle vs striploin, or meat-only vs
battered, unless cut and coating are separately modelled.

`NUTRITION_AS_EATEN_PREFERENCE` + its own allowlist, **default OFF including
for the V2 allowlist**. `ranking_policy_version()` reports
`rank_v1 | rank_v2 | rank_v2+as_eaten`, so "which policy picked this row" —
the question the mode-divergence finding showed nobody could answer — is now
recordable.

**⭐ THE SPLIT RESTORED A SIGNATURE ALREADY GIVEN.** `beef|roasted` under the
preference seats chuck eye roast, unreviewed; without it, `usda:173089` — the
row a reviewer read and signed. *A signature that applies under one policy
and not another has not been kept.* Now a gate.

**NINE IDENTITIES PRICED DIFFERENTLY BY USER before this**, `beef|fried` by
**+69%** (178 fleet / 301 for user 26). Review surface collapsed from **30
mode-specific pairs to 24 canonical rows**.

### 0.85  TWO SIGNATURES, NOT ONE  *(Danny, 2026-08-13 — STANDING RULE)*

**"ADMISSIBLE EVIDENCE" AND "ACCEPTABLE CANONICAL WINNER" ARE TWO DIFFERENT
QUESTIONS.** Several rows pass the first and fail the second, and the 24-row
triage is what forced the distinction into the open.

```text
ADMISSION       "is this legitimate evidence for this food identity?"
WINNER REVIEW   "is this the representative row we want pricing to choose?"
```

**⛔ DO NOT USE `REJECT` TO COMPENSATE FOR A RANKING WEAKNESS. That would turn
a ranking-policy defect into durable semantic falsehood.** Rejecting
"Mushrooms, shiitake" because white mushrooms are the better generic would
write down that shiitake is not a mushroom — a lie, kept forever, to work
around a ranker the next fix will change anyway.

So a pair now carries TWO independent states:

```text
semantic disposition   ADMIT | REJECT | UNRESOLVED    durable, about identity
winner status          SIGNED | HELD                  provisional, about policy
```

A row can be ADMIT + HELD: valid evidence whose selection as the canonical
winner is not yet trustworthy. That is the honest encoding for every row whose
win depends on a policy known to be provisional — and it is what keeps the
semantic baseline true while the ranking regime is still moving.

### 0.9  REVIEW THE 24 CANONICAL WINNERS  ⬅ **IN FLIGHT**

Worksheet: `data/baseline/phase_1_6_canonical_winners.csv`, one regime
(`rank_v2`), no mode split. Triage complete, **nothing signed**:

```text
13  clean ADMIT
 1  UNRESOLVED     beef| — manufacturing beef, ONLY candidate; consistent
                   with the signed sibling usda:173086
 1  REJECT?        potato| -> "Potatoes, raw, SKIN" — a PART of the food, not
                   the food. Ladder holds boiled flesh 87, microwaved 100.
                   An ADMISSION defect, not a ranking one.
 3  RANKING        admissible but unrepresentative: mushrooms| shiitake 56 vs
                   white 28 · rice| glutinous 97 vs medium-grain 130 ·
                   salmon| chinook 231 vs Atlantic farmed 206
 4  LAB SAMPLE     beef|grilled, beef|fried, chicken|fried, chicken|roasted
                   all seat "meat only"/"lean only, trimmed to 0\" fat"
 2  BLOCKED        mackerel|, tilapia| — see below
```

**⛔ `cooking_yield` COVERAGE DECIDES RAW-VS-COOKED, AND DOES NOT KNOW TWO OF
THE FISH.** `_cooked_pref` fires only when `cooking_yield(query) > 1.0`:

```text
salmon 1.20 FIRES -> cooked 231      mackerel 1.00 no -> RAW 205
shrimp 1.20 FIRES -> cooked  99      tilapia  1.00 no -> RAW  96
```

Same food class, opposite outcome, decided by a table's coverage rather than
by the food. **Signing `mackerel| = raw 205` would freeze a blind spot into
the baseline** — a table's silence reading as an answer, the identity-boundary
shape again.

**DANNY'S CALLS ON THE FOUR QUESTIONS, 2026-08-13:**

```text
1  potato| raw SKIN     REJECT as evidence. A part-of-food record is not a
                        whole-potato record — an ADMISSION defect. Reject it
                        and let the ladder move on.
2  mackerel| tilapia|   ADMIT as evidence (they ARE the fish; rejecting would
                        be false semantic truth). HOLD as winners pending the
                        cooking_yield coverage/policy fix.
3  the 3 unrepresentative  ADMIT as evidence. File "specialty variant beats
                        generic representative" separately as a RANKER issue.
4  the 4 lab samples    ADMIT if same food. HOLD as winners. Signing now would
                        freeze a transitional ranking outcome already expected
                        to move.
```

**APPLIED 2026-08-13 — `scripts/winner_review.py`, 9 gates.**

```text
15 SIGNED · 11 HELD   (potato| deliberately absent, see below)
   8  as_eaten_preference_awaiting_cut_and_coating_controls
   2  cooking_yield_has_no_entry_for_this_food
   1  the only retrieved candidate is a poor representative   <- NEW CAUSE
```

**⚠ A THIRD BLOCKING CAUSE WAS NEEDED, and is flagged as an extension.**
`beef|` has exactly ONE candidate, so no ranking policy can improve it and no
admission call is owed — the row IS beef. The gap is that RETRIEVAL never
surfaced an ordinary beef row. Neither a ranking defect nor an identity
question; collapsing it into either would misfile it.

**⚠ A FIFTH ROW WAS HELD, extending the rule rather than the list.**
`beef|roasted` was not among the four lab samples because it is already
ADMITTED semantically (`usda:173089`, signed by hand) — but it IS one of the
five winners the as-eaten split reverted, so the reworked preference is
expected to move it too.

**⭐ REJECTING THE PART-OF-FOOD ROW DOES NOT PRODUCE A GOOD WINNER.** With
`usda:170032` ("Potatoes, raw, SKIN") rejected, the ladder does not fall to
boiled flesh at 87:

```text
REJECTED   58.0  usda:170032  Potatoes, raw, skin
           87.0  usda:170114  Potatoes, boiled, cooked in skin, flesh, with salt
            100  usda:170522  Potatoes, microwaved, cooked in skin, flesh, with salt
->          132  usda:170115  Potatoes, microwaved, cooked, in skin, skin with salt
                              58 -> 132 kcal  (+74, +128%)
```

`usda:170115` is flesh AND skin — a legitimate whole potato, already signed
ADMIT in the frozen 77 — so admission cannot touch it either. `potato|` is
therefore REJECT-then-HOLD: the part-of-food row leaves, and its successor is
a ranking finding. It is deliberately absent from the winner review until the
artifact is rebuilt, and `accounting()` reports that contradiction as its one
outstanding failure. **That failure is a true statement about the current
artifact, not a gap in the review.**

**⭐⭐ THE FROZEN 77 ARE NOT AMENDED.** `usda:170032` was never in the Phase
1.5 population — the consequence frontier did not reach it. Adding it to
`baseline_signatures.SIGNATURES` would change a set that was signed, gated and
closed behind `baseline_migration`, so the record would stop saying what was
signed: the same class of error as amending a pushed migration. Phase 0.9's
semantic decisions live in `winner_review.ADMISSION_DECISIONS`, additive and
attributable to their own round, with a gate pinning the separation.

**SEQUENCE FROM HERE:** reject potato skin → admit valid-but-unrepresentative
rows semantically → hold mackerel/tilapia and the 4 lab-reference rows from
the winner freeze → patch `cooking_yield` coverage/policy → rework the
as-eaten preference with **cut / coating / skin / trim controlled explicitly**
→ rerun the canonical winner sheet → sign final winners → populate → freeze →
poison → prove → close Phase 0.

**⚠ AND THE SPLIT HAS AN HONEST COST.** Switching `as_eaten` off leaves USDA
LAB SAMPLES winning on four identities — "meat only" and "lean only, trimmed
to 0″ fat" are reference samples, not meals. The preference existed for a real
reason; the defect was its ±0.4 implementation, not its goal. This argues for
REWORKING it with cut and coating controlled, not dropping it.

### 1  RAW REPRODUCIBILITY PROOF

Clean builds against identical frozen inputs, compared on the PRE-RETENTION
artifact: candidate ids, ordering, eligibility, winner, price, fingerprint.
**Retention must not be the mechanism creating agreement.**
**EXIT:** raw generation is itself reproducible.

**⚠ ORDER CORRECTED 2026-08-13: THE POISONED REBUILD IS GATE #2, NOT #1.**
The committed artifact holds **ZERO annotations** — it predates the store
(built 08-08). One UN-POISONED build must populate the full retrieved
population first; only then can a poisoned rebuild prove `resolved_this_build
== 0`, `retention additions == 0`, `raw == intended`.

### 2  PERMANENT PRICING-SPINE GATES

**ADDED 2026-08-13, and permanent:** the typed artifact refusal.
`artifact_candidates_present_but_ranker_returned_none` +
`artifact_winner_carries_no_per100g` convert a silent rung disappearance into
an observable invariant violation. Gated four ways — fires when candidates
exist and nothing wins, does NOT fire on an empty candidate list (silence is
not failure), does not fire on success, and every committed identity in every
live mode either prices or names a reason. **Keep this permanently.**

Raw reproducibility · candidate drift · destructive removal · winner drift ·
price drift · attributable change reasons · no-text reply handling ·
truncated-response handling · mackerel and other moved-key regressions.
Retention stays a SAFETY NET, never determinism evidence.

### 3  COMPLETE B-1.7a

Regenerate with the five added-fat identities, then diff all 27 existing
entries on candidate universe, eligibility, winner, price and fallback. The
fats must be ADDITIVE and existing pricing STABLE unless a change is
attributable. **EXIT: B-1.7a CLOSED.**

### 3a  ⛔ THE CANARY'S REAL FINDING — A PROVEN CAPABILITY IS NOT AN ADOPTED ONE  *(2026-08-14)*

**THE GENERAL FOOD SETTLEMENT LANE DOES NOT USE CANONICAL PRICING.** Not a
consumer bug, not a broken seam — a lane that was never built.

```text
assemble() callers        core/b1_quantity_operation.py:1486   <- exactly ONE
turns/stages/food.py      no price(), no assemble, no canonical_pricing
turns/stages/execute_native.py -> handlers.tool_executor.execute_tool_calls
```

`NativeExecutionStage` delegates to the LEGACY tool executor. So the canonical
pricing spine has exactly one door — the **B-1 quantity-clarification flow** —
and a plain "2 bananas" that never triggers a clarification never enters it,
whatever `TURN_COORDINATOR_MODE` says.

**HOW THE CANARY FOUND IT, IN TWO RUNS.**

```text
run 1  new_observe   0/6 artifact-backed   legacy ladder settled, as designed
run 2  new_execute   0/6 artifact-backed   native stages ran, canonical:create
                                           written, quantity ownership improved
                                           (150 g stayed 150 g) — and pricing
                                           still never called assemble()
```

⭐ **AND THE ONE NUMBER THAT LOOKED LIKE A PASS WAS A COINCIDENCE.** `banana`
came back at exactly 210 — the artifact's prediction. It is also `2 x 105`,
the estimator's per-banana figure, and `confidence_score` was 0.65 rather than
`_from_artifact`'s 0.85. Reporting it as a win would have been
coincidence-as-evidence. The trace resolved it: the estimator produced it.

**WHAT WAS PROVEN OFFLINE AND REMAINS TRUE.** `_artifact(entity, prep)` ->
`ArtifactEvidence` -> `price(artifact=ev)` returns **6/6 artifact-backed,
every evidence id matching the freeze exactly** — banana 210 `usda:173944`,
mackerel 305 `usda:168149`, salmon 346 honouring the stated 150 g, potato 132
with no invented preparation. The consumer is correct. Nothing invokes it.

⭐⭐ **THE CORRECTED BOUNDARY, AND IT IS THE POINT OF THIS ENTRY:**

```text
Phase 0 producer                 CLOSED
artifact / evidence build        CLOSED
canonical pricing consumer       CLOSED WHERE INVOKED
B-1 quantity-clarification path  connected and proven
GENERAL FOOD SETTLEMENT          still on the older path
GENERAL CANONICAL OWNERSHIP      NOT BUILT
```

A closure claim about the producer said nothing about adoption, and for a day
the two were conflated. **Every artifact-consumption gate written this session
passes — against a path production does not take for ordinary food.**

### 3a.1  THE NEXT SLICE — GENERAL CANONICAL FOOD SETTLEMENT OWNERSHIP

Not an ad-hoc wiring job. A deliberate slice with acceptance criteria:

```text
route ordinary food turns through canonical pricing inputs
preserve EXPLICIT quantity                    ("150g salmon" stays 150 g)
preserve or ASK preparation, never invent it  ("a potato" is not fried)
consume artifact evidence when available
POISON legacy qualification and prove the turn still settles
emit artifact provenance on the committed row (conf 0.85 · source_id · rung)
canary representative cases
only then widen to the oils
```

⭐⭐⭐ **AND THE PERMANENT RULE THIS EPISODE BUYS:**

> Every new canonical PRODUCER requires a CONSUMER-SIDE POISONED PROOF that a
> real turn actually consumes its output before the producer may be called
> production-proven.

A poisoned build proof shows the artifact can be rebuilt without a model. It
says nothing about whether any turn reads it. Those are different claims and
only the second one reaches a user.

**REVISED SEQUENCE:** freeze current Phase 0 closure → scope the general
canonical settlement slice → implement and prove it → canary → five oils →
close B-1.7a → B-1.7b.

**THE FIVE OILS ARE BLOCKED ON THIS**, and the reason is not caution: adding
oil evidence to an artifact ordinary food turns do not consume would be
building on the same conflation this entry exists to record.

### 3a.2  THE SLICE, SCOPED  *(2026-08-14. Danny: "I don't care so much about preserving the legacy path or trying to wire new architecture into the legacy path. So let's not waste time away on relinking it.")*

**DIRECTION SET: this is an OWNERSHIP TRANSFER, not an interoperation.** No
canonical call is to be threaded into `_analyze_food`, and no legacy candidate
is to be fed into `price()`. The general lane gets its own settlement owner on
the spine that already exists, and legacy keeps whatever it still owns until it
owns nothing.

#### ⚠ THE SPINE'S ADOPTION — CORRECTED TOPOLOGY *(2026-08-16)*

> **CORRECTION.** This heading read *"THE SPINE IS ALREADY THREE-QUARTERS
> ADOPTED — measured, not assumed"* and the body claimed *"`write_canonical_meal`
> already has three callers"*. **The caller count was stale and the fraction it
> implied is unsupported.** A static caller count is not an adoption measure;
> behavioural settlement paths are.

```text
owner                              writer                    pricer
api/quick_log.py                   canonical                 CLIENT-supplied macros
core/b1_quantity_operation.py      canonical                 CANONICAL (assemble+price)
ordinary chat food turn            legacy execute_tool_calls legacy _analyze_food
```

**The measured topology of `write_canonical_meal`:**

```text
ONE direct caller
  core/b1_quantity_operation.py:1591   _writer() -> write_canonical_meal

TWO paths inject it as a writer argument to commit_or_load_existing
  api/quick_log.py:215                 writer=write_canonical_meal    COMMITS
  core/canonical_shadow.py:124         writer=write_canonical_meal    NEVER COMMITS
                                       (savepoint, rollback is unconditional)
  core/b1_quantity_operation.py:1546   writer=_writer                 COMMITS
```

⭐ **SO TWO BEHAVIOURAL SETTLEMENT PATHS COMMIT CANONICALLY** — the B-1 answer
path and quick_log — **a third executes the spine and rolls it back by
construction**, and the ordinary chat food turn is legacy end to end. **Restate
adoption as behavioural paths, never as a caller count**; "three-quarters" is
not recalculated here and must not be quoted until it is.

`assemble()` still has one caller. The missing component is still not a spine, a
writer, a commit coordinator or an idempotency layer — all four are built,
proven and carrying production traffic. **It is one general settlement owner**,
the ordinary-turn equivalent of `_AnswerOperation` (B-1) and `DirectOperation`
(quick_log).

#### ⭐⭐ AND "NEVER INVENT A PREPARATION" IS ALREADY STRUCTURAL

`pricing_artifact.split_identity()` — registry-driven, no food list, no regex
identity — is the inverse of `preparation_ontology.name_with`:

```text
interpreter emits  "Chicken, fried"   ->  chicken|fried    a DIFFERENT row
interpreter emits  "chicken"          ->  chicken|         a DIFFERENT row
```

An unstated preparation produces the BARE KEY, which is a distinct artifact
entry — not a defaulted one. So Danny's "a potato is not fried" is not a rule
this slice must add; it is a property the identity boundary already has, and
what the slice owes is a GATE proving it holds on the general path too. The
interpreter's item already carries `food` as a typed field (`core/food_turn.py`
`_log_call`), which `split_identity` decomposes without asking a model anything.

#### ⛔⛔ THE ONE REAL COST, STATED BEFORE ANYONE IS SURPRISED BY IT

Legacy `fetch_candidates` RETRIEVES — live USDA, OFF, and the web meal enrich
cascade. Canonical `assemble()` retrieves NOTHING, by design: that is Gate B,
and a synchronous `price()` is the structural statement of it.

```text
food IS in the artifact (27 today)   canonical is BETTER   the migration's point
food has a user memory row           canonical is EQUAL    same user_food_matches read
food is in NEITHER                   canonical is WORSE    estimate rung, where legacy
                                                           would have found a live USDA row
```

**That third line is the entire risk of this slice**, and no amount of care in
the wiring reduces it — it is a coverage fact, not a code defect. It is also
the number this migration has never actually measured: what fraction of a real
day's food the committed artifact covers.

#### ⛔⛔⛔ THEN I MEASURED IT, AND THE MEASUREMENT DECIDES

**691 real production food entries, 30 days, 267 of them user 26.** Each name
decomposed through the SAME `split_identity` the pricer uses, then asked of the
artifact and of `user_food_matches`. No model, no network beyond one DB read.

```text
WHICH RUNG CANONICAL SETTLEMENT WOULD ACTUALLY REACH

    308   44.6%   MEMORY      (wins — it outranks artifact)
     13    1.9%   ARTIFACT
    370   53.5%   estimate rung / refuse
   ────────────────────────────────────────────────────────
    321   46.5%   EVIDENCE-BACKED
```

⭐ **THE ARTIFACT IS THE DECIDING RUNG ON 13 OF 691 ENTRIES.** It could have
priced 28 — memory already owned 15 of those and outranks it. So the whole of
Phase 0 (77 signatures, 27 winners, the poisoned rebuild, the accounting
freeze, every gate in this directive) governs **1.9% of real logged food**.
Nothing about that work is wrong. But nobody had this number, and it is the
number that decides what to build next.

⭐⭐ **AND OPTION (2) IS DEAD ON ARRIVAL.** Canonical-owns-everything with no
fallback would take 53.5% of real food to the estimate rung or to a refusal.
Not viable, not even on one account. The choice is not the one I framed.

#### THE 53.5% IS NOT RANDOM — IT IS THREE NAMED POPULATIONS

```text
210  30.4%  NON-ENGLISH   Помидор · Котлеты куриные · Капучино на обычном молоке
 68   9.8%  BRANDED       Barebells · Royo Everything Bagel · Quest Protein Chips
 53   7.7%  QUALIFIED     Salmon, pan-cooked with oil · Ground turkey, 96% lean
 39   5.6%  BARE + UNCOVERED   Eggplant · French fries · Chicken wings · Almonds
```

Each names a defect this directive has already written down, now measured live:

**NON-ENGLISH — the global-readiness invariant, violated in production today.**
The invariant says *language → interpretation*. The identity key is built from
the SURFACE STRING, so `Помидор` can never reach `tomato|` no matter how many
identities the artifact holds. **30.4% of real food, and the largest single
population by a factor of three.**

**BRANDED — a rung with no producer.** `Rung.PRODUCT` exists, ranks second, and
`assemble()` hard-codes `"product": None`. It has never had a producer. This is
the population that should never be artifact rows at all — a Barebells bar is a
label, not a food identity.

**QUALIFIED — `split_identity`'s vocabulary is THREE WORDS: fried, grilled,
roasted.** "pan-cooked", "steamed", "boiled", "scrambled", "baked" are not in
it, so the qualifier stays glued to the entity and builds a key nothing can
reach. This is the identity-boundary defect class of 2026-08-10 at a new site,
and the fix is registry extension, not code. ⭐ `White rice` misses while bare
`rice|` HITS — so the boundary problem is modifiers generally, not preparation
specifically.

**⭐⭐⭐ ONLY 5.6% IS WHAT "ADD MORE ARTIFACT IDENTITIES" FIXES — WHICH MEANS
THE FIVE OILS ARE NOT THE HIGHEST-VALUE NEXT TRANCHE, AND THIS MEASUREMENT IS
WHY.** Oils live in the 5.6% bucket. Landing all five moves real coverage by
well under one point, while the interpretation boundary sits at 30.4%
unattended. The oils were sequenced next when the only visible axis was
artifact quality. That is no longer the only visible axis.

#### THE DECISION, RESTATED HONESTLY

Canonical settlement can own the turns it has evidence for — **46.5% today,
memory-dominated** — and that is a real and defensible first tranche. It cannot
own the rest, and no wiring decision changes that. So:

- the slice ships behind a **coverage predicate**, because the measured
  alternative is refusing half of real food;
- the predicate is a **typed pre-settlement routing decision**, not a canonical
  call threaded into `_analyze_food` — which is what Danny's steer rules out;
- and the predicate's miss rate is **emitted as telemetry from day one**, so
  the cliff stays measured rather than rescued invisibly.

⚠ NOTE THE HONEST LIMIT OF THIS MEASUREMENT: it approximates `_memory()`'s
lookup (`normalize_name` on the composed name) rather than executing it, and it
counts entries rather than turns. It is a scoping instrument, not a gate.

#### ACCEPTANCE CRITERIA — ✅ AMENDED AND IN FORCE *(P4, 2026-08-16)*

> **A6 and A7 are AMENDED; A2 and A11 are new. The originals are struck below**,
> because A6 as first written would have forced every settlement to report
> `rung=artifact` and put it in direct conflict with A10.

```text
A1  a general settlement owner exists on ResolvedMeal -> commit_or_load_existing
    -> write_canonical_meal, and it is the ONLY thing NativeExecutionStage
    invokes for structured_food under the lane flag
    ⛔ the seam to displace is `execute_native.py:55`, which today imports
       `execute_tool_calls` from handlers.tool_executor

A2  it prices via assemble() + price() and imports nothing from
    handlers.tool_executor — gated by an import/AST assertion, not by reading
    ⭐ AMENDED — the boundary A2 asserts against is now DRAWN, below. Do not
      import `_analyze_food` (handlers/tool_executor.py:2963) and do not
      reproduce its enrichment inside the owner. Canonical idempotency REPLACES
      legacy dedup for canonical writes; the old executor must not survive as a
      hidden second settlement owner.

A3  an EXPLICIT quantity survives settlement unchanged   ("150g salmon" -> 150 g)
A4  an UNSTATED preparation produces the BARE key       (potato| never potato|fried)
A5  a STATED preparation produces the composed key      (both routes -> one key)

A6  ⭐ AMENDED. PROVENANCE MUST IDENTIFY THE RUNG THAT ACTUALLY DECIDED THE
    PRICE — whichever rung that is — read from the DB, never from reply text.
    The artifact case is forced by a FIXTURE, never by bending precedence:
        memory ABSENT · artifact PRESENT and ELIGIBLE · artifact must WIN
        · persisted provenance reports `artifact` · evidence_id · confidence 0.85
    Separate fixtures prove MEMORY and prove REFUSAL.
    ~~was: the committed row carries artifact provenance rung=artifact~~
    ⛔ that phrasing demanded every settlement report the artifact rung, which
       A10 then has to contradict to measure anything.

A7  ⭐ AMENDED — CONSUMER-SIDE POISONED PROOF, WITH A BOUNDARY. Poison the
    SETTLEMENT-side seams only (USDA qualification · legacy executor enrichment
    · resolver fallback), never interpretation's own identity work. Full
    sequence below. The poison is VERIFIED TO BITE before its silence counts.
    ~~was: with ... the resolver ... poisoned to raise~~
    ⛔ a GLOBAL resolver poison kills the pre-settlement identity work the turn
       needs to produce a structured item at all, so the proof would pass by
       never reaching settlement.

A8  a food in neither artifact nor memory REFUSES rather than committing a
    number no evidence backs, and the refusal writes no row and no ledger event
    ⭐ and `PricingRefused` (core/canonical_pricing.py:128) PROPAGATES once
      canonical routing has begun — it may not cross back into legacy settlement

A9  the six canary identities are pre-registered OFFLINE with their expected
    evidence_ids, THEN observed in production — a matching calorie number is
    NOT provenance (banana 210 = 2x105 taught that at a cost)

A10 coverage measured and RECORDED: of one real day of food, how many items
    reached an evidence-backed rung

A11 ⭐ NEW — THE COVERAGE PREDICATE IS PURE AND PRE-SETTLEMENT, and its miss
    rate is emitted as telemetry from day one. Contract below.
```

A9 and A7 are the two that could not have been written before this week: A9
because a coincidence nearly passed for a proof, A7 because a producer proof
was mistaken for an adoption proof.

⚠ **WHAT STILL GATES IMPLEMENTATION.** The contract is now decidable, so A1–A10
may be built once the plan is approved (**P5**). **A11 and A10 additionally wait
on P2**, because a coverage predicate cannot be tuned against a coverage number
that does not exist.

#### ✅ THE CONTRACT DECISIONS — DECIDED AND IN FORCE *(P4, 2026-08-16)*

> **Status: IN FORCE.** Recorded as recommendations under P0, decided here.
> Every symbol named below was verified to exist before it was written as
> contract.

**A — WHAT THE CANONICAL OWNER OWNS.** ✅ **DECIDED.** *(A2 is an import
assertion and could not be written against an undrawn boundary. This is the
boundary.)*

```text
GeneralSettlementOwner owns        typed canonical routing · assemble() · price()
                                   ResolvedMeal construction · exactly-once claim
                                   canonical persistence · pricing provenance
                                   canonical ledger event · typed refusal propagation
shared post-settlement owns        card construction · rendering
                                   conversation acknowledgement · read-model formatting
legacy owns                        legacy-routed settlement, and nothing else
```

⛔ **Do not import `_analyze_food` into the canonical owner and do not retain its
enrichment behaviour there.** Canonical idempotency **replaces** legacy dedup for
canonical writes; the old executor must not survive as a hidden second
settlement owner.

**B — THE STALE CALLER COUNT.** Corrected above in this section. The adoption
claim is restated around behavioural paths; "three-quarters adopted" stays
unquoted until recalculated against the real topology.

**C — A6 VERSUS A10.** ✅ **DECIDED — A6 IS AMENDED ABOVE.** As first written it
required the committed row to carry `rung=artifact`, which would force every
settlement to report the artifact rung and put it in conflict with A10's
coverage measurement.

```text
CORRECT CONTRACT   provenance must identify the rung that ACTUALLY DECIDED
                   the price — whichever rung that is
ARTIFACT PROOF     forced by a FIXTURE, not by bending precedence:
                     memory absent · artifact present and eligible
                     artifact must win · persisted provenance reports 'artifact'
SEPARATE FIXTURES  one proves memory · one proves refusal
```

⛔ **Do not manipulate normal rung precedence merely to satisfy A6.**

**D — THE COVERAGE PREDICATE.** ✅ **DECIDED — this is A11.** A **pure,
pre-settlement routing check**. ⚠ Its THRESHOLDS wait on P2: the contract is
decided, the miss rate it is tuned against is not yet measured.

```text
MAY READ    canonical identity eligibility · local artifact availability
            eligible memory availability · required quantity/identity completeness
            rollout cohort
MUST NOT    call assemble() · call USDA, web retrieval or the resolver
            price the meal · write state · claim idempotency
            fall back after a canonical write has begun

RESULT      Supported(expected_source, reason) | Unsupported(reason)
ROUTING     unsupported -> untouched legacy path
            supported   -> canonical owner
```

⛔ **Once canonical routing begins, `PricingRefused` PROPAGATES.** It may not
silently cross back into legacy settlement — that re-creates the second
settlement owner this slice exists to remove.

#### ✅ A7 — THE POISON BOUNDARY SEPARATES INTERPRETATION FROM SETTLEMENT *(DECIDED, P4, 2026-08-16)*

⛔ **A GLOBAL RESOLVER POISON WOULD INVALIDATE THE PROOF**, because it also kills
the legitimate pre-settlement identity work the turn needs to produce a
structured item at all. The poison must target the dependencies canonical
settlement is **forbidden to use**, and nothing the interpretation boundary is
**required** to use.

```text
1  pre-register an artifact-addressable identity
2  prove each poisoned dependency RAISES when called directly   (the bite)
3  enter through a REAL user turn
4  let the normal interpretation boundary produce the structured item
5  poison the SETTLEMENT-SIDE seams only:
     USDA qualification · legacy executor enrichment · resolver fallback
6  confirm canonical settlement succeeds FROM THE ARTIFACT
7  confirm provenance and committed macros came from the artifact
8  confirm poison call counts remain ZERO during canonical settlement
```

Step 2 is not optional: **a poison must be proven to bite before its silence
counts.**

### 3a.3  ⚠ THE CARD GAP BELONGS TO THE NATIVE RENDERER *(measured 2026-08-16)*

**A native turn renders NO CARD, whoever settles it.** `NativeRenderStage.run`
returns `Response.from_text(text)` — text only, by construction.

```text
non-native + legacy      meal_commits 0   cards 1
native     + legacy      meal_commits 0   cards 0    <- the CONTROL
native     + canonical   meal_commits 1   cards 0    rungs ['artifact']
```

⛔⛔ **AND THE FIRST VERSION OF THIS FINDING WAS WRONG, IN A WAY WORTH KEEPING.**
It read *"legacy renders 1 card, canonical renders 0"* and blamed general
settlement. That comparison changed TWO variables at once — the first arm was
non-native AND legacy. **The control arm is the only thing that separated
them**, and without it this slice would have acquired a defect it did not
cause, and someone would have "fixed" the settlement owner.

⭐ **WHAT THE SLICE DOES OWE, AND NOW DOES:** the canonical branch publishes an
`ExecutionResult` (`general_settlement.execution_view`). Without it
`affected_entities(None)` is empty, so the snapshot has no committed
operations — every consumer of the execution view, not only the card, sees an
empty turn. That is fixed regardless of who fixes the renderer.

⚠ **STILL OPEN, NAMED:** `write_canonical_meal` records the ledger event but
does not return its id, so `ledger_event_ids` is empty for a canonically
settled turn and **no undo token can be surfaced from it**. That belongs with
B-1.8's correction work.

**The card is a COORDINATOR-MIGRATION blocker, not a settlement blocker.**

⭐ **DEFERRED TO A LATER PHASE BY DECISION** *(Danny, 2026-08-16)*. It was
previously written here as gating the canary. It does not: the canary runs on a
single test account that knows the card is missing, and the turn still logs
correctly with a real text reply. **It returns as a blocker before the cohort
widens beyond one informed user** — a correct settlement that renders no usable
card is still a product failure for anyone who did not opt into watching for it.

### 3a.4  ⛔ THE ROUTE IS NOT THE WRITER *(P11b, 2026-08-16)*

`ledger_events.source` names the **mutation lane and its owner** —
`canonical_writer` says so in as many words: *"`ledger_source` names the mutation
LANE and its owner (`canonical:create`, matching the existing
`structured_food:*` / `legacy:ios` / `quick_log:ios` convention)"*.

The first coverage instrument read it as the ROUTE: `startswith("structured_
food")` else legacy. That is an inversion with a fuse in it — `write_canonical_
meal` emits `canonical:create`, so **a structured-routed turn settled
canonically counts as a routing failure, and ADOPTION DRIVES THE MEASURED
ROUTING RATE DOWN.**

⛔ **AND IT WAS ALREADY FIRING.** 36 of 406 rows in the window are
`canonical:create` (the B-1 answer path, every one carrying a `chat_quantity`
operation id). Corrected:

```text
                 first published    corrected
A  routing              66.7%         81.0%
B  support              42.3%         45.6%
C  ownership            28.2%         36.9%
artifact as expected rung   1            12
```

The artifact moved most, because the misfiled meals were exactly the answered
ones that reach it.

⭐ **THE DENOMINATOR IS ORDINARY FOOD-CHAT MEALS.** `quick_log:*` and
`dashboard:*` are not chat turns; counting them as turns that failed to reach
the lane blames the lane for traffic that never went near it. An unrecognised
writer is reported as its own bucket rather than binned as legacy.

⚠ **THE HONEST LIMIT: A IS STILL WRITER-DERIVED**, because no per-meal routing
record is persisted. `canonical:*` counts as structured-route on the strength of
those operation ids. **If quick_log or the general settlement owner later emit
`canonical:create` too, this proxy needs the operation id to disambiguate them**
— and it will, the moment P12 ships.

### 3a.5  ⛔⛔ WHAT THE CANARY FOUND — FIVE GATES, AND TWO BROKEN CONTRACTS *(2026-08-16)*

**Four iOS turns. The settlement owner worked; the eligibility contract did
not.** A useful late-stage canary result, and exactly what one test user is for.

#### THE FIFTH GATE: THE ENTRYPOINT, AND IT IS CHANNEL-DEPENDENT

```text
iOS       api/chat.py -> chat_service.run_chat_turn -> the coordinator   ✅
Telegram  bot/telegram_handler.py:445 -> core.conversation.run_turn      ⛔ never
```

The first two canary turns were Telegram and looked like silent failure with
every flag correct. **The four gates in §3a.3 are not sufficient; the entrypoint
comes first.** A canary on a channel that cannot reach the coordinator proves
nothing, and reads exactly like a canary that fired and declined.

#### C1 — PRICEABILITY: A11 ASKED THE WRONG QUESTION

`"I had a corn on the cob"` had BOTH a memory row and an estimate, and canonical
settlement REFUSED it: `1 medium` carries no gram mass, every canonical rung is
per-100g, `scale_profile` declines each and `refuse_or_return` raises.
`PricingRefused` propagated (A8), the turn died, and the user got *"Lost the
thread there"* — **while legacy had logged the identical message hours
earlier.** A regression.

**A11 is amended: the predicate answers "can this meal be PRICED", not "does
evidence exist".** `look()` computes mass with the same `normalize_quantity`
settlement uses, so the two cannot disagree.

#### C2 — ADMISSIBILITY: LEGACY SURFACE MEMORY IMPERSONATING CANONICAL EVIDENCE

⚠ **AND THE MASS FIX DOES NOT TOUCH THIS.** `"1 banana"` -> 118 g IS scalable.
Canonical addressed a memory row of 312 kcal/100g and committed **368 kcal
where legacy priced 105**. Two independent defects.

```text
'banana' -> fdc 2012128  312 kcal/100g   on FOUR accounts (2, 26, 78, 108)
'bananas'-> fdc 173944    89 kcal/100g   the real USDA banana
both: confidence=exact · origin_tier=generic_exact · user_confirmed=false
```

⛔ **CONFIDENCE AND TIER CANNOT DISCRIMINATE** — both rows claim `exact`.
`user_food_matches` records NO canonical identity: a row is keyed by a lossy
surface normalization, so it is evidence about a STRING, not about the identity
being priced.

**THE INVARIANT — agreement between authorities, never plausibility:**

> A legacy surface-key row may participate in canonical pricing only when its
> authority is structurally unambiguous. Bindings that assert the SAME per-100g
> numbers are one authority re-cached; bindings that assert DIFFERENT numbers
> are competing, and a competing address cannot be authoritative for anybody.

⭐ **CHARACTERIZED BEFORE IT WAS WRITTEN**, as Danny required: `<oil>` 800.0 vs
800.0 is a history duplicate; `tomato` 71 vs 302 and `white rice` 97 vs 333 are
competing authorities. Exact agreement, no tolerance — **a threshold is where
nutrition judgement gets smuggled in.**

⭐⭐ **FLEET-WIDE, NOT PER-USER.** The collision is a property of the ADDRESS.
A per-user test would clear the three accounts whose only banana row is the bad
one.

⭐⭐⭐ **THE RUNG ABSTAINS; THE LADDER DOES THE REST.** It does not pick a
binding, average them, or fail the meal. For `banana`: memory abstains ->
ARTIFACT `usda:173944` -> **105 kcal, verified against production data.**
Nothing about pricing was redesigned.

⚠ **READ-TIME QUARANTINE, NOT DELETION.** No historical memory is rewritten in
this slice; the rows stay as evidence for a later migration onto canonical
identity.

**MEASURED DELTA:** 28 ambiguous keys · 78 of 836 rows (9.3%) · 28 recent turns
(21d) sit on one. Query cost is an indexed bitmap scan — the 116 ms first
measured was this laptop's network round-trip (`SELECT 1` costs 232 ms on the
same link), not the query.

#### C3 — THE NATIVE PATH NEVER BOUND `CURRENT_TURN_ID`

`core/conversation.py:927` binds it for legacy; the coordinator path did not, so
every canonical write landed with `turn_id = NULL` — losing the correlation key
the corpus repair and the coverage instrument are both built on. Bound in
`core/turns/entrypoint.run_turn`, reset in `finally`.

#### THE PREREG'S STOP CONDITIONS WERE INCOMPLETE

Neither **a mispricing** nor **a turn that logs nothing** was on the list, and
both happened. Both are now stop conditions.

### 3a.6  ⛔⛔ A TURN THE NATIVE LANE CANNOT EXECUTE MUST NOT BE SWALLOWED *(P14/1, 2026-08-16)*

**Measured in production.** `"I had a corn on the cob"` reached the native lane,
the interpreter produced NO log operation, and the turn was lost:

```text
NativeExecutionStage.run   ops empty  -> return None
NativeRenderStage          nothing committed -> returns None
_result_from_state         response is None -> Response.from_text("")
delivery                   empty reply -> "Lost the thread there."  NO ROW
```

Legacy had logged the identical message hours earlier. Ground turkey took the
same DECLINE path the same minute and succeeded, because the interpreter
produced an operation for it — so this is not the coverage predicate and not
settlement. **The native lane simply has no path back when it produces no plan.**

⭐⭐ **AND THIS IS NOT THE A8 FALLBACK.** A8 forbids reaching legacy AFTER
canonical settlement has begun, because that is two settlement owners for one
meal. Here `state.execution is None` means the execution stage returned before
taking any claim and before any canonical write — **nothing was settled and no
ownership transferred.** The line A8 actually draws:

```text
no plan, nothing settled         -> legacy runs the turn        ALLOWED
canonical settled then refused   -> propagate, never legacy     FORBIDDEN
an empty response reaching delivery                             IMPOSSIBLE
```

⚠ **AN ASK IS NOT AN EMPTY TURN.** A clarification legitimately has a response
and no execution, so the response is checked too — delegating one would ask the
user the same question twice. Both directions are gated.

⛔ **THIS IS THE CURRENT STOP CONDITION FOR WIDENING**, together with the card
(§3a.3). A settlement that is correct and a turn that silently loses food are
not offset by each other.

### 3b  THE TRANCHE CANARY — A RELEASE GATE, NOT A SMOKE TEST  *(Danny, 2026-08-14)*

Production is **32 commits behind** and this tranche changed the ARTIFACT, the
SEMANTIC STORE and the BUILD PATH. A generic smoke test would exercise none of
what actually moved, so the canary targets the invariants most likely to have
been disturbed — and it is a GATE: the five oils do not start until it passes.

```text
DEPLOY the tranche, then exercise LIVE:

  morphology / identity normalization     banana · potato · eggs — the
                                          singular/plural fold that made five
                                          identities reachable at all
  quantity clarification + repricing      B-1's slice, answered and repriced
  preparation clarification               B-1.5's independent material fields
  canonical pricing from the artifact     an artifact-backed settle, confirmed
                                          from the DB and not from reply text
  mechanical refusal / fail-closed        a base-food mismatch, a cooking-state
                                          conflict — refused BEFORE the model
  one known HELD ranking case             mackerel| or egg| — production must
                                          seat WHAT THE FREEZE SAYS IT SEATS
  one human-reviewed REJECTION            usda:170032 must not reappear; a
                                          rejected row staying rejected is the
                                          symmetry rule proven in production
```

**CONFIRM AFTER:** deployed SHA via `/health.commit` · the artifact hash the
deployed build is reading · telemetry showing the canonical lane took the
turns. Flags stay conservative — `NUTRITION_ACCURACY_V2` on its allowlist,
`NUTRITION_AS_EATEN_PREFERENCE` off fleet-wide. **No flag widening during the
canary.**

⭐ THE POINT: the frozen accounting is a claim about what production does.
Until production is observed doing it, that claim is local.

### 3c  THE FIVE OILS — THE REGENERATION STANDARD

> The five oils may ADD evidence. They may NOT silently alter existing
> production pricing. **Any movement in the existing 27 is a FINDING, not
> expected regeneration noise.**

This is the same standard the seam rebuild already met — 27 -> 27, six ladders
grew, zero lost, zero unexplained — and it is the reason that rebuild was
interpretable at all. A regeneration that shrugs at moved winners is a
regeneration nobody can audit.

Every delta in the existing 27 must classify as `retrieval | mechanical |
semantic | source`, exactly as the seam rebuild's did, and any signature whose
candidate universe moves expires as UNVERIFIED and is re-reviewed rather than
re-derived.

### 4  B-1.7b — MATERIALITY / CLARIFICATION POLICY  *(rewritten 2026-08-14)*

**PURPOSE: decide whether an unresolved food attribute is important enough
that Arnie must ASK before pricing. It is NOT another ranking project.**

> If plausible interpretations of an unresolved attribute can produce a
> MATERIALLY DIFFERENT nutritional result, Arnie must resolve that attribute
> before settlement. If the consequence is immaterial, Arnie may proceed
> without asking.

⭐ **THREE QUESTIONS THAT MUST NEVER BE CONFLATED**, and the 08-14 winner
review is what forced them apart:

```text
IDENTITY        is this legitimately the food?           -> admission
REPRESENTATIVE  which admissible row would pricing pick? -> ranking
MATERIALITY     is the uncertainty important enough that Arnie should ASK
                rather than accept that representative?  -> B-1.7b
```

⭐⭐ **AND THE MOST IMPORTANT RULE THIS PHASE PRODUCED:**

> **THE EXISTENCE OF A RANKER WINNER MUST NEVER ITSELF PROVE THAT
> CLARIFICATION IS UNNECESSARY.**

A ranker can always produce a winner. That says nothing about whether the
question it silently answered was worth asking.

#### THE TWO PERMANENT ACCEPTANCE FIXTURES

Both are real, both are in the frozen accounting as ADMIT + HELD, and both
exist because the system could settle them silently and should not.

**`egg|` — the acceptance case.** "2 eggs" leaves preparation unresolved, and
the plausible outcomes span boiled/poached against fried/scrambled/omelet with
materially different nutrition. Bare `egg|` must not settle merely because the
ranker can seat omelet at 154. The policy should activate a preparation ask —
*How were they prepared? Boiled · Fried · Scrambled · Poached* — after which
canonical identity becomes preparation-specific and pricing proceeds normally.

**`mackerel|` — the consequence case.** Bare `mackerel|` currently exposes
**raw 205 vs salted 305 — ~49%**, and the ranker seats salted for no reason
but that "salted" is a shorter lexical match to a bare query.

⛔ **THE CORRECT CONCLUSION IS NOT "make raw always outrank salted".** It is
that the unresolved state/form is MATERIALLY CONSEQUENTIAL, so bare
`mackerel|` cannot silently inherit a specialty representative when that
choice materially changes nutrition. Arnie either asks the appropriate
clarification or deterministically refuses that specialty representation as a
safe default.

#### WHAT 1.7b BUILDS

1. A DETERMINISTIC definition of material nutritional difference across
   plausible admissible interpretations.
2. Attribute-level consequence evaluation: preparation, added fat, state/form,
   quantity, and every other activated field.
3. Typed outcomes — `ASK` · `SAFE_TO_ESTIMATE` · `ACCEPT` · `REFUSE`.
4. A deterministic explanation of WHY an attribute became necessary.
5. NEGATIVE invariants proving Arnie does not ask unnecessary questions.
6. POSITIVE invariants proving materially consequential ambiguity cannot
   silently settle.

**MATERIALITY IS LOCALE- AND SOURCE-INDEPENDENT** (global-readiness invariant):
"did this added fat materially affect nutrition?" is a FOOD-DOMAIN policy
question, never a USDA or English-text one.

#### EXIT

> For every unresolved pricing-relevant attribute, Arnie deterministically
> knows whether the uncertainty is materially consequential, and materially
> consequential ambiguity cannot reach settlement without resolution or an
> explicitly safe policy.

Then B-1.7c handles the COMPOSITION consequences of those answers — added oil
becoming a second food contribution rather than a multiplier.

**SEQUENCE:** finish current closure → five oils → B-1.7a CLOSED → **B-1.7b**
→ B-1.7c composition.

### 4b  B-1.7b — ORIGINAL MATERIALITY NOTE *(superseded above)*

Deterministic policy over nutritional impact, confidence, preparation impact,
added-fat significance: ask vs estimate vs accept vs refuse.
**EXIT:** Arnie asks only when uncertainty materially affects trustworthiness.

### 5  B-1.7c — COMPOSITION / ADDED-FAT PRICING

Added fat as a SECOND TYPED FOOD CONTRIBUTION, never a phrase heuristic. No
return to legacy tables. **EXIT:** preparation and added-fat effects compose
through canonical pricing.

### 6  B-1.8 — ANSWER / REPAIR

Correction · edit · delete · undo · stale answer · repeated correction ·
multi-field repair · post-settlement repair.
**EXIT:** every canonical food write can be safely repaired.

#### ⛔ CARRIED IN FROM THE 08-15 CANARY — CANONICAL ROWS CANNOT BE CORRECTED YET

> **Canonical-created food rows cannot yet be corrected through the ordinary
> interpretation path.** *(observed live, user 26, turn `telegram:9350`)*

```text
19:07:14  interpreter_output action=update updates=[{entry_id:2992, 200g}]
19:07:14  correction_apply outcome=applied route=ratio ratio=1.149 cal=329.9
19:07:14  ERROR cross_owner_mutation_refused entry=2992
                owner=canonical:create authority=inferred_interpretation writer=None
19:07:16  tools=update_food_entry:error flags=tool_error voice_profile=recovery
```

⭐ **THE FIREWALL DID EXACTLY WHAT IT IS FOR** *(Danny, 2026-08-15)*. Entry 2992
was written `canonical:create` by B-1; the update arrived carrying
`inferred_interpretation` authority, and an authority mismatch on a canonical
row is precisely what it must refuse. **Do not reopen the ownership firewall.**

⚠ **WHAT IS MISSING IS A CANONICAL CORRECTION PATH** — one that takes an
ordinary interpreted correction and translates it into an AUTHORIZED mutation.
That is this section's work, not the interpretation boundary's. The user-visible
cost meanwhile is a recovery bubble on a perfectly reasonable correction, so it
is a real defect with a real owner, deliberately not fixed where it was found.

### 7  B-2 — REAL MULTI-FOOD MEALS

Restaurant meals · mixed dishes · bowls · sandwiches · sauces · leftovers ·
partial portions · several foods in one turn.
**EXIT:** normal human meals reliably resolve into canonical state.

### 8  PROMOTE B AND DELETE LEGACY

canary -> rollback proof -> promote -> delete legacy writers -> delete
duplicate semantic owners -> delete obsolete flags. **This is the actual end
of B.**

### THEN C · D · E · F

```text
C  CONVERSATION      one voice across deterministic and semantic routes. The
                     "two voices" problem is fixed HERE, after correctness is
                     frozen, not before.
D  PERSONALIZATION   history REDUCES questions — usual portions, preparations,
                     brands, restaurants, meal patterns
E  COACHING          canonical history -> interpretation: what happened, what
                     matters, what to do next
F  PROACTIVE AGENCY  when to intervene, when to stay silent, what is most
                     useful
```

**THE WHOLE ORDER, ONE LINE:** authority migration -> raw reproducibility ->
permanent gates -> five fats + 27-entry diff -> B-1.7a -> B-1.7b -> B-1.7c ->
B-1.8 -> B-2 -> promote/delete legacy -> C -> D -> E -> F.

## End goal

Arnie's backend should converge on one production architecture:

```text
human input
→ domain interpretation
→ canonical unresolved/resolved domain state
→ semantic clarification fields
→ typed answer patches
→ one PendingOperation
→ one canonical commit
→ one persisted result
→ presentation from committed truth
→ durable downstream work
```

The target is not merely "better clarification." The target is:

* no direct food writes outside the canonical writer,
* no client-derived chip meaning,
* no question-text parsing to recover semantics,
* no broad interpreter treating clarification answers as new meals,
* no competing pending stores,
* no partial meal topology created by accuracy mode,
* no narration before authoritative commit,
* no duplicated card/totals logic,
* and no clarification adapter with permanent tenure.

Food is the reference implementation. Workouts adopt the shared operation
spine only after food proves it.

## The slice loop — and what "done" means

**Augmented 2026-08-06 from team review.** A slice is not finished when its
lifecycle works. It is finished when its predecessor is gone.

```text
measure → freeze → build canonical path → gate → validate
→ promote → DELETE PREDECESSOR → LOWER RATCHET
```

The last two steps are the ones that get skipped, and skipping them is how the
four legacy clarification producers happened the first time: each was a
canonical path that shipped without removing what it replaced.

**Promote and delete per family, continuously.** Do not build every remaining
slice and postpone promotion to the end — that recreates a second large
migration branch whose assumptions go untested for months. Each field family
promotes and deletes its own predecessor independently.

**The goal is a repeatable loop, not heroics.** The first slice was expensive
because it had to invent the operation model, ownership rules, revision
semantics, answer routing, replay protection, commit coordination, failure
handling, provenance, presentation facts, lifecycle tests, production probes,
telemetry and ratchets. Later slices reuse nearly all of it. The measure of
success is when a slice takes **days to implement rather than weeks to
invent**.

## Presentation rides behind each slice — it is never the next phase

Voice, formatting and diction are a **controlled presentation layer**, not a
milestone. They sit strictly after the persisted-result boundary:

```text
interpretation → canonical state → typed clarification → PendingOperation
→ canonical commit → persisted result → PRESENTATION FROM COMMITTED TRUTH
```

**There are two distinct wording passes and they must not be confused.**

| | when | what it is | constraints |
|---|---|---|---|
| **Instrumentation wording** | inside every slice | make the question unambiguous and the routes visible so the slice is MEASURABLE | fixed · minimal · versioned · same QuestionIntent, options and patches · no dynamic LLM diction |
| **Product voice** | **B-2.8** | make it genuinely Arnie | adaptive · contextual · channel-aware · still facts-constrained |

Instrumentation wording is measurement hygiene: the phrasing directly affects
the metric being evaluated, so it must be settled *before* evidence
collection, and version-stamped so a later change stays comparable. It is not
permission to start the voice project.

**Why product voice waits for B-2.8.** The renderer needs stable semantic
intents to express — a question, an assumption, an uncertainty, a disclosure,
a repair, a confirmation. Those intents are not stable until B-1.6 fixes
dependency ordering and B-1.7 fixes accuracy policy. Diction written before
then gets rewritten. At B-2.8 the renderer owns sentence structure, tone,
contractions, channel length, splitting, emphasis and the deterministic
fallback — and never owns which field is unresolved, which options are valid,
what an option means, whether an assumption occurred, or whether the meal
committed.

**Output consolidation belongs to C-4, not to any slice.** `MealCommitResult →
CanonicalResponseFacts → copy` is the first safe boundary and is deliberately
narrow. One `PresentationSnapshot` feeding chat, card, day totals, timeline,
coach feed, notifications, widgets and API payloads is C-4's authority.
Polishing chat prose while cards and totals still have separate factual owners
is how screens come to disagree.

**The rule for the team:** every slice ships a presentation adapter; no slice
runs a broad voice redesign.

## Measure before generalize

**No clarification generator, candidate source, interaction pattern or UX
refinement expands until production telemetry demonstrates where users actually
succeed or fail.**

Adopted 2026-08-06, at the point B-1 stopped being an architecture question and
became a product one.

**Multiple defects in this slice shipped green because fixtures encoded
expected states without exercising naturally occurring production sequences**
— the ask origin, the ambiguity field name, the settled and expiry windows.
**Others exposed different gaps**: contradictory ownership of the quantity
(the stale macros), a renderer substituting its own question, observability
that could not report what it appeared to measure, and database parity between
models and migrations that nothing compared. **Both classes require
sequence-level production evidence before expansion**, which is what this rule
buys. Generalising an option generator without it would repeat the failure at
a layer where the cost is a user's trust rather than a test run.

Its first application is the **B-1 production-evidence ladder (B-1b)**:
B-1's option pipeline does not widen until the evidence says which candidate
source actually produces answers people accept and do not correct. Note what
the rule does NOT say — it does not require that evidence to be organic. Class
matters, not provenance: deterministic behaviour is proven deterministically,
and only natural preference requires natural traffic. It is deliberately labelled inside B-1 — it
is not Phase D work, and naming it `D4.1` implied Phase D was starting before
B-1 closed.

The rule binds the instruments too. An observation window read from
`core/trace_buffer` would be a window over "since the last deploy" — it is a
`deque(maxlen=2000)` in process memory, shared across every watched event, and
production measured **zero lines** minutes after a deploy with its dropped
counter reset alongside. Telemetry that decides a roadmap lives in a table.

## Standing constraints

These remain in force throughout the migration.

### Ownership

One owner per responsibility:

```text
resolver               → produces evidence
ambiguity engine       → identifies unresolved semantic fields
policy                 → decides ask / assume / defer / disclose
option generator       → produces valid semantic answer candidates
renderer               → produces human-facing wording and labels
answer application     → applies typed patches
domain writer          → mutates storage
presentation builder   → renders committed truth
```

No layer may silently re-own another layer's responsibility.

### Migration discipline

Every migration slice follows:

```text
measure → freeze → build canonical path → shadow or gate → validate
→ promote → delete predecessor → lower ratchet
```

Do not leave old production ownership available "just in case."

### Transaction rules

* One reported meal normally produces one operation and one commit.
* No user-facing success before commit.
* Duplicate delivery returns the persisted original result.
* Pending revisions are durable.
* Durable downstream work uses the transactional outbox.
* Best-effort cache or UI work remains post-commit.
* Accuracy mode changes policy, never storage topology.

## Current position

Already complete:

```text
Phase A
✓ quick-log canonical writer
✓ direct quick-log writer deleted
✓ production verification complete
✓ typed nutrition provenance
✓ canonical commit/replay path
✓ durable outbox split
✓ clarification producers frozen by C8 (and option producers by C9)
✓ B-0b semantic contract surface implemented and test-locked
✓ B-0c persistence, round-trip, validation and immutability hardened
```

The next work begins at B-1.

*(Superseded by events — kept for the construction/storage distinction below.
As of 2026-08-11: B-1 and B-1.9 are production-proven on iOS, B-1.5E has
landed, the P1 canonical pricer is CLOSED in production, and B-1.5 is blocked
on a deliberate canary exercise rather than on engineering. The authoritative
"where are we" is the Status board. This section is history, not position.)*

**PHASE STATE — 2026-08-11, reconciled after the B-1.5/B-1.6 session.**
Percentages are Danny's scoring, recorded so "nearly done" never stands in for
a measurement:

```text
P1 pricing seam / performance          100%   CLOSED in production
P1(b) canonical ownership firewall     100%   CLOSED, fired 3x in production
B-1.5 clarification lifecycle          100%   CLOSED — canary 5 passed, F N/A
B-1.6 conditional field lifecycle      100%   CLOSED — a/b/c, end to end
Canonical identity boundary            100%   key AND ranker, both consumers
B-1.7 accuracy policy                    0%   (was NEXT; see §NEXT)
Added-fat COMPONENT pricing              0%   blocked on ADDED_FAT_IDENTITY
Interpreter extraction survival          0%   ~1-in-3 loss measured -> B-1.7
```

**SEQUENCING FROM HERE *(2026-08-11)*.** Everything above the line is done and
production-verified; everything below is the open path to promotion:

```text
   ---------------- closed ----------------
 . P1      canonical pricer, settle 36-70 ms vs 8,225-11,053 legacy
 . P1(b)   ownership firewall, capability-based, UNKNOWN default-refused
 . B-1.5   one item, multiple independent material fields
 . B-1.6   conditional activation: a engine+lock, b producer, c seam
   ---------------- open ------------------
 1 B-1.7a  ADDED_FAT_IDENTITY contract        <- HERE
 2 B-1.7b  materiality policy: when presence/identity/amount merit asking
 3 B-1.7c  component pricing: identity + amount -> component -> pricer
 4 B-1.8   answer classification and repair hardening
 5 B-2     multi-item meals and atomicity
 6 PROMOTION — one migration, a DELETION event, not a flag flip
```

**B-1.7a's contract, settled 2026-08-11 and recorded so it cannot drift.**

```text
ADDED_FAT_PRESENT
  |- IsTrue -> ADDED_FAT_IDENTITY      SIBLINGS, never a chain
  \- IsTrue -> ADDED_FAT_AMOUNT
```

Amount must NOT depend on identity: *"about a tablespoon, not sure what oil"*
is a truthful, useful answer, and a graph that discarded the amount because
the identity is unknown would destroy a fact to satisfy a topology.

**THE ARTIFACT GENERATES CANDIDATES, NEVER TRUTH.**

```text
ALLOWED    food identity + preparation -> plausible added-fat identities
FORBIDDEN  food identity + preparation -> a RESOLVED added-fat identity
```

Evidence can say grilled chicken is commonly cooked in oil or butter. It
cannot say what THIS user cooked with. The pricing artifact already stores a
qualified candidate SET rather than a winner for exactly this reason, and
identity inherits that discipline rather than getting a shortcut. The
enforcing gate: **no path may produce a resolved `ADDED_FAT_IDENTITY` whose
provenance is the artifact.** Candidates from evidence; truth only from a user
answer or explicit interpretation.

**NO DEFAULT IDENTITY.** The legacy table is its own argument — one tablespoon
of "added fat" spans 60-180 kcal (marinade 60, teriyaki 70, mayo 90, butter
100, oil 120, ranch 145, alfredo 180). Defaulting to "oil" prices butter 20%
high and alfredo 33% low: the same heuristic under a typed interface, and
worse than the honest one because it looks settled.

**THE PROMPT STAYS FROZEN through 1.7a-c.** The semantic contract exists
first; only then is interpretation asked to populate it. The reverse order
means debugging a prompt against a model that does not exist yet.

**SEMANTIC COMPLETENESS IS NOT QUESTION COUNT.** Three fields, zero questions
when someone says "cooked in 1 tbsp olive oil"; one question for "yes, olive
oil", leaving amount. B-1.6b already separated what is ACTIVE from what
RENDERS — `renderable()` filters active-and-unresolved — so a renderer showing
one of two active fields needs no activation change at all.

**Why the firewall came first and the canary second** *(2026-08-10, both now closed — kept for the reasoning)*. Running the canary
over a known writer violation contaminates it — every scenario would have to
be re-run once the firewall lands. And why artifact expansion is LAST: seed
coverage chosen from what foods "seem likely" is a guess, while the canary
produces a measured list of real misses.

**The positive finding from the same trace, because it is easy to miss.** The
ledger/provenance work caught a data-loss defect that would previously have
looked like "salmon was logged". The chicken row's original state survived
only in its `created` event. That is the 08-07 P1 ledger fix paying for
itself, and it is the argument for provenance-before-features.

Status wording is deliberately split. "Implemented and test-locked" is a claim
about construction; "storage-proven" is a claim about the boundary B-1
actually crosses, and the two were conflated once already — the contracts
passed 105 in-memory tests while no patch could be serialized at all.

## Phase B — Canonical clarification for conversational food

### B-0 — Freeze legacy growth

Status: complete, but maintain continuously.

Enforce:

* four legacy clarification producers plus one relay cannot increase,
* option-producer locations cannot increase,
* no new loose `questions` payload shape,
* no new `ClarificationQuestion` constructor outside the frozen inventory,
* no new client prose-to-chip parser,
* no new pending representation,
* no new direct conversational food writer.

Add or retain ratchets for:

```text
question producers          (C8)
option producers            (C9)
legacy food writers         (C4)
pending-state writers
client prose chip derivation
```

Any new feature must use the canonical contracts or remain out of scope.

### B-0b — Lock semantic contracts

Status: implemented as prerequisites; production proof still pending.

Canonical contracts: `ClarificationAttribute`, `ResponseType`,
`ClarificationStatus`, `CandidateSource`, `UnresolvedField`, `CandidateValue`,
`SemanticPatch`, `ClarificationOption`, `ClarificationGroup`,
`ClarificationInteraction`, `QuestionIntent`, `EntityCapabilities`.

Required properties:

**Stable field identity** — `field_id = operation_id + event_id + attribute +
semantic revision`. Never derive identity from list index, option label,
question wording, screen position, or display name.

**Typed option meaning** — every selectable option carries a typed patch.
`label` = presentation, `option_id` = wire identity, `patch` = semantic
meaning.

**Versioned serialization** — every persisted canonical clarification payload
carries schema version, domain, operation ID, revision, event IDs, field IDs,
patch type IDs. No unversioned arbitrary dict becomes the permanent pending
payload.

**`patch=None` is permitted exclusively on inventoried legacy measurement
paths** — today the two construction sites in
`skills/nutrition/clarification_adapter.py`, which set `adapter_built=True`.
Every canonical option created for B-1 must carry a non-null patch. `source`
alone could not express this: it is independently optional, so no predicate
could distinguish an adapter-built option from a canonical producer that
forgot its patch, and C10 was a comment with nothing to key on.

### B-0c — Contract hardening and persistence proof

Status: complete (`core/semantics.py`, `tests/test_contract_persistence_b0c.py`).

Purpose: prove the B-0b types cross process and storage boundaries without
losing type identity, provenance, immutability, or domain meaning. B-1 stores
options and later receives only an `option_id`, so the backend must reload the
exact typed patch from persisted state. Without typed serialization the
canonical flow degrades to

```text
SetQuantity → JSON dict → loaded as dict → reconstructed heuristically
```

which is the architecture being removed, relocated server-side.

**Patch serialization.** Every patch serializes with an explicit
discriminator and schema version:

```json
{
  "patch_type": "set_quantity",
  "schema_version": 1,
  "event_id": "food_1",
  "field_id": "op_1:food_1:quantity:0",
  "provenance": "user_selected",
  "quantity": {"amount": "5", "unit_id": "oz", "dimension": "mass",
               "grams": "141.7"}
}
```

Loading returns the concrete type (`SetQuantity → JSON → SetQuantity`, never
`→ dict`) through a closed registry that fails shut on an unknown
`patch_type` or a newer `schema_version`. Round-trip equality is asserted for
every patch family. **Decimals cross as strings, not JSON numbers** — through
a float, `Decimal("0.1")` does not come back equal to itself, and exact
portion arithmetic is the reason quantities are `Decimal` at all.

**Enum coercion is symmetric.** Strings are coerced and invalid ones refused
at every construction boundary; after construction every internal value is an
enum instance. The asymmetry that existed — field attribute required an enum
while patch provenance and option source kept raw strings — silently
reclassified a user's own figure as an estimate, because
`Provenance.is_users_own` is an identity check and a `str` fails it without
raising.

**Group validation.** `ClarificationGroup` enforces a non-empty event id, at
least one field, every field targeting the same event, and no duplicate field
ids — which, since `field_id` embeds attribute and revision, is also the
no-duplicate-attribute check.

**Interaction validation.** `ClarificationInteraction` enforces operation and
revision alignment across every group and field, unique field ids across
groups, one group per event, and no option referencing a foreign field. A
selectable field with no options is refused at construction: it must declare
`FREE_TEXT_FALLBACK` rather than ship blank for a client to "repair" (C15).

**Immutability.** Mutable payloads are deep-copied at contract construction. A
frozen dataclass holding the caller's dict is not immutable — the producer
could keep editing it, injecting values past validation. The outbox's
`version` key is reserved so a payload cannot shadow the schema version.

**Workout seam completeness.** `SelectEntity` (renamed from
`SelectFoodEntity`) is the domain-neutral entity-selection patch that answers
`EXERCISE_IDENTITY`; `CandidateSource.DEVICE` exists for HealthKit/Whoop
candidates; `UncertaintyEvidence.impact_spread` is a `CanonicalQuantity`
rather than a calorie number. Renaming was free while zero producers existed;
after B-1 stores patches, `patch_type` is wire data and a rename is a
migration. Load-basis semantics (per-dumbbell vs total) remain owed and are
tracked in `docs/WORKOUT_CONTRACTS.md`.

**Persistence proof.** The test that matters is not an in-memory contract
test. It performs the real sequence, against a file database with real
per-session connections:

```text
create interaction with a SetQuantity option
  → serialize into the PendingOperation payload
  → commit → close the session → open a NEW session
  → load the operation → bind option_id
  → obtain a typed SetQuantity → apply
```

### B-1 — One item, one mass-quantity field

This is the first authoritative production slice.

**Eligibility predicate** — B-1 applies only when ALL are true: exactly one
food event; food identity sufficiently resolved; only material unresolved
attribute is consumed quantity; quantity expressible in one supported
dimension; first implementation uses mass; no product identity ambiguity; no
preparation dependency; no multi-item meal; no mixed food/workout turn; no
correction or destructive action; no requirement for multiple clarification
rounds.

Example — eligible: *"I had some chicken breast."* → entity = chicken breast,
quantity = unresolved, dimension = mass.

Not eligible (remain on legacy paths until their own slice is promoted):
"chicken and rice" · "a Core Power" · "two pieces of chicken" · "fried chicken
with sauce" · "half a rotisserie chicken" · "change yesterday's chicken".

**B-1 flow**

```text
message → resolved food identity → one UnresolvedField(quantity)
→ candidate generation → deterministic option selection
→ canonical ClarificationInteraction → persist PendingOperation
→ send grouped ID-addressed payload → receive chip or typed answer
→ produce SetQuantity patch → validate and apply patch
→ revise ResolvedMeal → canonical commit → PresentationSnapshot
→ narration/card/totals
```

**Candidate evidence for B-1** — use ONLY: (1) high-confidence user history
for the same canonical entity, (2) validated entity portion evidence,
(3) deterministic domain fallback candidates, (4) free text. Exclude
initially: web search, LLM-proposed candidates, complex cross-unit ranking,
product catalog variants, conditional preparation logic.

**Quantity option selection** — maximize useful coverage, not generic portion
tiers: `probability × information gain × nutritional materiality × evidence
confidence × user familiarity ÷ interaction cost`. Rules: one field only; at
most three primary numeric options plus "Other"; avoid near-duplicates;
respect preferred display units; preserve semantic quantities internally;
never parse rendered labels later.

**Wire contract** — server sends:

```json
{
  "operation_id": "op_123",
  "revision": 0,
  "interaction_id": "int_123",
  "groups": [
    {
      "event_id": "food_1",
      "label": "Chicken breast",
      "fields": [
        {
          "field_id": "op_123:food_1:quantity:0",
          "attribute": "quantity",
          "response_type": "single_select_or_text",
          "options": [
            {"option_id": "opt_3oz", "label": "3 oz"},
            {"option_id": "opt_5oz", "label": "5 oz"},
            {"option_id": "opt_8oz", "label": "8 oz"}
          ]
        }
      ]
    }
  ]
}
```

The stored server-side option contains the patch. The client submits
`operation_id · revision · interaction_id · field_id · option_id · delivery
key`. It never submits the label as meaning.

**Answer paths** — chip: `option_id → load stored SetQuantity patch →
validate field/revision/event → apply`. Typed ("Around six ounces"): `narrow
quantity parser → SetQuantity(6 oz, USER_STATED) → validate → apply`. Both
converge before pending-state mutation.

**Revision rule** — revision changes only when persisted semantic state
changes: r0 pending meal with open field → r1 patch applied, meal ready → r1
canonical commit. Sending, retrying, or re-rendering the same interaction does
not increment revision.

**B-1 answer idempotency** — chip-answer identity: operation_id, revision,
field_id, option_id, client delivery key. Typed-answer identity: operation_id,
revision, source turn ID, client delivery key. A replay after commit returns
the stored result. A duplicate before commit does not create another revision.

**B-1 presentation** — the final response is produced from committed result
data (committed item, meal totals, day totals, assumptions, provenance,
correction actions). The model may phrase this data. It may not recalculate or
invent it.

**B-1 production definition of done**

Server: canonical quantity producer is sole authority for eligible turns; one
PendingOperation persists the interaction; options carry typed patches; chip
and typed answers converge; stale and foreign answers fail closed; duplicate
answers are idempotent; commit uses the canonical coordinator; result is
persisted; no legacy writer is reached.

Client: canonical payload disables prose-derived chips; chips render directly
from fields/options; taps submit IDs; free text remains available; stale
interactions are handled; final card uses committed result.

Production corpus: chip answer · typed offered quantity · typed non-offered
quantity · duplicate tap · stale revision · invalid option · wrong field ·
answer after commit · repair flow · card/totals agreement · zero duplicate
meals.

Promotion: observe canonical B-1 writes → compare behavior → promote
eligibility path → delete legacy B-1 option/question path → lower
producer/option ratchets.

**B-1 option pipeline scope.** B-1 builds a *minimal, quantity-specific*
candidate generation → selection → patch → render path. It does NOT build the
generalized cross-field `ClarificationOptionGenerator` (milestone 9). The
distinction is load-bearing in both directions: overbuilding the general
framework during B-1 is how a vertical slice becomes a horizontal layer, and
deferring *semantic option integrity* to milestone 9 would ship B-1 chips that
are still labels. B-1's options are canonical — typed patches, recorded
source, no prose derivation — over exactly one attribute.

**B-1 deletion boundary.** Deletion happens at B-1 promotion, not at B-4.
Scoped to the exact B-1 eligibility predicate, delete or disable:

* the legacy quantity question producer,
* the legacy quantity option builder,
* answer-turn quantity reconstruction,
* client prose chip derivation for canonical quantity interactions.

Leaving these alive "until the cleanup phase" is how B-4 becomes an
unreviewable mass, and it is also how two owners of the same question coexist
in production — the condition that produced the four producers.

**B-1 product measurement.** Correctness is not success. Instrument, per
interaction: clarification shown · chip selected · free text used · repair
required · clarification abandoned · time to answer · rounds before commit ·
estimate requested · meal committed · correction within 10 minutes.

Key indicators: clarification completion rate · median clarification latency ·
repair rate · duplicate-meal rate · immediate-correction rate · share of
options sourced from history versus fallback · share of users choosing
"Other". **A technically correct option system that frequently forces "Other"
has failed**, and only the last two indicators can detect it.

### B-1.5 — One item, multiple independent material fields

*(2026-08-07: the lifecycle below is BUILT and deployed — PARTIAL outcome,
`hold_answer`/`ready_to_settle`, `ResolvedFields`, per-field settlement, the
two-field producer, evidence-driven `unresolved_when`, and the iOS multi-field
client. Preparation opens nowhere in production because no evidence source can
establish comparability — see B-1.5E, which now gates closure. The spec below
remains the contract.)*

After B-1 is green in production, add preparation classification. Do not use a
generic `cook_type`; model nutrition-relevant fields (breading, fried status,
skin presence, cut, added sauce, added fat). First expansion uses one compact
preparation category: `plain / breaded / fried / unknown`.

```text
Chicken breast
Amount        [3 oz] [5 oz] [8 oz]
Preparation   [Plain] [Breaded] [Fried] [Not sure]
```

Proves: multiple fields on one event; one grouped interaction; partial answer
state; independent typed patches (`SetQuantity`, `SetPreparationCategory`);
operation remains pending until policy says ready. Rules: both fields already
eligible; each option belongs to exactly one field; mixed chip rows forbidden;
a partial answer updates only answered fields; unanswered fields remain open;
one meal still commits once.

**B-1 language scope — English-only, ENFORCED, not assumed.**

`parse_command` decides whether to cancel a meal, skip an item or assume a
portion, and its patterns are English. Run against another language it is not
neutral: it is a matcher that does not know the ground moved. This repo has
shipped that defect — EN-only rescue detectors let Russian meals go unlogged
(2026-08-03); the routing gate was fixed and the DETECTORS were not.

The command layer is therefore a three-tier design, and B-1 builds only Tier 1:

```text
user text
  → Tier 1  locale-specific deterministic lexicon   (B-1: English only)
  → Tier 2  pending-aware constrained classifier    (B-1.8)
  → Tier 3  repair, never a guess
```

The OUTPUT is language-neutral (`ClarificationCommand`); the PATTERNS are not.
So, in force from B-1:

* `parse_command(text, locale=...)` returns `NONE` unless the locale is
  English. No phrase gets a "language-neutral" exemption — none can be proven
  one, and the cost of being wrong is a destroyed meal.
* `UNKNOWN_LOCALE` is not English. "We could not tell" must never authorise a
  destructive command.
* The locale is **persisted on the operation** (`operation_id · revision ·
  locale`), so an answer is interpreted under the same language context as the
  question rather than re-detected from a two-word reply.
* Resolution order: stored preference → the operation's established locale →
  script detection, last.
* Numeric/unit answers (`150 g`, `6 oz`) still work in any locale — excluding
  a locale from the COMMAND lexicon must not exclude it from answering.
  Language-specific number words (`seis onzas`, `шесть унций`) belong to the
  narrow quantity parser, not here.
* Destructive and non-destructive commands do not share a threshold:
  `CANCEL` very high · `SKIP_ITEM` high · `USE_ESTIMATE` moderate · `NONE`
  safe default. A mistaken estimate is repairable and disclosed; a mistaken
  cancellation discards the meal.

**Owed, per language, before that language may run Tier 1:** a locale lexicon,
field-parser fixtures, a classifier corpus, adversarial destructive-command
tests, and production measurement. Tracked in `DELETION_INVENTORY.md`.

**B-1 progress ledger** — kept current, because "the tests are green" and "the
slice is done" are different claims and were conflated once already.

| area | state |
|---|---|
| eligibility predicate, one owner, evaluated once | DONE |
| pre-ownership rollout gate (halt / allowlist / cohort) | DONE |
| candidates: user history + calibrated ontology only | DONE |
| deterministic selection, ≤3 + Other, no near-duplicates by grams OR label | DONE |
| typed `ClarificationInteraction`, persisted with patches | DONE |
| `PendingOperation` created before the question is sent | DONE |
| answer ownership: chip · exact label · typed · command | DONE |
| terminal ownership (C10): no mid-flight fallback, gate unreachable by AST | DONE |
| settlement: one canonical commit, replay on re-delivery | DONE |
| locale pinned at the ask, English-only Tier 1 | DONE |
| repair / cancel / internal-failure copy from committed truth | DONE (facts + deterministic fallbacks) |
| card + totals from the SAME facts — disagreement unconstructable | DONE |
| instrumentation: all 11 signals, one owner; abandonment + correction on a timer | DONE |
| live operation probe, correlated to a self-minted operation id | WRITTEN — evidence owed on deploy |
| **Arnie voice over the committed facts** | TODO — after lifecycle/committed-truth verification, BEFORE broad rollout |
| **Telegram/iMessage label-text path proven in production** | TODO |
| **iOS B-1d: ID-addressed payload + real chip-path proof** | DONE 2026-08-07 — entries 2887/2890 answered by `option_id` |
| **the card the client can actually decode** | DONE 2026-08-07 — `card_for` was dropping `quantity`/`carbs_g`/`fats_g`, which iOS declares non-optional; the meal logged and the card vanished silently |
| **reply-metadata binding for `LABEL_TEXT` channels** | TODO — owed with B-1d |
| **rollout** | ~~allowlist → 1% → 5% → 25% → 100%~~ **SUPERSEDED 2026-08-07.** No ramp. Allowlist only through B-2, then ONE promotion event |
| **deletion: legacy quantity producer, option builder, answer reconstruction, prose-chip path; lower C8/C9** | DEFERRED to the one promotion event — not per slice |

**B-1 presentation boundary.** B-1 completes the canonical response FACTS and
their deterministic fallbacks. Production-quality Arnie voice may be refined
after end-to-end lifecycle and committed-truth verification, and must land
before broad rollout — not after it.

The ordering is the whole point:

```text
commit  →  committed facts  →  deterministic copy  →  (later) voice
```

**Voice is post-commit, and may never reinterpret, recompute, or override a
committed fact.** It phrases what the row says; it does not decide what the
row says. The failure this forbids is measured and specific: a reply reading
"logged, 970/98g" while nothing had been written (2026-08-03), and a card whose
totals disagreed with the prose beside it because three owners each computed
their own. A renderer that can recompute is a second owner of the number.

**The renderer is never passed `MealCommitResult`.** Nor persistence models,
resolver evidence, or any mutable domain state. It receives the immutable
`CanonicalResponseFacts` that `facts_for()` produced, and nothing else — an
earlier draft of this section said voice would render "the same
`MealCommitResult` fields", which reopens the exact ownership problem the
seam exists to close. A renderer holding the commit result can recompute, and
a renderer that can recompute is a second owner of the number.

```text
MealCommitResult
  → facts_for()
    → CanonicalResponseFacts   (immutable)
       ├── deterministic fallback
       └── constrained voice renderer
```

This is structural and absolute. A voice pass that fails degrades to the
deterministic sentence — never to silence, and never to an invented one.

**THREE VOICE PASSES, EXPLICITLY, because "when does voice happen" currently
has three defensible answers and a team will pick different ones.**

| pass | when | scope |
|---|---|---|
| **B-1 presentation harmonization** | before **public** rollout of B-1 | remove the obvious lane-to-lane discontinuity — B-1 turns render from a template while legacy turns are composed, so the assistant sounds different depending on routing the user cannot see. Fixed/versioned templates or tightly constrained rendering. **Not** the adaptive voice project. |
| **B-2.8 product voice system** | after semantic intents and dependencies stabilize (B-1.6, B-1.7) | adaptive, contextual, channel-aware rendering. Inputs are `CanonicalResponseFacts` and `QuestionIntent` **only**. This is the first implementation of the real voice boundary. |
| **Gate 3 voice polish** | release candidate | final diction, consistency, evaluation and release tuning. **Not** the first implementation of the boundary — that already exists by then. |

Separate again from all three: **instrumentation wording inside each slice**
(B-1a and its successors), which exists to make a slice measurable and is
fixed, minimal and version-stamped.

**The `LABEL_TEXT` correlation limit, stated rather than discovered later.**
`"6 oz"` carries no identity. Once operation A has settled, a delayed reply
naming an option that also exists on operation B is indistinguishable from a
reply to B — `owning()` returns the most recent operation and binds there.

This is a TRANSPORT limitation, not an architecture flaw: with no metadata on
the reply there is nothing to correlate against. It is bounded, not solved, by
`SETTLED_OWNERSHIP_MINUTES` and by iOS being excluded until taps are
ID-addressed. **Owed with B-1d:** where a platform does expose reply metadata
(Telegram's `reply_to_message`), bind it to `operation_id` and prefer it over
inference. Until then `LABEL_TEXT` is a restricted capability and is named as
one in code — its production evidence does not substitute for the chip path's.

Two scope facts to state rather than let green tests imply otherwise:

* **The chip path has no production channel yet.** `answer_from_chip` is
  implemented and tested, but nothing in production submits an `option_id` —
  Telegram and iMessage return the label text, which binds to the stored patch
  through the label-selection path. The structured tap's PRODUCTION proof is
  owed at B-1d and must be recorded as owed, not as landed.
* **Pricing is stubbed in the lifecycle suites.** They monkeypatch
  `_analyze_food` deliberately, to measure the lifecycle rather than the
  enrichment ladder. "One commit, one row, correct provenance" is proven;
  "the number is right for 6 oz of chicken" is `analyze()`'s contract, tested
  where that lives. The live probe is what first exercises real pricing
  through this path.

**B-1.5 deletion boundary:** delete the matching legacy preparation ownership
at promotion — the preparation question producer, its option builder
(`_PREPARATION_OPTIONS`), and answer-turn preparation reconstruction.

### B-1.6 — Conditional clarification dependencies

Add semantic dependencies, beginning with added fat:

```text
quantity
preparation category
added_fat_present
    └── added_fat_amount, active only when present = true
```

Not hardcoded conversation code — field activation predicates
(`added_fat_amount active when added_fat_present == true`). After every patch
the dependency engine: (1) recomputes active unresolved fields, (2) closes
fields made irrelevant, (3) activates newly eligible dependent fields,
(4) reruns materiality policy, (5) asks, assumes, or commits.

Revision sequence: r0 quantity+preparation open → r1 quantity=5oz,
preparation=plain, added_fat_present activates → r2 present=yes, amount
activates → r3 amount=1 tbsp, ready → r3 canonical commit.

**B-1.6 deletion boundary:** delete hardcoded added-fat follow-up branching
for eligible turns, if present. The dependency engine replaces it; leaving the
branch as a fallback means two owners decide when to ask.

### B-1.7 — Accuracy-mode policy over one topology

Quick: ask quantity; assume plain; assume no added fat; disclose assumptions.
Moderate: ask quantity; ask preparation; ask added fat only when material.
Strict: ask quantity; ask preparation; ask skin/breading when relevant; ask
added-fat presence; ask amount when present.

All modes use one PendingOperation, one revision model, one answer system, one
commit path. Mode assumptions produce typed patches or typed assumptions with
`MODE_DEFAULT` provenance — never masquerading as user statements.

### B-1.75 — Repricing after a quantity patch *(observed in production, deferred)*

**Not a nutrition-accuracy item, and not fixable by improving the resolver.**
`core/b1_quantity_operation.py` builds the pricing input as
`inp = {**item, "quantity": quantity_text}` — the answered quantity layered on
top of the ask-time `amount`, `unit`, and macros. `_analyze_food`
(`handlers/tool_executor.py:2896`) reads `calories/protein/carbs/fats` straight
out of that dict as the authoritative figures, so it receives two contradictory
statements of the same fact and picks one.

**⚠ The production evidence first cited here was wrong, and is corrected below.**
The defect is asserted from the CODE, not from these three operations. Read the
correction before designing tests against them.

| entry | item at ask | answer actually sent | committed | verdict |
|---|---|---|---|---|
| 2849 rice | 100 **g** → 161/4/34/1 | *(typed grams)* | 39.6 g → 64/1.4/13.4/0.5 | scaled correctly (×0.396) |
| 2851 chicken | 6 **oz** → 280/52/0/7 | "Half a breast grilled with a little spray oil" | 87 g → 96/20/**4**/0 | **confounded** — the answer changed the food's description (spray oil legitimately re-prices fat 7→0). 4 g carbs on a chicken breast still looks wrong, but cannot be attributed to this mechanism. |
| 2852 oatmeal | 1 **cup cooked** → 150/5/27/3 | "Half a cup Made with milk nothing else in it" | 45 g → 150/5/27/3 | **not a defect.** ½ cup dry ≈ 45 g, and 1 cup cooked oatmeal *is made from* ½ cup dry — same quantity of food, so identical macros are correct. |

The original reading ("gram-based items survive, every other basis does not")
came from inferring the answers from what was *suggested* rather than reading
`conversation_logs.raw_message`. It does not survive contact with the actual
messages.

**What the defect rests on instead — a fact about the code.** `_analyze_food`
reads the macros out of `inp`, and `analyze()` documents its own conflict
policy: *"The LLM's calories/protein anchor the portion unless the quantity is
an explicit mass and the winner is trustworthy."* B-1 hands it macros belonging
to the ask-time quantity together with the answered quantity, so which of the
two governs is decided by that policy rather than by the user's answer. The
answered quantity must be the only quantity authority; today it is one of two
inputs competing for the role.

**Therefore the acceptance criteria are BEHAVIOURAL, not reproductions.**
Writing "the oatmeal regression" as a test would encode a misreading. Prove
instead that committed nutrition responds to the answered quantity across
gram, ounce, cup, piece and free-text bases — and let whichever of those is
already correct stay green.

**The fix is a deletion, not a guard:** the item handed to pricing must have its
quantity fields *replaced*, not shadowed, so pricing derives from `food_name` +
answered grams exactly once. Adding scaling arithmetic here would violate the
standing no-heuristics rule and would leave the contradictory input in place.

**Sequencing (Danny, 2026-08-06):** downstream nutrition refinement owns this;
it does not gate B-1. Recorded here so it is not rediscovered. It *does* gate
B-1 **promotion**, because promotion asserts the answered quantity produces the
committed numbers — so this must close before the legacy quantity path is
deleted, whichever phase closes it.

Regression test owed with the fix: ask-time basis in a non-gram unit, answer in
grams, assert the committed macros scale from the stated basis.

### B-1.8 — Harden answer classification and repair

Includes **Tier 2 of the command layer**: a pending-aware constrained
multilingual classifier that receives the user text, the known locale, the
active clarification field and the allowed command enum — and may return only
a `ClarificationCommand` or `NONE`. It has no authority to interpret a new
meal. "No tengo idea" resolves to `USE_ESTIMATE`; it can never resolve to a
food entry. Below the confidence threshold the answer falls to the field
parser and then to repair, phrased in the user's own language.

Fallback order:

```text
1. exact option-ID binding
2. narrow field parser
3. pending-aware constrained classifier
4. targeted repair
5. explicit cancel or skip
6. fresh-turn interpretation only with clear new consumption
```

Constrained commands: CANCEL · SKIP_ITEM · USE_ESTIMATE · COMMIT_READY ·
RESTART · KEEP_AS_READ · NONE. The classifier receives the open operation,
active fields, recent interaction, and user text — not an unconstrained
fresh-meal task.

**Hard routing rule** — while a clarification is open: an ambiguous reply is
presumed to address the open operation unless it clearly introduces a distinct
new consumption event. ("5 ounces" → answer; "probably grilled" → answer;
"skip it" → command; "I also had a protein shake" → potential new food event,
handled explicitly; "yeah" → field-specific interpretation or repair, never a
fresh meal.)

## B-2 — Multi-item meals and grouped interactions

Only after single-item dependent flows are production-proven.

*"I had chicken and rice."* →

```text
Meal
├── chicken: quantity open · preparation open · added fat conditional
└── rice:    quantity open
```

Capabilities: multiple events; grouped fields per event; partial answers;
multi-turn completion; independent field activation; neighbor protection; one
operation revision; one eventual meal commit.

**Neighbor protection** — a clear item must not be re-questioned because an
adjacent item is ambiguous. "5 oz chicken and some rice" → chicken quantity
stays resolved; only rice is open.

**Partial answers** — "5 oz for the chicken" applies only the matching field
patch; rice stays open. Do NOT create one committed chicken meal and a second
rice meal.

**Bundling** — bundle fields only when all are currently active, independently
answerable, the interaction remains compact, and field ownership stays clear.
Never flatten all options into one row.

**Explicit recovery partial commit** — allowed only through explicit recovery
("log the chicken and skip the rice", expiry policy, abandonment, clearly
separable consumption events, explicit "log the rest"), recorded as a
deliberate operation outcome — not normal moderate-mode behavior.

### B-2.5 — Product identity, package size, consumed fraction

*"I had a Fairlife shake."* Fields: product identity, package size, consumed
fraction. Candidate sources in order: user product history, exact catalog
candidates, package metadata, validated resolver candidates, constrained model
proposal last. Options carry stable identifiers (`SelectEntity`,
`SelectProductVariant`, `SetPackageSize`, `SetConsumedFraction`); the label is
never parsed.

### B-2.6 — Material preparation, sauces, composite additions

*(Inherits from B-1.5: the preparation ontology (`preparation_ontology.py`,
ids constrained to resolver-actionable tokens — `breaded`/`plain` rejected as
inert, `baked` folded into `roasted` for the validator, though USDA itself
says "baked" for potatoes), identity-composition pricing, and the B-1.5E
evidence layer. MULTI_SELECT remains unproduced and the one-answer-per-field
limit is pinned by `test_one_field_holds_exactly_one_answer_and_that_is_a_known_limit`
— multi-valued additions land HERE, and that gate is where the work starts.)*

Typed fields as needed: breading, skin, added fat, sauce type, sauce amount,
sweetener, milk type, toppings. Ask by materiality (`expected nutrient
variance × uncertainty × confidence improvement ÷ user effort`): grilled vs
baked may not deserve a question; plain vs fried often does; oil presence may
matter; herb seasoning does not; garnish color does not.

### B-2.7 — Semantic chip candidate pipeline

One `ClarificationOptionGenerator` (entity, field, resolver candidates, user
history, locale, accuracy mode, channel capabilities) → canonical candidates.
Evidence hierarchies per field family as in
[CHIP_GENERATION_MIGRATION.md](CHIP_GENERATION_MIGRATION.md). Selection by
probability, information gain, materiality, source confidence, semantic
diversity, user familiarity, interaction cost. A separate renderer owns
locale, unit preference, shortening, accessibility, channel constraints — no
semantic choice during rendering. The client decides layout only; it does not
derive semantics or generate missing options.

### B-2.8 — QuestionIntent and voice boundary

Policy emits `QuestionIntent` (interaction type, subjects, resolved context,
unresolved fields, assumptions, urgency/materiality, desired compactness); the
renderer produces wording under constraints, with deterministic fallback
templates mandatory. Wording failure must never block the semantic
interaction.

## B-3 — Consolidate pending state

`PendingOperation` becomes the sole durable owner: operation ID, revision,
domain, payload schema version, domain payload, active fields, inactive
dependent fields, resolved patches, assumptions, answer history, interaction
history, expiry, attempt count, terminal status, commit claim, answer claim.

Delete ownership from `deferred_calls`, `staged_items`, `pending_questions`,
loose conversation payloads, reconstructed wire questions, parallel pending
blobs. Compatibility readers may exist temporarily; no new writes target them.

### B-3.5 — Promote canonical clarification across all food cases

Field families one at a time (quantity → preparation → added fat → product
identity → package size → fraction → serving basis → multi-item → partial
answer → commands → repair), each through: eligibility predicate → canonical
producer authoritative → shadow/measure → production corpus → promote →
delete legacy family path → lower ratchet. Do not wait for all families before
deleting migrated legacy ownership.

## B-4 — Delete the old clarification architecture

Delete: the clarification adapter; loose dict question producers; duplicate
`ClarificationQuestion` constructors; question-text attribute inference;
position/text-based field IDs; response-schema reconstruction; client
`QuickReplyEngine` prose parsing; server option reconstruction; legacy
pending-question ownership; broad interpreter fallback for open clarification;
default moderate partial commits.

Ratchets: C8 producers → 0 · legacy relays → 0 · prose chip parsers → 0 ·
unstable field-ID builders → 0 · legacy pending writers → 0.

**Phase B is not complete until deletion is merged and production-stable.**

## Phase C — Finish conversational food on the canonical spine

* **C-1** Migrate the two remaining `tool_executor` writers to
  `ResolvedMeal → commit_or_load_existing → canonical writer`; C4 → 0.
* **C-2** Canonical corrections (edit quantity, replace identity, change
  preparation, remove item, add missed item, change meal type, correct
  logging day) — each a new operation revision → immutable ledger event →
  canonical write → persisted result. No row patches without ledger history.
* **C-3** Canonical undo — targets stable committed event IDs, never
  "last row" heuristics.
* **C-4** `PresentationSnapshot` authority — one post-commit snapshot feeds
  chat narration, meal card, day timeline, coach feed refresh, notifications,
  API response. Delete duplicated calculation/formatting paths.
* **C-5** Search/resolver consolidation — one coordinator over user history,
  catalog, USDA, OFF, web evidence, model estimate; every winning value
  records source, candidate ID, confidence, serving basis, identity
  provenance, nutrition provenance, evidence IDs. The resolver reports
  uncertainty; it does not decide whether to ask.
* **C-6** One ambiguity engine — resolver evidence → one food ambiguity
  engine → canonical unresolved fields → policy.
* **C-7** Food production-readiness gate before workouts: all food writers
  canonical; clarification canonical; corrections canonical; undo canonical;
  no prose-derived chips; one pending owner; presentation from committed
  truth; duplicate replay stable; PG concurrency tested; observability
  complete; fallback rates within target; no unbounded clarification loops;
  no legacy writer escape.

## Phase D — Generalize the proven operation envelope

Only after food has two real operation types or workouts begin using the
spine. **D-1** shared `OperationRequest` (domain payload stays strongly
typed — `ResolvedMeal | ResolvedWorkout | ResolvedWeight`, never generic JSON
blobs). **D-2** shared `OperationResult` (moves render actions, outbox
events, assumptions, warnings, committed event IDs out of `MealCommitResult`;
domain results stay inside the envelope). **D-3** shared typed outbox
contracts (event ID, kind enum, version, payload, dedup key, operation ID,
user ID) for memory update, coaching analysis, trend recomputation,
notification planning, timeline refresh, PR detection.

### The destination this is walking toward (recorded 2026-08-05)

B-1 turned out to be less "food clarification" than "a transaction system that
happens to be clarifying food": explicit ownership, canonical operations,
optimistic revisions, replay instead of duplicate execution, deterministic
presentation, boundaries that are structural rather than conventional, and
observability designed in rather than bolted on.

So the long-term target is **one conversational execution framework that
health domains plug into**, not parallel systems per domain. The concepts that
should end up domain-agnostic:

```text
PendingOperation           an operation with unresolved fields
ClarificationInteraction   what we are asking, ID-addressed
SemanticPatch              a typed answer
AnswerOutcome              applied / repair / cancelled / refused
CanonicalResponseFacts     committed truth, extracted once
Renderer                   phrases facts; never recomputes them
```

The backend should eventually think *"I have a pending operation with
unresolved fields"* and not *"I have a pending food quantity."* Food becomes
one implementation; workouts a second; medication, hydration, weight and
supplements are then additions rather than rewrites.

**This does NOT belong in B-1 or B-2, and pulling it forward would be the
mistake this whole migration exists to avoid.** The rule of two still governs:
extract only what two real domains have demonstrated needing. B-0b already
followed it (`ClarificationAttribute` carries workout members; the spine is
proven domain-neutral by a fake-domain test) and B-1 deliberately did not
(`quantity_clarification` is food-specific, because a generalized option
generator built before one vertical slice works is how the four legacy
producers happened).

What makes this a destination rather than a wish is that each phase already
lowers the distance: every ratchet that falls, every legacy owner deleted, and
every food-named-but-generic shape in `WORKOUT_CONTRACTS.md`'s owed-renames
register is one fewer thing standing between here and it.

## Phase E — Structured workout logging

**E-1** contracts (`ResolvedWorkout`/`ResolvedExercise`/`ResolvedSet`/
`WorkoutCommitResult`/`WorkoutPresentationSnapshot`). **E-2** storage
(`workout_sessions`, `workout_exercises`, `workout_sets`,
`exercise_resolution_evidence`; shared ledger for create/correct/undo/
replace). **E-3** structured quick workout path through the shared
coordinator, proving atomicity, duplicate replay, crash safety, PG
concurrency, correction/undo, outbox behavior. **E-4** one workout entity
registry (canonical exercise IDs, aliases, equipment variants, movement
pattern, laterality, load semantics, measurement capabilities) — no ad hoc
exercise-name strings as identity.

## Phase F — Conversational workout logging and cross-domain turns

**F-1** interpretation ("Bench 3x8 at 135, then incline dumbbells 3x10 with
50s" → `ResolvedWorkoutDraft`). **F-2** clarification reuses the EXACT shared
architecture — workout patches (`SetSetCount`,
`SetRepCount`, `SetExternalLoad`, `SetLoadBasis`, `SetDuration`,
`SetDistance`, `SetEquipment`; exercise identity is answered by the shared
`SelectEntity`, not a byte-identical `SelectExerciseEntity`), dependencies
(load amount → load basis:
per-dumbbell / total / machine stack / assisted), options from program
prescription, same-session history, recent history, equipment increments,
device data. No separate workout chip system. **F-3** presentation post-
commit; coaching downstream, never owning logging semantics. **F-4** mixed-
domain turns ("chicken and rice, then bench 3x8") → one Turn, independent
food and workout operations, each with its own resolution/pending/revision/
commit/result; no giant cross-domain transaction by default; the response may
aggregate both after each reaches a valid state.

## Final deletion and completion criteria

**Mutation** — zero direct food writers outside the canonical domain writer;
zero direct workout writers; duplicate replay always loads the persisted
result; all committed mutations have ledger events; corrections and undo use
canonical operations.

**Clarification** — zero legacy producers; zero adapter-owned production
semantics; zero prose-derived chips; zero label-to-meaning parsing; one
`PendingOperation` owner; typed patches for chip and text answers;
dependency-driven follow-ups; accuracy modes share one topology.

**Presentation** — narration, cards, totals from committed results; the model
cannot mutate facts; no duplicated total calculation paths; assumptions and
provenance preserved.

**Operations** — durable work uses the outbox; best-effort work is explicitly
noncritical; release tooling compiles operational scripts; promotion records
are measured; health reports active owners; ratchets prevent legacy ownership
from returning.

**Domain expansion** — food fully canonical and production-proven; structured
workout logging on the shared spine; conversational workout clarification
reuses typed fields and patches; domain payloads stay specific.

## Recommended milestone order

```text
 1. B-1 one-item quantity                   DONE, production-proven
    1a. P1 canonical pricer                 DONE, closed in production 08-10
    1b. P1(b) ownership firewall            DONE, fired 3x in production
 2. B-1.5 quantity + preparation            DONE, CLOSED 08-10
    2a. B-1.5E semantic evidence layer      DONE
    2b. the canary                          5 passed; F NOT APPLICABLE — the
                                            client removes the interaction on
                                            tap, so the gesture does not exist
    2c. identity boundary, both consumers   DONE — key AND ranker query
 3. B-1.6 conditional activation            DONE, CLOSED 08-10
    3a. engine + the B-1.5 lost update      declarative Rules, derived edges,
                                            row lock at the mutation boundary
    3b. producer + revision semantics       one bump per shape change, removal
                                            on the wire, persistence round-trip
    3c. ownership seam from portions.py     proven BY POISON, not by grep
 4. B-1.7 accuracy policy                  }  all built on the canonical
    4a. ADDED_FAT_IDENTITY contract        }  path, allowlist only.
        <- CURRENT                         }  4a is a CONTRACT, not pricing:
    4b. materiality: when to ask            }  candidates from evidence, truth
    4c. component pricing                   }  only from a user answer. And
    4d. prepared-identity fallback          }  4d/4e were deferred here on
    4e. preparation materiality             }  purpose — see the precision
    4f. extraction survival (~1-in-3 loss)  }  paradox
 5. B-1.8 answer repair/fallback           }  includes the ranker/SELECTION
                                           }  floor: `oats|` holds 2 qualified
                                           }  candidates best_candidate will
                                           }  not select, so a COVERED food
                                           }  still prices as an estimate
 6. B-2 multi-item and partial answers     }
    6a. meal atomicity (one mutation)      }  the canonical/chat-lane commit
                                           }  divergence, filed 08-07
 7. THE PROMOTION EVENT — all users to canonical, allowlist removed,
    legacy food pipeline deleted, ratchets lowered. Once, not per slice.
 8. product/fraction/package fields
 9. generalized ClarificationOptionGenerator across all migrated field
    families — NOT "semantic options arrive here". B-1 already ships a
    minimal, quantity-specific option pipeline; this milestone generalizes it
10. one PendingOperation owner
11. delete adapters and legacy clarification producers
12. migrate remaining conversational food writers
13. canonical corrections and undo
14. PresentationSnapshot authority
15. C4 reaches zero
16. food production-readiness gate
17. shared OperationResult envelope
18. structured workout logging
19. workout corrections/undo
20. conversational workout interpretation
21. workout clarification using the same patch system
22. mixed-domain turn coordination
```

**The key sequencing rule:** expand one semantic capability only after the
previous capability is authoritative end to end and production-measured. That
gets Arnie to the desired backend without recreating the same fragmentation
under better type names.

### One promotion event, not a rollout ramp *(Danny, 2026-08-07 — SUPERSEDES per-slice promotion)*

**Canonical stays allowlist-only — user 26 and internal testers — through
B-1.5, B-1.6, B-1.7, B-1.8 and B-2.** Every one of those is built on the
canonical path. Then a SINGLE promotion:

```text
  move all users to canonical
  remove the allowlist
  delete the legacy food pipeline
  lower the migration ratchets
```

**Why: one migration event instead of repeatedly switching production users
between implementations.** The prior order promoted and deleted after each
slice, which meant every user crossed the boundary five separate times, each
crossing carrying its own regression surface and its own rollback question.

**What this changes about the earlier rule.** "Prove → promote → delete →
reuse" required a slice's legacy owner to be *deleted* before the next slice
began. That clause is now deferred to the promotion event for the whole B-1
family. The reuse discipline is unchanged: each slice must still be
authoritative and production-measured before the next starts.

**The cost, stated plainly, because deferring deletion is the thing that rule
existed to prevent.** The legacy path stays alive through five more slices, so
"two owners of one behaviour" is carried longer, and C4/C8/C9 stay high until
the end. Two facts make it affordable and both must keep holding:

* legacy is **unchanged** for everyone outside the allowlist, so drift cannot
  reach a production user before promotion;
* the canonical path is **additive** — `try_take_ownership` returning None
  leaves the turn exactly as it is today.

If either stops being true, this sequencing has to be revisited rather than
worked around.

**The promotion event is therefore large, and must be gated hard rather than
declared.** Its gate is the union of every slice's promotion criteria — not a
fresh judgement made on the day. Each slice writes its promotion conditions as
executable gates when it lands, so promotion is running them, not re-deriving
them.

## Status board

### ⏱ SESSION 2026-08-16/17 — DUPLICATE SEMANTICS CLOSED · BACKEND FROZEN

```text
LOCAL       the freeze commit           origin/main 7059fbc (docs)
DEPLOYED    29ba0e1 — live, confirmed via /health, branch main
SUITE       9423 collected · SQLite 9311 passed / 111 skipped
                          · Postgres 9393 passed /  29 skipped   0 failed both
COHORT      user 26, iOS only · general_settlement_reachable = true
BACKEND     A1-A12 FROZEN — tests/test_the_general_settlement_backend_is_frozen.py
```

⛔ **THE PUSH DID NOT DEPLOY, TWICE.** `e2d732d` and `eedacfd` both sat on `main`
with production serving `8f5501d` until the deploy was triggered by hand. Do not
read "pushed to main" as "live" — read `/health`.

**WHAT CLOSED, AND THE OBSERVABLE THAT PROVES EACH:**

```text
the duplicate's reply    the coordinator's FAILURE FLOOR had already filled
                         `state.response` before the absorption ran, so
                         "Already logged that one." was unreachable. eedacfd
the legacy fingerprint   a re-cased plan minted its OWN claim. The observable is
                         the CLAIM COUNT: two before, one after
A12 canonical identity   the operation id shape: `general:26:meal:9303ac8deca72cd7`
                         where it read `general:26:ios:<UUID>` before — and ZERO
                         processed_turns claims, so canonical borrowed nothing
```

⭐⭐ **THREE MISREADINGS OF ONE LATENCY NUMBER, TWO OF THEM THIS SESSION'S.** A 6 ms
duplicate was read as proof that a different layer caught it, then as an
unexplained anomaly. Neither. A food already in memory makes **no model call**,
so the successful send was 112 ms with no `llm` leaf — and a successful CANONICAL
log is 29 ms with `stages={}`, because `pricing.*` and `tools` are legacy-executor
instrumentation. **On the canonical path a turn that succeeded is
indistinguishable by latency and stages from a refused duplicate.** Read the
stages of the turn that WORKED before attributing a symptom to a mechanism.

⚠ **STILL OPEN, DELIBERATELY:** `turn_metrics.outcome` cannot report a native
failure — `_rt.done()` runs in the `finally` around `coordinator.run`, which never
raises, while `raise state.error` happens after the trace closed. Deferred because
changing it mid-canary moves the measurement contract. · 6 of 88 `meal_commits`
rows for user 26 carry `created_at IS NULL` despite `server_default=func.now()`;
A12 fails closed on an unstamped row, but the NULLs have the shape of the
`_migrate` Postgres gap. · Whether a day-clear should drop that day's claims is
an unmade product decision. · ⛔ **THE "NO CI HAS EVER RUN" NOTE WAS FALSE** —
`ci.yml` runs the suite on every push to `main` against a real Postgres, and the
check-runs API shows `test` = FAILURE on `29ba0e1` and `7059fbc`. `main` has been
RED since the A12 push, from this document's own staleness gate (code 08-17 vs
stamp 08-14, lag 3 > MAX_LAG_DAYS 2). Reconciling and stamping it is the fix. A
second workflow, `eval.yml` (`battery`), failed on `eedacfd` and is unexamined.

⭐ **AND FOUR "PRE-EXISTING" TEST FAILURES WERE A CLOCK** — labelled
"order-dependent" once and "they fail standalone too" once, neither reading having
varied anything. The fixture built its `DailyLog` from the HOST'S `date.today()`
while the code under test resolved the USER'S logging day, so they were red
whenever the runner sat in a timezone behind UTC. Green now across 15 timezone ×
rollover-hour combinations. **A failure nobody can reproduce on demand gets
explained away — and this was the ratchet protecting "no row is deleted without a
ledger event".**

### ⏱ SESSION 2026-08-13 — BASELINE FROZEN · RANKER REACHED · V2 SPLIT

```text
LOCAL       724935b (+ uncommitted 0.8 split)   origin/main 929879e
DEPLOYED    20e3acd — 15 commits behind; auto-deploy has NOT fired since 0.1
SUITE       SQLite 8817 / 0 · Postgres 8899 / 0 · 4 xfailed   (at 724935b)
ARTIFACT    27 entries · 116 candidate pairs · 0 annotations (predates store)
BASELINE    77 signed: 29 admit / 45 reject / 3 UNRESOLVED · migration closed
REACHABLE   rank_v2 27/27 · rank_v1 24/27
REVIEW      24 canonical winners triaged, 0 SIGNED
```

**THE THREE FINDINGS THIS SESSION PRODUCED, IN ORDER OF WEIGHT.**

1. **The reviewed population was not the one production rests on.** The
   accounting gate caught 8 unsigned rows, then passed at 77/77 while 71 of
   the 77 were cold-start discoveries. 21 of 27 production winners had never
   been reviewed. *A gate proves its population reconciles with itself, not
   that it is the right population.*
2. **Five committed identities priced from nothing, silently.** Fixed at the
   RANKER (morphological folding), not in the evidence boundary — and the
   test that had recorded the plural gap as "a D-class ranking finding …
   deliberately NOT fixed inside the evidence boundary" was right about the
   layer. Its red half then stopped reproducing and was RESTORED with a case
   that still does.
3. **Reachability depended on a per-user feature flag.** Both modes live at
   once; 9 identities priced differently BY USER, `beef|fried` by +69%. Now
   split, so one regime is freezable.

**INSTRUMENTS THAT LIED BY SILENCE THIS SESSION — TWO WERE SELF-INFLICTED.**

```text
pytest printed no "N passed" for hours   pytest.ini already sets addopts=-q;
                                          adding -q made it -qq, which
                                          SUPPRESSES the summary
"SQLite + Postgres" was SQLite twice     conftest.py:61 hard-pins DATABASE_URL;
                                          PG gates on TEST_POSTGRES_URL, not
                                          TEST_DATABASE_URL. THE TELL WAS AN
                                          IDENTICAL SKIP COUNT (107/107);
                                          real PG skips 82 fewer.
confidence_score is not a rung signal    284 rows at 0.85 across many paths;
                                          NOT used to claim anything
```

Correct invocations:

```bash
TZ=UTC .venv/bin/python -m pytest -p no:randomly
TZ=UTC TEST_POSTGRES_URL="postgresql+psycopg://localhost/arnie_test"        .venv/bin/python -m pytest -p no:randomly
```

**OPEN, CARRIED FORWARD.**

```text
0.9   24 winners: 13 clean ADMIT · 1 UNRESOLVED · 1 admission REJECT (potato|
      raw SKIN) · 3 ranking findings · 4 lab samples · 2 BLOCKED on cooking_yield
NEW   cooking_yield returns 1.00 for mackerel/tilapia and 1.20 for salmon, so
      raw-vs-cooked is decided by TABLE COVERAGE, not by the food
NEW   as_eaten needs rework with cut and coating separately modelled, then a
      canary — not abandonment; "meat only" is a lab sample, not a meal
NEW   beef|fried's entire 5-row ladder is New Zealand imported; no domestic
      row was retrieved at all (a coverage observation, not a signing one)
NEW   broccoli| carries two distinct "Broccoli, raw" rows (31 and 34 kcal)
      that the DUPLICATE veto does not catch — different ids, different values
PUSH  724935b + the 0.8 split are NOT pushed. Pushing deploys 15 commits at
      once and the morphology fold is NOT flag-gated — it reaches every user.
```

Kept current. This is the single answer to "where are we"; the phase sections
above are the detail. **Everything open lives here** — a finding recorded only
in a session, a commit message or a side document is a finding that gets lost,
which is how this board came to read "B-1 NEXT" while B-1 was production-proven.

Last reconciled 2026-08-18 (7187742: P17-SB, iOS producer, P17-UA A/B/C, CF9, CF10/P17-UE registered) against the DUPLICATE-SEMANTICS SLICE AND THE BACKEND
FREEZE. What was actually re-read and corrected, rather than date-bumped: the
corrected-sequencing board's P12 line, which claimed the canary "has not
started" — it has run and passed on both settlement branches · the "immediate
next move is P12" paragraph, superseded and marked so · the ROLLOUT IS FROZEN
block, which named only the entity-resolution allowlist and gave the canary as
the reason cohort expansion is prohibited; the reason is now COVERAGE and
`GENERAL_SETTLEMENT_ALLOWLIST` is named alongside it · a new §FREEZE section
recording that backend hardening is closed, what the frozen surface is, and that
the freeze is enforced by a test rather than by this prose · a session entry at
the top of this board, since the previous one was 2026-08-13 and reported a
DEPLOYED sha 15 commits behind. **The measured coverage ordering is flagged as an
open sequencing decision in §FREEZE and deliberately not resolved:** the roadmap
reads oils → materiality → branded, while the measurement puts non-English at
30.4% and the oils' bucket at 5.6%.

Previously reconciled 2026-08-14 against the SEAM-POPULATION SLICE, opened from
merged main after #74. Building the batch-completeness instrumentation found
that a PARTIAL abstention was being written as `DIFFERENT_IDENTITY` at
confidence 0.95 — a durable, confident verdict about a row no model assessed,
which `needs_resolution` would never reopen. It would have corrupted the
86-pair populate run invisibly. Fixed before any live batch ran;
`Qualification` now carries the abstained rows and `build_one` records them
`UNRESOLVED`. Production's turn path was never affected. See the section above
the sequence block.

Previously reconciled 2026-08-14 against a REVIEW OF `2db4029`, which found three
holes in the G1/G2 gates themselves — a blank `source_fingerprint` on all six
human admissions, an expected-query-set that was computed and never asserted,
and a build-path proof that could not run and that nothing imported. All three
are fixed; the fingerprints are BACKFILLED from the seam capture on Danny's
call, with a uniqueness gate.

Driving the now-runnable proof measured that the semantic store does not cover
the seam population. **A first pass reported that gap as "333 pairs" and that
was wrong** — 333 was raw resolver invocations, batched by 3 and retried up to
3 times across 3 runs. The measured figure is **87 unique pairs**, and the
proof now emits pairs, batches and attempts as separately named per-run
counters so the largest can no longer be quoted as the smallest.

The closure condition is now executable and requires BOTH `resolved_this_build
== 0` AND `resolver_calls == 0`; today the first is true and the second is
not. All of it is recorded in the Phase 0 sections at the top of this
document, and the roadmap header — which had been running 2,100 lines behind
this board, still saying "start at 0.9" with three gates owed — now agrees
with it.

Previously reconciled 2026-08-14 against `5a4c7f4` + the G1/G2 hardening, by
re-reading the Phase 0 sections against the code rather than against the
previous board. What that reconciliation actually changed:

```text
Phase 0            CLOSED -> ARCHITECTURE CLOSED, CLOSURE EVIDENCE REFRESHING
                   a4b6d23's proof replays a FROZEN ARTIFACT and never calls
                   build_one, so it showed replay determinism and not
                   captured-source -> production builder -> equality
0.5                implemented -> CAUSALLY WIRED, all six veto reasons
                   consumed (34 of 397 rows refused at the seam)
G1 capture         CLOSED — recorded AT the retrieval seam, 397 rows,
                   fingerprint sha256:5508eb9e matches the build's own, and
                   every committed candidate is present
G2 human authority CLOSED — 6 decisions moved into the ANNOTATION STORE with
                   was/now/reviewer/cause/fingerprint/round, unre-rollable
                   ⚠ "fingerprint" was "" on all six when this line was
                   written; backfilled from the seam capture 2026-08-14
G3 lexical scope   CLOSED — the veto applies only where the CALLER asserts
                   its namespace; the semantic layer names no provider
eight-row delta    5 ADMIT / 3 REJECT -> 6 ADMIT + 2 RETRIEVAL absences
winner accounting  27/27 · 13 SIGNED · 14 HELD — UNCHANGED, and now known to
                   describe a universe the rebuild has not yet reproduced
production         20e3acd, 30 commits behind, deliberately undeployed
```

STILL OWED, and the reason Phase 0's closure evidence is not yet refreshed:
the authoritative rebuild against the seam capture, delta classification by
retrieval | mechanical | semantic | source, re-freeze of moved ladders, and
the poisoned real-build proof. B-1.7a does not start before those.

Previously reconciled 2026-08-11 against the identity-boundary fixes, the 08-10
production trace (user 26, entries 2963–2967), and the code itself. The
**session-close block below the board is the current answer to "where are
we"** — measured state, what is proven on which path, and what is still owed;
the findings ledger under it holds everything instrumental from the B-1.5
build-out.

**✅ CI IS GREEN ON `main` AGAIN as of `2fa8f7c` (2026-08-09), after 3 days
and 50 commits red.** Repaired by #72. Recorded rather than deleted, because
what the outage cost is not visible from a green board.

The cause was never a regression in a slice. `17da24f` dropped asyncpg from
`requirements.txt` for psycopg3 ("chosen over asyncpg because it [supports]
Python 3.14") and left `tests/test_a_full_day_of_food.py` rewriting the engine
URL back to `+asyncpg`, so the shared `app_db` fixture raised
`ModuleNotFoundError` at setup — **115 errors across ten files**, every one the
same import, none of them a real failure. The repair also had to translate
asyncpg's `connect_args={"server_settings": …}` to psycopg's
`options="-csearch_path=…"`; fixing only the URL would have gone green while
silently writing into the shared `public` schema.

**⚠ WHAT THE OUTAGE COST, AND WHY IT IS NOT DISCHARGED BY A GREEN RUN TODAY.**
Among those ten files is `test_b1b1_system_matrix.py` — 22 tests — which IS the
B-1b.1 promotion gate, "production-like system matrix green, real enrichment
exercised". It did not execute anywhere between 2026-08-06 and 2026-08-09,
while the ENTIRE B-1.5E C1/C2 workstream and the ENTIRE P1 pricing workstream
landed on top of it.

Those 22 tests pass now. That is a statement about the code as it stands, not
about the 50 commits as they landed: the evidence the gate exists to collect
was never collected, and cannot be reconstructed after the fact. So B-1b.1 is
**RUNNABLE AGAIN, NOT DISCHARGED.** Whether to re-run the matrix against that
history, or to accept it and move on, is an open judgement — recorded here
rather than settled quietly by the fact that CI is green today.

*(A second job, `battery`, is still red: `ANTHROPIC_API_KEY` is unset and the
job deliberately refuses rather than score a false eval result. That refusal is
correct behaviour on a missing secret — but a job that FAILS on a secret it
cannot see is asserting something it does not know, and a permanently red check
teaches everyone to ignore red. Open finding below.)*

```text
Phase A    COMPLETE          production-verified on a66e9ba8
B-0        COMPLETE          ratchets enforced continuously (C8, C9)
B-0b       COMPLETE          contract surface
B-0c       COMPLETE          serialization, validation, immutability, persistence
B-1.75     COMPLETE          answered quantity is the only quantity authority
B-1.9      COMPLETE          production proven on iOS 2026-08-07
B-1b.1     COMPLETE          absorbed by B-1.9 step 7
B-1b.2     COMPLETE          absorbed by B-1.9 step 7
B-1b.3     CONTINUOUS        usability evidence, NON-BLOCKING
B-1b.4     CONTINUOUS        low-volume organic evidence, NON-BLOCKING
B-1c       COMPLETE          detector coverage and precision
B-1d       COMPLETE          native ID-addressed iOS live

B-1 canonical capability   COMPLETE for allowlisted users
B-1 global promotion       DEFERRED until B-2
B-1 predecessor deletion   DEFERRED until B-2
B-1 legacy                 FROZEN for non-allowlisted users

B-1.5      CLOSED 08-10      machinery + PRODUCTION BEHAVIOURAL PROOF. Readiness,
                             producer, pricing and the generic `unresolved_when`
                             derivation deployed; preparation READS a
                             fingerprinted artifact rather than computing one
                             (404231d). Typed two-field answering proven live on
                             /chat after the `live_field` root cause; both
                             natural-language pricing canaries landed on
                             pre-registered predictions (chicken 445->263,
                             beef 305->250).
                             CANARY: 5 PASSED, F NOT APPLICABLE — the client
                             removes the interaction on tap, so "tap the same
                             chip twice" is a gesture the product does not
                             offer. The real replay vector is a retried
                             delivery; replay is closed by CONSTRUCTION (UNIQUE
                             (operation_id, operation_revision) live in
                             production, claim on every settle) and by harness,
                             NOT by observation. See the canary-F block.
                             CARRIED FORWARD, not blocking: the ranker fail-
                             closed fix is unexercised live (needs preparation
                             as a separate FIELD); extraction survival -> B-1.7;
                             ranker/selection floor -> B-1.8.
CONTRACT   FROZEN 08-07      semantic field registry + rule of three
B-1.5E     C1 + C2 LANDED    C1: core + food domain + both projections + LIVE
                             eval (Sonnet 80% exact, 0 false-compatible at
                             conf>=0.80; Haiku DISQUALIFIED — errors at 0.90+)
                             + qualification before best_candidate (220ae9d).
                             C2: preparation consumes qualified evidence and
                             the token matcher is DELETED, not refined
                             (1e70d88); turn-scoped execution through the
                             existing seam (778ebd0, c2265d6, e757682); fields
                             request evidence and do not own provider
                             lifecycles (652f19f).
                             ARCHITECTURE FROZEN — core/semantic_evidence.py
                             does not get smarter.

P0         LANDED            no row is deleted without a ledger event
                             (d9c6412); a food row and its history commit
                             together on every lane (279e411).
P1 PRICING  LANDED, AUDITED  THE CANONICAL LANE PRICES ITS OWN FOOD. A whole
                             workstream that did not exist at the last
                             reconciliation:
                             P1.1/P1.2 four pricing rungs + portion basis
                             through scaling.py (b92e828); P1.3 the qualified
                             artifact and the root cause of entry 2932
                             (02e45db); P1.4 the legacy pricing seam CUT from
                             the canonical lane (e162e36) — `_analyze_food` is
                             gone from settle, verified: the only remaining
                             mention in core/canonical_pricing.py is its own
                             docstring. Then an adversarial self-audit found
                             four defects in code that was already green
                             (2a88560).
                             SCOPE: the cut covers ANSWER/SETTLE only. The ASK
                             path still reaches `_analyze_food` — see the open
                             findings.
                             ⭐ CLOSED IN PRODUCTION 2026-08-10 (d087e67) —
                             five consecutive settles, every one with
                             `pricing.qualification` ABSENT. See below.
LATENCY    MEASURED          settle path bound (ad8b144), the 3,197 ms hole in
                             settle.pricing split (bdec559), the 2,206 ms
                             bucket inside _analyze_food closed (2ca3c19).
                             SETTLE SOLVED 08-10: 36–70 ms, from 8,225–11,053.
                             STILL ~4–6 s TO A QUESTION, and it is now ~100%
                             interpreter `llm` — P5 (resolving state, latency
                             copy) is the whole remaining user-visible cost.
OWNERSHIP  FIREWALL 08-10    P1(b): a canonically-created row may be mutated
                             only by a DECLARED capability — CANONICAL_OWNER,
                             EXPLICIT_USER_ACTION or RECORDED_REPLAY.
                             INFERRED_INTERPRETATION and UNKNOWN are refused,
                             and UNKNOWN is the DEFAULT, so a new mutation
                             surface breaks until it declares its authority.
                             Took three versions: canonical-only (blocked the
                             iOS editor), a writer-name denylist (right today,
                             silently permissive tomorrow), then the
                             capability. Guard sits at the single mutation
                             boundary `db.queries.update_food_entry`; refusals
                             are RECORDED as `mutation_rejected`. Fired 6x in
                             production before it existed.
TELEMETRY  REPAIRED 08-09    the canonical lane was absent from its own trace;
                             ten defects fixed with ratchets (870b6ea), and an
                             eleventh from review: the funnel's terms are now a
                             defined chain (interpreted → staged → written →
                             committed → visible), none a proxy for another.
                             See the closed block under Open findings. The B-1
                             funnel can now be read per cohort through the
                             conversion step, which the promotion gate needs.

B-1.6      CLOSED 08-10      THE CONDITIONAL LIFECYCLE, END TO END:
                             activate -> render -> answer -> activate dependent
                             -> retract -> rebuild -> stale-proof ->
                             concurrency-safe -> settlement-gated.
                             a  declarative Rule activation, derived edges,
                                acyclic at install, deterministic order; the
                                B-1.5 LOST UPDATE found and closed with a row
                                lock (8f9c440)
                             b  producer: one bump per shape change, removal
                                ON THE WIRE, no transient question, persistence
                                round-trip (2846b98)
                             c  ownership seam from the added-fat phrase tables
                                proven BY POISON, not by grep
                             PRICING IS NOT PART OF THIS MILESTONE. Added-fat
                             pricing is blocked because the SEMANTIC STATE is
                             incomplete (no fat identity in production), not
                             because conditional fields are — carrying that
                             blocker here would blur the boundary this slice
                             paid to make clean. -> B-1.7
B-1.7      NEXT 08-10        a  ADDED_FAT_IDENTITY contract: attribute, patch,
                                canonical vocabulary, candidate provenance,
                                artifact CANDIDATE generation, NO default
                             b  materiality policy: when presence/identity/
                                amount merit a question
                             c  component pricing: identity + amount ->
                                canonical component -> canonical pricer
                             then, and only then, interpreter enrichment. The
                             prompt stays FROZEN until the contract exists.
B-1.7      after B-1.6
B-1.8      after B-1.7
B-2        after those prerequisites
PROMOTION  after B-2 — a DELETION event, not a flag flip
B-3/B-4    ownership consolidation and deletion
C/D/E/F    canonical food, shared contracts, workouts
```

**What changed since `c5d3614`, in one sentence each, because the board above
compresses 25 commits.** B-1.5E finished (C1 and C2 both landed, the superseded
token matcher deleted rather than improved). An entire pricing workstream
appeared and closed: the canonical lane no longer rents `_analyze_food` for
settlement, and the commit that cut the seam was followed by an adversarial
audit of itself that found four more defects. Two P0 ledger guarantees landed.
The settle path was instrumented and three latency holes closed. Then the
2026-08-08 production trace showed the telemetry describing all of it was
wrong, and that was repaired.

**What is NOT proven, stated plainly.** B-1.5's machinery is deployed; a
production turn where preparation actually opens ~~has not been observed~~ was
observed 2026-08-10 — **for exactly one food**. That is an observation, not a
proof, and the distinction is the whole point:

```text
B-1.5 implementation / regression confidence   ~90–95%
B-1.5 production BEHAVIOURAL proof             INCOMPLETE
```

One food, one session, one order of answers. Preparation opened for `chicken`
and for nothing else logged that day, because only `chicken|` carries prepared
artifact evidence — so "preparation works" is currently a claim about a single
identity. B-1.5 does NOT close on it.

**~~The pricing rungs are unit-proven and were audited, but the CI engine that
the B-1b gates name has been red throughout — so "green under Postgres and
real pricing" is currently an untested claim for everything after
`17da24f`.~~** CLOSED 2026-08-10, and the closure is worth reading carefully
because it is a substitute for CI, not a fix to it.

```text
tree      3c693b9  (origin/main d8be23f + the 27-identity pricing artifact)
SQLite    8665 tests   0 failures   0 errors   104 skipped
Postgres  8665 tests   0 failures   0 errors    26 skipped
run with  TZ=UTC, live USDA/Anthropic/Tavily keys, real local Postgres
```

The claim was untested for a reason that is itself an open finding: the
`battery` job fails when `ANTHROPIC_API_KEY` is absent, and the cloud
containers doing the 08-09 work could not run the parts of the suite that need
live keys at all. So the gap was never "nobody ran it" — it was "the engine
that could run it has no credentials, and the engine that has credentials is a
laptop".

**What this closure does and does not license.** It licenses claims about the
code: the pricing rungs, the cut seam, the ledger guarantees and the trace
ratchets all hold under Postgres with real pricing. It does NOT make the
`battery` job authoritative, and a local run is not a merge gate — the finding
below stays open until an unavailable secret is either configured or made a
neutral state. Every future "suite green" line on this board must say which
engine produced it.

**Two Postgres skip counts, and they are not a discrepancy.** 26 under
Postgres against 104 under SQLite is the expected shape (the PG-gated proofs
run; the SQLite-only ones skip). A Postgres run reporting ~82 skips means the
PG-gated proofs silently no-opped and the result is worthless.

### P1 CANONICAL PRICER — CLOSED IN PRODUCTION *(measured 2026-08-10, `d087e67`)*

The stop condition's last line was "production canonical settle succeeds".
Five consecutive settles, one iOS session, user 26:

```text
13:56:28  clarification_answer    36 ms   qualification ABSENT   (preparation, PARTIAL)
13:56:31  clarification_answer    70 ms   qualification ABSENT   (quantity, APPLIED)
13:57:05  clarification_answer    58 ms   qualification ABSENT
13:57:18  clarification_answer    62 ms   qualification ABSENT
13:57:37  clarification_answer    55 ms   qualification ABSENT

settle.pricing 1–5 ms   ·   settle.commit 17–21 ms
```

**36–70 ms against 8,225–11,053 ms on the legacy pricer** — roughly 150×, and
two orders of magnitude inside the <2 s P95 target. `pricing.qualification`
appears on no settle path at all: the model call is gone from the tap, which
is the thing the seam cut was for.

Every stop-condition line now holds: four rungs, portion scaling through
`scaling.py`, canonical settle calling `price()`, the import gate green, a
committed artifact, deterministic pricing, no network/model on hit, the
mackerel and chicken regressions, both suites green (8665/0 — see the closure
above), and this trace.

**B-1.5's owed reversed-order proof passed in the same sequence.**
`FIELDS=2 [quantity, preparation]`; preparation answered FIRST → `PARTIAL`,
zero rows; quantity second → `APPLIED`, one row, created as
`Chicken, roasted 120 g / 200 kcal`. Same terminal state as quantity-first.

**What this does NOT close: B-1.5.** Preparation opened for chicken and for
nothing else in the session, because only `chicken|` carries prepared artifact
evidence. That is the coverage gap in the open findings, not a B-1.5 defect —
but it means "preparation works" is a claim about ONE identity, one session,
one answer order. P1 closes on this trace; B-1.5 does not.

### B-1.5 CLOSURE — A CONTROLLED CANARY EXERCISE *(Danny, 2026-08-10)*

Live traffic is tiny, so waiting for organic coverage is waiting indefinitely.
Closure requires a DELIBERATE production exercise, not an accumulation of
incidental turns. Ten scenarios, all on the allowlist:

```text
 1  ambiguous food            -> preparation question opens
 2  answer                    -> canonical settle
 3  artifact HIT              -> priced from evidence, deterministic id
 4  artifact MISS             -> estimate rung, non-zero, defensible
 5  bare `salmon` vs `grilled salmon`   -> the precision paradox, measured
 6  bare `chicken`            -> artifact miss by design; estimate rung
 7  unrelated message after a clarification   -> the open question survives
 8  replay / idempotency      -> a second delivery writes nothing
 9  Postgres committed state  -> read the rows, never the reply
10  trace chain               -> interpreted -> staged -> written ->
                                 committed -> visible, no term proxying another
```

Scenarios 5 and 6 are the ones that would otherwise be read as bugs: both are
artifact misses BY DESIGN, and a reader who does not know that will file them
twice. Scenario 10 is the funnel definition from the 08-09 review — the
exercise is also the first end-to-end test of that chain.

### ⚠️ THE PRECISION PARADOX — a policy decision, not an accident *(Danny, 2026-08-10)*

**A user supplying MORE precise information currently makes the pricing
evidence WEAKER.**

```text
"salmon"           -> salmon|          13 qualified candidates -> artifact rung
"grilled salmon"   -> salmon|grilled   no evidence             -> estimate rung
```

USDA carries no curated "salmon, grilled" row, so stating the preparation
moves the food from artifact-priced to estimate-priced. Only chicken and beef
have real coverage across grilled/roasted/fried.

**This is architecturally CORRECT under the strict identity contract** —
`salmon|grilled` is a different identity from `salmon|`, and pricing one from
the other's evidence is exactly the substitution the preparation field exists
to prevent. **It is also counterintuitive UX**, and being right about the
contract does not make it right for the user.

Recorded so it cannot become permanent behaviour by default. It is an explicit
B-1.5/B-1.6 decision with at least three candidate resolutions, none free:

```text
FALL BACK      entity|preparation misses -> use entity| evidence, and RECORD
               that the price came from a less specific identity
ASK LESS       do not open preparation when no prepared evidence exists for
               the food — the question implies a precision we cannot price
ACCEPT         keep it, and make the estimate rung good enough that the
               downgrade costs accuracy rather than correctness
```

The first is not a default: it prices a stated preparation from evidence about
a different identity. Whichever is chosen, the choice is recorded here.

### ⭐ THE IDENTITY BOUNDARY HAD TWO CONSUMERS, AND ONLY ONE WAS FIXED *(measured 2026-08-10)*

The precision paradox above is a COVERAGE statement: `salmon|grilled` has no
curated row, so stating the preparation loses evidence that never existed. Two
of the three cases it was measured on were not that. **The evidence existed
and the lookup could not reach it** — a different defect wearing the same
symptom, which is why it hid behind a finding already recorded as understood.

**Production, pre-fix (`d63b894`, 21:40).** Both rows priced from the estimate
rung while the artifact held qualified candidates for exactly these identities:

```text
"I had some grilled beef"    120 g   305 kcal  29.6 g P  est=True
"I had some fried chicken"   120 g   445 kcal  32.0 g P  est=True

artifact:  beef|grilled   5 qualified candidates
           chicken|fried  6 qualified candidates
```

**Consumer 1 — the KEY.** Preparation reaches pricing by two routes, and they
built different keys:

```text
answered as a FIELD    entity="Beef"           prep="grilled"  -> beef, grilled|  MISS
named in the MESSAGE   entity="Beef, grilled"  prep=""         -> beef, grilled|  MISS
                       (the artifact holds it under            -> beef|grilled)
```

Closed by `split_identity` (`1d1ab68`) — the inverse of
`preparation_ontology.name_with`, driven by the DECLARED vocabulary from
`spec_for("preparation")`, so it contains no food name and no preparation
literal. Extending the vocabulary extends it for free; a new food needs
nothing.

**PRE-REGISTERED PREDICTION, then production.** Computed offline against the
committed artifact with the network poisoned, recorded BEFORE the turn was
sent, so the trace could falsify it:

```text
                 BEFORE          PREDICTED            MEASURED (1d1ab68, 22:48)
Fried chicken    445 / 32.0      263 / 36.7  est=F    263 kcal / 36.7 g P  est=False ✅
Grilled beef     305 / 29.6      250 / 34.1  est=F    151 kcal / 29.0 g P  ⚠ see below
```

Chicken is the proof: entry 2966, `canonical:create`, `settle.pricing=2 ms`,
`pricing.qualification` absent, micros present. **69% overcount deleted on one
identity by a lookup change, with no new evidence generated.**

**⚠ BEEF DID NOT TEST THE FIX, AND THE ROW IS NOT WRONG.** The operation
payload shows the preparation was gone before pricing ever saw it:

```text
"I had some grilled beef"    -> {"food": "Beef",          "entity_id": "food:beef"}
"I had some fried chicken"   -> {"food": "Fried chicken", "entity_id": "food:fried chicken"}
```

No preparation field, no preparation in the name. So the turn keyed `beef|`
and priced plain beef correctly at 151 kcal. **An extraction loss, not an
identity-boundary failure — and NONDETERMINISTIC.** Three runs of the SAME
sentence produced three shapes:

```text
21:40   "I had some grilled beef"  ->  food "grilled beef"   kept
22:48   "I had some grilled beef"  ->  food "Beef"           DROPPED
23:26   "I had some grilled beef"  ->  food "Grilled Beef"   kept
```

**RESOLVED on the third run — entry 2968, `20e3acd`, 23:26:43:**

```text
Grilled Beef   120 g   250.0 kcal   34.1 g P   est=False   micros=Y
               predicted 250 / 34.1                              ✅
```

`canonical:create`, `settle.pricing=4 ms`, `settle.commit=21 ms`,
`pricing.qualification` absent. Both natural-language canaries now hit their
pre-registered numbers.

**⚠ AND IT DID NOT TEST THE RANKER FIX.** That run kept the preparation in the
NAME, so it went through the composed route, and the two queries agree there:

```text
ranker with BARE entity "Grilled Beef"  ->  usda:174702
ranker with COMPOSED   "beef, grilled"  ->  usda:174702    same record
```

The key fix alone would have produced 250 kcal. `20e3acd` is proven offline
across all six routes and gated by three mutation-tested assertions; it is
**not yet exercised in production**, because its defect only appears when
preparation arrives as a SEPARATE FIELD and no operation has ever carried one.
Recorded as such rather than folded into the canary pass — a green number that
would have been green anyway is not evidence for the change that produced it.

The extraction loss itself measured at roughly 1-in-3 on this sentence. It is
not the prompt (unchanged), and a word-list rescue in code is forbidden by
standing constraint. The legitimate move is the one used for the key — match
the raw message against the DECLARED preparation vocabulary. **→ B-1.7.**

**Consumer 2 — the RANKER. Found by hunting the beef anomaly, and worse than
the key defect.** `price()` looked the evidence up by the canonical key and
then asked `best_candidate` about the BARE entity:

```text
same ArtifactEvidence, same 5 candidates, opposite outcome
  entity="Beef, grilled"          query "Beef, grilled"  ->  250 kcal   artifact rung
  entity="Beef" prep="grilled"    query "Beef"           ->  REFUSED    no rung
```

A miss falls to an estimate. This FOUND the right evidence and discarded it,
which is indistinguishable from never having generated the artifact — and the
mutation test showed the sharper failure: with a candidate set where something
else matches, the bare query does not refuse, it selects **raw ground beef
(254 kcal) for a grilled query**. Silently pricing one preparation from
another's evidence is precisely what the preparation field exists to prevent.

Closed by `priced_identity()` — composed by `name_with` from the SAME split
that builds the key, so the two consumers cannot drift apart again. Measured
offline, every route converges:

```text
Beef+grilled · "Beef, grilled" · "grilled beef" · "BEEF,  GRILLED"
                                     -> 250 kcal  34.1 g P   usda:174702
"Fried chicken" · Chicken+fried · "fried chicken"
                                     -> 263 kcal  36.7 g P   usda:171053
"Beef" (bare)                        -> 151 kcal  29.0 g P   usda:174730
```

**⛔ AND THE FIRST VERSION OF THAT FIX FAILED OPEN** *(caught in review, Danny,
2026-08-10)*. `_ranker_query` wrapped composition in a bare `except` and
returned `entity`:

```python
try:
    return priced_identity(entity, preparation) or entity
except Exception:
    return entity                      # <- the defect, behind an except
```

By the time it runs, the artifact has ALREADY been loaded under
`beef|grilled`. Falling back to "Beef" therefore hands a PREPARED candidate
set to a query that cannot distinguish preparations — the precise sequence the
commit had just declared must never happen, reintroduced by its own error
handler. The docstring said *"a rung that cannot rank is a rung that cannot
price"* while the code did the opposite; the sentence was right and the
implementation had to follow it.

Now raises `IdentityCompositionFailed` — deliberately NOT a `PricingRefused`,
so the rung loop drops that rung and the meal still settles from the estimate
below it. Failing one rung is the correct blast radius: refusing the whole
meal would trade a preparation mismatch for a lost log.

Three gates, all mutation-tested against the restored fail-open: a broken
composition must not rank prepared evidence, an unregistered preparation falls
through instead of guessing, and a grilled meal may never return the raw row's
254 kcal.

**The generalisable lesson.** A canonicalisation is only as good as its least
careful consumer. `key` and the ranker query were derived independently from
the same inputs, so fixing one produced a system that could FIND evidence it
could not USE — a state neither route exhibited before the fix, and one the
green suite could not see because no test priced the same identity by two
routes and compared. The gate that now exists asserts exactly that equality.

### ⛔ P1(b) — THE LEGACY CORRECTION PATH OVERWRITES CANONICAL ROWS *(measured 2026-08-10)*

Found in the same session, and it is a live data-loss path on the canonical
lane. Recorded here rather than in Phase C because C-1..C-3 describe
corrections as a FUTURE canonical migration; this is a legacy writer reaching
a canonical row TODAY.

```text
13:56:31  created  entry=2947  canonical:create                 Chicken, roasted 200 kcal
13:56:43  updated  entry=2947  structured_food:food_interpreter_v2   -> Salmon 263 kcal
```

The user said **"I had some salmon"** — a plain new-food statement, no
correction language — twelve seconds after logging chicken. The legacy
interpreter classified it as a CORRECTION and mutated the canonical row in
place. The reply was *"Updated to salmon."* The chicken log is gone; it
survives only in its `created` event, which is the 08-07 P1 ledger fix
earning its place.

Three properties make this the worst class found so far:

```text
DATA LOSS    a committed canonical row lost its identity, silently
OWNERSHIP    a LEGACY writer mutated a row owned by the canonical lane —
             the migration rests on canonical rows having one owner
INVISIBLE    no error, a plausible reply, and a board that looks right
```

**IT FIRED SIX TIMES, not once.** Over the whole ledger, food-row updates come
from exactly four sources, and only one has ever touched a canonically created
row:

```text
updates to food rows                    of those, on a CANONICAL row
structured_food:food_interpreter_v2  92          6      <- every one
legacy                               36          0
ios_edit                             25          0
ledger_undo:v1                        1          0
```

**THE RULE TOOK THREE VERSIONS, and each failure taught the next.**

**v1 — "only the canonical lane may mutate a canonical row."** The obvious
reading of the incident. The suite refused it in under a minute: `ios_edit` is
a user opening the editor on their own row and has every right to.

**v2 — a DENYLIST of writer-name prefixes** (`structured_food:*`, `legacy`).
It produced the right answer for all four callers that exist today, passed
every gate, and was still wrong. A future inferred writer — `coach_agent:v3` —
would mutate canonical rows because nobody remembered to extend a tuple. And
`mutation_rejected` could NOT have caught it: an undenied writer is never
rejected, so no event would exist to say it escaped. *A permission system
whose failure mode is silence is the failure mode this migration exists to
remove* (Danny, 08-10).

**v3 — a CAPABILITY carried by the call.** The distinction is INFERRED versus
EXPLICIT, and the mutation declares which it is exercising:

```text
ALLOW   CANONICAL_OWNER           the owner
ALLOW   EXPLICIT_USER_ACTION      a human pointed at this row
ALLOW   RECORDED_REPLAY           replays an inverse that was WRITTEN DOWN
DENY    INFERRED_INTERPRETATION   a model DECIDED prose meant this row
DENY    UNKNOWN                   nothing was declared  <- the default
```

`ios_edit` is not trusted because its string starts with `ios_`; it is trusted
because the mutation declares that a user pointed at a row. `ledger_undo` is
not trusted because it is on a list; it is trusted because it declares a
recorded inverse. **Encode the concept, not the current names of the four
callers.**

**UNKNOWN IS THE DEFAULT AND IS REFUSED**, so a new mutation surface —
`apple_watch_edit`, `voice_edit` — BREAKS until it declares its authority.
That is intended: making a surface state what authority it exercises costs one
keyword, and silent permission destroyed six canonical rows in production.

**One call site, two authorities**, which is the clearest argument for the
capability: `ledger_undo` reaches the SAME tool dispatch as the interpreter by
emitting an `update_food_entry` tool call. Nothing about the caller
distinguishes them — only what the mutation declares.

Implemented in `db.queries.update_food_entry` — the single function every
food-row update funnels through, so the guard holds whichever interpretation
path reaches it. A special case in the correction classifier would only have
covered the one route observed failing. Ownership needs no new column:
`creating_source()` reads the row's own `created` event, which invariant I3
already guarantees is unique.

**The refusal is RECORDED, not merely raised** — a `mutation_rejected` event
carrying owner, writer, declared authority and the attempted changes. A firewall that silently
drops writes is its own blind spot, and that record is how we will know when
the legacy correction route can be deleted rather than guessed at.

**Pre-ledger rows FAIL OPEN and are COUNTED.** Ownership cannot be established
without creation provenance, and refusing those would break corrections across
the whole historical corpus. Every such call emits
`event=ownership_check result=unknown_provenance`, so the size of that corpus
is measurable and the exception can eventually be removed on evidence rather
than on nerve.

Gates: `tests/test_a_legacy_writer_cannot_touch_a_canonical_row.py`, sixteen
of them, mutation-tested in THREE directions — disabling the guard turns it
red, making it over-broad turns it red, and *permitting UNKNOWN* turns red
exactly the gate the denylist could never have had. An AST gate holds that no
call site mutates a food row without declaring authority.

⚠️ **Cost, measured:** the firewall adds one `SELECT` per food-row update, and
the full suite moved from ~5 min to over 10. Irrelevant for a single user
turn; recorded because it is a per-mutation read that will scale with write
volume.

### TWO ROLLOUTS ARE LIVE, AT DIFFERENT WIDTHS *(measured 2026-08-09)*

Recorded on the board because reading either one as "the rollout" produces a
wrong answer about who is exposed to what.

```text
nutrition resolver   LIVE, UNRESTRICTED   everyone. No allowlist, no canary
                                          percentage, not halted.
B-1 clarification    ALLOWLIST ONLY       user 26 and internal testers.
```

The resolver's width was an OPEN QUESTION in
`docs/HARDENING_JOURNAL.md` ("`NUTRITION_RESOLVER_MODE=shadow` in production,
`live` in the docs — unresolved"), and the answer had been printing on every
food turn the whole time. `cohort=live` is reachable through exactly one path
in `skills/nutrition/canary.cohort_label`, and it requires mode `live` with no
allowlist entry, no canary bucket and no halt. The journal entry is now closed
against that evidence.

**Why it stayed open while being continuously observable.** Both rollouts wrote
a field called `cohort` into the same log stream with overlapping vocabularies,
so the resolver's `live` and B-1's `allowlist` read as a contradiction about
one thing rather than as two facts about two things. Split into
`resolver_cohort=` and `b1_cohort=` on 2026-08-09.

**The consequence for evidence classes**, which the table further down governs:
there is **no control group for the resolver**. `cohort_label`'s own comment
makes the point — unrestricted live means everyone is treatment, and labelling
them `control` "made canary-versus-control reports compare the new path against
itself". Any resolver-quality claim from here is a before/after over time, not
a comparison; B-1's allowlist evidence is unaffected and remains what it was.

**Promotion and deletion are deliberately batched after B-2. This is a
ROLLOUT decision, not an architectural dependency.** Canonical development
continues for allowlisted users only. Nothing in B-1.5 through B-2 waits on
promotion, and promotion waits on all of them.

## Companion documents — what each owns

This document is the SEQUENCING AUTHORITY. The detail lives beside it. The
table below was reconciled 2026-08-07; the **freshness** column was checked
2026-08-09 against `870b6ea` and is deliberately separate, because "this
document owns X" and "this document is currently true about X" are different
claims and conflating them is how the board came to read `B-1 NEXT` while B-1
was production-proven.

| document | owns | fresh as of 08-09? |
|---|---|---|
| `ARCHITECTURE_CONTRACT.md` | executable invariants C1–C9, plus the Semantic Extension Contract, the one lane gate, and the no-unledgered-delete rule | assumed current — invariants are test-enforced, so drift fails rather than rots |
| `CLARIFICATION_MIGRATION.md` | Phase B design decisions | **STALE** — says B-1.5 is "blocked on B-1.5E"; that block lifted when C2 landed (`1e70d88`) |
| `CHIP_GENERATION_MIGRATION.md` | option pipeline + status ledger | not re-checked |
| `DELETION_INVENTORY.md` | cleanup scoreboard | **owes a line** — the P1.4 seam cut removed `_analyze_food` from the canonical settle path, the first real deletion since 08-05 |
| `WORKOUT_CONTRACTS.md` | Phase E/F shapes | not re-checked; no Phase E/F work has landed |
| `QUICK_LOG_PROMOTION_RECORD.md` | Phase A evidence and the prove→promote→delete template | current — Phase A is closed |
| `audits/NUTRITION_LANE_AUDIT_2026-07-28.md` | the standing nutrition-lane audit | updated 08-09 — finding **C5** closed for `Stage.INTERPRET`, still open for `Stage.PROMOTE` |
| `tests/evidence_corpus/` | captured RAW provider records (USDA, OFF, Tavily) + human-reviewed `GROUND_TRUTH.md` | not re-checked |

**Two of these are knowingly stale and are NOT being fixed silently.** Naming
them here is the point: a companion document that quietly disagrees with the
board is worse than one openly marked stale, because the reader cannot tell
which to believe. Whoever next touches Phase B design owes
`CLARIFICATION_MIGRATION.md` its correction.

Enforcement lives in `tests/test_the_canonical_invariants.py` and the suites
named in the contract document.

**The telemetry ratchets are enforcement too, and they live outside that file**
— `tests/test_the_food_log_stream_parses.py` (every measurement line parses
strictly; no prose, no duplicate keys, no empty values),
`tests/test_the_canonical_lane_is_on_the_trace.py` (the funnel-coverage ledger,
which fails in BOTH directions so the audit's stage count cannot drift from the
code again, plus `TestNoTermIsAProxyForAnother` holding the five-term chain),
and `tests/test_the_b1_counters_mean_their_names.py`.

All four are written to fail on the code as it was, not to assert that an edit
survived. Each was verified by reverting the fix it guards in a detached
worktree and confirming it goes red — a ratchet that cannot fail is a comment
with a slower test suite, and sixteen of those were deleted from this branch
for exactly that reason.

## ⛔ B-1.5 LOST UPDATE — a live correctness defect found while building B-1.6

Classified as B-1.5, not B-1.6 debt. It is reachable on the deployed system
today: two chips on screen and a fast pair of taps, or one tap plus a retried
delivery.

`hold_answer` rewrote the WHOLE `answered` map from an `OwnedOperation`
hydrated by an UNLOCKED read:

```python
held = dict(owned.answered or {})               # read, unlocked
held[patch.field_id] = patch
owned.row.canonical_payload = json.dumps(...)   # blind write
```

Two answers arriving together each read the map, each add their own patch,
each write everything. **Last write wins, one answer is silently lost, and the
reply confirms it.** B-1.6 did not introduce this; it made the blast radius
obvious, because retraction and activation would have ridden the same unsafe
write.

**`save_revision` is a genuine compare-and-swap and CANNOT fix it.** Holding an
answer deliberately does not move the revision — the other chips are on the
user's screen — so both writers satisfy `WHERE revision = N` and both succeed.
The read-modify-write itself has to be serialized.

**THE FIX IS A ROW LOCK, NOT A SECOND VERSION COUNTER** *(Danny's call)*. A
payload-version column would solve it and would introduce a new persistence
concept whose only job is protecting a very short read-modify-write that
Postgres already serializes. No migration; main auto-deploys, and the schema
did not need to change.

`pending_repository.locked_operation` is a SHARED PRIMITIVE, not
`with_for_update()` buried in `hold_answer`. B-1.6 retraction and B-1.8 repair
need the identical guarantee, and a boundary only one caller uses is a
boundary the second caller routes around.

```text
load the row FOR UPDATE
decode answered/revision/payload FROM THE LOCKED ROW
apply the patch  ->  reconcile  ->  retract
one revision bump IF the active-set shape changed
write the complete payload, flush, release with the transaction
```

**⭐ THE SUBTLE FAILURE, AND THE ONLY GATE THAT CAUGHT IT.** A correct lock
still protects a stale read if the merge target predates it:

```python
locked = await repo.locked_operation(db, ...)   # correct lock
held = dict(owned.answered or {})               # STALE MERGE
```

That mutation was run. **Both timing-based overlap gates PASSED under it** —
the scheduler happened to serialize the writers — and only the structural
assertion that `held` derives from the locked row went red. A concurrency
test that can pass because scheduling was kind is theater; the anti-vacuity
checks are what make these evidence:

```text
gate 1  two same-revision holds, different fields   RED without FOR UPDATE
gate 2  shape-changing answer vs concurrent answer  RED without FOR UPDATE
gate 3  aborted writer leaks nothing to the next    green
gate 4  merge reads the LOCKED row                  RED on correct-lock/stale-merge
gate 5  uncontended acquire is cheap (<250 ms)      green
        gate 1 also asserts max(lock_wait_ms) > 0 — if neither writer waited,
        the sections never overlapped and the run proved nothing
```

Postgres only. SQLite is single-writer and would prove the lock unnecessary
rather than that it works.

**No timeout and no retry, deliberately.** These rows are per-operation and
per-user; contention is a measured question, not an assumed one.
`operation_lock_wait_ms` is emitted on every acquire so the measurement exists
before anyone tunes anything. Two structural ratchets keep the section honest:
`with_for_update` appears nowhere in `core/` outside the repository, and
`hold_answer` awaits nothing from the provider/model/pricing set while holding
the lock.

## B-1.6a — CONDITIONAL ACTIVATION AS A STATE TRANSITION *(2026-08-10)*

```text
previous_active -> patch -> resolved_state -> desired_active -> RECONCILE
                      still_active / newly_active / newly_inactive / retracted
```

**Retraction kills the VALUE, not just the chip.** "1 tbsp of oil" then
"actually, no oil" must remove the tablespoon from settlement; hiding its chip
while the patch stays in `answered` prices fat the user just said was not
there. Invalidation history is durable and separate from current truth, so
B-1.8 can tell "never active" from "answered, then invalidated".

**⭐ PURITY IS STRUCTURAL AFTER REVIEW, AND THE FIRST ATTEMPT WAS NOT.**
`active_when` began as a callable with a declared `depends_on` beside it —
a contract at one end and an assumption at the other, the shape this migration
keeps finding. Refusing `async def` looked like a fix and proves nothing: a
SYNCHRONOUS closure can capture a provider, read a module global, consult a
cache, and its `depends_on` is an unverifiable claim, which leaves the cycle
check formally green and semantically false.

`active_when` is now a declarative `Rule` — `Present`, `IsTrue`, `Equals`,
`All`, `Any_`, `Not`. The engine evaluates; the rule only describes.
`depends_on` is DERIVED by walking the rule, so there is no second declaration
that can disagree with it, and there is nowhere in a rule to put a provider.

Registration refuses a callable outright, a self-dependency, an empty rule and
an unknown dependency; the graph is asserted acyclic at INSTALL, where a cycle
breaks the process instead of presenting as a question that silently never
opens. `activation_order()` is deterministic topological — field order reaches
the iOS payload, and order that depends on registry insertion is a rendering
difference with no semantic cause.

**The commit boundary asserts, never derives.** A second policy there would be
the two-owners defect wearing a safety vest.

**The consumer ratchet found a live trap.** `register()` had refused an
undeclared CONDITIONAL field since the contract was written, and NOTHING read
the other end — a conditional field would have been admitted, passed its
check, and then never activated. Both ends are ratcheted now: every registered
conditional must be observed being evaluated by the reconciler.

**Not built:** the producer half. Nothing renders the new fields as chips, so
`added_fat_present` / `added_fat_amount` are reachable by patch and not by a
user. B-1.6b resumes from here.

**`ADDED_FAT_PRESENT` materiality stays in B-1.7.** B-1.6 demonstrates the
lifecycle once presence is canonically known; deciding when silence about fat
is suspicious enough to ask is accuracy policy, and blurring that line
immediately after deliberately separating it would waste the separation.

## B-1.6b — THE PRODUCER HALF: REBUILDING THE ANSWER SURFACE *(2026-08-10)*

B-1.6a made activation a state transition in STORAGE. A field could become
active, become inactive, and have its answer retracted, and none of it reached
the screen. `core/interaction_generation.py` regenerates the surface itself.

**REMOVAL HAPPENS ON THE WIRE, NOT ONLY IN STORAGE** *(Danny's addition)*.
Marking a field inactive while the client keeps rendering its chip leaves a
tappable control for a question the system no longer has, and a tap on it is
an answer to nothing. `yes -> amount opens -> no` returns an interaction in
which the amount field is PHYSICALLY ABSENT.

**AND PERSISTENCE ROUND-TRIPS** *(also Danny's)*. The gate is
`reconcile -> rebuild -> persist -> RELOAD -> wire_payload`, never
`rebuild -> wire_payload`. Producer state that lives only in the answer turn's
memory is state a reload cannot reproduce, and reload is the NORMAL case: a
relaunched app, a second device, another worker.

**⭐ AND THE ACCEPTANCE LIST FOUND A REAL B-1.6a SEMANTICS BUG that all 19 of
its own gates missed.** `active_attributes` treated EVERY registered
unconditional field as active. On an operation that only asked about quantity,
answering it therefore reported:

```text
newly_active=(preparation,)     ->  changed=True  ->  revision bump
```

A phantom shape change that would have invalidated every chip on the user's
screen for nothing. Unconditional membership is NOT this pass's to decide — it
is settled by the ask producer's materiality pass. `active_attributes` now
takes a `baseline` of what the operation is actually asking about and computes
only the CONDITIONAL layer. Settlement narrowed to match: *every resolved
conditional field must be in the current active set*, because an unconditional
answer is always legitimate and the commit boundary has no business
re-litigating materiality. Found only by the "a value change must not bump"
criterion.

The acceptance contract, each behavioural line with the mutation that reddens
it:

```text
built from the registry/spec, not ad hoc          ENUMERATED+vocabulary -> select
                                                  MEASURED -> free-text fallback (C15)
active-but-resolved never renders                 M2 red
one shape change = exactly one revision bump      M3 red
every rendered field rebuilt at the new revision   M3 red
no mixed-generation interaction can persist       structural — __post_init__ refuses
value change without shape change: no bump        M4 red
present=yes + amount known: no transient question M2 red
stale taps rejected without mutation              field_id embeds the revision
deterministic topological reconstruction          activation_order()
wire payload persisted before it is returned      same write, same lock
producer consumes reconciliation, never recomputes AST gate
removal ON THE WIRE, field physically absent      M1 red
round trip reconcile->rebuild->persist->reload    green
```

**⚠ A FOURTH INSTRUMENT MATCHED THE WRONG THING.** B-1.6a's "policy does not
decide activation" gate grepped file TEXT for `active_when`, so it fired on
the two modules whose COMMENTS explain why they must not read it. A gate that
cannot tell an access from a sentence about an access punishes the
documentation it asked for. Rewritten over the AST. The pattern is consistent
enough to name: **grep-shaped gates check spelling; AST-shaped gates check
structure.**

**Still not wired:** `ADDED_FAT_PRESENT` has no `unresolved_when`, so it opens
only when the interpreter volunteers it. That is B-1.7 by the directive's own
split, and giving it a predicate here would blur the line immediately after
deliberately drawing it.

**Next is B-1.6c** — the canonical lane stops consulting `core/portions.py`'s
added-fat phrase table (`_ADDED_FAT_CAL`, `_ADDED_FAT_NEGATIONS`,
`added_fat_calories`, `addressed_added_fat`), which is a second semantic owner
for eligible turns. NOT a global deletion: legacy keeps them, and they go on
the deletion inventory for the promotion boundary. Proven by monkeypatching
those helpers to RAISE and showing the canonical path still completes — much
stronger than grepping for imports, because it proves the seam is cut rather
than merely unreferenced.

## B-1.6c — THE OWNERSHIP SEAM, PROVEN BY POISON *(2026-08-10)*

`core/portions.py`'s added-fat phrase table is a SECOND SEMANTIC OWNER for a
question B-1.6 now models as fields. NOT deleted — legacy keeps it, and it is
recorded in `DELETION_INVENTORY.md` for the promotion boundary. The claim
established today is narrower: **canonical cannot reach it.**

**POISON, NOT GREP.** An import gate proves a module is not NAMED; it does not
prove it is not REACHED, and `settle -> canonical_pricing -> a shared helper`
is exactly how a seam looks cut and is not. All four owners are replaced with
objects that raise — the TABLES as well as the functions, on membership,
iteration, indexing, `get`, `items` and `len`, so a caller that inlined a
lookup cannot sail past a patched function.

```text
canonical prices with all four raising        artifact rung, 250.0 kcal
does NOT degrade to a weaker rung             estimate offered at 999, refused
numbers identical poisoned vs clean           byte-for-byte
legacy still depends on them                  a SEAM, not a deletion
canonical imports no raw-utterance helper     broader than the four names
```

**⭐ THE NEGATIVE INVARIANT IS THE LOAD-BEARING ONE.** "Canonical completed" is
not the claim. A path that quietly falls to the estimate rung when the phrase
tables explode is still DEPENDENT on them — it has converted a hard failure
into a silent accuracy loss, which is worse because it does not announce
itself. So the gate offers a 999-kcal estimate and requires the artifact rung
anyway.

**⭐⭐ THE "LEGACY STILL DEPENDS" GATE IS DELIBERATELY INVERTED.** It FAILS if
nothing outside `portions.py` calls the helpers, because at that point they
are dead code and belong in the deletion inventory's done column rather than
guarded by a seam test protecting nothing. A guard whose subject has
disappeared is one more instrument reporting success without testing anything.

**⭐⭐⭐ THE BOUNDARY IS GATED BY PATTERN, NOT BY NAME.** The rule is that
canonical settlement derives nutrition ONLY from canonical resolved state and
canonical evidence, never from phrase-table interpretation of the original
utterance. The gate reads the set of raw-text helpers OFF the `portions`
module rather than hardcoding four strings, so a fifth written tomorrow is
covered the day it exists. Gating the four names would let the identical
second-owner pattern return under a new one.

Mutation: planting `added_fat_calories(query)` inside the artifact rung
reddens FOUR of the five gates independently.

## ⛔ B-1.6d IS BLOCKED ON A CONTRACT, NOT AN IMPLEMENTATION

Measured across 12 production operations, the staged item carries:

```text
food · amount · unit · calories · protein · carbs · fats
entity_id · basis · meal · branded
```

**No fat identity.** `entity_id` is `food:beef` — the food, not what it was
cooked in. So `identity + amount -> canonical component -> canonical pricer`
cannot be composed from what interpretation produces, and the field model
needs `ADDED_FAT_IDENTITY`.

**Do not default to "oil" to reach pricing.** The legacy table is its own
argument: one tablespoon of "added fat" spans 60–180 kcal (marinade 60,
teriyaki 70, mayo 90, butter 100, oil 120, ranch 145, alfredo 180). A default
prices butter 20% high and alfredo 33% low — the same heuristic under a typed
interface, and worse than the honest one because it looks settled.

The shape when it unblocks: `ADDED_FAT_IDENTITY` conditional on
`ADDED_FAT_PRESENT` alongside `ADDED_FAT_AMOUNT`, both on the same rule, so
the graph stays acyclic and an amount is never priced without something to
price. Whether identity is asked or inferred is B-1.7's question.

## ⚠ THE EIGHTH BAD INSTRUMENT — A MUTATION THAT DID NOT MUTATE

Recorded with the other seven rather than fixed quietly, because it is the
same family: **the verifier itself has to be falsifiable.**

Closing B-1.6 on the board added a gate asserting the board still names
`ADDED_FAT_IDENTITY`. It was "mutation-tested" by replacing that string in the
board section — with `replace(..., 1)`. The board holds THREE occurrences, so
the assertion still found one, the suite stayed green, and **the green was
read as "the gate holds" when it meant "the mutation never landed."**

```text
mutation -> RED     the mutation took effect AND the gate caught it   evidence
mutation -> GREEN   the gate is vacuous OR the mutation never landed  AMBIGUOUS
```

The loophole is one-directional, which is why it survived: every other
mutation this session went red, and a red proves reachability and
observability by existing. A GREEN mutation result proves nothing at all
without inspecting the signal, and that is precisely where inspection stops.

**THE RULE.** A mutation test is evidence only if the mutation changes the
exact value or control-flow condition the assertion consumes. Three checks
around every serious ratchet:

```text
REACHABILITY   the mutated branch or value is actually exercised by the test
OBSERVABILITY  the assertion reads a value DOWNSTREAM of the mutation
CAUSALITY      the gate fails for the INTENDED reason, not because an
               unrelated guard tripped first — check the failure NAME
```

Sharpest form: assert the pre/post signal itself before asserting the gate.
For an activation ratchet, first show the mutated implementation computes a
DIFFERENT active set, then require the behavioural gate to go red. That closes
the loophole rather than documenting it.

So the standard is **"mutate the guarantee, verify the mutation took effect,
then require the gate to fail"** — not "edit something nearby and observe zero
failures."

Redone with all three occurrences replaced:

```text
drop ADDED_FAT_IDENTITY from the board   1 failure
drop B-1.7 from the board                1 failure
restored                                 0
```

**SCOPE OF THE INVALIDATION.** The mutation evidence for THAT gate was invalid
until this rerun; nothing else is affected. Every other mutation in this
session produced a named failure, which establishes reachability and
observability by construction, and the failure names were checked, which
covers causality. Suite evidence is independent of all of it: the
SHA-and-count-qualified frozen runs stand on their own.

## B-1.7a — THE ADDED-FAT IDENTITY CONTRACT *(2026-08-11)*

```text
ADDED_FAT_PRESENT
  |- IsTrue -> ADDED_FAT_IDENTITY     SIBLINGS, never a chain
  \- IsTrue -> ADDED_FAT_AMOUNT
```

**THE FAT IS A FOOD, and that is the whole design.** `olive_oil` is not a
modifier worth 120 kcal; it is an ingredient with its own rows, density and
micros, so B-1.7c prices it by COMPOSITION through the canonical pricer rather
than by constant. A typed field resolving to "+120 kcal" would be
`_ADDED_FAT_CAL` with better manners. `SetAddedFatIdentity` therefore carries
an `entity_id`, and `Pricing.NONE` — the chicken is still chicken; identity
names a SECOND food rather than changing which food we asked about.

**⭐ EVIDENCE OFFERS CANDIDATES, NEVER TRUTH.**

```text
ALLOWED    food + preparation -> plausible added-fat identities
FORBIDDEN  food + preparation -> a RESOLVED added-fat identity
```

A resolved identity carrying artifact provenance would mean the system decided
what the user cooked with — the substitution the artifact's candidate-set
design exists to prevent, arriving by another door.

**⭐⭐ AMOUNT DOES NOT DEPEND ON IDENTITY.** *"About a tablespoon, not sure
what oil"* is truthful and useful; a chain would discard that fact to satisfy
a topology. Which of the two open fields is ASKED is presentation and B-1.7b
policy — B-1.6b already separated what is ACTIVE from what RENDERS.

**⭐⭐⭐ AN ID THE PRICER CANNOT ACT ON IS INERT — and every id here is,
today.** Measured 2026-08-11: the pricing artifact holds 27 entries and NONE
is a fat. `olive oil`, `butter`, `vegetable oil`, `coconut oil` and
`mayonnaise` all MISS. `preparation_ontology` paid for this constraint
already: a chip that changes nothing is worse than no chip, because its usage
rate looks like engagement.

So the field registers `Evidence.GENERATED` — not offered where there is
nothing to build an option from — and `added_fat_ontology.priceable()`
measures the gap against the artifact rather than asserting confidence. **The
unblocking step is extending the artifact's seed set to cover these foods,
which is BUILD time, not turn time.** Until then the contract exists, is
answerable by an explicit patch, and offers nothing it cannot price.

**NO DEFAULT, AND NO `UNKNOWN` MEMBER.** `resolve()` returns None for an id it
does not hold; returning a fallback would price an identity we do not have as
one we do. Preparation has an UNKNOWN member because an unknown preparation
legitimately leaves the food's name alone — there is no equivalent here, since
"some fat, unspecified" would immediately need a calorie value, which is the
default this design refuses.

**DRESSINGS AND SAUCES ARE DELIBERATELY EXCLUDED.** Ranch, caesar, alfredo,
vinaigrette, marinade and gravy are COMPOSITE FOODS with their own amounts,
not fats. `_ADDED_FAT_CAL` fused them together and that fusion is how it
became a phrase table; folding them in here would make one field mean two
things. They belong to a future `added_sauce` field.

Mutations, each with its SIGNAL verified before the gate was trusted — the
standard the eighth bad instrument produced:

```text
amount chained to identity     depends_on -> ('added_fat_identity',)   2 red
resolve() falls back           'schmaltz' -> AddedFat(olive_oil)       1 red
ONTOLOGY not GENERATED         evidence -> 'ontology'                  1 red
a sauce joins the vocabulary   OFFERED gains 'ranch'                   1 red
```

**Owed by B-1.7a before it can close:** artifact coverage for the five fats,
so `priceable()` is non-empty and the field can actually be offered.

## ⛔ PRICING-SPINE BUILD DETERMINISM — OPEN *(2026-08-11)*

**The artifact is deterministic at READ time and not at BUILD time.** Same
seeds, same code, same fingerprints, two runs, different qualified evidence.
`mackerel|roasted` went 4 candidates to 1, losing three textbook rows
(`mackerel, king / spanish / Pacific, cooked, dry heat`).

**⭐ THE SYSTEM-WIDE INVARIANT THIS PRODUCED — larger than pricing:**

```text
AN ABSENT ANSWER MUST NEVER BE REPRESENTABLE AS A NEGATIVE ANSWER.
```

The failure was never "the model chose the wrong candidate". It was **"the
model returned no usable verdict, the system recorded that as qualification
output, and evidence disappeared silently."** Absence, timeout, malformed
output and low confidence must all be incapable of becoming evidence
DELETION. Treat this as a design rule for every layer, not a pricing fix.

### Cause A — STRUCTURAL. Closed.

`RESOLVER_MODEL = claude-sonnet-5` emits thinking blocks and `max_tokens`
bounds thinking AND text together, so the text budget was whatever thinking
left. Six runs on the real prompt:

```text
thinking + text   out=3000  stop=max_tokens   text truncated mid-JSON
thinking ONLY     out=3000  stop=max_tokens   NO TEXT BLOCK AT ALL
thinking + text   out=2498  stop=end_turn     valid
                                              THREE OF SIX FAILED
```

Both modes abstained the ENTIRE batch. Fixed by: `thinking` disabled (4/4
valid, output 2371-3000 -> 544-620 tokens); `_text_of()` as a TOTAL function
raising the named `ResolverReplyUnusable`; `_elements()` row-local parse
recovery; `_retain_unexplained()` non-destructive rebuild; a pre-retention
`pricing_evidence_v1.raw.json` snapshot; and a raw-vs-final report on every
build. Qualifier on frozen rows: **6/6 identical**, fresh context per run.

### Cause B — SAMPLING. Open, and NOT fixable by configuration.

Post-fix builds still diverged — `beef|` and `mayonnaise|` lost candidates,
`salmon|roasted` vanished as a key. One row scored `DIFFERENT_IDENTITY` at
0.6 / 0.7 / 0.75 and `COMPATIBLE_SPECIALIZATION` at 0.8 across runs;
`MINIMUM_IDENTITY_CONFIDENCE` is a threshold, so rows cross it or do not.

**`temperature=0` returns `400 — temperature is deprecated for this model`.**
The knob does not exist. So determinism cannot be bought by configuring the
model; it has to come from giving the model less to decide.

### THE STATUS WORDING, and it is deliberately not "reproducible"

```text
batch-destructive failure mode     CLOSED
silent evidence deletion           GUARDED
raw generation reproducibility     STILL OPEN
production artifact stability      PROTECTED BY RETENTION (a weaker claim)
```

### THE FOUR OWNERSHIP LAYERS *(Danny, 2026-08-11)*

Formalised so this class of failure cannot return under a different model or
a different artifact builder:

```text
EVIDENCE           what source rows exist        deterministic, preserved,
                                                 versioned
ELIGIBILITY        which rows are MECHANICALLY   deterministic CODE
                   compatible
SEMANTIC ADVISORY  what the model thinks about   NON-AUTHORITATIVE metadata;
                   genuinely ambiguous cases     may never delete evidence
RANKING            which eligible evidence wins  deterministic
```

**Next slice is an AUTHORITY MIGRATION, not another configuration tweak.**
Move the mechanical dimensions into code first — raw vs cooked, preparation
compatibility, branded vs generic, unit compatibility, duplicate equivalence,
obvious identity conflicts — each typed, testable and versioned. The model
keeps classification, confidence, reason and ambiguity, and keeps no power to
remove a durable row.

**NOT REOPENED by this finding, because it is UPSTREAM of them:** B-1, B-1.5,
B-1.6, concurrency locking, canonical settlement, replay/idempotency, the
ownership seam.

**Sequencing:** land safety fix -> deterministic qualification extraction ->
raw reproducibility proof -> permanent gates (against the RAW artifact) ->
five fats -> 27-entry diff -> close B-1.7a -> B-1.7b materiality -> B-1.7c
composition -> B-1.8 repair -> promotion.

## Session close — 2026-08-10, measured state and what it cost

Written last, against the numbers rather than the intent. The unflattering
items are first on purpose: a board that records only what worked is a board
that will let the same failure be bought twice.

### What I reported before it was true

**The reversed-order proof was overstated.** It was reported as passing on the
strength of a run that went through the STRUCTURED endpoint — explicit
`field_id` on every answer, which never consults `live_field` at all. Through
`/chat`, the modality a user actually types into, it could not have worked: the
free-text path was pinned to `fields[0]` and read every further answer against
quantity. Danny's independent read — "implementation confidence 90–95%,
production behavioural proof 25–35%" — was the correct one, and the gap between
those two numbers is exactly the gap between "the code is right" and "the code
is right on the path traffic uses". **A proof is about a PATH, not a feature.**

**A gate I wrote to guard the root cause could not fail.** The first
`live_field` gate asserted that `open_fields` was called *somewhere* in
`_handle_owned`. It already was, in the PARTIAL branch — so restoring the exact
production defect left it GREEN. Caught only by mutation-testing my own test.
Rewritten as a data-flow assertion: whatever `open_fields` returns must be what
`live_field` is derived from. **A gate on a one-line root cause that cannot
fail is worse than no gate, because it reports the defect as fixed.** The
standing rule this reinforces is [[verify_the_instrument_before_its_silence]],
applied to tests: mutate the fix, confirm the gate goes red, or do not claim
the gate.

**A fix that made the system able to find evidence it could not use.**
`split_identity` canonicalised the artifact KEY and left the ranker query
derived independently from the same inputs — see the identity-boundary section
above. Green suite throughout, because no test priced one identity by two
routes and compared them.

### What is proven, and on which path

```text
P1 canonical pricer         CLOSED   settle 36–70 ms vs 8,225–11,053 legacy;
                                     pricing.qualification absent on every settle
P1(b) ownership firewall    CLOSED   fired 3× in production, both rows intact;
                                     capability-based, UNKNOWN default-refused
B-1.5 typed two-field flow  PROVEN   live, /chat, preparation reachable by text
identity key (consumer 1)   PROVEN   fried chicken 445 -> 263 kcal, prediction
                                     pre-registered and matched exactly
identity ranker (consumer 2) FIXED   proven offline across all six routes,
                                     fail-CLOSED after review; NOT yet
                                     exercised in production — its defect needs
                                     preparation as a separate FIELD, and no
                                     operation has ever carried one
```

### What is open, and where it goes

```text
canary F — replay           CLOSED BY CONSTRUCTION, NOT BY OBSERVATION (below)
grilled-beef canary         PASSED   entry 2968, 250.0 / 34.1, on prediction —
                                     but via the KEY path, not the ranker
extraction loss             -> B-1.7  a stated preparation must survive to the
                                     operation. Vocabulary-driven, never a list
ranker floor                -> B-1.8  `oats|` holds 2 qualified candidates that
                                     `best_candidate("oats", ...)` will not
                                     select, so a covered food still prices as
                                     an estimate. Coverage is not the binding
                                     constraint here — SELECTION is
preparation materiality     -> B-1.7  preparation opened for NO item in the
                                     08-10 session; the question never fired
meal atomicity              -> B-2    multi-item meals still commit per row
B-1b.1 system matrix        RUNNABLE, NOT DISCHARGED (see the outage note above)
```

### CANARY F — THE CLIENT MAKES THE SPECIFIED TEST UNREACHABLE

F was written as "tap a chip, let it commit, tap the SAME chip again". **The
iOS client removes the interaction on tap**, so there is no second chip to
tap. That is correct UX and it is not a gap in the client — it means the
scenario was specified against a gesture the product does not offer.

**The real replay vector was never a double-tap.** It is a RETRIED DELIVERY:
one POST, a network timeout, a client retry. A user cannot produce that on
demand, which is why no amount of manual canary work would have closed F.

What is actually true today, measured rather than assumed:

```text
pending_store.claim()        RUNS ON EVERY PRODUCTION SETTLE — `claim=5–6 ms`
                             on every clarification_answer in the 08-10 trace
UNIQUE (operation_id,        PRESENT IN PRODUCTION — uq_meal_commits_operation_
        operation_revision)  revision, verified against pg_indexes, 81 rows
attempt_count                0 ON ALL 73 OPERATIONS, user 26, all time —
                             no duplicate delivery has EVER occurred naturally
```

So F is closed **by construction and by harness**, and it is honest to say
that and no more:

* the database arbitrates, not the application — `COMMIT_KEY_ENFORCEMENT` in
  `core/semantics.py` is satisfied by a real UNIQUE index, and an
  application-level `if not already_committed` under concurrent workers was
  explicitly rejected there
* the claim is a conditional UPDATE where exactly one caller sees rowcount 1
* the harness proves the behaviour (`test_pending_store.py`,
  `test_meal_commit_boundary_0804.py`)

**What remains UNOBSERVED, and is not claimed:** a duplicate delivery has
never happened in production, so `COMMIT_DUPLICATE_BEHAVIOUR` — that a
duplicate returns the ORIGINAL `MealCommitResult` rather than nothing — has
been proven only in the harness. Getting nothing back is the phantom-log
failure in a new costume, so this is worth an eventual deliberate exercise
against a staging deployment. It does not gate B-1.5, and it may not be
retired quietly on the strength of a green suite.

**The one-line summary of the whole day.** Every defect closed today was a
LOOKUP defect, not a knowledge defect: the artifact already held qualified
evidence for `chicken|fried` and `beef|grilled` before any of this work
started, and three separate mechanisms — the key, the ranker query, and the
interpreter's extraction — each independently prevented a turn from reaching
it. Two are closed. The third is named above and is not yet scheduled.

## Findings ledger — 2026-08-07, the B-1.5 build-out

Everything here was paid for once. Recorded so it is not paid for again.

### Defects found and fixed, by class

**A — architecture**

* **Lane ownership had two owners and had already drifted.** `conversation.py`
  computed client capability, `try_take_ownership` asked the rollout gate;
  `client_capable` ("can read the payload at all" — TRUE for Telegram)
  collapsed into `ID_ADDRESSED if client_capable else LABEL_TEXT`, so a real
  Telegram turn persisted `surface=id_addressed` (`telegram:9241`). One gate
  now (`canonical_food_enabled` → `LaneDecision`), capability carried on the
  ask, ratchet keeps derivations from coming back. Deploy-safe because
  `surface` is inside the `decision_id` hash — a corrected turn writes a NEW
  decision rather than raising DeterminismViolation.
* **The expiry door bypassed readiness.** An expired-but-awaiting operation
  receiving its FIRST late answer settled immediately — a late tap on Amount
  would have committed a two-field meal with Preparation never asked. Found by
  an existing sweep gate failing with "reached settlement with no quantity
  answer". Settled-vs-expired share one claiming rule but NOT one settlement
  path.
* **`ResolvedFields._one` returned `found[0]`** — right for one food, silently
  wrong for two: would price the chicken and drop the rice. Cannot fire in
  B-1.5 (one event by construction); defused before B-2 with a loud raise plus
  `for_event()` / `event_ids` as the per-event seam. B-2 settles per event; it
  does not relax the check.
* **`clear_day_log` deletes with no ledger events** (14 rows, 4 canonical,
  zero `deleted` events — the ledger CAN record food deletes; this path
  doesn't). **P0, BLOCKING B-1.5E's start (task #32).** A mutation-integrity
  defect must not be buried under evidence work: fix is one ledger event per
  deleted row in the same transaction, plus a ratchet that no code path may
  delete a food_entries row without a paired ledger event.
* **Cross-lane pending-state leak** (16:08 salmon): canonical settled and
  released; legacy re-asked a question canonical answered 21s earlier, then
  read "Ignore" as a log instruction. NOT hybrid ownership — the measured
  standing cost of deferring promotion until B-2. Accepted, not fixed.

**C — implementation**

* **The client silently dropped every canonical card.** `card_for` omitted
  `quantity`/`carbs_g`/`fats_g`; iOS `MacroCardPayload` declares them
  non-optional; synthesized Decodable fails the whole struct; `try? decode` →
  `.unknown` → dropped. The backend gate asserted only "cards non-empty" — the
  server WAS sending a card the client could not read. Now pinned field-for-
  field against legacy's card.
* **B-1.5 was askable and unreachable.** Preparation opened only when the
  interpreter volunteered the ambiguity, which it does not do for a food it
  identifies confidently. The producer's trigger is now the field's own
  evidence-driven `unresolved_when` — but see B-1.5E: the evidence itself is
  the remaining blocker.

**D — nutrition (tracked, not B-1.5's to fix)**

* Papaya 2896: 200 cal for 80g — the heavy-syrup row (206/100g) over raw (43).
* Banana 2891: 736 cal for 236g (312/100g vs real ~89) via canonical free-text.
* Both are the same class: retrieval treated as identity. B-1.5E's boundary is
  the structural fix; no food-specific patches.

**F — instruments that lied by silence, continued**

* `turn_metrics.outcome` = ok on 1188/1188 rows ALL-TIME. A non-ok value has
  never been written; "no errors in 7d" from this table is worth nothing.
* Proactive turns: 50 conversation_logs rows in 7d, 0 turn_metrics — every
  route-mix and latency table silently excludes them.
* `meal_commits.result_payload` carries no enrichment receipt — the papaya
  miss could not be diagnosed from durable state. Forensic reproducibility is
  a B-1.5E deliverable (§9 persistence).
* My own deploy watcher grepped `"ae95043|ok"` — matched `"status": "ok"` on
  the OLD build and reported success. The instrument-verification rule applies
  to instruments built mid-conversation too.

### ⭐ The synthetic-fixture failure — the one to internalize

The first B-1.5 producer shipped FOURTEEN green gates against `CHICKEN_ROWS`,
a fixture written to look like USDA and never checked against it. Mutation
testing caught a vacuous gate INSIDE the fixture (FLAT_ROWS used raw/boiled/
grilled — only one registered, so the materiality branch was never reached, and
mutating the threshold changed nothing) and still could not catch that the
fixture was fiction: **mutation testing verifies the test against the code,
never the code against the world.** Only a live probe found it.

Standing rule: a slice that consumes provider data is not proven until
something has touched the provider. Recorded fixtures are captured, never
authored (`tests/evidence_corpus/`), and stay ugly.

### Working patterns that held (reuse them)

* **Write the gate, then the headline** — held through ~20 commits.
* **Mutation-verify every new gate** — caught the vacuous FLAT_ROWS gate, the
  copy_for fall-through to "Logged.", and each ratchet's ability to fire.
* **AST ratchets over substring** — substring flagged its own explanatory
  docstrings twice; punishing WHY-comments teaches people to delete them.
* **Behavior, not mechanism, when porting** — badges-v2 reconciliation took
  five commits whole, rejected 650e414 for resurrecting QuickReplyEngine, and
  hand-ported its ReceiptStore fix by file.
* **Function calls, not import side effects, for registration** —
  `import_module` on an already-imported module is a no-op; `_reset_for_tests`
  never repopulated and 35 tests went red at a distance.
* **Construction free, presentation gated** — the contract bites on the
  interaction (persisted, rendered, answered), not on `UnresolvedField`, or
  the Phase-O workout seam breaks.
* **Live-probe the operand before writing the policy** — the corpus capture
  found in one hour what the fixture hid for a full commit cycle.

## B-1.5E — SEMANTIC EVIDENCE RESOLUTION *(Danny, 2026-08-07 — prerequisite, bounded)*

**B-1.5's topology is sound and its producer is blocked on evidence quality.**
Measured in production, not inferred: the multi-field spine holds, preparation
prices correctly through canonical naming, and the field cannot open because
nothing can tell whether retrieved evidence is about the food the user meant.

### What the measurement actually showed

Real USDA, corpus of seven, captured 2026-08-07 — **preserved raw in
`tests/evidence_corpus/usda_2026_08_07.json` with human-reviewed ground truth
in `tests/evidence_corpus/GROUND_TRUTH.md`**. Fixtures for the semantic layer
start from those files, never from memory of them. A bare `chicken` query returns
**zero** comparable rows in its top eight:

```text
Chicken spread · Chicken, meatless · Fat, chicken (900 cal) · Frankfurter,
chicken · Fast foods, chicken tenders · Bologna · Bratwurst · Chicken, canned
```

`Papaya, canned, heavy syrup` at **206 cal/100g** sits three rows above
`Papayas, raw` at 43 — and production entry 2896 committed 200 cal for 80 g.
The papaya miss is this defect, already shipped.

Shaped queries are worse, not better: they fall through USDA's curated pass into
Branded and return all-caps commercial rows.

⭐ **AND THE LESSON THAT MATTERS MOST.** The first B-1.5 producer shipped with
fourteen green gates against a `CHICKEN_ROWS` fixture I wrote to LOOK like USDA
and never checked against it. Mutation testing caught a vacuous gate INSIDE that
fixture and still could not catch that the fixture was fiction — mutation
testing verifies the test against the code, never the code against the world.
Only a live probe found it. **Synthetic provider fixtures must be grounded in
captured real responses, and a slice that consumes provider data is not proven
until something has touched the provider.**

### The prohibition, and it is absolute

There must be no production identity logic based on regex matching,
comma-position parsing, token counts, substring exclusions, food-name
allowlists, curated lists of foods needing clarification, enumerated bad
provider results, `if food == "chicken"`, `if "fat" in candidate`,
provider-specific textual special cases, or calorie-density multipliers standing
in for identity.

**A provider adapter may decode STRUCTURED provider fields. It may not infer
food semantics from naming tricks.** If USDA exposes a field, use it. If USDA
exposes only a human-readable description, that description is natural-language
evidence and goes through semantic resolution.

This kills the tempting fix. USDA writes `<base>, <qualifiers>`, so "the leading
term is the base identity" would reject five of six failure classes for
`chicken` in one line — and it is a naming trick, provider-specific, and the
first description that breaks the convention breaks the system silently.

### C2.1 — turn-scoped evidence execution

One `EvidenceContext` per turn, threaded through the seam that already
existed: `derive_unresolved(item, context)` -> `unresolved_when(item,
context)`. The parameter had been defined and never used; C2.1 is what it was
for.

**IN-FLIGHT, NOT COMPLETED-VALUE.** The context memoizes the COROUTINE, so two
fields evaluated CONCURRENTLY both await one acquisition. A finished-result
cache cannot do this — concurrent consumers all miss it and all pay, which is
exactly the case §2 names.

**LIFETIME BY CONSTRUCTION, third attempt and the right one.** v1 was a module
dict keyed `(food, version)` and described as turn-scoped while nothing
cleared it — a later turn could recall assessments made against evidence a
previous turn retrieved. v2 put the turn id in the key. v3 puts the state on a
context the turn owns: a later turn holds no reference, so there is nothing to
key correctly.

**ACQUISITION HAS ONE OWNER.** The pricing path retrieves and classifies;
preparation AWAITS that work and never starts its own. If enrichment never ran
for this food, preparation gets nothing rather than opening a second retrieval
path.

**FIELDS EVALUATE CONCURRENTLY** (`asyncio.gather`), so derivation latency is
the slowest predicate rather than the sum — and user-stated or
interpreter-explicit values short-circuit before any lookup.

**ONE FIELD-GENERIC ACTIVATION TRACE**, emitted for every field whether it
opens or not, because a field that quietly declines is what made B-1.5
unreachable:

```text
event=field_activation attribute=preparation disposition=unresolved
  opened=True latency_ms=2
  evidence={assessments_reused: True, from_structured: 2,
            from_supplemental: 0, supplemental_used: False}
```

**NO SPECULATIVE TIMEOUT.** Latency is measured first. After the production
trace, a product budget applies: inability to establish materiality in time
means UNKNOWN / do not ask — never guess, never block the user.

### SPACE vs VALUE — the invariant governing every semantic field

    external evidence establishes the SPACE of plausible answers
    only user evidence — or an explicit assumption policy — resolves the VALUE

A compatible record reading `Chicken breast, roasted` is evidence that ROASTED
EXISTS as a material preparation for this food. It is NOT evidence that the
user ate roasted chicken. Collapsing the two is how a clarification system
quietly stops asking and starts assuming — and it is the precise shape that
would let semantic evidence mutate user state, which this whole boundary
exists to prevent.

Enforced by `tests/test_evidence_opens_preparation_but_cannot_answer_it.py`:
`PreparationEvidence` has no field a resolved value could travel through; no
module outside the OPTION PRODUCER (a chip's meaning is its patch, C11) and
the ANSWER PATH may construct a `SetPreparation`; and the evidence modules
cannot even import the type. The only writers of a resolved preparation are
the user's tap, the user's stated text, and — later, B-1.7 — a disclosed
assumption policy.

Generalize it when the next field lands: evidence opens fields and populates
options; users and disclosed policy answer them.

### Qualification in the pricing path — landed, with four guardrails

`qualify_usda_rows` runs between `search_food` and `best_candidate`:
eligibility before ranking, truth still owned by the pick.
Measured red half: the unqualified winner for "papaya" is the BABYFOOD
COMPOSITE (token coverage passes, composite penalty insufficient). Green half:
qualified, only `Papayas, raw` is seatable.

**THE FAILURE INVARIANT (Danny): `SEMANTIC_RESOLVER_DOWN !=
RAW_EVIDENCE_AUTHORIZED`.** The user's action fails OPEN — the ladder's
qualification-free rungs (memory, structured product matches, the estimate)
still serve. The ambiguous evidence fails CLOSED — a resolver outage returns
NO USDA rows, disposition `resolver_down_no_candidates`, and the babyfood row
cannot be resurrected by a timeout. The first implementation failed open to
the raw rows and was corrected: fail open for the action, fail closed for the
evidence — different things.

**Guardrails recorded (2026-08-07), all bounded, none a new phase:**

1. **Meal-level batching** waits for B-2 and lands in `_prewarm_enrichment`,
   where the multi-food fan-out already lives. Per-food calls are bounded
   (`MAX_RECORDS`) and cached (single-flight + prewarm).
2. **Any DURABLE assessment cache keys on `resolver_version`** and no cached
   clarification-necessity survives a policy version change. Today's cache is
   per-turn single-flight, so nothing outlives a process.
3. **False-compatible is a first-class production metric**, separate from
   qualification success rate. Ground truth is unavailable in production; the
   proxy is the correction join — admitted evidence ids on the qualification
   event, corrections keyed on `entry_id`.
4. **Evidence establishes the SPACE; only the user (or an explicit assumption
   policy) resolves the VALUE.** `extracted preparation=roasted` on a
   compatible record may open the field and populate options; it may never
   construct a `SetPreparation`. Gated in commit 2's suite.

**D-class finding, recorded not fixed here:** `best_candidate` cannot bridge
`papaya` -> `Papayas, raw` (singular/plural token coverage), so the qualified
set yields no USDA candidate and pricing falls to the estimate — strictly
better than the composite, worse than the raw row. A ranking-quality item for
the nutrition thread.

**Instrument lesson repeated:** the first wiring ratchet was substring-based
and satisfiable by dead code (`if False:` around the call still matched).
Replaced with the behavioral gate. Kill switch: `EVIDENCE_QUALIFICATION_HALT`.

### The deployed predicate is SUPERSEDED DESIGN — do not improve it

`skills/nutrition/preparation_materiality.py` as deployed in `c5d3614` embodies
the invalid assumption this section exists to remove: that raw USDA retrieval
can directly establish the preparation family. It is fail-closed in practice —
it opens nothing, harms nothing — and that is the only reason it may stay
deployed while B-1.5E is built.

**The next implementation must not touch that predicate.** Build B-1.5E beneath
it, then make preparation consume qualified semantic evidence through its
`unresolved_when` hook. The hook survives; the predicate behind it is replaced,
not refined. Token matching against provider descriptions
(`_preparations_in`) dies with it — that is regex identity, prohibited above,
and it lives on borrowed time only because it currently cannot fire.

### The layer

```text
typed FoodIntent  +  bounded EvidenceRecord[]
        -> SEMANTIC RESOLVER (model, typed, versioned, schema-closed)
        -> EvidenceAssessment[]   relationship + extracted semantics
        -> DETERMINISTIC POLICY   authority, thresholds, abstention
        -> qualified evidence graph
        -> semantic-field derivation
```

`relationship` is closed and driven by measured failure classes:

```text
SAME_IDENTITY · COMPATIBLE_SPECIALIZATION · COMPOSITE_CONTAINING_IDENTITY
DERIVED_OR_EXTRACTED_FORM · SUBSTITUTE_OR_ANALOGUE · DIFFERENT_IDENTITY
INSUFFICIENT_EVIDENCE
```

**THE MODEL INTERPRETS MEANING; CODE DECIDES AUTHORITY.** The resolver may say
`COMPATIBLE_SPECIALIZATION, confidence 0.94, preparation=roasted`. It may never
say "use this row" or "log 226 calories". `confidence=0.91` does not authorize a
mutation — a deterministic threshold owns that, and nutrition values still come
from the existing resolver ladder.

**UNDER-SPECIFICATION IS EXPLICIT.** "I had chicken" means *base identity
chicken, everything else unspecified*. It does not mean "any description
containing chicken", and it does not mean "assume chicken breast".

**SEMANTIC CONFIDENCE AND SOURCE QUALITY ARE DIFFERENT DIMENSIONS.** A model can
be highly confident a low-quality blog is about fried chicken while policy
refuses it for nutrition. Store both, plus `claim_support`.

**AUTHORITY IS PER CLAIM, NOT PER SOURCE.** Web search answers the materiality
question USDA cannot — measured: grilled ~165 vs fried ~297 cal/100g — but its
synthesized answer is admissible for *"is preparation worth asking about"* and
inadmissible for *"what are this food's calories"*. `TAVILY_API_KEY` is
configured in production.

**PRECISION OVER RECALL, AND ABSTENTION IS A RESULT.** Rejecting a useful
candidate costs another lookup; accepting chicken fat as chicken costs a wrong
meal. `INSUFFICIENT_EVIDENCE` is a first-class answer.

Persist typed conclusions — never chain-of-thought — under
`food_evidence_semantics_v1`, so changing the prompt or model cannot silently
redefine historical assessments.

### Retrieval strategy: ask for authority, do not grade for it afterwards

**Source quality is a function of QUERY CONSTRUCTION, and the adapter controls
it.** Measured 2026-08-07, same claim, three shapes:

```text
loose     "chicken calories per 100g"
          -> nutriscan · INSTAGRAM · eatthismuch · healthline
specific  "USDA SR Legacy chicken breast meat only roasted kcal per 100 g"
          -> recipal · medicinenet · myfooddata · fdc.nal.usda.gov
sourced   "site:fdc.nal.usda.gov chicken breast roasted energy kcal 100g"
          -> fdc.nal.usda.gov x4
```

All three return **165 kcal** — the number is stable while citability varies
enormously. So §15's preference list (government/academic, manufacturer,
official restaurant pages) is not a post-hoc filter to apply to loose results;
it is what the web adapter should ASK FOR. This is provider-specific retrieval
doing its job (§10), and it belongs in the adapter, not the policy.

It does not remove the need for source-quality scoring — a `site:` query can
still return a page that is stale or wrong — but it changes the input
distribution rather than discarding most of it after the fact.

### The core/domain boundary — protected aggressively

**There is no single giant resolver that knows every domain's ontology.** The
shared layer provides mechanism and contract; domains provide schemas and
meaning:

```text
shared core                          nutrition (first domain)
  EvidenceRecord                       FoodIntent schema
  SemanticAssessment                   food relationship vocabulary
  resolver invocation/versioning       preparation projection
  confidence/abstention contract       product projection
  persistence
  policy boundary                    workouts (Phase E/F, later)
                                       ExerciseIntent schema
                                       exercise relationship vocabulary
                                       equipment / load / reps projections
```

**THE HONESTY TEST, and it is a gate, not a sentiment: if workouts adopt this
later, core must not change.** Workouts add a domain schema, field
registrations and evidence projections — never another semantic-resolution
architecture. This is the same inversion already enforced for the field
registry (`_DOMAIN_REGISTRARS`, `supported_vocabulary`), extended to evidence:
the seam generalizes or it is nutrition-specific debt wearing a generic name.

Why this detour is not really a food detour: it is the missing seam between
probabilistic interpretation and deterministic execution —

```text
LLM / search / external systems -> uncertain evidence
    -> typed semantic boundary -> deterministic canonical system
```

— which is what later lets Arnie become more agentic without probabilistic
reasoning ever mutating user state directly.

### Scope, and where it stops

NOT a food ontology, knowledge graph, universal nutrition engine, search engine,
fine-tune, cuisine model, restaurant intelligence, ingredient decomposition or
recipe reconstruction. The objective is narrow: **stop retrieval results being
treated as interchangeable because strings overlap, and make enough trustworthy
evidence available to production-prove preparation.**

Two consumers prove generality — preparation AND product_variant, sharing one
assessment with different projections, neither owning an identity matcher.
Product_variant may not be substituted for preparation: B-1.5 closes on a
NATURALLY occurring real iOS turn, with no constructed ambiguity, no synthetic
rows, and no manually inserted field.

**When B-1.5 passes, stop and resume B-1.6.**

## THE SEMANTIC EXTENSION CONTRACT *(Danny, 2026-08-07 — enforced, not documented)*

**A new food behaviour enters as a REGISTERED FIELD or it does not enter.**
`core/semantic_fields.py` is the registry and the only door. The question asked
of "fried", "with sauce", "half the package", "skin on" and "brand variant" is
the same one every time — *what semantic field is this?* — and an
implementation beginning `if "fried" in food_name` has already answered it
wrong.

A spec declares all of: typed `attribute` · `value_space` · `patch_type` ·
`pricing` · `evidence` · `settlement` · `activation` (+ predicate) ·
`vocabulary` · presentation metadata. `register()` refuses anything else, at
IMPORT time, so a malformed field breaks the process rather than the first user
who triggers it.

**The invariants, and where each is enforced:**

| invariant | enforced by |
|---|---|
| a field cannot be **presented** unless registered | `ClarificationInteraction.__post_init__` |
| unsupported semantics cannot be emitted | `register()` → `validators._PREPARATIONS` |
| `ResolvedFields` is the ONLY settlement boundary | `Settlement` has one member |
| no field may price by a multiplier | `Pricing` has no such member |
| exactly one field decides the amount | `register()` |
| a conditional field declares its predicate as DATA | `register()` |
| no field-specific settlement extractor | AST ratchet |
| the coordinator names no attribute | AST ratchet |

**Two boundaries that are NOT the same, and conflating them broke a test.**
`ClarificationAttribute` is the vocabulary of what COULD be asked — including
the Phase-O workout attributes that exist so onboarding workouts need no food
edit. The registry is what CAN be asked today. Construction is free;
**presentation** is gated. That is why the check sits on the interaction rather
than on `UnresolvedField`.

### The rule of three — PASSED, and what it does not prove

`tests/test_the_rule_of_three_fields.py` registers a third family
(`serving_basis`, `Pricing.NONE`, its own patch type), drives it through
production, presentation, answering, holding and settlement, and asserts three
fields settle **once** with no coordinator change. It passes, and the coordinator
names no attribute.

**It is a probe, deliberately not shipped** — a field with no producer and no
user is the defect `UNUSABLE_AMOUNT` was deleted for.

**A KNOWN LIMIT, pinned by its own gate.** All three families answer with ONE
option producing ONE patch, and `hold_answer` keys the held map by field id, so
a second answer REPLACES the first. A genuinely multi-valued field ("no bun,
extra cheese") cannot be expressed: the held value would have to become a set
and `ResolvedFields._one` would have to stop assuming singularity.
`ResponseType.MULTI_SELECT` exists and nothing produces it.
`test_one_field_holds_exactly_one_answer_and_that_is_a_known_limit` is there so
whoever tries finds out from a test rather than from a user whose second
selection vanished. **"The mechanism is generic" must not be read more broadly
than this.**

### Owed to B-1.5 UI — ported behavior, NOT the legacy mechanism

`feat/badges-v2` reached these on the legacy `QuickReply` bar. Those four
commits were deliberately NOT picked (37f946d, 34f2b2c, 0a10677, 8652439) —
label-valued answers, a `group` index for identity, label deduplication and
legacy chip routing are the architecture B-1b replaced and D7 deletes. Four of
the product decisions were hand-ported in `55bf93b`; **two remain owed**, and
both need canonical equivalents expressed through `option_id`:

* **selected answers render back into the transcript** — from `34f2b2c`. The
  chosen chip should appear as the user's turn, by option id, never by echoing
  the label back as if they had typed it.
* **a card does not visually erase an unresolved question** — from `0a10677`. A
  committed card arriving while another field is open must not read as "done".
  Directly relevant now: B-1.5 settles on the LAST field, so every partial turn
  is exactly this state.

These are presentation and belong with the B-1.5 UI work, not with the
contract. Also owed and unrelated: `ArnieShare` (from `6376a76`) needs its
provisioning profile before a signed device build.

### Product-quality backlog — recorded, NOT blocking

These are B-1's first-production findings. They are product quality, not
semantic-spine defects, and none of them justifies reopening canonical
architecture. Do not let them interrupt B-1.5 through B-2 unless severity
changes.

| finding | note |
|---|---|
| labels render `118g`, not `4 oz` | `_everyday_labels` does not know the food; the number is correct, the phrasing is not |
| iOS replies are richer and slower | 223 chars vs Telegram's 95 — `IOS_STYLE` + `NATIVE_CARDS` + `IOS_FORMAT_ANCHOR`. A product decision about output length |
| copy refinement | Arnie voice over committed facts, still the deterministic fallback |
| chip visual polish | client-side |
| candidate-quality generalisation | belongs to the generalised generator milestone, not here |

**Latency is a separate thread from this migration.** Measured on the same
user: the structured tap itself is 257 ms, and iOS framework overhead
(15–154 ms) is LOWER than Telegram's. Perceived latency is dominated by model
output length, not by the clarification architecture. Optimise it separately;
do not treat it as evidence about the canonical path.

### Legacy is a frozen compatibility lane, not a second development lane

Allowed in legacy:

* P0/P1 production fixes
* security fixes
* migration compatibility needed to keep existing users working

Forbidden in legacy: new food features · new clarification semantics · new
pending mechanisms · new candidate logic · new mutation writers. **All new
food capability belongs to canonical.**

### Lane ownership is decided ONCE, at the top of the food turn

`core.canonical_lane.canonical_food_enabled(user_id=…, channel=…)` is the one
gate, and `tests/test_one_gate_decides_the_lane.py` is the ratchet that keeps
it the only one — no other module may name `may_take_ownership` or
`client_renders_interactions` to decide a lane.

**There is never hybrid ownership inside one user turn.** A canonical user may
not ask through canonical and answer through legacy, create canonical pending
state and fall back to legacy pending state, commit through a legacy writer
because canonical clarification failed, reconstruct canonical options from
prose, or switch implementations between turns of the same live operation.

**PROMOTION BLOCKER — no per-request client build.** The gate takes
`(user_id, channel)` and not `(user_id, channel, build)`, because NOTHING
carries a client build to the backend: no header, no field. `_CHANNEL_CAPABILITY`
therefore claims `ios` is `ID_ADDRESSED` for the whole platform rather than for
the app in the user's hand. An older build that cannot decode `interaction`
receives `ask_copy(capability=ID_ADDRESSED)` — the introduction ALONE, options
carried only in a payload it cannot read — so the user sees "How much chicken
breast?" and nothing to pick from. Free text still works; the options are
invisible and their usage rate reads zero. Harmless at one user on a known
build; NOT harmless at promotion, which is when every old build arrives at
once. Closing it needs an iOS version header plumbed through to the gate.

### B-1 state — the authoritative lines

```text
B-1 lifecycle implementation       COMPLETE
B-1 production lifecycle proof     COMPLETE
B-1a wording                       COMPLETE      versioned b1_quantity_q2
B-1c safety observability          COMPLETE      coverage and precision proven
B-1b.1 system validation           COMPLETE      absorbed by B-1.9 step 7
B-1b.2 sequence simulation         COMPLETE      absorbed by B-1.9 step 7
B-1b.3 human simulation            CONTINUOUS    usability, NON-BLOCKING
B-1b.4 organic confirmation        CONTINUOUS    low volume, NON-BLOCKING
B-1d structured iOS client         COMPLETE      live, answering by option_id
B-1 canonical capability           COMPLETE      for allowlisted users
B-1 global promotion               DEFERRED      until B-2
B-1 predecessor deletion           DEFERRED      until B-2
B-1 legacy                         FROZEN        for non-allowlisted users
```

These last four lines are a SCHEDULE, not a defect. B-1 is not blocked on
anything; promotion and deletion were batched to the end of B-2 so production
users cross the boundary once instead of five times.

Quote these lines rather than a single adjective. "B-1 is done" is true of the
first four and false of the rest, and the slice loop is won or lost in the rest.

**The last three lines changed meaning on 2026-08-07 and the distinction
matters.** They no longer read BLOCKED because something is wrong; they read
DEFERRED because promotion and deletion were consolidated into a single event
at the end of B-2. B-1 is not waiting on a defect. It is waiting on a schedule.
Do not let that reading drift back into "B-1 is finished" — the legacy producer
is still alive and still serving everyone outside the allowlist, which is
exactly the condition the slice loop was written to make visible.

**B-1 owes the promotion event its executable gate.** Write it when B-1.5
starts, not on promotion day: the answered quantity produces the committed
numbers across every basis, and the legacy quantity path has no remaining
caller. That is the B-1.75 condition already recorded above.

### B-1.9 — candidate-system correction. Runs BEFORE B-1 closure.

**Received 2026-08-06.** Two production failures showed the candidate layer,
not the lifecycle, is what is wrong. B-1.5 does not start until this and B-1
closure are done.

```text
1  contain unsafe "not sure"        <- IMMEDIATE, safety
2  add the missing quantity semantics
3  instrument the whole candidate universe
4  evidence-backed quantity generator
5  versioned candidate selector
6  replay the two failures as SYSTEM CLASSES
7  complete B-1b.2 integration evidence
8  freeze the candidate contract
9  structured iOS interaction
10 promote and close B-1  (deletion included, or it is not closed)
```

**1 — contain unsafe "not sure".** `USE_ESTIMATE` must not commit from weak or
unsupported evidence.

```text
not sure -> retrieve typed estimate evidence
         -> policy evaluates SUFFICIENCY
         -> commit only when the evidence supports it
         -> otherwise remain unresolved and REPAIR
```

Forbidden as the fix: a smaller hardcoded estimate · a midpoint · a
food-specific cap · a manually chosen "safe" portion · regex food
classification. Exit gate: **insufficient evidence → zero meal writes →
operation stays open → explicit repair.**

**1 — status: PASS with two carry-forwards** *(disposition 2026-08-06)*.
Landed `c859758`. **B-1 may not be promoted on this commit alone.**

* **CF-1 — replace source-name sufficiency with typed evidence semantics,
  before B-1.9 closes.** The containment currently keys on a frozenset of
  source NAMES (`{"user_history", "catalog"}`). That is a stand-in: it works
  because those sources happen to be entity-specific today, and it will drift
  the moment a source is added whose name says nothing about what its evidence
  is ABOUT. The property is semantic — *does this candidate describe this
  entity for this user* — and belongs on `QuantityCandidateEvidence` in item 2,
  read rather than inferred from a name.
* **CF-2 — persist the policy version.** ✅ done. `estimate_evidence_v1` was
  emitted to a log and nowhere else; the ring is a bounded in-memory deque
  that empties on deploy, so an analysis weeks later could not say which
  sufficiency rule produced a refusal. `b1_answer_observations.policy_version`
  (migration `b1obs003`), empty when no versioned policy governed the route —
  a stated quantity decides itself, and stamping every row would make the
  field mean "some policy ran" rather than "this policy decided".

Also fixed in passing: `modality_of` matched the reason by exact equality, so
improving an error message reclassified a refusal from `command` to `text`
and counted it as free-text usage — corrupting the "Other" rate with a better
sentence.

**⚠ CI HAS NOT PRODUCED A GREEN CHECK ON ANY RECENT COMMIT.** Raised in review
as "no combined status checks", investigated 2026-08-06, and it is worse than
a reporting quirk:

```text
6b66681  queued
c859758  failure   job=cancelled   15 min   no failed step
9c9d4ea  failure   job=cancelled   15 min   no failed step
cda108e  failure   job=cancelled   15 min   no failed step
bd30854  failure   job=cancelled   15 min   no failed step
a16bc03  failure   job=failure      7 min   failed at "Set up job"
```

**CAUSE: a GitHub Actions outage, not this repository.** The job page reports
*"The job was not acquired by Runner of type hosted even after multiple
attempts"* alongside an internal server error, and GitHub Status shows Actions
in **major outage** from 2026-08-06T15:22Z: *"Workflow runs are failing or
delayed in starting, and some queued jobs may time out."* Every red run above
falls inside that window, and one cause explains all five — jobs queue, no
runner takes them, they are cancelled around fifteen minutes.

Ruled out on the way: not the push cadence (`cancel-in-progress` is `false` on
`main`), not a job timeout (none set, default 360 minutes), and **not billing**
— which was my first hypothesis from the "Set up job" failure and was wrong.
Nothing needs enabling or configuring.

The cause being external and temporary does not change the standing: until a
check goes green, **every test result in this programme is author-reported
execution evidence, not an attached check.** The numbers are real and the runs
happened; nothing independent confirms them. That distinction belongs in the
evidence-class table alongside the others, and it should be closed before
promotion — a migration whose safety rests on a suite nobody else has seen run
is resting on the same kind of unverified instrument this slice keeps finding.

**2 — the missing contracts.** `ServingBasis` (MASS · VOLUME · COUNT · PIECE ·
PACKAGE · FRACTION_OF_PACKAGE · FRACTION_OF_ENTITY · STANDARD_SERVING),
`QuantityCandidateEvidence`, `EstimateEvidence`, `CandidateSet`,
`CandidateSelectionDecision`. Every candidate carries canonical entity id,
canonical quantity, serving basis, source type and record, conversion
evidence, confidence, uncertainty, policy version, provenance. **No candidate
without typed evidence enters an interaction.**

**2 — status: DONE** *(commits `f93e77c` + `cd17234`, 2026-08-06)*. CF-1 is
closed: sufficiency now reads declared scope and subject, not a source name.

* **Commit 2 shipped a P0 and review caught it.** `authorizes_assumption`
  proved the evidence *named* a user or product and never that it described
  the one being asked about — all three subject ids were stored and none was
  compared to anything, so evidence about user 123 would have authorised an
  assumption for user 456. Fixed in **2.1** with `EvidenceContext` and
  identity comparison, assembled **from the operation** rather than
  re-derived from the incoming message.
* `THIS_PRODUCT` → **`THIS_PRODUCT_QUANTITY`**, requiring a quantity-bearing
  basis. Identity is not consumption: knowing a jar is Brand X honey does not
  establish that three tablespoons were eaten.
* Evidence-bearing options **fail shut** without a context.

**3 — instrument the whole universe, not the selected three.** Persist all
generated candidates, their evidence sources, serving bases, conversions,
which were selected, which excluded, the selection reasons, policy version,
the answer, its modality, and any later correction — so that *retrieval*
failure, *conversion* failure, *selection* failure, *presentation-basis*
failure and *ranking* failure stop being one undifferentiated "bad options"
problem.

**3 is SPLIT — 3a contracts, 3b persistence** *(2026-08-06)*. The schema is
not cut until the shape is settled, because a migration is the one artefact
this programme may not amend after pushing
(`feedback_arnie_never_amend_a_pushed_migration`).

**3a — the architectural correction. `candidate_id` belongs to the CANDIDATE,
never to the evidence.** The first implementation put identity on
`QuantityCandidateEvidence`, which encodes *one candidate = one evidence
record* into the persisted shape. That assumption does not survive real
candidate generation, where one offered amount may be supported at once by
exact user history, package metadata and a canonical serving record. Caught in
review before any schema existed. Three levels now:

```text
CandidateSet
└── QuantityCandidate          candidate_id · normalized offered quantity
    │                          · presentation serving basis
    └── evidence[]             QuantityCandidateEvidence
                               observed quantity · observed basis
                               · provenance · applicability · conversion
```

The split also fixes an ownership ambiguity: with a quantity on both objects
and no stated authority, `candidate.quantity = 21 g` beside
`evidence.observed = 30 g` was representable and meaningless. The candidate
owns the **offered** value; evidence owns what its source **observed**;
crossing them requires a sourced conversion, and agreeing on one basis
requires agreeing on the number.

Further corrections taken in 3a:

* **Selection is reproducible only with its context.** A policy version alone
  does not determine the outcome — the same universe yields three text options
  on Telegram and five structured ones on iOS.
  `CandidateSelectionContext(surface, locale, maximum_options,
  renderer_contract_version)` is persisted, so the claim becomes *set + policy
  + context = same decision*.
* **A source id is not durable evidence.** A `food_entries` id points at
  whatever that row says now, not what it said at generation. Evidence
  snapshots `observed_quantity`, `observed_basis`, `observed_at` and a
  `SourceReference(dataset_id, dataset_version, record_key, record_version)` —
  so `portion:chicken_breast:large` cannot silently mean 174 g before an
  ontology refresh and 190 g after while presenting as one claim.
* **`RENDER_COLLISION`, not `DUPLICATE_LABEL`.** A label is presentation. Two
  candidates can be semantically distinct, collide in English and not collide
  in another locale; recording that as a duplicate would assert they meant the
  same thing when they did not. Reproducible only against
  `renderer_contract_version`, which is why that field is required.
* **No generic exclusion reason.** "Not selected" restates the fact already
  recorded. The enum is exactly `semantic_duplicate · render_collision ·
  selection_cap` — one per real policy branch.
* **Generation failures are not selection decisions.**
  `CandidateGenerationRejection` holds inputs that could not form a candidate.
  Forcing them into the universe would mean constructing invalid candidates
  just to mark them excluded, defeating the construction-time gates and
  corrupting the denominator of every selection metric. It also separates
  "found nothing" from "found a row that could not be used".
* **Keyword-only construction** on every new contract. These records grow
  fields as the slice does, and a positional call silently reinterprets an old
  argument as a new field.
* **Selected order is data**, not database insertion order — it decides which
  option is first, and therefore prominence and selection rate.
* **Opaque candidate ids.** Never built from user id, food name, label,
  confidence or evidence ordering; `semantic_hash` carries merge identity
  separately, where it can be compared without being an address.

The load-bearing gate: `selected ∪ excluded == every generated candidate` and
`selected ∩ excluded == ∅`. With it, three failures that look identical in
production separate — **retrieval** (absent from the set), **selection**
(present and excluded with a typed reason), **user rejection** (present in
`selected`, so it *was* shown). Without it the first two are one observation
and the third is guesswork over displayed options.

**3a — status: DONE, contracts only.** 7987 pass on SQLite, 0 failed.

**3a.1 — the contract proved evidence EXISTED, not that it produced the
offered quantity.** Review 2026-08-06 on `2d67bc3`. Every conversion check was
structural — a source exists, the factor is positive, the bases join up — and
none of them applied the factor. Reproduced before fixing:

```text
CONSTRUCTIBLE  evidence 240 ml x 0.758 g/ml -> candidate 435 g   (false by 2.4x)
CONSTRUCTIBLE  evidence 240 ml            -> candidate 500 ml    (both .grams None)
CONSTRUCTIBLE  confidence=7.5 · uncertainty=-40 · naive datetime
CONSTRUCTIBLE  a conversion claiming a result its own factor does not produce
```

The same-basis check read `.grams` only, so two volume quantities compared
`None == None` and agreed; count, piece, package and fraction had the
identical hole. Closed by `measure_on(quantity, basis)` plus one basis-aware
support operation — *evidence → typed conversion → supported quantity →
compare with the candidate's own quantity* — exact, with **no tolerance**. A
producer that must round declares `quantize_exponent` under a
`policy_version`, so rounding is a versioned decision rather than an epsilon
that absorbs real errors alongside representation noise.

Also in 3a.1:

* **`ServingExpression`** — a basis enum cannot render an option. `21 g +
  VOLUME` does not say `1 tbsp` / `15 ml` / `3 tsp`; `182 g + PIECE` does not
  say `1 breast` / `½ large breast`. That gap *is* the honey failure, and it
  was still there. The candidate now owns both what would be committed
  canonically and what the user is offered; a candidate that cannot be said
  cannot be constructed.
* **`ConversionEvidence.source` is a `SourceReference`**, not a free string —
  a density record can be corrected while keeping its key. It also carries
  input, output and policy version, so the conversion is executable.
* **`PresentedCandidateOption`** — "candidate c1 was selected" does not prove
  "c1 became `opt_c1`, labelled `6 oz`, first, in revision 0". The rendered
  label is **persisted, not recomputed**: locale and renderer version do not
  capture every renderer input, and re-rendering later answers a question
  about today rather than about that turn. This is what makes
  `RENDER_COLLISION` auditable.
* **Fail-shut properties became contracts**: timezone-aware `observed_at`,
  `0 ≤ confidence ≤ 1`, `uncertainty ≥ 0`, typed collection elements, and a
  `SourceReference` that must carry a `record_version` **or** declare
  `immutable_within_version` — a `food_entries` id points at whatever the row
  says now, and correction rewrites it.

**3a.2 — the shown serving and the committed quantity were still independent
fields.** Review 2026-08-06 on `e4b6139`. `ServingExpression` checked that
`amount` was positive, `unit_id` non-empty and `normalized` non-empty on its
basis — and never that the amount and the unit PRODUCE the normalized value.
Reproduced before fixing:

```text
CONSTRUCTIBLE  displayed 99 tbsp · normalized 15 ml · committed 21 g
               attached conversion 100 ml -> 140 g (valid, unrelated)
CONSTRUCTIBLE  unit_id "wibbles"
CONSTRUCTIBLE  set.user_id=26 holding a salmon candidate on a chicken field,
               carrying THIS_USER evidence about user 99
CONSTRUCTIBLE  presented positions [7, 12] and [0, 0]
   NON-DETERMINISTIC  a stored conversion returning 182, then 181, after any
               library anywhere set getcontext().rounding
```

Closed by:

* **`core/unit_registry.py`** — a closed Decimal table, so `amount + unit_id`
  formally normalizes to the stored quantity, and an unregistered unit is
  REFUSED rather than defaulted. Mass constants are **derived from
  `core.units`**, not respelled: the "one place knows what a pound is" ratchet
  caught this module on its first run, which is the gate working on a module
  added to improve exactness.
* **The attached conversion must be about THIS expression's values** — input
  equal to the expression's own basis amount, output equal to its committed
  mass. An internally valid conversion for an unrelated quantity licensed
  nothing while looking fully sourced.
* **`CandidateSet.context`** — the set is bound to an `EvidenceContext` and
  every candidate and scoped record is checked against it. Foreign evidence is
  **rejected, not out-voted**: applicability is an `any()`, so a population
  record beside a foreign THIS_USER record made the candidate look applicable
  while the foreign record stayed persisted and readable. A stored claim about
  another user is a durable disclosure whether or not a selector reads it.
* **`RoundingMode`**, persisted and passed explicitly to every `quantize()`.
* **Presented positions must be exactly `0..n-1`** — otherwise "position"
  means only "earlier than" and the exact row cannot be reconstructed.

**3a.2 — status: DONE.** 8035 pass on SQLite and 8035 on Postgres (21 skips),
97 contract gates.

**3a.1 — status: DONE.** 8017 pass on SQLite and 8017 on Postgres (21 skips),
79 contract gates. Mutation-verified: disabling the support comparison turns 5
gates red, disabling the conversion arithmetic turns 2 red. No schema, no
producer, no ranking, no visible-option change.

**A RULE ADOPTED BEFORE CUTTING THE SCHEMA** *(2026-08-06)*:

> Any field that participates in **identity, replay, authorization,
> arithmetic, or provenance** must be final before persistence. Organization
> and module placement may change later without changing the wire or the
> stored meaning.

That is what made 3a/3a.1/3a.2 worth their review cycles, and it is why
`core/semantics.py` being large is not a reason to delay 3b — splitting it is
pure module movement, gated on *no payload change, no schema change, no
renamed enum value, identical suite*.

**3b — status: DONE** *(2026-08-06)*. Five tables, `b1uni001`, all six
domain-neutral: `domain`, `subject_entity_id`, `candidate_kind` and typed
payloads. Nothing names a food, so exercise identity, set/rep, distance,
duration and dose ambiguity reuse them without a redesign.

**NOT SCORED ON THE TABLES EXISTING.** Scored on whether a persisted record
survives hostile lifecycle conditions without changing meaning —
`tests/test_the_candidate_universe_survives_storage.py`, 15 gates:

```text
atomic write                  partial write rolls back to zero rows
idempotent create             a retried ask finds its universe, not a second
same key / same fingerprint   returns the stored set
same key / diff fingerprint   DeterminismViolation, loudly
concurrent duplicate          one universe, DB-deduped, no half-written loser
process restart reload        full record from storage, generator never run
append-only revisions         revision 1 adds; revision 0 is untouched
user-scoped retrieval         an id alone does not open someone's history
schema/model parity           alembic head vs create_all, on Postgres
end to end                    the row persisted IS the row shown
```

Plus the analytics gate: `why_not()` returns exactly one of `shown` ·
`excluded:<typed reason>` · `not_generated`, and **never "unknown"** — with
the set's `rejections` separating "found nothing" from "found a row we could
not use". Exclusion reasons and evidence sources aggregate by `GROUP BY`
rather than by opening payloads, because "why wasn't my usual portion there"
has to be answerable at population scale.

**Fail-closed is wired at the ask.** The universe is written BEFORE
`open_operation`, so a persistence failure means no operation, no option ids
and no question — the turn proceeds as it does today and nothing was taken.
The alternative, ask-then-persist, produces exactly the state this record
exists to prevent: a user answering options nothing can explain.

**One instrument fixed while writing the gates.** The end-to-end test began as
`pytest.skip("rollout gate declined")` — which is an instrument lying by
silence: the day the gate started declining, it would have gone green having
exercised nothing. It asserts now. It caught two real setup defects
immediately (`client_incapable`, then `no_quantity_question`).

**3b.2 — durable identity and integrity completed** *(review of `6c5e87b`)*.
Four defects, all confirmed by reading the code before fixing:

* **P0 — a decision could never be written over an existing set.** `save()`
  returned the moment the set existed, so a second decision over the same
  immutable universe was impossible — and that is the NORMAL case: the same
  universe rendered for Telegram and for iOS, or reduced again after the
  selector versions up. Split into `ensure_candidate_set` /
  `ensure_selection_decision` / `ensure_presented_options`, three independent
  idempotencies. The set is write-once; the decision is not.
* **P0 — `maximum_options` was missing from the decision's identity**, in both
  the id hash and the unique constraint, while the selection context claimed
  the outcome was determined by it. A three-option text row and a five-option
  structured row collided under one identity: the second could never be
  written and the first was replayed in its place.
* **P1 — membership was enforced only by the aggregate.** Exclusions and
  presented options had a foreign key to the DECISION and none to the
  candidate, so either could name a candidate from another set, or from no
  set, at the database level. Composite foreign keys added; `candidate_set_id`
  added to `candidate_exclusions` and backfilled from the decision it already
  pointed at.
* **P1 — evidence had two durable authorities.** The candidate payload
  embedded its evidence AND every record was written to
  `candidate_evidence_records`; replay read the first, the funnel grouped the
  second. They could disagree, and the system would behave correctly while
  reporting the wrong provenance — a metric that is confidently wrong, which
  is worse than a missing one. The evidence rows are now the sole authority
  and the payload carries no copy to drift from.

`b1uni002`, **forward only** — `b1uni001` is pushed and `main` auto-deploys.

**A gate that was proving nothing.** Enabling the composite foreign keys
revealed that **SQLite ignores foreign keys unless the pragma is set per
connection**, so every database-integrity assertion in the storage suite would
have passed against an engine enforcing none of them. The fixture now sets
`PRAGMA foreign_keys=ON` and asserts it took. Same class as the three
instruments this slice has already caught lying by silence.

**3b — status: DONE.** 8061 pass on SQLite and 8061 on Postgres (21 skips),
26 storage gates.

**3b.3 — replay bound to the exact decision** *(review of `edae1d8`)*. Making
several decisions per universe legal — the 3b.2 fix — broke the read path,
which still behaved as though there were one. Three P0s, all reproduced first:

* **`load()` returned an arbitrary decision.** `.first()` over an unordered
  query, so once a universe held a Telegram decision and an iOS one, replay
  returned whichever row the database produced. That is the same failure as
  regenerating: a true statement about the system and a false one about this
  turn. `load_by_decision_id()` is the authoritative read now, `load()` orders
  deterministically and is administrative, and **the operation stores the
  `decision_id`** so the answer turn names the question it is answering
  instead of inferring it.
* **Decision equality compared only the winners.** Same options, different
  reason for dropping the rest — `SEMANTIC_DUPLICATE` becoming
  `SELECTION_CAP` — was accepted and silently discarded, so the caller
  believed one explanation and the record held another. A decision whose
  explanation can drift is not evidence. The whole canonical decision is
  compared now: selection AND order, exclusions AND reasons, full context,
  policy, set.
* **Presented equality compared only option ids.** `6 oz` becoming `8 oz`
  under the same id was accepted and dropped. The whole ordered row is
  compared now — id, candidate, set, revision, position, label, renderer.

Plus the P1: **the repository recovers from a lost race** instead of
surfacing an `IntegrityError` to a turn that did nothing wrong. Losing the
insert is a replay — the winner wrote the same universe — so it rolls back to
a savepoint, re-reads, and validates the fingerprint. Concurrency is proven at
all three boundaries, including two legitimately different decisions over one
set both persisting.

No migration: `decision_id` and `candidate_set_id` live in the operation's
existing JSON payload.

**3b — status: DONE.** 8073 pass on SQLite and 8073 on Postgres (21 skips),
38 storage gates.

**Superseded plan for 3b:** Atomic write of the immutable set and its typed decision
*before options are rendered*, fail-closed; append-only; candidate set bound to
its operation's user at write **and** read; database constraints as well as
domain validation, because migrations and future write paths bypass a
dataclass; `generation_input_fingerprint` so that the same key regenerated from
different inputs **fails loudly** instead of silently returning the old
universe; the interaction referencing its `candidate_set_id` directly, so
settlement proves `option_id → candidate_id → candidate_set_id → the exact
revision shown`.

**Commit 3 gates.** Ticked only against executed proof.

```text
[x] QuantityCandidate owns the normalized offered quantity
[x] evidence owns observed source facts, not candidate identity
[x] new contracts are keyword-only
[x] a candidate may carry multiple evidence records
[x] selection context is persisted and versioned
[x] selected ordering is durable
[x] label collisions cannot erase distinct semantics silently
[x] every exclusion maps to a real policy branch
[x] invalid generation attempts are separate from valid exclusions
[x] arbitrary converted quantities are unconstructable          3a.1
[x] same-basis mismatches fail for mass, volume, count,
    piece and package                                           3a.1
[x] every candidate can render its own basis                    3a.1
[x] every conversion authority is versioned and auditable       3a.1
[x] every shown option binds to one persisted candidate         3a.1
[x] rendered labels and positions are durable                   3a.1
[x] invalid timestamps or evidence types fail at construction   3a.1
[x] expression amount/unit formally produces its quantity        3a.2
[x] expression conversion starts and ends on that quantity       3a.2
[x] unrelated conversion evidence cannot be attached             3a.2
[x] candidate set rejects wrong-user / wrong-entity /
    wrong-product evidence                                       3a.2
[x] population evidence cannot mask foreign scoped evidence      3a.2
[x] rounding is deterministic independent of Decimal context     3a.2
[x] presented positions are exactly 0..n-1                       3a.2
[x] generator inputs carry a reproducibility fingerprint      3b
[x] same key + different fingerprint fails loudly             3b
[x] source evidence is snapshotted, not merely referenced     3b.1
[x] ontology source identity includes dataset version         3b.1
[x] the interaction directly references the candidate set shown  3b.1
[x] candidate set and decision are append-only                3b
[x] database constraints enforce cross-record integrity       3b
[x] user ownership is checked at persistence AND retrieval    3b
```

**Stop condition, unchanged:** the system can distinguish retrieval failure
from selection failure from user rejection **using durable records alone** —
not by re-running the generator, and not by inferring from displayed options.

**4 — status: DONE** *(2026-08-06)*. Every production quantity source emits
`QuantityCandidate` with typed evidence, a versioned source snapshot, a
`ServingExpression` and a stable semantic identity. The bridges are deleted:

```text
[x] every production candidate is natively typed
[x] every evidence record has explicit scope and subject
[x] every mutable source is revisioned or content-pinned
[x] every conversion is typed and versioned
[x] no producer emits ClarificationOption      selection does; producers do not
[x] generate() is the only production generation entry
[x] reduce_universe() is the only production reduction entry
[x] compatibility callers inventoried and RATCHETED
[x] _LEGACY_SOURCE_SCOPE deleted
[x] visible labels, order and patches unchanged
```

`tests/test_every_quantity_candidate_is_natively_typed.py` keeps them closed —
three of its gates are SOURCE SCANS, because a reappearing bridge behaves
identically to the canonical path until the day it diverges, so nothing
observable can catch it.

**The deletion forced a real wiring gap into the open.** With source names no
longer authorising anything, the estimate path refused every live turn: the
stored wire form carries only ids, by design, so options reconstructed from a
pending row have no candidate. The answer turn now resolves them from the
persisted universe via the operation's `decision_id` — which is exactly what
3b.3 stored it for, and the first thing to actually consume it.

**Both 3b follow-ups taken here rather than deferred**, since an
administrative default on a read path is what gets misused later:

* `load_for_replay(decision_id=...)` is separated from
  `load_oldest_for_admin()` **by signature**, so a future production caller
  cannot take the administrative behaviour by omission.
* `why_not()` is **decision-scoped**. "Shown" and "excluded" are properties of
  a decision, not of a universe — the same candidate can be shown on iOS and
  dropped on Telegram by the slot cap.

8080 pass on SQLite and 8080 on Postgres (21 skips).

**4 — the generator.** Approved sources only: exact canonical-entity user
history · validated entity portion evidence · validated product/package
metadata · canonical serving distributions. **Never**: food-name
conditionals, curated per-food option lists, arbitrary tiers, LLM-generated
numeric portions, unverified mass/volume/piece conversion, broad regex
classification. A narrow parser may recognise formal quantities (`1 tbsp`,
`50 g`, `½ package`); it does not decide what to offer.

**5 — status: DONE** *(2026-08-06)*. `skills/nutrition/candidate_selection.py`.

```text
[x] same set + same context + same policy -> identical decision
[x] every generated candidate is selected or excluded exactly once
[x] every exclusion has the actual typed policy reason
[x] the selector reads only persisted candidate features
[x] the selector performs no generation or enrichment
[x] option capacity respected without losing auditability
[x] semantically equivalent candidates merge, better-evidenced survives
[x] distinct serving bases are NOT collapsed when labels collide
[x] exact user history outranks population evidence when applicable
[x] population evidence still cannot authorise "not sure"
[x] a new policy version writes a new append-only decision over one set
[x] the visible row is unchanged — v1 IS the baseline
```

**THE RESTRUCTURE THE DIRECTIVE FORCED.** The selector rendered labels inside
itself, so a wording judgement was indistinguishable from a semantic one:
`RENDER_COLLISION` was attributed to the policy, and a locale that worded two
candidates differently would silently have changed what got SELECTED. Three
stages with three owners now:

```text
select    what each candidate MEANS      pure · versioned · never sees a label
present   what each candidate SAYS       renders, reports its collisions
record    what was offered and why not   the durable decision
```

Policies are **registered, not replaced** — re-registering a version raises,
because a version names one rule forever and redefining it would change what
past decisions claimed to be. The partition is checked inside `select()` as
well as in the aggregate: a new policy is exactly where losing a candidate
gets done, and catching it there names the RULE rather than the record.

`_says_the_same_thing` requires a shared serving basis. `1 piece` and `1 g`
can be numerically adjacent and mean nothing like each other; collapsing them
would delete a distinct option and file it as a duplicate.

The authority ladder falls out of persisted features rather than a special
case: history carries prior 0.55 at confidence 0.9, the ontology median 0.5 at
0.6. **No rule names a source.** The policy signature has nowhere to put a
food name, so a per-food branch cannot be written without changing the
contract — and a source scan holds the purity line, because a selector that
reached for a label would decide identically today and differently the first
time a locale worded two candidates apart.

**5.1 — exactness and a purity proof that cannot be fooled** *(review of
`2a47f40`)*. Two findings, both taken before the contract freeze rather than
carried to it:

* **P1 — the policy still computed in `float`.** Ranking, the near-duplicate
  ratio and the final ordering all crossed `float()`, which contradicts the
  determinism this module claims: two `Decimal` scores differing in the 18th
  place collapse to one binary float, and **generation order silently becomes
  the tie-breaker** — an accidental rule nobody wrote, reachable only by
  inputs nobody would think to test. All three are `Decimal` now, and `_near`
  compares by **multiplication rather than division** (`hi < lo * ratio`),
  because `hi / lo` is exact only to the ambient decimal context's precision —
  process-wide state any library can change, the same trap already found in
  conversion rounding. Ties are now broken by a **stated** rule: the
  earlier-generated candidate, which is the authority ladder's own order.
* **P2 — the purity ratchet was a string scan.** A scan catches an obvious
  call and misses an indirect one. The selector now runs against candidate and
  context **proxies that raise on any attribute outside the approved set**, so
  a future policy reaching for something new fails at the gate rather than
  quietly making decisions the persisted record cannot explain. The scan is
  kept as the cheap first line.

**5.2 — the exactness claim was still false.** *(review of `f40e472`)*
Avoiding division was not enough: `hi < lo * ratio` is still **Decimal
multiplication**, and every Decimal operation is governed by the ambient
context's precision and rounding. `prior * best` in `rank_of` had the
identical defect. Measured:

```text
lo=100.1  hi=125.1  ratio=1.25    exact product 125.125, so hi < it -> True
  prec=3 ROUND_DOWN -> 125  ->  False
  prec=3 ROUND_UP   -> 126  ->  True
```

The same comparison, two answers, decided by process-wide state no caller set.
Both now use **`Fraction`**, which has neither precision nor rounding: the
arithmetic is exact or it does not happen.

**The gate I wrote could not have caught it.** It used `100 x 1.25 = 125` — a
product no precision can round — so it would have passed however wrong the
arithmetic was. The replacement parameterises over operands that *do* round
(100.1/125.1, 80.7/100.8) across four precisions and five rounding modes, and
mutation-verified: restoring Decimal multiplication turns five gates red.

8110 pass on SQLite and 8110 on Postgres (21 skips), 30 selector gates.

**Standing lesson, third instance in this slice:** an instrument that cannot
express the failure it is aimed at reports success indistinguishably from
absence — see also `matched: 0`, the phantom-log detector, and SQLite's
foreign keys.

**Carried forward from the commit-4 review** *(non-blocking, for the
observability pass)*: a candidate-universe read failure currently degrades to
the same refusal as genuine insufficient evidence. The safety behaviour is
right; the two need separating in telemetry —
`estimate_refused:insufficient_evidence` vs
`estimate_refused:universe_unavailable`. And `candidates()` / `select()`
survive for offline tooling with production reachability structurally
prohibited; their deletion belongs with the D7 legacy sweep.

**5 — the selector.** Entity-agnostic, versioned, reproducible, observable,
mutation-tested, and replaceable by a learned ranker later. Every inclusion
and exclusion explainable from persisted features.

**6 — status: DONE** *(2026-08-06)*.
`tests/test_the_known_failures_replay_as_classes.py`, 32 gates. Chicken and
honey are one row each, not the subject.

```text
CLASS A  unsupported estimate    swept over ALL SEVEN serving bases x
                                 {population, this-user, this-product} x
                                 {history-rich, history-empty}
CLASS B  serving-basis mismatch  every cross-basis pair refused without a
                                 sourced conversion; with one, the arithmetic
                                 must land on the offered quantity; a
                                 volume-native food stays volume-native
```

**THE SWEEP FOUND A LIVE DEFECT, which is what a class sweep is for.** The
renderer pushed every candidate through `float(grams)`, so the first volume,
count, piece, package or fraction candidate to reach a real ask would have
raised `TypeError` on `float(None)` and **taken the whole turn down**. The
platform claimed to carry those bases since 3a.2 and could not render one. A
narrow chicken-and-honey regression pair would never have touched it.

Fixed by rendering non-mass candidates from their own `ServingExpression` —
which is what that field exists for — while mass still goes through
`_everyday_labels`, unchanged. Label collision is now compared **only within a
basis**, so `1 piece` and `150 g` can never merge on a coincidence of wording.

**Coverage ledger, asserted rather than assumed:** the generator still emits
mass only, because the portion ontology it reads is in grams. Everything above
proves the PLATFORM carries the other bases; production does not yet PRODUCE
them. A gate fails the day that changes, so someone decides deliberately
whether the ledger still describes reality — *"not produced" is not
"not supported", and neither is "not tested"*.

**6.1 — the matrix I claimed was broader than the matrix I wrote.** Eight
corrections from the review of `4cbffed`:

* **The cross-product was described, not implemented.** Population and
  this-user were swept across seven bases; product evidence was ONE case,
  history-empty ONE case, and the test named "population prior beside the
  user's record" built only the user record — so the thing its name promised
  was never tested. `MATRIX` is now generated: scope × basis × history, with
  `THIS_PRODUCT_QUANTITY` present on the three quantity-bearing bases and
  **excluded by rule** on the others rather than silently absent.
* **"Every cross-basis pair" was five of forty-two.** Generated now from all
  unequal pairs, twice: once proving no basis changes without an authority,
  once proving a conversion must START where the evidence looked.
* **Product evidence ran through `authorizes_assumption` directly.** It goes
  through the full ask → "not sure" → answer route now, against the matching
  variant, a foreign variant and no variant.
* **Labels were never asserted** — only stored expressions. So `3 tbsps`,
  `240 mls` and `2 ozs` sat in the row unremarked: `_expression_label`
  appended "s" whenever the amount was not one. **No rule can fix that**,
  because nothing in a canonical unit id says whether it is an abbreviation,
  and it does not survive a second language. Written forms are now a
  versioned table in `core/unit_registry` (`UNIT_DISPLAY_VERSION`), and the
  rendered labels are asserted across every basis. Mass still goes through
  `_everyday_labels`, unchanged.
* **One assertion was vacuous** — `... and result.patch` inside an `any()`
  after `result.patch` was established as `None`. It could never be true.

8279 pass on SQLite and 8279 on Postgres (25 skips), 159 class gates.

**Carried to the step-8 freeze** *(P2 from the 5.2 review)*: the purity proxy
returns real evidence objects, so a future policy could branch on
`evidence[0].source_type` without tripping it. Tighten to per-evidence proxies
permitting only `confidence`, and narrow the approved candidate and context
fields to those actually read.

**6 — replay the two failures as CLASSES, not as chicken and honey.**
*Unsupported estimate*: weak evidence + "not sure" → no automatic commit.
*Serving-basis mismatch*: volume evidence or volume-based history → volume
candidates preserved, canonical mass conversion stays server-side. Also:
piece-native · count-native · package-native · fraction-native · history-rich
· history-empty · conversion available · conversion unavailable.

**6.2 — word units inflect; symbol units do not.** The registry marked every
volume alias invariant, so an offered expression stating `cup` or
`tablespoon` would have rendered `2 cup` and `3 tablespoon`. Symbols
(`ml · g · tbsp · oz · lb`) and words (`cup/cups · tablespoon/tablespoons ·
ounce/ounces`) are registered separately now, both spellings of a word unit
pointing at one pair so the id a producer happens to use cannot change how the
row reads.

**7 — status: DONE** *(2026-08-06)*.
`tests/test_the_whole_slice_holds_together.py`.

The three corpora that came before each prove one half of the slice, and all
three **predate the durable universe** — not one joins a committed meal back
to the candidate row that justified it. That join is what step 7 closes:

```text
raw message -> operation -> candidate set -> decision -> presented option
            -> tap (by id) -> patch -> nutrition -> card + totals -> telemetry
```

Covered: real Postgres · real enrichment · raw-message routing · restart
between turns · stale and foreign answers · duplicate transport and duplicate
taps · unrelated meals while awaiting · exact candidate, decision, option,
nutrition and telemetry records · and `why_not()` answering for **every**
candidate on a real production turn, never "unknown".

**TWO INSTRUMENT DEFECTS, BOTH SELF-CAUGHT.** The engine reporter read
`db.database.engine` — the module-level engine the harness does not bind to —
and printed `sqlite` with `TEST_POSTGRES_URL` set, so *"this ran on Postgres"*
would have been false while the reporter agreed. It reads the bound engine
now, asserts the binding, and **fails if the variable is set and Postgres was
not used**. The restart test disposed that same wrong engine, simulating
nothing; it drops the real pool on Postgres and re-materialises from rows on
SQLite, where disposing would destroy the database.

**7.1 — the proof was narrower than its headline.** Six corrections:

* **The chain said "tap by id" and the test answered with prose.** `say(label)`
  is LABEL SELECTION — a different route, a different modality — so the one
  path the iOS client will actually use was untested by the test that claimed
  it. It goes through `option_id` now, and asserts the recorded modality is
  `option_id` rather than something else.
* **Real enrichment was never in the same sequence.** The candidate chain was
  proven against a fixed density; live USDA was proven by a separate suite
  that knows nothing about candidates. Neither showed a candidate's own grams,
  priced by the real ladder, producing the row and the card. Now joined —
  **verified running on Postgres with a live key**, and the gate PRINTS
  whether it ran, because a skip reported as a pass is the same instrument
  problem as everything else here.
* **Card and daily totals were in the headline and not in the test.** Both
  asserted now, against the row: `entry_id`, calories, protein, the
  `estimated` flag, and the sentence beside the card.
* **Stale and foreign were conflated** — one case sent a nonsense option id, a
  field id in the wrong parameter, and the CURRENT revision. Three separate
  gates now: a valid option at a stale revision (and the same option at the
  right one, so the refusal is the revision talking), an option never offered,
  and an answer to a foreign field.
* **Duplicate transport and duplicate taps were one test using labels.** Three
  now: the same transport id redelivered, the same option under two transport
  ids, and the label route separately.
* **Provenance attribution** — `USER_SELECTED` on the patch, the telemetry
  source matched against persisted evidence rows, and a plain tap proven to
  name NO policy version, because stamping every row would make that field
  mean "some policy ran".

The unrelated-meal gate also had its claim corrected: an unrelated message is
**held, not logged** — it repairs rather than answering — so "the meal is not
lost" means the board stays empty, the question survives, and the lane frees
afterwards. Asserting the meal had been logged was asserting a design the
system does not have.

**7.2 — two of these were product defects, not test gaps.**

* **THE UNRELATED MEAL WAS WORSE THAN LOST.** Probed live: *"I had some salmon
  too"* while chicken was awaiting drew **"How much was it? A rough amount is
  fine."** — no food named. A user reasonably reads that as a question about
  the salmon, answers it, and the amount prices the **chicken**. The pronoun
  was doing work no pronoun can do. The re-ask now names the food and states
  that anything else mentioned is not logged yet. **The deferred report is
  still not persisted** — that is a real open decision, recorded below, not
  something to call "held".
* **The live-enrichment gate could pass on stale nutrition.** `0.8 ≤ cal/g ≤
  3.0` admits the ask-time 280 cal for any quantity between ~94 g and 350 g,
  so it could not tell repricing from a number that never moved. Now the
  ask-time figure is **seeded at 9999** — impossible for any real food — so a
  stale value is falsifiable without knowing a live density. *(Proportionality
  across two answers was the first attempt and does not work: a second ask for
  the same food replays the settled operation rather than opening a new one.)*
* Source attribution is scoped to the **tapped candidate's own evidence**, not
  matched against the whole universe.
* Transport redelivery goes through **`run_chat_turn` with a repeated
  `msg_id`**, not two direct calls to the answer layer — the dedup that sits
  in front is the layer a real retry hits first.
* The "stale revision" case was a FUTURE revision. In B-1 the revision moves
  in exactly one place — `settle()` — so a stale-but-valid revision on an OPEN
  operation is **not reachable today**. That reachability is now asserted, so
  B-1.5's dependent re-asks will fail this gate rather than inherit a comment;
  and the genuinely stale post-settlement tap is proven to replay.

**OPEN DECISION, BEFORE USER TESTING** — a food reported while a question is
open is refused, not stored. The user is now told, but the report itself is
gone and must be re-sent. Persisting and replaying deferred reports is the
alternative. **Do not describe the current behaviour as "held".**

Mutation-verified: making `save()` persist nothing turns six of seven red.

8319 pass on SQLite and 8319 on Postgres, live-enrichment join included.

**8 — status: PARTIAL. NOT CLOSED.** *(2026-08-06)* — stated plainly because
the standing failure in this slice has been headlines running ahead of gates,
and a contract freeze institutionalises whatever it gets wrong.

**Landed:**

```text
[x] typed RepairReason      no_amount_in_answer · unusable_amount ·
                            estimate_unsupported · universe_unavailable
[x] typed RefusalReason     unknown_option · foreign_field ·
                            revision_mismatch · option_without_patch
[x] repair_reason persisted           b1obs004, indexed for GROUP BY
[x] outage split from evidence        universe_unavailable is its own reason
[x] wire envelope frozen              24 gates, every persisted enum
[x] golden JSON fixtures              13 gates: old bytes decode, round-trip
                                      exact, additive changes compatible,
                                      unknown versions and enums fail shut
[x] selector purity per EVIDENCE      only `confidence`; context only
                                      `maximum_options`
[x] unrelated-report copy contract    names the food, states it is not
                                      logged, PROVES it claims nothing about
                                      saving or queueing
```

**NOT landed, and step 8 does not close until they are:**

```text
[ ] client_message_id in the answer envelope      needs the API surface
[ ] `replay` and `expired` as first-class outcomes  today `replay` is a
                                                  reason on an APPLIED turn
                                                  and expiry is a property of
                                                  the row, not an outcome —
                                                  changing that touches every
                                                  consumer and is the kind of
                                                  edit a freeze exists to
                                                  make deliberate
[ ] telemetry for the RESEND after a refusal      round_index counts attempts
                                                  on one operation; a resend
                                                  opens a NEW one, so nothing
                                                  currently joins them
[ ] CI attached and mandatory                     Actions outage; every number
                                                  in this document remains
                                                  author-reported
```

**ONE REQUESTED ITEM IS REFUSED, WITH REASONING.**
`unrelated_report_while_awaiting` is asked for in the reason taxonomy and is
**not implemented, deliberately**. The answer turn runs BEFORE the interpreter
and receives only the raw message — that ordering is how `"6 oz"` stopped
becoming a second meal. It therefore cannot distinguish *"I had some salmon
too"* from *"it was pretty good"*; doing so needs the interpreter, and
reaching for it there reintroduces exactly the coupling C10 removes. Stamping
the reason anyway would record knowledge the turn does not have.

The user-facing requirement is met without the claim: the re-ask names the
active food and states that anything else mentioned is not logged. A gate
asserts the reason is absent, so this stays a decision rather than an
oversight.

**8.1 — the reason contract, completed.** *(review of `a01950c`)*

* **The overclaim, again, and in the freeze commit itself.** That message said
  *"typed RepairReason and RefusalReason, persisted and indexed"*. Only
  `repair_reason` was. `RefusalReason` existed on the in-memory result and
  stopped at the answer function — so the reason a CLIENT has to branch on
  never reached storage or the wire. Now carried through `AnswerTurn` →
  `CanonicalResponseFacts` → `B1AnswerObservation`, with `b1obs005`
  **forward-only** and an index. A gate asserts it reaches the facts, named
  after the overclaim so it cannot recur silently.
* **`universe_unavailable` was inferred from container shape.** `not
  candidates` conflates a legitimate empty, an operation older than the
  universe, and a read that failed — so a future legitimate empty would be
  filed as an outage. The loader now DECLARES a typed
  `UniverseDisposition(loaded · unavailable · not_applicable)` and `_estimate`
  copies it.
* **`UNUSABLE_AMOUNT` was frozen with no producer.** A planned behaviour in a
  vocabulary meant to describe actual ones — and a value analysis would look
  for and never find, indistinguishable from one that simply never occurs.
  **Removed.** A gate now scans production source and fails on any frozen
  reason nothing can produce; mutation-verified by adding a dead member.
* Reasons are asserted **empty on the outcomes they do not describe**, so a
  field means "this is why" rather than "something happened".

**8364 pass on SQLite and 8364 on Postgres**, live-enrichment join running.

**8.2 — status: DONE.** *(2026-08-06)*

**`REPLAY` is a first-class outcome.** `APPLIED` with `reason="replay"` was an
unstable contract: an authoritative result handed back with nothing written
was indistinguishable from a fresh mutation, so a client could not tell
whether to animate a row and "successful applications" silently counted
repeats. Split into `turn.applied` (authoritative result, new OR replayed —
what every existing caller means) and `turn.mutated` (a new meal was written —
what the count means). Three gates caught the addition, including one written
earlier for exactly this: *"the outcome set changed — re-check which of them
actually ask a question."*

**`POST /api/v1/chat/answer`, Class A, through `mutation_turn`.** Built,
reverted once for non-compliance, and rebuilt properly rather than made to
pass by mentioning the right symbols:

```text
canonical turn id   make_turn_id(channel, client_key, user_id, dedup)
request trace       RequestTrace around the whole turn
durable claim       claim=True; a retry returns the ORIGINAL result and never
                    reaches settlement again
concurrency proof   two deliveries via asyncio.gather through the real ASGI
                    app: one 200, the other 200-replay or 409-conflict,
                    and EXACTLY ONE meal
ledger event        settle() -> write_canonical_meal, in the row's own
                    transaction
```

**ONE IDENTITY, NOT TWO.** `client_message_id` becomes the turn id the claim
is taken under **and** the `source_turn_id` settlement dedupes on. Two dedup
mechanisms would be two answers to "has this already happened", and they would
eventually disagree.

`b1_answer_turn.handle` was added to the `ledger_event` markers under the
reasoning already documented for `execute_tool_calls`: *a route that delegates
owns the turn's identity rather than the write*, so reading only the handler
reports it as leaving no history when it leaves the strongest kind.

**Expiry is modelled explicitly, and is NOT an answer outcome.**
`OwnershipDisposition(holding · expired · settled)`, with
`claims_unaddressed_messages` naming the one thing expiry changes. An expired
operation still accepts an answer ADDRESSED to it — someone replying late is
still replying — so the user never receives "expired" as the result of
answering. A gate asserts `Outcome.EXPIRED` does not exist.

**Golden request/response fixtures frozen.** The five-field envelope, all
required; the response envelope proven to leak no semantics; the committed
request fixture still validating against the current model.

**8.3 — a replay returned the SHAPE of the original, not its CONTENT.**

The commit said *"a retry returns the ORIGINAL result"*. It returned
`{outcome, entry_id}` with **empty bubbles and no card** — so a phone that
lost the HTTP response after the meal committed got back an id and nothing to
show, and would have to reconstruct the confirmation itself or re-fetch. That
is the client-side inference the frozen boundary exists to prevent.

`IdempotencyRecord` stores a durable IDENTIFIER, not a response body, so the
fix is the second option: `facts_from_committed_row()` recovers the result
from the thing that IS authoritative — the row — and re-renders it through
**the same `copy_for`/`card_for`** the first reply used. `_render_answer()` is
now the one renderer for both, so a fresh result and a replayed one cannot say
different things about one row.

**Nothing there recomputes semantics**: no quantity is parsed, no candidate
selected, no pricing run. It reads what was written and says it again.

The claim replay reports the **original outcome** (`applied`) with
`idempotent_replay: true` — that flag is how a client knows it is a
redelivery. `Outcome.REPLAY` still means something different: a NEW request
finding the operation already settled.

**The crash window is tested, not reasoned about.** The meal commits first and
the claim completes in a second transaction; the shared contract documents
that a process dying between them leaves durable work behind an incomplete
claim, and nothing proved what a retry then does. It now kills `complete()`
after the commit, verifies the meal IS durable, retries, and proves **no
second meal** — safety that comes not from the claim, which never completed,
but from settlement finding the operation already settled under the same turn
id.

Mutation-verified: restoring the empty-shell replay turns two gates red.

**8389 pass on SQLite and 8389 on Postgres**, live-enrichment join running.

**CI — CONFIGURED, NOT YET OBSERVED BY ME.** `.github/workflows/ci.yml` runs
on every push to `main` and every PR, against a real Postgres service. This
push triggers it. I cannot read the result: `gh` is not installed in this
environment and I cannot authenticate to the API, so **whether a check
attaches to this SHA is something you can see and I cannot.** Until you
confirm a green attached run, every number in this document remains
author-reported execution evidence.

Resend-to-refusal attribution stays **deferred to B-1b.3** as advised.
`unrelated_report_while_awaiting` stays **unimplemented**, with a gate
asserting its absence.

**7–8** — run the sequence corpus through the real candidate pipeline *and*
real enrichment together, then freeze the wire contract, the semantic
candidate contract and the decision telemetry. **Client work begins only
after that freeze.**

**B-1b.0 — THE INTERACTION HAD NO WIRE CHANNEL.** *(2026-08-06, found by the
iOS integration on its first hour — which is what integrations are for.)*

`POST /chat/answer` requires `operation_id`, `revision`, `field_id` and
`option_id`. **Nothing on the wire could tell a client what any of them
were.** Probed live rather than reasoned about:

```text
serialize_response keys:  v bubbles reaction effect buttons link cards
                          achievement program_updated reasoning
buttons:                  [{label: "1 chicken breast",
                            value: "1 chicken breast"}]   <- a LABEL as a value
pending_clarifications:   the LEGACY question shape, no ids
interaction:              did not exist
```

The interaction was built, persisted and rendered into the SENTENCE — correct
for Telegram, where the sentence is the whole interface — and a native client
had only `buttons`, whose `value` is a label travelling back as semantics: the
round-trip C11 exists to forbid. The endpoint was unanswerable by the client it
was built for.

`Response.interaction` is now on the wire, **additive and optional**: absent
unless a canonical operation owns the turn, so its presence IS the signal that
a structured answer is possible, and older clients are unaffected.

**TWO THINGS THAT ARE NOT DEFECTS, checked before assuming they were:**

* **iOS is deliberately absent from `_CHANNEL_CAPABILITY`.** B-1 declines every
  iOS turn with `client_incapable` BY DESIGN — *"naming it here before then
  would be a capability claim about software that does not exist."* Adding
  `"ios": ID_ADDRESSED` is the LAST step of B-1b, after a build renders
  fields and submits ids. Gates driven through `/api/v1/chat` therefore skip
  on a designed exclusion and prove nothing, so they drive the capable channel
  instead — the wire contract is channel-agnostic.
* **`field_id` rides the FIELD on the wire and the OPTION in storage.** Both
  deliberate: the field computes it as a property, so only options survive
  serialization. A client reads it from the field.

**9 — status: BUILT AND ON DEVICE** *(2026-08-06, `arnie-ios@48cb626`)*.

```text
ClarificationInteraction   ids and labels; no patch, candidate or evidence
ChatResponse.interaction   always present, null on most turns; NON-NULL is
                           the signal a structured answer is possible
answerClarification()      POST /chat/answer, four ids + a stable key
```

**One key per tap, reused on retry** — the server makes it the turn identity
its claim AND its settlement key on, so a resend resolves to the original
commit. Taps are once-only while one is in flight; an unknown outcome fails
safe to "still open" so a newer server cannot make an older build claim a meal
it never wrote; a network failure keeps the question open and the key intact.

**`"ios": ID_ADDRESSED` is now in `_CHANNEL_CAPABILITY`** — added when the
build that honours it existed and not before. Three gates pinned the old state
and had to be updated deliberately, which is what they were for. Exactly one
channel is ID-addressed, and a gate says so.

### B-1b — PROVEN END TO END IN PRODUCTION ON iOS *(2026-08-07)*

The first structured clarifications ever answered by tapping. Read from the
production database, not from a reply:

```text
candidate_sets        3 written, user 26, domain=food, gen b1_quantity_gen_v1
decisions             3, ALL surface=id_addressed   <- the structured path
answers               2 applied via modality=option_id  (entries 2887, 2890)
                      1 applied via text/free_text on telegram (entry 2875)
clarification_answer  257 ms   {claim 34, write 223}
```

**Every exclusion reason fired on a real turn, on day one:**

```text
cand_9ad7f3e4041   semantic_duplicate
cand_0107453db45   selection_cap
cand_0784b20d111   render_collision
```

That is the whole point of the durable universe, working in production: for a
candidate the user did not see, the record says which of the three happened —
never "unknown". Evidence sources so far: **9 ontology, 1 user_history**.

**TWO FINDINGS FROM THE FIRST SESSION, neither an architecture defect.**

**1 — The labels read `118g` and `276g`, not `4 oz` and `10 oz`.**
`_everyday_labels` did not recognise the food and fell back to grams. The
mass path is unchanged and correct; the ontology simply has no everyday
rendering for this item. A product-quality item for the candidate-quality
pass, not a contract problem.

**2 — iOS feels slower than Telegram, and it is not this architecture.**
Measured on the same user (26), same account:

```text
              turns   avg total    LLM    tools   framework
  ios           367     8672 ms   7303     1190         190
  telegram       59     6390 ms   5649      185         556
```

Framework overhead on iOS is **15–154 ms** on 9 of the last 10 turns — LOWER
than Telegram's. The tap is 257 ms. **The latency is the model writing more**:
iOS replies average 223 characters against Telegram's 95, because
`IOS_STYLE` + `NATIVE_CARDS` + `IOS_FORMAT_ANCHOR` (~3,200 tokens Telegram
never sees) teach rich markdown, paragraph structure and card driving. Input
caching is already on with a 1h TTL, so those tokens are cheap to send; the
cost is that Arnie then WRITES 2.3x more.

Trimming that is a PRODUCT decision — shorter replies, less markdown, and the
card layer loses its instructions — so it is recorded here rather than done
silently. **Open: does iOS keep the rich voice or trade some of it for speed?**

**9 — the client** receives and returns identifiers and labels only, and never
generates options, chooses units, converts quantities, infers meaning from
labels, ranks candidates, or recreates missing semantics.

**10 — promotion and closure**, deletion included. B-1 is complete only after
the legacy question producer, answer reconstruction, overlapping pending
ownership and prose-derived options are deleted and C8/C9 lowered.

### Permanent engineering constraints

Standing rules, added 2026-08-06. They bind every slice, not just this one.

> **No semantic decision may depend on a food-name branch, a broad regex
> classifier, an arbitrary threshold, a manually curated option tier, or an
> unsupported conversion.**
>
> **Deterministic parsers are restricted to formal syntax**: quantities,
> registered units, identifiers, transport metadata, narrowly defined
> commands.
>
> **Every candidate, estimate, conversion, assumption and selection decision
> carries typed evidence, provenance, confidence and policy version.**
>
> **When evidence is insufficient the canonical state remains unresolved.**
> The system does not manufacture certainty to complete a turn.
>
> **No new domain introduces an alternate pending owner, answer interpreter,
> mutation path or presentation authority.**

### The remaining programme, in dependency order

Recorded so nothing is lost and the order is not re-litigated per slice.

```text
B-1.9  candidate-system correction      <- current, at 3b (persistence)
B-1    promote + DELETE predecessor + lower ratchets
B-1.5  quantity + preparation_category  (largest exclusion class in production)
B-1.6  conditional dependencies         generic field-activation engine,
                                        never `if fried then ask oil`
B-1.7  accuracy policy over ONE topology — may change ask/assume/defer/
                                        disclose, never storage or writers
B-1.8  answer classification and repair — option id -> narrow field parser ->
                                        pending-aware constrained classifier
                                        -> targeted repair
B-2    multi-item: many events, grouped fields, partial answers, neighbour
       protection, ONE revision, ONE meal commit
B-2.5  SelectEntity · SelectProductVariant · SetPackageSize ·
       SetConsumedFraction
B-2.6  sauces and additions — only nutritionally material fields
B-2.7  generalized option generator — ONLY after several real field families
       exist. Not pulled forward because quantity needs better evidence.
B-2.8  product voice — QuestionIntent + CanonicalResponseFacts only
B-3    PendingOperation as SOLE durable pending owner; delete writes to
       pending_questions, deferred_calls, staged blobs, loose payloads
C-1    every remaining conversational food writer through the coordinator
C-2    canonical corrections (quantity, identity, preparation, additions,
       meal type, date, removal) as operation revisions
C-3    canonical undo by stable committed event id — no "last meal" heuristic
C-4    ONE PresentationSnapshot for chat, cards, totals, timeline, coach feed,
       notifications, widgets, API
C-5/6  one resolver coordinator, one ambiguity engine, policy separate
C-7    food production-readiness gate — food is NOT half-migrated when
       workouts begin
D      generalize under the RULE OF TWO only: shared OperationRequest /
       OperationResult / outbox, domain payloads stay typed
E/F    workouts — structured first, then conversational, on the SAME spine.
       No separate workout pending or chip architecture.
G      weight · hydration · supplements · medication · vitals, same spine
```

**Directive 1 restated, because it is the whole method:** every capability runs
`measure → define semantic field → add typed evidence → build canonical
producer → persist PendingOperation → apply typed patch → commit canonically →
produce committed facts → validate in production → promote → delete
predecessor → lower ratchet`. **No slice skips deletion.**

### B-1 is now a PROMOTION project, not an implementation project

**Augmented 2026-08-06 from team review.** Every commit until now answered
*"can this architecture work?"*. From here they answer *"can we trust it
enough to delete the old one?"* — a different question, and the roadmap says
so rather than leaving the shift implicit.

```text
lifecycle implementation      COMPLETE
persistence                   COMPLETE
settlement                    COMPLETE
presentation boundary         COMPLETE
evidence harness              COMPLETE
Postgres engine validation    COMPLETE
logic matrix                  COMPLETE
product evidence              IN PROGRESS
structured client             NOT STARTED
promotion                     NOT STARTED
legacy deletion               NOT STARTED
```

**"Implementation complete" is not "slice complete."** The last three lines are
the slice.

#### Track A — production evidence. Finishes first.

> **A1 — THE ARCHITECTURE IS FROZEN.** No new abstractions, no new ownership
> concepts, no shared framework work. Bug fixes only. Every generalisation is
> cheaper after the evidence and irreversible before it.

| | | |
|---|---|---|
| **A1** | freeze | in force from 2026-08-06 |
| **A2** | finish instrumentation — every clarification measurable | ✅ closed below |
| **A3** | internal observation window — observe, do **not** optimise | running |
| **A4** | real-enrichment validation **in production**, not another synthetic test | pending traffic |

**A2's eleven signals, and where each lives.** Nothing else is built until
every clarification can be analysed end to end.

```text
shown              pending_operations                      (durable)
accepted           b1_answer_observations.modality         chip | label
free-text override b1_answer_observations.selected_source  free_text
repair             b1_answer_observations.outcome
estimate           modality=command + MODE_DEFAULT
cancellation       outcome=cancelled
abandonment        pending_operations.status = expired     <- was UNANALYSABLE
latency            b1_answer_observations.latency_ms
correction window  b1_correction_observations
candidate source   selected_source + offered mix
copy version       question_version
```

**Abandonment was the hole, and it was structural.** The funnel table holds
ANSWERS, and a question the user walked away from never produced one — so
every rate computed from it silently conditions on *"they replied"*, and
completion % was not derivable at all. It is the loudest possible statement
that a question was not worth asking, and an answers-only dashboard is blind
to it by construction. `scripts/b1_option_scorecard.py` now reads the
operation table for a `shown → committed / cancelled / abandoned` lifecycle
and reports completion against questions **asked**, never against questions
answered — the second number is the flattering one.

#### Track B — product refinement. Only after the evidence exists.

```text
B1  clarification wording    version every change; copy is an experiment;
                             never overwrite a baseline
B2  candidate ranking        history weighting, ontology ranking, portion
                             generation — telemetry decides, not taste
B3  voice harmonization      eliminate the two-Arnie-voices seam only.
                             NOT adaptive coaching. Renders
                             CanonicalResponseFacts, never the commit result.
```

#### Then, in order

```text
B-1d structured client   -> after candidate quality is understood, so the UX
                            is not hard-coded around weak suggestions
promotion                -> internal -> 1% -> 5% -> 25% -> 100%, evidence-driven
deletion                 -> legacy quantity clarification, legacy pending
                            ownership, legacy answer routing, legacy
                            presentation for this slice; then lower ratchets
```

> **DO NOT START B-2 — or preparation, added fat, multi-item, or workout
> clarification — until B-1 is promoted AND its predecessor is deleted.**
>
> The temptation will be to reuse the new architecture immediately *because it
> is working*. That is exactly how a second generation of legacy paths gets
> created, and this migration exists because it happened once already. The
> order is **prove → promote → delete → reuse**, and only the last step is
> allowed to be fun.

### Closing B-1 — the production-evidence ladder

**Augmented 2026-08-06 from team review.** The earlier plan made organic
traffic the sole sequencing gate: observe, wait, then build. That was an
overcorrection. Synthetic *acceptance* data would measure our model of the user
rather than the user — true, and still true — but low traffic must change the
**label and confidence** of evidence, not suspend the migration.

| | step | exit condition |
|---|---|---|
| **B-1a** | measurement wording | ✅ versioned `b1_quantity_q2` |
| **B-1b.1** | deterministic system-validation matrix | ✅ **GREEN** — Postgres-backed, real enrichment exercised |
| **B-1b.2** | production-sequence corpus | green under Postgres and real pricing |
| **B-1b.3** | instrumented human simulation | internal panel shows the interaction is understandable |
| **B-1b.4** | natural-traffic confirmation | continuous; confirms rather than gates |
| **B-1c** | safety observability | ✅ coverage and precision proven |
| **B-1d** | structured iOS client | **may start after B-1b.1 + B-1b.2** — does not wait for organic volume |
| **B-1e** | promote → delete predecessor → lower ratchets | after B-1d proof |

**B-1d is deliberately not gated on B-1b.3 being statistically significant.**
Start it once the system matrix and sequence corpus are green and no structural
redesign of the candidate contract is known — then run B-1b.3 *through the iOS
client*, because the structured `option_id` path is the actual intended
interaction and testing it in prose is testing something else.

### Evidence classes — what a given source may legitimately prove

| class | what it can prove | valid source |
|---|---|---|
| **System correctness** | ownership, persistence, settlement, idempotency, replay, pricing, card/totals agreement, telemetry | automated production-like scenarios |
| **Candidate quality** | source availability, option spread, degenerate forks, history recall, ontology coverage, ranking | real account history + deterministic dry runs |
| **Interaction usability** | whether the wording and choices are understandable; whether people know they can type an amount or say "not sure" | structured internal human testing |
| **Natural preference** | true acceptance, free-text preference, abandonment, correction over time | **real production usage only** |

**No simulated result may be reported as natural preference.** Absence of
organic traffic changes the label, never the sequence.

### B-1b.1 — the deterministic system-validation matrix

Canonical path, production-like Postgres, **real enrichment enabled**. Every
axis crossed:

```text
candidate source   history · calibrated ontology · fallback · none
answer route       exact label · typed offered · typed NOT offered ·
                   "not sure"/MODE_DEFAULT · malformed -> REPAIR · cancel ·
                   stale · foreign · duplicate delivery
quantity basis     grams · ounces · mass answer replacing non-mass ask-time
                   data · conflicting ask-time macros removed before pricing
outcome            commit · repair · cancel · refuse · internal failure · replay
```

Each scenario verifies **database state, never reply text**: exactly one
operation · expected revision · expected terminal state · 0 or 1 meal commit ·
0 or 1 food row · resolved quantity and provenance · real `analyze()` result ·
card and totals agreement · expected telemetry · duplicate execution
impossible · health detector executed · no legacy fallback after ownership.

**Status 2026-08-06.** `tests/test_b1b1_system_matrix.py`, 17 scenarios.

* **Postgres backing — CLOSED.** The harness fixture binds the real engine in
  a private per-test schema when `TEST_POSTGRES_URL` is set, via
  `make_engine` (the codebase refuses an unpinned Postgres engine by
  construction). The file **asserts its own dialect**: without the variable it
  passes on SQLite and skips with a message saying that is not B-1b.1
  evidence; with it, the dialect must genuinely be `postgresql` in an isolated
  schema. Verified directly — engine `postgresql`, `search_path`
  `harness_…`, real rows written.
* **Real enrichment — CLOSED.** `tests/test_b1b1_real_enrichment.py` runs the
  canonical path against the live USDA/Open Food Facts ladder, gated on
  `USDA_API_KEY` so its absence SKIPS loudly rather than weakening the matrix
  quietly. Verified by counting calls: 8 real results for "Chicken breast",
  committing **165.0 cal at 100 g** — the correct density, matching production
  entry 2860 exactly.

  **And the ladder's refusal machinery is what earns that.** USDA's top hit
  for "chicken breast" is *"Chicken breast tenders, breaded, uncooked"* at 263
  cal/100 g; for "white rice" it is rice FLOUR at 359; for "salmon" it is fish
  OIL at 902. All three carry no confident match, the ladder declines to seat
  them, and the committed number is right anyway. Raw lookup quality is poor;
  the authority ladder is the reason that does not reach a user.

  Assertions there are **relational, never absolute** — pinning a calorie
  number would encode today's USDA index and fail on a data refresh for
  reasons unrelated to B-1. What must hold whichever row wins is that the
  answered quantity drives the result.

> **Reporting rule, because these were conflated once.** State the backing
> store, not the run flag. *"Suite run under Postgres; matrix scenarios
> Postgres-backed"* is a different sentence from *"7,914 pass on Postgres"* —
> the second says only that the run had the variable set, and was true for
> months while every one of these scenarios executed on SQLite.

Found while closing it: `DROP SCHEMA … CASCADE` at teardown deadlocks against
the same engine's pooled connections (`asyncpg.DeadlockDetectedError`). The
pool is disposed first and the drop runs on a throwaway connection.

### B-1b.2 — the production-sequence corpus

Naturally occurring *sequences*, not isolated states:

```text
clarification -> answer -> unrelated new meal
clarification -> answer -> duplicate answer
clarification -> delayed answer after another operation opens
clarification -> cancel -> new meal
clarification -> repair -> valid answer
clarification -> internal failure -> retry
clarification -> deploy/restart -> answer
clarification -> duplicate webhook delivery
clarification -> prior meal referenced in the reply -> new question
clarification -> correction within ten minutes
```

Through real routing, real persistence, **fresh database sessions between
turns**, real pricing, production-equivalent platform capabilities, the
expected deployment configuration, and durable telemetry queries.

> **Simulate sequences, not desired outcomes.** A scenario must begin from raw
> user messages and production-shaped account history and pass through real
> routing, candidate generation, persistence, answer application, enrichment
> and commit. It may control the user's next reply; it may **not** directly
> construct the internal state it exists to validate, unless the test
> explicitly targets that isolated contract.
>
> Every defect this slice produced that shipped green came from violating this:
> a fixture built the state it then asserted, so the assertion could not fail.

### B-1b.3 — instrumented human simulation

Preference cannot be inferred from synthetic answers, so recruit rather than
wait. 5–10 people · 10–15 sessions each · 50–150 interactions, mixing familiar
foods, foods with history, foods with no ontology row, vague portions, branded
foods that B-1 excludes, and deliberately awkward quantities. Real product
surface; participants answer naturally and are **not told which option is
expected**.

Capture: selected option · typed amount · "Other" · "not sure" · repair ·
abandonment · time to answer · immediate correction · qualitative reason after
selected sessions.

This is **usability** evidence, not retention evidence. It is sufficient to
validate the interaction contract and to begin B-1d.

### B-1b.4 — natural-traffic confirmation

A confirmation stream, not the gate. Confirms: no behaviour absent from the
corpus · real users understand the wording · correction and abandonment are not
materially worse · no channel-specific issue · candidate-source distribution
resembles the tested corpus. **Low sample size is reported explicitly** and
blocks nothing unless it reveals a severe contradiction.

### B-1 promotion gates

Promotion means deleting the legacy quantity path. Blocked until all hold.
**No arbitrary organic sample count is required** unless traffic later becomes
sufficient to justify one.

```text
[ ] production-like system matrix green            (B-1b.1)
[ ] production-sequence corpus green               (B-1b.2)
[ ] real analyze() pricing verified through the canonical path
[ ] internal human simulation shows the interaction is understandable (B-1b.3)
[ ] no known severe candidate-generation defect remains
[ ] structured iOS option_id path production-proven (B-1d)
[ ] natural traffic, where available, shows no contradictory severe signal
[ ] B-1c detector coverage and precision remain live
[ ] 100% of eligible turns canonical under the rollout cohort
[ ] rollback tested
```

### Coverage ledger — "not seen organically" is not "not tested"

Kept current. Four columns per required behaviour, so a gap in one column
cannot masquerade as a gap in the system.

| behaviour | automated sequence | internal human | organic | status |
|---|---|---|---|---|
| history option offered | ✅ matrix (PG) + control | pending | none yet | **sufficient** |
| typed non-offered amount | ✅ matrix (PG) | pending | 2 observations | **sufficient** |
| real `analyze()` pricing | estimate lane only | pending | ✅ density lane (2860) | partial — needs USDA key |
| duplicate delivery | ✅ harness | unnecessary | ✅ proven | **sufficient** |
| settled op declines new meal | ✅ harness | pending | ✅ proven | **sufficient** |
| expired op declines new meal | ✅ harness | pending | none yet | **sufficient** |
| stale revision / foreign field | ✅ harness | pending | none yet | **sufficient** |
| estimate / "not sure" route | ✅ matrix (PG) | pending | 1 observation | **sufficient** |
| abandonment preference | not simulable | pending B-1b.3 | none yet | **provisional** |
| long-term correction rate | not simulable | limited | none yet | **unresolved** |

### B-1b finding 1 — the `piece` fallback produces unusable option sets

**Recorded 2026-08-06. Evidence, not opinion. Deferred, not fixed.**

Measured with `scripts/b1_option_dryrun.py` over the 60 most-logged real foods
of a real account — real foods, real history, the deterministic producer, and
**no synthetic answers**. The correlation is total:

```text
ontology specificity   foods   degenerate   share
category                 33         0         0%
fallback                 18         0         0%
piece                     9         6        67%   <- no ontology row
```

A "degenerate" set is two options 2× or more apart with nothing between —
not a choice, a fork. Every one of them is `specificity='piece'`, meaning the
portion ontology has **no row for that food** and falls back to a generic
piece bracket:

```text
39x  Barebells Salty Peanut Protein Bar   ['2 oz', '5 oz']    2.6x
14x  Banana                               ['98g', '276g']     2.8x
 3x  Grilled chicken breast               ['5 oz', '16 oz']   3.3x
```

**It reproduces the production observation exactly.** Live, a chicken-breast
question offered `6 oz` / `16 oz`; the dry run gives `5 oz` / `16 oz` for the
same food. And under the standing bias-high rule a "not sure" answer then takes
the upper of two, which committed **435 g of chicken breast, 718 cal** on
2026-08-06. The estimate logic is correct; it was handed a fork.

Two further signals inside the same data:

* **Countable foods are bracketed by mass.** A protein bar offered as "2 oz or
  5 oz" is not a question anyone answers. Whether B-1 would ask at all is a
  separate matter — see the caveat below.
* **The three-anchor set collapses to two** in `_collapse_by_label` when the
  lower and median render alike, so the middle value disappears precisely
  where the bracket is widest.

**Scope, and why it is deferred.** Wording ("say it more like a person") is
B-2.8. This is not wording — it is *candidate generation*, which B-1b exists
to evaluate and B-1.5+ inherits. Fixing it now would be optimizing a generator
before the window has finished saying what is wrong with it. It is recorded so
promotion cannot happen while it is unexamined.

**The instrument's honest limit.** The dry run **cannot apply `is_eligible`** —
that needs a decision with staged items, which cannot be built from a food
name. So the corpus is foods *logged*, not foods B-1 would *ask* about; a
branded bar may be declined as `identity_ambiguous` and never reach a
question. **Read the per-specificity rates, not the headline total.** The
unambiguous in-scope case is grilled chicken breast, and it matched production.

*(An earlier version of this tool reported "0 degenerate sets" — it measured
the raw ontology anchors and skipped `_collapse_by_label`, which is where the
degeneracy is created. A clean number from an instrument pointed at the wrong
stage; the same failure as the trace ring, one layer up.)*

### Open findings — deferred, not dropped

Each is real, none blocks the current phase, and none may be closed silently.

| finding | evidence | owner |
|---|---|---|
| `/admin/food-traces?q=` is ignored — substring queries return EVERYTHING, not nothing | measured 08-05 | instrument fix, unscheduled |
| `phantom_log_claim` fires in the harness but showed `flags=None` on both production incident turns; `skills_fired` is NULL even on turns that wrote rows, so the column cannot say why | measured 08-06 | **unrecorded until now** — needs a cause before it is trusted as a safety net |
| the legacy lane re-logged a meal already on the board (entry 2862 duplicated 2861, `legacy_reason=interpreter_none`) | measured 08-06, row deleted | D7 — the path B-1 replaces |
| `reask_refused` firing for user `ios:5` on the legacy lane | observed 08-05 | uninvestigated |
| `scripts/b1_operation_probe.py` cannot exercise B-1 — it drives `/api/v1/chat`, which is `PLATFORM="ios"`, excluded until B-1d | by design | B-1d |
| zero history-sourced options across all asks so far | 7 asks, all `sources=ontology` | B-1b decides whether this is recall or ranking |
| two voices: B-1 turns render from a template, legacy turns from the composer, so the assistant sounds different depending on which lane owns the turn | measured 08-06 | item 2 above |
| user pseudonyms in the food stream are UNSALTED — `FOOD_TRACE_SALT` is set in no deployment config, and account ids are small integers, so `user=u…` reverses by enumeration. The raw id is on ~10 neighbouring lines of the same stream regardless | measured 08-08 | the process now warns once; closing it is a stream-wide logging policy, unscheduled |
| the `stages=` breakdown legitimately sums to MORE than `total_ms` (speculative enrichment runs during the LLM stream), and nothing on the line says so — a reader attributing time by summing it is wrong by construction | measured 08-08, by design | documentation, unscheduled |
| `pricing.usda_search` still runs on the ASK turn — the P1.4 seam cut was scoped to the B-1 answer/settle function, which an ask never enters | measured 08-08, in scope | not a defect; recorded so it is not rediscovered |
| P0.2 `TurnCoordinator` (`core/turns/*`, gated by `TURN_COORDINATOR_MODE`) is a SECOND migration this directive does not track, and `planner=legacy-adapter-v1` on a `structured_food` turn belongs to it | observed 08-08 | needs its own sequencing authority, or a section here |
| the `battery` CI job FAILS when `ANTHROPIC_API_KEY` is absent, rather than reporting neutral/skipped — a job asserting a result it cannot know, and a permanently red check that teaches everyone to ignore red | observed 08-09, every PR that triggers it | configure the secret to make it authoritative, OR make an unavailable secret a neutral state; NOT left red. **Confirmed 08-10**: the cloud containers cannot run the key-dependent suite at all, so this is why the 08-09 work shipped unverified — a credential gap, not a discipline gap |
| **answering a preparation can make pricing WORSE.** `salmon\|` carries 13 qualified candidates; `salmon\|grilled` has none, because USDA holds no curated "salmon, grilled" row — so stating the preparation moves that food from artifact-priced to estimate-priced. Only chicken and beef have real coverage across grilled/roasted/fried | measured 08-10, full 64-identity build | **needs a decision, not a default.** Falling back `entity\|preparation` → `entity\|` would price a stated preparation from evidence about a different identity, which is the substitution the field exists to prevent |
| `chicken\|` carries NO qualified pricing evidence — 0 of 15 rows survive, because bare "chicken" returns spread, fat, frankfurter and bologna | measured 08-10 | not a defect: the boundary working. Recorded because plain "I had some chicken" therefore prices from the ESTIMATE rung, and a trace reader will otherwise misread that as the artifact failing |
| **artifact coverage is 16 seed entities; production logs foods outside it.** The 08-10 session logged halibut and steak, neither in `SEED`, so both priced from the ESTIMATE rung with no artifact consulted | measured 08-10 | see the rebuild triggers below — bare-entity coverage is a routine rebuild; PREPARED coverage is blocked on the fallback decision, not on effort |
| **preparation uses a WEAKER materiality rule than every other uncertainty.** `space_is_material()` is a pure density RATIO (`MATERIAL_SPREAD=1.25`) with no portion, no day targets and no accuracy mode, while `skills/nutrition/materiality.is_material()` — whose own docstring says "ONE rule, wherever the question is being considered" — takes all three. The ratio is not merely coarser, it is INVERTED in real cases: mushrooms at 60 g (29 vs 39 kcal/100 g) clear 1.25× and get asked about a **6 kcal** difference, while a food at 300 g (150 vs 180) fails the gate and stays silent on **90 kcal** | measured 08-10 | **B-1.7**, with the accuracy-mode policy. Do NOT tune `MATERIAL_SPREAD` — that would be guessing at the same wrong measure. Danny 08-10 also raises a second axis the calorie rule cannot express: preparation sharpens IDENTITY (it becomes the food-memory key, so the next log prices from memory in ~130 ms), which argues for a lower bar for this field specifically |

**Closed 2026-08-08 — the telemetry of one production turn (build `2a8856035e66`).**
One iOS B-1 clarification, correct end to end, whose record was not admissible
as promotion evidence. Ten defects, all fixed, none of which changed what the
user got:

| finding | why it mattered |
|---|---|
| `food_trace` reported `stopped_at=context asked=0 committed=0` on a turn that asked and committed — the interpreter ask origin recorded no CLARIFY stage, `Stage.INTERPRET` had no call site anywhere (audit C5, 07-28), and neither answer route opened a span at all | the triage spine could not describe the lane being migrated TO |
| `latency_ms=10894` for an answer given in 2,560 ms — `asked_at` read `row.created_at`, and Postgres `now()` stamps TRANSACTION start | 76% of the "user latency" behind the *provisional* abandonment row was our own backend |
| `repairs` read `owned.revision`, which this codebase documents as deliberately not moving on a repair — a constant 1 on every commit | the metric B-1.8 would be judged by |
| `rounds` was never passed, so it reported its default of 1 forever while `round_index` sat durably in the observation rows | multi-round asks were invisible |
| `cohort` was never persisted on the operation, so answers and commits reported `-` and the durable observation row stored empty | the funnel broke at the conversion step — the gate is "100% of eligible turns canonical under the rollout cohort" |
| two unrelated rollouts printed a key called `cohort` into one stream, disagreeing (`live` vs `allowlist`) on the same turn | filtering `cohort=live` for natural traffic swept in allowlist-only canonical turns — the evidence-class error forbidden above |
| `food_policy_v1` named both the legacy ledger constant and the native P0.2 stage's | `policy=food_policy_v1` could not evidence that the native stage ran |
| `request_done` emitted `outcome=` twice on every line, and `setdefault` let the two values differ | a `dict(pairs)` reader silently took the last |
| `voice_ttfb_ms=0` beside a named `voice_model` on every turn — the field was never written by anything, and the composer does not stream | a model credited with copy on no evidence; `voice_ms` now carries what is measurable |
| prose inside `k=v` lines (`b1_not_a_replay`, `meal_commit` duplicate) | the stream is the measurement surface and it has to parse |

Ratchets: `tests/test_the_canonical_lane_is_on_the_trace.py`,
`tests/test_the_b1_counters_mean_their_names.py`,
`tests/test_the_food_log_stream_parses.py`.

**An eleventh came out of REVIEW, not the capture, and it is the general form
of the other ten.** Every defect above was one term standing in for another:
the clarifier's approval reported as a commit, the operation's revision
reported as a repair count, observation rows reported as rounds. Fixing them
one at a time left the funnel's terms still undefined, so the next collapse
had nowhere to be caught. The names are now a CHAIN of strictly strengthening
claims, and no two of them may be proxies for one another:

```text
interpreted   the model produced an item
staged        canonical staging ACCEPTED it, with typed identity
written       a row was flushed into the transaction
committed     that transaction COMMITTED
visible       the committed truth reached the reply (a `mark`)
```

Two terms were missing, and their absence was load-bearing:

| term | what its absence did |
|---|---|
| `items_written` | `items_attempted` meant "calls we tried" on the legacy lane and "rows successfully flushed" on the canonical one. The canonical lane writes into a caller-owned transaction where flush and commit come apart; the legacy lane's helpers commit independently, where they do not. A name true on one lane is not automatically true on the other |
| `items_interpreted` | `stage_items` silently drops a raw row with no food name, so a staging REJECTION — the model proposing something the canonical types refuse — was indistinguishable from the model proposing nothing. An undercount at the funnel's mouth understates every rate below it |

Consequences now enforced: `attempted` is stamped BEFORE the writer runs, so a
writer that raises reports `attempted=N written=0` instead of `attempted=0`
(a turn that tried and failed reading as a turn that never tried);
`committed_durably()` promotes `written`, so a writer handed three items that
lands two reports `committed=2`; and both ask origins report `interpreted`,
because a term only some origins emit is worse than no term — a structural
zero and a measured zero are the same token in the log.

Ratchet: `TestNoTermIsAProxyForAnother`, which drives the turns where the
terms DIVERGE. Every previous coordinator test handed the writer exactly as
many items as it returned, which is where a correct implementation and three
broken ones are indistinguishable. Its origin ledger fails when a THIRD ask
origin reports `staged` without `interpreted`.

Five things in the same capture read as defects and are **correct** —
`stages` outrunning `total_ms`, `pricing.usda_search` at ask time,
`turn_phase … ms=0`, `planner=legacy-adapter-v1`, and `b1_not_a_replay` firing
on later messages. Recorded above or in the review so they are not
re-litigated. (On the last: a terminal operation staying durable and being
consulted defensively is not stale-operation corruption, *provided* it then
returns None and neither claims nor mutates the new turn — which those three
lines show it doing.)

**A sixth was withdrawn on review, and the distinction is worth keeping.**
`b1_answer_held … open=0` was originally recorded here as correct-by-design.
That claim was too strong and conflated two different truths:

```text
TELEMETRY TRUTH   open=0 accurately reported the operation's stored state.
                  Zero fields were open according to what was persisted, and
                  `hold_answer` running before the readiness check is the
                  designed order. The LINE is not lying.
PRODUCT TRUTH     whether preparation SHOULD have been open on that item is a
                  separate B-1.5 semantic question, and this capture cannot
                  answer it. Preparation was observed activating for
                  "had some chicken"; if it should also have been open here,
                  the stored state was wrong and the line faithfully reported
                  a wrong state.
```

A trace that accurately reports bad state and a trace that reports good state
are indistinguishable from the line alone. Filing this under "correct" would
have closed a live B-1.5 question using telemetry evidence that cannot reach
it — which is the same class of error as reading allowlist traffic as natural
preference. **It is now an open B-1.5 item**, below.

### ⚠ OPEN — preparation activation must not depend on quantity wording

**The invariant, and it is the actual B-1.5 defect surface:**

```text
same canonical identity + preparation absent
    => preparation activation cannot depend on how the QUANTITY was worded
```

Preparation was observed opening for `"had some chicken"`. Whether it opens for
`"200g chicken"` — same food, same missing preparation, different quantity
wording — is unproven. If it does not, then quantity phrasing is silently
deciding whether a *different* field exists, and the `open=0` above was a
faithful report of wrong state rather than a clean terminal answer.

**Owed as its own change, NOT folded into the telemetry work.** The gate:

| message | expected |
|---|---|
| `some chicken` | quantity **+** preparation |
| `200g chicken` | preparation only |
| `7 oz chicken` | preparation only |
| `grilled chicken` | quantity only |
| `200g grilled chicken` | no clarification — settle |

The 2026-08-09 tracing work exists partly to make this diagnosable: `operation=`
now joins the ask to its answer, `Stage.CLARIFY` records what opened, and
`asked=` counts it — so the next capture can say which fields opened on which
wording instead of leaving it to be inferred from a terminal `open=0`.

### Release gates — where the whole product stands

**Team assessment, 2026-08-06.** B-1 proves the migration *method* and the
hardest ownership mechanics. It does not mean every food behaviour has moved.

> **These percentages predate 50 commits and are NOT re-scored here** (noted
> 2026-08-09). Since they were set: B-1.5E C1+C2 landed, the canonical pricer
> replaced `_analyze_food` in settlement, two P0 ledger guarantees landed, and
> the lane's telemetry was found wrong and repaired. Those move "Food logging
> migration" upward. Pulling the other way: CI has been red the whole time, so
> none of it is Postgres-verified, and Gate 1 explicitly requires "telemetry
> readable, failures visible" — which was FALSE for the canonical lane until
> 2026-08-09 and is a condition, not a percentage.
>
> A number invented by whoever last edited the file is worse than a dated one,
> because it reads as a fresh judgement. Re-score these when the team next
> assesses; until then treat them as of 08-06.

```text
Core backend architecture        80–85%
Food logging migration           60–70%
Production-ready food product    55–65%
Entire Arnie V1                  45–55%
Tightly controlled beta          close
Broad consumer release           not yet
```

| gate | goal | position after |
|---|---|---|
| **1 — Internal canonical product** | daily internal use with no manual DB intervention: B-1 promoted, detector silence explained, pricing and card/totals verified, corrections and undo safe for the supported scope, telemetry readable, failures visible | 55–60% of V1 |
| **2 — Closed beta** | the common food workflow end to end: B-1 → ~B-2.7, single and multi-item, branded foods and package fractions, preparation and additions, Quick/Moderate/Strict, corrections/deletion/undo, structured iOS, one presentation authority, no critical legacy duplication on eligible turns | 70–80% |
| **3 — Release candidate** | chargeable: every intended slice promoted, overlapping legacy writers deleted, clarification ownership consolidated, voice boundary stable, output consistent, onboarding, billing, analytics, error budgets, rollback playbooks. **This is where the serious voice and diction pass belongs** — the renderer finally sits on stable intents and committed facts | 90–95% |
| **4 — Public release** | staged rollout completed, acceptable duplicate/false-confirmation/correction/abandonment rates, stable latency, no unresolved severe data-loss path, release-blocking legacy deleted, privacy and account-deletion reviewed, support process live | shipped |

The last 5–10% after Gate 3 is not features. It is reliability proof, rollout
evidence and cleanup.

**Rough ranges** (two focused engineers, architecture reusing cleanly, no
foundational surprise — planning aid, not a commitment):

```text
close and promote B-1                          1–3 weeks
common single-item clarification surface       3–6 more
multi-item, products, additions                4–8 more
corrections, undo, presentation consolidation  3–6 more
production hardening and closed beta           3–5 more
staged broad release                           2–4 more

credible closed beta        8–14 weeks
release candidate          14–22 weeks
broad rollout              16–26 weeks
```

**What is NOT yet canonical, and gates production readiness.** Logging commits
canonically; these still do not: corrections and edits · additions to an
existing meal · deletion · undo · replacements · merge/split · delayed and
out-of-order answers · proactive follow-up actions. A system is not
production-ready while logging is canonical and correction takes a separate
mutation path. Those are Phase C-1 through C-3.

### Earlier items — superseded or still live

Reconciled rather than carried forward silently:

```text
P3  chips on every question        SUPERSEDED for quantity by B-1; still open
                                   for every other attribute (B-1.5+)
P4  undercount as a commit gate    STILL LIVE, unscheduled
P5  resolving state, latency copy  STILL LIVE, unscheduled
Phase 1b invariants I2/I7/I8       STILL LIVE, unscheduled
adversarial gap hunt before push   STILL LIVE, unscheduled
```

