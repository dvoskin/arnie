# Evidence corpus — human-reviewed ground truth

Captured 2026-08-07 from the live USDA API. **The records are raw and
uncleaned.** `usda_2026_08_07.json` is exactly what the provider returned, and
it must stay that way: the previous B-1.5 producer shipped with fourteen green
gates against a fixture written to *look* like USDA, and only a live probe
caught it. Rewriting these into tidier examples would rebuild that failure.

The classifications below are the expected `relationship` for a **bare,
under-specified intent** — `base_identity ≈ <food>`, everything else
unspecified. They are the evaluation target for
`food_evidence_semantics_v1`, and they are human judgements, not code output.

Relationship vocabulary is closed and driven by these measured classes:

```text
SAME_IDENTITY                  the record is the food, unqualified
COMPATIBLE_SPECIALIZATION      a narrower form of it (cut, preparation)
COMPOSITE_CONTAINING_IDENTITY  a dish or product that contains it
DERIVED_OR_EXTRACTED_FORM      rendered, pressed, floured, concentrated
SUBSTITUTE_OR_ANALOGUE         imitates it, is not it
DIFFERENT_IDENTITY             a different food that names it
INSUFFICIENT_EVIDENCE          cannot tell
```

## chicken — the headline failure

**Zero comparable rows in the top eight.** This is why B-1.5 could not open
preparation, and why "the string contains chicken" is not identity.

| kcal | record | relationship |
|---:|---|---|
| 158 | Chicken spread | COMPOSITE_CONTAINING_IDENTITY |
| 224 | Chicken, meatless | SUBSTITUTE_OR_ANALOGUE |
| 900 | Fat, chicken | DERIVED_OR_EXTRACTED_FORM |
| 223 | Frankfurter, chicken | DIFFERENT_IDENTITY |
| 271 | Fast foods, chicken tenders | COMPOSITE_CONTAINING_IDENTITY |
| 336 | Bologna, chicken, pork | DIFFERENT_IDENTITY |
| 176 | Bratwurst, chicken, cooked | DIFFERENT_IDENTITY |
| 185 | Chicken, canned, no broth | COMPATIBLE_SPECIALIZATION |

`Fat, chicken` at 900 kcal is the sharpest false-compatible: highest lexical
overlap, 20× the density of the food meant.

## papaya — the shipped defect

Production entry **2896 committed 200 cal for 80 g of papaya.**
`Papaya, canned, heavy syrup` is 206 kcal/100g and sits three rows above
`Papayas, raw` at 43. This is not hypothetical; it is the miss.

| kcal | record | relationship |
|---:|---|---|
| 43 | Papayas, raw | SAME_IDENTITY — **positive control** |
| 57 | Papaya nectar, canned | DERIVED_OR_EXTRACTED_FORM |
| 206 | Papaya, canned, heavy syrup, drained | DERIVED_OR_EXTRACTED_FORM |
| 63 | Babyfood, fruit, guava and papaya with tapioca | COMPOSITE_CONTAINING_IDENTITY |
| 70 | Babyfood, fruit, papaya and applesauce with tapioca | COMPOSITE_CONTAINING_IDENTITY |
| 86 | Fruit salad, tropical | COMPOSITE_CONTAINING_IDENTITY |

## salmon — positive controls exist here

| kcal | record | relationship |
|---:|---|---|
| 902 | Fish oil, salmon | DERIVED_OR_EXTRACTED_FORM |
| 179 | Fish, salmon, chinook, raw | COMPATIBLE_SPECIALIZATION |
| 117 | Fish, salmon, chinook, smoked | COMPATIBLE_SPECIALIZATION |
| 120 | Fish, salmon, chum, raw | COMPATIBLE_SPECIALIZATION |
| 127 | Fish, salmon, pink, raw | COMPATIBLE_SPECIALIZATION |
| 131 | Fish, salmon, sockeye, raw | COMPATIBLE_SPECIALIZATION |
| 208 | Fish, salmon, Atlantic, farmed, raw | COMPATIBLE_SPECIALIZATION |
| 142 | Fish, salmon, Atlantic, wild, raw | COMPATIBLE_SPECIALIZATION |

**A policy that rejected everything would pass the chicken gates and fail here.**
Positive controls are mandatory for exactly this reason.

## potato

| kcal | record | relationship |
|---:|---|---|
| 266 | Bread, potato | DIFFERENT_IDENTITY |
| 357 | Potato flour | DERIVED_OR_EXTRACTED_FORM |
| 268 | Potato pancakes | COMPOSITE_CONTAINING_IDENTITY |
| 52 | Babyfood, potatoes, toddler | COMPATIBLE_SPECIALIZATION |
| 157 | Potato salad with egg | COMPOSITE_CONTAINING_IDENTITY |
| 58 | Potatoes, raw, skin | COMPATIBLE_SPECIALIZATION |
| 522 | Snacks, potato sticks | DERIVED_OR_EXTRACTED_FORM |

## chicken breast — narrower intent, still mostly incompatible

