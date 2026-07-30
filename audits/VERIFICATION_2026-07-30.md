# Post-deploy verification — 2026-07-30 ~16:05 UTC

Deploy of `7cea41e` confirmed in production. Evidence labels move as follows
(per the master directive §2 — nothing marked CLOSED without a production window).

## Structural — verified directly, label `DEPLOYED` + repairs confirmed

| Item | Query result |
|---|---|
| `alembic_version` | `pendinguniq001` — both new migrations ran via preDeploy |
| Indexes | all 3 live: `ix_conversation_logs_turn_id`, `uq_ledger_events_created_entry`, `uq_pending_open_per_user_kind` |
| `fitness`-domain created events | **0** (target 0 — re-domain/dedupe repairs applied) |
| Duplicate (domain, entry_id) created groups | **0** (target 0) |
| Stacked open pendings per (user, kind, purpose) | **0** (target 0) |
| Historic `turn_id` backfill | **2,241** rows joined (`ios:ios:%` as designed) |

Invariants **I2 and I3 are now enforced by the database in production** — a duplicate operation
or stacked pending is rejected at commit, not cleaned up after.

## Behavioural — label `DEPLOYED`, awaiting traffic for `CLOSED`

`7cea41e` contains everything from the 07-30 merge train: the gate fix (`15f961a`), `KEEP_AS_READ`,
`[TURN OBLIGATIONS]` + the five state blocks, the provenance fix, the build stamp, the one-writer
ledger fix, and the turn-id unification. One post-deploy turn exists so far (15:59, a no-reasoning
surface). Closure queries — run after ~24h of traffic:

1. Build stamp: `reasoning_json->'build'->>'sha'` non-null on chat turns; record the SHA.
2. Punctuation admits: 0 turns `owner=gate_regex` with emoji/smart-punct-only evidence.
3. New `ios:ios:%` turn_ids: 0; `conversation_logs ⋈ ledger_events ON turn_id` returns rows.
4. `ledger_dup_blocked` / stacked-pending IntegrityErrors: 0 in steady state (the guard firing
   means a duplicate writer returned).
5. `interpreter_none` re-baseline; premise confirmations settle in-lane, any language (the state
   blocks now ride every legacy pass).
6. Latency p50 vs 7.1s baseline.

Then the directive's 7-day audit window begins. Remaining implementation: Phase 3 remainder
(tool-result strings out of the visible reply), Phase 4 (ask/write join), Phase 5 (replay corpus),
Phase 6 (out-of-pipeline writers) — see the approved plan and `project-arnie-hardening-phases-0730`.

---

# Closure pass — attempted at +24h, run at **+2h07m**

**The window is not 24 hours and the closure pass cannot complete.** Read this first: the
pass was commissioned as a 24-hour post-deploy review, but production's own clock reads
`2026-07-30 18:09 UTC` — the deploy (16:00 UTC) is **two hours old, on the same calendar day**.
No 24-hour window exists yet to query.

Worse than the wall-clock gap is the traffic in it:

| | |
|---|---|
| Wall-clock since deploy | 2h 07m |
| Rows in `conversation_logs` since 16:00 UTC | **5** (4 chat turns + 1 proactive `day_report`) |
| Distinct users | **1** (`user_id=5`; the proactive row is `user_id=3`) |
| Span of actual chat traffic | **5m 10s** (17:20:12 → 17:25:22) |
| Latest turn in the database | 17:25:22 — no traffic in the 44 min since |

Four chat turns from one user over five minutes. Per the master directive §2 — *nothing is
marked CLOSED without the production window confirming it* — a sample this size confirms
nothing behavioural. The structural and mechanism checks close on deterministic evidence;
the rate- and distribution-based checks (5 and 6) do not, and **check 6 moves the wrong way**.

Method: read-only `psycopg` against prod. Gate assertions were run as behavioural tests
against the **exact** `raw_message` strings pulled from the database, not hand-typed copies —
and re-run a second time against a pristine `git archive 7cea41e` export in a scratch
directory, so the verdicts below are the *deployed* code's, independent of any working-tree
state. Both runs agree exactly.

## 1 · Build stamp — `CLOSED`

`reasoning_json->'build'->>'sha'` = **`7cea41e78f52`** on **4 of 4** chat turns. Flags carried
on every one: `STRUCTURED_FOOD=true`, `FOOD_GATE_MODEL=true`, `FOOD_GATE_OPEN=true`,
`FOOD_COMPOSER=true`, `FOOD_FAST_PATH=on`, `NUTRITION_RESOLVER_MODE=true`,
`TURN_COORDINATOR_MODE=new_observe`; `FOOD_ANSWER_APPLY` and `TURN_OBLIGATIONS` null.

