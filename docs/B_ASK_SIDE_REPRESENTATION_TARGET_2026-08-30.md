# B — REFRAMED: ASK-SIDE REPRESENTATION

**Frozen 2026-08-30 (Danny), before any implementation.**

## The variant is closed as a USEFUL NEGATIVE

Reverted to baseline; the behaviour paths are byte-identical to `4049778`.

The experiment answered the architectural question strongly enough:

> **The interpreter's field list is NOT an ask vocabulary. It is a PERMISSION
> LIST for what the model may resolve by judgement and then LOG.**

Adding `extras` therefore does two things **by design**:

```
1. gives Arnie a way to REPRESENT extras
2. gives Arnie PERMISSION to stop asking and assume extras-shaped uncertainty
```

That is why even the one-word variant suppressed asking, and suppressed it
*more* than the fully-framed exception. **The closed-list wording was not the
culprit. The COUPLING is.**

⛔ **Do not keep iterating on that list.** Every edit trades semantic coverage
for more aggressive assumption.

## ⭐⭐⭐ THE FROZEN TARGET

> **Representing an unresolved semantic subject must NOT alter whether that
> subject is defaultable. Representation and resolution-permission are
> INDEPENDENT STATE.**

In practice: the interpreter needs an **ask-side structured vocabulary** able to
emit `unstated_extras`, `consumption_complete`, `menu_size` and the rest
**without granting permission to assume those things and log**.

## Why this fits everything else measured

```
staged pipeline      ALREADY carries ask-specific `requested_fields`, separate
                     from any resolution permission
interpreter          has NO equivalent independent representation
unstated_extras      becomes representable ONLY by contaminating the judgement
                     vocabulary — proven three times (6, 7, 7 emissions, each
                     costing asks)
portion_multiplier   still has NO proven producer on either path
DEFAULTABILITY       cannot safely consume an ask type if PRODUCING that type
                     changes whether Arnie asks
```

That last line is the deepest reason this matters: a defaultability policy reading
`unstated_extras` would be reading a field whose very existence made Arnie less
likely to ask — **the measurement would be entangled with the behaviour it is
measuring.**

## EXIT TEST — both required

Add `unstated_extras` to the ask-side representation, rerun the same census,
and require:

```
1. real `unstated_extras` emissions
2. clarification rate AND material asks stay INSIDE the same-SHA null
```

Only both together demonstrate capability decoupled from behaviour.

⚠ The null must be measured **on the variant's own SHA** — the existing null
(Δ1 ask) was measured at `ede35b9` and is an estimate for any other code state.

## Evidence trail

```
census_v4  4049778  baseline                        asks 30  extras 0
census_v5  ede35b9  exception (2 edits)             asks 25  extras 6
census_v6  ede35b9  NULL TWIN of v5                 asks 24  extras 7   Δ null = 1
census_v7  cfe4d51  variant (ONE WORD)              asks 24  extras 7   Δ -6
```
