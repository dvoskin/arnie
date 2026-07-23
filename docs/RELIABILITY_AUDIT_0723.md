# Arnie Reliability Audit — 2026-07-23

**Goal (Danny):** one cohesive smooth unit — refine interaction reliability and
function, no regression risk, guards at boundaries, deterministic logic wherever
possible.

## The architecture as of tonight (`58847b5`)

```
message ──► GATE (state + cheap regex; miss → main brain, always safe)
              │
              ▼
        STRUCTURED LOGGER (one small model call — the ONLY model decision
              │             on a food turn: log / update / ask / pass)
              ▼
        DETERMINISTIC WRITES (executor: enrichment ladder, dedup, meal slots)
              │   history > exact-USDA > OFF/web label > model estimate
              ▼
        DETERMINISTIC NUMBERS everywhere (say tokens ← committed DB;
              card, daily log, dashboards, receipts ← same rows)
```

What is already deterministic-by-construction: writes (impersonated tool calls),
every user-visible number (token fill + say contract enforcement), receipts
(per-call `_result`), day/completion state (`infer_today` off `DailyLog.date`),
board-resolved corrections (entry_id must be on the board), question-vs-item
separation (different JSON actions).

## Where nondeterminism remains (the refinement map)

| # | Surface | Today | Deterministic refinement | Risk | Priority |
|---|---------|-------|--------------------------|------|----------|
| 1 | **Workout logging** | main brain, freeform (the set-drop class) | **Structured workout turn** — same lane as food: logger emits set/exercise actions, board-aware ("same weight again" → append), deterministic set-append | Medium (new lane; kill-switched, bench first) | **P0** |
| 2 | Gate coverage | EN regex + 15-min thread state | `event=structured_gate` telemetry FIRST — measure miss-rate on live traffic, widen from data, not phrasing lists; RU tokens once measured | Low | **P0** (telemetry), P1 (widening) |
| 3 | Logger extraction fidelity | model JSON, say-contract enforced | Cross-check guard at the write boundary: every number the USER stated must appear in some item's amount (else demote to ask). Cheap, catches misreads like ⅓→0.5 class | Low | P1 |
| 4 | Water / weight quick-logs | main brain | Trivial structured actions (`log_water`, `log_body_weight`) in the same JSON — kills the last simple-log phantom class | Low | P1 |
| 5 | Web/OFF parse quality | regex over Tavily text | Structured parse (ask the search for JSON), confidence floor, cache label hits per product in `user_food_matches` (already cached — verify hit-rate telemetry) | Low | P1 |
| 6 | Enrichment latency | USDA/OFF prewarmed; **web serial per item** | Extend the prewarm fan-out to the web-label lane (bounded concurrency) — biggest wall-clock lever now that web fires more | Low | **P0** (latency) |
| 7 | Legacy narration numbers | day-guard verifies claimed totals | Already guarded; shrink surface by moving lanes (1,4) rather than adding guards | — | by-product |
| 8 | Photos | main brain + photo pipeline | Structured photo turn (logger over vision extraction) — after 1 | Medium | P2 |
| 9 | Deletes | main brain (by design) | Keep — destructive intent deserves full context; add confirm-before-bulk-delete card | Low | P2 |
| 10 | iOS mass-delete crash | unknown — needs crash log | Deterministic fix once symbolicated; suspect rapid state invalidation on N deletions | ? | **P0** (get log) |

## The no-regression method (what tonight proved works)

1. **Every behavior behind an env switch**, default = current behavior; flip after review.
2. **Live repro before ship** — each fix tonight was validated against the exact
   failing exchange from prod screenshots (pizza, birria, quest, bagel-thin).
3. **The benchmark suite is the guard-rail**: `scripts/bench_deep_session.py`
   (deep-session drops), `tests/test_no_drops_matrix.py`, `eval_multi_item`,
   161-file unit suite. A refinement that moves these backward doesn't ship.
4. **Telemetry before widening** — `event=structured_food`, `web_label_enrich`,
   `log_rescue`, `say_contract` lines make prod behavior observable; widen gates
   from measured misses, never from imagined phrasings.
5. **Boundary guards only** (write boundary, render boundary) — no mid-pipeline
   patch nets; the rip stays ripped.

## Accuracy policy (settled tonight)

- User-stated amounts/labels: **verbatim ground truth** — never rounded, never
  overridden.
- User's own history: authoritative.
- USDA: overrides **only on near-identical name match** (exact); otherwise it
  only derives fiber/sodium under the model's calories.
- OFF / web label: label-grade, trusted at `likely`+; branded items are
  logger-declared (`branded: true`) and always get the label lane when the DB
  match isn't exact.
- Estimates: bias high, venue-real portions for dense add-ons; round amounts
  only when the logger itself is estimating.
- Disagreement demotion: two independent reads disagreeing hard = low
  confidence → escalate to the web lane, keep the model's read meanwhile.

## Open items owed / blocked

- **Danny:** deploy `58847b5`; build `ios/hardening @ ccdaa99` (Release);
  Health → Arnie → Workouts toggle check; crash log for the mass-delete crash;
  widget v1 branch pushed from its session.
- **Next build sessions:** P0 items above (structured workout turn, web prewarm
  fan-out, gate telemetry), then P1.
