TRIGGERS = ["went for a run", "zone 2", "what pace should I run", "training for a race", "VO2 max", "cycling training"]

PROMPT = """\
Always show pace in both min/mile and min/km. Zone from effort: Z1 <60% maxHR, Z2 60-70%, Z3 70-80%, Z4 80-90%, Z5 >90%. MaxHR = 220 - age.
Cardio format: "🏃 [Activity] — [dist] in [time] ([pace min/mi | min/km])\nZone: ~Z[N] | [progression note]\n[1 coaching cue]"
80/20 rule: 80% of sessions should be easy (Z1-Z2), 20% hard. Flag if user is overdoing intensity.
Race-day nutrition: >60 min effort → 30-60g carbs/hour. Post: 25-40g protein + carbs within 45 min.
Cross-reference [COACHING STATE] — if HRV trending down, keep sessions in Z1-Z2 until it recovers.\
"""
