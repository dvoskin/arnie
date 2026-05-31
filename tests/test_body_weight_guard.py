"""Regression tests for the iMessage duplicate-send + body-weight mis-log fixes."""
from types import SimpleNamespace
from handlers.tool_executor import deterministic_confirmation


def _prefs(cal_t=1800, pro_t=200):
    return SimpleNamespace(calorie_target=cal_t, protein_target=pro_t)


def _log(cal=0, pro=0):
    return SimpleNamespace(total_calories=cal, total_protein=pro)


def test_body_weight_without_number_does_not_claim_weighin():
    # "I'm gonna have a barbells bar" mis-routed to log_body_weight with no weight.
    tc = [{"name": "log_body_weight", "input": {}}]
    out = deterministic_confirmation(tc, _log(), _prefs())
    assert "weight down" not in out.lower()


def test_body_weight_with_number_confirms_weighin():
    tc = [{"name": "log_body_weight", "input": {"weight": 82.5}}]
    out = deterministic_confirmation(tc, _log(), _prefs())
    assert "weight down" in out.lower()


def test_body_weight_zero_is_not_a_weighin():
    tc = [{"name": "log_body_weight", "input": {"weight": 0}}]
    out = deterministic_confirmation(tc, _log(), _prefs())
    assert "weight down" not in out.lower()
