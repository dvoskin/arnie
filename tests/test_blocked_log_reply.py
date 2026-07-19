"""blocked_log_reply — the structural form of the 00:38 turkey incident.

Contract: ALL log_* results blocked ('Already on the board:') → deterministic
honest reply (never a model follow-up). Mixed, successful, or non-logging
turns → None (model keeps its voice).
"""
from handlers.tool_executor import blocked_log_reply


BLOCK = "Already on the board: Ground turkey 250g, 355 cal, logged at 00:32 (6m ago)"


def test_all_blocked_returns_honest_reply():
    out = blocked_log_reply(
        [{"name": "log_food", "input": {}}],
        {"log_food": BLOCK},
    )
    assert out is not None
    assert "nothing new logged" in out
    assert BLOCK in out
    assert "logged, you're at" not in out.lower()


def test_successful_log_passes_through():
    out = blocked_log_reply(
        [{"name": "log_food", "input": {}}],
        {"log_food": "Logged: Ground turkey 250g — 355 cal. Today: 1,520 cal."},
    )
    assert out is None


def test_non_logging_turn_passes_through():
    assert blocked_log_reply(
        [{"name": "query_history", "input": {}}], {"query_history": "..."}) is None
    assert blocked_log_reply([], {}) is None
