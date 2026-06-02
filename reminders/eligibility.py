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
