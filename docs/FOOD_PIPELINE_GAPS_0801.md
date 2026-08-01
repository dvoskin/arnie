# Food pipeline gaps + web-enrichment plan (2026-08-01)

Audited Danny's OWN prod logs today (user 26, 14 entries). **6/14 within 10%** of
an independent reference. Five distinct, user-facing failures in one afternoon —
the pipeline is NOT launch-ready. Evidence is prod data, not screenshots (the
cards mislead; e.g. whiskey card said 30 cal, DB logged 200).

## Confirmed gaps (with prod evidence)

1. **Multi-item DROP (leave-no-food-behind).** User typed *"you dropped all my
   other items."* 6-item log → two clarifications (turkey portion, bun size); on
   the turn answering Q1, only the bun committed, the other 5 vanished until Q2
   was answered. Worse than single-item: a multi-QUESTION clarification strands
   everything not being asked. `I1` fix (orphan-commit in the ask branch) covers
   the FIRST-turn ask (`action==ask and not prior`); **must extend to the
   answer-turn-asks-again path (`action==ask and prior`, food_turn ~3909)** — the
   trace shows that's where the 5 items dropped.

2. **Calorie accuracy — 6/14 within 10%.** Misses: burger bun −30%, parmesan
   −18%, turkey deli +89%, ground turkey +92%, Drizzlicious −17%, Magic Spoon
   −13%, chicken +15%. Roots: (a) wrong USDA cousins — "corn"→*Corn grain* 365
   (dry seed), "whiskey"→*whiskey sour* 149 (a cocktail); (b) servings that don't
   convert to grams ("1 ear", "2 shots") so a seated density is DISCARDED and the
   interpreter's guess wins.

3. **Garbage micronutrients.** Whiskey logged sodium **3347mg**, sugar **39g**;
   Drizzlicious sugar **22g > 6g carbs** (impossible). Micro-enrichment invents
   values; no `sugar≤carbs` / Atwater-reconcile invariant.

4. **Reply ≠ logged.** Arnie's reply said whiskey was "30 cal, basically
   nothing" while the DB logged 200. Reply-composer voicing a number not taken
   from the committed value.

5. **Garbled clarification voice.** *"How big were the small buns of Small burger
   bun?"* — the question template mashes the food name in.

## THE WEB-ENRICHMENT GAP (the accuracy lever Danny asked for)

The general web fallback `_web_lookup_meal` exists (uses `core.search` +
a Haiku extraction pass) but is blocked THREE ways:

- **⚠ It's almost certainly OFF in prod.** `core.search` needs `SEARCH_ENABLED=true`
  AND `TAVILY_API_KEY`. Local `.env` has NEITHER. If Render lacks them the web
  rung CANNOT fire for any food, regardless of code. **Danny must confirm/set both
  on Render — this is the #1 unblock.**
- **Gate A — `source=="estimate"` only.** A WRONG USDA cousin that seats (corn
  grain, whiskey sour → source="usda") blocks the web rung even though the match
  is wrong. It should fire on a WEAK resolution, not only on no-resolution.
- **Gate B — `_worth_web_meal` (substantial composites only).** Simple foods
  (corn, a bun, parmesan, 2 shots whiskey) skip it.

## Web enrichment — TESTED with a real Tavily key (2026-08-02)

`_web_lookup_meal` run live against the misses. It is helpful but NOT a silver
bullet, and a naive loosening would regress:
- FIXES: burger bun 3in → **120** (truth ~120); turkey deli 3 slices → **88**
  (~90). Real wins over the DB (84 / 142).
- WRONG SERVING: parmesan **2 oz → 85** (~1 serving, truth ~220); ground turkey
  **200 g → 160** (per-serving, truth ~350). Web ignores the stated quantity too.
- NONE: whiskey 2 shots, corn 1 ear — no confident web hit.
- The `_worth_web_meal` gate is deliberate: web returns garbage for drinks /
  single ingredients (past incident). So: expand it for foods web handles, keep
  it off where web is unreliable, and NEVER override a trusted (non-weak) DB seat
  (parmesan seated "likely" at 180 — web must not replace it with 85).

**Common root under DB AND web: the stated serving isn't respected.** That is the
highest-leverage fix; web sits on top of it.

## Plan — serving-first, then guarded web

1. **Serving→grams coverage (THE ROOT, do first):** ear/shot/clove/slice/bun and
   respect stated mass (oz/g), so a seated density is USED not discarded. Fixes
   the "1 ear"/"2 shots"/"2 oz"/"200 g" collapse — the common cause under BOTH
   the DB and the web results. Highest leverage, deterministic, testable offline.
2. **Matcher identity:** reject wrong cousins (corn grain for corn; whiskey sour
   for whiskey) — extends the V2 species/cut work.
3. **Invariants (deterministic safety net, universal/non-flag-gated):**
   I1 leave-no-food-behind (extend to the answer-turn), macro-consistency
   (sugar≤carbs, Atwater reconcile), zero-floor.
4. **Web as a GUARDED rung (employ, don't just loosen):** enable it
   (Danny/Render: `SEARCH_ENABLED=true` + `TAVILY_API_KEY`), then fire only on a
   WEAK resolution (estimate/low-confidence — NOT over a trusted seat like the
   parmesan 180), expand `_worth_web_meal` to the foods web handles (bun, deli),
   and accept the web number ONLY if it's plausible FOR THE STATED SERVING (so
   parmesan 2oz can't be overwritten with an 85-cal single serving). Keep off for
   drinks/ambiguous where web returns garbage.
5. **Reply-voicing:** reply calorie numbers must come from committed values.
6. **Voice:** fix the clarification question template.

## Status
- `I1` (first-turn leave-no-food-behind) landed on `dvoskin/food-invariants`
  @2d26ba6. Everything else is open.
- **Highest leverage: serving→grams (1) — it fixes the common root and makes web
  (4) usable. Web tested helpful but partial; employ it guarded, on top of (1).**
- Old framing "just loosen the web gate" is WRONG — tested to regress. That's the
  "like Google" accuracy fix Danny asked for; it is blocked on the env first.
