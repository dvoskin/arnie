"""Exercise phantom detector — a claimed set with no log_exercise = a drop.

Danny 2026-07-23: Low-to-High sets 2 & 3 and the first Dip set were each confirmed
with a "🏋️ … " log-line but never written. looks_like_unlogged_exercise flags
those so the rescue force-logs them.
"""
from core.turn_health import looks_like_unlogged_exercise as f


def test_barbell_logline_without_tool_is_phantom():
    assert f("60x13", "🏋️ Low-to-High Fly · set 2, 60×13", False) is True
    assert f("8 dips to wrap it", "🏋️ Dips · 1×8 (bodyweight), that wraps it.", False) is True
    assert f("13 again", "🏋️ Low-to-High Fly · set 3, 60×13, matched it.", False) is True


def test_real_log_is_not_phantom():
    # A log_exercise actually fired -> never a phantom, even with the log-line.
    assert f("3x8 bench at 135", "🏋️ Bench · 3×8 @135lb", True) is False


def test_recorded_claim_on_a_set_report_is_phantom():
    # No barbell emoji, but a set report + "on the board" claim with no tool.
    assert f("205x11 last set", "Nice, that's on the board, three sets at 205.", False) is True


def test_no_claim_no_logline_is_not_phantom():
    # Coaching/question with no logged-set presentation -> not a phantom.
    assert f("moving on to high to low fly", "Good call, that shifts the tension up.", False) is False
    assert f("how many sets should I do", "Aim for 3 working sets today.", False) is False


def test_empty_and_none_safe():
    assert f("", "", False) is False
    assert f(None, None, False) is False
