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
