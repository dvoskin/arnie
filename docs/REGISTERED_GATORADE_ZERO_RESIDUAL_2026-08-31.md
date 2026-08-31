# REGISTERED — Gatorade Zero prices 6/8, not 8/8

**Monitoring item. Not a tranche, not an investigation.** Danny 2026-08-31:
*"register it and let production data decide whether it matters enough to
investigate."*

## What was observed

After the zero-calorie priceability repair (`2c0e233`), against live OFF:

```
Coca-Cola Zero Sugar          pool=12  ->  12/12 priceable
Gatorade Zero Glacier Cherry  pool=8   ->   6/8  priceable
```

The deterministic defect **is** repaired — the class that was structurally
unpriceable now prices, and the two named fixtures both resolve. But two of
eight Gatorade candidates still do not, and the cause was not traced.

## Why it is NOT being chased now

Candidate-level non-priceability has several innocent explanations that are
indistinguishable without production data — a record genuinely missing a macro
field, an incoherent panel correctly refused by the new check, or a row that
was never a Gatorade Zero at all. Chasing it would be choosing work by
plausibility, which is exactly the habit this phase is moving away from.

## What decides it

`event=priceability_rejected` now carries `reason`, `calories`,
`macro_fields_present` and `n_present`. Once `2c0e233` is deployed, production
says which reason class those refusals fall into and how often real turns hit
them.

**Escalate only if** the census shows a material rate of
`PRICEABILITY_MISSING_FIELDS` or `PRICEABILITY_INCOHERENT` on branded drinks.
Otherwise this stays a curiosity about two OFF records.
