# CF26 — REGISTERED: the cache stores a number the meal never used

*Found 2026-08-25 while probing CF24. Registered, not fixed — the repair
changes caching semantics and needs a decision, not a guess. This is the
**producer** half of the two-defect split; CF24 is the consumer half.*

## The defect

`handlers/tool_executor.py:3077`, the post-pricing cache write:

```python
await upsert_user_food_match(
    db, user.id, name_norm, food_name,
    _hit.get("fdc_id"), _hit.get("per100g", {}),   # <- the LADDER'S candidate
    _grade, origin_tier=_origin,
    serving_text=(_hit.get("serving_text") or ""))
```

⭐⭐⭐ **THE CACHE RECORDS THE CANDIDATE THE LADDER SEATED, NOT THE NUTRITION
THE ENTRY COMMITTED.** `analyze()` decides the meal's numbers on its own and
can land somewhere else — on the interpreter's estimate, on a blend, on a
different rung. When it does, the row written under that food's name describes
a meal that never happened.

The comment above the call already worried about the neighbouring problem —
"a web label could answer the turn while USDA's generic was what got cached
under the product's name". That fixed WHICH RUNG is cached. It did not ask
whether the cached value is **the one the meal used**.

## The evidence — three instances, one live

| turn | interpreter said | entry committed | cache stored |
|---|---|---|---|
| 2026-08-02, entry 2687 / row 936 | — | **150 kcal** | **437.5 kcal/100g** |
| 2026-08-25, entry 3053 / row 1031 | 500 kcal | **590 kcal** | **643 kcal/100g** |

Entry 3053 is a **live, on-demand fixture**: logging `100g crispy onions`
produced three different numbers in one turn. The interpreter said 500, the
board got 590, and the cache took 643.

⛔ **THIS IS WHERE POISONED ROWS COME FROM.** Every row the CF24 probes went
looking for was made this way — 936 (`grilled shrimp`, 437.5), 886
(`cucumber`, 179), 292 (`banana`, 312), 1029 (`whole milk`, 582), 1031
(`crispy fried onions`, 643). The consumer guard is holding the line; the
producer keeps loading it.

## Why it is not merely cosmetic

A row written this way is **silently wrong and looks authoritative**: it
carries a real `fdc_id`, a real `origin_tier`, and a plausible serving panel.
Nothing about it says "the meal that made me disagreed with me". It is exactly
the shape CF23's `test_an_internally_consistent_but_unproven_row_is_still_not_evidence`
describes — self-consistent, well-formed, and false.

Row 936 sat untouched for three weeks and then appeared in an incident. Row
1029 carries `4 pieces (16.7 g)` on a litre of milk. These are not edge cases;
they are the ordinary output of this path.

## The invariant to decide on

> **A cache row may only record nutrition the meal actually used, or record
> nothing.**

Two candidate semantics, and the choice is a product decision rather than a
mechanical one:

1. **Cache the committed values.** The row then describes a meal that really
   happened. Loses the ladder's richer per-100g when the entry was scaled from
   a portion, so a later log of a different amount re-derives from a value that
   was itself derived.
2. **Cache nothing when they disagree.** Strictly safer, and the cache stays a
   record of resolved lookups rather than of meals. Costs the hit rate: a food
   whose entry and candidate routinely differ never caches at all.

⛔ **NOT A THIRD OPTION: a tolerance band.** "Cache it if they agree within
N%" is a plausibility threshold wearing an equality check's clothes, and this
project has paid for that shape before. Agreement is exact or it is absent.

## The test to write once the semantics are chosen

```
test_the_cache_records_only_what_the_meal_used
    drive a turn where analyze() lands on the interpreter estimate while the
    ladder seats a different candidate — the 3053 shape — and assert the
    written row either carries the committed per-100g or does not exist.

test_a_row_is_still_written_when_they_agree      (the negative invariant)
    fail-closed must not mean fail-always, or the cache is deleted rather than
    corrected and every repeat log pays a fresh lookup.
```

## Scope

CF26 is **not** CF24. CF24 is one unexplained consumption of row 936 and stays
open on its own terms. Fixing CF26 does not close CF24 — but it stops the
supply of rows for any consumer bug to reach, which makes CF24 materially less
dangerous while it remains open.
