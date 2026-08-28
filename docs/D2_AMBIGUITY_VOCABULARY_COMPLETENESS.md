# D2 — AMBIGUITY VOCABULARY COMPLETENESS

**Opened 2026-08-27.** Carries the **narrow prompt exception** authorized by
Danny.

> **Exit: all seven semantic subjects are independently producible, compound
> asks preserve multiple subjects, and no classification depends on prose.**

## ⭐⭐⭐ THE PROMPT FREEZE EXCEPTION — WHY IT IS NOT A VIOLATION

The standing rule (`feedback_arnie_food_prompt_frozen`) exists to stop
**speculative prompt tuning until examples pass.** This is not that.

> *"You are not improving the model prompt until examples pass. You are
> changing the OUTPUT SCHEMA CONTRACT because measurement proved the existing
> contract cannot represent the state the application requires."*
> — Danny, 2026-08-27

The measurement: **24 turns, and the producer emitted exactly two field values**
(`quantity` ×18, `prep` ×12) against seven semantic subjects. No downstream code
can recover a distinction that was never represented — **without reading prose
or asking a second model**, both of which were rejected.

## What the exception changed — and ONLY this

⭐ **The vocabulary was already in the prompt, attached to the WRONG BRANCH.**
`(fields: quantity, identity, brand, prep, consumed)` sat inside the LOG-time
rule about unknowns resolved by judgement. The ASK contract showed only
`field:"prep"` by example, so on an ask the model never reached for `consumed`.

1. **Completed the value set** — added `extras` and `multiplier`, and gave each
   value a one-line definition of what it names.
2. **Attached the same closed vocabulary to the ASK branch**, stating
   explicitly that `prep` there is the example's field, not the default.

**Unchanged:** food reasoning · nutrition policy · default behaviour · every
line of prose the user sees · the ask/log decision · thresholds.

## Six fields, seven subjects

```
quantity   -> menu_size (branded) | continuous_portion (unbranded)
multiplier -> portion_multiplier        consumed -> consumption_complete
prep       -> preparation_fat           extras   -> unstated_extras
identity   -> identity_variant
```

`quantity` splits on `items[].branded`, a STRUCTURED item flag — the one split
that was already working and stays code-side.

## Binding constraints

- **Do NOT derive subjects from `points[].qs`.** It contains exactly the
  missing subjects, in prose. Using it is the `_FACET_KINDS` inference this
  work removed, one layer down. c16 is the proof: its ambiguities said
  `prep, prep, prep` while its `qs` asked about toppings.
- **Compound asks keep MULTIPLE structured records.** Already working (10 of 24
  asks emitted >1 record pre-exception); must not regress.
- **Unknown or missing structure stays EXPLICIT**, never guessed —
  `unclassified` remains durable, visible, and not model-selectable.
- **A producer registry test proves each canonical subject has at least one
  actual producer** (`tests/test_protected_types_have_proven_producers.py`,
  `data/ask_type_producers.json`).

## Re-measurement

Rerun `scripts/characterise_ask_producer.py` on the same 8 cases × 3 reps and
compare against `data/corpus/producer_characterisation_2026-08-27.jsonl`.
**Then, and only then, does T1 resume.**

---

## FIRST MEASUREMENT AFTER THE EXCEPTION — **EXIT NOT MET**

Same 8 cases × 3 reps, same instrument.
Raw: `data/corpus/producer_after_exception_2026-08-27.jsonl`.

```
field vocabulary   BEFORE {'quantity':18, 'prep':12}
                   AFTER  {'quantity':11, 'prep':6, 'extras':5}
```

| subject | before | after | |
|---|---:|---:|---|
| `unstated_extras` | 0 | **3** | ⭐ NEW PRODUCER |
| `consumption_complete` | 0 | **0** | ⛔ still absent |
| `portion_multiplier` | 0 | **0** | ⛔ still absent |
| `identity_variant` | 0 | **0** | ⛔ still absent |

**Compound distinct-field asks 3 → 6.** c16 separates `['prep','extras','extras']`
where it emitted `['prep','prep','prep']` on the identical utterance, all 3 reps.

