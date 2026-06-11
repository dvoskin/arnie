"""
Reminders decision layer — eligibility, suppression, and context-aware follow-up
timing. All pure functions, so these run without a DB.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from reminders import eligibility as elig
from reminders import suppression as supp
from reminders import pending as pend


# ── eligibility ───────────────────────────────────────────────────────────────

def test_in_window_inclusive_edges():
    assert elig.in_window("12:00", "09:00", "21:00") is True
    assert elig.in_window("08:59", "09:00", "21:00") is False
    assert elig.in_window("21:01", "09:00", "21:00") is False
    assert elig.in_window("09:00", "09:00", "21:00") is True
    assert elig.in_window("21:00", "09:00", "21:00") is True


def test_has_timezone():
    assert elig.has_timezone(SimpleNamespace(timezone="America/New_York")) is True
    assert elig.has_timezone(SimpleNamespace(timezone="UTC")) is False
    assert elig.has_timezone(SimpleNamespace(timezone=None)) is False
    assert elig.has_timezone(SimpleNamespace(timezone="")) is False


def test_clamp_window_respects_tighter_caps_wider():
    # wider stored window → clamped to 9-21
    w, s = elig.clamp_window(SimpleNamespace(wake_time="06:00", sleep_time="23:30"))
    assert (w, s) == ("09:00", "21:00")
    # tighter stored window → respected
    w, s = elig.clamp_window(SimpleNamespace(wake_time="10:00", sleep_time="20:00"))
    assert (w, s) == ("10:00", "20:00")
    # missing prefs → hard defaults
    w, s = elig.clamp_window(SimpleNamespace(wake_time=None, sleep_time=None))
    assert (w, s) == ("09:00", "21:00")


def test_pacing_pct():
    assert elig.pacing_pct(9, 0, "09:00", "21:00") == 0.0
    assert elig.pacing_pct(21, 0, "09:00", "21:00") == 1.0
    assert elig.pacing_pct(15, 0, "09:00", "21:00") == pytest.approx(0.5)
    # degenerate window
    assert elig.pacing_pct(12, 0, "21:00", "09:00") == 0.5


def test_is_in_live_conversation():
    assert elig.is_in_live_conversation(None) is False     # never messaged
    assert elig.is_in_live_conversation(5) is True
    assert elig.is_in_live_conversation(24.9) is True
    assert elig.is_in_live_conversation(25) is False       # boundary
    assert elig.is_in_live_conversation(60) is False


def test_should_skip_linked():
    linked = SimpleNamespace(linked_to_user_id=7)
    unlinked = SimpleNamespace(linked_to_user_id=None)
    assert elig.should_skip_linked(linked, linking_enabled=True) is True
    assert elig.should_skip_linked(linked, linking_enabled=False) is False
    assert elig.should_skip_linked(unlinked, linking_enabled=True) is False


def test_proactive_pref_on():
    assert elig.proactive_pref_on(SimpleNamespace(proactive_messaging_enabled=True)) is True
    assert elig.proactive_pref_on(SimpleNamespace(proactive_messaging_enabled=False)) is False
    assert elig.proactive_pref_on(None) is False


# ── Tier-2 silence gate (D4) ────────────────────────────────────────────────────

_PREFS = SimpleNamespace(reminder_frequency="moderate")


def test_gate_decision_warmup_always_sends():
    # During the warmup burst (< WARMUP_BURST_HOURS), even a big streak still sends.
    assert elig.gate_decision(streak=0, hours_since_created=1.0, prefs=_PREFS) == "send"
    assert elig.gate_decision(streak=5, hours_since_created=1.0, prefs=_PREFS) == "send"
    assert elig.gate_decision(streak=2, hours_since_created=49.9, prefs=_PREFS) == "send"


def test_gate_decision_streak_thresholds_after_warmup():
    h = elig.WARMUP_BURST_HOURS + 10  # past the burst
    assert elig.gate_decision(streak=0, hours_since_created=h, prefs=_PREFS) == "send"
    assert elig.gate_decision(streak=1, hours_since_created=h, prefs=_PREFS) == "send"
    assert elig.gate_decision(streak=2, hours_since_created=h, prefs=_PREFS) == "consolidate"
    assert elig.gate_decision(streak=3, hours_since_created=h, prefs=_PREFS) == "suppress"
    assert elig.gate_decision(streak=9, hours_since_created=h, prefs=_PREFS) == "suppress"


def test_gate_decision_warmup_boundary():
    # Exactly at the boundary is no longer warmup → streak gate applies.
    h = elig.WARMUP_BURST_HOURS
    assert elig.gate_decision(streak=3, hours_since_created=h, prefs=_PREFS) == "suppress"


# ── Tier-3 reminder-frequency read path (D6) ────────────────────────────────────

def _p(freq):
    return SimpleNamespace(reminder_frequency=freq)


def test_frequency_heavy_allows_everything():
    p = _p("heavy")
    for slot in ("morning_checkin", "late_morning_nolog", "midday_pacing",
                 "preworkout", "workout_check", "evening_pacing", "night_closeout"):
        assert elig.frequency_allows(p, slot) is True


def test_frequency_moderate_drops_marginal_slots():
    p = _p("moderate")
    assert elig.frequency_allows(p, "morning_checkin") is True
    assert elig.frequency_allows(p, "evening_pacing") is True
    # the two most marginal pokes are dropped at moderate
    assert elig.frequency_allows(p, "late_morning_nolog") is False
    assert elig.frequency_allows(p, "night_closeout") is False


def test_frequency_light_only_anchors():
    p = _p("light")
    assert elig.frequency_allows(p, "morning_checkin") is True
    assert elig.frequency_allows(p, "evening_pacing") is True
    assert elig.frequency_allows(p, "midday_pacing") is False
    assert elig.frequency_allows(p, "preworkout") is False


def test_frequency_none_is_smallest_nonempty_not_hard_off():
    """'none' must still permit at least one anchor — it is NOT a second kill switch.
    UI label: "Morning only" — so only morning_checkin from the timed slot chain."""
    p = _p("none")
    allowed = [s for s in ("morning_checkin", "late_morning_nolog", "midday_pacing",
                           "preworkout", "workout_check", "evening_pacing", "night_closeout")
               if elig.frequency_allows(p, s)]
    assert allowed == ["morning_checkin"]  # exactly one anchor, never empty


def test_frequency_none_blocks_warmup_hooks_recap_eod():
    """Minimal preference must NOT spray warmup nudges, hook re-asks, weekly
    recap, or EOD report — that's exactly the screenshot complaint."""
    p = _p("none")
    # warmup_* category (prefix-collapsed): blocked at "none"
    for k in ("warmup_15m", "warmup_1h", "warmup_48h"):
        assert elig.frequency_allows(p, k) is False, k
    # other proactive paths: blocked at "none"
    assert elig.frequency_allows(p, "conversation_hook") is False
    assert elig.frequency_allows(p, "weekly_recap") is False
    assert elig.frequency_allows(p, "day_report") is False
    assert elig.frequency_allows(p, "proactive_hook") is False
    # followup_* category: blocked at "none"
    assert elig.frequency_allows(p, "followup_profile_stats") is False
    assert elig.frequency_allows(p, "followup_conversation_hook") is False
    # city_ask is the one-time setup exemption (everyone gets it once)
    assert elig.frequency_allows(p, "city_ask") is True


