"""Cadence throttle — the global budget across ALL proactive slots.

Gi, 2026-07-14: five proactives in one day, each slot individually legit,
together reading as nagging. The budget is the fix: PROACTIVE_DAILY_CAP per
rolling 24h and PROACTIVE_MIN_GAP_MIN between any two sends.
"""
from scheduler.proactive_scheduler import _throttle_decision


def test_under_budget_sends():
    assert _throttle_decision(0, None, cap=4, gap_min=90) == "send"
    assert _throttle_decision(3, 240, cap=4, gap_min=90) == "send"


def test_daily_cap_blocks_fifth_send():
    # Gi's day: the 5th proactive must not fire.
    assert _throttle_decision(4, 300, cap=4, gap_min=90) == "cap"


def test_min_gap_blocks_back_to_back():
    # 13:30 → 14:00 was a 30-minute gap; the throttle spaces them out.
    assert _throttle_decision(1, 30, cap=4, gap_min=90) == "gap"


def test_never_sent_has_no_gap():
    assert _throttle_decision(0, None, cap=4, gap_min=90) == "send"
