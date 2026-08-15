# ⛔⛔ THE CORPUS ATTRIBUTION INSTRUMENT IS BROKEN — AND WHAT IT INVALIDATES

*(Danny, 2026-08-16. P0 of the corrected sequencing. Documentation only — no
code, no schema, no flag changed by this commit.)*

**Interpretation adoption is FUNCTIONALLY CONNECTED in production for one user.
Its CORPUS-BASED EVIDENCE is invalid** until the attribution instrument is
repaired and the run is repeated from a clean database. Those are two different
claims and 2026-08-15 published them as one.

## THE DEFECT, MEASURED FROM THE ARTIFACT ITSELF

`scripts/corpus_through_the_real_turn.py::_reconcile` attaches each written food
row to the corpus item it came from **by `normalize_name` of the food name**.
`normalize_name` strips non-Latin script, so every Cyrillic surface reduces to
its digits — and for a name with no digits, to the **empty string**.

Measured on `data/corpus/production_like_v1.json` (100 items, 4 users):

```text
user         items   distinct normalized keys   items sharing a key with another
en-staples      30                          8                                 28
qualified       30                          8                                 30
ru              30                          3                                 28
branded         10                          6                                  7
──────────────────────────────────────────────────────────────────────────────
                                       28 of the 30 ru items share ONE key: ''
```

⭐ **AND THE EMPTY KEY IS A WILDCARD, NOT MERELY A COLLISION.** The reconciler's
second pass is a substring test:

```python
target in normalize_name(candidate) or normalize_name(candidate) in target
```

`'' in anything` is **True**. So once interpretation translates the surface —
`Куриная грудка` → `Chicken breast` — the row's target is non-empty, the exact
pass fails, and the fallback matches **the first unclaimed `ru` candidate in
corpus order, whatever food it names**. Every subsequent row is shifted with it.

⛔ **THE RESULT, READ BACK OUT OF `run_shadow.json`:**

```text
user         rows attributed   attributed to a DIFFERENT food
en-staples               24                                0
qualified                19                                0
ru                       29                               29   (28 truly wrong;
branded                   9                                0    1 flagged on
──────────────────────────────────────────────────────────      punctuation only)
```

The shift is visible item by item:

```text
slot 'Помидор'         <- row 'Cheese pizza'        rung=ESTIMATE_OR_REFUSE
slot 'Пицца сырная'    <- row 'Carbonara'           rung=CACHED_BY_THIS_TURN
slot 'Хамон'           <- row 'Tomato'              rung=MEMORY   role='repeat'
slot 'Куриная грудка'  <- row 'Листья салата'       rung=MEMORY   role='establish'
```

`run_off.json` shares the instrument and fails the same way: **26 of its 27
attributed `ru` rows name a different food.** `--compare` reads both files, so
the comparison inherits the defect from both sides.

⭐⭐ **THE ZERO THAT SHOULD HAVE CAUGHT IT DID NOT.**
`rows_the_corpus_did_not_predict` is `0` in both runs — the reassuring value —
**because the wildcard guarantees every row finds a slot.** A leftover-detector
cannot detect anything when the matcher cannot fail to match. This is
[[verify_the_instrument_before_its_silence]] at a new site: the instrument's own
"nothing unexplained" signal was produced by the defect.

## WHAT IS INVALIDATED, AND WHAT SURVIVES — STATED SEPARATELY

**INVALID — any conclusion that joins a written row to its corpus item's
identity, declared bucket, or role:**

```text
realized_mix_pct · realized_mix_pct_comparable · drift_pts · mix_within_tolerance
uncovered_buckets                          bucket comes from the SLOT, not the row
memory_at_settle_pct · memory_addressable_after_pct
"memory was earned by repetition"          role establish/repeat is slot-derived
the per-population cacheability ratios     en 16/24 · branded 8/8 · qualified 2/22 · ru 2/27
"2 of 22 QUALIFIED and 2 of 27 non-English foods ever cached"
every production-distribution drift claim built on the above
```

⚠ **AND BE PRECISE ABOUT THE ARITHMETIC.** Candidates are pooled **per user**,
so a within-user rung ratio is not corrupted by within-user shuffling, and every
`ru` item is declared `NON-ENGLISH` so that bucket is coincidentally intact.
**Those numbers are withdrawn anyway** — not because each is provably wrong, but
because the instrument that produced them cannot demonstrate correct
attribution, and **a percentage may not publish while attribution completeness
is unproven**. Some will likely return unchanged after P2. That is a prediction,
not a permission.

**SURVIVES — measured without the reconciler, and independently:**

