# PREREGISTRATION — the C re-run after the invariant-basis repair

**Written and committed BEFORE the run.** Nothing below may be edited after the
first turn executes; a changed prediction is a new document with a new date.

## Danny's acceptance condition (verbatim, 2026-08-31)

> It isn't enough for the north-star ask rate to improve again. It must improve
> **without changing the materiality decision of an unresolved fact merely
> because C re-parented it.** If C still wins after that, then its benefit is
> finally attributable to the intended DEFAULTABILITY behavior rather than a
> scorer artifact.

## What changed since the last C run

1. **The repair.** `FoodAmbiguity.impact_basis_cal` is state on the FACT.
   `attach_ambiguities` consumes it instead of rediscovering a denominator from
   the owning row. Whole-item facts are untouched; a component-scoped fact
   (`extras`) now carries an explicitly NOT-ESTABLISHED basis instead of the
   parent's calories.
2. **C is a declared arm, not a tree edit.** `FOOD_EXTRAS_REPORT_ONLY`, off in
   `render.yaml`, spliced into the interpreter prompt by `[[XTRA…XTRA]]`.
   ⭐ Both arms therefore run from **ONE commit with one `_code_sha`** —
   `MEASUREMENT_ARM` records the varied flag under `_arm`. The previous C
   measurement compared `407ed03` against `79ece8a`; this one cannot.

## Arms — three runs, 25 cases × 2 reps each

| run | arm | `FOOD_EXTRAS_REPORT_ONLY` | role |
|---|---|---|---|
| D1 | A | false | baseline |
| D2 | A | false | **null twin of D1** — the drift envelope |
| D3 | B | true | treatment |

Effect = D3 vs mean(D1, D2). Envelope = \|D1 − D2\|. **No effect-size claim may
use an envelope built from fewer than two comparable runs on the same
behavioural SHA** — that rule is why D2 exists.

## ⭐ THE PREDICTION, stated before the run

The repair makes an `extras` fact material whenever its span reaches **26
calories**, whatever its parent — measured, not assumed. C reports the mayo as
`extras` with a span the interpreter has put at 80–150 across every capture.

**Therefore c1's mayo ask should COME BACK under C, and C's ask-rate reduction
should collapse toward zero.**

- **Predicted:** `|D3 − mean(D1,D2)|` falls **inside** the envelope. C shows no
  reliable ask-rate effect once the artifact is gone.
- **Falsified if:** C still reduces asks by more than the envelope. That would
  mean a SECOND mechanism exists, and it must be found and characterised before
  any adoption — a surviving effect is a new question, not a vindication.

