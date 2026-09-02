# REGISTERED — CONSUMED-FORM AUTHORITY

**When preparation is unspecified, what evidence establishes whether the eaten
representation is raw, cooked, dry, prepared or drained?**

Today nothing does. `best_candidate` has a cooked-preference (`_cooked_pref`,
±0.6) gated on `cooking_yield_known(query) > 1.0`, and for most foods that
returns `None` — `COOKED_AXIS_UNDECIDED`, which the code is careful to say "is
not a softer no. It says the raw-vs-cooked axis was never established for this
food."

## HOW IT SURFACED

Query expansion doubled the candidate pool (median raw rows 10 → 21). Base
forms that were always semantically admissible became reachable, and the ranker
had no reason to prefer the form a person eats. Measured on artifact seeds:

```
oats|       cooked (84% water) -> DRY (11% water)   +434%
mushrooms|  shiitake cooked    -> white RAW          -61%
potato|     boiled flesh       -> flesh+skin RAW     -42%
tofu|       145 kcal           -> 62 kcal            -57%
```

⭐ **THE DEFECT IS RANKING, NOT RECALL.** The rows are correct and reachable;
nothing about widening retrieval should be undone.

## PREVALENCE — measured, not assumed

Across the 20 identities query expansion recovered: **3 genuine form errors.**

```
Рыба      -> Fish, bluefish, raw       generic fish, eaten cooked
Кальмар   -> Mollusks, squid, raw      eaten cooked
Гребешок  -> Mollusks, scallop, raw    usually cooked
```

⛔ **A NAIVE `\braw\b` SCAN FLAGGED 9 OF 20 AND WAS WRONG ABOUT SIX.** In USDA,
`raw` denotes the FRESH UNPROCESSED form — which is precisely how blueberries,
mangoes, radishes, sweet peppers and tomatoes are eaten. `Salami, dry or hard`
is a product type, not a precursor. The real errors are concentrated in ANIMAL
PROTEINS, where cooking is expected and the raw row is a reference sample.

3 of 20 is edge debt, not a prerequisite. Registered; roadmap continues.

## WHY THE OBVIOUS FIXES WERE REJECTED

**A comparability-class exchange cannot fire.** `prefer_consumed_form` was
written, measured against the real pools, and found INERT for all six seeds:
USDA's cooked equivalents differ in variety, brand or enrichment too, so strict
comparability correctly refuses. It was DELETED rather than left in place —
dead safety code is worse than none, because the next reader assumes the axis
is guarded.

**Widening comparability** would weaken a boundary built to stop hidden policy
("nobody has to enumerate what a cut is for that to hold").

**A scoring term** repeats a defect the ranker already carries scars from: a
±0.4 term "can only overturn a NEAR-TIE — so it decided CUT and COATING,
dimensions it never evaluated".

**Extending `cooking_yield_known` per food** works locally and rebuilds the
hand-curated catalog shape this project just escaped — the 27-food artifact and
the 54-identity work order.

## THE DIRECTION WHEN IT IS TAKEN UP

Not a preference table keyed by food name. **Typed representation evidence**:
whether a candidate is a consumed food, an ingredient precursor, a dry
commodity, a raw ingredient or a prepared dish — established from the record,
not asserted about the food. Same principle everything else converged on:

    evidence first · authority second · ranking last

---

## PRODUCTION STATE DIVERGENCE — recorded, not repaired

The identity-derivation repair (parentheticals stripped; part/cut words
postposed; taxonomy heads dropped) was APPLIED to production: **33 acquired
evidence rows were re-keyed** — `thigh chicken|` → `chicken thigh|`,
`salmon fish|` → `salmon|`, `paste tomato|` → `tomato paste|`, and 30 more.
Two collisions (`cod fish|`, `tuna fish|`) were left as unreachable duplicates
rather than merged, because merging two evidence rows is a pricing decision.

⚠ **The derivation that produced those keys is NOT in the tree.** It was
reverted with the blocked publication chain, so a future preload run would
compute the OLD keys again. The re-keyed rows remain MORE reachable, not less,
so nothing is broken — but the divergence is real and must be resolved when
this work resumes. `scripts/rekey_preload_identities.py` was deleted rather
than committed: with no repaired derivation to migrate toward, its contract was
incoherent, and code that implies a capability it does not have is worse than
no code.

## ⭐ A PUBLICATION GATE THIS TRANCHE EARNED

    An artifact built under OPTIONAL semantics must not make an identity LESS
    reachable when those semantics are DISABLED.

`test_the_artifact_rung_is_reachable` caught the expanded artifact violating
this: *"with V2 off, 1 identities became unreachable: ['salmon|roasted'].
Evidence was retrieved, judged and committed, and the turn will price from a
lower rung without saying so."* `salmon|roasted` was one of the eight identities
the expansion appeared to WIN — and it was only reachable with the flag on.

This must become a permanent gate, not a one-off fixture: any future artifact
built under a flag has to be checked with the flag off.
