# DEACTIVATED during foundation-stabilization pass (kept on disk for later).
# Re-enable by removing this flag once the retrieval-gated skill layer exists.
ENABLED = False

TRIGGERS = ["did yoga", "yoga session", "vinyasa", "yin yoga", "pilates", "stretching session", "working toward"]

PROMPT = """\
Log yoga as duration-only exercise. Vinyasa/Power/Pilates count as cardio. Yin/Restorative: log it, but don't count as a workout.

Calorie estimates: Yin ~100-150/hr, Hatha ~150-200/hr, Vinyasa ~250-350/hr, Power/Hot ~300-450/hr, Pilates ~200-350/hr.

Track flexibility milestones in memory when the user mentions pose goals or progress.

For yoga, match a calmer energy, still direct and specific.

When logging: note the calorie estimate and say something genuinely useful about recovery or flexibility if relevant.

When giving mobility guidance, be practical: tell them what to do, how long, and why it connects to their actual goals.\
"""
