# Food Logging — Ironclad Evaluation (2026-07-23)

> **UPDATE 2026-07-29 — the "20/20" below was measured through a broken
> harness. Read this first.**
>
> The battery's fake user carried `preferences.calorie_target` and nothing
> else. Materiality scores against `compute_macro_targets(user)`, which
> DERIVES the day's goals from weight/height/age/sex and raises on a user with
> none; `_daily_targets` swallowed that and returned `None`, which drops
> `is_material` off its proportional day-share engine onto the legacy ABSOLUTE
> thresholds. **Every ask-or-log verdict in this document was scored by an
> engine production does not run.** Fixed by giving the eval user real body
> stats (they compute to 2163 cal / 180 g protein — the numbers the decorative
> fields claimed).
>
> A single run also never scored a commit. The battery is a live-model matrix
> and several cases were genuinely non-deterministic: measured over 8 runs,
> "usual + two matches" passed 3 times and "multi-item split" 5 — and one of
> those was passing *for the wrong reason*, since running cases concurrently
> blows the 6 s turn budget and a timeout surfaces as the `ask` the case
> wanted. The battery now runs each case `EVAL_REPS` times (default 3),
> **serially**, counts a case green only if every rep passes, and exits
> non-zero on FLAKY. It also refuses to start without `ANTHROPIC_API_KEY`
> rather than scoring the all-auth-fail run as a plausible 6/20.
>
> Four real product defects were hiding behind the broken harness and the
> single-run scoring — a categorical strict rule enforced as a swing rule, a
> pointer whose failure was invisible, a stated amount re-asked, and a stated
> range read as our invention. All four are fixed; see the 07-29 section at the
> end. Current state: **21/21, five reps each, zero flaky.**

Full-system evaluation of the food-logging brain at `main` (post-7c55538),
run three layers deep. Verdict up front: **the English chat-text lane is
solid — 20/20 on the live behavioral matrix, deterministic invariants green,
and 14 days of prod data fully coherent. The remaining risk lives at the
edges: Russian-language turns, destructive operations, and the photo lane —
all of which still run on the legacy path.**

## Method

1. **Deterministic suite** — full pytest run, hermetic env (no API key,
   `-p no:randomly`): gates, thread routing, say contract, token fill,
   reconciliation, enrichment demotion, receipts truth, program rotation.
2. **Live behavioral matrix** — `scripts/eval_food_matrix.py`: 20 cases
   against the real FOOD_LOGGER_MODEL, each one a canonical production
   failure we fixed or a behavior Danny locked. Action + shape + calorie
   assertions, not vibes.
3. **Prod data scan** — read-only, all users, 14 days: macro/calorie
   coherence, zero-cal-with-macros, single-entry outliers, same-day dup
   groups, daily-total drift vs entry sums.

## Results

### Live matrix: 20/20

| Family | Cases | Result |
|---|---|---|
| Action routing (log/ask/pass, plans, questions, destructive, workout) | 8 | all pass |
| Strict brand discipline (Barebells saga) | 3 | all pass |
| Regulars pointer ("my usual X", 3 states + brand overlap) | 4 | all pass |
| Count/mass anchoring (truffle-fries saga) | 2 | all pass |
| Board corrections (scale, off-board pass, keep-as-is) | 3 | all pass |
| Say contract (no model-invented totals) | 1 | pass |

Notable confirmations:
- **Keep-as-is closes the thread at the GATE** — "Leave it like this" after a
  proposed bump can never reach the logger (deterministic, not model-behavior).
- **5-6 fries now price per piece** (~150-220), not as a menu side. Fixed
  during this eval with a calibration example in the count rule (same
  precedent as the venue-schmear rule).
- **Regulars resolve verbatim** — the logger copies the user's own history
  numbers exactly, and exact-name matches legitimately win the pointer over
  fuzzier candidates ("my usual coffee" → the regular literally named
  Coffee…; two non-literal coffees → asks which).

### Deterministic suite: green

