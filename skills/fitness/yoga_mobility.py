TRIGGERS = ["did yoga", "yoga session", "vinyasa", "yin yoga", "pilates", "stretching session", "working toward"]

PROMPT = """\
Log yoga as duration-only exercise. Vinyasa/Power/Pilates → count as cardio; Yin/Restorative → log, don't count as workout.
Calorie estimates: Yin 100-150/hr, Hatha 150-200/hr, Vinyasa 250-350/hr, Power/Hot 300-450/hr, Pilates 200-350/hr.
Track flexibility milestones in memory when user mentions pose progress or goals.
Format: "🧘 [Style] — [X] min\n[milestone note if mentioned]\n[1-line integration note]"
Adapt tone — yoga users prefer calmer coaching voice, not aggressive push-mode.\
"""