If the prediction holds, C's original measured benefit is fully attributed to
the denominator artifact, and C is dead as an ask-rate intervention. It may
still be defensible as a *representation* change (it does move c1's component
count toward the corpus's frozen `expected_component_range` of [1,1]) — but that
is a different claim, tested against different labels, and it is NOT in this
run's scope.

## What is measured

Per case and rep, from the frozen JSONL:

1. **ask rate** — `q_kinds` containing `food_structured_ask` (the D1
   denominator; `conversation_hook` and `food_clarification` are NOT food asks).
2. **staged vs interpreter authority** — `staged_raised` via `question_id`.
3. **every ambiguity's `field_name`, `material`, and `impact_basis_cal`** — new
   this run. ⭐ This is the direct test of Danny's second clause: an `extras`
   fact must carry `impact_basis_cal = None`, and its materiality must not
   correlate with its parent's size.
4. **staged item count** per case, against `expected_component_range`.
5. **c17** — the case both previously-rejected variants drove to 0.25 and 0.00.
   Must stay at 1.00.

## ⛔ Refusal conditions — the run is VOID, not "noisy", if any hold

- `pin_config` raises, or `_code_sha` differs between the three runs.
- `differs_only_in(D1, D3, {"FOOD_EXTRAS_REPORT_ONLY"})` is not `(True, [])`.
- Any run records a config whose `_arm` disagrees with its intended arm.
- The `impact_basis_cal` capture is absent or all-`None` on whole-item facts —
  that would mean the instrument is reading a field the producer never fills,
  which is the inert-read failure that voided two censuses on 2026-08-28.

## What this run does NOT decide

- Whether `impact_cal` is a truthful span (registered upstream,
  `condiment_span_truthfulness`).
- The `DAY_SHARE_OVERRIDE` predicate divergence (registered, own tranche).
- The 1-calorie residual window between the two encodings — pinned by
  `test_the_residual_gap_is_ONE_CALORIE_WIDE`, and a consequence of the
  interpreter naming the parent rather than the component.

---

## AMENDMENT 1 — 2026-08-31, after the first attempt was VOIDED

**The prediction above is unchanged and was not looked at against any data.**
This section records only what happened to the first attempt.

The first three arms ran and were **voided by refusal condition 1**: they
recorded `0181534`, `0181534-dirty`, `0181534-dirty`. The cause was the
instrument, not the product — `scripts/analyse_c_rerun.py`, untracked and
imported by nothing, was written while arms 2 and 3 were in flight.
`git diff 0181534 -- core skills handlers db scripts render.yaml` is empty and
no commit touched those paths, so all three arms ran byte-identical product
code.

⛔ **That proof was NOT accepted in place of the rule.** Arguing past a
preregistered refusal with an after-the-fact demonstration is the failure this
document exists to prevent. No effect number was computed or read from the void
arms; the analysis script refuses before reporting one, and it did.

Outputs kept as `data/corpus/VOID_census_D*_2026-08-31.jsonl`.

**Fixed so it cannot recur** (`scripts/config_pin.py`): modified TRACKED files
still dirty `_code_sha`; UNTRACKED files are recorded by name under
`_untracked`. A marker that says something changed without saying what can only
be argued with, never adjudicated.

The re-run is arms **E1 / E2 / E3**, same design, same prediction, on a clean
tree. Cost of the void attempt: 150 turns.

---

## AMENDMENT 2 — 2026-08-31, after the E arms landed

**The prediction above is unchanged.** This classifies its outcome in the
three-way vocabulary adopted *because of* this document's gap, and records the
gap itself.

### The gap

This preregistration enumerated two outcomes:

- **the effect falls inside the envelope** — predicted
- **the effect survives in the predicted direction** (C still REDUCES asks) —
  falsifying

The result was neither. **The effect survived with its sign reversed:** C
increased asking by +7.5 against a null envelope of 1. That outcome had no name
in this document, so a decisive result had to be classified after it was seen —
the ordering preregistration exists to forbid.

The gap was not carelessness about this run. **Only the outcomes I could imagine
wanting got written down**, which is the bias preregistration exists to remove,
arriving through the document's own structure.

### The outcome, in the vocabulary now required

```text
BENEFIT   not observed
NULL      not observed
HARM      ⛔ OBSERVED. E3 30/50 against 22/50 and 23/50; null envelope 1;
          effect +7.5, outside it and in the opposite direction to the
          intervention's purpose.
```

**Action bound by the HARM branch, and taken:** optimization stopped. C was not
tuned, not re-thresholded, not re-run at another setting. The reversal was
characterised (`docs/C_RERUN_RESULT_2026-08-31.md`) and C was permanently
rejected. No further candidate was designed from it.

### Prediction scorecard

- **Clause 1 — HIT, exactly.** c1's mayo ask returned: `extras`, span 150,
  basis `None`, score 5.976, material, 2/2 reps.
- **Clause 2 — WRONG, and unfalsifiable as written.** "Collapses inside the
  envelope" did not happen, and the way it failed could not be expressed by the
  falsification conditions this document set.

Recorded as partially unfalsifiable rather than as a hit.

See `docs/PREREG_TEMPLATE.md` and
`tests/test_a_preregistration_declares_all_three_outcomes.py`.