| kcal | record | relationship |
|---:|---|---|
| 263 | Chicken breast tenders, breaded, uncooked | COMPOSITE_CONTAINING_IDENTITY |
| 134 | Chicken breast, roll, oven-roasted | DIFFERENT_IDENTITY |
| 252 | Chicken breast tenders, breaded, cooked, microwaved | COMPOSITE_CONTAINING_IDENTITY |
| 109 | Oscar Mayer, Chicken Breast (honey glazed) | DIFFERENT_IDENTITY |
| 98 | Chicken breast, deli, rotisserie seasoned, sliced | DIFFERENT_IDENTITY |

## protein bar / protein shake — USDA is the wrong authority

Branded items where Open Food Facts or manufacturer evidence should lead.
Recorded to show authority is per claim, not per source.

`protein bar` returns `Soy protein isolate` (335) and `Bread, protein` (245)
alongside actual bars. `protein shake` returns `BURGER KING, Vanilla Shake`
(168) and three fast-food milkshakes.

## What the corpus does NOT contain

No food yields two or more **registered** preparations (grilled / roasted /
fried) with a material spread. USDA's own preparation words here are
raw · smoked · baked · "cooked, dry heat" — only partially overlapping the
registered vocabulary. This is why preparation materiality needs web evidence,
and why §26 requires the model to normalize provider wording into the
registered vocabulary or `UNKNOWN` rather than deriving vocabulary from tokens.

---

# Open Food Facts — captured 2026-08-07

`off_2026_08_07.json`. Best match plus siblings, via the same `off.search()` /
`off.search_variants()` the resolver uses.

## ⭐ The finding: OFF's own confidence grade carries no information

**Every result below is graded `_match: "exact"` by OFF.** The grade is
identical on a pizza returned for "chicken" and on four correct branded
matches. A provider's self-reported confidence is not evidence of
comparability, and any policy keyed on it inherits the pizza.

| query | best match | kcal | grade | verdict |
|---|---|---:|---|---|
| chicken | **SPICY CHICKEN & 'NDUJA PIZZA** (Deluxe) | 511 | exact | COMPOSITE_CONTAINING_IDENTITY |
| papaya | Mango Papaya Passion Fruit (Onken yogurt) | 93 | exact | COMPOSITE_CONTAINING_IDENTITY |
| salmon | Salmon ahumado (smoked) | 144 | exact | COMPATIBLE_SPECIALIZATION |
| potato | — none — | | | correctly returns nothing |
| Barebells salty peanut protein bar | Protein Bar Salty Peanut | 369 | exact | SAME_IDENTITY ✓ |
| Fairlife Core Power | Core Power High Protein Milk Shake | 85 | exact | SAME_IDENTITY ✓ |
| Doritos Protein Chips | Doritos Protein Chips | 521.7 | exact | SAME_IDENTITY ✓ |
| Royo everything bagel | Royo Everything Bagel | 102.6 | exact | SAME_IDENTITY ✓ |

The chicken row also carries `serving_text: "1 tsp (100 g)"` — a teaspoon of
pizza. Serving metadata is as unreliable as identity here.

Variants for "chicken" are `SPICY CHICKEN & 'NDUJA PIZZA`, `Indomie instant
noodles baladi`, `Ramen-Buldak HOT Chicken Flavour` — the sibling set inherits
the base identity error wholesale.

**The branded four are the positive controls**, and they are drawn from Danny's
real production log (entries 2878/2884/2886). Product-variant reuse (§29) has
working evidence precisely here.

# Tavily web search — captured 2026-08-07

`tavily_2026_08_07.json`. **`answer` is LLM-SYNTHESIZED**, not a structured
record: it has no `source_record_id`, cannot be re-derived, and is a summary of
whatever pages ranked.

| query | synthesized answer | sources include |
|---|---|---|
| chicken calories per 100g | 165 cal, 31g protein | NutriSc, **Instagram** |
| grilled vs fried chicken | **165 vs 250** | comparison blog, **Instagram** |
| papaya raw per 100g | **42–43** | Aprifel, a **PDF** |
| Barebells salty peanut | 20g protein / 55g | **Amazon**, **GNC**, brand site |
| Doritos Protein Chips | 150 cal / 28g | brand press, news |

Two things are true at once, and they are the whole reason authority is per
claim:

* Tavily answers what USDA and OFF could not — the grilled/fried spread is the
  materiality evidence B-1.5 needs, and **papaya raw at 42–43 is exactly the
  number production got wrong** (entry 2896 committed 200).
* Its sources are Instagram, Amazon and GNC, and the answer reads equally
  confident regardless. **Semantic confidence and source quality are
  orthogonal dimensions** and must be stored separately.

## Cross-provider: authority is per claim, MEASURED

| claim | USDA | OFF | Web |
|---|---|---|---|
| generic food identity | weak (adjacent products) | **catastrophic** (pizza for chicken) | usable |
| generic nutrient composition | **strong** when identity holds | weak | usable, unciteable |
| branded product identity | weak | **strong** (4/4) | usable |
| preparation materiality | absent | absent | **only source** |
| package / serving | unreliable | mixed | manufacturer pages |

No single ranking is correct. `if source == USDA: trust = 1.0` is refuted by
this table on the branded row, and the reverse is refuted on the generic row.