def test_frequency_light_matches_morning_and_evening_label():
    """UI label: "Morning & evening" — two daily anchors + the EOD summary."""
    p = _p("light")
    assert elig.frequency_allows(p, "morning_checkin") is True
    assert elig.frequency_allows(p, "evening_pacing") is True
    assert elig.frequency_allows(p, "day_report") is True
    # but no warmup spam, no hooks, no weekly recap, no consolidate
    assert elig.frequency_allows(p, "warmup_15m") is False
    assert elig.frequency_allows(p, "conversation_hook") is False
    assert elig.frequency_allows(p, "weekly_recap") is False
    assert elig.frequency_allows(p, "proactive_hook") is False


def test_frequency_moderate_matches_a_few_times_a_day_label():
    """UI label: "A few times a day" — 3-5 slots + housekeeping."""
    p = _p("moderate")
    # 3 of the 5 mid-day slots plus the anchors fire
    assert elig.frequency_allows(p, "midday_pacing") is True
    assert elig.frequency_allows(p, "preworkout") is True
    assert elig.frequency_allows(p, "workout_check") is True
    # warmup, hooks, EOD, recap all on at moderate
    assert elig.frequency_allows(p, "warmup_1h") is True
    assert elig.frequency_allows(p, "conversation_hook") is True
    assert elig.frequency_allows(p, "day_report") is True
    assert elig.frequency_allows(p, "weekly_recap") is True
    # late_morning and night_closeout still dropped at moderate
    assert elig.frequency_allows(p, "late_morning_nolog") is False
    assert elig.frequency_allows(p, "night_closeout") is False