One stale test repointed: `test_prompt_ships_id_discipline` asserted a legacy
prompt line the deliberate July-7 revert (017d436) removed; entry-id
discipline now lives (and is asserted) in the structured logger's board
contract. This test had been red since the revert — pre-existing, unrelated
to any recent change.

### Prod data (14 days, all users, 349 entries)

- Macro-incoherent rows (calories vs 4P+4C+9F off >±30%): **0**
  (the one offender — Danny's truffle fries, from a client-side edit race —
  was repaired, and `_reconcile_macros` now makes the class impossible).
- Zero-cal rows with real macros: **0**. Entries >3000 cal: **0**.
- `daily_logs` totals vs entry sums: **0 drift**.
- Same-day duplicate groups: 6 → five are hours-apart plausible re-eats;
  **one is a real defect**: user 3 (RU) logged Сметана+Творог twice, 4
  minutes apart (07-22) — see gap #1.

## Fixes shipped during this evaluation

- Count rule calibration example (fries per-piece pricing; was 280-340, now
  ~150-220) and "count = HIGH confidence, don't stack the bias-HIGH rule".
- "TWO OR MORE plausible regulars → ALWAYS ask, never pick by frequency."
- Regulars renderer no longer silently drops malformed rows (`name`/`food`
  fallback) — an invisible regulars list made the pointer rules dead letters.
- Stale id-discipline test repointed at the structured board contract.

## Standing gaps, ranked

1. **RU lane (P1, prod evidence).** The structured gate is EN-keyed → Russian
   turns fall to legacy, and legacy dedup missed a 4-minute double-log
   (user 3, 07-22). Options: localize the gate regexes (small set), or gate
   on a cheap language-agnostic food classifier. Until then RU users get
   pre-rebuild behavior end to end.
2. **Destructive ops are still legacy (P1).** Tonight's transcript: "delete
   that meal" hit the wrong entry (strawberries instead of the bagel batch),
   and "Remove them" NARRATED a deletion that never executed, then joked
   about it. Deletes need the same treatment corrections got: a structured
   lane resolving against the board with entry-ids, plus a claimed-delete
   verifier (count rows before/after; never narrate an unverified delete).
3. **Photo lane is legacy (P2).** The 07-15 interaction audit measured 71%
   photo-turn failure. The structured logger only sees text today.
4. **Water/weight lanes legacy (P2, low risk).** Simple single-tool turns;
   fine for now, but they're outside the say-contract guarantees.
