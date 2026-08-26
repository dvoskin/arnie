# CF27 — REGISTERED: legacy tier-0 replays nutrition across incompatible units

*Found 2026-08-26 tracing a production iOS turn. **Registered, NOT
implemented** — Danny's call. The tier-0 override touches every legacy log;
changing it is its own tranche, not a same-session add-on.*

## The causal chain, end to end

```text
'Grilled chicken breast'
      ↓  coverage_for  →  Unsupported  (rung=None, no local evidence)
_canonical_route returns None
      ↓  turn routes to legacy UNTOUCHED, exactly as designed
legacy fetch_candidates, TIER 0
      ↓  _logged_history_match matches by content-token set
prior entry replayed, ratio CLAMPED across incompatible units
      ↓
WRONG COMMITTED NUTRITION
```

⭐⭐⭐ **TIER-0 FIRING IS A CONSEQUENCE OF CANONICAL DECLINING, NOT A
COMPETITOR TO IT.** Ownership is decided first in `_canonical_route`; once it
returns `None` the turn belongs to legacy and canonical is never consulted
again. Any fix that treats these as racing owners is fixing the wrong picture.

## The defect itself

`handlers/tool_executor.py::_lead_count` reads the leading number of a
quantity string and **ignores the unit**:

```python
ratio = _lead_count(quantity) / max(_lead_count(fe.quantity), 0.5)
if ratio <= 0 or ratio > 20:
    ratio = 1.0
```

`_lead_count('200 g')` → 200.0 · `_lead_count('6 oz')` → 6.0 · ratio **33.3**.

⛔⛔ **AND THE GUARD CLAMPS RATHER THAN ABSTAINS.** 33× is not a large
scaling — it is evidence the two quantities are **not comparable at all**.
Clamping turns "these cannot be compared" into "scale by 1", which is the
project's recurring failure shape: *an unknown converted into a number instead
of a refusal*. See [[feedback_arnie_absence_is_not_a_negative]].

⭐ The override's own docstring already warned about the blast radius:

> A ROW IS NOT GROUND TRUTH JUST BECAUSE WE WROTE IT. This override returns
> before the resolver, the plausibility cap, the web lane and the micro
> fallback — everything that would otherwise object — so a bad row here is not
> merely wrong once, **it is wrong forever**.

## The two production fixtures

| | entry 3027 — the POISONED SOURCE | entry 3063 — the REPLAY |
|---|---|---|
| logged | 2026-08-18, `6 oz` | 2026-08-26, `200 g` |
| committed | 230 kcal, P16.5 **C22.5** F8.2 | 230 kcal, P16.5 **C22.5** F8.2 |
| `estimated_flag` | **False** → eligible as ground truth | False |
| truth | ~257 kcal, P51.9, C0, F5.4 | ~302 kcal, P61, C0, F6.3 |

⛔ **22.5 g OF CARBS ON GRILLED CHICKEN BREAST IS IMPOSSIBLE**, and 3027
carried it while flagged non-estimated — which is precisely what made it
permanent ground truth. Identical totals at different quantities is the
signature: the numbers did not scale because the ratio was clamped to 1.0.

**Both corrected** against USDA `171534` (`Chicken, broiler or fryers, breast,
skinless, boneless, grilled`, 151 kcal/100g, P30.5 C0.0 F3.17), each with a
paired `updated` ledger event sourced `cf27:unit_blind_history_replay`, and
both days recomputed FROM THE ENTRIES and verified in sync.

## Adjacent finding — NOT part of CF27's cause

`event=memory_confidence_unmapped key='beef grilled' value='canonical'` fires
when the first trusted memory row (row 1033) is read back:
`remember_canonical_settlement` writes `confidence="canonical"` and
`food_intelligence._CONF_NUM` has no entry for that grade, so it falls back to
a declared default.

⚠ **INSTRUMENTATION / RANKING DEBT, NOT A CAUSE.** It did not produce either
wrong commit. Do not let it expand CF27 unless someone **proves it changes
selection** — the ironic shape is that the newest and most authoritative rows
are the ones the confidence mapping cannot score.

## Disposition

**Registered. Not implemented.** Sequencing is unchanged:

```text
CF26 deploy/prod proof → CF24 attribution + closure → FREEZE MEMORY WORK →
CF27 registered NOT implemented → REAL-MEAL BASELINE → OILS →
MATERIALITY/PREPARATION → COMPOSITION → CLARIFICATION → MULTI-FOOD →
return to registered defects by measured priority
```

⛔ **ONE PROMOTION RULE.** If CF27 reproduces during a normal production
canary and commits another wrong meal, it is promoted from registered to
**immediate Rule-0 repair**. Otherwise it does not pull work sideways.

## ⭐⭐⭐ THE MORE IMPORTANT FINDING IS THE DECLINE ITSELF

```text
'Grilled chicken'         @ 200 g  →  Supported
'Grilled chicken breast'  @ 200 g  →  Unsupported, rung=None
```

**Adding truthful specificity currently makes Arnie LESS capable.** The same
shape appeared three times this week — `Salmon` → `Salmon, dry grilled`,
`Shrimp` → `Shrimp, grilled`, `Chicken` → `Grilled chicken breast` — where a
qualifier the interpreter itself added moved the identity off every artifact
the corpus holds.

That is a **coverage/semantics problem for the upcoming food-semantic work**,
to be solved systematically. It is emphatically NOT a reason to teach the
legacy lane another patch: tier-0 exists to paper over exactly this gap, and
its blast radius is what this file records.
