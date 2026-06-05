"""Tests for the weekly insights data summary (pure logic, no LLM)."""
from api.insights import _build_week_summary


def test_week_summary_includes_nutrition_weight_and_wearable():
    stats = {
        "user": {"goal_weight_lbs": 180},
        "targets": {"calories": 2100, "protein": 200},
        "history": [
            {"status": "closed", "calories": 2200, "protein": 180, "workout": True,
             "date": f"2026-06-0{i}"} for i in range(1, 8)
        ],
        "weights": [{"lbs": 186.0, "date": "2026-06-01"},
                    {"lbs": 185.2, "date": "2026-06-05"}],
        "health": [{"source": "whoop", "recovery_score": 62, "strain": 13.1,
                    "sleep_hours": 6.8, "hrv": 82} for _ in range(5)],
    }
    s = _build_week_summary(stats)
    assert "WEEKLY trends" in s
    assert "Avg calories: 2200/day" in s
    assert "Avg protein: 180g/day" in s
    assert "Workouts completed: 7" in s
    assert "186.0lb -> 185.2lb" in s
    assert "WEARABLE (Whoop" in s and "Recovery: 62%" in s


def test_week_summary_handles_no_data():
    s = _build_week_summary({"user": {}, "targets": {}, "history": [],
                             "weights": [], "health": []})
    assert "No closed days logged" in s
