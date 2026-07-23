

def test_infer_today_completed_until_rollover_then_advances():
    """Danny 2026-07-23: chest finished at 12:15am must show COMPLETED until the
    4am logging-day rollover, then auto-advance to the next split day. History is
    grouped by DailyLog.date (already rollover-aware), so 'today' flips at 4am."""
    from core.program_rotation import infer_today
    program = {
        "rotation": ["Chest", "Back", "Legs"],
        "days": [
            {"name": "Chest", "exercises": [{"name": "Bench Press"}, {"name": "Incline Press"}]},
            {"name": "Back", "exercises": [{"name": "Lat Pulldown"}, {"name": "Row"}]},
            {"name": "Legs", "exercises": [{"name": "Squat"}, {"name": "Leg Press"}]},
        ],
    }
    hist = [("2026-07-22", {"bench press", "incline press"})]
    # Still the same logging day (pre-4am): chest shows as DONE.
    day, done = infer_today(program, hist, "2026-07-22")
    assert (day, done) == ("Chest", True)
    # After the 4am rollover the logging day advances: next split day, not done.
    day, done = infer_today(program, hist, "2026-07-23")
    assert (day, done) == ("Back", False)
    # No history at all: first day, not done.
    assert infer_today(program, [], "2026-07-23") == ("Chest", False)
