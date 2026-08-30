# B — RE-MEASURING THE D2 EXCEPTION BEHIND PROVENANCE

**Preregistered BEFORE the run. Danny, 2026-08-30.**

## Why the old evidence cannot settle it

The exception (adding `extras` + `multiplier` to the interpreter's field
vocabulary, and attaching the closed vocabulary to the ASK branch) was reverted
because **"zero-ambiguity asks" rose 28 % → 42 %/38 %** and records fell
30 → 22 → 20.

A rise in *"zero INTERPRETER ambiguities"* could mean either:

```
(a) the interpreter became less structured        <- a real regression
(b) the staged pipeline legitimately raised more asks   <- an authority shift
```

**Before provenance, those looked identical.** Now they do not.

## ⛔ THE RIGHT DENOMINATOR

NOT `interpreter ambiguities present / absent`. For **every user-visible ask**:

```
ask -> producer -> requested fields -> canonical subject -> rendered text
```

`total structured asks` = asks carrying structure from **EITHER** authority.
That is the quantity the old measurement could not see.

## Decision rule — frozen before the run

| observation | conclusion |
|---|---|
| **total structured asks STABLE, staged share RISES** | the old "structure regression" was mostly an AUTHORITY SHIFT. **The revert rationale dissolves**, and B can likely proceed by giving `unstated_extras` an explicit representation. |
| **total structured coverage FALLS across BOTH authorities** | the revert was substantively correct. **Keep it reverted**; find another B repair. |
| **producer mix changes AND product behaviour changes materially** | treat the PRODUCER SHIFT ITSELF as the finding. Call it neither harmless nor a regression until the rendered questions are inspected. |
| **run noisy / incomparable** | **publish no conclusion.** |

⚠ Run-to-run drift on this corpus has already been observed larger than some
effects measured on it (asks 25 → 30, staged 13 → 10 between two identical
censuses). **Drift is a live candidate for the fourth outcome, not a footnote.**

## Baseline

`data/corpus/census_v4_postrepair_2026-08-29.jsonl` — `code=4049778`, 50 turns,
same corpus, same reps, same config. The exception run differs by the prompt
edit ALONE.

## Constraints

- **No DEFAULTABILITY or product-behaviour change** on the strength of the old
  revert evidence.
- The exception is re-applied to be MEASURED, not adopted. Adoption is a
  separate decision that this run informs.

---

# OUTCOME CATEGORIES — FROZEN 2026-08-30, BEFORE THE RESULT (Danny)

```
1. structure loss ABOVE the drift envelope           -> obstacle CONFIRMED;
                                                        keep the revert rationale
2. producer shift ABOVE the envelope, total          -> the old revert rationale
   structure STABLE                                     DISSOLVES
3. mixed change ABOVE the envelope                   -> inspect USER-VISIBLE
                                                        behaviour before any
                                                        adoption decision
4. any effect INSIDE the drift envelope              -> NO CONCLUSION, full stop.
                                                        No directional narrative.
```

> **Random movement must not become policy.**

## ⛔⛔ AND EVEN A DECISIVE RESULT DOES NOT ADOPT THE EXCEPTION

If the run strongly shows the old revert rationale was wrong, that **removes a
false blocker**. It does not make the exception desirable. **Adoption is a
SEPARATE decision, taken in a separate step**, on its own merits.

## ⚠⚠ MY DRIFT ENVELOPE IS NOT MEASURED FROM A TRUE NULL

I cited *asks 25 → 30, staged 13 → 10* as a "no-code" envelope. **That is not
accurate.** Those two censuses were `census_v3` (`0b5f432`) and `census_v4`
(`4049778`) — and `4049778` contains **repair A**, which edits the composer
prompt on every clarification.

**No two censuses in this project share a code SHA.** So the envelope is
inferred from runs that also changed code, which makes it an UPPER bound on
drift conflated with whatever those changes did.

Consequences, stated rather than smoothed over:

- the envelope is **conservative in the wrong direction** — it may be too WIDE
  (absorbing real effects into "drift") or too NARROW (if repair A suppressed
  variation);
- **outcome 4 is therefore easier to reach than it should be**, which is the
  safe way to be wrong;
- a true null — two censuses at identical code — has never been run, and is the
  cheapest thing that would make every future comparison on this corpus
  interpretable.

**Using it as a floor is defensible; treating it as a measured null is not.**
Any conclusion drawn here inherits that limitation.

---

# RESULT — **OUTCOME 4 on the blocker question**

Baseline `4049778` vs exception `ede35b9`. 50 turns each, same corpus, config,
harness. Raw: `data/corpus/census_v5_exception_2026-08-30.jsonl`.

```
                                        BASE   EXC    Δ      envelope(±)
asks                                      30     25   -5      5   AT EDGE
staged-raised                             10     12   +2      3   inside
asks WITH structure (either authority)  29/30  24/25          —
staged field-instances                    13     18   +5
interpreter field-instances               41     28  -13
```

## ⭐ NORMALISED PER ASK, STRUCTURE IS UNCHANGED