⛔ **THE TWO SUBJECTS THE EXCEPTION WAS MADE FOR DID NOT APPEAR.** `extras` was
a bonus; `consumed` and `multiplier` were the target.

## ⛔⛔ AND D1 APPEARS TO HAVE REGRESSED — CAUSED BY THIS CHANGE

```
zero-ambiguity asks   5/18 (28 %)  ->  8/19 (42 %)
total ambiguity records      30    ->    22
```

It spread to cases that previously emitted records:

```
c9  rep1  ['quantity','quantity','quantity'] -> []      (all 3 reps lost every record)
c23 rep1  ['quantity','quantity','quantity'] -> ['quantity']   (all 3 reps)
```

⭐ **PLAUSIBLE MECHANISM: offering six choices where there were effectively two
made the model likelier to emit NOTHING than to pick.** If real, **the D2 fix
actively worsened D1** — precisely the interaction the tranches were separated
to keep visible, arriving in the first measurement.

⚠ n=24 cannot separate this from run variance, though the direction is
consistent across all 3 reps of c9. **A confirmation run is the only way to
know**, and it is due diligence on a change I made — not an optional extra.

**Status: exception NOT validated. Not reverted, not endorsed — measured.**

---

# ⛔ EXCEPTION REVERTED 2026-08-27 — experimental isolation, not retreat

**The schema deficiency remains PROVEN. The implementation attempt was
introduced one dependency too early.**

## The confirmation run settled it

```
PRE    (2 fields)   zero-ambiguity 5/18 = 28 %   records = 30
POST-1 (6 fields)   zero-ambiguity 8/19 = 42 %   records = 22
POST-2 (6 fields)   zero-ambiguity 6/16 = 38 %   records = 20
```

Two independent post runs, both worse on both metrics. **Record emission fell
~33 %.** Not noise-shaped:

```
c23  PRE ['quantity','quantity','quantity'] ×3   ->  POST ['quantity'] ×3, BOTH runs
c9   PRE records in all 3 reps                   ->  POST none at all,     BOTH runs
```

⭐ **Offering six choices where there were effectively two made the model
likelier to emit NOTHING than to pick.** The D2 change damaged D1.

## D1 BLOCKS D2 — the sequencing was backwards

```
c2 (needs `consumed`)     5/5 of its asks emit ZERO records
c3 (needs `multiplier`)   4/6 of its asks emit ZERO records
```

**The vocabulary could not be exercised on the cases that need it.** Naming
`consumed` in the schema cannot help an ask that records no ambiguity at all.
Keeping the exception would have meant holding a known regression to enable a
measurement that cannot yet be taken.

`unstated_extras` 0 → 3 (stable across both runs) is encouraging and does NOT
justify keeping it: that is a richer vocabulary bought by degrading the
existence of the underlying representation.

## ⚠⚠ c20 — PRESERVED AS AN EXPLICIT WARNING CASE

c20 **did** emit ambiguity records and **still** did not select `consumed`
(0/1 of its asks were zero-record). So even after D1 is fixed, **D2 splits into
two questions that must NOT be collapsed:**

1. **Can the schema EXPRESS the subject?**
2. **Does the interpreter actually EMIT the correct subject when that situation
   occurs?**

A schema that can express `consumed` while the producer never selects it is the
same failure class as a guard whose protected input never occurs.

## The corrected sequence (binding)

```
1. ✅ revert the exception to the known-better baseline
2.    D1 — every ask-producing path with an unresolved subject emits >= 1 record
3.    rerun the 24-turn characterisation; prove the zero-record population is
      gone or materially reduced
4.    reapply the vocabulary exception IN ISOLATION
5.    rerun the same characterisation AND the ask-type measurement
6.    accept D2 only if the new subjects appear WITHOUT reducing ambiguity
      coverage or creating new omissions
7.    T1 only after both are measurable
```

**Board: D1 first — representation EXISTENCE. D2 second — representation
EXPRESSIVENESS and CORRECT SELECTION.**

---

# ⛔⛔⛔ FORBIDDEN INFERENCE

> **"A staged enum value exists, therefore the subject has a producer."**

