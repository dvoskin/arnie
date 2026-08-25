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

---

# ⛔ CF24 IS OPEN — AND THE AUG 2 / AUG 25 DEFECTS ARE DISTINCT

*Appended 2026-08-25 at Danny's direction. CF25 stays a separate, valid
defect; it does NOT explain entry 3050.*

## Two defects, not one

| | when | what |
|---|---|---|
| **producer** | 2026-08-02 | a lookup wrote memory row 936 at 437.5 kcal/100g, tier `branded_exact`, `serving_text='80 g'` — **beside an entry (2687, `Grilled shrimp`, 150 kcal) that did not itself consume it** |
| **consumer** | 2026-08-25 | entry 3050 committed 525 kcal — the exact **1.2x image** of row 936 — on the CF24 build, from a row the predicate refuses |

**CF24 is about the second one.** The producer defect created bad memory; the
consumer bypass used it three weeks later.

## What is ruled out, by production data rather than reading

- **`pricing.enrichment_hit`** — the inflight cache holds `(usda, off)` only
  and "Touches NO DB"; it cannot carry memory macros.
- **Tier 0 `_logged_history_match`** — a real bypass class (it returns an
  override *before* the guarded rung), but at 18:28 there was **no
  token-equal prior entry**: the only candidate, entry 2687, carries
  `estimated_flag=True` and is filtered by design.
- **Provider retrieval** — live USDA returns `GRILLING SHRIMP` at 106 kcal as
  `best_candidate`; `_looks_branded("Shrimp, grilled")` is False and the item
  carried no `is_packaged`, so the OFF lane was never consulted.
- **A write at 18:28** — CF24-D makes `upsert_user_food_match` never write
  nutrition to an existing row, so 437.5 has been on row 936 since Aug 2.
- **The guarded readers** — cloning row 936 into a local database and
  replaying entry 3050's exact production item commits **110 kcal**: the
  predicate refuses, memory is skipped, the interpreter's estimate stands.

## The instrumentation, and why it is not a patch

`memory_nutrition_evidence` is now the ONE conversion from a stored row to
pricing evidence. Both known consumers route through it, and it emits, before
any candidate can return or override:

```
event=memory_nutrition_use row_id= key= trusted= consumer=
    candidate_kind= hydration= turn= operation= stage=
```

`tests/test_every_memory_to_evidence_conversion_is_named.py` freezes the
enumeration — five sites in shipped code read stored per-100g values — and
fails when a new one appears. A companion test pins that the trust predicate
has exactly ONE caller, so no conversion can pass the guard silently.

⚠ **PRIME SUSPECT, NOT A VERDICT: `core/food_intelligence.py::analyze`.** It
reads `cal_100` off a candidate dict it did not fetch —
`src.get("per100g") or {"calories": src.get("cal_100"), ...}` — which is the
prehydrated shape: the trust check runs at the reader and a copy made
elsewhere never meets it. **Deliberately not patched.** The replay decides.

## The replay, and how to read it

Log `grilled shrimp` on user 26 on the instrumented build:

- event fires, `trusted=False`, and 525 commits → the check runs and is
  **ignored after conversion**
- event fires with `trusted=True` → the defect is in **trust derivation or
  stale hydration**
- **no event** and 525 commits → an **uninstrumented conversion path** remains
- ~110-120 commits → the incident depends on speculative/prewarm state or a
  one-turn race, and the canary must be repeated under that state

No closure claim for CF24 until one of these is proven.