```
total field-instances / ask     BASE 54/30 = 1.80     EXC 46/25 = 1.84
asks carrying structure         BASE 96.7 %           EXC 96.0 %
```

**The raw drops track the ask count, not a loss of structure.** The Δ-13 in
interpreter field-instances looks alarming and is almost entirely five fewer
asks plus a partial shift to the staged producer (+5 there).

## Classification

**Δ asks −5 sits AT the provisional envelope edge; Δ staged +2 is inside it.**
By the frozen rule:

> **OUTCOME 4 — INSIDE the envelope → NO CONCLUSION, full stop. No directional
> narrative.**

The old revert rationale is **neither confirmed nor dissolved.** It is
**unresolved**, and — per the census contract — this cannot even be called
*"inside measured drift"*, because the envelope has no true null behind it.

## ⭐⭐ ONE RESULT IS **NOT** SUBJECT TO THE ENVELOPE

```
interpreter emitted `extras`:      6      (baseline: STRUCTURALLY IMPOSSIBLE)
interpreter emitted `multiplier`:  0
interpreter emitted `consumed`:    0
```

`extras` is **not in the baseline vocabulary at all** — the baseline cannot emit
it under any amount of drift. Six emissions are therefore **definitively caused
by the exception**, and this is a CATEGORICAL observation, not a magnitude
comparison. Drift envelopes do not apply to a value that could not previously
exist.

> **The exception does give `unstated_extras` an interpreter producer.** That
> is established.

⚠ **And it delivers ONE of three.** `multiplier` and `consumed` were added to
the same vocabulary in the same edit and appeared **zero** times. Naming a field
in the schema is still not sufficient for the model to use it — the third
demonstration of that in this session.

## What is and is not decided

```
does the exception create an `extras` producer?      YES — established
does the exception cost structural coverage?         UNRESOLVED — outcome 4
should the exception be adopted?                     NOT DECIDED, and NOT to be
                                                     decided in this step
```

**Next: the same-SHA null pair.** Until a measured null exists, the coverage
question cannot be resolved in either direction — that is the whole point of the
census contract, and this run is the first thing it has blocked.

---

# ⭐⭐⭐ THE NULL PAIR — AND A WITHDRAWN CLASSIFICATION

Two censuses, **identical code `ede35b9`**, same corpus/config/harness. The
first true null in this project.
Raw: `data/corpus/census_v6_nulltwin_2026-08-30.jsonl`.

```
                    run A   run B   NULL Δ
asks                   25      24        1
staged-raised          12      12        0
staged field-inst      18      18        0
interpreter f-inst     28      27        1
total field-inst       46      45        1
total / ask          1.84    1.88     0.03
```

> **This census is FAR more stable than I assumed. The provisional envelope
> (asks ±5) was roughly FIVE TIMES TOO WIDE.**

## ⛔ THE "OUTCOME 4 — NO CONCLUSION" CLASSIFICATION IS WITHDRAWN

It rested on an invented envelope. Against the measured null the effect
**exceeds it on every metric**:

```
metric                   effect Δ   null Δ   verdict
asks                        5          1     EXCEEDS
staged-raised               2          0     EXCEEDS
staged field-instances      5          0     EXCEEDS
interpreter field-inst     13          1     EXCEEDS
total field-instances       8          1     EXCEEDS
```

**The exception has a real, measurable effect.** Had I stopped at the
provisional envelope I would have filed a genuine effect as noise — the exact
error the census contract was written to prevent, caught by the first
measurement it demanded.

## Classification: **CATEGORY 3 — MIXED CHANGE ABOVE THE ENVELOPE**

```
producer shift      staged-raised +2, staged field-instances +5   -> toward staged
interpreter loss    interpreter field-instances -13
total structure     54 -> 46 absolute (DOWN 8)
per-ask density     1.80 -> 1.84 (slightly UP)
ASK COUNT           30 -> 25  (DOWN ~17 %)
```

Not category 1 (total structure did not simply collapse — per ask it rose) and
not category 2 (total structure is **not** stable in absolute terms). It is
**mixed**, and the frozen rule says:

> **inspect USER-VISIBLE behaviour before any adoption decision.**

## ⚠ THE FINDING THAT MATTERS MOST IS THE ONE I WAS NOT MEASURING

**The exception reduces clarifications by ~17 % (30 → 25 asks), an effect 5×
the null.** That is a PRODUCT BEHAVIOUR change, not a telemetry change: Arnie
asks the user fewer questions.

Whether that is good or bad **depends entirely on whether the dropped asks were
material** — and nothing measured so far says which asks disappeared. A
capability win (`extras` producer) sitting on top of an unexamined 17 % drop in
asking is not a trade anyone has evaluated.

## Status

```
unstated_extras producer   PROVEN     6 and 7 emissions across the pair
structural cost            REAL       exceeds the measured null on every metric
which asks were lost       UNKNOWN    <- the blocking question now
exception adoption         NOT AUTHORIZED
```