```text
turns_driven=100 · entries_written=81 · turn_failures=0 · recovery bubbles=0
latency p50/p95/max                          per-turn, never joined to a slot
resolution_rows=46 · states 22 resolved / 19 distinct / 5 product
PRODUCT binds nothing                        5 product rows, 0 consumer bindings
no false collapse                            read from the resolution store
distinct_families_fragmented = {}            read from the resolution store
non-English resolution 19/19                 surface forms, store-side only
anti_vacuity.turns_reached_the_model         instrument liveness, not attribution
```

⛔ **`corpus_items_with_no_row = 19` is NOT in either list.** The count is real —
19 fewer rows than items — but *which* 19 items went unwritten is slot-derived
and therefore unknown. `Кефир 1%` reports `NO_ROW_WRITTEN`; that is not evidence
it failed.

## THE CACHEABILITY PHENOMENON — RECORDED, DELIBERATELY UNQUANTIFIED

The phenomenon is **independently proven** and does not rest on the corpus. On a
live production turn, `Сметана 5%`:

```text
entity_identity_consumed stamped=1     key = 'smetana 5percent'
pricing.memory: 4ms                    the rung RAN and returned nothing
evidence_qualified raw=8 kept=0        dispositions={'DIFFERENT_IDENTITY': 8}
canonical_priced rung=estimate         price unchanged: 80 kcal/100g
```

**Consumption made the key addressable; it did not make the row exist.** Nothing
seats a candidate, so nothing caches, so a correct key addresses nothing.
Cacheability is a separate defect with a separate owner.

⛔ **Its PREVALENCE is unknown and must not be stated.** Every ratio that
previously quantified it was reconciliation-derived. Do not write "QUALIFIED
never caches" as a rate, a fraction, or a population share until P2 republishes
one.

## ✅ P1 IS DONE — ATTRIBUTION v2 *(2026-08-16)*

**The join is now closed and made of ids.** No food name reaches the decision.

```text
client_msg_id per driven turn      make_turn_id returns "ios:<id>" VERBATIM,
                                   so the establish and the repeat of one food
                                   can no longer share an hour-bucket hash
ledger_events(entry_id, turn_id)   the turn that COMMITTED each row
                                   (measured: 378 of 378 rows carry one)
a flush turn DECLARES its origin   written down before it is driven, never
                                   deduced afterwards
turn_metrics.turn_id               proof a driven turn actually RAN — a flush
                                   that was deduped drains nothing and looks
                                   exactly like a flush with nothing to drain
```

⭐ **HELD FOOD IS DRAINED, NOT DISENTANGLED.** `_drain` settles a user's
outstanding food **before** driving them again, so at most one food per user is
ever in flight and every commit window belongs to exactly one corpus item. v1
tried to separate two foods in one window afterwards, by name. This removes the
question instead of answering it.

⭐⭐ **AND THE DECISION IS FOUR LINES, ALONE, SO IT CAN BE GATED STRUCTURALLY.**
`_position_for_row` reads one key and looks it up. The AST gate asserts the only
string it may name is the correlation key and the only call it may make is a
dict lookup — so there is nowhere for a comparison, a fuzzy pass or a fallback
to live.

**PROVEN BY MUTATION — each verified to LAND before its result was read:**

```text
name-similarity fallback in the decision fn   RED  the AST gate
a faithful v1 rescue pass inside _attribute   RED  "an unattributable row is not
                                                    rescued by an identical name"
publish = True regardless of completeness     RED  x3, the percentage gates
```

⚠ **THE SECOND MUTATION IS THE ONE THAT MATTERS**, because the AST gate did NOT
catch it — it lives outside the gated function and uses no banned name. A
structural gate and a behavioural gate cover different halves, and this session
needed both.

**PROVEN LIVE, on the scratch database:**

```text
6-item smoke     6 of 6 rows attributed · 0 unattributed · 0 problems
18-item smoke    18 items + 1 FLUSH · 18 of 18 attributed · 0 problems
                 ios:corpus:...:flush:1  ->  Пицца сырная
```

⭐⭐⭐ **THE FLUSH CARRIED A RUSSIAN ROW — the exact case v1 got wrong.** Held
food committed under the flush turn's id and was mapped back to its declared
origin. Had that mapping failed, the row would have been reported UNATTRIBUTED
and the run would have refused to publish, which is the whole point.

⚠ **AND THE FIRST SMOKE PROVED NOTHING ABOUT THE FLUSH PATH** — it drove 0
flushes, because its six items were one per user and each settled in its own
turn. A green run over a path that never executed is the shape this whole
session is about. The 18-item run is the one that counts.

