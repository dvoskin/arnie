# Backend Performance Audit — 2026-07-06

Read-only sweep of the per-turn hot path, scheduler, LLM call patterns, and
prod index reality (checked live via pg_indexes). Baseline: a non-tool turn
costs ~12 DB queries + 1 LLM call; a tool turn ~18-22 queries + 2 LLM calls.
No N+1 in the eager-loading (selectinload used correctly). The wins were
indexes, one blocking call, and one redundant loop.

## Shipped in this pass

1. **Hot-path indexes** (alembic `0a1b2c3d4e5f` + matching model `Index()`s —
   prod had NONE of these; Postgres does not auto-index FK columns):
   - `conversation_logs(user_id, timestamp)` — every turn's history window,
     scheduler recency/silence gates, proactive routing.
   - `body_metrics(user_id, timestamp)` — weight trend read every context build.
   - `food_entries(daily_log_id)` / `exercise_entries(daily_log_id)` — day-view joins.
   - `pending_questions(user_id, answered_at)` — open-question scan per tick.
   Tables are small today (~5k rows max) so this is growth insurance, not a
   current fire — but conversation_logs is the fastest-growing table and it's
   read on literally every interaction.

2. **Reverse-geocode unblocked** (api/chat.py): the city lookup was network
   I/O awaited INSIDE the per-user turn lock — a slow geocoder stalled the
   coaching reply 100-500ms and queued the user's next messages. Coords now
   save immediately; city backfills via fire-and-forget task.

3. **Linked-user health fetch batched** (core/context_builder.py): was one
   query per linked identity when the canonical had no snapshots; now a single
   `user_id IN (...)` query.

## Shipped in the second pass (same day)

4. **Legacy linked-health fallback REMOVED from the turn path** — investigated
   whether it was intentional: it was a 2026-06-03 repair (4f72354) for
   snapshots that synced to the wrong (linked) user_id before that fix. Prod
   held 49 such rows, ALL shadowed by fresh canonical data — the fallback
   could never fire, yet cost every snapshot-less user one query per turn.
   The 6 rows covering dates canonical lacked were migrated to canonical
   (backup in session scratchpad), the rest parked; fallback deleted. The
   stats-endpoint twin (api/app.py) stays — it also serves the Whoop-token
   check and is off the hot path.

5. **Scheduler batch loading** — `batch_send_targets` (2 set queries, window
   function for newest-platform) + `batch_today_logs` (1 eager-loaded set
   query, per-user local dates computed in memory) replace 3 per-user queries
   per tick in `_run_reminders`, and the hooks sweep shares the routing batch.
   Priority logic factored into `_pick_send_target` so the batch and single
   paths cannot drift; equivalence pinned in tests/test_scheduler_batching.py.

6. **pytz "cache" item CLOSED as moot** — measured: `pytz.timezone()` memoizes
   internally (0.76µs/call, identity-equal objects). Do not "optimize" this.

## Deferred (ordered by value; none currently user-visible at beta scale)

1. **Attribute-store cache** — `get_attributes_for_context` queries + ranks on
   every turn; cache per-user, invalidate on `store_attribute`/`update_profile`.
   Held back deliberately: stale attributes would silently skew coaching, and
   the invalidation surface (attribute store, profile tool, nightly
   consolidation) needs its own careful pass.
2. **Prompt caching depth** — `cache_control` covers only the static system
   prompt. The ~8k-token dynamic context re-processes every turn. Restructure
   context into (slow-changing profile/attribute block | fast-changing today
   block) and move the cache break so the slow half caches too. Meaningful
   token-cost lever at scale; held back because context reordering changes
   model behavior (small-iterations lesson).
3. **EOD/day-report window queries** — `_eod_report_window` re-derives the
   14-day dinner median per user per tick during the report hour; cache per day.

## Next-level ideas (product intelligence, not perf)

- **Barcode → OpenFoodFacts cross-check**: the iOS scan message could carry
  package size + servings-per-container (data OFF already returns), removing
  the single-vs-multi-serving inference entirely.
- **Photo→product grounding**: when a photo is PACKAGED and brand text is
  legible, run the same OpenFoodFacts/label lookup the barcode path uses —
  photos and scans converge on one ground-truth pipeline.
- **Streaming the coach reply** on iOS chat (the ws path exists) for perceived
  latency — the 2-LLM-call tool turns feel slow mainly at the tail.
- **Per-user food memory embeddings** for "the usual" recall — current
  food-memory is string-match; embedding recall would nail "same shake as
  always" phrasing variants.
