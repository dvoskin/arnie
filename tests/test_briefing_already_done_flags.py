"""The coach brief must know what's already been logged TODAY so its "first
move" directive never recommends a done move (weigh-in, first meal).

Regression for Danny 2026-07-04: after he said "gonna weigh in" AND logged the
weight, the brief still read "log your weight, then breakfast". The brief was
conversation-aware but log-blind — it had no weighed_today signal. These tests
assert the signal now reaches the DATA payload the briefing LLM reads.
"""
from api.insights import _build_briefing_summary


def _base_stats(**over):
    stats = {
        "user": {"name": "Danny", "goal": "cut",
                 "current_weight_lbs": 187, "goal_weight_lbs": 180},
        "targets": {"calories": 2164, "protein": 180},
        "today": {"calories": 0, "protein": 0, "workout_completed": False,
                  "exercise_entries": [], "food_entries": []},
        "history": [],
        "weights": [{"date": "2026-07-04", "lbs": 187.6}],
        "health": [],
        "timezone": "America/New_York",
    }
    stats.update(over)
    return stats


def test_weighed_today_true_tells_model_not_to_ask():
    s = _base_stats(weighed_today=True)
    out = _build_briefing_summary(s)
    assert "weighed in YES" in out
    assert "do NOT tell them to weigh in" in out


def test_weighed_today_false_says_not_yet():
    s = _base_stats(weighed_today=False)
    out = _build_briefing_summary(s)
    assert "weighed in not yet" in out


def test_first_meal_logged_surfaced_from_flag():
    s = _base_stats(logged_food_today=True)
    out = _build_briefing_summary(s)
    assert "first meal logged" in out


def test_first_meal_logged_inferred_from_today_entries():
    # Even without the top-level flag, a food entry in `today` marks it logged.
    s = _base_stats(today={"calories": 300, "protein": 20,
                           "workout_completed": False, "exercise_entries": [],
                           "food_entries": [{"id": 1, "name": "eggs"}]})
    out = _build_briefing_summary(s)
    assert "first meal logged" in out


def test_no_flags_defaults_to_not_yet():
    out = _build_briefing_summary(_base_stats())
    assert "weighed in not yet" in out
    assert "first meal not yet" in out