The one unstamped row (`id=8322`, 16:59) is a `source_type='proactive'` `day_report`, outside
the check's scope — but see *New finding B*: proactive surfaces carry no `reasoning_json` at
all, so they are invisible to every audit query in this file.

## 2 · Gate fix `15f961a` — `CLOSED` (mechanism verified on production inputs)

**0 turns admitted on emoji or smart punctuation.** Both `interpreter_none` turns in the window
do contain U+2019, which is exactly the character that used to force admission — so this is the
right sample to test, even at n=2. Every window message run through the deployed gate:

| id | U+2019 | `_non_latin` (old → new) | `applies` | route recorded |
|---|---|---|---|---|
| 8323 | no | False → False | True | `structured_log` / `gate_regex` |
| 8324 | **yes** | **True → False** | True | `legacy` / `interpreter_none` / `gate_regex` |
| 8325 | **yes** | **True → False** | **False** (`no_food_shape`) | `legacy` / `interpreter_none` / `gate_regex` |
| 8326 | no | False → False | False (`destructive`) | `structured_commit` / `thread` |

`_non_latin` is False on both smart-punctuation turns, so typography contributed nothing to
either routing decision. 8324 was admitted on genuine food vocabulary ("dinner", "protein"),
which is the gate working as designed — not the punctuation defect. The three regressions
named in the commit message all now decline (`applies=False`): "Mark my Flat DB complete
coach 💪", "7 couldn't do more", "Call the tool mate don't forget". Russian meals still admit
(`Съел овсянку с бананом` → `_non_latin=True`, `applies=True`), so the RU lane is not collateral.

The punctuation escape is closed. It did **not**, however, reduce the `interpreter_none` bucket —
see check 5 and *New finding A*.

## 3 · Turn ↔ operation join — `CLOSED`

- New `turn_id LIKE 'ios:ios:%'` since 16:00: **0** (the double-prefix root fix holds).
- Historic backfill intact: **2,241** rows, unchanged.
- `conversation_logs ⋈ ledger_events ON turn_id` returns rows for post-deploy turns: **5 of 5**
  ledger events in the window carry a well-formed `ios:<UUID>` turn_id and every one joins.

| turn_id | events | detail |
|---|---|---|
| `ios:D27B3783…` (8323) | 2 | `created` food 2611, 2612 |
| `ios:335CF9DA…` (8326) | 3 | `created` food 2613; `deleted` 2611, 2612 |

§9 of the master audit ("narrated actions without tool calls — **not computable this window**")
is now computable. Turn 8326 is the proof end-to-end: "Had it and remove the oatmeal" →
one create and two deletes, all three joined to the turn that caused them, all from the single
writer `structured_food:food_interpreter_v2`.

## 4 · DB guards — ledger side `CLOSED`; pending side **NOT EXERCISED**

Both partial unique indexes confirmed live in `pg_indexes`:

- `uq_ledger_events_created_entry` on `(domain, entry_id) WHERE event_type='created' AND entry_id IS NOT NULL`
- `uq_pending_open_per_user_kind` on `(user_id, kind, COALESCE(item_referenced,'')) WHERE answered_at IS NULL`

Repo-wide re-check: **0** duplicate `(domain, entry_id)` created groups, **0** stacked open
pendings. The 3 creates in the window are distinct entry_ids (2611/2612/2613) with no
duplicate writer.

**The pending guard got no post-deploy exercise: 0 rows in `pending_questions` since 16:00.**
Its "0 stacked" result is therefore vacuous for this window — it restates the pre-deploy repair,
not the guard holding under live traffic. `ledger_dup_blocked` is a log line and is not
queryable from the database, as anticipated; absence of DB duplicates is consistent with it
never firing, but is not direct evidence either way.

## 5 · `interpreter_none` re-baseline — **NOT CLOSED** (n=4)

| Window | `interpreter_none` | Rate |
|---|---|---|
| Pre-deploy 18h (master audit window) | 26 / 57 | 45.6% |
| Post-deploy | **2 / 4** | **50.0%** |

The rate did not improve; with n=4 it cannot be said to have moved at all. One in four turns
would swing this figure 25 points. **No conclusion is available** — this needs the real 24h.

Sub-items:

