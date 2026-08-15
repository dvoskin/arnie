# ⛔ THESE RUN ARTIFACTS ARE INVALID FOR RECONCILIATION-DERIVED CONCLUSIONS

*(2026-08-16, P0)*

```text
run_shadow.json   sha256 7439954eb01edcc66482520e5a5d13e9e415b3181c86a0a78017ddf0af5a2f2b
run_off.json      sha256 dbbe477dfe96943b1353db052c7379345d2b5b865dc48a13616cf38b3e6112bf
production_like_v1.json (the corpus definition, still valid)
                  sha256 60adff4ce60bee387a5ba61f30dcece14faec542525c7c6845b47c5f6907d1d6
```

**Both run files are PRESERVED BYTE FOR BYTE and must not be edited, replaced or
deleted.** They are the evidence for the defect, and the hashes above are how a
later reader proves they were not quietly touched.

## WHY

`_reconcile` attributes rows to corpus items by `normalize_name`, which reduces
every digit-free Cyrillic surface to the **empty string** — 28 of the 30 `ru`
items share one key — and whose substring fallback makes that key a **wildcard**
(`'' in anything` is True). Measured from these files: **29 of 29 attributed
`ru` rows in `run_shadow.json`** and **26 of 27 in `run_off.json`** are attached
to a different food than the one that produced them.

`rows_the_corpus_did_not_predict = 0` in both files is not reassurance — the
wildcard guarantees every row finds a slot, so the leftover detector could not
report anything else.

## WHAT THIS FORBIDS

Do not quote, re-derive, or compare: `realized_mix_pct`,
`realized_mix_pct_comparable`, `drift_pts`, `mix_within_tolerance`,
`uncovered_buckets`, `memory_at_settle_pct`, `memory_addressable_after_pct`,
any per-population cacheability ratio, or any role-dependent claim
(`establish` / `repeat`, "memory earned by repetition").

✅ **`--compare` NOW REFUSES BOTH FILES** *(P1, 2026-08-16)*. It requires
`attribution.version >= 2`; these carry no attribution block at all, so they
read as v1 and the comparison exits 1 naming the reason. This marker is no
longer the only guard — but it stays, because a marker explains and a guard only
stops.

## WHAT MAY STILL BE QUOTED

Store-side and per-turn measurements, which never pass through `_reconcile`:
`turns_driven`, `entries_written`, `turn_failures`, recovery bubbles,
`latency_ms`, `resolution_rows`, `resolution_states`, PRODUCT non-binding,
absence of false collapse, `distinct_families_fragmented`, and non-English
resolution success.

Full account and the repair contract: `docs/CORPUS_ATTRIBUTION_DEFECT_0816.md`.
