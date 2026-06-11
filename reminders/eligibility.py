"""
Eligibility — may we send a timed proactive message to this user *right now*?

Pure functions, no DB / no IO. These are the overnight-spam and
interrupt-the-live-thread guards, extracted from proactive_scheduler so they can
be unit-tested in isolation and reused by the follow-up path.
"""
from __future__ import annotations

# A user who exchanged messages with Arnie within this many minutes is mid-thread;
# a scheduled nudge on top of that reads as a non-sequitur. Skip and re-check later.
LIVE_CONVERSATION_MINUTES = 25

# Hard window — never message before 09:00 or after 21:00 local, regardless of a
# user's stored wake/sleep. A tighter personal window is respected; a wider one is
# clamped to this.
HARD_WAKE = "09:00"
HARD_SLEEP = "21:00"


def in_window(hhmm: str, wake: str, sleep: str) -> bool:
    """True if the local HH:MM falls within [wake, sleep] (inclusive edges)."""
    return wake <= hhmm <= sleep


def has_timezone(user) -> bool:
    """
    True only if we know the user's real timezone. The column defaults to "UTC",
    and the city resolver never returns "UTC" for any real city, so "UTC"/None
    means "unknown" — and we must NOT send timed messages (would risk 3am spam).
    """
    return bool(getattr(user, "timezone", None)) and user.timezone != "UTC"


def clamp_window(prefs) -> tuple[str, str]:
    """
    Resolve the effective [wake, sleep] window for proactive sends: the user's
    stored window, clamped to the 9am-9pm hard cap. Respects a TIGHTER personal
    window (e.g. wake 10:00) but never widens past the cap.
    """
    user_wake = getattr(prefs, "wake_time", None)
    wake = max((user_wake or HARD_WAKE), HARD_WAKE)
    sleep = min((getattr(prefs, "sleep_time", None) or HARD_SLEEP), HARD_SLEEP)
    return wake, sleep


def pacing_pct(hour: int, minute: int, wake: str, sleep: str) -> float:
    """Fraction of the waking day elapsed (0.0–1.0). 0.5 if the window is degenerate."""
    wh, wm = int(wake.split(":")[0]), int(wake.split(":")[1])
    sh, sm = int(sleep.split(":")[0]), int(sleep.split(":")[1])
    wake_min = wh * 60 + wm
    sleep_min = sh * 60 + sm
    now_min = hour * 60 + minute
    day_len = sleep_min - wake_min
    if day_len <= 0:
        return 0.5
    return max(0.0, min(1.0, (now_min - wake_min) / day_len))


def is_in_live_conversation(mins_since_last_exchange) -> bool:
    """
    True if the user is actively mid-conversation (last exchange < LIVE window).
    `None` (never messaged) is NOT live. Used to avoid firing on top of a thread.
    """
    if mins_since_last_exchange is None:
        return False
    return mins_since_last_exchange < LIVE_CONVERSATION_MINUTES


def should_skip_linked(user, linking_enabled: bool) -> bool:
    """
    True if this is a *secondary* linked identity — skip it so a linked user gets
    each proactive message exactly once (on their canonical/preferred account).
    Safe when linking is off (always False) or the row is unlinked.
    """
    return bool(linking_enabled and getattr(user, "linked_to_user_id", None))


def proactive_pref_on(prefs) -> bool:
    """True if the user hasn't opted out of proactive messaging."""
    return bool(prefs and getattr(prefs, "proactive_messaging_enabled", False))


# ── Tier-2: silence consolidation gate ─────────────────────────────────────────
# A fresh account is in its warmup burst (the day-1/day-2 engagement cadence). We
# never consolidate or suppress during that window — going quiet early is normal
# and the burst is how we hook them. Past it, repeated silence means back off.
WARMUP_BURST_HOURS = 50.0


def gate_decision(streak: int, hours_since_created: float, prefs) -> str:
    """
    Pure Tier-2 policy: given how many proactive check-ins the user has ignored in a
    row (`streak`), how long they've been a user, and their prefs, decide what the
    scheduler should do this tick. Returns one of:

      "send"        — proceed normally (fire the due slot nudge).
      "consolidate" — they've ignored a couple in a row; skip the individual slots
                      and instead open ONE proactive_hook so the follow-up loop
                      re-asks a single warm check-in.
      "suppress"    — they've ignored several; go dark on timed nudges for now.

    Policy only — no DB, no sending. The scheduler acts on the verdict.

    During the warmup burst (hours_since_created < WARMUP_BURST_HOURS) we always
    "send": a brand-new user going quiet is expected, and the engagement burst is
    deliberately aggressive. The streak gate only kicks in after they've settled.
    """
    if hours_since_created < WARMUP_BURST_HOURS:
        return "send"
    if streak >= 3:
        return "suppress"
    if streak >= 2:
        return "consolidate"
    return "send"