**This inference is banned.** An enum member is **capability vocabulary, not
producer evidence.**

Proved twice, one layer apart:

1. `classify("consumed") == CONSUMPTION_COMPLETE` mapped correctly while
   **nothing ever emitted `field="consumed"`** — a consumption question arrived
   labelled `menu_size`.
2. `AmbiguityType.CONSUMED_QUANTITY` and `COMPONENT_BREAKDOWN` exist in the
   staged store, and I predicted the zero-producer subjects would gain
   producers once both authorities were read. **Neither fired in 50 turns.**

**Producer evidence is an observed emission on a real path, cited by run.**
Nothing else counts. This is the same family as *a guard whose protected input
never occurs* — the vocabulary can express it; that says nothing about whether
anything does.

## Current evidence (census 2026-08-28, BOTH authorities, 50 turns)

```
menu_size             8   empirically real
continuous_portion   12   empirically real
preparation_fat       7   empirically real   ⚠ one instance semantically suspect
identity_variant      2   empirically real
consumption_complete  0   UNPROVEN
unstated_extras       0   UNPROVEN
portion_multiplier    0   UNPROVEN
unclassified          2   not semantically classifiable from observed authority state
```

**Four subjects are empirically real. Three remain unproven. Two asks cannot be
classified from the authority state observed.**

## ⚠ THE MAPPING IS EXERCISED, NOT VALIDATED

Case 17 typed `preparation_fat` on a question about wrap **SIZE**. That is
**three different defects wearing one symptom**:

1. the staged **field** is wrong;
2. **`_STAGED_MAP`** is wrong;
3. the **rendered question and the structured subject disagree**.

The census could not distinguish them — it captured `ask_types` but not
`requested_fields`. **A per-ask authority record is required:**

```
producer -> requested_fields -> mapped ask_type -> rendered question
```

aggregated into a confusion table. Only that shows whether `_STAGED_MAP` is
CORRECT rather than merely EXERCISED.

## Sequence (binding)

```
full suite green -> empirical staged-map census -> repair any mismatches
   -> rerun producer registry across both authorities -> recompute D2
   -> ONLY THEN decide whether the three zero-producer subjects truly lack producers
```

---

# ⛔⛔⛔ THE D2 GATE — TIGHTENED 2026-08-28 (Danny)

An earlier form said *"every contributing type has a verified producer path."*
**Not strong enough.** This incident showed that a real field emitted by a real
producer can still carry the wrong semantics — a consumption question was
observed wearing `menu_size`, and `menu_size` is in `DEFAULTABLE_CANDIDATES`.

> **Every contributing classification must have an OBSERVED PRODUCER EMISSION
> whose RAW FIELD → SEMANTIC TYPE mapping has been VALIDATED AGAINST THE
> RENDERED QUESTION.**

Three conditions, all required, none sufficient alone:

```
1. observed emission        the field actually flowed on a real path, cited by run
2. validated mapping        raw field -> semantic type checked, not read off source
3. rendered-question check  the question the USER SAW matches that semantic type
```

⭐ **(3) IS THE ONE THIS INCIDENT ADDED.** "Real field + real producer" is not
enough: `preparation_fat` appeared on a wrap-SIZE question, and that mismatch is
invisible to any check that stops at the mapping.

## Sequence (binding, do not reorder)

```
1. corrected census
2. producer × raw field × rendered-question CONFUSION TABLE   (primary artifact,
                                                               NOT a histogram)
3. explain / repair EVERY mismatch, individually
4. re-run census
5. freeze the verified producer registry
6. recompute D2 from VERIFIED PRODUCERS ONLY
7. re-evaluate DEFAULTABILITY
8. only then reconsider 27983be
```

⚠ **The biggest risk now is seeing `consumed_fraction` finally appear and
rushing back to the defaultability thesis.** The instrument may finally be
trustworthy; that requires one clean run to demonstrate, not an inference.

## Rows requiring individual explanation

- `mapped_ask_type == unclassified`
- the rendered subject conflicts with the mapped type
- producer provenance missing
- `menu_size` or `continuous_portion` appears *(both carry unresolved pre-fix
  contamination)*
