# Nutrition accuracy — one designed capability

**Status: Parts 1-5 landed + matcher identity pass, 2026-08-01.** Branch
`dvoskin/nutrition-accuracy-redesign`. Behind `NUTRITION_ACCURACY_V2` (default
off). Gate `scripts/eval_accuracy.py` (committed-number axes): **4/11 → 9/11**,
honest passes — skirt steak −41% → −1%, almonds −26% → 0%, sirloin −20% → −4%,
**ribeye −39% → −3%**, **grilled thigh +15% → +8%**, **fried thigh −19% → +2%**.
The two rows still red are BY CONSTRUCTION, not density bugs: `fat-steak-butter`
(the butter is elicited by Part 5's ask, invisible to a commit-path eval) and
`fat-salad-plain` (the salad-category estimate). Part 5 (resolve-then-ask) is the
ask-path half, covered by `tests/test_food_turn_resolve_then_ask.py`. Full suite
green with the flag off (v1 unchanged).

The matcher now treats identity as identity: species (no bison for beef), cut
(no ribeye-cap for ribeye), separators (split "steak/roast"), as-eaten over
trimmed ("meat and skin", not "meat only"), and a complete cooked-marker list
(rotisserie/BBQ are cooked, so a cooked row is not yielded a second time). All
v2-gated, magnitudes derived from the existing constants — see
`tests/test_food_matcher_v2.py`.

## Readiness posture (2026-08-01) — canary, NOT global

The 6/11 → 9/11 leap is REAL: matcher defects fixed, not gold numbers
manipulated. But the eval proves only the COMMITTED NUMBER on 10 fixtured foods.
V2 is therefore ready for a **dark merge** (land with the flag off) and an
**internal canary** (flag on for the team only) — **not global enablement.**

Global is gated on validating V2 across the COMPLETE CONVERSATIONAL PATH, none of
which the committed eval touches:
- Part 5's ask → answer → apply loop. **PROMOTION half now validated end-to-end**
  (`tests/test_food_turn_resolve_then_ask_e2e.py`): a mocked-interpreter `log`
  becomes a rendered ask through the real turn, thresholded by mode (spoon asks;
  a 7-cal handful and an explicit-mass log commit; steak fat asks on strict, not
  moderate), inert flag-off, partial commit intact. STILL OPEN: the ANSWER →
  apply half (the follow-up turn re-parses and applies via P2/P4) with a real
  multi-turn exchange.
- Ask-RATE on real traffic — Part 5 promotes log→ask and could over-ask (every
  fat-prone food on strict, every vague unit); unmeasured.
- The branded `plan_turn` / variant-spread path, which the new matcher feeds.
- Non-English: every V2 token set (prep, vague units, species, added fat) is
  English; the RU lane gets none of it — a silent gap (see
  [[feedback_arnie_russian_safety_nets]]).
- Interaction with correction / update / delete turns.

The internal canary is what produces the ask-rate and correction-rate reads that
should decide global enablement — not the committed eval alone.

**Backend readiness (unchanged by V2):** controlled-BETA ready. BROAD market
launch stays blocked by — correction/delete proof (B2 mutation contract),
production latency evidence (B5, needs a week of prod rows), operational recovery
(B9/B10 backup + rollback), and the V2 conversational-path validation above.

**Landed:** Part 1 (identity matcher), Part 2a/b/c (cooked-preference, cooking
yield, trust full-coverage), Part 3 (portion prior). Part 4 (added fat) is
partial — applied only on a seated base so it never double-counts, but the
common case (fat not named in the food) needs Part 5.

**The two rows still red — both by construction, not density bugs:**
- `fat-steak-butter` −14% — the butter is not in the food name, so the commit
  path cannot see it; it is **elicited** by Part 5 (the ask fires in a real chat)
  then added by Part 4. The committed-number eval runs the commit path with no
  answer, so this is red HERE and green in conversation.
- `fat-salad-plain` +20% — "green salad" seats no USDA row and estimates; needs a
  food-category signal (a salad is not a dressing) to seat a leafy-greens density.
  Small absolute (10 cal); the +1608% micro is a separate fibre artifact.

**Fixed 2026-08-01 (matcher identity pass), all v2-gated in `best_candidate` /
`normalize_name`, magnitudes derived from the existing constants, not the gold
numbers — tests in `test_food_matcher_v2.py`:**
- `port-ribeye` −39% → −3%. USDA returned *bison* (wrong animal) and *ribeye cap*
  rows (a leaner sub-cut), and the real beef ribeye read "ribeye steak/roast" so
  the `/` hid the token "steak". Fixes: split separators; reject an unrequested
  species (−2.5, below the trust floor even alone); deprioritise an unrequested
  sub-cut (−1.5, above the cooked/raw swing).
- `prep-thigh` grilled +15% → +8%, fried −19% → +2%. Two bugs: it seated "meat
  ONLY" over "meat and skin" (added the as-eaten preference, +0.4), and it read
  the cooked "rotisserie/BBQ" row as raw and yielded it a second time (completed
  the cooked-marker list, shared by matcher and analyze).

## The problem, stated once

A committed calorie is `PORTION(g) x DENSITY(per-100g)`, and DENSITY is
`base food x preparation x added fat`. Today each factor is estimated badly, and
the errors compound in one direction — down. Measured by `eval_accuracy` on the
real committed path (`_analyze_food`), every un-weighed whole food undercounts
20-47%. This is not a per-food bug; it is four estimators with no ground truth
and a pile of guards patching their symptoms one incident at a time.

Three roots, all verified:

1. **The USDA matcher rejects legitimate whole-food rows.** `best_candidate`
   penalizes description LENGTH (−0.15/token). "skirt steak" vs USDA's *"Beef,
   plate steak, boneless, inside skirt, separable lean and fat… raw"* scores 1.05
   against a 1.2 gate despite a PERFECT token match — so it returns `None`, no
   density, and the LLM's low guess stands. Verified offline.
2. **Raw beats cooked.** When a row IS seated it is USDA's raw entry (ribeye 195
   vs ~291 cooked). A logged food was eaten; raw is the wrong basis.