- **Premise confirmations settle in-lane — one positive datapoint.** Turn 8326, "Had it and
  remove the oatmeal", resolved "it" to the chicken parm wrap discussed in 8325 and settled
  in `structured_commit` (`owner=thread`), logging the wrap and deleting both oatmeal rows.
  That is the `[TURN OBLIGATIONS]` / state-block behaviour working on a real turn.
- **ANY-language is untested.** All four turns are English. The RU premise-confirmation
  blindspot from §8 of the master audit remains unobserved in production.
- **`KEEP_AS_READ` did not fire** and remains unobservable from the database, as the brief
  anticipated. No lane outcome in the window implies it.

## 6 · Latency — **NOT CLOSED · REGRESSION FLAG**

| | p50 | p90 | n |
|---|---|---|---|
| Pre-deploy 18h baseline | 7,159 ms | 11,484 ms | 57 |
| Post-deploy window | **11,032 ms** | **13,606 ms** | 4 |
| Change | **+54%** | **+18%** | |

Individual durations: 9,058 · 10,421 · 11,643 · 14,447 ms. **All four turns exceeded the
pre-deploy p50, and the fastest (9.06s) is above it.** Under a no-change null that is a 1-in-16
outcome — weak on its own, but it points the wrong way and it is the second checked item that
the thin window cannot resolve.

Two of the four turns are `interpreter_none` at 14.4s and 10.4s: the structural waste §20–23
identified — a full interpreter pass that produces nothing — is **still being paid in production**.
The gate fix removed the punctuation route into that waste but not the waste itself.

**This item must not be closed, and the deploy should not be called latency-neutral.** Re-measure
at a genuine 24h before drawing any conclusion.

## New findings

**A · `route.owner` is not a faithful per-turn record (NEW, open).** Turn 8325 recorded
`owner=gate_regex`, but its exact production string returns `applies=False` /
`decline_reason='no_food_shape'` from the deployed code. `claim_route` is *first-claim-wins
per trace*, and the only two `gate_regex` claim sites in the repo (`core/food_turn.py:528,531`)
are both unreachable for that text while `FOOD_GATE_MODEL=true` — line 528 needs the model
gate off, line 531 needs `applies()` True. So the recorded owner cannot be produced by that
turn's own text. Trace leakage from the preceding turn is contradicted by 8326 correctly
claiming `thread`. This matters beyond one row: **§5–8 of the master audit classify 79 turns by
`owner`, and check 2 above is itself defined in terms of `owner`.** Needs its own investigation
before owner-based counts are trusted again. Not root-caused here.

**B · Proactive surfaces are invisible to the audit.** `id=8322` (`day_report`, `source_type=
'proactive'`) carries no `reasoning_json` — no route, no build stamp, no duration. Proactive
sends are a real write path to the user and currently sit outside every telemetry query in this
document.

## Status after this pass

| Check | Label |
|---|---|
| 1 · Build stamp | `CLOSED` — `7cea41e78f52` |
| 2 · Gate fix `15f961a` | `CLOSED` — mechanism verified on exact prod strings |
| 3 · Turn ↔ operation join | `CLOSED` |
| 4 · Ledger dup guard | `CLOSED` |
| 4 · Pending stack guard | **NOT EXERCISED** — 0 pendings in window |
| 5 · `interpreter_none` re-baseline | **NOT CLOSED** — n=4, rate flat/worse |
| 6 · Latency | **NOT CLOSED — REGRESSION FLAG** (+54% p50) |

**The closure pass is not complete and no behavioural item has been relabelled on this
evidence.** Re-run checks 4 (pending), 5 and 6 against a real 24-hour window — earliest
`2026-07-31 16:00 UTC` — before the directive's 7-day audit window is considered started.
Findings A and B are new work, neither root-caused.

## Not merged to main — worktree contention

This section was committed to `dvoskin/food-lane-rootfix` but **not merged**, because the
merge precondition (clean working tree) does not hold. During this pass the worktree moved
under the session: `HEAD` advanced `1d24164 → 352ce92`, and six tracked files plus two
untracked ones (`core/food_pipeline.py`, `core/food_turn.py`, `handlers/tool_executor.py`,
`skills/nutrition/{staging,answer_application,ask_candidates}.py`,
`tests/test_the_pipeline_produces_a_priceable_item.py`) are uncommitted work belonging to
**another session in progress**. Local `main` is at `47e290d`.

Only `audits/VERIFICATION_2026-07-30.md` was committed, by pathspec; nothing else was
touched, staged, or stashed. The full suite was green (6,216 tests, exit 0) but that run
included the other session's uncommitted changes, so it is not a clean signal for this
branch tip either. Whoever owns that work should do the merge.
