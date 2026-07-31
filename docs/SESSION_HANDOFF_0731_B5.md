# Handoff — 2026-07-31 (B5 latency pass)

Third pass this session, after B7 (security) and B6 (voice). Read this, then the
updated scorecard §7.

Everything below was proven by a test, not remembered.

## Where the work is

Branch `dvoskin/b5-latency-budgets` @ `472e8e6`, cut from `origin/main` @
`50ba640`. **Committed locally, not pushed, not deployed.** Independent of the
B6/B7 branches (different code, different scorecard section → merge cleanly).
Full shuffled suite green at the tip (6407 tests, exit 0).

```bash
pytest tests/test_request_trace_ambient.py tests/test_latency_report.py -q
python scripts/latency_report.py --hours 168      # needs a prod DATABASE_URL
```

## What §7 asked, and what each answer is

§7 was UNKNOWN: "no stage timings exist outside quick-log, no budgets are
enforced, and the +54% p50 regression flagged 2026-07-30 was never explained."
The machinery it needed already half-existed — the `turn_metrics` table, the
`RequestTrace`, and `scripts/latency_report.py` — but only `quick_log` wrote to
the table, so the MAIN conversational turn (where the regression lived) was
invisible in the one dataset that outlives the logs. That is the gap this pass
closed.

**Main turns now write a metric.** `core/conversation.run_turn` — the thin
wrapper at the turn boundary — opens ONE `RequestTrace` and, in a `finally` that
every return path runs, writes a `turn_metrics` row: `command` (`turn` or
`turn:log`), `channel`, `outcome`, `total_ms`, `build_sha`, `turn_id`, and a
per-stage breakdown. So "did main-turn p50 regress after that deploy" is finally
a query, not a shrug.

**The breakdown is ambient.** Threading a trace through a 3,000-line branch
would be twenty signatures to keep in step. Instead `run_turn` sets the trace in
a contextvar (`core/request_trace.active`), and the leaves that do the real work
time themselves into it: `core/llm.chat` and `chat_follow_up` record `llm`,
`handlers/tool_executor.execute_tool_calls` records `tools`. Duplicate stages
SUM, so three model calls in one turn report one `llm` figure — the total time
in the model, which is the number worth budgeting. Off a traced turn (quick-log,
proactive, tests) `timed()` is a pure no-op, so nothing else changed.

**Telemetry can't corrupt the turn.** The row is written by
`persist_isolated()` on a FRESH session, never the turn's — so a metric can
neither commit half of an errored turn nor be rolled back with it. It never
raises; a telemetry row must not break the write it describes.

**Budgets are scored.** `latency_report.py` now scores p95 against
`BUDGET_P95_MS` for `turn` (6s) and `turn:log` (5s) as well as the quick-log
routes (2.5s). The pure `summarize()` was split out of `main()` so the
percentile + pass/fail logic is tested without a Postgres.

## What is still UNKNOWN (honest)

**The numbers.** The report reads `DATABASE_URL`; a clean checkout has none, and
production has no rows through the new writer until this deploys. So the +54%
regression is now MEASURABLE but still UNexplained — there is no data yet. After
deploy, give it a week and run `python scripts/latency_report.py --hours 168`.

**The turn budgets are PROVISIONAL.** 6s / 5s are set at the runtime deadline,
so a PASS today only means "not hitting the hard cap", not "fast". Calibrate
down against the first week of real p95s.

## Watch-outs for the reviewer

* The 6s hard cap (`core/deadline`) is UNCHANGED. B5 adds measurement, not a
  second cap — `run_turn`'s `except/raise` preserves the exact existing
  propagation, including `DeadlineExceeded`.
* `persist_isolated` writes on every turn. In tests the global engine has no
  `turn_metrics` table, so the write fails and is swallowed (a captured WARNING,
  no test failure). In prod it is a single-row insert on a pooled connection —
  the table was designed "cheap enough to write on every turn".
* The write happens in `run_turn`'s `finally`, i.e. before the handler sends —
  ~a few ms on a 1-6s turn. If that ever matters, move it to a held-reference
  background task; it was kept inline for the same reason `RequestTrace.persist`
  is explicit (a fire-and-forget failure nobody sees is worse than a few ms).

## Next, in order

1. **B2** — 57 of 60 user-visible mutations off the contract;
   `mutation_inventory.py` ranks them. NOTE: overlaps the running "capability
   tokens out of URLs" session on the `api/` mutation handlers — coordinate or
   sequence to avoid conflicts.
2. **B9/B10** — backup restore + rollback rehearsal (ops, needs Danny).
3. **B1** — deploy. Three branches (B5/B6/B7) now sit undeployed behind it.

## Files touched

New: `tests/test_request_trace_ambient.py`, `tests/test_latency_report.py`, this
handoff.
Changed: `core/request_trace.py` (contextvar + `active`/`timed`/`time_stage`,
stage accumulation, `persist_isolated`), `core/conversation.py` (the `run_turn`
wrapper), `core/llm.py` (`@time_stage("llm")` on chat/chat_follow_up),
`handlers/tool_executor.py` (`@time_stage("tools")` on execute_tool_calls),
`scripts/latency_report.py` (turn budgets + testable `summarize`),
`docs/MARKET_READINESS_SCORECARD.md` (§7 + B5 row).
