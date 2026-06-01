# DEACTIVATED during foundation-stabilization pass (kept on disk for later).
# Re-enable by removing this flag once the retrieval-gated skill layer exists.
ENABLED = False

TRIGGERS = ["why did I go up", "what does my weight mean", "my weight is up", "scale went up", "weight fluctuation"]

PROMPT = """\
When a user logs their weight or reacts to it, give them context: not panic, not dismissal.

Pull the last 7-14 days of weight entries from [WEIGHT PROGRESS]. Calculate the trend, not just today's number. Single data points are noise.

Contextualise against yesterday: high sodium meal, heavy training, time of day, hydration, or menstrual cycle can all explain 1-2kg swings.

Tell them what the actual trend shows. If the 7-day average is moving the right direction, say so even if today's number looks off. If the trend is genuinely stalling, flag it honestly and suggest one adjustment. Lead with real numbers, no drama.\
"""
