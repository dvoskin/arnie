# Handoff — 2026-07-31 (proactive cadence budget → delivery_attempts)

A small, contained fix that closes the last open question the 2026-07-31 handoff
left on proactive delivery, and with it blocker B3. Read this, then scorecard §9.

## Where the work is

Branch `dvoskin/proactive-budget-delivery-attempts`, cut from `origin/main` @
`50ba640`. **Committed locally, not pushed, not deployed.** Independent of the
B5/B6/B7 branches and of the two running chip sessions (touches one function in
`scheduler/proactive_scheduler.py`, a different region than the `_CITY_NUDGES`
the joke-emoji chip edits). Full shuffled suite green at the tip.

## The bug

`_within_proactive_budget` — the 24h proactive cadence gate — counted
`conversation_logs` proactive rows. `DeliveryAttempt` was built specifically to
end that ambiguity (its own model docstring: a proactive `conversation_logs` row
once meant "we reached the send function", covering a delivered push and a total
failure alike, so **a user whose pushes all FAIL was rate-limited into silence
as though they were being reached**). The delivery table shipped; the budget was
never migrated onto it. It read the right answer only by accident — those rows
are now written on acceptance — which couples the gate to an unrelated write's
timing. The 07-31 handoff flagged exactly this: "it reads the wrong table for
the right answer and should query `delivery_attempts`."

## The fix

`_within_proactive_budget` now counts `delivery_attempts` with a
`core.delivery.TERMINAL_SUCCESS` status (accepted / delivered) in the rolling
24h, not `conversation_logs`. `delivery_attempts` is written only by the
proactive path (`_record_delivery`), so no proactive filter is needed. Only
sends that REACHED the user count against cadence; failing delivery can no
longer silence a user. `_throttle_decision` (the pure cap/gap verdict) is
unchanged. Also hardened the SQLite datetime-as-string case the raw query shared
with `_user_spoke_recently` (it parses; this now does too).

`test_proactive_budget_counts_deliveries.py` pins it — previously NO test
covered this function's query (the delivery tests monkeypatch the budget out):
failed deliveries don't count, a recent accepted one trips the gap, three
accepted ones hit the daily cap, conversation_logs no longer move the budget, a
30h-old delivery is outside the window.

## Not touched (deliberately)

`_user_spoke_recently` still reads `conversation_logs` for `source_type !=
'proactive'` — that is the USER's own activity, correctly sourced. This fix is
only the proactive-send cadence.

## Files touched

New: `tests/test_proactive_budget_counts_deliveries.py`, this handoff.
Changed: `scheduler/proactive_scheduler.py` (`_within_proactive_budget`),
`docs/MARKET_READINESS_SCORECARD.md` (§9 + B3 row).
