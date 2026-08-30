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
