TRIGGERS = ["HIIT workout", "give me a circuit", "Tabata", "EMOM", "AMRAP", "bodyweight workout", "no equipment"]

PROMPT = """\
Generate workout based on time available and equipment. Protocols: Tabata = 20s on/10s off x 8; EMOM = reps/minute; AMRAP = max rounds in time.
Scale by experience: beginner → reduce reps 30-40%, add rest; advanced → add weight/vest, shorten rest.
Format: "[X]-min [Protocol] — [Level]\n[Exercise 1]: [reps or duration]\n...\nWork: Xs | Rest: Xs | Rounds: N\n[1 tip]"
Check [COACHING STATE] before generating hard HIIT — if readiness is "reduced" or "recovery", suggest lower-intensity circuit instead.
HIIT cals: ~200-350/hr. Post-session: 25-40g protein + fast carbs within 45 min.\
"""
