# WINNER-SAFETY REVIEW — query expansion, 86-item dev census

Expansion widens the candidate pool, so `best_candidate` re-ranks and can
displace a previously-correct winner. Four identities changed winner. None
blocked. Recorded individually so a reviewed semantic correction cannot
disappear inside a "gate passed" summary.

*(USDA `Energy` here is kJ/100 g; deltas are proportional either way.)*

| identity | old → new | delta | verdict |
|---|---|---|---|
| `Pastry` | `Puff pastry, frozen, ready-to-bake` → `…, baked` | +1% | **BETTER_MATCH** — eaten baked, not as frozen dough |
| `Mashed potatoes` | `Fast foods, potato, mashed` → `Potatoes, mashed, ready-to-eat` | **+20%** | **BETTER_MATCH / MATERIAL_NUTRITION_DELTA / REVIEWED_AND_ACCEPTED** |
| `Royo Plain Bagel` | `Bagels, plain, without calcium propionate` → `…, with` | −4% | **EQUIVALENT** — preservative variant |
| `French fries` | `WENDY'S french fries` → `APPLEBEE'S french fries` | −4% | **AMBIGUOUS, immaterial** |

## ⭐ `Mashed potatoes` — the case that must stay visible

A **+20% nutrition change on an identity that was already working.** It is
accepted because the semantic reason is explicit and reviewable: the old record
was scoped to FAST-FOOD preparation, the new one is the generic, and for an
unqualified `Mashed potatoes` the generic is the more defensible identity.

⛔ **THE DISTINCTION THIS PRESERVES** *(Danny, 2026-09-01)*:

    material delta because the system got WORSE            -> block
    material delta because the system corrected a
      previously OVER-SPECIFIC record                      -> allow, but FLAG

The gate is about semantic degradation, not about any material movement
whatsoever. Collapsing the two would either block every genuine correction or
wave through every silent regression.

## ⚠ NOT introduced here, and not this tranche's to fix

`Royo Plain Bagel` resolves to a GENERIC USDA bagel under both the old and new
winner — expansion did not degrade a branded match, because there was never a
branded match. Same for `French fries`, where both records are
restaurant-branded stand-ins for a generic identity. These are the
branded/SKU class (cf. `Fage Total 0%` → `Yogurt, Greek, plain, nonfat`) and
belong to that tranche.

## CONTEXT — what the winner review was gating

```
                                v1 base    v2 guidance    + EXPANSION
B  reachable                    23 (27%)    24 (28%)       49 (57%)
C2 retrieved, none qualified    61 (71%)    58 (67%)       34 (40%)
D  true source gap               1 ( 1%)     1 ( 1%)        0

C2 -> B recovered  20    regressions 0    raw rows median 10 -> 21
```

⭐ **16 of the 20 recovered are non-Latin** — a bucket that measured 0/6 in
every prior arm. Guidance alone moved 1; expansion moved 25. The dominant
failure class was retrieval, and the qualification gate was left unchanged
throughout: it admitted every one of these on its own judgement.
