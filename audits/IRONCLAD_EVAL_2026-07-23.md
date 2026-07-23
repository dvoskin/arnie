# Ironclad evaluation — structured food logger — 2026-07-23

Scope: the full logging stack as of `7c55538` (== `origin/main`): the structured
logger (`core/food_turn.py`), its wiring in `core/conversation.py`, the tool
executor write paths, and the test/simulation nets around them.

Execution environment note: this evaluation ran in a cloud session with **no
`ANTHROPIC_API_KEY` and no `DATABASE_URL`**. Everything hermetic ran to
completion here; the two live phases ship as committed, ready-to-run harnesses
with their exact commands below — they need a machine that has the key / prod DB.

## Phase 1 — hermetic test suite (RAN)

`pytest` (default `-m "not behavioral"` selection): **2223 passed, 14 failed,
8 skipped, 17 deselected**.

Every one of the 14 failures is **test debt from an intentional behavior
change** — none indicates a live product bug. Three groups:

### Group A — stale prompt-wording pins (7 tests)
`test_food_logging_simulation_suite` (×5), `test_entry_id_and_freshness::
test_prompt_ships_id_discipline`, `test_food_logging_sim::TestPromptRuleIntegrity::
test_multi_item_list_logs_first_then_refines`.

These assert exact phrases of the legacy system prompt. The July-7 scale-back
revert (`017d436`) re-worded that prompt. The **rules survive** in current
wording — LOGGING FIDELITY block at `core/prompts/arnie.py:1269`, entry-id
distinctness discipline at `arnie.py:653` — but pinned strings like
`"not an assumed garlic bread"` and `"NEVER GUESS AN [#id]"` no longer appear
verbatim. Fix: re-pin to the current wording (or pin section presence, not
sentences). One nuance worth a human look: the explicit "never guess an id"
sentence is gone; only same-id-twice distinctness survives. If the guess-an-id
failure mode ever recurs on the legacy path, restore that rule rather than the
test string.

### Group B — stale USDA-override policy pin (1 test)
`test_sodium_sanity::test_mass_stated_salt_record_drops_sodium` expects a
`"likely"` USDA match to override calories (50/100g × 200g = 100). Since
`58847b5` (USDA overrides only on near-identical name match), a "likely" match
keeps the logger's own 90. The test's actual point — implausible sodium is
dropped — **still passes**; only the forward-path calorie assert pins the old
policy. Fix: update the assert to the new policy (calories stay 90 unless the
match is near-identical).

### Group C — stale coaching-contract pins + a REAL infra bug (6 tests)
`test_pipeline` (×3), `test_streaming` (×1), `test_query_history_extension`
(×1), `test_screenshot_cascade` (×1).

Two things at once:

1. **Stale contract**: these assert `chat_follow_up` fires on a pure food-log
   turn. Since fast-log-voice single-source (`core/conversation.py:1315` —
   "NEVER the legacy follow-up"), pure-food turns are voiced by `voice_log` or
   the structured say; `follow_up == 1` can never hold again. They fail on any
   machine, keyed or not. Fix: rewrite against the voice_log/say contract.
2. **Infra bug (fixed in this branch)**: `core/log_voice.py:27` binds `chat`
   at import, so fixtures patching `conversation.chat` never reach it — on a
   keyed machine, `voice_log` was silently making **live paid API calls inside
   the "hermetic" suite** (nondeterministic, ~2 retries × 8s timeout per food
   turn). `tests/conftest.py` now has an autouse guard that blocks
   `log_voice.chat` for every non-`behavioral` test; a test that wants scripted
   voice patches `core.log_voice.chat` itself. Full-suite results are byte-for-
   byte identical before/after the guard (14F/2223P), ~18s faster.

## Phase 2 — deterministic adversarial sim (RAN)

`simulate_logging_discipline.py`: **12 failing assertions, all one class** —
the add-cue contract ("2nd oatmeal", "a couple more", "ещё один …", "twice"
→ expect a **second row**). Since RECONCILE-BEFORE-LOG
(`handlers/tool_executor.py:2216`, Danny 2026-07-02: a second protein bag makes
the first row read "2 bags"), an add-cue **folds into the same row** — quantity
merged, calories/protein summed, day totals correct, readback honest. The sim's
contract is stale against a deliberate product decision. Consequence: the
`--prove-regression` self-proof reports INCOMPLETE for the gate toggle (the
baseline is already red, so neutering the fix changes nothing) — the sim is
currently **useless as a regression net** until its add-cue expectations are
rewritten to "same row, grown quantity, summed macros, correct day total".
Everything else in it is green: DB readbacks, exercise roll-up, weight
source-aware coexistence + manual headline, leak sweep, and the weight-toggle
regression proof still fires correctly (150/300 assertions fail with the fix
off, restore clean).

