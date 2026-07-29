# Session handoff — food lane root-cause work, 2026-07-29

**Branch:** `dvoskin/food-lane-rootfix` (pushed) · **Base:** `origin/main` @ `bdd5a52`
**Plan:** [`audits/FOOD_LANE_PLAN_2026-07-29.md`](../audits/FOOD_LANE_PLAN_2026-07-29.md) — read this
first; it carries the evidence for every item below.

Full suite green at every commit (`python -m pytest -q`, 0 failures).

---

## Where to work

The primary checkout `/Users/danielvoskin/Code Learn/arnie` is on `feat/coach-card-microviz`, **a
month stale (merge-base 2026-06-25) and dirty**. Do not work there.

This branch is checked out at:
`/Users/danielvoskin/Code Learn/arnie/.claude/worktrees/arnie-nutrition-lane-audit-c5debc`

Interpreter: `/Users/danielvoskin/Code Learn/arnie/.venv/bin/python` (the system `python3` has no
`psycopg`).

**Another session is active in this lane** — see `audits/ARCHITECTURE_AUDIT_2026-07-29.md` (routing,
latency, voice, reachability). Causes B, C, E, F, G are untouched by it; **A is adjacent to its
S1/S2** — confirm ownership before taking A. `git fetch` before starting anything.

---

## Done (8 commits)

| Commit | What |
|---|---|
| `f182b6e` | Route + `legacy_reason` + `route_owner` persisted on `reasoning_json`. The trace was a log line, so escapes could only be asked of Render logs before rotation; now it is a DB query. |
| `a82ad50` | Corrections report what actually changed — outcome read from the row before/after, not inferred from which keys the interpreter sent. Includes the card reading `quantity`/name from the committed row, `_reresolved` no longer gated on a trace artifact, and **B.0**. |
| `efe0362` | A correction that moved no number discloses it — and the disclosure channel is fixed (see B.0). |
| `c20885e` | `_log_call` carries `date`; a day the user names reaches the write. **The only data-loss case in the window.** |
| `32dcb36` | One pending record per open question; the chase moves to the record that can receive the answer. |
| `b0f8570`, `a8bc39b`, `0beefa3` | The plan, plus two corrections to it. |

### Three things found while implementing, not while reading

1. **B.0 — `fc682d5`'s unpriced disclosure has never fired.** `stash()` writes to `CALL_CTX` and
   documents that the command input is never written; `ok_tool_calls()` returns `{name, input:
   raw_input}`; the reply read the key off that raw input. Its test asserts the executor's **source
   text** contains the string, so a grep stood in for the behaviour.
   **Open follow-up:** sweep for any other disclosure reading execution state off `raw_input`.
2. **B.1 — re-dating was complete except `_log_call`.** The tool schema, `_resolve_log`, `_update_call`
   and the receipt step all existed. One builder dropped the field, so the lane could re-date an
   existing row and never write a new one to the named day.
3. **G — the 23:07 banana turn recorded only a `conversation_hook`, no food ask.** That is *why* the
   next turn went cold and kept the invented banana. The duplicate was not merely noise; on that turn
   it was the only record.

---

## Next: cause A — the ask carries the item's resolution

**Start here.** Everything left leans on it:

- **F must not ship before A.** Without thread state a better matcher produces a *more confident*
  wrong answer — that is the sopressata → "Dollar pizza slices" leak.
- **C's residue** ("Thanks" wrote two foods) needs the staged store A creates.
- The 14:03 production turn is A's case.

The pending payload persists text, not the resolved priced item, so the answering turn re-interprets
and re-enriches from zero. `fd2266a` put `response_schema`/`options`/`staged_item_id` on the payload;
the **resolution** is still absent, which is why only `parse_command` is reachable.

Shape: persist identity (fdc_id / OFF code / label), per-100g basis, the portion candidates the
question chooses between, and the assumptions already made. The answering turn *applies* the answer to
that stored resolution as a pure function, re-resolving only if identity changes.

Second half: **segmentation runs before resolution can reject a split** — "cavendish and Harvey"
became a banana and a candy. If a segment does not resolve, try the unsplit span before asking.

Related and already half-fixed: expiry works correctly, but expiring the *question* discards facts the
*thread* established. With `32dcb36`, a chase refreshes `last_asked_at` and keeps the question inside
its TTL — so A now has a live pending to apply an answer to rather than a cold turn.

Then, in order: **F** (staged: write invariants + sweep → `frequent_foods` returns the distribution →
materiality over identity spread → scored identity claim → split-prior ask), **E** (parallelisable),
**C**, and **D** as a re-measure only.

---

## Verification

```bash
python -m pytest -q
```
Baseline 0 failures. `tests/conftest.py` is hermetic since `7643816` — before it, a developer `.env`
produced 21–34 *stable* failures, which is what made audit findings E1–E3 measurement error.

```bash
python scripts/eval_food_matrix.py
```
Live-model battery; keep green, add a case per defect.

**Write behavioural tests, not source greps.** B.0 is the standing example of what a source-text
assertion hides.

### The production trace is the acceptance test

The scoreboard is in the plan's §7. Re-pull it the same way — prod URL is the **second**
`DATABASE_URL` in `arnie/.env`, raw `psycopg` (the async engine hangs), 18-hour window over
`conversation_logs`, `ledger_events`, `food_entries`, `pending_questions`, `user_food_matches`.
`conversation_logs.reasoning_json` now carries `duration_ms` **and** `route`, so latency and lane
ownership are both queryable without log access.

Deploys are manual, from an isolated worktree. Nothing here is deployed.
