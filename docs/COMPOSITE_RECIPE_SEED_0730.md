# Composite recipe library — seed list from production traffic

**Date:** 2026-07-30 · **Source:** 30 days of `food_entries` read live (see
`ARCHITECTURE_AUDIT_2026-07-30.md` §7b for the full analysis and the plan this serves).

The engine (`40d4d9b` / `e4d651d`) fails closed: a dish with no recipe seats nothing. Its current
library is taco/burger-shaped; the traffic is not. **Merging before the library matches the traffic
ships an engine that is correct and silent.** This is the ranked build list, from what users
actually logged, weighted by calorie contribution.

## Tier 1 — logged this month, no recipe exists in either branch

| Dish family | Seen as | Notes for the recipe |
|---|---|---|
| **Pizza** | Dollar slices ×2, NY-style thin crust, Detroit-style pepperoni | The most-logged composite. Per-slice basis; crust style is a material dimension (Detroit ≠ NY thin). Strong candidate for *direct prepared-dish rows first* — USDA has curated pizza rows; decomposition may lose to them (§7b step 2). |
| **Composed salads** | Caesar, arugula/avocado/onion w/ balsamic, CAVA bowl | Dressing is the dominant variance (the plan's own worked example). `40d4d9b` has partial salad coverage; needs dressing-as-component. |
| **Stews** | Beef stew w/ mashed potatoes, ground-beef & eggplant stew, RU-named рагу | Cross-language names reach this family (cause E adjacency). Broth/oil base is the spread. |
| **Bowls** | Chicken burrito bowl, CAVA Spicy Lamb Bowl | `e4d651d` has chipotle/rice bowl shapes — closest existing coverage; extend, don't rewrite. |
| **Sushi** | Vegetable roll | Per-piece basis; rice dominates. |
| **Shawarma / gyro** | Shawarma platter (asked about, then escaped) | Platter = meat + rice + sides; the ask ladder already asks the right question here. |
| **Soups** | Chicken soup, broth vegetable soup w/ chicken (both held for clarification 07-29/30) | Both live asks in the last 48h stored these with zero candidates — the join's first customers. |

## Tier 2 — already covered by a branch library (adopt, verify against ground truth)

Tacos (carnitas/al pastor/asada/birria/fish), quesadillas, burgers/cheeseburgers, poke, falafel,
omelets/eggs, grilled-cheese/toasted sandwiches.

## What "done" means (from §7b — do not shortcut)

1. Recipe exists → engine prices a **range**, fails closed otherwise.
2. Per dish: decomposition **vs a direct prepared-dish row**, decided by comparison, not assumption.
3. Scored against the ground-truth corpus (30–50 dishes, restaurant published nutrition + curated
   rows) on **coverage** (range contains truth) and **per-macro error, protein separately**.
4. The 18–21 % cross-mode drift (`b835700`) measured before/after.
5. Only then does the `component_estimate` rung get claimed — its false *assignment* was already
   removed (the "Estimated from its components" line no longer renders for work nothing performed).
