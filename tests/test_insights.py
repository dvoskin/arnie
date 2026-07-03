"""Tests for the weekly insights data summary (pure logic, no LLM)."""
from api.insights import (_build_week_summary, _engagement_signal,
                          _briefing_tier_guidance, _training_state)


def test_training_state_distinguishes_lifting_from_cardio():
    # A Whoop walk is cardio, not a lift — the coach must NOT read it as
    # "workout done" (the "your lift is done" bug).
    whoop_walk = {"cardio_completed": True, "exercise_entries": [
        {"name": "Walking", "cardio_type": "Walking", "is_cardio": True,
         "duration_minutes": 32, "source": "whoop"}]}
    s = _training_state(whoop_walk)
    assert "NOT a strength session" in s
    assert "no lifting logged yet" in s
    assert "wearable" in s  # flags the auto-synced origin

    # A real lift → strength done.
    lift = {"workout_completed": True, "exercise_entries": [
        {"name": "Bench Press", "sets": 4, "reps": "8", "is_cardio": False}]}
    assert _training_state(lift) == "strength workout done"

    # Both → strength credited (cardio noted).
    both = {"workout_completed": True, "cardio_completed": True,
            "exercise_entries": [
                {"name": "Squat", "sets": 5, "is_cardio": False},
                {"name": "Run", "cardio_type": "Running", "is_cardio": True}]}
    assert _training_state(both) == "strength workout done (plus cardio)"

    # Nothing logged → not yet.
    assert _training_state({}) == "not yet"
    assert _training_state({"exercise_entries": []}) == "not yet"


def test_engagement_signal_tiers_scale_with_data():
    # NEW: profile only, nothing logged → tier 0 (plan/projection brief).
    assert _engagement_signal({})["tier"] == 0
    assert _engagement_signal({"today": {}, "history": [], "weights": []})["tier"] == 0

    # EARLY: just today touched (no prior days) → tier 1.
    assert _engagement_signal({"today": {"calories": 600}})["tier"] == 1
    # EARLY: one logged day in history → tier 1.
    assert _engagement_signal({"history": [{"date": "2026-06-01", "calories": 1800}]})["tier"] == 1

    # BUILDING: several logged days → tier 2.
    building = {"history": [{"date": f"2026-06-0{i}", "calories": 1800} for i in range(1, 6)]}
    assert _engagement_signal(building)["tier"] == 2

    # RICH: many logged days + enough weigh-ins → tier 3.
    rich = {
        "history": [{"date": f"2026-06-{i:02d}", "calories": 1800, "workout": i % 2 == 0}
                    for i in range(1, 13)],
        "weights": [{"date": f"2026-06-{i:02d}", "lbs": 200 - i} for i in range(1, 7)],
    }
    sig = _engagement_signal(rich)
    assert sig["tier"] == 3
    assert sig["logged_days"] == 12 and sig["weigh_ins"] == 6


def test_briefing_tier_guidance_always_demands_complete_brief():
    # Every tier insists on a full brief; only the low tiers mention the unlock nudge.
    for tier in range(4):
        g = _briefing_tier_guidance({"tier": tier})
        assert "COMPLETE" in g
    assert "next unlock" in _briefing_tier_guidance({"tier": 0}).lower()
    assert "next unlock" not in _briefing_tier_guidance({"tier": 3}).lower()


def test_week_summary_includes_nutrition_weight_and_wearable():
    # Use dates well in the past so the past-days filter (today's date) keeps them all.
    stats = {
        "user": {"goal_weight_lbs": 180},
        "targets": {"calories": 2100, "protein": 200},
        "history": [
            {"calories": 2200, "protein": 180, "workout": True,
             "date": f"2024-06-0{i}"} for i in range(1, 8)
        ],
        "weights": [{"lbs": 186.0, "date": "2024-06-01"},
                    {"lbs": 185.2, "date": "2024-06-05"}],
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
    assert "No prior days logged" in s
