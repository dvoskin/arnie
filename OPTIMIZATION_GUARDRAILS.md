# Optimization Guardrails — deliberate behaviors that look like waste

Before "optimizing away" anything that looks redundant, run the process that
caught the linked-health fallback (2026-07-06): `git log -S "<snippet>"` for
the intent, check prod data for whether it still serves anyone, and write the
verdict down. Removal without that trail is how purposeful repairs get
regressed.

## Turn path

- **`db.refresh(user)` in `core/context_builder.py`** (f0f3207) — deliberate
  identity-map bypass so Whoop tokens written by another session are seen.
  Looks like a wasted query; is not.
- **Double `resolve_user` in `api/chat.py::_coached_reply`** when location is
  attached — re-read after `save_user_location` so the turn never sees a
  stale-cache row. Keep.
- **`get_today_log` duplicate tolerance** (`.first()` + order by id, never
  `scalar_one`) — legacy pre-constraint duplicate rows must not 500 a turn.
- **Stats-endpoint linked-health merge in `api/app.py`** — the turn-path twin
  was removed (data migrated 2026-07-06, verified dead), but this one ALSO
  backs the Whoop-token fallback and is off the hot path. Keep.
- **`CACHE_BREAK` split in `core/llm.py`** — the static prompt prefix carries
  `cache_control` and must stay BYTE-IDENTICAL across turns. Any "cleanup"
  that reorders static prompt sections or interpolates per-user data before
  the break silently kills the ~38k-token cache.
- **pytz** memoizes zone objects internally (measured 0.76µs/call) — do not
  add a cache layer on top.

## Proactive / scheduler

- **`_send_hook` bypasses `PROACTIVE_MESSAGING_ENABLED`** — conversation
  continuity (re-asking Arnie's own unanswered question) is deliberately not
  gated by the marketing-nudge kill switch. (It DOES respect the wake/sleep
  window as of 2026-07-06.)
- **Warmup burst ignores silence de-escalation** (`gate_decision` returns
  "send" inside `WARMUP_BURST_HOURS`) — early silence is normal; the burst is
  aggressive on purpose.
- **`day_report` is deterministic prose, no LLM** — cost decision, not a
  missing feature. Translation pass runs only for non-English users.
- **`LIVE_CONVERSATION_MINUTES = 25`** is intentionally short — it guards
  mid-thread interruption only; "already chatted since wake" is a separate
  gate on `late_morning_nolog`. Don't merge them.
- **`_eod_report_window` clamps to [20:30, 22:30]** even past a user's stored
  sleep_time — known, flagged in PROACTIVE_AUDIT.md recommendation #3; change
  it deliberately, not as a drive-by.

## Data / schema

- **`LOGGING_DAY_ROLLOVER_HOUR` default 0** (midnight) — the old 4am
  MacroFactor grace was deliberately retired (iOS shows calendar-date totals);
  env-tunable, don't hardcode either way.
- **Never delete a user row with `linked_to_user_id` set** — cross-platform
  link identities look like junk and are not (cleanup_users.py is guarded).
- **`db/database.py::_migrate` is SQLite-only** — every schema change needs a
  paired alembic migration or prod crashes on deploy.
- **Alembic revision ids are hand-minted hex — CHECK UNIQUENESS FIRST**
  (`grep "^revision" alembic/versions/*.py`). A duplicate id created a
  revision-graph cycle on 2026-07-06 and blocked deploys at the
  preDeployCommand.
- **Weight values are ALWAYS stored kg**; display-side converts (iOS
  `arnie.weightImperial`). Never store display units.

## Prompt layer

- **Bias-high food estimation** exists because Arnie systematically
  undercounts — but LABEL DATA (barcode/photographed label/user-typed label)
  is exempt, and every future bias-high reinforcement must restate that
  exemption in the same block or the stronger language wins (regressed once,
  2026-07-06).
- **Past-day logging requires the day reference in the CURRENT message** — an
  open backfill thread must not make new mentions retroactive.
- **[CURRENT TIME] known-tz branch says never ASK the time; unknown-tz branch
  says DO ask (for the city) when timing matters.** The asymmetry is the
  feature.
