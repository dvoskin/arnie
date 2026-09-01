# REAL-TURN ACQUISITION CANARY — FROZEN

**2026-09-01 · production · Render · user 26 · ambient `EvidenceContext`**
Deployed `834e727`. Gate passed, therefore rates are publishable.

## COLLISION GATE (precondition, not a metric)

`sweet potato` **5 candidates in-turn**, `pork tenderloin` **9**. Under the
single-flight collision an in-turn acquisition could never exceed
`_QUALIFY_BATCH = 3`, so this proves multiple qualification batches genuinely
ran under ambient context. Without it a broken build still looks FAST — reusing
batch one's assessment is quick — and the canary would certify the defect it
exists to detect.

## RESULT

```
9 logged · 7 canonical same-turn · 0 deferred · 0 provenance contradictions
7/7 arithmetically correct against the evidence each names
2 refusals, both EXPECTED (branded SKU · nonsense stew)

latency, turns only (n=12):  min 5.9s  p50 8.1s  p90 13.2s  p95 18.8s
```

| entry | food | evidence | owner |
|---|---|---|---|
| 3081 | Sweet potato 250 g → 190.0 kcal | `usda:168484` | canonical:create |
| 3082 | Brown rice 200 g → 294.0 kcal | `usda:173263` | canonical:create |
| 3083 | Cottage cheese 200 g → 144.0 kcal | `usda:173417` | canonical:create |
| 3084 | Pork tenderloin 170 g → 185.0 kcal | `usda:168249` | canonical:create |
| 3085 | Lentils 250 g → 285.0 kcal | `usda:175254` | canonical:create |
| 3086 | Fage Total 0% 170 g → 104.0 kcal | `usda:330137` | canonical:create |
| 3088 | Buckwheat 150 g → 138.0 kcal | `usda:170686` | canonical:create |
| 3087 | Quest Bar 60 g | — | legacy (expected) |
| 3089 | Grandmother's stew 300 g | — | legacy (expected) |

⚠ **`total_ms` is TOTAL TURN time**, of which acquisition is one component. The
schema carries no separable acquisition timing. p95 18.8 s exceeds the 12 s
acquisition budget; zero deferrals means acquisition itself stayed inside it.

## THE LANGUAGE / COMPOSITION SPLIT — retest, 2026-09-01

⛔ **RETRACTED: "Russian foods require a multilingual provider."** That came from
a producer canary that fed RAW Russian to USDA, bypassing the interpreter. In a
real turn the interpreter normalises first: `гречка` → *"Buckwheat, cooked"* →
acquired canonically. Third instrument-vs-subject mismatch of the session.

The real split, probed under multiple English name variants each:

| | probe | verdict |
|---|---|---|
| **LANGUAGE** — surface form maps to a known canonical food | `творог`: `farmer cheese` ✗ · `quark` ✗ · **`cottage cheese, dry curd` ✅ `usda:172181`** | the record EXISTS; only the descriptor was wrong. Interpreter normalisation target matters. |
| **COMPOSITION** — no single authoritative row captures the meal | `шакшука` 0/3 · `плов` 0/3 · `окрошка` 0/3 · `сырники` 0/3 — including plain-English descriptive forms | genuine absence. Belongs to composition/decomposition, NOT to a provider layer. |

**Consequence: do not build a multilingual provider layer.** It would not have
fixed the composite dishes and was not needed for the language cases.

## OPEN, EXPLICITLY NOT BLOCKING PHASE 2A

- `ACQUIRE_DEADLINE_EXCEEDED` vs `PROVIDER_UNAVAILABLE` conflated (measurement quality)
- nonsense strings burn the full budget — needs an UPSTREAM identity signal, never a string heuristic
- acquisition timing not separable from turn timing
- ⭐ **Fage resolved to a GENERIC** (`Yogurt, Greek, plain, nonfat`), not the SKU.
  Correct here. Becomes a branded-provider INVARIANT: *a generic substitute is
  admissible only where the SKU-specific formulation is not materially
  different.* Not a reason to distrust the generic lane.

## FROZEN

Acquisition tuning stops here. The canary has answered the core question. Next
is Phase 2A bulk preload under `docs/BULK_PRELOAD_SELECTION_PROTOCOL.md`, then
the first unsealing of the frozen 222.
