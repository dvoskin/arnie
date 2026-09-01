# BULK PRELOAD — SELECTION PROTOCOL

**Frozen 2026-09-01, before any preload list exists.** That ordering is the
point: a protocol written after seeing candidate lists can be shaped, however
unconsciously, by what those lists contain.

---

## THE RULE

> **The bulk preload universe MUST be selected from external frequency or market
> coverage criteria established independently of Arnie's evaluation corpus. The
> frozen 222-meal population MAY be used only afterward, to measure impact.
> It may NEVER be used to choose what gets loaded.**

The frozen 222 stays **sealed** until the preload is committed.

## WHY THIS IS A RULE AND NOT A PREFERENCE

This project has already made the mistake once, at small scale. On 2026-08-31 a
"Phase 1B work order" enumerated 54 identities **drawn from the 68 exact-mass
meals inside the frozen corpus** and offered them as the thing to build. A
producer that sourced those 54 would have moved 9.0% and generalised to nothing:
the number would have measured its own inputs.

At a thousand times the scale, the same mistake produces a number that looks
like a triumph and means nothing. **A benchmark you selected against is not a
benchmark.**

## WHAT THE RESULT HAS TO BE ABLE TO SAY

> We loaded N foods selected independently of the benchmark, then ownership on
> the untouched 222-meal population moved 9.0% → X%.

That sentence is only available if selection never consulted the benchmark. It
cannot be recovered afterwards by argument, and it cannot be patched by
disclosure — once the corpus informed the list, no later analysis restores the
claim.

## ADMISSIBLE SELECTION SOURCES

Each is independent of the evaluation corpus:

| source | basis |
|---|---|
| USDA / common-food frequency | broad food-category coverage, published frequency |
| grocery & product datasets | high-volume retail populations |
| U.S. restaurant chains | ranked by sales or traffic, externally published |
| common international foods | externally defined, not derived from our traffic mix |
| production frequency | **a SEPARATE time window or user population** from the corpus |
| OFF / manufacturer SKUs | filtered by EVIDENCE QUALITY, never by benchmark presence |

⛔ **On the production-frequency source.** Real demand weighting is legitimate
and valuable, but the frozen 222 was itself drawn from production. Using
overlapping traffic reintroduces the contamination through the back door. The
window or population must be disjoint, and the disjointness must be stated in
the preload manifest — not assumed.

⛔ **On the SKU source.** "Filtered by evidence quality" means the filter reads
the PROVIDER RECORD — does it carry a nutrition panel, a serving basis, a
resolvable SKU. It must never read whether the product appears in our data.

## INADMISSIBLE, EXPLICITLY

- any query against the frozen 222, its identities, or its decline buckets
- any list derived from `data/phase1b_workorder_*.json` (that file is an
  instrument and is corpus-derived by construction)
- "foods we noticed failing" from canary or corpus analysis
- ⭐ **`SEED` in `scripts/build_pricing_artifact.py`** — 21 entities whose own
  generator records that *"seems likely someone will log this" is NOT a
  criterion*. It is bootstrap data, not a selection method, and expanding it by
  intuition is the original defect at larger scale.

## THE MANIFEST

Every preload batch commits a manifest naming, per source: the source, its
version or retrieval date, the selection criterion, the count admitted, and —
for production-derived frequency — the window and population, with its
disjointness from the corpus stated explicitly.

A batch whose manifest cannot name its criterion does not load.

## WHAT DOES NOT CHANGE

Preload runs through the **same** `AcquiredEvidence` contract as runtime
acquisition: identity qualification, authority grade, nutrition basis,
provenance, `AcquiredEvidenceRecord`. No privileged path, no second food
database, no bypass of `decide()`. Bulk changes WHICH foods are established and
WHEN — never on what terms.

Authority is not relaxed to raise a count. A preload entry that cannot establish
source authority is not loaded; it is refused, by name, and counted.
