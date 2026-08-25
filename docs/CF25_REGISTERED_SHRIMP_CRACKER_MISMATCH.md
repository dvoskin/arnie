# CF25 — REGISTERED, NOT OPEN: a snack product priced a plain cooked food

*Found 2026-08-25 while tracing production turns on the CF24 build
`a7549d72fbfb`. Registered at Danny's direction; it does NOT open a tranche and
does NOT hold CF24 open.*

## The row

Entry **3050**, user 26, logged `2026-08-25 18:28:06` via Telegram.

| | committed | truth |
|---|---|---|
| `Shrimp, grilled` @ 120 g | **525.0 kcal** | ~119 kcal |
| implied per-100g | **437.5** | 99 (fdc `175180`) |
| protein / carbs / fat | 10.6 / **76.6** / 19.4 | 28.8 / 0.2 / 0.3 |

⭐⭐⭐ **THE MACROS RECONSTRUCT PERFECTLY AND ARE STILL FALSE.**
`4(10.6) + 4(76.6) + 9(19.4) = 523 ≈ 525`. This is the case
`test_an_internally_consistent_but_unproven_row_is_still_not_evidence` names:
when a whole row comes from ONE wrong source, every internal check agrees with
it. Consistency is not provenance.

⛔ **AND 76.6 g OF CARBS IS NOT A SCALING ERROR.** Shrimp has ~0 carbs. This is
not the right food scaled wrongly — it is a **different food entirely**.

## The source shape

USDA `173160` — **`Snacks, shrimp cracker`** — is **426 kcal/100g, P7.14 C59.1
F17.9**. Entry 3050 per-100g was **437.5, P8.83 C63.8 F16.2**. Same shape, and
the memory row the same turn wrote (`936`, `Grilled shrimp`, `cal_100=437.5`)
carries tier **`branded_exact`** — so the winner was a BRANDED snack record,
not the USDA generic.

⭐ **A SNACK PRODUCT WON A PLAIN COOKED-FOOD QUERY.** This is the CF5b class
(`70004199`, OFF junk whose per-bar numbers were read as per-100g) reappearing
at the *ranking* layer rather than the units layer: nothing checked that a food
described as `grilled` should not resolve to a `cracker`.

`nutrition_evidence_id` was **NULL** on the committed row — the number arrived
with no evidence id at all, through `pricing.enrichment_hit` /
`speculative.pricing.qualification`, not through memory and not through the web
path CF23 disabled.

## What CF24 already contains, and what it does not

**Contained.** Memory row 936 was created by the same turn carrying 437.5. The
predicate was EXECUTED against production, not assumed:

```
row 936  'Grilled shrimp'  cal100=437.5  tier='branded_exact'  TRUSTED=False
```

Neither canonical nor legacy will price nutrition from it. **The poison does
not propagate.** That is CF23/CF24 doing exactly their job, on a real row,
within an hour of shipping.

**Not contained.** CF24 guards memory *reads*. It has nothing to say about the
lookup that invented 437.5 in the first place — that is upstream, in the
legacy pricing/enrichment path.

## Disposition

- Entry 3050 **corrected** in production: 118.8 kcal, P28.8 C0.2 F0.3, with
  `nutrition_evidence_id = '175180'` (`Crustaceans, shrimp, cooked`).
- `daily_logs` 568 recomputed **from the entries**, never by applying a delta;
  verified equal to the entry sum afterwards.
- Ledger event `2256`, `updated` / `cf24_canary:shrimp_cracker_mismatch`,
  payload records before, after, evidence and the suspected source shape.
- ⚠ **Memory row 936 was left in place at `cal_100=437.5`.** It is untrusted
  and therefore inert for pricing, and the standing CF23 instruction is not to
  modify rows. It is listed here so the decision is visible rather than
  implied. If the trust predicate is ever loosened, this row is live poison.

## Not authorized by this registration

No tranche. No memory cleanup, no heuristic trust restoration, no historical
backfill — per the CF24 stop condition. What would justify opening it is a
second production incident of this shape, or evidence that snack/branded
records win plain-food queries at material rate.
