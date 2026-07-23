# Food Logging — Ironclad Evaluation (2026-07-23)

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
# behavioral matrix (needs ANTHROPIC_API_KEY)
PYTHONPATH=. python scripts/eval_food_matrix.py
# deterministic suite
ANTHROPIC_API_KEY="" pytest tests/ -p no:randomly -q
```

The matrix is the regression battery for the logging brain: every future
prompt or pipeline change should keep it at 20/20 and add its own case.
