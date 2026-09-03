# REGISTERED — the ranker is lexical; non-Latin evidence is qualified but unpriceable

**Measured 2026-09-03, locally, no provider involved:**

```
candidate = Blueberries, raw (usda:171711)
query 'черника'           -> best_candidate returns NONE
query 'blueberries'       -> PRICES, conf=exact
```

`best_candidate` scores **token overlap between the query and an English USDA
description**. The v2 qualification gate now reads an intent in any language
and admits the right rows; the ranker that must then pick among them cannot
match a Cyrillic query to any of them, and returns nothing. The rung yields
`None` and a lower rung answers — silently.

## WHAT THIS MEANS FOR THE MEASUREMENTS ALREADY REPORTED

The 86-item census counted an identity as **recovered** when `build_one`
returned qualified candidates. **16 of the 20 recoveries are non-Latin, and
none of them PRICE under their own query.** Re-run of the runtime probe: 18 of
19 blanks were `status=ok` — evidence found, judged, kept, then refused by the
ranker. So:

- *Expansion works* — the recall claim stands; the gate admitted correct rows.
- *The ownership lift from the non-Latin class is currently zero in replay*,
  because the frozen-222 instrument prices from the STORED `parsed_food_name`,
  which for those entries is Cyrillic.
- *Live turns may differ*: the interpreter emitted "Buckwheat, cooked" for
  `гречка` in production. Where it normalises to English, the ranker prices.
  Where the stored name is the raw surface form, it cannot.

This is the reachability docstring's own warning, one consumer further along:
**"A CANONICALISATION IS ONLY AS GOOD AS ITS LEAST CAREFUL CONSUMER. Fixing the
query without fixing the ranker built a system that can FIND evidence it cannot
USE."**

## SCOPE — NOT IR-PUBLISH

Publication is gated on the artifact's seeds, which are English. This gap
affects the runtime non-Latin class and the replay instrument, not the
publication gate. It is registered so that when the sealed holdout opens, a
flat non-Latin result is read as *ranker cannot price* and not as *expansion
did not work*. The fix is a ranker question (query normalisation at the ranker
seam, or ranking on the qualified set without a lexical gate) — and it is
explicitly out of scope until this tranche ships.

## 2026-09-03 addendum — the gap is closable at the ranker, and one way of closing it is wrong

**Measured (dev population, 20 recovered identities, USDA quiet, post rebuild #2):** 19/20 price once the
ranker is given an English identity — 1 via the original English name, 18 via an English form — against
exactly the rows the v2 gate qualified. The blank (`Smoke test chicken`) is test junk. So the ranker gap is
purely lexical: same candidates, English query, priced.

**The wrong way to close it:** ranking with the *retrieval* query from `retrieval_intent.expand()`. Those
queries exist to widen recall and deliberately carry form words — `Рыба` expands to `Fish, raw`,
`Fish, cooked`, … — and the first that seats wins. Ranked that way, three seafood items seated a **raw**
row although a cooked sibling was qualified (`Рыба`, `Кальмар`, `Гребешок`): recall-expansion became a
form authority, which is exactly what the reachability contract forbids ("recall only, never authority").
Any consumer that ranks must rank with a form-neutral identity.

**What the real runtime ranks with:** `skills.nutrition.entity_resolver.interpret()` emits a canonical
English id per surface — `squid`, `scallop`, `bell pepper`, `tomato`, `salami`, … (18/20 resolved).
`Рыба` resolves to **nothing** (state unresolved, "unspecified type of fish"), so generic fish never reaches
the ranker at all. The runtime exposure of the consumed-form defect is therefore decided by
`best_candidate(<canonical id>, qualified rows)` with no form word — measured in
`docs/REGISTERED_CONSUMED_FORM_AUTHORITY.md` (same date).

**Instrument note:** `interpret()` caps a batch at `_MAX_BATCH = 12` and returns fewer results for a longer
list; the 20-name census call silently came back with 12. Callers must batch. (Production calls it with a
turn's handful of surfaces.)
