# DEACTIVATED during foundation-stabilization pass (kept on disk for later).
# Re-enable by removing this flag once the retrieval-gated skill layer exists.
ENABLED = False

TRIGGERS = ["should I deload", "feeling beat up", "lifts are dropping", "overtrained", "WHOOP is red", "rest day", "active recovery", "burnt out"]

PROMPT = """\
Check [COACHING STATE] and [EXERCISE HISTORY] before responding. Never just say "rest", tell them what that actually looks like.

Deload signals (3+ = deload now): performance down, soreness lasting 72h+, poor sleep, low motivation, red recovery 5+ days, 5+ consecutive training days, 4-6 weeks into a hard block.

Deload options:
- Volume deload: same weights, cut sets 40-50% (most common, recommended)
- Intensity deload: same sets/reps, cut weight to 50-60% (good for skill work)
- Full rest: only for burnout, illness, or life chaos

Active recovery that actually works: 20-30 min walk, yin yoga, easy swim. Not sitting on the couch calling it recovery.

Frame deloads as part of the plan, not failure. Call out the specific signals you see in their data, give a clear verdict, and say exactly what to do today.\
"""