Also landed: `--compare` **refuses** any report below `ATTRIBUTION_VERSION`, and
refuses a complete-but-unattributed one. Verified against the recorded
artifacts — it exits 1 and names the reason. Suite: **9152 passed · 107 skipped
· 4 xfail · 0 failed** (baseline 9136; the 16 new tests are the difference).

## P1 — WHAT REPAIR MEANT

⛔ **`surface_key()` ALONE IS NOT THE FIX.** It removes the empty-Cyrillic
collision — that is real and it is why the resolution store was never affected —
but it is still a **name** match, and interpretation transforms names:

```text
Сметана 5%       ->  Sour cream 5%
Куриная грудка   ->  Chicken breast
```

Semantically identical, different script-preserving keys. **The instrument must
never infer turn ownership from lossy or semantic food-name matching.**

**CORRELATION ORDER — take the first available, never skip down for convenience:**

```text
1  stable turn id / operation id / idempotency key / ledger correlation id
2  the committed entry id returned or emitted by settlement
3  per-turn before/after entry capture in an isolated database
4  exact surface_key() match — ONLY where the source surface is preserved
```

**GATES THE REPAIRED INSTRUMENT MUST PASS BEFORE IT PUBLISHES A PERCENTAGE:**

```text
every committed entry maps to AT MOST ONE driven turn
every driven turn maps to its own entry OR a typed no-row outcome
no matcher key is shared by two corpus items
delayed settlement maps back to its originating pending operation
translation / canonicalization cannot reassign a row to another turn
unmatched AND ambiguous rows FAIL the run — they may not vanish into totals
percentages do not publish unless attribution completeness passes
the database is clean and corpus users are isolated before the run starts
```

⚠ **ONE USER PER POPULATION IS A HELP, NOT A SOLUTION.** It bounds the blast
radius of a mismatch — it is why `en-staples`, `qualified` and `branded` show
zero name mismatches — but it does not solve **delayed settlement** or
**within-user ordering**, which is exactly where the surviving doubt lives.

## ⛔⛔ P2 MUST PUBLISH THREE COVERAGE NUMBERS, NEVER ONE *(Danny, 2026-08-16)*

The general settlement owner only ever sees turns routed as `STRUCTURED_FOOD`,
and on 2026-08-15 **three of four ordinary food turns never reached that lane**
(`entity_identity_skipped reason=no_interpretation` — the food was logged from
the legacy tool batch). So a support rate measured inside structured traffic
describes a quarter of the product and reads like all of it.

```text
A  structured-food routing rate    structured turns / ALL food turns
B  A11 support rate WITHIN structured   supported meals / structured meals
C  whole-product coverage          supported meals / ALL food meals  =  A x B
```

⛔ **C IS THE ONLY ONE THAT DESCRIBES THE PRODUCT, AND B IS THE ONE THAT WILL
LOOK BEST.** B is what this slice can move on its own, so B is what a later
reader will quote. **No support rate publishes without its routing rate beside
it.** Every one of these numbers can be individually correct while the
population underneath changes — the quiet version of the `16 of 15 (106.7%)`
error, where numerator and denominator counted different things.

⚠ **AND THE MEAL IS THE UNIT, NOT THE ENTRY.** A11 declines the whole meal when
ANY item lacks local evidence, so a 44.6% addressable ENTRY rate does not imply
a 44.6% supported MEAL rate. Measuring per entry would overstate coverage by
construction.

## P2 — WHAT THE RE-RUN MUST PUBLISH, AND WHAT CLOSES IT

Run from a clean database. Publish all of:

```text
attribution completeness · ambiguous and unmatched counts
turn failures · recovery bubbles
non-English resolution success
false collapses · fragmentation
PRODUCT non-binding
memory / artifact / estimate mix
cacheability by population
production-distribution drift
cross-language convergence and duplication
latency
the instrument's own limitations
```

**Closure requires all five, with no exceptions and no rounding:**

```text
ambiguous attribution     = 0
incorrect attribution     = 0
unexplained written rows  = 0
false collapses           = 0
PRODUCT bindings          = 0
```

Only then may unconditional *"interpretation adoption is closed"* language
return to §0z.

## THE ARTIFACTS ARE PRESERVED, NOT REPLACED

`data/corpus/run_shadow.json` and `data/corpus/run_off.json` are kept **byte for
byte** — they are the evidence for this document. See
`data/corpus/run_shadow.INVALID.md` for the marker and the hashes.

⚠ **`compare_runs()` still reads both files today.** The refusal is a P1 CODE
change and is not in this commit. Until it lands, the marker is the only thing
standing between these files and a second publication of the same numbers.
