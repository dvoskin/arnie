# TRANCHE — CANONICAL ADOPTION

**Opened 2026-08-31, immediately after CF24 closed.** The pivot: stop proving
the architecture is safe and start getting traffic into it.

## The question

> **Why are real branded products failing canonical admission?**

⛔ **DO NOT START BY FIXING MUSCLE MILK.** It is the first FIXTURE, not the
first repair. A one-product fix is the shape this project has repeatedly shown
to be worthless — the value is in the decline POPULATION.

## The observation that opened it

Production, `telegram:9503`, 2026-08-31 17:21, build `63d926a`:

```
event=off_identity_refused    food=Muscle Milk Pro Series Vanilla products=1
                              verdicts=SAME_IDENTITY
event=evidence_qualified      raw=8 kept=0 dispositions={'DIFFERENT_IDENTITY': 8}
event=branded_lookup          outcome=miss db_grade=- needs_branded=True panel=False
event=resolution              class=manufactured rung=estimate
                              macros_from_source=False portion=user_stated
event=nutrition_promotion     outcome=declined reason=unverified_identity
```

A named, packaged, barcode-having product — and the user received a **legacy
estimate**. ⭐ Note `off_identity_refused ... verdicts=SAME_IDENTITY`: an OFF
product was found AND judged the same identity, and was still refused. That
line alone is worth understanding before any fix is designed.

⚠ **This is n=1 and is a FIXTURE, not a rate.** Four entries I happened to see
while querying for CF24 showed 1 of 4 carrying a canonical artifact rung — that
is consistent with the frozen 9.0% ownership figure and is NOT a measurement.
This tranche opens with a census precisely because this session twice showed
what happens when an incidental observation becomes a premise.

## The census — capture per DECLINE, per Danny 2026-08-31

```text
input
candidate identity
identity evidence available
identity confidence / qualification result
nutrition source available
serving evidence available
canonical admission result
decline reason
legacy result
correct expected outcome
```

The last field is a human label and must be frozen before any repair is
designed, or the metric becomes whatever the repair happens to achieve.

## Why branded is the highest-value bucket

Branded products carry the **best possible evidence chain**: exact product
identity → manufacturer/package nutrition → serving basis → deterministic
settlement. There is no long-term reason a known Muscle Milk product should end
as a generic estimate. If `unverified_identity` is frequent, one producer
unlocks a large class of meals at once.

## ⛔ Contracts carried in from this session

- **`pin_runtime` on every measurement.** The manifest is not the authority;
  the runtime snapshot is, and subject cohort membership decides behaviour.
  `scripts/prodruntime.sh`, not `prodenv.sh`.
- **Producer/basis census travels with EVERY measurement**, not just the first
  — otherwise a coverage change reads as a policy effect.
- **`benefit / null / harm`** preregistered, harm binding to *stop and
  characterise the reversal*.
- **Ownership is measured against the 9.0% baseline** on the frozen population.
  Every newly owned meal must name the evidence producer that made ownership
  possible. **An increase caused by weakened authority is invalid.**
- **The 40% rollout gate is fixed** and rises through capability, never through
  relaxed authority.
- **A signal is not evidence until its writer is known** (the `times_used`
  lesson, 2026-08-31).

## Runs alongside, not after

Food experience — DEFAULTABILITY → OILS → composition / clarification /
multi-food — proceeds in parallel. This lane is what stops the architecture
being perfected for the 9% of meals that reach it.