def test_frequency_heavy_includes_all_proactive_categories():
    """UI label: "All day" — every path fires."""
    p = _p("heavy")
    for k in ("morning_checkin", "late_morning_nolog", "midday_pacing", "preworkout",
              "workout_check", "evening_pacing", "night_closeout",
              "warmup_15m", "warmup_48h",
              "conversation_hook", "day_report", "weekly_recap",
              "proactive_hook", "city_ask",
              "followup_profile_stats", "followup_conversation_hook"):
        assert elig.frequency_allows(p, k) is True, k


def test_frequency_unknown_falls_back_to_moderate():
    # unset / garbage / None → behaves like moderate (the default tier)
    for freq in (None, "", "wat", "MODERATE"):
        p = _p(freq)
        assert elig.frequency_allows(p, "morning_checkin") is True
        # late_morning is moderate-excluded; for a junk value we fall back to moderate
        if freq != "MODERATE":  # MODERATE lowercases to a real tier
            assert elig.frequency_allows(p, "late_morning_nolog") is False
    # case-insensitivity: "MODERATE" resolves to moderate
    assert elig.frequency_allows(_p("MODERATE"), "late_morning_nolog") is False


def test_normalize_reminder_frequency_relative_and_exact():
    norm = elig.normalize_reminder_frequency
    # "less"/"more" step one tier along none<light<moderate<heavy from CURRENT
    assert norm("less", "moderate") == "light"
    assert norm("more", "moderate") == "heavy"
    assert norm("fewer", "heavy") == "moderate"
    assert norm("up", "light") == "moderate"
    # clamps at the ends — "text me less" on none stays none, never wraps
    assert norm("less", "none") == "none"
    assert norm("more", "heavy") == "heavy"
    # exact tier names pass through unchanged (case-insensitive)
    for tier in ("none", "light", "moderate", "heavy"):
        assert norm(tier, "moderate") == tier
    assert norm("HEAVY", "light") == "heavy"
    # missing/garbage current tier falls back to moderate as the pivot
    assert norm("less", None) == "light"
    assert norm("less", "wat") == "light"
    # unrecognized value is returned unchanged (frequency_allows then defaults)
    assert norm("banana", "moderate") == "banana"


# ── suppression ───────────────────────────────────────────────────────────────

def test_parse_slots():
    assert supp.parse_slots(None) == set()
    assert supp.parse_slots("") == set()
    assert supp.parse_slots("a,b,a") == {"a", "b"}


def test_has_fired_and_add_slot():
    s = supp.add_slot(None, "warmup_15m")
    assert supp.has_fired(s, "warmup_15m") is True
    assert supp.has_fired(s, "warmup_1h") is False
    s2 = supp.add_slot(s, "warmup_1h")
    # sorted + deduped
    assert s2 == "warmup_15m,warmup_1h"
    assert supp.add_slot(s2, "warmup_1h") == s2  # idempotent


# ── pending follow-up timing ──────────────────────────────────────────────────

def _q(tier="casual", asked_h_ago=0.0, last_h_ago=None, count=0, answered=False):
    """Build a duck-typed PendingQuestion at a given age."""
    now = datetime.utcnow()
    asked = now - timedelta(hours=asked_h_ago)
    last = None if last_h_ago is None else now - timedelta(hours=last_h_ago)
    return SimpleNamespace(
        tier=tier, asked_at=asked, last_asked_at=last,
        follow_up_count=count,
        answered_at=(now if answered else None),
    )


def test_answered_never_follows_up():
    assert pend.should_follow_up(_q(answered=True, asked_h_ago=100)) is False


def test_casual_waits_24h_for_first_followup():
    assert pend.should_follow_up(_q("casual", asked_h_ago=10)) is False
    assert pend.should_follow_up(_q("casual", asked_h_ago=25)) is True


