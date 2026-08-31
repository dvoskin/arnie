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