3. **Portion comes from the guess, preparation from nowhere.** No stated mass →
   grams are backed out of the model's ~19%-low calories. Grilled vs fried, plain
   vs marinated/buttered/dressed resolve to the SAME density. The clarification
   that could ask runs BEFORE the lookup, scored on the guess, so it never sees
   the spread — and nothing re-checks after (`fetch_candidates` docstring: "8x…
   nothing anywhere re-checking").

## The capability (five parts, one flow)

The new resolution path, all behind `NUTRITION_ACCURACY_V2`:

1. **Identity — match on meaning, not brevity.** Replace the length penalty with
   a COMPOSITE penalty: punish tokens that name a DIFFERENT food (`_FORM_PENALTY`
   composite markers — gravy, meal, frozen, sandwich…), never descriptive tokens
   of the SAME food (cut/grade/trim — boneless, separable, lean, choice). A full
   token-overlap match is strong regardless of how verbose USDA's description is.
   *Guard preserved:* "turkey breast" still must not seat "turkey breast and
   gravy, frozen meal" — that is a composite token, and it still loses.

2. **Preparation as a resolution input.** A `Preparation` value
   (raw|grilled|roasted|pan-fried|deep-fried|braised|…) carried from the log,
   defaulting to **cooked** for anything a person eats cooked (meats, eggs,
   grains, vegetables that aren't obviously raw). It selects the cooked USDA row
   over raw and biases the matcher toward the stated method's row.

3. **Added fat / marinade as an explicit term.** Oil, butter, marinade, dressing
   are not in the base food and USDA will never carry them. A small, auditable
   `ADDED_FAT_G` table (1 tbsp oil/butter ≈ 100-120 cal, 2 tbsp dressing ≈ 145)
   adds a term to the committed calories when the log or the clarification names
   one. Not a fudge factor — a named, quantified addition with its own provenance
   line.

4. **Portion prior.** A per-food typical serving (grams) for un-weighed whole
   foods, sourced in priority: the user's own logged history for THIS food →
   USDA/OFF serving size → a curated `SERVING_PRIOR_G` table (steak ~200g cooked,
   nuts 28g, cooked grains 200g…). Replaces "grams from the guess." Extends the
   existing `core/portions.py` engine, which already knows units but has no bare-
   name default.

5. **Resolve, then ask (like Google).** Move the clarification decision AFTER
   `fetch_candidates`, so it scores against the RESOLVED spread. When a food's
   candidates span a wide preparation/portion range (raw vs cooked, lean vs fat,
   or the portion prior is uncertain) AND the swing is calorie-material, ask —
   "grilled or pan-fried? any oil or marinade?" — and apply the answer via #2/#3.
   The ask stays surgical (the existing `spread x prior` policy), just fed the
   real spread instead of the guess.

## Why this is not more heuristics

Each part reaches a capability the system lacks, and DELETES a guard that patched
its absence: the length penalty (a heuristic) goes; the disagreement-demotion and
profile-flip guards exist because the matcher seats wrong rows — a matcher that
seats the RIGHT row needs them less. The measure of success is the guard count
falling while `eval_accuracy` rises.

## The gate

`scripts/eval_accuracy.py` — committed number vs ground truth, decomposed into
portion / density, plus preparation-pair capture. Each capability names the rows
it must turn green (below). `NUTRITION_ACCURACY_V2` flips on only when the eval,
run on the full fixture, shows the un-weighed / preparation / added-fat axes
passing without regressing control or branded.

| part | rows that must go green |
|---|---|
| 1 identity | skirt steak, ribeye seat a USDA density (not estimate) |
| 2 cooked-default | ribeye/steak density within tolerance of cooked truth |
| 3 added fat | steak-in-butter, salad-with-ranch |
| 4 portion prior | almonds, un-weighed meats |
| 5 resolve-then-ask | preparation pairs diverge in committed density |

## Staged rollout (each stage its own commit, eval-gated)

1. Land `eval_accuracy` + record/replay fixture (this branch). Complete the
   fixture with `--record` on the prod USDA key.
2. Part 1 (identity/matcher) — offline-verifiable via `best_candidate`.
3. Part 2 (cooked-default) + Part 4 (portion prior) — table + selection.
4. Part 3 (added fat) — table + provenance term.
5. Part 5 (resolve-then-ask) — the ordering change; the largest, landed last.
6. Flip `NUTRITION_ACCURACY_V2` on after the full eval passes; delete the guards
   the new path makes redundant.

## Part 5 — resolve-then-ask (LANDED 2026-08-01)

**What shipped (behind the flag):** the symmetric half of the ask gate. The gate
had one direction — `_proposed_ask_is_material` DEMOTES an ask the model proposed
but nothing sizes as material. Its blind spot was the ask the model never
proposed: a "spoon" of something dense committed at 350 nobody established (the
production case that prompted this), a steak logged with its oil uncounted.

`core/food_turn._resolved_ambiguities(data, message)` now states the doubt the
overconfident `log` omitted, SIZED from the portion ontology, in the exact
`ambiguity` shape the model emits, so the SAME consequence engine scores it:
- QUANTITY — a vague unit (`core.portions.is_vague_unit`: spoon/scoop/handful…)
  names no definite mass, so the portion is unresolved and the whole item is in
  doubt; the span is the item's own calories. A 7-cal handful of spinach sizes to
  7 and the gate drops it; a 350-cal spoon sizes to 350 and the gate keeps it.
- PREPARATION — a fat-prone food (`core.portions.prep_fat_span`: protein 100,
  salad 145, eggs 90) that has not addressed added fat (`mentions_fat` — named OR
  denied) carries that added-fat doubt. This is the "ask about prep/marinade like
  Google" gap Danny named.

The call site (`run`, at `action=="log" and not prior`) merges the synthesized
doubt, re-runs `_proposed_ask_is_material`, and on a MATERIAL result promotes
`log→ask` — the doubted item waits, the settled ones commit as `ready`, and the
existing renderer voices it ("How much peanut butter — one spoon or more?"). A
promotion is earned by a sized spread, never a new threshold; mode is the only
dial (350-cal spoon asks on moderate, 100-cal prep only on strict). Inert unless
`NUTRITION_ACCURACY_V2` is on and the model chose to log on a first turn.

Tests: `tests/test_food_turn_resolve_then_ask.py` (11, deterministic, no LLM/flag
— they size the doubt through the same call the turn makes). Answer application
needs no new code: the reply turn re-parses with the prep/amount now stated and
Parts 2/4 refine it.

**Residual (the deeper reorder, not shipped):** the ask is still sized from the
interpreter's guess-derived calories, not from a LIVE candidate spread fetched
before the decision. For a whole food the portion ontology stands in for that;
for a genuinely confused branded lookup (the spoon's product identity), scoring
against the resolved OFF/USDA shelf is the remaining depth — it belongs with the
ribeye cut/species and salad-category matcher work.

---

### Original scoping notes (kept for context)

The asker already EXISTS and is mature — do not rebuild it:
`skills.nutrition.materiality` (calorie-swing vs % of day's target),
`skills.nutrition.ambiguity` (`AmbiguityType.PREPARATION`, `CONSUMED_QUANTITY`,
`build_ambiguity`), `core/food_pipeline.derive_variant_ambiguity(items, spreads)`,
and food_turn's prompt already teaches a CUT ask ("sirloin vs ribeye, ~100 cal").
Variant/identity spreads are already fetched from real candidates (Phase 4).

The gap is ONE thing: the ask-materiality decision is scored on the
INTERPRETER'S GUESSED calories, BEFORE the lookup — `fetch_candidates`' own
docstring: "the ask is settled before anything is resolved… measured at 8x,
nothing anywhere re-checking." So for an un-weighed whole food the swing looks
small against the guess and no prep/portion question fires, then enrichment moves
the number out from under the (already-made) decision.

The change, behind `NUTRITION_ACCURACY_V2`:
1. Feed the RESOLVED spread to materiality — the raw candidate set from
   `fetch_candidates` (which now runs before `plan_turn`) already knows the
   cooked-vs-raw, lean-vs-fat, cut span. Score "worth asking?" against THAT
   span, not the guess.
2. Enable the two dimensions that never fire for a bare whole food:
   `CONSUMED_QUANTITY` when there's no stated mass and the portion prior is
   uncertain, and `PREPARATION` / added-fat when the candidate span is wide
   (skirt steak's raw/cooked, a steak's plain/buttered).
3. Apply the answer through the machinery Parts 2-4 already built: a prep answer
   selects the cooked/method row + yield; an added-fat answer adds the term; a
   portion answer overrides the prior.
4. Add a post-resolution re-check: if the committed number moved > Nx from the
   number the ask decision saw, that is the "8x, nothing re-checking" hole —
   flag or re-ask.

Why its own session: it reorders the clarify pipeline inside a mature,
incident-guarded subsystem and is NOT scored by a single committed number, so
`eval_accuracy` can't gate it the way it gated Parts 1-4 — it needs its own
conversation-level tests. Land it alone, not on this branch's tail.

## What needs Danny

Complete the eval fixture: `USDA_API_KEY=<prod> python scripts/eval_accuracy.py
--record` (once, on Render or with the real key). Everything else is code + the
curated tables above, which are auditable and correctable.
