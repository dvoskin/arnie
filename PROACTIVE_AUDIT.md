# Proactive Messaging Audit — 2026-07-06

Triggered by three prod reports: Gi still getting Telegram nudges after moving
to iOS, Danny's 10:00 AM "You up?" thirty minutes after a live conversation,
and a 1:45 AM "Still nothing in the log for today" follow-up. Audited the full
pipeline: scheduler loop, eligibility gates, routing, pacing, and APNs banners.

## Confirmed defects (fixed on this branch)

### 1. Routing ignored iOS entirely
`_platform_of` only knew `im:` vs Telegram — an `ios:`/`apple:` identity
classified as **telegram**. `resolve_send_target` routed by `channel_preference`
alone, so a stale pref pinned a user to their old platform forever. Gi (user 5,
canonical iMessage row, pref `telegram` from June) linked the iOS app on 7/3,
chatted there daily, and every nudge still went to Telegram — where he may not
even look anymore.

**Fix:** routing now follows the conversation — the platform of the user's most
recent real message wins (proactive sends and the `[start]` seed don't count),
then `channel_preference` (new/quiet users), then canonical. Gi self-heals on
deploy; so does everyone who migrates platforms later. (`db/queries.py`)

### 2. Conversation-hook re-asks bypassed the sleep window
`_run_conversation_hooks` ran live-convo + 90-min cool-off gates but **never
checked wake/sleep** — by design ("conversation continuity"), but in practice it
buzzed Danny's phone at 1:45 AM. **Fix:** hooks now respect the same clamped
9am–9pm window as timed nudges. (`scheduler/proactive_scheduler.py`)

### 3. "You up?" fired mid-morning-conversation
`late_morning_nolog` (10:00–10:30) checks food entries only; the 25-minute
live-conversation window can't catch "said good morning at 9:09, logged weight
at 9:30, slot ticked at 10:00." **Fix:** the slot now skips when the user has
sent any message since wake — someone who already talked this morning is
obviously up; midday pacing covers the food gap. (`scheduler/proactive_scheduler.py`)

### 4. Banner polish
- Short coach openers ("You up?", "End of day check, Danny.") are now the push
  **title** with the substance bubble as body, instead of a generic category
  label + opener-as-body.
- Markdown is stripped — banners were showing literal `**1,482/2,164 cal**`.

## Ratings of what's already there (no change needed)

- **Frequency tiers** (`none/light/moderate/heavy` → slot allowlists) — sound
  design, correctly a narrowing filter after the hard opt-out.
- **Silence de-escalation** (`gate_decision`: 2 ignored → consolidate,
  3+ → suppress) — good; warmup burst exemption is deliberate.
- **EOD report adaptive timing** (median dinner + 30 min, clamped 20:30–22:30) —
  nice touch, keep.
- **Per-sweep canonical dedupe + 20-min idempotency text guard** in hooks — keep.
- **Dead APNs token revocation** on BadDeviceToken/410 — correct.

## Recommendations (not implemented — next passes)

1. **Repetitive openers.** "You up?" (7/4 and 7/6), "Hop on the scale" /
   "What's your weight this morning?" every day at 13:30 — the LLM nudges are
   slot-prompted into sameness. Feed `recent_proactive` more aggressively into
   the prompts with an explicit "never reuse an opener from the last 3 days"
   instruction, or rotate slot personas. The de-repetition pattern from the
   coach-card work (banked-win memory) would port well.
2. **Live-window asymmetry.** 25 minutes is right for interrupting mid-thread,
   but "just finished a conversation" deserves a longer shadow (60–90 min) for
   low-information slots (`late_morning_nolog`, generic check-ins) while data
   slots (EOD report) can keep 25. The since-wake gate (#3) covers the worst
   case for now.
3. **Quiet hours vs. hard window.** The 9pm hard sleep clamp saved Danny from
   worse — but `day_report` at "hour == report_h" uses the EOD window (20:30–
   22:30) which can exceed a user's stored 21:00 sleep. Consider clamping the
   EOD slide to the user's sleep time too. (Danny's "End of day check" lands
   0:00 UTC = 8 PM ET — inside, fine, but a sleep_time=21:30 user could get
   a 22:30 report.)
4. **APNs deep-link payload.** Banner taps open the app cold; add
   `payload_extra={"slot": ..., "thread": "chat"}` so iOS can route straight to
   the chat thread (client work).
5. **Per-user activity-platform cache.** `resolve_send_target` now runs one
   extra indexed query per candidate user per 30-min tick — fine at current
   scale; revisit if user count grows 100×.
6. **Warmup burst tone.** New-user warmup fires 9 windows in 48h — aggressive
   by design, but combined with hooks it can feel like spam if the user replies
   to none. The `gate_decision` warmup exemption means silence never
   de-escalates during the burst. Consider capping total unanswered warmups
   at 4-5.

## Prod data notes

- Gi's `channel_preference='telegram'` can stay — activity-first routing
  outranks it once deployed. (Clearing it would flip him to iMessage sends
  under the CURRENT prod code — don't.)
- Marina (76) timezone repaired in prod (`America/New_York`); Dean (78)
  completed on his own — no data fix needed.

All fixes require the manual Render deploy to reach prod.