## Phase 3 — live behavioral matrix (HARNESS COMMITTED; needs the key)

`scripts/ironclad_eval.py` — 35 canonical cases from this saga against the
REAL logger pass (`core.food_turn.run`, live model, production prompt):
10 deterministic gate rows plus 25 live rows covering keep-as-is (truffle
fries), piece-count anchor, board corrections (birria / "2 of those" / not-on-
board / no-relog), say-contract enforcement, regulars pointer (one/two/zero
matches), strict branded-flavor asks, brand preservation + `is_packaged`,
fraction and mass fidelity, venue-real dense portions, ask thresholds by mode,
answer-turn never re-asks, thread complaints/confirmations/chit-chat. Every
log row also asserts macro coherence (cal ≈ 4P+4C+9F), editable "amount unit"
quantities, and zero machinery leaks.

Ran here: the 10 gate rows — **10/10 green**. The 25 live rows need the key:

    set -a; source .env; set +a
    .venv/bin/python scripts/ironclad_eval.py --runs 3

## Phase 4 — prod data-coherence scan (HARNESS COMMITTED; needs prod DB)

`scripts/prod_coherence_scan.py` — READ-ONLY, all users, all food rows +
day-log roll-ups. Seven invariant classes: machinery LEAK in names/quantities,
ROLL-UP drift (stored day totals vs row sums), NO-DUPES (same log+name+qty
within 3 min), EDITABLE quantities (the "~2 handfuls romaine, 3 strips
chicken" class), macro COHERENCE, physical BOUNDS (incl. the 4000mg sodium
clamp, retroactively), CLEAN NAMEs. Validated here against a seeded scratch DB
with planted violations: **every planted violation flagged, one per class,
zero false positives on clean rows**. Run where `DATABASE_URL` points at prod:

    .venv/bin/python scripts/prod_coherence_scan.py            # all time
    .venv/bin/python scripts/prod_coherence_scan.py --days 30

Report lands in `audits/prod_coherence_<date>.md`; exit 1 on any critical
class (LEAK / ROLL-UP / DUPES).

## Gap map

| # | Gap | Class | Severity | Action |
|---|-----|-------|----------|--------|
| 1 | `voice_log` live-called the paid API inside the hermetic suite on keyed machines | test infra | HIGH | **FIXED** — conftest autouse guard |
| 2 | Discipline sim add-cue contract contradicts RECONCILE-BEFORE-LOG; prove-regression INCOMPLETE | stale sim | HIGH | rewrite add-cue expectations to the fold contract |
| 3 | 6 tests pin the dead `chat_follow_up` pure-food contract | stale tests | MED | rewrite against voice_log/structured-say |
| 4 | 7 tests pin pre-revert prompt sentences | stale tests | MED | re-pin to current wording; human check on the dropped "never guess an id" sentence |
| 5 | 1 test pins pre-`58847b5` USDA override policy | stale test | LOW | update the forward-path assert |
| 6 | The structured logger had no live behavioral net (existing evals target the legacy path) | coverage | HIGH | **CLOSED** — `scripts/ironclad_eval.py` (needs keyed run) |
| 7 | No standing data-coherence check over prod rows | coverage | MED | **CLOSED** — `scripts/prod_coherence_scan.py` (needs prod run) |
| 8 | Suite hermeticity depends on the key being ABSENT; nothing enforces it | process | LOW | run CI/pre-deploy suites with the key unset; the conftest guard covers the known leak |

## Verdict

The product code paths evaluated hermetically are sound: 2223 tests green, all
14 reds are contract drift in the nets, not defects in the stack. The two nets
that would catch tomorrow's regressions (discipline sim, live matrix) need the
sim contract update (#2) and one keyed run of the matrix to be trustworthy
end-to-end. Ironclad = run Phase 3 and Phase 4 on the box that has the key and
the prod DB; both are one command each.