5. **Structured workout turn (P0, already tracked as task #20).** The last
   big log type on the old brain.
6. **Watch item:** executor dedup could still false-block a structured item
   re-logged across turns (same name+qty later the same day is sometimes a
   real re-eat). No prod evidence yet — Danny's hours-apart pairs above all
   landed. Keep watching.

## How to re-run

```
# behavioral matrix — the key MUST be exported (a worktree has no .env, and
# the script now refuses to run without it rather than scoring 6/20)
export ANTHROPIC_API_KEY="$(grep '^ANTHROPIC_API_KEY=' /path/to/arnie/.env \
    | cut -d= -f2- | tr -d '"'"'"' ')"
PYTHONPATH=. .venv/bin/python scripts/eval_food_matrix.py   # EVAL_REPS=5 for a harder pass
# deterministic suite
ANTHROPIC_API_KEY="" pytest tests/ -p no:randomly -q
```

The matrix is the regression battery for the logging brain: every future
prompt or pipeline change should keep it green — **all 21 cases passing every
rep** — and add its own case. A FLAKY case is a failure, not a footnote: it is
what let a re-broken behaviour read as a pass. Run it from a worktree on
`main`, never the primary checkout.

---

## 2026-07-29 — re-run at `cca96be`, harness repaired, four defects fixed

Re-measured because the battery was reading 15/20. Establishing what was a
real regression versus model variance came first, and it changed the answer
twice: serial re-runs promoted one "flaky" case to a stable pass (its failures
were my own harness's concurrency) and demoted another from flaky to stable
FAIL (its passes were timeouts landing on the expected `ask`).

### The harness was measuring the wrong engine

See the note at the top. Consequence: cases were tuned against absolute
thresholds while production ran proportional ones. Repairing it flipped
`usual + two matches` green on its own, and exposed `5-6 fries`, which had
only ever passed *because* the proportional engine was switched off.

### Defects found and fixed

| # | Defect | Root cause | Fix |
|---|---|---|---|
| 1 | Strict + branded + unstated flavour logged instead of asking (0/5) | The prompt states this rule with no threshold in it — "ALWAYS an ask, REGARDLESS OF SWING SIZE" — but `_proposed_ask_is_material` routed it through the consequence engine anyway. A Barebells line sits inside ~30 cal, so the ask was demoted every time. The Barebells saga, arriving through the gate built after it. | `core/food_turn.py`: a strict-mode identity/brand unknown on an item the interpreter flagged `branded` is categorical and never demoted. Which flavour it was is a question about identity, not magnitude, so an engine that scores how wrong a *number* might be cannot see it. |
| 2 | "my usual coffee" with no regulars returned `pass` — left the lane and wrote nothing (0/5) | The REGULARS block is emitted only when regulars exist, so a pointer that resolves to nothing arrived as bare prose. The prompt's rule for exactly this case never fired because nothing told the model it *was* that case; "coffee" then hit the standing "never ask about black coffee" rule. | `core/food_turn.py`: when the message carries a usual-pointer and the list is empty, state that fact. The rule already existed and only ever lacked its premise — the same failure the adjacent malformed-entry guard already names. |
| 3 | A stated count re-asked as a menu portion ("5-6 fries" → "the small side or the full share plate?") | `attach_ambiguities` lifted the interpreter's residual *quantity* span onto an item whose amount the user had given, spending the one interruption we get on the only field not in doubt. | `core/food_pipeline.py`: a `CONSUMED_QUANTITY` ambiguity is not lifted when the amount is stated. The span stays on the item and keeps informing the estimate; it stops being something we interrupt for. Identity/prep/package unknowns are untouched — an amount does not answer those. |
| 4 | The same case still flaky: identical, correct interpreter output logged or asked at random | Two blind spots in the stated-amount proxy. (a) One food can span two clauses — "some fries…, like 5-6 fries" — and clause scoping kept the half saying "some". (b) A stated *range* read as our invention: the interpreter averages "5-6" to `5.5`, which appears nowhere in the text. Outcome depended on whether the model emitted its OPTIONAL `basis` field. | `core/food_turn.py`: `_refining_clauses` lets a later clause naming the same food (matched on head noun only, so "half a banana" still cannot refine peanut butter) supply the amount; and any value inside a stated range counts as stated. |

### Battery changes

- Real body stats on the eval user, so materiality runs its production path.
- `EVAL_REPS` (default 3), **serial**; a case is green only if every rep is.
  FLAKY is a failure and the script exits non-zero. Do not parallelise for
  speed — it does not measure the same thing.
- Hard preflight on `ANTHROPIC_API_KEY`.
- Retired `say never carries model-invented totals`. It was **vacuous**: it
  compared `enforce_say_contract(say)` to `say`, and the interpreter stopped
  emitting prose (`451fb35`, `f3aa3be`), so `say` is always `""` and the check
  passed on equality-of-nothing regardless of model behaviour. It read as a
  live guard and guarded nothing. The contract is alive at
  `core/conversation.py:2153` against the composer's line — a layer `FT.run`
  does not reach — and is unit-tested. Replaced by two honest cases: the
  interpreter emits no prose on a clean log, and an unfixed unit ("a bowl of")
  is asked about, which is the deliberate post-`5fba5f4` behaviour the old
  expectation predated.

### Verification

- `21/21`, `EVAL_REPS=5`, serial — 105 live runs, zero flaky.
- Full pytest suite: 6102 passed, 0 failed.