def test_goal_critical_waits_only_8h():
    assert pend.should_follow_up(_q("goal_critical", asked_h_ago=5)) is False
    assert pend.should_follow_up(_q("goal_critical", asked_h_ago=9)) is True


def test_spacing_between_subsequent_followups():
    # casual, already followed up once 10h ago → too soon (needs 24h spacing)
    assert pend.should_follow_up(_q("casual", asked_h_ago=48, last_h_ago=10, count=1)) is False
    # ...25h ago → ok
    assert pend.should_follow_up(_q("casual", asked_h_ago=48, last_h_ago=25, count=1)) is True


def test_max_followups_cap():
    # casual caps at 2 follow-ups
    assert pend.should_follow_up(_q("casual", asked_h_ago=500, last_h_ago=200, count=2)) is False
    # goal_critical caps at 3
    assert pend.should_follow_up(_q("goal_critical", asked_h_ago=500, last_h_ago=200, count=3)) is False
    assert pend.should_follow_up(_q("goal_critical", asked_h_ago=500, last_h_ago=200, count=2)) is True


def test_live_conversation_blocks_followup():
    q = _q("goal_critical", asked_h_ago=100)
    assert pend.should_follow_up(q, mins_since_last_exchange=5) is False   # mid-thread
    assert pend.should_follow_up(q, mins_since_last_exchange=120) is True  # thread cooled


def test_cold_user_suppressed():
    q = _q("goal_critical", asked_h_ago=1000)
    cold_mins = pend.COLD_USER_CUTOFF_DAYS * 24 * 60 + 10
    assert pend.should_follow_up(q, mins_since_last_exchange=cold_mins) is False
    # never-messaged (None) is NOT treated as cold
    assert pend.should_follow_up(q, mins_since_last_exchange=None) is True


def test_select_prioritizes_goal_critical_then_oldest():
    casual_old = _q("casual", asked_h_ago=100)
    crit_new = _q("goal_critical", asked_h_ago=20)
    crit_old = _q("goal_critical", asked_h_ago=200)
    picked = pend.select_follow_up([casual_old, crit_new, crit_old])
    assert picked is crit_old  # goal_critical beats casual; oldest within tier

    # only casual eligible → returns it
    assert pend.select_follow_up([casual_old]) is casual_old
    # nothing eligible → None
    assert pend.select_follow_up([_q("casual", asked_h_ago=1)]) is None


def test_follow_up_tone_scales_with_tier_and_count():
    assert "matters" in pend.follow_up_tone(_q("goal_critical", count=0))
    assert "last real ask" in pend.follow_up_tone(_q("goal_critical", count=1))
    assert "zero pressure" in pend.follow_up_tone(_q("casual", count=0))
    assert "final nudge" in pend.follow_up_tone(_q("casual", count=1))


def test_proactive_hook_registered_in_tier_policy():
    """D5: the silence-consolidation kind is a real follow-up tier."""
    assert "proactive_hook" in pend.TIER_POLICY
    policy = pend.TIER_POLICY["proactive_hook"]
    assert policy.max_follow_ups == 1  # one warm re-ask, then let it go


def test_proactive_hook_has_its_own_tone():
    tone = pend.follow_up_tone(_q("proactive_hook", count=0))
    # a distinct, warm-and-open tone (not the goal_critical / casual phrasings)
    assert "warm" in tone
    assert "guilt" in tone  # explicitly no guilt about the silence


def test_proactive_hook_follow_up_timing():
    # first re-ask waits ~4h, then capped at one attempt
    assert pend.should_follow_up(_q("proactive_hook", asked_h_ago=1)) is False
    assert pend.should_follow_up(_q("proactive_hook", asked_h_ago=5)) is True
    assert pend.should_follow_up(_q("proactive_hook", asked_h_ago=500, last_h_ago=200, count=1)) is False


def test_aware_now_compares_with_naive_timestamps():
    """A tz-aware `now` must not crash against naive DB timestamps."""
    from datetime import timezone
    q = _q("casual", asked_h_ago=30)
    aware_now = datetime.now(timezone.utc)
    # should not raise, and 30h-old casual question is due
    assert pend.should_follow_up(q, now=aware_now) is True
