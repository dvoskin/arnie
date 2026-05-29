TRIGGERS = ["HIIT workout", "give me a circuit", "Tabata", "EMOM", "AMRAP", "bodyweight workout", "no equipment"]

PROMPT = """\
When generating a workout, always check [COACHING STATE] first — if readiness is "reduced" or \
"recovery", offer a lighter circuit instead of asking, and say why.

Scale by what you know about the user: beginner → reduce reps, extend rest; \
advanced → add load, shorten rest.

Key protocols to know:
- Tabata: 20s on / 10s off x 8 rounds per exercise
- EMOM: complete X reps at the top of every minute
- AMRAP: max rounds in the time window
- Circuit: move through exercises with minimal rest

Cover in your response: the protocol, exercises with reps or time, work/rest breakdown, \
total duration, and one practical tip. Use multi-bubble format — don't dump it all at once. \
Lead with the protocol and vibe, then the workout, then the tip. \
Post-session nutrition: 25-40g protein + fast carbs within 45 min.\
"""