# ── Tier-3: reminder-frequency read path ───────────────────────────────────────
# reminder_frequency NARROWS which proactive paths may fire. The Client tab labels
# the tiers as:
#   none     → "Morning only"          (1 message a day)
#   light    → "Morning & evening"     (2 anchors a day)
#   moderate → "A few times a day"     (3-5 touchpoints)
#   heavy    → "All day"               (everything)
#
# Every outbound proactive path (timed slots, warmup burst, conversation hooks,
# EOD report, weekly recap, pending follow-ups, consolidate hook) is gated by
# frequency_allows(). proactive_messaging_enabled is still the hard OFF; this
# only shrinks WHICH paths fire when proactive is on.
#
# Slot categories (prefix-matched in frequency_allows):
#   warmup_*    — new-user engagement burst (warmup_15m, warmup_1h, …)
#   followup_*  — re-asks for open pending questions
#   Other keys are the literal slot names from the scheduler.
_FREQUENCY_SLOTS: dict[str, set[str]] = {
    # heavy = "All day" — everything fires
    "heavy": {
        "morning_checkin", "late_morning_nolog", "midday_pacing", "preworkout",
        "workout_check", "evening_pacing", "night_closeout",
        "warmup", "conversation_hook", "day_report", "weekly_recap",
        "proactive_hook", "city_ask", "followup_pending",
    },
    # moderate = "A few times a day" — 3-5 anchors + housekeeping
    "moderate": {
        "morning_checkin", "midday_pacing", "preworkout",
        "workout_check", "evening_pacing",
        "warmup", "conversation_hook", "day_report", "weekly_recap",
        "followup_pending", "city_ask",
    },
    # light = "Morning & evening" — the two daily anchors + essential summaries
    "light": {
        "morning_checkin", "evening_pacing", "day_report",
        "followup_pending", "city_ask",
    },
    # none = "Morning only" — one message a day. Setup-critical city_ask exempt
    # because it's one-time and required for everything else to work.
    "none": {
        "morning_checkin", "city_ask",
    },
}

# Unknown / unset frequency behaves like the default tier.
_DEFAULT_FREQUENCY = "moderate"

# Frequency tiers, ascending (fewest → most pokes). A relative "less"/"more"
# instruction shifts one step along this ladder; an exact tier name passes
# through. Single source of the frequency vocabulary, shared with the write path.
# "minimal" is a UI synonym for "none" (the Client tab labels it "Morning only").
_FREQ_LADDER = ["none", "light", "moderate", "heavy"]
_FREQ_LESS = {"less", "fewer", "down", "reduce", "lower", "quieter", "minimal", "minimum"}
_FREQ_MORE = {"more", "up", "increase", "higher", "louder", "max", "maximum"}


def normalize_reminder_frequency(value, current=_DEFAULT_FREQUENCY) -> str:
    """Map a model- or user-written reminder_frequency onto a valid tier.

    Exact tier name ("heavy"/"moderate"/"light"/"none") → returned as-is.
    Relative "less"/"more" (and common synonyms) → one step down/up the ladder
    from the user's CURRENT tier, so "text me less" always reduces and never
    accidentally raises. Anything unrecognized is returned unchanged, leaving
    frequency_allows() to apply the moderate default.
    """
    v = str(value or "").strip().lower()
    if v in _FREQUENCY_SLOTS:           # already an exact tier name
        return v
    cur = str(current or _DEFAULT_FREQUENCY).strip().lower()
    if cur not in _FREQ_LADDER:
        cur = _DEFAULT_FREQUENCY
    idx = _FREQ_LADDER.index(cur)
    if v in _FREQ_LESS:
        return _FREQ_LADDER[max(0, idx - 1)]
    if v in _FREQ_MORE:
        return _FREQ_LADDER[min(len(_FREQ_LADDER) - 1, idx + 1)]
    return value  # unrecognized — leave as-is; frequency_allows falls back to moderate


def frequency_allows(prefs, slot_key: str) -> bool:
    """
    True if `slot_key` is permitted under the user's reminder_frequency tier.

    Precedence: this is a NARROWING filter applied *after* the hard
    proactive_messaging_enabled check — it never re-enables a disabled user.
    "none" maps to the Client-tab "Morning only" tier (morning_checkin + the
    one-time city_ask), not a second off switch. Unknown / missing frequency
    falls back to moderate.

    Prefix collapsing for stable category gates regardless of the per-tick
    instance key:
      warmup_*    (warmup_15m, warmup_1h, ...) → "warmup"
      followup_*  (followup_profile_stats, ...) → "followup_pending"
    """
    freq = (getattr(prefs, "reminder_frequency", None) or _DEFAULT_FREQUENCY)
    freq = str(freq).strip().lower()
    allowed = _FREQUENCY_SLOTS.get(freq, _FREQUENCY_SLOTS[_DEFAULT_FREQUENCY])
    if slot_key.startswith("warmup_"):
        return "warmup" in allowed
    if slot_key.startswith("followup_"):
        return "followup_pending" in allowed
    return slot_key in allowed
