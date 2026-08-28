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
